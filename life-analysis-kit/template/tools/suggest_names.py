#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. Suggests names to put in private/names_input.csv.

Reads raw/archive.json, writes private/name_candidates.csv (most frequent capitalised words
that are not at the start of a sentence, with a short example) and, if missing, a starter
private/names_input.csv. Review the candidates, add real people/places to names_input.csv
with spelling variants (the speech recogniser often misspells names), then run pseudonymize.py.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_records, scan_candidates  # noqa: E402


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=root)
    ap.add_argument("--min-count", type=int, default=2)
    args = ap.parse_args()
    private = args.root / "private"
    private.mkdir(exist_ok=True)
    records = load_records(args.root / "raw" / "archive.json")
    cands = [c for c in scan_candidates([r.get("transcript") or "" for r in records])
             if c["count"] >= args.min_count]
    with open(private / "name_candidates.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["word", "count", "documents", "example"])
        w.writeheader()
        w.writerows(cands)
    starter = private / "names_input.csv"
    if not starter.exists():
        shutil.copy(Path(__file__).with_name("names_input.example.csv"), starter)
    print(f"{len(cands)} candidates written to {private / 'name_candidates.csv'}")
    print(f"Edit {starter}: replace the example rows with your real names, aliases and places.")


if __name__ == "__main__":
    main()
