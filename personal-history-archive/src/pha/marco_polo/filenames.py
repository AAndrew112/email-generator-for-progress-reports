"""Metadata encoded in exported file names.

Marco Polo's chat export names files like
``2026-04-28_05-07-33_PDT_Evelyn_E.mp4``: date, time, timezone abbreviation
and sender. The pattern is configurable (``marco_polo.filename_pattern``).
A sender taken from a file name is not trusted on its own; see
``OwnershipMetadataRule.spot_checked``.
"""

from __future__ import annotations

import re

DEFAULT_PATTERN = (
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_(?P<tz>[A-Z]{2,5})_(?P<sender>.+?)(?: \(\d+\))?$"
)

# Abbreviations as used in the US; "CST" etc. are ambiguous elsewhere, which
# is why the abbreviation itself is also kept in the timestamp evidence.
TZ_OFFSETS = {
    "UTC": "+00:00", "GMT": "+00:00",
    "EST": "-05:00", "EDT": "-04:00", "CST": "-06:00", "CDT": "-05:00",
    "MST": "-07:00", "MDT": "-06:00", "PST": "-08:00", "PDT": "-07:00",
    "AKST": "-09:00", "AKDT": "-08:00", "HST": "-10:00",
    "BST": "+01:00", "CET": "+01:00", "CEST": "+02:00",
}


def parse_filename(stem: str, pattern: str) -> dict[str, str]:
    """Return ``sender``, ``timestamp`` and ``tz_abbreviation`` fields, if the name matches."""
    if not pattern:
        return {}
    m = re.match(pattern, stem)
    if not m:
        return {}
    g = m.groupdict()
    out: dict[str, str] = {}
    if g.get("sender"):
        out["sender"] = g["sender"].replace("_", " ").strip()
    if g.get("date") and g.get("time"):
        stamp = f"{g['date']}T{g['time'].replace('-', ':')}"
        tz = g.get("tz") or ""
        if tz:
            out["tz_abbreviation"] = tz
        if tz in TZ_OFFSETS:
            stamp += TZ_OFFSETS[tz]
        out["timestamp"] = stamp
    return out
