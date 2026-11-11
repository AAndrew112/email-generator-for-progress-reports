#!/usr/bin/env python3
"""Check sub-agent extraction files against the schema and against the source text.

Every quote must be a real passage of its chunk (so an invented quote is rejected), at most
25 words, and every person token must occur in the chunk. Rejected records move to
work/extractions_rejected/ for re-running.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import TOKEN_RE, WORK, read_jsonl  # noqa: E402

SENSITIVE = {"none", "trauma", "abuse", "self_harm", "crisis", "sexual", "health", "other_person_disclosure"}
CONTEXTS = {"support_given", "support_sought", "conflict", "logistics", "humor", "worry", "celebration", "gossip", "other"}
COMMIT_KINDS = {"start", "stop", "change", "will_do", "resolution"}
LOCUS = {"internal", "external", "mixed", "none"}
CONFLICT_ROLES = {"initiator", "recipient", "mediator", "observer", "none"}
QUOTED = {"emotions": "evidence_quote", "commitments": "quote", "predictions": "quote",
          "advice_given": "quote", "self_descriptions": "quote", "reception_cues": "quote"}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", s.lower())).strip()


def validate_record(rec: dict, chunk_text: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(rec.get("chunk_id"), str):
        return ["missing chunk_id"]
    body = norm(chunk_text)
    for field, qkey in QUOTED.items():
        for i, item in enumerate(rec.get(field) or []):
            q = item.get(qkey) if isinstance(item, dict) else None
            if not isinstance(q, str) or not q.strip():
                errs.append(f"{field}[{i}] has no {qkey}"); continue
            if len(q.split()) > 25:
                errs.append(f"{field}[{i}] quote is over 25 words")
            if norm(q) not in body:
                errs.append(f"{field}[{i}] quote not found in chunk")
    for i, p in enumerate(rec.get("people") or []):
        tok = p.get("token", "")
        if not TOKEN_RE.fullmatch(tok) or tok not in chunk_text:
            errs.append(f"people[{i}] token {tok!r} not in chunk")
        if p.get("context") not in CONTEXTS:
            errs.append(f"people[{i}] bad context")
        if p.get("valence_toward") not in (-2, -1, 0, 1, 2):
            errs.append(f"people[{i}] bad valence_toward")
    for i, c in enumerate(rec.get("commitments") or []):
        if c.get("kind") not in COMMIT_KINDS:
            errs.append(f"commitments[{i}] bad kind")
    for i, e in enumerate(rec.get("emotions") or []):
        if e.get("intensity") not in (1, 2, 3) or not isinstance(e.get("label"), str):
            errs.append(f"emotions[{i}] bad label/intensity")
    ag = rec.get("agency") or {}
    if ag.get("locus") not in LOCUS or ag.get("self_blame") not in (0, 1, 2) or ag.get("externalizing") not in (0, 1, 2):
        errs.append("agency malformed")
    cf = rec.get("conflict") or {}
    if not isinstance(cf.get("present"), bool) or cf.get("role") not in CONFLICT_ROLES:
        errs.append("conflict malformed")
    if rec.get("sensitive_flag") not in SENSITIVE:
        errs.append("sensitive_flag invalid")
    if not isinstance(rec.get("risk_flag"), bool):
        errs.append("risk_flag must be true/false")
    if rec.get("salience") not in (0, 1, 2, 3):
        errs.append("salience must be 0-3")
    if len((rec.get("notes") or "").split()) > 30:
        errs.append("notes over 30 words")
    return errs


def main() -> None:
    texts: dict[str, str] = {}
    for f in sorted((WORK / "batches").glob("B-*.jsonl")):
        for row in read_jsonl(f):
            texts[row["chunk_id"]] = row["text"]
    ext_dir, rej_dir = WORK / "extractions", WORK / "extractions_rejected"
    ok = bad = 0
    report: dict[str, list[str]] = {}
    for f in sorted(ext_dir.glob("B-*.json")):
        try:
            records = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report[f.name] = [f"invalid JSON: {exc}"]; bad += 1
            continue
        good, rejected = [], []
        for rec in records:
            errs = validate_record(rec, texts.get(rec.get("chunk_id", ""), "")) if rec.get("chunk_id") in texts else ["unknown chunk_id"]
            (rejected if errs else good).append((rec, errs))
        ok += len(good); bad += len(rejected)
        if rejected:
            rej_dir.mkdir(exist_ok=True)
            (rej_dir / f.name).write_text(json.dumps([{**r, "_errors": e} for r, e in rejected], indent=1))
            f.write_text(json.dumps([r for r, _ in good], indent=1))
            report[f.name] = [f"{r.get('chunk_id')}: {'; '.join(e)}" for r, e in rejected][:20]
    (WORK / "extraction_validation.json").write_text(json.dumps({"accepted": ok, "rejected": bad, "details": report}, indent=1))
    print(json.dumps({"accepted": ok, "rejected": bad, "files_with_rejections": len(report)}))
    if bad:
        print("Re-run the listed chunks (see work/extractions_rejected/).")


if __name__ == "__main__":
    main()
