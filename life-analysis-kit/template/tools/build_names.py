#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. Turns the marked-up private/name_candidates.csv into private/names_input.csv.

Rows with a category become people/places. Rows with same_as are added as spellings of that person.
Existing rows in names_input.csv are kept; only words not already listed are appended, so you can run
this again after marking more rows. Safe to repeat.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

CATEGORIES = {"SUBJECT", "PERSON", "PARTNER", "CHILD", "FAMILY", "FRIEND", "WORKPLACE", "SCHOOL", "CITY", "PLACE"}
TRUTHY = {"yes", "y", "true", "1", "x"}
FIELDS = ["name", "category", "token", "aliases", "case_sensitive"]


def read_marked(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(fh)]
    return [r for r in rows if r.get("word") and not r["word"].startswith("#")]


def build(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    problems: list[str] = []
    by_word = {r["word"].lower(): r for r in rows}

    def root_of(word: str) -> str | None:
        seen = set()
        cur = word.lower()
        while by_word.get(cur, {}).get("same_as"):
            if cur in seen:
                return None
            seen.add(cur)
            cur = by_word[cur]["same_as"].strip().lower()
        return cur if cur in by_word else None

    entries: dict[str, dict] = {}
    subject: dict | None = None
    for r in rows:
        cat = r.get("category", "").upper()
        if cat and cat not in CATEGORIES:
            problems.append(f"'{r['word']}': unknown category '{r['category']}' (use one of {', '.join(sorted(CATEGORIES))})")
            continue
        if r.get("same_as"):
            root = root_of(r["word"])
            if root is None:
                problems.append(f"'{r['word']}': same_as '{r['same_as']}' is not a word in this sheet")
                continue
            if cat and cat != by_word[root].get("category", "").upper():
                problems.append(f"'{r['word']}': category differs from '{by_word[root]['word']}'; using the latter")
            entries.setdefault(root, {"aliases": []})["aliases"].append(r["word"])
        elif cat:
            e = entries.setdefault(r["word"].lower(), {"aliases": []})
            e.update(name=r["word"], category=cat, cs=r.get("case_sensitive", "").lower() in TRUTHY)
    out: list[dict[str, str]] = []
    for key, e in entries.items():
        if "name" not in e:
            problems.append(f"'{key}' is used in same_as but has no category of its own")
            continue
        if e["category"] == "SUBJECT":
            if subject is None:
                subject = {"name": e["name"], "category": "SUBJECT", "token": "SUBJECT", "aliases": list(e["aliases"]),
                           "case_sensitive": ""}
                out.append(subject)
            else:
                subject["aliases"] += [e["name"], *e["aliases"]]
            continue
        out.append({"name": e["name"], "category": e["category"], "token": "", "aliases": list(e["aliases"]),
                    "case_sensitive": "yes" if e["cs"] else ""})
    for e in out:
        e["aliases"] = ";".join(e["aliases"])
    return out, problems


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=root)
    args = ap.parse_args()
    private = args.root / "private"
    marked = read_marked(private / "name_candidates.csv")
    if not any(r.get("category") or r.get("same_as") for r in marked):
        header = list(csv.reader(open(private / "name_candidates.csv", encoding="utf-8-sig")))[0]
        sys.exit(
            f"No marked rows found in {private / 'name_candidates.csv'}.\n"
            f"  columns seen: {header}; data rows: {len(marked)}; rows with category or same_as: 0\n"
            "  Most likely your edits were saved to a different file or format (Numbers/Excel 'Export to CSV' writes a new\n"
            "  file). Export as CSV, save over this exact file, and keep the column headers unchanged."
        )
    new, problems = build(marked)
    target = private / "names_input.csv"
    existing: list[dict[str, str]] = []
    if target.exists():
        with open(target, encoding="utf-8-sig", newline="") as fh:
            existing = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip()]
    listed = {s.strip().lower() for r in existing for s in [r["name"], *(r.get("aliases") or "").split(";")] if s.strip()}
    added = skipped = 0
    for e in new:
        surfaces = [e["name"], *[a for a in e["aliases"].split(";") if a]]
        if any(s.lower() in listed for s in surfaces):
            skipped += 1
            continue
        existing.append({k: e.get(k, "") for k in FIELDS})
        listed.update(s.lower() for s in surfaces)
        added += 1
    with open(target, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(existing)
    print(f"{added} people/places added, {skipped} already listed. names_input.csv now has {len(existing)} rows.")
    for p in problems:
        print("  WARNING: " + p)
    if problems:
        print("Fix the rows above in name_candidates.csv and run this again.")
        sys.exit(1)
    print("Next: python3 tools/pseudonymize.py")


if __name__ == "__main__":
    main()
