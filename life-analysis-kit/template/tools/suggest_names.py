#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. Writes private/name_candidates.csv, the sheet you mark up to say who matters.

Reads raw/archive.json. Lists the capitalised words that look like names (most frequent first) with a
short example, plus three empty columns to fill in: category, same_as, case_sensitive. Then run
tools/build_names.py, which turns your marked rows into private/names_input.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_records, rank_name_like  # noqa: E402

INSTRUCTIONS = [
    "# HOW TO FILL THIS IN (20-30 minutes). Each row below is a capitalised word from your transcripts, most frequent first.",
    "# category: for people/places that matter, type FRIEND, PARTNER, EXPARTNER, CHILD, SIBLING, PARENT, INLAW, FAMILY, COWORKER, PERSON, PET, FICTION (characters in your own stories), WORKPLACE, SCHOOL, CITY or PLACE. Type SUBJECT for your own name. Leave BLANK for everything else (it is still hidden automatically).",
    "# Shortcut: instead of the category column you can type a note in the word cell, like 'Tyler - brother' or 'Holly - close friend, nicknames Holls, Shmolls' or 'York - unknown'. Nicknames become spellings of that person.",
    "# same_as: if this word is another spelling, nickname or surname of someone in another row, type that other row's word here. Leave category blank on it. Example: row Pria -> same_as = Priya.",
    "# case_sensitive: type yes only if the word is also an ordinary word (Hope, Mark, Rose). Otherwise leave blank.",
    "# You can stop when the frequent rows run out of people who matter. Save as CSV, then run: python3 tools/build_names.py",
]
FIELDS = ["word", "count", "documents", "example", "category", "same_as", "case_sensitive"]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=root)
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--top", type=int, default=400)
    args = ap.parse_args()
    private = args.root / "private"
    private.mkdir(exist_ok=True)
    records = load_records(args.root / "raw" / "archive.json")
    cands = [c for c in rank_name_like([r.get("transcript") or "" for r in records]) if c["count"] >= args.min_count]
    with open(private / "name_candidates.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(FIELDS)
        for line in INSTRUCTIONS:
            w.writerow([line])
        for c in cands[: args.top]:
            w.writerow([c["word"], c["count"], c["documents"], c["example"], "", "", ""])
    starter = private / "names_input.csv"
    if not starter.exists():
        starter.write_text("name,category,token,aliases,case_sensitive\n", encoding="utf-8")
    print(f"{min(len(cands), args.top)} candidates written to {private / 'name_candidates.csv'}")
    print("Open it, fill in the category / same_as / case_sensitive columns as the first rows explain, "
          "save as CSV, then run: python3 tools/build_names.py")


if __name__ == "__main__":
    main()
