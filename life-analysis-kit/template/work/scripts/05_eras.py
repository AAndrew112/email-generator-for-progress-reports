#!/usr/bin/env python3
"""Segment the record into eras from data-driven change-points (no assumed life events).

Monthly features: writing volume, journal share, sentence length, first-person rate, and the
leading components of the month's vocabulary. Greedy binary segmentation splits where the
within-era variance falls most, and stops when a split explains less than --tau of the total.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, month_key, read_jsonl, words  # noqa: E402
from lib.lexicons import PRONOUNS  # noqa: E402

STOP = set("the a an and or but if so to of in on at for with as is are was were be been it its this that "
           "these those i me my you your we our they them he she his her not no yes just like um uh "
           "really very have has had do does did will would can could there here what when who how "
           "about from up out one get got going".split())


def monthly_features(chunks: list[dict]) -> tuple[list[str], np.ndarray, list[str], dict]:
    per: dict[str, dict] = defaultdict(lambda: {"words": 0, "docs": set(), "journal": set(), "sent": 0,
                                                 "first": 0, "vocab": Counter()})
    for c in chunks:
        m = month_key(c["date"])
        if not m:
            continue
        w = words(c["text"])
        p = per[m]
        p["words"] += len(w); p["docs"].add(c["doc_id"]); p["journal"].update([c["doc_id"]] if c["kind"] == "journal" else [])
        p["sent"] += max(1, sum(c["text"].count(x) for x in ".!?"))
        p["first"] += sum(t in PRONOUNS["i_me"] for t in w)
        p["vocab"].update(t for t in w if t not in STOP and len(t) > 2)
    months = sorted(per)
    top = [t for t, _ in sum((p["vocab"] for p in per.values()), Counter()).most_common(400)]
    V = np.array([[per[m]["vocab"][t] for t in top] for m in months], float)
    V = V / np.maximum(V.sum(1, keepdims=True), 1)
    V = V * np.log((1 + len(months)) / (1 + (V > 0).sum(0)))  # tf-idf style weighting
    V -= V.mean(0)
    k = min(5, len(months) - 1, V.shape[1])
    comps = (np.linalg.svd(V, full_matrices=False)[0][:, :k] * 1.0) if k > 0 else np.zeros((len(months), 0))
    base_names = ["log_words", "docs", "journal_share", "mean_sentence_words", "first_person_rate"]
    base = np.array([[np.log1p(per[m]["words"]), len(per[m]["docs"]), len(per[m]["journal"]) / max(1, len(per[m]["docs"])),
                      per[m]["words"] / per[m]["sent"], per[m]["first"] / max(1, per[m]["words"])]
                     for m in months])
    X = np.hstack([base, comps])
    X = (X - X.mean(0)) / np.where(X.std(0) > 1e-9, X.std(0), 1.0)
    return months, X, base_names + [f"vocab_pc{i + 1}" for i in range(k)], per


def seg_cost(cs: np.ndarray, cs2: np.ndarray, lo: int, hi: int) -> float:
    n = hi - lo
    s = cs[hi] - cs[lo]
    return float((cs2[hi] - cs2[lo]).sum() - (s ** 2).sum() / n)


def segment(X: np.ndarray, min_len: int, max_eras: int, tau: float) -> list[int]:
    n = len(X)
    cs, cs2 = np.vstack([np.zeros(X.shape[1]), np.cumsum(X, 0)]), np.vstack([np.zeros(X.shape[1]), np.cumsum(X ** 2, 0)])
    total = seg_cost(cs, cs2, 0, n) or 1.0
    bounds = [0, n]

    def best(lo: int, hi: int):
        cands = [(seg_cost(cs, cs2, lo, hi) - seg_cost(cs, cs2, lo, k) - seg_cost(cs, cs2, k, hi), k)
                 for k in range(lo + min_len, hi - min_len + 1)]
        return max(cands) if cands else (0.0, None)

    while len(bounds) - 1 < max_eras:
        options = [(best(a, b), a, b) for a, b in zip(bounds, bounds[1:])]
        (gain, k), a, b = max(options, key=lambda o: o[0][0])
        if k is None or gain / total < tau:
            break
        bounds = sorted(bounds + [k])
    return bounds


def distinctive_terms(chunks: list[dict], months: list[str], lo: int, hi: int, n: int = 12) -> list[str]:
    inside = {m for m in months[lo:hi]}
    a, b = Counter(), Counter()
    for c in chunks:
        m = month_key(c["date"])
        if m:
            (a if m in inside else b).update(t for t in words(c["text"]) if t not in STOP and len(t) > 2)
    na, nb = sum(a.values()) or 1, sum(b.values()) or 1
    score = {t: (a[t] / na) * np.log(((a[t] + 0.5) / na) / ((b[t] + 0.5) / nb)) for t in a if a[t] >= 3}
    return [t for t, _ in sorted(score.items(), key=lambda kv: -kv[1])[:n]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-months", type=int, default=4)
    ap.add_argument("--max-eras", type=int, default=10)
    ap.add_argument("--tau", type=float, default=0.04, help="min share of total variance a split must explain")
    a = ap.parse_args()
    chunks = list(read_jsonl(WORK / "chunks.jsonl"))
    months, X, names, per = monthly_features(chunks)
    if len(months) < 2 * a.min_months:
        bounds = [0, len(months)]
    else:
        bounds = segment(X, a.min_months, a.max_eras, a.tau)
    eras = []
    for i, (lo, hi) in enumerate(zip(bounds, bounds[1:]), 1):
        ms = months[lo:hi]
        eras.append({"era_id": f"E{i}", "start": ms[0], "end": ms[-1], "months": len(ms),
                     "documents": sum(len(per[m]["docs"]) for m in ms),
                     "words": sum(per[m]["words"] for m in ms),
                     "journal_share": round(sum(len(per[m]["journal"]) for m in ms) / max(1, sum(len(per[m]["docs"]) for m in ms)), 2),
                     "distinctive_terms": distinctive_terms(chunks, months, lo, hi)})
    (WORK / "eras.json").write_text(json.dumps(eras, indent=1), encoding="utf-8")
    with open(WORK / "monthly_features.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["month"] + names)
        for m, row in zip(months, X):
            w.writerow([m] + [round(float(v), 3) for v in row])
    OUT.mkdir(exist_ok=True)
    lines = ["# Era segmentation (data-driven)", "",
             f"Method: binary segmentation on standardized monthly features ({', '.join(names)}); "
             f"min {a.min_months} months per era, tau={a.tau}. Boundaries are hypotheses about when writing changed, "
             "not claims about life events. Undated and year-only documents are outside this segmentation.", "",
             "| Era | Start | End | Months | Documents | Words | Journal share | Distinctive terms |", "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {e['era_id']} | {e['start']} | {e['end']} | {e['months']} | {e['documents']} | {e['words']:,} | "
              f"{e['journal_share']} | {', '.join(e['distinctive_terms'][:8])} |" for e in eras]
    (OUT / "02_eras.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps([{k: e[k] for k in ("era_id", "start", "end", "documents")} for e in eras]))


if __name__ == "__main__":
    main()
