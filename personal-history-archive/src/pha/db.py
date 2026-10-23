"""SQLite storage: sources, records, review queue, corrections and failures.

Design rules enforced here:
  * Machine output (``raw_transcript`` and the ``machine_*`` timestamp fields)
    is written by the pipelines only. Manual edits go to ``corrected_*``
    columns and are logged in ``corrections``, so both versions survive.
  * Re-running a pipeline never overwrites a manual correction.
  * Source rows act as checkpoints: a source marked ``done`` is skipped.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,          -- marco_polo | journal
    filename        TEXT NOT NULL,
    location        TEXT NOT NULL,          -- local path or Drive link
    sha256          TEXT,
    size_bytes      INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    stage           TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    ownership       TEXT,                   -- owner | other | uncertain
    ownership_detail TEXT,                  -- JSON evidence
    metadata_json   TEXT,
    duplicate_of    TEXT,
    first_seen      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_sha ON sources(sha256);

-- Every location a source has been seen at (repeat imports, copies).
CREATE TABLE IF NOT EXISTS source_locations (
    source_id   TEXT NOT NULL REFERENCES sources(source_id),
    location    TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    PRIMARY KEY (source_id, location)
);

CREATE TABLE IF NOT EXISTS records (
    record_id             TEXT PRIMARY KEY,
    source_id             TEXT NOT NULL REFERENCES sources(source_id),
    source_type           TEXT NOT NULL,
    entry_index           INTEGER NOT NULL DEFAULT 0,
    -- machine-extracted timestamp
    machine_date          TEXT,
    machine_time          TEXT,
    machine_timezone      TEXT,
    machine_confidence    TEXT NOT NULL DEFAULT 'unknown',
    timestamp_utc         TEXT,
    timestamp_evidence    TEXT,             -- JSON
    -- manual corrections (NULL = not corrected)
    corrected_date        TEXT,
    corrected_time        TEXT,
    corrected_timezone    TEXT,
    corrected_confidence  TEXT,
    raw_transcript        TEXT,
    corrected_transcript  TEXT,
    transcript_detail     TEXT,             -- JSON: segments, model, markers
    source_filename       TEXT NOT NULL,
    source_location       TEXT NOT NULL,
    page_number           INTEGER,
    page_end              INTEGER,
    duration              REAL,
    speaker_verification  TEXT,
    transcription_status  TEXT NOT NULL DEFAULT 'pending',
    approved_at           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_source ON records(source_id);

CREATE TABLE IF NOT EXISTS review_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key    TEXT NOT NULL UNIQUE,
    record_id   TEXT,
    source_id   TEXT,
    kind        TEXT NOT NULL,      -- date | speaker | transcription | duplicate | failure
    reason      TEXT NOT NULL,
    details     TEXT,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    resolution  TEXT,
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id   TEXT,
    source_id   TEXT,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    note        TEXT,
    at          TEXT NOT NULL
);

-- Original files deleted on request (marco_polo.delete_after_processing).
CREATE TABLE IF NOT EXISTS deleted_files (
    location    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    sha256      TEXT,
    reason      TEXT NOT NULL,
    deleted_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT,
    stage       TEXT,
    error       TEXT,
    at          TEXT NOT NULL
);

-- Hash cache so unchanged files are not re-read on every run.
CREATE TABLE IF NOT EXISTS file_index (
    path        TEXT PRIMARY KEY,
    size_bytes  INTEGER NOT NULL,
    mtime_ns    INTEGER NOT NULL,
    sha256      TEXT NOT NULL
);

-- Page-level checkpoints for journal PDFs.
CREATE TABLE IF NOT EXISTS journal_pages (
    source_id   TEXT NOT NULL REFERENCES sources(source_id),
    page_number INTEGER NOT NULL,
    image_path  TEXT,
    phash       TEXT,
    ink_ratio   REAL,
    raw_text    TEXT,
    backend     TEXT,
    model       TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | done | manual_needed | failed
    error       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (source_id, page_number)
);
"""

TIMESTAMP_CONFIDENCE = ("exact", "inferred", "unknown")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Database:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ sources
    def get_source(self, source_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sources WHERE source_id = ?", (source_id,)
        ).fetchone()

    def find_source_by_sha(self, sha256: str, source_type: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM sources WHERE sha256 = ? AND source_type = ? "
            "ORDER BY first_seen LIMIT 1",
            (sha256, source_type),
        ).fetchone()

    def upsert_source(
        self,
        source_id: str,
        source_type: str,
        filename: str,
        location: str,
        sha256: str | None,
        size_bytes: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Insert a source if new; always record the location. Returns True if new."""
        ts = now_iso()
        with self.tx() as c:
            existing = self.get_source(source_id)
            if existing is None:
                c.execute(
                    "INSERT INTO sources (source_id, source_type, filename, location, sha256,"
                    " size_bytes, metadata_json, first_seen, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        source_id,
                        source_type,
                        filename,
                        location,
                        sha256,
                        size_bytes,
                        json.dumps(metadata) if metadata is not None else None,
                        ts,
                        ts,
                    ),
                )
            c.execute(
                "INSERT OR IGNORE INTO source_locations (source_id, location, first_seen)"
                " VALUES (?,?,?)",
                (source_id, location, ts),
            )
        return existing is None

    def update_source(self, source_id: str, **values: Any) -> None:
        if not values:
            return
        for key in ("metadata_json", "ownership_detail"):
            if key in values and not isinstance(values[key], (str, type(None))):
                values[key] = json.dumps(values[key], default=str)
        values["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in values)
        with self.tx() as c:
            c.execute(
                f"UPDATE sources SET {cols} WHERE source_id = ?",
                (*values.values(), source_id),
            )

    def source_locations(self, source_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT location FROM source_locations WHERE source_id = ? ORDER BY first_seen",
            (source_id,),
        ).fetchall()
        return [r["location"] for r in rows]

    def sources(self, source_type: str | None = None, status: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM sources WHERE 1=1"
        args: list[Any] = []
        if source_type:
            sql += " AND source_type = ?"
            args.append(source_type)
        if status:
            sql += " AND status = ?"
            args.append(status)
        return self.conn.execute(sql + " ORDER BY first_seen, source_id", args).fetchall()

    def record_deletion(self, source_id: str, location: str, sha256: str | None, reason: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO deleted_files (location, source_id, sha256, reason, deleted_at)"
                " VALUES (?,?,?,?,?)",
                (location, source_id, sha256, reason, now_iso()),
            )

    def deleted_files(self, source_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM deleted_files WHERE source_id = ? ORDER BY deleted_at", (source_id,)
        ).fetchall()

    def log_failure(self, source_id: str | None, stage: str, error: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO failures (source_id, stage, error, at) VALUES (?,?,?,?)",
                (source_id, stage, error, now_iso()),
            )

    def cached_sha256(self, path: Path) -> str:
        from .runtime import sha256_file

        st = path.stat()
        key = str(path.resolve())
        row = self.conn.execute(
            "SELECT * FROM file_index WHERE path = ?", (key,)
        ).fetchone()
        if row and row["size_bytes"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns:
            return row["sha256"]
        digest = sha256_file(path)
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO file_index (path, size_bytes, mtime_ns, sha256)"
                " VALUES (?,?,?,?)",
                (key, st.st_size, st.st_mtime_ns, digest),
            )
        return digest

    # ------------------------------------------------------------------ records
    def get_record(self, record_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM records WHERE record_id = ?", (record_id,)
        ).fetchone()

    def records_for_source(self, source_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM records WHERE source_id = ? ORDER BY entry_index", (source_id,)
        ).fetchall()

    def upsert_machine_record(self, record_id: str, **values: Any) -> None:
        """Write machine output for a record without touching manual corrections."""
        protected = {
            "corrected_date",
            "corrected_time",
            "corrected_timezone",
            "corrected_confidence",
            "corrected_transcript",
            "approved_at",
        }
        bad = protected.intersection(values)
        if bad:
            raise ValueError(f"Pipelines may not write manual fields: {sorted(bad)}")
        for key in ("timestamp_evidence", "transcript_detail"):
            if key in values and not isinstance(values[key], (str, type(None))):
                values[key] = json.dumps(values[key], default=str, ensure_ascii=False)
        ts = now_iso()
        with self.tx() as c:
            if self.get_record(record_id) is None:
                values.setdefault("created_at", ts)
                values["updated_at"] = ts
                cols = ["record_id", *values]
                c.execute(
                    f"INSERT INTO records ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    (record_id, *values.values()),
                )
            else:
                values.pop("created_at", None)
                values["updated_at"] = ts
                sets = ", ".join(f"{k} = ?" for k in values)
                c.execute(
                    f"UPDATE records SET {sets} WHERE record_id = ?",
                    (*values.values(), record_id),
                )

    def delete_machine_records(self, source_id: str, keep: set[str]) -> None:
        """Remove stale machine-only records for a source (never corrected ones)."""
        with self.tx() as c:
            for row in self.records_for_source(source_id):
                if row["record_id"] in keep:
                    continue
                corrected = any(
                    row[k] is not None
                    for k in ("corrected_date", "corrected_time", "corrected_transcript", "approved_at")
                )
                if not corrected:
                    c.execute("DELETE FROM review_items WHERE record_id = ?", (row["record_id"],))
                    c.execute("DELETE FROM records WHERE record_id = ?", (row["record_id"],))

    def apply_correction(
        self, record_id: str, field: str, new_value: Any, note: str | None = None
    ) -> None:
        allowed = {
            "date": "corrected_date",
            "time": "corrected_time",
            "timezone": "corrected_timezone",
            "timestamp_confidence": "corrected_confidence",
            "transcript": "corrected_transcript",
        }
        if field not in allowed:
            raise ValueError(f"Field '{field}' cannot be corrected")
        if field == "timestamp_confidence" and new_value not in (*TIMESTAMP_CONFIDENCE, None):
            raise ValueError(f"timestamp_confidence must be one of {TIMESTAMP_CONFIDENCE}")
        column = allowed[field]
        row = self.get_record(record_id)
        if row is None:
            raise KeyError(record_id)
        old = effective(row)[field]
        if (old or None) == (new_value or None):
            return
        with self.tx() as c:
            c.execute(
                f"UPDATE records SET {column} = ?, updated_at = ? WHERE record_id = ?",
                (new_value, now_iso(), record_id),
            )
            if field == "transcript":
                c.execute(
                    "UPDATE records SET transcription_status = 'corrected' WHERE record_id = ?",
                    (record_id,),
                )
            c.execute(
                "INSERT INTO corrections (record_id, field, old_value, new_value, note, at)"
                " VALUES (?,?,?,?,?,?)",
                (record_id, field, old, new_value, note, now_iso()),
            )

    def approve_record(self, record_id: str) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE records SET approved_at = ?, updated_at = ? WHERE record_id = ?",
                (now_iso(), now_iso(), record_id),
            )
            c.execute(
                "UPDATE review_items SET status = 'resolved', resolution = 'approved',"
                " resolved_at = ? WHERE record_id = ? AND status = 'open'",
                (now_iso(), record_id),
            )

    def all_records(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM records").fetchall()

    # ------------------------------------------------------------------ review
    def add_review(
        self,
        kind: str,
        reason: str,
        record_id: str | None = None,
        source_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Queue a review item. Idempotent: re-queuing an item keeps its status."""
        key = f"{kind}|{record_id or ''}|{source_id or ''}|{reason}"
        with self.tx() as c:
            c.execute(
                "INSERT INTO review_items (item_key, record_id, source_id, kind, reason, details,"
                " created_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(item_key) DO UPDATE SET details = excluded.details",
                (
                    key,
                    record_id,
                    source_id,
                    kind,
                    reason,
                    json.dumps(details, default=str, ensure_ascii=False) if details else None,
                    now_iso(),
                ),
            )

    def resolve_review(self, item_id: int, resolution: str) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE review_items SET status = 'resolved', resolution = ?, resolved_at = ?"
                " WHERE id = ?",
                (resolution, now_iso(), item_id),
            )

    def review_items(self, status: str | None = "open", kind: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM review_items WHERE 1=1"
        args: list[Any] = []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        return self.conn.execute(sql + " ORDER BY id", args).fetchall()

    def open_review_count(self, record_id: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM review_items WHERE record_id = ? AND status = 'open'",
            (record_id,),
        ).fetchone()[0]


def effective(row: sqlite3.Row) -> dict[str, Any]:
    """The shared output view of a record: corrections override machine values."""

    def pick(corrected: str, machine: str) -> Any:
        return row[corrected] if row[corrected] is not None else row[machine]

    return {
        "date": pick("corrected_date", "machine_date"),
        "time": pick("corrected_time", "machine_time"),
        "timezone": pick("corrected_timezone", "machine_timezone"),
        "timestamp_confidence": pick("corrected_confidence", "machine_confidence"),
        "transcript": pick("corrected_transcript", "raw_transcript"),
    }
