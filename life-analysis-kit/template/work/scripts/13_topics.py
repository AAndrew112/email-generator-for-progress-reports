#!/usr/bin/env python3
"""Topic clustering (NMF on TF-IDF) and how each topic's share moves across eras."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, read_jsonl  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=12)
    k = ap.parse_args().k
    from sklearn.decomposition import NMF
    from sklearn.feature_extraction.text import TfidfVectorizer

    chunks = list(read_jsonl(WORK / "chunks.jsonl"))
    eras = json.loads((WORK / "eras.json").read_text()) if (WORK / "eras.json").exists() else []
    vec = TfidfVectorizer(stop_words="english", max_df=0.5, min_df=3, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z']{2,}\b")
    X = vec.fit_transform([c["text"] for c in chunks])
    k = max(2, min(k, X.shape[0] - 1, X.shape[1] - 1))
    model = NMF(n_components=k, init="nndsvda", random_state=0, max_iter=400)
    W = model.fit_transform(X)
    terms = vec.get_feature_names_out()
    topics = [[terms[i] for i in comp.argsort()[::-1][:10]] for comp in model.components_]

    def era_of(date: str | None) -> str:
        m = (date or "")[:7]
        return next((e["era_id"] for e in eras if e["start"] <= m <= e["end"]), "undated") if len(m) == 7 else "undated"

    share: dict[str, list[float]] = defaultdict(lambda: [0.0] * k)
    for c, w in zip(chunks, W):
        s = w.sum() or 1.0
        for j in range(k):
            share[f"{era_of(c['date'])}/{c['kind']}"][j] += w[j] / s
    OUT.mkdir(exist_ok=True)
    lines = ["# Topics (NMF) and their share by era", "", "Topics are statistical clusters; the labels are for the "
             "reader to assign. Share = fraction of that era's chunks' topic weight.", ""]
    lines += [f"- T{j + 1}: {', '.join(t)}" for j, t in enumerate(topics)]
    lines += ["", "| Era/source | " + " | ".join(f"T{j + 1}" for j in range(k)) + " |", "|---|" + "---|" * k]
    for key in sorted(share):
        tot = sum(share[key]) or 1
        lines.append(f"| {key} | " + " | ".join(f"{share[key][j] / tot:.2f}" for j in range(k)) + " |")
    (OUT / "13_topics.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (WORK / "topics.json").write_text(json.dumps({"topics": topics, "share": share}, indent=1), encoding="utf-8")
    print(f"{k} topics")


if __name__ == "__main__":
    main()
