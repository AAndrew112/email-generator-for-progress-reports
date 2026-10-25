"""Handwritten journal pipeline.

PDF (Drive or local) -> rendered pages -> vision transcription per page
(checkpointed) -> entries split on written date headings -> records.
Scans are never modified or deleted; duplicates are flagged for review.
"""

from __future__ import annotations

import difflib
import errno
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..db import Database, now_iso
from ..runtime import Progress
from . import drive as gdrive
from .entries import date_entry, split_entries, year_hints
from .render import dhash, hamming, ink_ratio, page_count, render_page
from .vision import BackendUnavailable, VisionBackend, make_backend, uncertainty_markers

log = logging.getLogger("pha.journals")

SOURCE_TYPE = "journal"
MAX_ATTEMPTS = 3
BLANK_INK = 0.004
TRUNCATED_NOTE = "model output hit its length limit; the end of the page may be missing"


class RunAborted(RuntimeError):
    """A problem that would fail every remaining page (disk full, Ollama down)."""


@dataclass
class JournalSource:
    source_id: str
    filename: str
    location: str  # Drive link or local path
    local_pdf: Path
    folder_path: list[str]
    metadata: dict[str, Any]


class JournalPipeline:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        backend_factory: Callable[[], VisionBackend] | None = None,
        drive_service_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self.jc = cfg.journals
        self.db = db
        self._backend_factory = backend_factory or (lambda: make_backend(cfg))
        self._backend: VisionBackend | None = None
        self._drive_factory = drive_service_factory or (
            lambda: gdrive.get_service(
                cfg.path(self.jc.client_secret_file),
                cfg.path(self.jc.token_file) if self.jc.token_file else cfg.data_path / "google_token.json",
            )
        )
        self.pdf_cache = cfg.cache_path / "journals" / "pdf"
        self.page_cache = cfg.cache_path / "journals" / "pages"

    @property
    def backend(self) -> VisionBackend:
        if self._backend is None:
            self._backend = self._backend_factory()
        return self._backend

    # ------------------------------------------------------------ discovery
    def drive_sources(self) -> list[JournalSource]:
        service = self._drive_factory()
        if self.jc.drive_folder_id:
            roots = [{"id": self.jc.drive_folder_id, "name": self.jc.drive_folder_name}]
        else:
            roots = gdrive.find_folders(service, self.jc.drive_folder_name)
            if not roots:
                raise RuntimeError(f"No Drive folder named '{self.jc.drive_folder_name}' found")
            if len(roots) > 1:
                ids = ", ".join(r["id"] for r in roots)
                raise RuntimeError(
                    f"Several Drive folders are named '{self.jc.drive_folder_name}' ({ids}); "
                    "set journals.drive_folder_id to choose one."
                )
        out = []
        for root in roots:
            for f in gdrive.walk_pdfs(service, root["id"], [root["name"]]):
                local = self.pdf_cache / f"{f.id}.pdf"
                meta_file = local.with_suffix(".json")
                previous = json.loads(meta_file.read_text()) if meta_file.exists() else {}
                if not local.exists() or (f.md5 and previous.get("md5") != f.md5):
                    log.info("Downloading %s", f.display_path)
                    try:
                        gdrive.download(service, f.id, local)
                    except Exception as exc:
                        log.exception("Download failed: %s", f.display_path)
                        self.db.log_failure(f"jr-{f.id}", "download", f"{f.display_path}: {exc}")
                        continue
                    meta_file.write_text(json.dumps({"md5": f.md5}))
                out.append(
                    JournalSource(
                        source_id=f"jr-{f.id}",
                        filename=f.name,
                        location=f.web_view_link,
                        local_pdf=local,
                        folder_path=f.folder_path,
                        metadata={
                            "drive_file_id": f.id,
                            "drive_path": f.display_path,
                            "drive_md5": f.md5,
                            "drive_created_time": f.created_time,
                            "drive_modified_time": f.modified_time,
                            "note": "Drive created/modified times are upload times, never journal dates",
                        },
                    )
                )
        return sorted(out, key=lambda s: (s.folder_path, s.filename))

    def local_sources(self) -> list[JournalSource]:
        root = self.cfg.path(self.jc.local_pdf_dir)
        if not self.jc.local_pdf_dir or not root.exists():
            raise RuntimeError(f"Local journal folder not found: {root}")
        out = []
        for pdf in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"):
            sha = self.db.cached_sha256(pdf)
            rel = pdf.relative_to(root)
            out.append(
                JournalSource(
                    source_id=f"jr-{sha[:16]}",
                    filename=pdf.name,
                    location=str(pdf.resolve()),
                    local_pdf=pdf,
                    folder_path=[root.name, *rel.parts[:-1]],
                    metadata={"local_path": str(pdf.resolve())},
                )
            )
        return out

    # ------------------------------------------------------------------ run
    def run(self, source: str = "drive", retry_failed: bool = False, force: bool = False, limit: int | None = None) -> Progress:
        sources = self.drive_sources() if source == "drive" else self.local_sources()
        if limit:
            sources = sources[:limit]
        progress = Progress(len(sources), "journals")
        for js in sources:
            try:
                outcome = self._process(js, retry_failed, force)
            except RunAborted as exc:
                progress.step(js.filename, "stopped")
                log.error("Run stopped: %s", exc)
                log.error("Fix that, then run the same command again; finished pages are kept.")
                raise
            except Exception as exc:
                log.exception("Failed on %s", js.filename)
                self.db.log_failure(js.source_id, "journal", str(exc))
                outcome = f"failed: {exc}"
            progress.step(js.filename, outcome)
        self.flag_duplicate_pages()
        log.info(progress.summary())
        return progress

    def _process(self, js: JournalSource, retry_failed: bool, force: bool) -> str:
        sha = self.db.cached_sha256(js.local_pdf)
        meta = {**js.metadata, "folder_path": js.folder_path, "sha256": sha}
        is_new = self.db.upsert_source(
            js.source_id, SOURCE_TYPE, js.filename, js.location, sha, js.local_pdf.stat().st_size, meta
        )
        src = self.db.get_source(js.source_id)
        if not is_new and src["sha256"] != sha:
            # The scan was replaced in Drive: re-read pages, keep manual corrections.
            log.info("%s changed since last run; re-processing", js.filename)
            with self.db.tx() as c:
                c.execute("DELETE FROM journal_pages WHERE source_id = ?", (js.source_id,))
            self.db.update_source(js.source_id, sha256=sha, status="pending", attempts=0, metadata_json=meta)
            src = self.db.get_source(js.source_id)

        twin = self.db.find_source_by_sha(sha, SOURCE_TYPE)
        if twin is not None and twin["source_id"] != js.source_id:
            self.db.update_source(js.source_id, status="duplicate", duplicate_of=twin["source_id"])
            self.db.add_review(
                "duplicate", f"identical file to {twin['filename']}", source_id=js.source_id,
                details={"duplicate_of": twin["source_id"], "location": twin["location"]},
            )
            return f"duplicate of {twin['filename']} (not re-transcribed)"

        if src["status"] == "done" and not force:
            return "already done"
        if src["status"] == "failed" and src["attempts"] >= MAX_ATTEMPTS and not retry_failed:
            return f"skipped (failed {src['attempts']}x; use --retry-failed)"
        self.db.update_source(js.source_id, status="in_progress", attempts=src["attempts"] + 1)

        n_pages = page_count(js.local_pdf)
        failed = 0
        for p in range(1, n_pages + 1):
            started = time.monotonic()
            try:
                try:
                    outcome = self._page(js, p, force)
                except BackendUnavailable as exc:
                    raise RunAborted(str(exc)) from exc
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise RunAborted(
                            "The disk is full. Free some space (see README), then run again."
                        ) from exc
                    raise
                if outcome != "already done":
                    log.info(
                        "  %s page %d/%d: %s (%.0fs)",
                        js.filename, p, n_pages, outcome, time.monotonic() - started,
                    )
            except RunAborted:
                self.db.update_source(js.source_id, status="pending", attempts=0)
                raise
            except Exception as exc:
                failed += 1
                log.exception("Page %d of %s failed", p, js.filename)
                self._set_page(js.source_id, p, status="failed", error=str(exc)[:2000])
                self.db.log_failure(js.source_id, f"page {p}", str(exc))

        n_records = self.build_records(js.source_id)
        if failed:
            self.db.update_source(js.source_id, status="failed", last_error=f"{failed} page(s) failed")
            return f"{n_pages - failed}/{n_pages} pages transcribed, {n_records} entries (will retry failed pages)"
        self.db.update_source(js.source_id, status="done", last_error=None)
        return f"{n_pages} pages, {n_records} entries"

    def _set_page(self, source_id: str, page: int, **values: Any) -> None:
        values["updated_at"] = now_iso()
        cols = ", ".join(values)
        with self.db.tx() as c:
            c.execute(
                f"INSERT INTO journal_pages (source_id, page_number, {cols}) VALUES (?, ?, {', '.join('?' * len(values))})"
                f" ON CONFLICT(source_id, page_number) DO UPDATE SET "
                + ", ".join(f"{k} = excluded.{k}" for k in values),
                (source_id, page, *values.values()),
            )

    def _page(self, js: JournalSource, page: int, force: bool) -> str:
        row = self.db.conn.execute(
            "SELECT * FROM journal_pages WHERE source_id = ? AND page_number = ?", (js.source_id, page)
        ).fetchone()
        if row and row["status"] == "done" and not force:
            return "already done"
        img = render_page(js.local_pdf, page, self.page_cache / js.source_id / f"p{page:04d}.jpg", self.jc.render_dpi)
        ink = ink_ratio(img)
        self._set_page(js.source_id, page, image_path=str(img), phash=dhash(img), ink_ratio=ink)
        if ink < BLANK_INK:
            self._set_page(js.source_id, page, raw_text="[blank page]", backend="ink-check", model="", status="done", error=None)
            return "blank page"
        result = self.backend.transcribe(img)
        if result is None:
            self._set_page(js.source_id, page, status="manual_needed", backend=self.backend.name, error=None)
            return "needs manual transcription"
        self._set_page(
            js.source_id, page, raw_text=result.text, backend=result.backend, model=result.model,
            status="done", error=TRUNCATED_NOTE if result.truncated else None,
        )
        outcome = f"transcribed ({len(result.text.split())} words)"
        return outcome + ", may be cut off" if result.truncated else outcome

    # ------------------------------------------------------------- records
    def build_records(self, source_id: str) -> int:
        src = self.db.get_source(source_id)
        meta = json.loads(src["metadata_json"] or "{}")
        hints = year_hints(*meta.get("folder_path", []), src["filename"])
        pages = self.db.conn.execute(
            "SELECT * FROM journal_pages WHERE source_id = ? ORDER BY page_number", (source_id,)
        ).fetchall()

        keep: set[str] = set()
        # Machine-transcribed pages are split into entries across page breaks.
        done = [(p["page_number"], p["raw_text"] or "") for p in pages if p["status"] == "done"]
        per_page_count: dict[int, int] = {}
        for entry in split_entries(done, self.jc.date_order):
            k = per_page_count.get(entry.start_page, 0)
            per_page_count[entry.start_page] = k + 1
            record_id = f"{source_id}-p{entry.start_page:04d}-{k:02d}"
            keep.add(record_id)
            dated = date_entry(
                entry, self.jc.date_order, hints,
                src["filename"] if self.jc.date_undated_from_filename else None,
            )
            backend_rows = [p for p in pages if entry.start_page <= p["page_number"] <= entry.end_page]
            markers = uncertainty_markers(entry.text)
            self.db.upsert_machine_record(
                record_id,
                source_id=source_id,
                source_type=SOURCE_TYPE,
                entry_index=len(keep) - 1,
                machine_date=dated["date"],
                machine_time=dated["time"],
                machine_timezone=None,
                machine_confidence=dated["confidence"],
                timestamp_evidence=dated["evidence"],
                raw_transcript=entry.text,
                transcript_detail={
                    "pages": list(range(entry.start_page, entry.end_page + 1)),
                    "backends": sorted({f"{p['backend']}/{p['model']}" for p in backend_rows}),
                    "uncertainty_markers": markers,
                    "page_images": [p["image_path"] for p in backend_rows],
                },
                source_filename=src["filename"],
                source_location=src["location"],
                page_number=entry.start_page,
                page_end=entry.end_page,
                transcription_status="machine",
            )
            for reason in dated["review"]:
                self.db.add_review("date", reason, record_id=record_id, details=dated["evidence"])
            self.db.resolve_stale_reviews(record_id, "date", dated["review"], "no longer applies after re-dating")
            if markers:
                self.db.add_review(
                    "transcription",
                    f"{len(markers)} illegible/uncertain passage(s) marked",
                    record_id=record_id,
                    details={"markers": markers},
                )
            cut = [p["page_number"] for p in backend_rows if p["error"] == TRUNCATED_NOTE]
            if cut:
                self.db.add_review(
                    "transcription",
                    "transcription may be cut off before the end of the page",
                    record_id=record_id,
                    details={"pages": cut},
                )

        # Pages awaiting a human transcription become one record each.
        for p in pages:
            if p["status"] != "manual_needed":
                continue
            record_id = f"{source_id}-p{p['page_number']:04d}-manual"
            keep.add(record_id)
            self.db.upsert_machine_record(
                record_id,
                source_id=source_id,
                source_type=SOURCE_TYPE,
                entry_index=len(keep) - 1,
                machine_confidence="unknown",
                timestamp_evidence={"folder_year_hints": hints},
                raw_transcript=None,
                transcript_detail={"pages": [p["page_number"]], "page_images": [p["image_path"]]},
                source_filename=src["filename"],
                source_location=src["location"],
                page_number=p["page_number"],
                page_end=p["page_number"],
                transcription_status="manual_needed",
            )
            self.db.add_review("transcription", "page needs manual transcription", record_id=record_id)

        self.db.delete_machine_records(source_id, keep)
        return len(keep)

    def redate(self) -> dict[str, int]:
        """Rebuild entries and dates from pages already transcribed (no recognition runs)."""
        sources = self.db.conn.execute(
            "SELECT DISTINCT p.source_id FROM journal_pages p JOIN sources s ON s.source_id = p.source_id"
            " WHERE s.status != 'duplicate'"
        ).fetchall()
        entries = sum(self.build_records(row["source_id"]) for row in sources)
        counts = self.db.conn.execute(
            "SELECT SUM(COALESCE(corrected_date, machine_date) IS NOT NULL) AS dated,"
            " SUM(COALESCE(corrected_date, machine_date) IS NULL) AS undated,"
            " SUM(timestamp_evidence LIKE '%taken from the PDF name%' AND corrected_date IS NULL) AS from_name"
            " FROM records WHERE source_type = ?",
            (SOURCE_TYPE,),
        ).fetchone()
        return {"pdfs": len(sources), "entries": entries, **{k: counts[k] or 0 for k in counts.keys()}}

    # ---------------------------------------------------------- duplicates
    def flag_duplicate_pages(self) -> int:
        """Flag pages that look like the same scan (overlapping PDFs)."""
        rows = self.db.conn.execute(
            "SELECT p.* FROM journal_pages p JOIN sources s ON s.source_id = p.source_id"
            " WHERE p.phash IS NOT NULL AND p.ink_ratio >= ? AND s.status != 'duplicate'",
            (BLANK_INK,),
        ).fetchall()
        flagged = 0
        hashes = [(r, int(r["phash"], 16)) for r in rows]
        for i in range(len(hashes)):
            a, ha = hashes[i]
            for j in range(i + 1, len(hashes)):
                b, hb = hashes[j]
                if bin(ha ^ hb).count("1") > self.jc.duplicate_page_distance:
                    continue
                text_sim = None
                if a["raw_text"] and b["raw_text"]:
                    text_sim = difflib.SequenceMatcher(None, a["raw_text"], b["raw_text"]).ratio()
                    if text_sim < 0.6:
                        continue  # similar layout, different writing
                flagged += 1
                for here, there in ((a, b), (b, a)):
                    rec = self._record_for_page(here["source_id"], here["page_number"])
                    other = self.db.get_source(there["source_id"])
                    self.db.add_review(
                        "duplicate",
                        f"page {here['page_number']} looks like page {there['page_number']} of {other['filename']}",
                        record_id=rec,
                        source_id=None if rec else here["source_id"],
                        details={
                            "other_source_id": there["source_id"],
                            "other_page": there["page_number"],
                            "hash_distance": hamming(a["phash"], b["phash"]),
                            "text_similarity": round(text_sim, 3) if text_sim is not None else None,
                        },
                    )
        return flagged

    def _record_for_page(self, source_id: str, page: int) -> str | None:
        row = self.db.conn.execute(
            "SELECT record_id FROM records WHERE source_id = ? AND page_number <= ? AND page_end >= ?"
            " ORDER BY page_number LIMIT 1",
            (source_id, page, page),
        ).fetchone()
        return row["record_id"] if row else None
