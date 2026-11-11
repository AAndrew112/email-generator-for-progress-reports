"""Shared helpers for the analysis scripts.

These scripts read only ``work/`` (pseudonymized data) and write to ``work/``
or ``out/``. They never touch ``raw/`` or the operator's key folder.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(os.environ.get("LIFE_ANALYSIS_ROOT") or Path(__file__).resolve().parents[3])
WORK = ROOT / "work"
OUT = ROOT / "out"

TOKEN_RE = re.compile(r"\[[A-Z][A-Z_]*(?:_?\d+)?\]")
MARKER_RE = re.compile(r"\[(?:illegible[^\]]*|\?[^\]]*\?|crossed out[^\]]*|drawing[^\]]*)\]", re.I)
WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
TOKENS_PER_WORD = 1.35  # rough English estimate; the budget script reports it as an estimate


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def words(text: str) -> list[str]:
    """Lower-case word tokens with entity tokens and transcription markers removed."""
    text = MARKER_RE.sub(" ", TOKEN_RE.sub(" ", text))
    return WORD_RE.findall(text.lower())


def month_key(date: str | None) -> str | None:
    """'YYYY-MM' for day- and month-precision dates; None for year-only or undated."""
    if date and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", date):
        return date[:7]
    return None


def est_tokens(n_words: int) -> int:
    return int(round(n_words * TOKENS_PER_WORD))


def connect_index() -> sqlite3.Connection:
    conn = sqlite3.connect(WORK / "index.sqlite")
    conn.row_factory = sqlite3.Row
    return conn
