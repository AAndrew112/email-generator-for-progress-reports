#!/usr/bin/env python3
"""Language-over-time metrics (rates per 1,000 words) by year and by era, split by source."""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import lexicons as L  # noqa: E402
from lib.common import OUT, WORK, read_jsonl, words  # noqa: E402

try:  # optional: pip install vaderSentiment (the lexicon ships inside the package)
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER = SentimentIntensityAnalyzer()
except Exception:  # noqa: BLE001
    VADER = None


def phrase_count(text: str, phrases: set[str]) -> int:
    return sum(len(re.findall(rf"\b{re.escape(p)}\b", text)) for p in phrases)


def metrics(text: str) -> dict[str, float]:
    low = text.lower()
    toks = words(text)
    out: dict[str, float] = {"words": len(toks)}
    for group, ws in L.PRONOUNS.items():
        out[f"pron_{group}"] = sum(t in ws for t in toks)
    for group, ws in L.MODALS.items():
        out[f"modal_{group}"] = phrase_count(low, ws)
    out["certainty"] = sum(t in L.CERTAINTY for t in toks)
    out["hedge"] = phrase_count(low, L.HEDGES)
    out["negation"] = sum(t in L.NEGATIONS for t in toks)
    out["agency_active"] = phrase_count(low, L.AGENCY_ACTIVE)
    out["agency_passive"] = phrase_count(low, L.AGENCY_PASSIVE)
    out["past"] = sum(t in L.PAST for t in toks)
    out["present"] = sum(t in L.PRESENT for t in toks)
    out["filler"] = phrase_count(low, L.FILLERS)
    out["questions"] = text.count("?")
    return out


def main() -> None:
    chunks = list(read_jsonl(WORK / "chunks.jsonl"))
    eras = json.loads((WORK / "eras.json").read_text()) if (WORK / "eras.json").exists() else []

    def era_of(date: str | None) -> str:
        m = (date or "")[:7]
        return next((e["era_id"] for e in eras if e["start"] <= m <= e["end"]), "undated") if len(m) == 7 else "undated"

    agg: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    valence: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for c in chunks:
        m = metrics(c["text"])
        for scheme, label in (("year", (c["date"] or "UNDATED")[:4]), ("era", era_of(c["date"]))):
            key = (scheme, label, c["kind"])
            for k, v in m.items():
                agg[key][k] += v
            if VADER:
                valence[key].append(VADER.polarity_scores(c["text"])["compound"])
    cols = sorted({k for v in agg.values() for k in v if k != "words"})
    with open(WORK / "language_metrics.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["scheme", "period", "source", "words"] + [f"{c}_per_1k" for c in cols] + (["mean_vader"] if VADER else []))
        for key in sorted(agg):
            nw = agg[key]["words"] or 1
            row = [*key, int(nw)] + [round(agg[key][c] / nw * 1000, 2) for c in cols]
            if VADER:
                row.append(round(sum(valence[key]) / len(valence[key]), 3))
            w.writerow(row)
    OUT.mkdir(exist_ok=True)
    (OUT / "11_language_notes.md").write_text(
        "# Language metrics\n\nRates per 1,000 words are in `work/language_metrics.csv` (by year and by era, "
        "journals and spoken messages separately). Limits: word lists miss sarcasm, quotation and slang; "
        "spoken and written text differ in style, so compare within a source, not across; adolescent writing "
        "is developmental. "
        + ("Valence uses VADER." if VADER else "VADER is not installed, so no valence column.") + "\n", encoding="utf-8")
    print(f"{len(agg)} period rows written")


if __name__ == "__main__":
    main()
