#!/usr/bin/env python3
"""Roll validated extractions up into aggregates the lens agents read.

  python work/scripts/20_aggregate.py                  # write work/aggregates/*
  python work/scripts/20_aggregate.py --era E3 --compact   # print one era's extractions, one chunk per line
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import WORK, month_key, read_jsonl  # noqa: E402


def load() -> tuple[list[dict], dict[str, dict], list[dict]]:
    chunks = {c["chunk_id"]: c for c in read_jsonl(WORK / "chunks.jsonl")}
    ext = []
    for f in sorted((WORK / "extractions").glob("B-*.json")):
        ext += json.loads(f.read_text(encoding="utf-8"))
    eras = json.loads((WORK / "eras.json").read_text()) if (WORK / "eras.json").exists() else []
    return ext, chunks, eras


def era_of(date: str | None, eras: list[dict]) -> str:
    m = (date or "")[:7]
    return next((e["era_id"] for e in eras if e["start"] <= m <= e["end"]), "undated") if len(m) == 7 else "undated"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--era")
    ap.add_argument("--compact", action="store_true")
    a = ap.parse_args()
    ext, chunks, eras = load()

    if a.compact:
        for e in sorted(ext, key=lambda r: r["chunk_id"]):
            c = chunks.get(e["chunk_id"])
            if not c or (a.era and era_of(c["date"], eras) != a.era):
                continue
            q = lambda items, k: "; ".join(f'"{i[k]}"' for i in items[:2])  # noqa: E731
            print(f"{e['chunk_id']} s{e['salience']} flag={e['sensitive_flag']} topics={','.join(e['topics'][:4])} "
                  f"emo={','.join(x['label'] for x in e['emotions'][:4])} people={','.join(p['token'] for p in e['people'][:4])} "
                  f"locus={e['agency']['locus']} blame={e['agency']['self_blame']} conflict={e['conflict']['present']} "
                  f"commit=[{q(e['commitments'], 'quote')}] self=[{q(e['self_descriptions'], 'quote')}] note={e['notes']!r}")
        return

    out = WORK / "aggregates"
    out.mkdir(exist_ok=True)
    monthly: dict[tuple[str, str], dict] = defaultdict(lambda: {"n": 0, "conflict": 0, "repair": 0, "blame": 0,
                                                                 "ext": 0, "salience": 0, "sensitive": 0,
                                                                 "emotions": Counter()})
    ledger, people = [], defaultdict(lambda: {"n": 0, "valence": 0, "contexts": Counter()})
    for e in ext:
        c = chunks.get(e["chunk_id"])
        if not c:
            continue
        key = (month_key(c["date"]) or "undated", c["kind"])
        m = monthly[key]
        m["n"] += 1; m["conflict"] += e["conflict"]["present"]; m["repair"] += e["conflict"]["repair_attempt"]
        m["blame"] += e["agency"]["self_blame"]; m["ext"] += e["agency"]["externalizing"]
        m["salience"] += e["salience"]; m["sensitive"] += e["sensitive_flag"] != "none"
        m["emotions"].update(x["label"].lower() for x in e["emotions"])
        for cm in e["commitments"]:
            ledger.append({"chunk_id": e["chunk_id"], "date": c["date"], "kind": cm["kind"], "horizon": cm["horizon"], "quote": cm["quote"]})
        for p in e["people"]:
            people[p["token"]]["n"] += 1; people[p["token"]]["valence"] += p["valence_toward"]
            people[p["token"]]["contexts"][p["context"]] += 1
    with open(out / "monthly.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "source", "chunks", "conflict_rate", "repair_rate", "self_blame_mean", "externalizing_mean",
                    "salience_mean", "sensitive_chunks", "top_emotions"])
        for (mo, kind), m in sorted(monthly.items()):
            n = m["n"]
            w.writerow([mo, kind, n, round(m["conflict"] / n, 3), round(m["repair"] / n, 3), round(m["blame"] / n, 3),
                        round(m["ext"] / n, 3), round(m["salience"] / n, 3), m["sensitive"],
                        ";".join(f"{k}:{v}" for k, v in m["emotions"].most_common(5))])
    with open(out / "promise_ledger.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["chunk_id", "date", "kind", "horizon", "quote"])
        w.writeheader(); w.writerows(sorted(ledger, key=lambda r: r["chunk_id"]))
    (out / "people_valence.json").write_text(json.dumps(
        {t: {"mentions": p["n"], "mean_valence": round(p["valence"] / p["n"], 2), "contexts": dict(p["contexts"])}
         for t, p in sorted(people.items(), key=lambda kv: -kv[1]["n"])}, indent=1))
    print(f"{len(ext)} extractions; {len(ledger)} commitments; {len(people)} people tokens")


if __name__ == "__main__":
    main()
