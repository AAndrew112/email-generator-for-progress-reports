from datetime import datetime, timezone

from pha.config import MarcoPoloConfig, TimestampSourceRule
from pha.marco_polo.timestamps import parse_datetime, resolve

MTIME = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)  # "downloaded" date
QT = "com.apple.quicktime.creationdate"


def test_parses_common_formats():
    assert parse_datetime("2019-05-04T12:34:56-0700").utcoffset().total_seconds() == -7 * 3600
    assert parse_datetime("2019-05-04T19:34:56.000000Z").tzinfo is not None
    assert parse_datetime("2019:05:04 12:34:56").year == 2019
    assert parse_datetime("1557000000").year == 2019
    assert parse_datetime("1557000000000").year == 2019
    assert parse_datetime("not a date") is None


def test_unconfirmed_fields_never_date_a_video():
    cfg = MarcoPoloConfig()
    ts = resolve(cfg, {QT: "2019-05-04T12:34:56-0700"}, [], MTIME)
    assert ts.date is None and ts.confidence == "unknown"
    assert ts.evidence["candidates"][0]["name"] == QT
    assert "no field has been confirmed" in ts.review_reason


def test_confirmed_field_with_offset_is_exact_local_time():
    cfg = MarcoPoloConfig(timestamp_rules=[TimestampSourceRule("container_tag", QT)])
    ts = resolve(cfg, {QT: "2019-05-04T23:34:56-0700"}, [], MTIME)
    assert (ts.date, ts.time, ts.timezone, ts.confidence) == ("2019-05-04", "23:34:56", "UTC-07:00", "exact")
    assert ts.utc == "2019-05-05T06:34:56+00:00"


def test_timestamp_near_download_time_is_rejected():
    cfg = MarcoPoloConfig(timestamp_rules=[TimestampSourceRule("container_tag", "creation_time")])
    ts = resolve(cfg, {"creation_time": "2026-10-01T09:00:00Z"}, [], MTIME)
    assert ts.date is None
    assert "export/download" in ts.review_reason


def test_placeholder_dates_rejected():
    cfg = MarcoPoloConfig(timestamp_rules=[TimestampSourceRule("container_tag", "creation_time")])
    ts = resolve(cfg, {"creation_time": "1904-01-01T00:00:00Z"}, [], MTIME)
    assert ts.date is None and "Marco Polo existed" in ts.review_reason


def test_utc_only_with_assumed_zone_is_inferred():
    cfg = MarcoPoloConfig(
        timestamp_rules=[TimestampSourceRule("container_tag", "creation_time")],
        assume_timezone="America/Chicago",
    )
    ts = resolve(cfg, {"creation_time": "2019-05-05T02:00:00Z"}, [], MTIME)
    assert (ts.date, ts.time, ts.confidence) == ("2019-05-04", "21:00:00", "inferred")
    assert ts.timezone == "America/Chicago (assumed)"


def test_utc_only_without_assumption_stays_utc():
    cfg = MarcoPoloConfig(timestamp_rules=[TimestampSourceRule("container_tag", "creation_time")])
    ts = resolve(cfg, {"creation_time": "2019-05-05T02:00:00Z"}, [], MTIME)
    assert (ts.date, ts.timezone, ts.confidence) == ("2019-05-05", "UTC", "exact")


def test_sidecar_rule_and_fallthrough_order():
    cfg = MarcoPoloConfig(
        timestamp_rules=[
            TimestampSourceRule("container_tag", "creation_time"),
            TimestampSourceRule("sidecar", "sent_at"),
        ]
    )
    sidecar = [{"manifest": "m.json", "fields": {"sent_at": "2018-02-03T10:00:00+01:00"}}]
    ts = resolve(cfg, {"creation_time": "2026-10-01T10:00:00Z"}, sidecar, MTIME)
    assert ts.date == "2018-02-03" and ts.timezone == "UTC+01:00"
    assert ts.evidence["source"]["name"] == "sent_at"
