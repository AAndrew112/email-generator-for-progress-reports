"""Split page transcriptions into dated entries.

Dates come from what is written at the top of each entry. Folder and file
names only supply supporting evidence (e.g. the year when a heading says
"March 4th"), and such dates are marked "inferred". Times are taken only
when written in the entry heading.

Optionally (``journals.date_undated_from_filename``), an entry with no
usable written date takes the month or year its PDF's name points to,
marked "inferred". A name gives at most a month: a PDF holds many entries,
so a day in its name is not the day of any particular one.

Optionally (``journals.date_undated_from_neighbours``), such an entry first
takes the written date of the nearest entry before it in the same PDF (or
after it, when it comes first), also marked "inferred".
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
    year_written: bool = False


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


def _month_of(m: re.Match[str], kind: str, date_order: str) -> int:
    g = m.groupdict()
    if kind in ("numeric", "numeric_noyear"):
        a, b = int(g["a"]), int(g["b"])
        month = a if date_order.upper() == "MDY" else b
        return (b if month == a else a) if month > 12 else month
    return int(g["mon"]) if g["mon"].isdigit() else MONTHS[g["mon"].lower()]


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

        if not g.get("year") and any(
            later.start() > m.start() and later.groupdict().get("year")
            and _month_of(later, later_kind, date_order) == month
            for later, later_kind in matches
        ):
            continue  # e.g. "12/20" above "12/23/20": the full date says more
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
        finding = DateFinding(iso, "exact" if exact else "inferred", m.group(0), notes, year_written=bool(g.get("year")))
        finding.needs_review = bool(notes) and any(
            k in n for n in notes for k in ("does not match", "conflicts", "assumed", "differs")
        )
        return finding
    return invalid


_NAME_NUMERIC_RE = re.compile(r"(?<![\d.])(\d{1,2})[./\-](\d{1,2})[./\-](\d{4}|\d{2})(?![\d.])")
_NAME_YEAR_MONTH_RE = re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)[./\-](\d{1,2})(?![\d.])")
_NAME_MONTH_RE = re.compile(rf"(?<![a-z])({_MON})(?![a-z])", re.I)
_NAME_RANGE_RE = re.compile(r"\b(?:until|till|starting|start|through|thru|since|from|to)\b", re.I)


def date_from_filename(name: str, date_order: str = "MDY") -> tuple[str | None, str]:
    """The month (YYYY-MM) or year (YYYY) a journal PDF's name points to.

    Returns (date or None, explanation). Names covering a span ("starting
    jan 2002", "june and july 2005") give only the year; spans across a new
    year, or names with several years or none, give no date.
    """
    stem = re.sub(r"\.pdf$", "", name.strip(), flags=re.I)
    m = _NAME_NUMERIC_RE.search(stem)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        month = a if date_order.upper() == "MDY" else b
        if month > 12:
            month = b if month == a else a
        year, _ = _resolve_year(m.group(3), [], [])
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}", f"numeric date '{m.group(0)}' in the PDF name"
    m = _NAME_YEAR_MONTH_RE.search(stem)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}", f"'{m.group(0)}' in the PDF name"

    years = year_hints(stem)
    if len(years) != 1:
        return None, ("no year in the PDF name" if not years else f"PDF name spans several years {years}")
    year = years[0]
    months = [MONTHS[t.lower()] for t in _NAME_MONTH_RE.findall(stem)]
    if any(later < earlier for earlier, later in zip(months, months[1:])):
        return None, "PDF name spans into a new year, so the year of each entry is unclear"
    if len(set(months)) == 1 and not _NAME_RANGE_RE.search(stem):
        return f"{year:04d}-{months[0]:02d}", "month and year in the PDF name"
    return f"{year:04d}", "year in the PDF name" + (" (it names a span of months)" if months else "")


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


_MARKER_VARIANT_RE = re.compile(r"^\s*(?:={2,}|#{2,})\s*ENTRY\s*(?:={2,}|#{2,})?\s*$", re.I)


def _is_marker(line: str) -> bool:
    """The model's entry marker, including near-misses such as '### ENTRY'."""
    return line.strip() == ENTRY_MARKER or bool(_MARKER_VARIANT_RE.match(line))


def _is_header(line: str, date_order: str, first_on_page: bool = False) -> bool:
    s = line.strip()
    if not s or len(s) > 60:
        return False
    found = parse_written_date(s, date_order)
    if found is None:
        return False
    # The first line of a page with a full date (day, month and year) starts an
    # entry even with a title beside it ("7/13/21 Dan and I").
    if first_on_page and found.year_written and found.date and len(found.date) == 10:
        return True
    if len(s) > 45:
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

    def only_headers(e: Entry | None) -> bool:
        lines = [ln for ln in (e.lines if e else []) if ln.strip()]
        return bool(lines) and all(_is_header(ln, date_order) for ln in lines)

    for page_number, text in pages:
        if text.strip() in ("[blank page]", ""):
            continue
        first_on_page = True
        for line in text.splitlines():
            is_marker = _is_marker(line)
            is_header = not is_marker and _is_header(line, date_order, first_on_page)
            if line.strip():
                first_on_page = False
            if is_marker and only_headers(current):
                continue  # marker written just after the date heading: same entry
            if is_marker or (is_header and has_content(current)):
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


def date_entry(
    entry: Entry, date_order: str, hints: list[int], filename: str | None = None
) -> dict[str, Any]:
    """Date an entry from its heading; ``filename`` enables the PDF-name fallback."""
    header = entry.header()
    found = parse_written_date(header, date_order, hints)
    time, time_notes = parse_written_time(header) if found else (None, [])
    review: list[str] = []
    if found is None or found.date is None:
        evidence: dict[str, Any] = {"header": header}
        if found is not None:
            evidence.update(written=found.written, notes=found.notes)
        if filename:
            name_date, why = date_from_filename(filename, date_order)
            evidence["filename_date"] = {"filename": filename, "date": name_date, "basis": why}
            if not name_date and "no year" in why and len(set(hints)) == 1:
                name_date, why = f"{hints[0]:04d}", "year in the folder name"
                evidence["filename_date"].update(date=name_date, basis=why)
            if name_date:
                evidence["notes"] = evidence.get("notes", []) + [
                    f"no usable date written in the entry; {name_date} taken from the PDF name ({why})"
                ]
                return {"date": name_date, "time": None, "confidence": "inferred", "evidence": evidence, "review": []}
        if found is None:
            review.append("no date written at the start of this entry")
        else:
            review.extend(found.notes or ["date needs checking"])
        return {"date": None, "time": None, "confidence": "unknown", "evidence": evidence, "review": review}
    if found.needs_review:
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


def date_entries(
    entries: list[Entry],
    date_order: str,
    hints: list[int],
    filename: str | None = None,
    neighbours: bool = False,
) -> list[dict[str, Any]]:
    """Date every entry of one PDF, in order.

    Entries without a usable written date take, when enabled, the written date
    of the nearest earlier entry (the next one for leading entries), then the
    PDF name's month or year (``filename``).
    """
    written = [date_entry(e, date_order, hints) for e in entries]
    out: list[dict[str, Any]] = []
    for i, (entry, dated) in enumerate(zip(entries, written)):
        if dated["date"] is not None:
            out.append(dated)
            continue
        near = None
        if neighbours:
            before = [(j, w) for j, w in enumerate(written[:i]) if w["date"]]
            after = [(j, w) for j, w in enumerate(written) if j > i and w["date"]]
            near = before[-1] if before else (after[0] if after else None)
        if near is not None:
            j, w = near
            where = "before" if j < i else "after"
            other = entries[j]
            evidence = {
                **dated["evidence"],
                "neighbour_date": {
                    "date": w["date"],
                    "entry_pages": [other.start_page, other.end_page],
                    "written": w["evidence"].get("written"),
                },
            }
            evidence["notes"] = evidence.get("notes", []) + [
                f"no usable date written in the entry; {w['date']} taken from the entry {where} it "
                f"(pages {other.start_page}-{other.end_page})"
            ]
            out.append({"date": w["date"], "time": None, "confidence": "inferred", "evidence": evidence, "review": []})
        elif filename:
            out.append(date_entry(entry, date_order, hints, filename))
        else:
            out.append(dated)
    return out
