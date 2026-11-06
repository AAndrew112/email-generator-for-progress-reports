#!/usr/bin/env python3
"""OPERATOR-RUN ONLY. Puts real names back into the analysis outputs.

    python tools/rehydrate.py            # out/  ->  out_real/
    python tools/rehydrate.py --in out --out out_real

Uses private/key.json. The assistant must never read out_real/ or private/.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SUFFIXES = {".md", ".txt", ".html", ".json", ".csv", ".jsonl"}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=root)
    ap.add_argument("--in", dest="src", default="out")
    ap.add_argument("--out", dest="dst", default="out_real")
    args = ap.parse_args()
    key = json.loads((args.root / "private" / "key.json").read_text(encoding="utf-8"))
    best = {f"[{tok}]": max(seen, key=seen.get) for tok, seen in key.items() if seen}
    rx = re.compile("|".join(re.escape(t) for t in sorted(best, key=len, reverse=True)) or r"(?!x)x")
    src, dst = args.root / args.src, args.root / args.dst
    n = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in SUFFIXES:
            target.write_text(rx.sub(lambda m: best[m.group(0)], path.read_text(encoding="utf-8")),
                              encoding="utf-8")
        else:
            target.write_bytes(path.read_bytes())
        n += 1
    print(f"{n} files written to {dst}")


if __name__ == "__main__":
    main()
