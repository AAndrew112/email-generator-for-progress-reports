#!/usr/bin/env python3
"""Split pseudonymized documents into chunks, build the search index and the batch files.

Chunk IDs: C-YYYY-MM-DD-NN (video message) and J-YYYY-MM-DD-NN (journal entry). Partial dates
use 00 for the unknown part (J-1998-03-00-01, J-1998-00-00-01); undated entries are J-UNDATED-NN.
Nothing is given a date it does not have.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import WORK, est_tokens, read_jsonl, write_jsonl  # noqa: E402

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_text(text: str, max_words: int) -> list[str]:
    parts, cur, n = [], [], 0
    for sent in SENT_SPLIT.split(text.strip()):
        sw = sent.split()
        while len(sw) > max_words:  # a very long unpunctuated stretch
            if cur:
                parts.append(" ".join(cur)); cur, n = [], 0
            parts.append(" ".join(sw[:max_words])); sw = sw[max_words:]
        if n + len(sw) > max_words and cur:
            parts.append(" ".join(cur)); cur, n = [], 0
        cur.append(" ".join(sw)); n += len(sw)
    if cur:
        parts.append(" ".join(cur))
    return parts or [""]


def date_part(date: str | None, precision: str | None) -> str:
    if not date or not precision:
        return "UNDATED"
    y, m, d = (date.split("-") + ["00", "00"])[:3]
    return f"{y}-{m}-{d}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-words", type=int, default=1200)
    ap.add_argument("--batch-tokens", type=int, default=30000, help="target tokens per batch file")
    args = ap.parse_args()

    counters: dict[str, int] = defaultdict(int)
    chunks = []
    for doc in read_jsonl(WORK / "docs_pseudo.jsonl"):
        prefix = "J" if doc["kind"] == "journal" else "C"
        stamp = date_part(doc["date"], doc["date_precision"])
        for part, text in enumerate(split_text(doc["text"], args.max_words), 1):
            counters[f"{prefix}-{stamp}"] += 1
            nw = len(text.split())
            chunks.append({
                "chunk_id": f"{prefix}-{stamp}-{counters[f'{prefix}-{stamp}']:02d}",
                "doc_id": doc["doc_id"], "part": part, "kind": doc["kind"],
                "date": doc["date"], "date_precision": doc["date_precision"], "time": doc["time"],
                "timezone": doc["timezone"], "date_confidence": doc["date_confidence"],
                "page": doc["page"], "source_label": doc["source_label"],
                "quality": doc["quality"], "words": nw, "tokens_est": est_tokens(nw), "text": text,
            })
    write_jsonl(WORK / "chunks.jsonl", chunks)

    db_path = WORK / "index.sqlite"
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE chunks (chunk_id TEXT PRIMARY KEY, kind TEXT, date TEXT, "
                 "date_precision TEXT, words INTEGER, text TEXT)")
    conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text, "
                 "tokenize='porter unicode61')")
    conn.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                     [(c["chunk_id"], c["kind"], c["date"], c["date_precision"], c["words"], c["text"]) for c in chunks])
    conn.executemany("INSERT INTO chunks_fts VALUES (?,?)", [(c["chunk_id"], c["text"]) for c in chunks])
    conn.commit(); conn.close()

    bdir = WORK / "batches"
    shutil.rmtree(bdir, ignore_errors=True)
    bdir.mkdir(parents=True)
    batches, cur, tok = [], [], 0
    for c in chunks:
        if cur and tok + c["tokens_est"] > args.batch_tokens:
            batches.append(cur); cur, tok = [], 0
        cur.append(c); tok += c["tokens_est"]
    if cur:
        batches.append(cur)
    index = []
    for i, b in enumerate(batches, 1):
        bid = f"B-{i:04d}"
        write_jsonl(bdir / f"{bid}.jsonl", [
            {k: c[k] for k in ("chunk_id", "date", "date_precision", "kind", "source_label", "text")} for c in b])
        index.append({"batch_id": bid, "chunks": len(b), "tokens_est": sum(c["tokens_est"] for c in b),
                      "first": b[0]["chunk_id"], "last": b[-1]["chunk_id"]})
    (bdir / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"{len(chunks)} chunks, {len(batches)} batches, index at {db_path}")


if __name__ == "__main__":
    main()
