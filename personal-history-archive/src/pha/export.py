"""Archive export: CSV, JSON, per-record text files and the review queue.

Dates may be partial ISO strings ("1998", "1998-03", "1998-03-04") because a
journal page may only document a month or a year. Records without a verified
date are written to an "undated" section and are never given a made-up date.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .db import Database, effective, now_iso

SCHEMA_FIELDS = [
    "record_id",
    "source_type",
    "date",
    "time",
    "timezone",
    "timestamp_confidence",
    "transcript",
    "source_filename",
    "source_location",
    "page_number",
    "duration",
    "speaker_verification",
    "transcription_status",
    "review_required",
]

_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def is_dated(date: str | None) -> bool:
    return bool(date) and bool(_DATE_RE.match(date))  # type: ignore[arg-type]


def _loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def build_records(db: Database) -> list[dict[str, Any]]:
    open_items = db.review_items(status="open")
    by_record: dict[str, list[dict[str, Any]]] = {}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in open_items:
        entry = {"id": item["id"], "kind": item["kind"], "reason": item["reason"]}
        if item["record_id"]:
            by_record.setdefault(item["record_id"], []).append(entry)
        elif item["source_id"]:
            by_source.setdefault(item["source_id"], []).append(entry)

    out = []
    for row in db.all_records():
        src = db.get_source(row["source_id"])
        if row["source_type"] == "marco_polo" and src["ownership"] != "owner":
            # Only videos verified as mine belong in the archive.
            continue
        eff = effective(row)
        reviews = by_record.get(row["record_id"], []) + by_source.get(row["source_id"], [])
        rec = {
            "record_id": row["record_id"],
            "source_type": row["source_type"],
            "date": eff["date"] if is_dated(eff["date"]) else None,
            "time": eff["time"] or None,
            "timezone": eff["timezone"] or None,
            "timestamp_confidence": eff["timestamp_confidence"]
            if is_dated(eff["date"])
            else "unknown",
            "transcript": eff["transcript"] or "",
            "source_filename": row["source_filename"],
            "source_location": row["source_location"],
            "page_number": row["page_number"],
            "duration": row["duration"],
            "speaker_verification": row["speaker_verification"],
            "transcription_status": row["transcription_status"],
            "review_required": bool(reviews),
            # full metadata (JSON export only)
            "metadata": {
                "source_id": row["source_id"],
                "file_sha256": src["sha256"],
                "entry_index": row["entry_index"],
                "page_end": row["page_end"],
                "timestamp_utc": row["timestamp_utc"],
                "timestamp_evidence": _loads(row["timestamp_evidence"]),
                "machine": {
                    "date": row["machine_date"],
                    "time": row["machine_time"],
                    "timezone": row["machine_timezone"],
                    "timestamp_confidence": row["machine_confidence"],
                    "transcript": row["raw_transcript"],
                },
                "corrected": {
                    "date": row["corrected_date"],
                    "time": row["corrected_time"],
                    "timezone": row["corrected_timezone"],
                    "timestamp_confidence": row["corrected_confidence"],
                    "transcript": row["corrected_transcript"],
                },
                "transcript_detail": _loads(row["transcript_detail"]),
                "all_source_locations": db.source_locations(row["source_id"]),
                "deleted_originals": [
                    {"location": d["location"], "deleted_at": d["deleted_at"], "reason": d["reason"]}
                    for d in db.deleted_files(row["source_id"])
                ],
                "approved_at": row["approved_at"],
                "open_review_items": reviews,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        }
        out.append(rec)
    return sort_chronologically(out)


def sort_chronologically(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(r: dict[str, Any]) -> tuple:
        utc = r["metadata"]["timestamp_utc"] if "metadata" in r else None
        return (
            0 if r["date"] else 1,
            r["date"] or "",
            r["time"] or "",
            utc or "",
            r["source_filename"] or "",
            r.get("page_number") or 0,
            r["record_id"],
        )

    return sorted(records, key=key)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:80]


def transcript_path(root: Path, rec: dict[str, Any]) -> Path:
    stem_bits = []
    if rec["date"]:
        parts = rec["date"].split("-")
        year = parts[0]
        month = parts[1] if len(parts) > 1 else "unknown-month"
        folder = root / year / month
        stem_bits.append(rec["date"])
        if rec["time"]:
            stem_bits.append(rec["time"].replace(":", "")[:4])
    else:
        folder = root / "undated"
    stem_bits += [rec["source_type"], _safe(rec["record_id"])]
    return folder / ("_".join(stem_bits) + ".txt")


def render_transcript_file(rec: dict[str, Any]) -> str:
    lines = [
        f"record_id: {rec['record_id']}",
        f"source_type: {rec['source_type']}",
        f"date: {rec['date'] or 'UNDATED'}",
        f"time: {rec['time'] or 'unknown'}",
        f"timezone: {rec['timezone'] or 'unknown'}",
        f"timestamp_confidence: {rec['timestamp_confidence']}",
        f"source_filename: {rec['source_filename']}",
        f"source_location: {rec['source_location']}",
    ]
    if rec["page_number"] is not None:
        lines.append(f"page_number: {rec['page_number']}")
    if rec["duration"] is not None:
        lines.append(f"duration_seconds: {rec['duration']:.2f}")
    if rec["speaker_verification"]:
        lines.append(f"speaker_verification: {rec['speaker_verification']}")
    lines += [
        f"transcription_status: {rec['transcription_status']}",
        f"review_required: {'yes' if rec['review_required'] else 'no'}",
        "",
        "-" * 60,
        "",
        rec["transcript"],
        "",
    ]
    return "\n".join(lines)


def export_archive(db: Database, export_dir: Path) -> dict[str, Any]:
    """Regenerate the export directory atomically and return a summary."""
    export_dir = Path(export_dir)
    tmp = export_dir.with_name(export_dir.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    records = build_records(db)

    with open(tmp / "archive.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCHEMA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            row["review_required"] = "yes" if rec["review_required"] else "no"
            row["date"] = rec["date"] or "UNDATED"
            writer.writerow(row)

    dated = [r for r in records if r["date"]]
    undated = [r for r in records if not r["date"]]
    with open(tmp / "archive.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "exported_at": now_iso(),
                "schema": SCHEMA_FIELDS,
                "counts": {"total": len(records), "dated": len(dated), "undated": len(undated)},
                "records": dated,
                "undated_records": undated,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    troot = tmp / "transcripts"
    for rec in records:
        path = transcript_path(troot, rec)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_transcript_file(rec), encoding="utf-8")

    queue = export_review_queue(db)
    with open(tmp / "review_queue.json", "w", encoding="utf-8") as fh:
        json.dump(queue, fh, ensure_ascii=False, indent=2)
    with open(tmp / "review_queue.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["id", "kind", "reason", "record_id", "source_id", "source_filename",
                "source_location", "created_at", "details"]
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for item in queue:
            writer.writerow({**item, "details": json.dumps(item["details"], ensure_ascii=False)})

    old = export_dir.with_name(export_dir.name + ".old")
    if old.exists():
        shutil.rmtree(old)
    if export_dir.exists():
        export_dir.rename(old)
    tmp.rename(export_dir)
    if old.exists():
        shutil.rmtree(old)

    return {
        "records": len(records),
        "dated": len(dated),
        "undated": len(undated),
        "review_items": len(queue),
        "export_dir": str(export_dir),
    }


def export_review_queue(db: Database) -> list[dict[str, Any]]:
    out = []
    for item in db.review_items(status="open"):
        src = db.get_source(item["source_id"]) if item["source_id"] else None
        rec = db.get_record(item["record_id"]) if item["record_id"] else None
        out.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "reason": item["reason"],
                "record_id": item["record_id"],
                "source_id": item["source_id"],
                "source_filename": rec["source_filename"] if rec else (src["filename"] if src else None),
                "source_location": rec["source_location"] if rec else (src["location"] if src else None),
                "created_at": item["created_at"],
                "details": _loads(item["details"]),
            }
        )
    return out
