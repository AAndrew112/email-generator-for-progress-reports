"""Split page transcriptions into dated entries.

Dates come from what is written at the top of each entry. Folder and file
names only supply supporting evidence (e.g. the year when a heading says
"March 4th"), and such dates are marked "inferred". Times are taken only
when written in the entry heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .vision import ENTRY_MARKER

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4,
    "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_ORD = r"(?:st|nd|rd|th)?"
_YEAR = r"(?:\d{4}|'\d{2}|\d{2})"

PATTERNS = [
    ("iso", re.compile(r"\b(?P<year>\d{4})-(?P<mon>\d{1,2})-(?P<day>\d{1,2})\b")),
    ("mdy_name", re.compile(
        rf"\b(?P<mon>{_MON})\.?\s+(?P<day>\d{{1,2}})(?!\d){_ORD}(?:\s*,?\s*(?P<year>{_YEAR}))?(?!\d)", re.I)),
    ("dmy_name", re.compile(
        rf"\b(?P<day>\d{{1,2}})(?!\d){_ORD}\s+(?:of\s+)?(?P<mon>{_MON})\.?(?:\s*,?\s*(?P<year>{_YEAR}))?(?!\d)", re.I)),
    ("my_name", re.compile(rf"\b(?P<mon>{_MON})\.?\s*,?\s+(?P<year>\d{{4}})\b", re.I)),
    ("numeric", re.compile(r"(?<![\d:])(?P<a>\d{1,2})[/.\-](?P<b>\d{1,2})[/.\-](?P<year>\d{4}|\d{2})(?![\d:])")),
    ("numeric_noyear", re.compile(r"(?<![\d:/])(?P<a>\d{1,2})/(?P<b>\d{1,2})(?![\d/:])")),
]
_WEEKDAY_RE = re.compile(rf"\b({_WD})\b\.?", re.I)
_TIME_RE = re.compile(
    r"(?<![\d/.\-])(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>[ap]\.?\s?m\.?)(?![a-z])"
    r"|(?<![\d/.\-])(?P<h2>\d{1,2}):(?P<m2>\d{2})(?![\d/])",
    re.I,
)
_YEAR_HINT_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)")


@dataclass
class DateFinding:
    date: str | None  # ISO, possibly partial (YYYY or YYYY-MM)
    confidence: str  # exact | inferred | unknown
    written: str
    notes: list[str] = field(default_factory=list)
    needs_review: bool = False


def year_hints(*texts: str) -> list[int]:
    years: set[int] = set()
    for t in texts:
        years.update(int(y) for y in _YEAR_HINT_RE.findall(t))
    return sorted(years)


def _resolve_year(raw: str, hints: list[int], notes: list[str]) -> tuple[int, bool]:
    """Return (year, exact). Two-digit years need a century."""
    raw = raw.lstrip("'")
    if len(raw) == 4:
        return int(raw), True
    yy = int(raw)
    options = [1900 + yy, 2000 + yy]
    if hints:
        lo, hi = min(hints) - 1, max(hints) + 1
        matching = [y for y in options if lo <= y <= hi]
        if len(matching) == 1:
            return matching[0], True
    year = 2000 + yy if 2000 + yy <= date.today().year else 1900 + yy
    notes.append(f"century of two-digit year '{raw}' assumed")
    return year, False


def parse_written_date(text: str, date_order: str = "MDY", hints: list[int] | None = None) -> DateFinding | None:
    hints = hints or []
    # Earliest match first; at the same position prefer the longest reading.
    matches = sorted(
        ((m, kind) for kind, rx in PATTERNS for m in rx.finditer(text)),
        key=lambda mk: (mk[0].start(), -len(mk[0].group(0))),
    )
    invalid: DateFinding | None = None
    for m, kind in matches:
        notes: list[str] = []
        g = m.groupdict()
        exact = True
        if kind in ("numeric", "numeric_noyear"):
            a, b = int(g["a"]), int(g["b"])
            month, day = (a, b) if date_order.upper() == "MDY" else (b, a)
            if month > 12 and day <= 12:
                month, day = day, month
                notes.append("day and month order differs from configured date_order")
            elif a <= 12 and b <= 12 and a != b:
                notes.append(f"numeric date read as {date_order.upper()}")
        else:
            month = int(g["mon"]) if g["mon"].isdigit() else MONTHS[g["mon"].lower()]
            day = int(g["day"]) if g.get("day") else None

        if g.get("year"):
            year, year_exact = _resolve_year(g["year"], hints, notes)
            exact = exact and year_exact
        elif len(set(hints)) == 1:
            year = hints[0]
            exact = False
            notes.append(f"year not written; {year} taken from folder/file name")
        else:
            return DateFinding(
                None, "unknown", m.group(0),
                notes + ["month/day written without a year and folder/file names do not settle it"],
                needs_review=True,
            )

        if day is None:
            iso = f"{year:04d}-{month:02d}"
        else:
            try:
                d = date(year, month, day)
            except ValueError:
                invalid = invalid or DateFinding(
                    None, "unknown", m.group(0), [f"'{m.group(0)}' is not a valid date"], True
                )
                continue
            iso = d.isoformat()
            wd = _WEEKDAY_RE.search(text)
            if wd and WEEKDAYS[wd.group(1).lower()] != d.weekday():
                notes.append(f"written weekday '{wd.group(1)}' does not match {iso}")
        if hints and not (min(hints) - 1 <= year <= max(hints) + 1):
            notes.append(f"year {year} conflicts with folder/file name years {hints}")
        finding = DateFinding(iso, "exact" if exact else "inferred", m.group(0), notes)
        finding.needs_review = bool(notes) and any(
            k in n for n in notes for k in ("does not match", "conflicts", "assumed", "differs")
        )
        return finding
    return invalid


def parse_written_time(text: str) -> tuple[str | None, list[str]]:
    m = _TIME_RE.search(text)
    if not m:
        return None, []
    if m.group("h") is not None:
        h, mi, ampm = int(m.group("h")), int(m.group("m") or 0), m.group("ampm").lower()
        if not 1 <= h <= 12 or mi > 59:
            return None, []
        if ampm.startswith("p") and h != 12:
            h += 12
        if ampm.startswith("a") and h == 12:
            h = 0
        return f"{h:02d}:{mi:02d}", []
    h, mi = int(m.group("h2")), int(m.group("m2"))
    if h > 23 or mi > 59:
        return None, []
    notes = ["am/pm not written"] if 1 <= h <= 12 else []
    return f"{h:02d}:{mi:02d}", notes


def _is_header(line: str, date_order: str) -> bool:
    s = line.strip()
    if not s or len(s) > 45:
        return False
    found = parse_written_date(s, date_order)
    if found is None:
        return False
    rest = s.replace(found.written, " ")
    rest = _WEEKDAY_RE.sub(" ", rest)
    rest = re.sub(r"dear diary|dear journal|[^a-z0-9]", " ", rest, flags=re.I)
    rest = _TIME_RE.sub(" ", rest)
    return len(rest.replace(" ", "")) <= 4


@dataclass
class Entry:
    start_page: int
    end_page: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip("\n")

    def header(self, n: int = 3) -> str:
        return "\n".join([ln for ln in self.lines if ln.strip()][:n])


def split_entries(pages: list[tuple[int, str]], date_order: str = "MDY") -> list[Entry]:
    entries: list[Entry] = []
    current: Entry | None = None

    def has_content(e: Entry | None) -> bool:
        return e is not None and any(ln.strip() for ln in e.lines)

    for page_number, text in pages:
        if text.strip() in ("[blank page]", ""):
            continue
        for line in text.splitlines():
            is_marker = line.strip() == ENTRY_MARKER
            if is_marker or (_is_header(line, date_order) and has_content(current)):
                if has_content(current):
                    entries.append(current)  # type: ignore[arg-type]
                current = Entry(page_number, page_number)
                if is_marker:
                    continue
            if current is None:
                current = Entry(page_number, page_number)
            current.lines.append(line.rstrip())
            current.end_page = page_number
    if has_content(current):
        entries.append(current)  # type: ignore[arg-type]
    return entries


def date_entry(entry: Entry, date_order: str, hints: list[int]) -> dict[str, Any]:
    header = entry.header()
    found = parse_written_date(header, date_order, hints)
    time, time_notes = parse_written_time(header) if found else (None, [])
    review: list[str] = []
    if found is None:
        review.append("no date written at the start of this entry")
        return {"date": None, "time": None, "confidence": "unknown", "evidence": {"header": header}, "review": review}
    if found.needs_review or found.date is None:
        review.extend(found.notes or ["date needs checking"])
    if time_notes:
        review.extend(time_notes)
    return {
        "date": found.date,
        "time": time,
        "confidence": found.confidence if found.date else "unknown",
        "evidence": {
            "written": found.written,
            "header": header,
            "notes": found.notes + time_notes,
            "folder_year_hints": hints,
        },
        "review": review,
    }
