#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. Turns the marked-up private/name_candidates.csv into private/names_input.csv.

Rows with a category become people/places. Rows with same_as are added as spellings of that person.
Existing rows in names_input.csv are kept; only words not already listed are appended, so you can run
this again after marking more rows. Safe to repeat.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

CATEGORIES = {"SUBJECT", "PERSON", "FRIEND", "COWORKER", "PARTNER", "EXPARTNER", "CHILD", "SIBLING", "PARENT",
              "INLAW", "FAMILY", "PET", "FICTION", "WORKPLACE", "SCHOOL", "CITY", "PLACE"}
TRUTHY = {"yes", "y", "true", "1", "x"}
FIELDS = ["name", "category", "token", "aliases", "case_sensitive"]


NOTE_SPLIT = re.compile(r"\s[-\u2013\u2014:]\s")
ALIAS_RX = re.compile(r"(?:k?nick\s?names?|a\.?k\.?a\.?|also called|goes by|called)(?:\s+(?:include|includes|are|is))?[:\s]+(.*)$", re.I)
RULES = [  # first match wins; order matters
    ("SUBJECT", re.compile(r"\bsubject\b|\(me\)|\bmyself\b|^me\b", re.I)),
    ("EXPARTNER", re.compile(r"\bex[- ]?(husband|wife|boyfriend|girlfriend|partner|fianc)|\bformer (husband|wife|partner)", re.I)),
    ("PARTNER", re.compile(r"\b(husband|wife|partner|boyfriend|girlfriend|fianc\w*|spouse)\b", re.I)),
    ("CHILD", re.compile(r"\b(my|our) (son|daughter|child|kid|baby|stepson|stepdaughter)\b", re.I)),
    ("INLAW", re.compile(r"\bin[- ]?law", re.I)),
    ("SIBLING", re.compile(r"^(my )?(half[- ]?|step)?(brother|sister|sibling)\b", re.I)),
    ("PARENT", re.compile(r"^(my )?(step)?(mother|mom|mum|mommy|father|dad|daddy|parent)\b", re.I)),
    ("FAMILY", re.compile(r"\b(grand\w+|aunt|uncle|cousin|niece|nephew|stepmom|stepdad|relative|family)\b", re.I)),
    ("FRIEND", re.compile(r"\bfriend\b", re.I)),
    ("COWORKER", re.compile(r"\b(coworker|co-worker|colleague|boss|manager|supervisor)\b", re.I)),
    ("PET", re.compile(r"\b(pet|(my|our|family|childhood) (cat|dog|kitten|puppy)|dog|cat)\b", re.I)),
    ("FICTION", re.compile(r"\b(character|fiction|story I wrote|creative writing)\b", re.I)),
    ("PERSON", re.compile(r"\b(teacher|professor|neighbou?r|classmate|roommate|acquaintance|person|doctor|therapist)\b", re.I)),
    ("WORKPLACE", re.compile(r"\b(workplace|company|employer|office|firm|business|work for|worked at)\b", re.I)),
    ("SCHOOL", re.compile(r"\b(school|university|college|academy|kindergarten)\b", re.I)),
    ("CITY", re.compile(r"\b(city|town|village|state|country|neighbou?rhood)\b", re.I)),
    ("PLACE", re.compile(r"\b(place|restaurant|cafe|park|store|shop|hotel|beach|church|gym|hospital|camp)\b", re.I)),
]


def parse_note(note: str) -> tuple[str, list[str]]:
    """Category and nicknames from a short note such as 'close friend, nicknames include Al, Ally'.

    Returns ('', []) when the note says the word is unknown (it is then hidden by the automatic
    catch-all with a plain NAME_ label). Everything else in the note is discarded, not saved.
    """
    if re.fullmatch(r"\W*(unknown|unsure|\?+|not sure|idk|n/?a)\W*", note.strip(), re.I):
        return "", []
    aliases: list[str] = []
    m = ALIAS_RX.search(note)
    if m:
        aliases = [a.strip(" \"'.()") for a in re.split(r",|;|/|\band\b|\bor\b", m.group(1)) if a.strip(" \"'.()")]
        note = note[: m.start()]
    for category, rx in RULES:
        if rx.search(note.strip()):
            return category, aliases
    return "PERSON", aliases


def load_sheet(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Header row and data rows. Lines above the header (a spreadsheet's title line) are ignored."""
    table = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    for i, row in enumerate(table):
        header = [c.strip().lower() for c in row]
        if "word" in header and "category" in header:
            return header, [{h: (c or "").strip() for h, c in zip(header, r) if h} for r in table[i + 1:]]
    return [], []


def read_marked(path: Path) -> list[dict[str, str]]:
    out = []
    for r in load_sheet(path)[1]:
        word = r.get("word", "")
        if not word or word.startswith("#"):
            continue
        parts = NOTE_SPLIT.split(word, maxsplit=1)
        if len(parts) == 2:  # a note typed into the word cell, e.g. "Tyler - brother"
            r["word"] = parts[0].strip()
            category, aliases = parse_note(parts[1])
            r["note_category"], r["note_aliases"] = category, ";".join(aliases)
            if category and not r.get("category"):
                r["category"] = category
        out.append(r)
    return out


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
            e["aliases"] += [a for a in r.get("note_aliases", "").split(";") if a]
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
        header, _ = load_sheet(private / "name_candidates.csv")
        first = (private / "name_candidates.csv").read_text(encoding="utf-8-sig").splitlines()[:1]
        sys.exit(
            f"No marked rows found in {private / 'name_candidates.csv'}.\n"
            f"  columns seen: {header or 'no header row containing word and category (first line: ' + repr(first[0][:40] if first else '') + ')'}; "
            f"data rows: {len(marked)}; rows with category or same_as: 0\n"
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
    by_name = {r["name"].strip().lower(): r for r in existing}
    added = extended = unchanged = 0
    for e in new:
        surfaces = [e["name"], *[a for a in e["aliases"].split(";") if a]]
        row = by_name.get(e["name"].lower())
        if row is not None:  # a person already listed: add any spellings that are new
            fresh = [a for a in surfaces[1:] if a.lower() not in listed]
            if fresh:
                have = [a.strip() for a in (row.get("aliases") or "").split(";") if a.strip()]
                row["aliases"] = ";".join(have + fresh)
                listed.update(a.lower() for a in fresh)
                extended += len(fresh)
            else:
                unchanged += 1
            continue
        if any(x.lower() in listed for x in surfaces):  # the word is already listed under someone else
            unchanged += 1
            continue
        existing.append({k: e.get(k, "") for k in FIELDS})
        by_name[e["name"].lower()] = existing[-1]
        listed.update(x.lower() for x in surfaces)
        added += 1
    with open(target, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(existing)
    print(f"{added} people/places added, {extended} new spellings added to people already listed, "
          f"{unchanged} already up to date. names_input.csv now has {len(existing)} rows.")
    if new:
        print("What was understood (check this; it stays on your Mac):")
        for e in new:
            print(f"  {e['name']} -> {e['category']}" + (f"  (also: {e['aliases'].replace(';', ', ')})" if e["aliases"] else ""))
    for p in problems:
        print("  WARNING: " + p)
    if problems:
        print("Fix the rows above in name_candidates.csv and run this again.")
        sys.exit(1)
    print("Next: python3 tools/pseudonymize.py")


if __name__ == "__main__":
    main()
