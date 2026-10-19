"""Recording-timestamp resolution for videos.

Only metadata fields the user has confirmed (``timestamp_rules`` in the
config, chosen after ``pha mp inspect``) can date a video. Everything else
that looks like a date is kept as a *candidate* for the review queue. File
system dates (mtime/ctime) are never used as a recording date; the
modification time is only used to detect container timestamps that were
rewritten at export/download time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..config import MarcoPoloConfig, TimestampSourceRule
from .sidecar import sidecar_values

# Marco Polo launched in 2014; QuickTime writes 1904-01-01 when the field is
# unset and some tools write 1970-01-01. Anything earlier is not a recording.
EARLIEST_PLAUSIBLE = datetime(2013, 1, 1, tzinfo=timezone.utc)

_IGNORED_TAGS = {"duration", "timecode", "encoder", "handler_name", "vendor_id"}
_EXIF_RE = re.compile(r"^(\d{4}):(\d{2}):(\d{2})([ T].*)$")


@dataclass
class ResolvedTimestamp:
    date: str | None = None
    time: str | None = None
    timezone: str | None = None
    confidence: str = "unknown"
    utc: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    review_reason: str | None = None


def parse_datetime(value: str, fmt: str | None = None) -> datetime | None:
    value = str(value).strip()
    if not value:
        return None
    if fmt:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            return None
    if re.fullmatch(r"\d{10}(\.\d+)?", value):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if re.fullmatch(r"\d{13}", value):
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    m = _EXIF_RE.match(value)
    if m:
        value = f"{m.group(1)}-{m.group(2)}-{m.group(3)}{m.group(4)}"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _offset_label(dt: datetime) -> str:
    off = dt.utcoffset()
    if off is None:
        return ""
    if off == timedelta(0):
        return "UTC"
    total = int(off.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 60:02d}:{total % 60:02d}"


def _is_plausible(dt: datetime, mtime: datetime) -> str | None:
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if aware < EARLIEST_PLAUSIBLE:
        return "earlier than Marco Polo existed (unset/placeholder value)"
    if aware > mtime + timedelta(days=1):
        return "later than the file itself was written"
    return None


def _looks_like_export_time(dt: datetime, mtime: datetime, window_hours: float) -> bool:
    if dt.tzinfo is None:
        # Naive values are local wall-clock time; allow up to 14 h of offset.
        delta = abs(dt - mtime.replace(tzinfo=None))
        return delta <= timedelta(hours=window_hours + 14)
    return abs(dt - mtime) <= timedelta(hours=window_hours)


def _rule_values(
    rule: TimestampSourceRule, tags: dict[str, str], sidecar: list[dict], filename: dict[str, str]
) -> list[str]:
    if rule.kind == "filename":
        v = filename.get(rule.name)
        return [v] if v else []
    if rule.kind == "container_tag":
        v = tags.get(rule.name)
        return [v] if v else []
    if rule.kind == "sidecar":
        return sidecar_values(sidecar, rule.name)
    raise ValueError(f"Unknown timestamp rule kind '{rule.kind}'")


def find_candidates(
    tags: dict[str, str],
    sidecar: list[dict],
    mtime: datetime,
    window_hours: float,
    filename: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Every metadata value that parses as a date-time, with plausibility notes."""
    found: list[dict[str, Any]] = []

    def consider(kind: str, name: str, value: str) -> None:
        if name.split(":")[-1].lower() in _IGNORED_TAGS:
            return
        dt = parse_datetime(value)
        if dt is None:
            return
        found.append(
            {
                "kind": kind,
                "name": name,
                "value": value,
                "parsed": dt.isoformat(),
                "has_timezone": dt.tzinfo is not None,
                "implausible": _is_plausible(dt, mtime),
                "near_file_mtime": _looks_like_export_time(dt, mtime, window_hours),
            }
        )

    for name, value in (filename or {}).items():
        consider("filename", name, value)
    for name, value in tags.items():
        consider("container_tag", name, value)
    for entry in sidecar:
        for name, value in entry["fields"].items():
            consider("sidecar", name, value)
    return found


def resolve(
    cfg: MarcoPoloConfig,
    tags: dict[str, str],
    sidecar: list[dict],
    mtime: datetime,
    filename: dict[str, str] | None = None,
) -> ResolvedTimestamp:
    """Pick the recording time from confirmed rules, or leave it unknown."""
    filename = filename or {}
    candidates = find_candidates(tags, sidecar, mtime, cfg.contamination_window_hours, filename)
    rejected: list[dict[str, Any]] = []

    for rule in cfg.timestamp_rules:
        for raw in _rule_values(rule, tags, sidecar, filename):
            dt = parse_datetime(raw, rule.format)
            if dt is None:
                rejected.append({"rule": rule.name, "value": raw, "why": "unparseable"})
                continue
            problem = _is_plausible(dt, mtime)
            if problem is None and _looks_like_export_time(dt, mtime, cfg.contamination_window_hours):
                problem = (
                    "within the contamination window of the file modification time; "
                    "probably the export/download time"
                )
            if problem:
                rejected.append({"rule": rule.name, "value": raw, "why": problem})
                continue
            ts = _build(cfg, dt, rule, raw, candidates)
            if rule.kind == "filename" and filename.get("tz_abbreviation"):
                ts.evidence["tz_abbreviation_as_written"] = filename["tz_abbreviation"]
            return ts

    reason = "no confirmed recording-time metadata"
    if rejected:
        reason = "confirmed timestamp field rejected: " + "; ".join(r["why"] for r in rejected)
    elif candidates and not cfg.timestamp_rules:
        reason = "date-like metadata found but no field has been confirmed as the recording time"
    elif candidates:
        reason += f"; {len(candidates)} unconfirmed date-like field(s) listed in details"
    return ResolvedTimestamp(
        evidence={"source": None, "candidates": candidates, "rejected": rejected},
        review_reason=reason,
    )


def _build(
    cfg: MarcoPoloConfig,
    dt: datetime,
    rule: TimestampSourceRule,
    raw: str,
    candidates: list[dict[str, Any]],
) -> ResolvedTimestamp:
    evidence: dict[str, Any] = {
        "source": {"kind": rule.kind, "name": rule.name, "value": raw},
        "candidates": candidates,
    }
    if dt.tzinfo is None:
        evidence["note"] = "metadata value has no timezone; wall-clock time kept as written"
        return ResolvedTimestamp(
            date=dt.date().isoformat(),
            time=dt.strftime("%H:%M:%S"),
            timezone=None,
            confidence="exact",
            utc=None,
            evidence=evidence,
        )

    utc = dt.astimezone(timezone.utc)
    label = _offset_label(dt)
    if label == "UTC" and cfg.assume_timezone:
        local = utc.astimezone(ZoneInfo(cfg.assume_timezone))
        evidence["note"] = (
            f"metadata is UTC only; converted to assumed zone {cfg.assume_timezone}"
        )
        return ResolvedTimestamp(
            date=local.date().isoformat(),
            time=local.strftime("%H:%M:%S"),
            timezone=f"{cfg.assume_timezone} (assumed)",
            confidence="inferred",
            utc=utc.isoformat(),
            evidence=evidence,
        )
    if label == "UTC":
        evidence["note"] = "metadata is UTC only; recording-location timezone unknown"
    return ResolvedTimestamp(
        date=dt.date().isoformat(),
        time=dt.strftime("%H:%M:%S"),
        timezone=label,
        confidence="exact",
        utc=utc.isoformat(),
        evidence=evidence,
    )
