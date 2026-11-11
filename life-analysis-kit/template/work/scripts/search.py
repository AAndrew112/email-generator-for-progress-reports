#!/usr/bin/env python3
"""Search the pseudonymized corpus (local SQLite full-text index).

  python work/scripts/search.py "should quit" --kind chat --from 2019-01 --to 2020-12 --limit 10
  python work/scripts/search.py --show C-2021-07-02-11      # print one whole chunk
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import connect_index  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--show")
    ap.add_argument("--kind", choices=["chat", "journal"])
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--snippet", type=int, default=200)
    a = ap.parse_args()
    conn = connect_index()
    if a.show:
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (a.show,)).fetchone()
        if not row:
            sys.exit("no such chunk")
        print(f"[{row['chunk_id']}] {row['date'] or 'UNDATED'} ({row['words']} words)\n{row['text']}")
        return
    if not a.query:
        sys.exit("give a query or --show CHUNK_ID")
    q = " ".join(f'"{w}"' for w in re.findall(r"[\w']+", a.query))
    sql = ("SELECT c.chunk_id, c.date, c.kind, c.text FROM chunks_fts f JOIN chunks c USING (chunk_id) "
           "WHERE chunks_fts MATCH ?")
    args: list = [q]
    if a.kind:
        sql += " AND c.kind = ?"; args.append(a.kind)
    if a.start:
        sql += " AND c.date >= ?"; args.append(a.start)
    if a.end:
        sql += " AND c.date <= ?"; args.append(a.end + "-99")
    sql += " ORDER BY c.date LIMIT ?"; args.append(a.limit)
    for r in conn.execute(sql, args):
        text = r["text"]
        m = re.search(re.escape(a.query.split()[0]), text, re.I)
        i = max(0, (m.start() if m else 0) - a.snippet // 2)
        print(f"{r['chunk_id']}  {r['date'] or 'UNDATED'}  {text[i:i + a.snippet]!r}")


if __name__ == "__main__":
    main()
