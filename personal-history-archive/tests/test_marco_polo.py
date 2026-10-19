import csv
import json
import shutil

import pytest

from conftest import OLD, OTHER_HZ, OWNER_HZ, FakeEmbedder, FakeTranscriber, make_video, write_json
from pha.config import OwnershipMetadataRule, TimestampSourceRule
from pha.export import export_archive
from pha.marco_polo.pipeline import MarcoPoloPipeline, set_manual_ownership
from pha.runtime import sha256_file

QT = "com.apple.quicktime.creationdate"


@pytest.fixture
def export_dir(cfg, tmp_path):
    root = tmp_path / "exports"
    # Mine, per sidecar manifest, with a real recording date.
    make_video(root / "chat_mom" / "a.mp4", tags={QT: "2019-05-04T20:15:00-0500"}, mtime=OLD)
    make_video(root / "chat_mom" / "b.mp4", tags={QT: "2020-01-02T08:00:00-0600"}, mtime=OLD, freqs=(OTHER_HZ,))
    # Mine, but the only timestamp is the download time.
    make_video(root / "chat_dad" / "c.mp4", tags={"creation_time": "2026-08-31T22:00:00Z"}, mtime=OLD)
    # Unknown sender.
    make_video(root / "misc" / "d.mp4", tags={QT: "2018-07-07T07:07:07+0000"}, mtime=OLD)
    write_json(root / "chat_mom" / "manifest.json", {"polos": [
        {"file": "a.mp4", "sender": {"name": "Amanda"}},
        {"file": "b.mp4", "sender": {"name": "Mom"}},
    ]})
    write_json(root / "chat_dad" / "c.json", {"sender": {"name": "amanda"}})
    # Same file imported twice.
    shutil.copy2(root / "chat_mom" / "a.mp4", root / "chat_mom" / "copy of a.mp4")
    cfg.marco_polo.ownership_rules = [OwnershipMetadataRule("sidecar", "sender.name", ["Amanda"])]
    cfg.marco_polo.timestamp_rules = [TimestampSourceRule("container_tag", QT)]
    return root


def run(cfg, db, transcriber=None, embedder=None, **kw):
    t = transcriber or FakeTranscriber()
    p = MarcoPoloPipeline(cfg, db, transcriber_factory=lambda: t,
                          embedder_factory=(lambda: embedder) if embedder else None)
    return p.run(**kw), t


def by_name(db):
    return {r["filename"]: r for r in db.sources("marco_polo")}


def test_end_to_end_ownership_dates_and_duplicates(cfg, db, export_dir):
    progress, t = run(cfg, db)
    src = by_name(db)
    assert src["a.mp4"]["status"] == "done" and src["a.mp4"]["ownership"] == "owner"
    assert src["b.mp4"]["status"] == "excluded"
    assert src["c.mp4"]["status"] == "done"
    assert src["d.mp4"]["status"] == "needs_review"
    assert "copy of a.mp4" not in src  # recognised as the same content
    assert len(db.source_locations(src["a.mp4"]["source_id"])) == 2
    assert len(t.calls) == 2  # a and c only; never other people's or uncertain videos

    recs = {r["source_filename"]: r for r in db.all_records()}
    assert set(recs) == {"a.mp4", "c.mp4"}
    a = recs["a.mp4"]
    assert (a["machine_date"], a["machine_time"], a["machine_timezone"]) == ("2019-05-04", "20:15:00", "UTC-05:00")
    assert a["raw_transcript"] == "Um, so I- I was thinking uh, mumble mumble"  # disfluencies kept
    assert "sender metadata" in a["speaker_verification"]
    c = recs["c.mp4"]
    assert c["machine_date"] is None and c["machine_confidence"] == "unknown"

    kinds = {(i["kind"], i["source_id"] or i["record_id"]) for i in db.review_items()}
    assert ("speaker", src["d.mp4"]["source_id"]) in kinds
    assert ("date", c["record_id"]) in kinds
    assert ("transcription", a["record_id"]) in kinds  # low-confidence passage


def test_repeat_import_does_not_retranscribe(cfg, db, export_dir):
    run(cfg, db)
    _, t2 = run(cfg, db)
    assert t2.calls == []


def test_interrupted_run_resumes(cfg, db, export_dir):
    t = FakeTranscriber()
    # Files are processed in path order: chat_dad/c.mp4, then chat_mom/a.mp4.
    t.interrupt_on = {sha256_file(export_dir / "chat_mom" / "a.mp4")[:6]}
    with pytest.raises(KeyboardInterrupt):
        run(cfg, db, transcriber=t)
    assert by_name(db)["c.mp4"]["status"] == "done"
    assert by_name(db)["a.mp4"]["status"] == "in_progress"
    _, t2 = run(cfg, db)
    assert by_name(db)["a.mp4"]["status"] == "done"
    assert len(t2.calls) == 1  # only the interrupted video


def test_failures_are_logged_and_processing_continues(cfg, db, export_dir):
    t = FakeTranscriber()
    t.fail_on = {sha256_file(export_dir / "chat_mom" / "a.mp4")[:6]}
    run(cfg, db, transcriber=t)
    src = by_name(db)
    assert src["a.mp4"]["status"] == "failed" and "decoder exploded" in src["a.mp4"]["last_error"]
    assert src["c.mp4"]["status"] == "done"
    assert db.conn.execute("SELECT COUNT(*) FROM failures").fetchone()[0] == 1
    _, t2 = run(cfg, db)
    assert by_name(db)["a.mp4"]["status"] == "done"


def test_confirming_a_timestamp_rule_later_dates_done_videos(cfg, db, export_dir):
    cfg.marco_polo.timestamp_rules = []
    run(cfg, db)
    rec = [r for r in db.all_records() if r["source_filename"] == "a.mp4"][0]
    assert rec["machine_date"] is None
    cfg.marco_polo.timestamp_rules = [TimestampSourceRule("container_tag", QT)]
    _, t = run(cfg, db)
    assert t.calls == []
    assert db.get_record(rec["record_id"])["machine_date"] == "2019-05-04"
    open_dates = [i for i in db.review_items("open", "date") if i["record_id"] == rec["record_id"]]
    assert open_dates == []


def test_manual_ownership_then_processing(cfg, db, export_dir):
    run(cfg, db)
    d = by_name(db)["d.mp4"]
    set_manual_ownership(db, d["source_id"], "owner", "that's my voice")
    _, t = run(cfg, db)
    assert len(t.calls) == 1
    rec = db.records_for_source(d["source_id"])[0]
    assert rec["speaker_verification"] == "owner: confirmed in manual review"
    # --reclassify must not override a manual decision
    run(cfg, db, reclassify=True)
    assert db.get_source(d["source_id"])["ownership"] == "owner"


def test_corrections_survive_reprocessing(cfg, db, export_dir):
    run(cfg, db)
    rec = [r for r in db.all_records() if r["source_filename"] == "a.mp4"][0]
    db.apply_correction(rec["record_id"], "transcript", "Um, so I- I was thinking, uh, about Grandma")
    run(cfg, db, force_retranscribe=True)
    row = db.get_record(rec["record_id"])
    assert row["corrected_transcript"] == "Um, so I- I was thinking, uh, about Grandma"
    assert row["raw_transcript"].startswith("Um, so I- I was thinking")
    assert db.conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 1


def test_voice_verification_and_conflicts(cfg, db, tmp_path):
    root = tmp_path / "exports"
    for i in range(3):
        make_video(tmp_path / "samples" / "me" / f"me{i}.mp4", seconds=3 + i, freqs=(OWNER_HZ,))
    make_video(tmp_path / "samples" / "others" / "mom" / "m.mp4", freqs=(OTHER_HZ,))
    make_video(root / "mine.mp4", seconds=5, mtime=OLD)
    make_video(root / "theirs.mp4", seconds=5, freqs=(OTHER_HZ,), mtime=OLD)
    make_video(root / "both.mp4", seconds=6, freqs=(OWNER_HZ, OTHER_HZ), mtime=OLD)
    make_video(root / "silent.mp4", audio=False, mtime=OLD)
    make_video(root / "liar.mp4", seconds=7, freqs=(OTHER_HZ,), mtime=OLD)
    write_json(root / "liar.json", {"sender": "Amanda"})
    cfg.marco_polo.ownership_rules = [OwnershipMetadataRule("sidecar", "sender", ["Amanda"])]
    cfg.voice.enabled = True
    cfg.voice.owner_samples_dir = "samples/me"
    cfg.voice.other_samples_dir = "samples/others"
    run(cfg, db, embedder=FakeEmbedder())
    src = by_name(db)
    assert src["mine.mp4"]["ownership"] == "owner"
    assert src["theirs.mp4"]["ownership"] == "other"
    both = json.loads(src["both.mp4"]["ownership_detail"])
    assert src["both.mp4"]["ownership"] == "uncertain" and both["reason"] == "multiple speakers detected"
    assert src["silent.mp4"]["ownership"] == "uncertain"
    liar = json.loads(src["liar.mp4"]["ownership_detail"])
    assert src["liar.mp4"]["ownership"] == "uncertain" and "voice check says 'other'" in liar["reason"]
    rec = db.records_for_source(src["mine.mp4"]["source_id"])[0]
    assert rec["speaker_verification"].startswith("owner: voice match")


def test_voice_needs_enough_samples(cfg, db, tmp_path):
    make_video(tmp_path / "samples" / "me" / "me0.mp4", freqs=(OWNER_HZ,))
    make_video(tmp_path / "exports" / "mine.mp4", mtime=OLD)
    cfg.voice.enabled = True
    cfg.voice.owner_samples_dir = "samples/me"
    run(cfg, db, embedder=FakeEmbedder())
    s = by_name(db)["mine.mp4"]
    assert s["ownership"] == "uncertain"
    assert "at least 3 labelled samples" in json.loads(s["ownership_detail"])["reason"]


def test_export_files(cfg, db, export_dir):
    run(cfg, db)
    summary = export_archive(db, cfg.export_path)
    assert summary == {**summary, "records": 2, "dated": 1, "undated": 1}
    rows = list(csv.DictReader(open(cfg.export_path / "archive.csv", encoding="utf-8")))
    assert [r["date"] for r in rows] == ["2019-05-04", "UNDATED"]
    assert rows[1]["review_required"] == "yes"
    data = json.loads((cfg.export_path / "archive.json").read_text())
    assert data["undated_records"][0]["date"] is None
    assert data["records"][0]["metadata"]["file_sha256"]
    assert (cfg.export_path / "transcripts" / "2019" / "05").is_dir()
    assert len(list((cfg.export_path / "transcripts" / "undated").glob("*.txt"))) == 1
    queue = json.loads((cfg.export_path / "review_queue.json").read_text())
    assert {q["kind"] for q in queue} >= {"speaker", "date", "transcription"}


def test_originals_untouched(cfg, db, export_dir):
    before = {p: (sha256_file(p), p.stat().st_mtime_ns) for p in export_dir.rglob("*") if p.is_file()}
    run(cfg, db)
    after = {p: (sha256_file(p), p.stat().st_mtime_ns) for p in export_dir.rglob("*") if p.is_file()}
    assert before == after


def test_inspect_report(cfg, db, export_dir):
    from pha.marco_polo.inspect import inspect_export, render_markdown

    report = inspect_export(cfg)
    assert report["video_files"] == 5
    assert "sidecar:sender.name" not in report["date_fields"]
    assert report["date_fields"]["container_tag:creation_time"]["verdict"].startswith("LIKELY EXPORT")
    assert "sender.name" in report["possible_sender_fields"]["sidecar"]
    assert "Possible sender fields" in render_markdown(report)


def test_icloud_placeholders_reported_not_silently_skipped(cfg, db, tmp_path, caplog):
    from pha.marco_polo.inspect import inspect_export, render_markdown

    root = tmp_path / "exports"
    make_video(root / "Voice videos" / "downloaded.mov", mtime=OLD)
    (root / "Voice videos" / ".not yet.mov.icloud").write_bytes(b"bplist00")
    (root / "Voice videos" / ".notes.txt.icloud").write_bytes(b"bplist00")
    report = inspect_export(cfg)
    assert report["video_files"] == 1
    assert report["icloud_not_downloaded"] == ["Voice videos/.not yet.mov.icloud"]
    assert "in iCloud only" in render_markdown(report)
    with caplog.at_level("WARNING", logger="pha"):
        run(cfg, db)
    assert "not yet.mov" in caplog.text and "NOT processed" in caplog.text


# ------------------------------------------------- Marco Polo file-name metadata
def test_parse_marco_polo_filenames():
    from pha.marco_polo.filenames import DEFAULT_PATTERN, parse_filename

    assert parse_filename("2026-04-28_05-07-33_PDT_Evelyn_E", DEFAULT_PATTERN) == {
        "sender": "Evelyn E", "tz_abbreviation": "PDT", "timestamp": "2026-04-28T05:07:33-07:00",
    }
    assert parse_filename("2025-12-01_20-00-00_PST_Amanda_W (1)", DEFAULT_PATTERN)["sender"] == "Amanda W"
    assert parse_filename("2025-12-01_20-00-00_XYZT_Amanda_W", DEFAULT_PATTERN)["timestamp"] == "2025-12-01T20:00:00"
    assert parse_filename("IMG_1234", DEFAULT_PATTERN) == {}


@pytest.fixture
def named_export(cfg, tmp_path):
    root = tmp_path / "exports" / "Chat_1_of_4"
    make_video(root / "2025-01-02_18-30-00_PST_Amanda_W.mp4", mtime=OLD)
    make_video(root / "2025-01-03_09-00-00_PST_Evelyn_E.mp4", seconds=5, freqs=(OTHER_HZ,), mtime=OLD)
    cfg.marco_polo.timestamp_rules = [TimestampSourceRule("filename", "timestamp")]
    return root


def test_unverified_filename_sender_goes_to_review(cfg, db, named_export):
    cfg.marco_polo.ownership_rules = [OwnershipMetadataRule("filename", "sender", ["Amanda W"])]
    _, t = run(cfg, db)
    src = by_name(db)
    assert {s["ownership"] for s in src.values()} == {"uncertain"}
    assert "not verified yet" in json.loads(src["2025-01-02_18-30-00_PST_Amanda_W.mp4"]["ownership_detail"])["reason"]
    assert t.calls == []


def test_spot_checked_filename_sender_and_date(cfg, db, named_export):
    cfg.marco_polo.ownership_rules = [
        OwnershipMetadataRule("filename", "sender", ["Amanda W"], spot_checked=True)
    ]
    run(cfg, db)
    src = by_name(db)
    assert src["2025-01-02_18-30-00_PST_Amanda_W.mp4"]["ownership"] == "owner"
    assert src["2025-01-03_09-00-00_PST_Evelyn_E.mp4"]["status"] == "excluded"
    rec = db.all_records()[0]
    assert (rec["machine_date"], rec["machine_time"], rec["machine_timezone"], rec["machine_confidence"]) == (
        "2025-01-02", "18:30:00", "UTC-08:00", "exact")
    assert json.loads(rec["timestamp_evidence"])["tz_abbreviation_as_written"] == "PST"
    assert "filename:sender=Amanda W" in rec["speaker_verification"]


def test_unverified_filename_sender_confirmed_by_voice(cfg, db, named_export, tmp_path):
    for i in range(3):
        make_video(tmp_path / "samples" / "me" / f"me{i}.mp4", seconds=3 + i, freqs=(OWNER_HZ,))
    cfg.voice.enabled = True
    cfg.voice.owner_samples_dir = "samples/me"
    cfg.marco_polo.ownership_rules = [OwnershipMetadataRule("filename", "sender", ["Amanda W"])]
    run(cfg, db, embedder=FakeEmbedder())
    src = by_name(db)
    assert src["2025-01-02_18-30-00_PST_Amanda_W.mp4"]["ownership"] == "owner"
    assert src["2025-01-03_09-00-00_PST_Evelyn_E.mp4"]["ownership"] == "other"
    assert "confirmed by voice" in db.all_records()[0]["speaker_verification"]


def test_inspect_lists_filename_senders(cfg, db, named_export):
    from pha.marco_polo.inspect import inspect_export, render_markdown

    report = inspect_export(cfg)
    fm = report["filename_metadata"]
    assert fm["senders"] == {"Amanda W": 1, "Evelyn E": 1}
    assert fm["timezone_abbreviations"] == {"PST": 2}
    assert "filename:timestamp" in report["date_fields"]
    assert "**Amanda W**" in render_markdown(report)
