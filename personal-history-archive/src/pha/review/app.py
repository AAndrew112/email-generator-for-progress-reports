"""Local review interface.

Runs on 127.0.0.1 only. Lets you look at the original video or page scan
next to the transcript, correct transcripts and dates, decide uncertain
video ownership, resolve review items and re-export the archive. Machine
output is never overwritten: corrections are stored alongside it.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from ..config import Config
from ..db import Database, effective
from ..export import export_archive
from ..marco_polo.pipeline import set_manual_ownership

KINDS = ("speaker", "date", "transcription", "duplicate")


def create_app(cfg: Config, db: Database | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.secret_key = secrets.token_hex(32)
    csrf_token = secrets.token_urlsafe(32)
    database = db or Database(cfg.db_path)

    def get_db() -> Database:
        return database

    @app.context_processor
    def inject() -> dict[str, Any]:
        return {"csrf_token": csrf_token, "kinds": KINDS}

    @app.before_request
    def check_csrf() -> None:
        if request.method == "POST" and request.form.get("csrf_token") != csrf_token:
            abort(403)

    @app.template_filter("fromjson")
    def fromjson(value: str | None) -> Any:
        return json.loads(value) if value else None

    # ----------------------------------------------------------- overview
    @app.get("/")
    def index() -> str:
        d = get_db()
        records = d.all_records()
        eff = [effective(r) for r in records]
        counts = {
            "records": len(records),
            "dated": sum(1 for e in eff if e["date"]),
            "undated": sum(1 for e in eff if not e["date"]),
            "videos": sum(1 for r in records if r["source_type"] == "marco_polo"),
            "journal_entries": sum(1 for r in records if r["source_type"] == "journal"),
        }
        review_counts = {k: len(d.review_items("open", k)) for k in KINDS}
        status_rows = d.conn.execute(
            "SELECT source_type, status, COUNT(*) AS n FROM sources GROUP BY source_type, status"
            " ORDER BY source_type, status"
        ).fetchall()
        failures = d.conn.execute("SELECT * FROM failures ORDER BY id DESC LIMIT 20").fetchall()
        return render_template(
            "index.html", counts=counts, review_counts=review_counts,
            status_rows=status_rows, failures=failures,
        )

    @app.get("/queue")
    def queue() -> str:
        kind = request.args.get("kind") or None
        d = get_db()
        items = []
        for it in d.review_items("open", kind):
            rec = d.get_record(it["record_id"]) if it["record_id"] else None
            src = d.get_source(it["source_id"]) if it["source_id"] else None
            items.append({"item": it, "record": rec, "source": src})
        return render_template("queue.html", items=items, kind=kind)

    @app.get("/records")
    def records() -> str:
        d = get_db()
        show = request.args.get("show", "all")
        rows = []
        for r in d.all_records():
            e = effective(r)
            if show == "undated" and e["date"]:
                continue
            if show == "dated" and not e["date"]:
                continue
            rows.append({"r": r, "e": e, "open": d.open_review_count(r["record_id"])})
        rows.sort(key=lambda x: (x["e"]["date"] is None, x["e"]["date"] or "", x["e"]["time"] or "", x["r"]["record_id"]))
        return render_template("records.html", rows=rows, show=show)

    # ------------------------------------------------------------- record
    @app.get("/record/<record_id>")
    def record(record_id: str) -> str:
        d = get_db()
        r = d.get_record(record_id)
        if r is None:
            abort(404)
        items = [i for i in d.review_items(status=None) if i["record_id"] == record_id]
        corrections = d.conn.execute(
            "SELECT * FROM corrections WHERE record_id = ? ORDER BY id DESC", (record_id,)
        ).fetchall()
        detail = json.loads(r["transcript_detail"] or "{}")
        evidence = json.loads(r["timestamp_evidence"] or "{}")
        return render_template(
            "record.html", r=r, e=effective(r), items=items, corrections=corrections,
            detail=detail, evidence=evidence, locations=d.source_locations(r["source_id"]),
        )

    @app.post("/record/<record_id>/correct")
    def correct(record_id: str) -> Any:
        d = get_db()
        if d.get_record(record_id) is None:
            abort(404)
        note = request.form.get("note") or None
        for field in ("date", "time", "timezone", "timestamp_confidence", "transcript"):
            if field not in request.form:
                continue
            value = request.form[field]
            if field == "transcript":
                value = value.replace("\r\n", "\n")
            else:
                value = value.strip()
            try:
                d.apply_correction(record_id, field, value, note)
            except ValueError as exc:
                flash(str(exc))
        flash("Saved. The machine transcript is kept unchanged alongside your correction.")
        return redirect(url_for("record", record_id=record_id))

    @app.post("/record/<record_id>/approve")
    def approve(record_id: str) -> Any:
        get_db().approve_record(record_id)
        flash("Record approved; its open review items are resolved.")
        nxt = request.form.get("next")
        return redirect(nxt if nxt and nxt.startswith("/") else url_for("record", record_id=record_id))

    @app.post("/review/<int:item_id>/resolve")
    def resolve(item_id: int) -> Any:
        get_db().resolve_review(item_id, request.form.get("resolution") or "resolved in review UI")
        nxt = request.form.get("next")
        return redirect(nxt if nxt and nxt.startswith("/") else url_for("queue"))

    # ------------------------------------------------------------- source
    @app.get("/source/<source_id>")
    def source(source_id: str) -> str:
        d = get_db()
        s = d.get_source(source_id)
        if s is None:
            abort(404)
        return render_template(
            "source.html", s=s, meta=json.loads(s["metadata_json"] or "{}"),
            detail=json.loads(s["ownership_detail"] or "{}"),
            items=[i for i in d.review_items(status=None) if i["source_id"] == source_id],
            records=d.records_for_source(source_id), locations=d.source_locations(source_id),
        )

    @app.post("/source/<source_id>/ownership")
    def ownership(source_id: str) -> Any:
        d = get_db()
        if d.get_source(source_id) is None:
            abort(404)
        decision = request.form.get("decision", "")
        set_manual_ownership(d, source_id, decision, request.form.get("note", ""))
        flash(
            "Marked as mine. Run 'pha mp process' to transcribe it."
            if decision == "owner"
            else "Marked as someone else's; it will be excluded from the archive."
        )
        return redirect(url_for("source", source_id=source_id))

    # -------------------------------------------------------------- media
    @app.get("/media/source/<source_id>")
    def media_source(source_id: str) -> Any:
        s = get_db().get_source(source_id)
        if s is None or s["source_type"] != "marco_polo":
            abort(404)
        path = Path(s["location"])
        if not path.is_file():
            abort(404)
        return send_file(path, conditional=True)

    @app.get("/media/page/<source_id>/<int:page>")
    def media_page(source_id: str, page: int) -> Any:
        row = get_db().conn.execute(
            "SELECT image_path FROM journal_pages WHERE source_id = ? AND page_number = ?",
            (source_id, page),
        ).fetchone()
        if row is None or not row["image_path"] or not Path(row["image_path"]).is_file():
            abort(404)
        return send_file(row["image_path"], mimetype="image/png", conditional=True)

    # ------------------------------------------------------------- export
    @app.post("/export")
    def export() -> Any:
        summary = export_archive(get_db(), cfg.export_path)
        flash(
            f"Exported {summary['records']} records ({summary['dated']} dated, "
            f"{summary['undated']} undated) and {summary['review_items']} open review items "
            f"to {summary['export_dir']}"
        )
        return redirect(url_for("index"))

    return app


def serve(cfg: Config, port: int = 8765) -> None:
    app = create_app(cfg)
    print(f"Review interface: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=False)
