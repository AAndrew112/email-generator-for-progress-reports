#!/usr/bin/env python3
"""Phase 0 manifest from the pseudonymized documents (counts and structure only)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date as Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, est_tokens, read_jsonl  # noqa: E402


def main() -> None:
    docs = list(read_jsonl(WORK / "docs_pseudo.jsonl"))
    OUT.mkdir(exist_ok=True)
    by_kind: dict[str, dict] = defaultdict(lambda: {"docs": 0, "words": 0})
    year: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    prec, conf = Counter(), Counter()
    seen: dict[str, str] = {}
    exact_dupes = 0
    short = illegible_docs = lowconf_docs = 0
    day_dates = []
    for d in docs:
        nw = len(d["text"].split())
        k = by_kind[d["kind"]]; k["docs"] += 1; k["words"] += nw
        y = (d["date"] or "UNDATED")[:4]
        year[(d["kind"], y)][0] += 1; year[(d["kind"], y)][1] += nw
        prec[(d["kind"], d["date_precision"] or "undated")] += 1
        conf[(d["kind"], d["date_confidence"] or "unknown")] += 1
        h = hashlib.sha1(re.sub(r"\W+", " ", d["text"].lower()).strip().encode()).hexdigest()
        if h in seen: exact_dupes += 1
        seen[h] = d["doc_id"]
        short += nw < 5
        q = d["quality"]
        illegible_docs += (q.get("illegible_markers") or 0) > 0
        lowconf_docs += (q.get("low_confidence_fraction") or 0) > 0.2
        if d["date_precision"] == "day":
            day_dates.append(Date.fromisoformat(d["date"]))
    day_dates.sort()
    gaps = [(a.isoformat(), b.isoformat(), (b - a).days) for a, b in zip(day_dates, day_dates[1:]) if (b - a).days > 30]
    total_words = sum(v["words"] for v in by_kind.values())
    manifest = {
        "documents": len(docs), "words": total_words, "tokens_est": est_tokens(total_words),
        "by_kind": by_kind, "date_precision": {f"{k}/{p}": n for (k, p), n in prec.items()},
        "date_confidence": {f"{k}/{c}": n for (k, c), n in conf.items()},
        "first_day": day_dates[0].isoformat() if day_dates else None,
        "last_day": day_dates[-1].isoformat() if day_dates else None,
        "gaps_over_30_days": gaps, "exact_duplicate_documents": exact_dupes,
        "documents_under_5_words": short, "journal_docs_with_illegible_markers": illegible_docs,
        "docs_with_over_20pct_low_confidence_speech": lowconf_docs,
    }
    (WORK / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    lines = ["# Manifest (Phase 0)", "", f"- Documents: {len(docs)}; words: {total_words:,}; "
             f"estimated tokens: {est_tokens(total_words):,}",
             f"- Dated days: {manifest['first_day']} to {manifest['last_day']}", "",
             "| Source | Documents | Words |", "|---|---|---|"]
    lines += [f"| {k} | {v['docs']} | {v['words']:,} |" for k, v in sorted(by_kind.items())]
    lines += ["", "## By year", "", "| Source | Year | Documents | Words |", "|---|---|---|---|"]
    lines += [f"| {k} | {y} | {n} | {w:,} |" for (k, y), (n, w) in sorted(year.items())]
    lines += ["", "## Date quality", ""]
    lines += [f"- {k}: {n}" for k, n in sorted(manifest["date_precision"].items())]
    lines += [f"- confidence {k}: {n}" for k, n in sorted(manifest["date_confidence"].items())]
    lines += ["", "## Gaps over 30 days between dated documents", ""]
    lines += [f"- {a} to {b} ({n} days)" for a, b, n in gaps] or ["- none"]
    lines += ["", "## Data-quality flags", "",
              f"- exact duplicate documents: {exact_dupes}", f"- documents under 5 words: {short}",
              f"- journal documents with illegible markers: {illegible_docs}",
              f"- spoken documents with over 20% low-confidence speech: {lowconf_docs}",
              "- speaker attribution: every spoken document is the subject alone (other people's "
              "videos were excluded at the source), so no conversational partner text exists.",
              "- journal pages over-represent distress and early journals are adolescent writing "
              "(see source criticism)."]
    (OUT / "01_manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("documents", "words", "tokens_est")}))


if __name__ == "__main__":
    main()
