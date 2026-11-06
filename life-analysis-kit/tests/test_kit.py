import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import synth  # noqa: E402

KIT = Path(__file__).resolve().parents[1]
TEMPLATE = KIT / "template"
PY = sys.executable


def run(root: Path, *cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, "LIFE_ANALYSIS_ROOT": str(root)}
    return subprocess.run([PY, *cmd], cwd=root, env=env, capture_output=True, text=True, check=check)


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    r = tmp_path_factory.mktemp("life") / "life-analysis"
    shutil.copytree(TEMPLATE, r)
    for d in ("raw", "private", "work", "out"):
        (r / d).mkdir(exist_ok=True)
    synth.write_archive(r / "raw" / "archive.json")
    (r / "private" / "names_input.csv").write_text(synth.NAMES_CSV, encoding="utf-8")
    run(r, "tools/pseudonymize.py")
    run(r, "work/scripts/02_manifest.py")
    run(r, "work/scripts/04_chunk.py")
    run(r, "work/scripts/05_eras.py")
    return r


def docs(root: Path) -> list[dict]:
    return [json.loads(l) for l in (root / "work" / "docs_pseudo.jsonl").read_text().splitlines()]


def test_planted_names_and_identifiers_are_gone(root):
    blob = (root / "work" / "docs_pseudo.jsonl").read_text() + (root / "work" / "pseudonymization_report.json").read_text()
    for planted in synth.PLANTED:
        assert planted.lower() not in blob.lower(), planted
    text = " ".join(d["text"] for d in docs(root))
    for tok in ("[SUBJECT]", "[PERSON_001]", "[PARTNER]", "[CHILD_1]", "[WORKPLACE_01]", "[SCHOOL_01]", "[CITY_01]",
                "[EMAIL_01]", "[PHONE_01]", "[URL_01]", "[HANDLE_01]", "[ADDRESS_01]"):
        assert tok in text, tok


def test_case_sensitive_name_only_matches_exact_case(root):
    t = next(d["text"] for d in docs(root) if "[EMAIL_01]" in d["text"])
    assert "I hope [PERSON_002] is fine" in t  # 'hope' the word stays, 'Hope' the name goes


def test_no_filenames_or_paths_leak_into_documents(root):
    for d in docs(root):
        assert set(d) >= {"doc_id", "kind", "date", "text", "source_label", "quality"}
        assert "source_filename" not in d and "source_location" not in d and "record_id" not in d
    labels = {d["source_label"] for d in docs(root) if d["kind"] == "journal"}
    assert labels == {"[SUBJECT] trip to [CITY_01]"}


def test_unlisted_names_are_caught_automatically(root):
    text = " ".join(d["text"] for d in docs(root))
    assert "Bronwyn" not in text and "Zelda" not in text      # never in the names list
    assert re.search(r"\[NAME_\d{4}\] came over later", text)   # sentence-start-only name
    assert re.search(r"then \[NAME_\d{4}\] laughed at", text, re.I)
    # ordinary capitalised words are left alone
    assert "Anyway" in text and "Deadline" in text and text.count("[NAME_") < 40
    rep = json.loads((root / "work" / "pseudonymization_report.json").read_text())
    assert rep["automatic_catch_all"] and rep["auto_name_groups"] >= 3 and rep["empty_documents_skipped"] == 1
    assert "Bronwyn" not in json.dumps(rep)
    key = json.loads((root / "private" / "key.json").read_text())
    assert any("Bronwyn" in seen for tok, seen in key.items() if tok.startswith("NAME_"))


def test_variants_and_full_names_share_a_token_but_lookalikes_do_not(root):
    key = json.loads((root / "private" / "key.json").read_text())
    holders = {t: set(seen) for t, seen in key.items() if t.startswith("NAME_")}
    odessa = [t for t, seen in holders.items() if "Odessa" in seen]
    assert len(odessa) == 1 and {"Odessa", "Brandt", "Odesa"} <= holders[odessa[0]]
    sara = [t for t, seen in holders.items() if "Sara" in seen]
    sarah = [t for t, seen in holders.items() if "Sarah" in seen]
    assert sara and sarah and sara != sarah                      # two frequent look-alikes stay apart
    groups = list(csv.DictReader(open(root / "private" / "auto_groups.csv")))
    assert any("Odesa" in g["words_grouped_together"] and "Brandt" in g["words_grouped_together"] for g in groups)


def test_without_auto_the_unlisted_name_is_only_reported_privately(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    for d in ("raw", "private", "work"):
        (r / d).mkdir(exist_ok=True)
    synth.write_archive(r / "raw" / "archive.json")
    (r / "private" / "names_input.csv").write_text(synth.NAMES_CSV, encoding="utf-8")
    run(r, "tools/pseudonymize.py", "--no-auto")
    assert "Bronwyn" in (r / "work" / "docs_pseudo.jsonl").read_text()
    cands = {x["word"] for x in csv.DictReader(open(r / "private" / "residual_candidates.csv"))}
    assert "Bronwyn" in cands


def test_not_names_file_protects_words(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    for d in ("raw", "private", "work"):
        (r / d).mkdir(exist_ok=True)
    synth.write_archive(r / "raw" / "archive.json")
    (r / "private" / "names_input.csv").write_text(synth.NAMES_CSV, encoding="utf-8")
    (r / "private" / "not_names.txt").write_text("Zelda\n")
    run(r, "tools/pseudonymize.py")
    text = (r / "work" / "docs_pseudo.jsonl").read_text()
    assert "Zelda came over later" in text and "Bronwyn" not in text


def test_rehydrate_restores_real_names(root):
    (root / "out").mkdir(exist_ok=True)
    (root / "out" / "note.md").write_text("[PERSON_001] met [SUBJECT] in [CITY_01]; call [PHONE_01].", encoding="utf-8")
    run(root, "tools/rehydrate.py")
    text = (root / "out_real" / "note.md").read_text()
    assert "[" not in text and "Duluth" in text and "867-5309" in text


def test_conflicting_aliases_are_rejected(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    for d in ("raw", "private", "work"):
        (r / d).mkdir(exist_ok=True)
    synth.write_archive(r / "raw" / "archive.json")
    (r / "private" / "names_input.csv").write_text("name,category,token,aliases,case_sensitive\nAnn,PERSON,,Al,\nBob,PERSON,,Al,\n")
    p = run(r, "tools/pseudonymize.py", check=False)
    assert p.returncode != 0 and "two different tokens" in (p.stderr + p.stdout)


def test_chunk_ids_dates_and_splitting(root):
    chunks = [json.loads(l) for l in (root / "work" / "chunks.jsonl").read_text().splitlines()]
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert re.fullmatch(r"[CJ]-(\d{4}-\d{2}-\d{2}|UNDATED)-\d{2,}", c["chunk_id"]), c["chunk_id"]
        assert c["words"] <= 1200
    assert any(re.fullmatch(r"J-2005-03-00-\d+", i) for i in ids)       # month precision keeps 00
    assert any(re.fullmatch(r"J-2005-00-00-\d+", i) for i in ids)       # year precision
    assert any(i.startswith("J-UNDATED-") for i in ids)                   # undated stays undated
    long_parts = [c for c in chunks if c["date"] == "2019-06-15"]
    assert len(long_parts) == 3 and [c["part"] for c in long_parts] == [1, 2, 3]
    index = json.loads((root / "work" / "batches" / "index.json").read_text())
    assert sum(b["chunks"] for b in index) == len(chunks)


def test_search_tool(root):
    p = run(root, "work/scripts/search.py", "nursery", "--kind", "chat", "--from", "2020-01", "--limit", "3")
    lines = p.stdout.strip().splitlines()
    assert lines and all(l.startswith("C-2020-") for l in lines)
    cid = lines[0].split()[0]
    assert cid in run(root, "work/scripts/search.py", "--show", cid).stdout


def test_manifest_matches_documents(root):
    m = json.loads((root / "work" / "manifest.json").read_text())
    assert m["documents"] == len(docs(root))
    assert (root / "out" / "01_manifest.md").exists()


def test_era_boundary_found_near_the_planted_shift(root):
    eras = json.loads((root / "work" / "eras.json").read_text())
    starts = [e["start"] for e in eras]
    assert any("2019-10" <= s <= "2020-04" for s in starts), starts


def test_budget_and_quantitative_scripts_run(root):
    run(root, "work/scripts/06_budget.py")
    assert "Standard" in (root / "out" / "03_budget.md").read_text()
    for script in ("10_volume_silence.py", "11_language.py", "12_people.py", "13_topics.py"):
        run(root, f"work/scripts/{script}")
    assert (root / "work" / "language_metrics.csv").exists()
    people = (root / "work" / "people_summary.csv").read_text()
    assert "[PERSON_001]" in people and "[EMAIL_01]" not in people


def test_extraction_validator_rejects_invented_quotes(root):
    sys.path.insert(0, str(TEMPLATE / "work" / "scripts"))
    import importlib
    v = importlib.import_module("07_validate_extractions")
    text = "I told [PERSON_001] that I will start running next week. It felt good."
    good = {"chunk_id": "C-1", "emotions": [{"label": "pride", "intensity": 2, "evidence_quote": "It felt good"}],
            "people": [{"token": "[PERSON_001]", "role_in_text": "friend", "valence_toward": 1, "context": "support_given"}],
            "commitments": [{"quote": "I will start running next week", "kind": "start", "horizon": "week"}],
            "agency": {"locus": "internal", "self_blame": 0, "externalizing": 0},
            "conflict": {"present": False, "role": "none", "repair_attempt": False},
            "sensitive_flag": "none", "risk_flag": False, "salience": 1, "notes": "ok"}
    assert v.validate_record(good, text) == []
    bad = json.loads(json.dumps(good))
    bad["commitments"][0]["quote"] = "I will quit my job tomorrow"
    bad["people"][0]["token"] = "[PERSON_009]"
    errs = v.validate_record(bad, text)
    assert any("quote not found" in e for e in errs) and any("token" in e for e in errs)


def test_validate_and_aggregate_end_to_end(root):
    batch = next((root / "work" / "batches").glob("B-0001.jsonl"))
    rows = [json.loads(l) for l in batch.read_text().splitlines()]
    recs = []
    for r in rows[:4]:
        words = r["text"].split()
        quote = " ".join(words[:5])
        recs.append({"chunk_id": r["chunk_id"], "emotions": [], "topics": ["work"], "people": [],
                     "commitments": [{"quote": quote, "kind": "will_do", "horizon": "soon"}],
                     "predictions": [], "advice_given": [], "self_descriptions": [], "reception_cues": [], "values": [],
                     "agency": {"locus": "mixed", "self_blame": 1, "externalizing": 0},
                     "conflict": {"present": False, "role": "none", "repair_attempt": False},
                     "sensitive_flag": "none", "risk_flag": False, "salience": 2, "notes": "x"})
    recs[3]["commitments"][0]["quote"] = "this sentence is invented by the sub agent"
    (root / "work" / "extractions").mkdir(exist_ok=True)
    (root / "work" / "extractions" / "B-0001.json").write_text(json.dumps(recs))
    out = json.loads(run(root, "work/scripts/07_validate_extractions.py").stdout.splitlines()[0])
    assert out == {"accepted": 3, "rejected": 1, "files_with_rejections": 1}
    assert (root / "work" / "extractions_rejected" / "B-0001.json").exists()
    run(root, "work/scripts/20_aggregate.py")
    assert len(list(csv.DictReader(open(root / "work" / "aggregates" / "promise_ledger.csv")))) == 3
    assert run(root, "work/scripts/20_aggregate.py", "--compact").stdout.count("\n") == 3


def test_analysis_scripts_cannot_reach_private_data_or_network():
    banned = ("private", "out_real", "requests", "urllib", "socket", "http.client", "subprocess", "os.system")
    for path in list((TEMPLATE / "work" / "scripts").rglob("*.py")):
        text = path.read_text()
        for word in banned:
            assert word not in text, f"{path.name} mentions {word}"
    for path in (TEMPLATE / "tools").glob("*.py"):
        for word in ("requests", "urllib", "socket", "http.client"):
            assert word not in path.read_text(), f"{path.name} mentions {word}"


def test_settings_deny_rules_cover_the_brief():
    deny = json.loads((TEMPLATE / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    for rule in ("WebFetch", "WebSearch", "Bash(curl:*)", "Bash(wget:*)", "Read(./private/**)", "Edit(./raw/**)",
                 "Write(./raw/**)", "Read(./out_real/**)", "Bash(python tools/*)"):
        assert rule in deny


def test_setup_script_refuses_synced_folders_and_makes_raw_readonly(tmp_path):
    archive = tmp_path / "archive.json"
    synth.write_archive(archive)
    bad = subprocess.run(["bash", str(KIT / "setup.sh"), str(tmp_path / "Dropbox" / "x"), str(archive)], capture_output=True, text=True)
    assert bad.returncode != 0 and "synced" in bad.stdout
    dest = tmp_path / "life"
    ok = subprocess.run(["bash", str(KIT / "setup.sh"), str(dest), str(archive)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert not ((dest / "raw" / "archive.json").stat().st_mode & 0o222)
    assert "PASS  settings.json denies WebFetch" in ok.stdout
    assert "PASS  raw/archive.json is read-only" in ok.stdout
    assert "FAIL  private/names_input.csv exists" in ok.stdout
    os.chmod(dest / "raw", 0o700)


def test_mark_up_sheet_builds_names_list_and_pseudonymizes(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    for d in ("raw", "private", "work"):
        (r / d).mkdir(exist_ok=True)
    synth.write_archive(r / "raw" / "archive.json")
    run(r, "tools/suggest_names.py", "--min-count", "1")
    sheet = r / "private" / "name_candidates.csv"
    rows = list(csv.reader(open(sheet, encoding="utf-8")))
    assert rows[0] == ["word", "count", "documents", "example", "category", "same_as", "case_sensitive"]
    assert rows[1][0].startswith("# HOW TO FILL THIS IN") and sum(r_[0].startswith("#") for r_ in rows) == 5
    assert (r / "private" / "names_input.csv").read_text().strip() == "name,category,token,aliases,case_sensitive"

    marks = {"Priya": ("PERSON", ""), "Pria": ("", "Priya"), "Marcus": ("PARTNER", ""),
             "Theo": ("CHILD", ""), "Duluth": ("CITY", "")}
    out = []
    for row in rows:
        row = row + [""] * (7 - len(row))
        if row[0] in marks:
            row[4], row[5] = marks[row[0]]
        out.append(row)
    assert {row[0] for row in out} >= set(marks)
    # someone missing from the sheet (here the author's own name) is added as a row at the bottom
    out += [["Dana", "", "", "", "SUBJECT", "", ""], ["Whitfield", "", "", "", "", "Dana", ""]]
    with open(sheet, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(out)
    msg = run(r, "tools/build_names.py").stdout
    assert "5 people/places added" in msg
    names = {x["name"]: x for x in csv.DictReader(open(r / "private" / "names_input.csv"))}
    assert names["Dana"]["token"] == "SUBJECT" and names["Dana"]["aliases"] == "Whitfield"
    assert names["Priya"]["aliases"] == "Pria" and names["Marcus"]["category"] == "PARTNER"
    assert "0 people/places added, 5 already listed" in run(r, "tools/build_names.py").stdout   # safe to repeat

    run(r, "tools/pseudonymize.py")
    text = " ".join(d["text"] for d in docs(r))
    assert "[PERSON_001]" in text and "Priya" not in text and "Pria" not in text
    assert "[SUBJECT]" in text and "[PARTNER_01]" in text and "[CHILD_01]" in text and "[CITY_01]" in text


def test_build_names_reports_mistakes(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    (r / "private").mkdir(exist_ok=True)
    (r / "private" / "name_candidates.csv").write_text(
        "word,count,documents,example,category,same_as,case_sensitive\n"
        "Alice,5,3,x,PEERSON,,\nAl,2,1,x,,Alicia,\n# note,,,,,,\n")
    p = run(r, "tools/build_names.py", check=False)
    assert p.returncode == 1 and "unknown category" in p.stdout and "not a word in this sheet" in p.stdout


def test_build_names_says_so_when_nothing_is_marked(tmp_path):
    r = tmp_path / "x"
    shutil.copytree(TEMPLATE, r)
    (r / "private").mkdir(exist_ok=True)
    (r / "private" / "name_candidates.csv").write_text(
        "word,count,documents,example,category,same_as,case_sensitive\nAlice,5,3,x,,,\n")
    p = run(r, "tools/build_names.py", check=False)
    assert p.returncode == 1 and "No marked rows found" in (p.stdout + p.stderr)
    assert not (r / "private" / "names_input.csv").exists()
