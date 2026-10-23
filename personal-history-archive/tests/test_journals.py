import json
import shutil

import pytest

from conftest import FakeVision, make_pdf
from pha.config import Config
from pha.export import export_archive
from pha.journals import drive as gdrive
from pha.journals.entries import parse_written_date, parse_written_time, split_entries, year_hints
from pha.journals.evaluate import evaluate, score_pair
from pha.journals.pipeline import JournalPipeline
from pha.journals.vision import AnthropicBackend, CloudNotAuthorized, ManualBackend, OllamaBackend
from pha.runtime import sha256_file

PAGE1 = """=== ENTRY ===
Wednesday, March 4th, 1998
Dear Diary, today we went to the libary and I got
a [?bok?] about horses. It was [illegible] fun.
=== ENTRY ===
March 5
Mom said no."""
PAGE2 = """and then I cryed for a long time.
=== ENTRY ===
3/7/98 7:30 pm
Saturday. Pizza night!!"""
PAGE3 = """=== ENTRY ===
I dont know what day it is.
School is boring."""


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize(
    "text,expected,confidence",
    [
        ("Wednesday, March 4th, 1998", "1998-03-04", "exact"),
        ("4 March 98", "1998-03-04", "exact"),
        ("3/4/98", "1998-03-04", "exact"),
        ("March 1998", "1998-03", "exact"),
        ("march 4", "1998-03-04", "inferred"),  # year from folder name
        ("Sept. 9 1999", "1999-09-09", "exact"),
    ],
)
def test_written_dates(text, expected, confidence):
    found = parse_written_date(text, "MDY", [1998])
    assert (found.date, found.confidence) == (expected, confidence)


def test_dates_without_year_and_ambiguous_folder_stay_undated():
    found = parse_written_date("March 4", "MDY", [1998, 1999])
    assert found.date is None and found.needs_review


def test_weekday_mismatch_and_invalid_dates_flagged():
    assert parse_written_date("Monday March 4, 1998", "MDY", []).needs_review
    assert parse_written_date("Feb 30 2000", "MDY", []).date is None


def test_dmy_order():
    assert parse_written_date("3/4/98", "DMY", [1998]).date == "1998-04-03"


def test_times_only_when_written():
    assert parse_written_time("3/7/98 7:30 pm") == ("19:30", [])
    assert parse_written_time("at 9am") == ("09:00", [])
    assert parse_written_time("8:15") == ("08:15", ["am/pm not written"])
    assert parse_written_time("we got 3 cookies") == (None, [])


def test_year_hints():
    assert year_hints("1 journals", "1998-1999", "Journal 2001.pdf") == [1998, 1999, 2001]


def test_entry_splitting_across_pages():
    entries = split_entries([(1, PAGE1), (2, PAGE2), (3, PAGE3)])
    assert [(e.start_page, e.end_page) for e in entries] == [(1, 1), (1, 2), (2, 2), (3, 3)]
    assert entries[1].text.endswith("and then I cryed for a long time.")


def test_header_detection_without_markers():
    entries = split_entries([(1, "March 4, 1998\nhello\nMarch 5, 1998\nbye")])
    assert [e.text.splitlines()[0] for e in entries] == ["March 4, 1998", "March 5, 1998"]


# ----------------------------------------------------------------- pipeline
def _setup(cfg: Config, tmp_path):
    jdir = tmp_path / "journals" / "1998"
    pdf = make_pdf(jdir / "journal 1998 part 1.pdf", ["page one text", "page two text", "page three"])
    return pdf


def _vision(source_id: str) -> FakeVision:
    return FakeVision({f"{source_id}/p0001": PAGE1, f"{source_id}/p0002": PAGE2, f"{source_id}/p0003": PAGE3})


def test_journal_pipeline_records(cfg, db, tmp_path):
    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    vision = _vision(sid)
    JournalPipeline(cfg, db, backend_factory=lambda: vision).run(source="local")
    recs = sorted(db.all_records(), key=lambda r: r["record_id"])
    got = [(r["page_number"], r["page_end"], r["machine_date"], r["machine_time"], r["machine_confidence"]) for r in recs]
    assert got == [
        (1, 1, "1998-03-04", None, "exact"),
        (1, 2, "1998-03-05", None, "inferred"),
        (2, 2, "1998-03-07", "19:30", "exact"),
        (3, 3, None, None, "unknown"),
    ]
    first = recs[0]
    assert "libary" in first["raw_transcript"] and "[?bok?]" in first["raw_transcript"]  # spelling kept
    assert first["source_location"] == str(pdf.resolve())
    reasons = {(i["kind"], i["record_id"]): i["reason"] for i in db.review_items()}
    assert reasons[("transcription", first["record_id"])].startswith("2 illegible/uncertain")
    assert reasons[("date", recs[3]["record_id"])] == "no date written at the start of this entry"

    # Second run: nothing re-transcribed.
    vision2 = _vision(sid)
    JournalPipeline(cfg, db, backend_factory=lambda: vision2).run(source="local")
    assert vision2.calls == []


def test_page_level_resume(cfg, db, tmp_path):
    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]

    class Flaky(FakeVision):
        def transcribe(self, image_path):
            if image_path.stem == "p0002":
                raise ConnectionError("model server went away")
            return super().transcribe(image_path)

    JournalPipeline(cfg, db, backend_factory=lambda: Flaky(_vision(sid).script)).run(source="local")
    assert db.get_source(sid)["status"] == "failed"
    v = _vision(sid)
    JournalPipeline(cfg, db, backend_factory=lambda: v).run(source="local")
    assert [p.stem for p in v.calls] == ["p0002"]
    assert db.get_source(sid)["status"] == "done"
    assert len(db.all_records()) == 4


def test_duplicate_scans_flagged_not_deleted(cfg, db, tmp_path):
    pdf = _setup(cfg, tmp_path)
    copy = tmp_path / "journals" / "backup" / pdf.name
    copy.parent.mkdir(parents=True)
    shutil.copy2(pdf, copy)
    # A re-scan of page 2 at a different resolution, inside another PDF.
    rescan = make_pdf(tmp_path / "journals" / "1998" / "rescan.pdf", ["page one text", "page two text"], scale=1.3)
    sid = "jr-" + sha256_file(pdf)[:16]
    rid = "jr-" + sha256_file(rescan)[:16]
    script = {**_vision(sid).script, f"{rid}/p0001": "unrelated words entirely here", f"{rid}/p0002": PAGE2}
    JournalPipeline(cfg, db, backend_factory=lambda: FakeVision(script)).run(source="local")
    assert len(db.source_locations(sid)) == 2  # identical file: one source, two locations
    dup = [i for i in db.review_items("open", "duplicate")]
    reasons = {i["reason"] for i in dup}
    assert any("page 2 looks like page 2 of rescan.pdf" in r for r in reasons)
    assert not any("page 1 looks like" in r for r in reasons)  # same layout, different text
    assert pdf.exists() and copy.exists() and rescan.exists()


def test_manual_backend_creates_pages_for_typing(cfg, db, tmp_path):
    _setup(cfg, tmp_path)
    JournalPipeline(cfg, db, backend_factory=ManualBackend).run(source="local")
    recs = db.all_records()
    assert len(recs) == 3 and {r["transcription_status"] for r in recs} == {"manual_needed"}
    rid = recs[0]["record_id"]
    db.apply_correction(rid, "transcript", "typed by hand")
    db.apply_correction(rid, "date", "1998-03-04")
    db.apply_correction(rid, "timestamp_confidence", "exact")
    summary = export_archive(db, cfg.export_path)
    assert summary["dated"] == 1 and summary["undated"] == 2


def test_cloud_backends_refused_without_authorization(cfg):
    with pytest.raises(CloudNotAuthorized):
        AnthropicBackend(cfg)
    cfg.vision.ollama_url = "http://192.168.1.20:11434"
    with pytest.raises(CloudNotAuthorized):
        OllamaBackend(cfg)
    cfg.vision.ollama_url = "http://localhost:11434"
    OllamaBackend(cfg)


def test_evaluation_metrics(cfg, db, tmp_path):
    assert score_pair("I cryed", "I cryed")["cer"] == 0
    s = score_pair("I cryed a lot", "I cried a lot")
    assert s["cer"] > 0 and s["wer"] == 0.25
    assert score_pair("a bok", "a [?bok?]")["cer"] == 0  # best guess is scored

    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    JournalPipeline(cfg, db, backend_factory=lambda: _vision(sid)).run(source="local")
    truth = tmp_path / "truth"
    truth.mkdir()
    (truth / "journal 1998 part 1__p3.txt").write_text("I dont know what day it is.\nSchool is boring.")
    result = evaluate(db, truth)
    assert result["pages_scored"] == 1 and result["weighted_cer"] == 0


# ------------------------------------------------------------------- drive
class FakeDrive:
    """Minimal stand-in for the Drive v3 files() resource."""

    def __init__(self, files):
        self.files_by_id = {f["id"]: f for f in files}
        self.queries = []

    def files(self):
        return self

    def list(self, q, **kw):
        self.queries.append(q)
        if q.startswith("name = "):
            res = [f for f in self.files_by_id.values() if f["name"] == "1 journals"]
        else:
            parent = q.split("'")[1]
            res = [f for f in self.files_by_id.values() if parent in f.get("parents", [])]
        return _Exec({"files": res})

    def get(self, fileId, **kw):
        return _Exec(self.files_by_id[fileId])


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


def test_drive_walk_follows_folders_and_shortcuts():
    svc = FakeDrive([
        {"id": "root", "name": "1 journals", "mimeType": gdrive.FOLDER_MIME},
        {"id": "y98", "name": "1998", "mimeType": gdrive.FOLDER_MIME, "parents": ["root"]},
        {"id": "f1", "name": "jan.pdf", "mimeType": gdrive.PDF_MIME, "parents": ["y98"], "md5Checksum": "x"},
        {"id": "s1", "name": "shortcut", "mimeType": gdrive.SHORTCUT_MIME, "parents": ["root"],
         "shortcutDetails": {"targetId": "f2", "targetMimeType": gdrive.PDF_MIME}},
        {"id": "f2", "name": "loose.pdf", "mimeType": gdrive.PDF_MIME, "parents": ["elsewhere"]},
        {"id": "n1", "name": "notes.txt", "mimeType": "text/plain", "parents": ["root"]},
    ])
    folders = gdrive.find_folders(svc, "1 journals")
    files = list(gdrive.walk_pdfs(svc, folders[0]["id"], ["1 journals"]))
    assert sorted(f.display_path for f in files) == ["1 journals/1998/jan.pdf", "1 journals/loose.pdf"]
    assert gdrive.SCOPES == ["https://www.googleapis.com/auth/drive.readonly"]


def test_drive_token_with_broader_scope_refused(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive"],
    }))
    with pytest.raises(RuntimeError, match="only drive.readonly"):
        gdrive.get_service(tmp_path / "client_secret.json", token)


def test_ollama_sends_large_context_and_detects_cutoff(cfg, tmp_path, monkeypatch):
    import pha.journals.vision as vision

    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "```\nDear Diary, today we\n```", "done_reason": "length"}

    def fake_post(url, json, timeout):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(vision.requests, "post", fake_post)
    img = tmp_path / "p.png"
    img.write_bytes(b"png")
    result = OllamaBackend(cfg).transcribe(img)
    assert sent["options"]["num_ctx"] == 16384 and sent["options"]["num_predict"] == 8192
    assert result.truncated and result.text == "Dear Diary, today we"


def test_cut_off_page_is_queued_for_review(cfg, db, tmp_path):
    from pha.journals.vision import PageTranscription

    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    script = _vision(sid).script

    class CutOff(FakeVision):
        def transcribe(self, image_path):
            r = super().transcribe(image_path)
            return PageTranscription(r.text, r.backend, r.model, truncated=image_path.stem == "p0003")

    JournalPipeline(cfg, db, backend_factory=lambda: CutOff(script)).run(source="local")
    items = [i for i in db.review_items("open", "transcription") if "cut off" in i["reason"]]
    assert len(items) == 1
    assert db.get_record(items[0]["record_id"])["page_number"] == 3


def test_each_page_is_reported_as_it_finishes(cfg, db, tmp_path, caplog):
    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    with caplog.at_level("INFO", logger="pha"):
        JournalPipeline(cfg, db, backend_factory=lambda: _vision(sid)).run(source="local")
    assert "journal 1998 part 1.pdf page 1/3: transcribed (" in caplog.text
    assert "page 3/3" in caplog.text


def test_pages_cached_as_jpeg(cfg, db, tmp_path):
    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    JournalPipeline(cfg, db, backend_factory=lambda: _vision(sid)).run(source="local")
    paths = [r["image_path"] for r in db.conn.execute("SELECT image_path FROM journal_pages")]
    assert paths and all(p.endswith(".jpg") for p in paths)
    with open(paths[0], "rb") as fh:
        assert fh.read(3) == b"\xff\xd8\xff"  # JPEG signature


@pytest.mark.parametrize("problem", ["ollama_down", "disk_full"])
def test_run_stops_instead_of_failing_every_page(cfg, db, tmp_path, problem):
    import errno

    from pha.journals.pipeline import RunAborted
    from pha.journals.vision import BackendUnavailable

    pdf = _setup(cfg, tmp_path)
    sid = "jr-" + sha256_file(pdf)[:16]
    script = _vision(sid).script

    class Breaks(FakeVision):
        def transcribe(self, image_path):
            if image_path.stem == "p0002":
                if problem == "ollama_down":
                    raise BackendUnavailable("Cannot reach Ollama")
                raise OSError(errno.ENOSPC, "No space left on device")
            return super().transcribe(image_path)

    with pytest.raises(RunAborted):
        JournalPipeline(cfg, db, backend_factory=lambda: Breaks(script)).run(source="local")
    statuses = dict(db.conn.execute("SELECT page_number, status FROM journal_pages").fetchall())
    assert statuses[1] == "done" and statuses.get(2) != "failed"
    assert db.get_source(sid)["status"] == "pending"

    v = _vision(sid)
    JournalPipeline(cfg, db, backend_factory=lambda: v).run(source="local")
    assert [p.stem for p in v.calls] == ["p0002", "p0003"]
    assert db.get_source(sid)["status"] == "done"


def test_ollama_connection_error_becomes_backend_unavailable(cfg, tmp_path, monkeypatch):
    import pha.journals.vision as vision

    def refuse(*a, **kw):
        raise vision.requests.ConnectionError("refused")

    monkeypatch.setattr(vision.requests, "post", refuse)
    img = tmp_path / "p.jpg"
    img.write_bytes(b"x")
    with pytest.raises(vision.BackendUnavailable, match="Is the Ollama app running"):
        OllamaBackend(cfg).transcribe(img)
