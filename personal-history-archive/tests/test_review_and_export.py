import json
import re

import pytest

from conftest import OLD, FakeTranscriber, make_video
from pha.export import build_records, export_archive, transcript_path
from pha.marco_polo.pipeline import MarcoPoloPipeline
from pha.review.app import create_app


@pytest.fixture
def populated(cfg, db, tmp_path):
    make_video(tmp_path / "exports" / "mine.mp4", mtime=OLD)
    make_video(tmp_path / "exports" / "unknown.mp4", seconds=3, mtime=OLD)
    from conftest import write_json
    from pha.config import OwnershipMetadataRule

    write_json(tmp_path / "exports" / "mine.json", {"sender": "me"})
    cfg.marco_polo.ownership_rules = [OwnershipMetadataRule("sidecar", "sender", ["me"])]
    t = FakeTranscriber()
    MarcoPoloPipeline(cfg, db, transcriber_factory=lambda: t).run()
    return db


def _client(cfg, db):
    app = create_app(cfg, db)
    app.config["TESTING"] = True
    client = app.test_client()
    html = client.get("/").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    return client, token


def test_review_ui_flow(cfg, populated):
    db = populated
    client, token = _client(cfg, db)
    rec = db.all_records()[0]
    unknown = [s for s in db.sources() if s["filename"] == "unknown.mp4"][0]

    for url in ["/", "/queue", "/queue?kind=date", "/records", "/records?show=undated",
                f"/record/{rec['record_id']}", f"/source/{unknown['source_id']}"]:
        assert client.get(url).status_code == 200, url
    assert client.get(f"/media/source/{rec['source_id']}").status_code == 200
    assert client.get("/media/source/nope").status_code == 404

    # POST without the token is refused.
    assert client.post(f"/record/{rec['record_id']}/approve").status_code == 403

    r = client.post(f"/record/{rec['record_id']}/correct", data={
        "csrf_token": token, "date": "2019-05-04", "time": "", "timezone": "",
        "timestamp_confidence": "exact", "transcript": "Um, hi Mom", "note": "listened to video",
    })
    assert r.status_code == 302
    row = db.get_record(rec["record_id"])
    assert row["corrected_date"] == "2019-05-04" and row["corrected_transcript"] == "Um, hi Mom"
    assert row["raw_transcript"].startswith("Um, so I-")  # machine version kept

    client.post(f"/record/{rec['record_id']}/approve", data={"csrf_token": token})
    assert db.open_review_count(rec["record_id"]) == 0

    client.post(f"/source/{unknown['source_id']}/ownership", data={"csrf_token": token, "decision": "other"})
    assert db.get_source(unknown["source_id"])["ownership"] == "other"

    assert client.post("/export", data={"csrf_token": token}).status_code == 302
    data = json.loads((cfg.export_path / "archive.json").read_text())
    assert data["records"][0]["transcript"] == "Um, hi Mom"
    assert data["records"][0]["metadata"]["machine"]["transcript"].startswith("Um, so I-")


def test_uncertain_videos_never_exported_even_if_transcribed(cfg, db, tmp_path):
    make_video(tmp_path / "exports" / "unknown.mp4", mtime=OLD)
    cfg.marco_polo.transcribe_uncertain = True
    MarcoPoloPipeline(cfg, db, transcriber_factory=FakeTranscriber).run()
    assert len(db.all_records()) == 1
    assert build_records(db) == []


def test_partial_dates_and_undated_paths(tmp_path):
    rec = {"date": "1998-03", "time": None, "source_type": "journal", "record_id": "jr-x-p0001-00"}
    assert transcript_path(tmp_path, rec).parts[-3:-1] == ("1998", "03")
    rec["date"] = "1998"
    assert transcript_path(tmp_path, rec).parts[-3:-1] == ("1998", "unknown-month")
    rec["date"] = None
    assert transcript_path(tmp_path, rec).parent.name == "undated"


def test_clearing_a_wrong_date_makes_record_undated(cfg, populated):
    db = populated
    rec = db.all_records()[0]
    db.apply_correction(rec["record_id"], "date", "2001-01-01")
    db.apply_correction(rec["record_id"], "date", "")
    out = export_archive(db, cfg.export_path)
    assert out["undated"] == 1
    hist = db.conn.execute("SELECT field, old_value, new_value FROM corrections").fetchall()
    assert [tuple(h) for h in hist] == [("date", None, "2001-01-01"), ("date", "2001-01-01", "")]


def test_pipelines_cannot_write_manual_fields(db):
    with pytest.raises(ValueError):
        db.upsert_machine_record("x", corrected_transcript="nope")


def test_real_voice_encoder_on_synthetic_speakers(cfg, db, tmp_path):
    """The real pretrained encoder, end to end, on synthetic (flite) voices.

    This checks the plumbing and decision logic with a genuine speaker
    model. It says nothing about accuracy on real recordings.
    """
    pytest.importorskip("resemblyzer")
    from conftest import make_speech_video
    from pha.voice import build_profiles, calibrate, make_embedder

    lines = [
        "Um so I was thinking we should go to the park tomorrow if it does not rain",
        "Hi Mom it is me again I just wanted to tell you about my day at school",
        "Okay so the thing is I forgot my keys and I had to wait outside for an hour",
        "Happy birthday I hope you have the best day ever and eat a lot of cake",
        "I am driving home now and the traffic is terrible as usual sorry",
    ]
    for i in range(3):
        make_speech_video(tmp_path / "samples" / "me" / f"me{i}.mp4", [("slt", lines[i])])
    make_speech_video(tmp_path / "samples" / "others" / "dad" / "d.mp4", [("rms", lines[0])])
    make_speech_video(tmp_path / "samples" / "others" / "bro" / "b.mp4", [("awb", lines[1])])
    exp = tmp_path / "exports"
    make_speech_video(exp / "new_me.mp4", [("slt", lines[3]), ("slt", lines[4])], mtime=OLD)
    make_speech_video(exp / "dad.mp4", [("rms", lines[3]), ("rms", lines[4])], mtime=OLD)
    make_speech_video(exp / "mixed.mp4", [("slt", lines[3]), ("rms", lines[4])], mtime=OLD)

    cfg.voice.enabled = True
    cfg.voice.owner_samples_dir = "samples/me"
    cfg.voice.other_samples_dir = "samples/others"
    profiles = build_profiles(cfg.voice, tmp_path, cfg.cache_path, make_embedder(cfg.voice))
    cal = calibrate(profiles)
    assert cal["owner_samples"] == 3 and cal["separable"], cal
    cfg.voice.accept_threshold = cal["suggested_accept_threshold"]
    cfg.voice.reject_threshold = cal["suggested_reject_threshold"]

    MarcoPoloPipeline(cfg, db, transcriber_factory=FakeTranscriber).run()
    own = {s["filename"]: s["ownership"] for s in db.sources()}
    detail = {s["filename"]: json.loads(s["ownership_detail"]) for s in db.sources()}
    assert own["new_me.mp4"] == "owner", detail["new_me.mp4"]
    assert own["dad.mp4"] == "other", detail["dad.mp4"]
    assert own["mixed.mp4"] != "owner", detail["mixed.mp4"]



def test_whisper_gets_decoded_samples_not_a_path(tmp_path, monkeypatch):
    """faster-whisper's PyAV decoder fails with newer PyAV; the wrapper must bypass it."""
    import subprocess

    import faster_whisper
    import numpy as np

    from pha.config import TranscriptionConfig
    from pha.transcribe import FasterWhisperTranscriber

    seen = {}

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, audio, **kw):
            seen["audio"] = audio
            return iter([]), type("Info", (), {"language": "en"})()

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1",
                    "-ar", "16000", "-ac", "1", str(wav)], check=True)
    FasterWhisperTranscriber(TranscriptionConfig()).transcribe(wav)
    assert isinstance(seen["audio"], np.ndarray) and seen["audio"].dtype == np.float32
    assert len(seen["audio"]) == 16000
