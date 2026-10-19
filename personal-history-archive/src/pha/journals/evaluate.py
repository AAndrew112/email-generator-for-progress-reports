"""Measure handwriting-recognition accuracy against hand-checked pages.

Put ground-truth files in a folder, named ``<pdf filename stem>__p<page>.txt``
(e.g. ``1998 journal__p3.txt``), each containing exactly what is written on
that page. The report gives character and word error rates per page, both
strict (case and punctuation count, because spelling must be preserved) and
relaxed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..db import Database

_TRUTH_RE = re.compile(r"^(?P<stem>.+)__p(?P<page>\d+)\.txt$")
_MARKUP_RE = re.compile(r"\[(?:illegible[^\]]*|crossed out[^\]]*|drawing[^\]]*|blank page)\]|^=== ENTRY ===$", re.M)
_UNSURE_RE = re.compile(r"\[\?([^\]]*?)\?\]")


def levenshtein(a: list[str] | str, b: list[str] | str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def machine_text_for_scoring(text: str) -> str:
    """Drop markup; keep the model's best guess inside [?word?]."""
    return _norm(_MARKUP_RE.sub(" ", _UNSURE_RE.sub(r"\1", text)))


def _relaxed(text: str) -> str:
    return _norm(re.sub(r"[^\w\s]", "", text.lower()))


def score_pair(truth: str, machine: str) -> dict[str, Any]:
    t, m = _norm(truth), machine_text_for_scoring(machine)
    tr, mr = _relaxed(t), _relaxed(m)
    tw, mw = t.split(), m.split()
    return {
        "cer": round(levenshtein(t, m) / max(1, len(t)), 4),
        "wer": round(levenshtein(tw, mw) / max(1, len(tw)), 4),
        "cer_relaxed": round(levenshtein(tr, mr) / max(1, len(tr)), 4),
        "wer_relaxed": round(levenshtein(tr.split(), mr.split()) / max(1, len(tr.split())), 4),
        "truth_chars": len(t),
        "illegible_markers": machine.count("[illegible"),
        "unsure_markers": len(_UNSURE_RE.findall(machine)),
    }


def evaluate(db: Database, truth_dir: Path) -> dict[str, Any]:
    pages = []
    missing = []
    for f in sorted(truth_dir.glob("*.txt")):
        m = _TRUTH_RE.match(f.name)
        if not m:
            missing.append(f"{f.name}: name must look like '<pdf stem>__p<page>.txt'")
            continue
        stem, page = m.group("stem"), int(m.group("page"))
        row = db.conn.execute(
            "SELECT p.raw_text, p.backend, p.model, s.filename, s.location FROM journal_pages p"
            " JOIN sources s ON s.source_id = p.source_id"
            " WHERE p.page_number = ? AND p.status = 'done' AND s.filename LIKE ?",
            (page, stem + ".%"),
        ).fetchone()
        if row is None:
            missing.append(f"{f.name}: no transcribed page {page} of a PDF named '{stem}'")
            continue
        result = score_pair(f.read_text(encoding="utf-8"), row["raw_text"] or "")
        pages.append({"file": row["filename"], "page": page, "backend": f"{row['backend']}/{row['model']}", **result})

    summary: dict[str, Any] = {"pages_scored": len(pages), "problems": missing, "pages": pages}
    if pages:
        total = sum(p["truth_chars"] for p in pages)
        summary["weighted_cer"] = round(sum(p["cer"] * p["truth_chars"] for p in pages) / total, 4)
        summary["weighted_cer_relaxed"] = round(
            sum(p["cer_relaxed"] * p["truth_chars"] for p in pages) / total, 4
        )
        summary["mean_wer"] = round(sum(p["wer"] for p in pages) / len(pages), 4)
    return summary
