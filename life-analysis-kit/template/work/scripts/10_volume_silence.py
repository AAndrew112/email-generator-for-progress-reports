#!/usr/bin/env python3
"""Writing volume per month and the silences between dated documents, with chunk IDs on both sides."""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date as Date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, month_key, read_jsonl  # noqa: E402

GAP_DAYS = 14


def main() -> None:
    chunks = list(read_jsonl(WORK / "chunks.jsonl"))
    monthly: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    dated = []
    for c in chunks:
        m = month_key(c["date"])
        if m:
            monthly[(m, c["kind"])][0] += 1
            monthly[(m, c["kind"])][1] += c["words"]
        if c["date_precision"] == "day":
            dated.append((Date.fromisoformat(c["date"]), c["time"] or "", c["chunk_id"], c["kind"]))
    dated.sort()
    with open(WORK / "volume_monthly.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["month", "kind", "chunks", "words"])
        for (m, k), (n, nw) in sorted(monthly.items()):
            w.writerow([m, k, n, nw])
    gaps = []
    for kind in ("chat", "journal", "any"):
        seq = [d for d in dated if kind == "any" or d[3] == kind]
        for a, b in zip(seq, seq[1:]):
            n = (b[0] - a[0]).days
            if n > GAP_DAYS:
                gaps.append({"kind": kind, "start": a[0].isoformat(), "end": b[0].isoformat(), "days": n,
                             "before": a[2], "after": b[2]})
    gaps.sort(key=lambda g: -g["days"])
    with open(WORK / "silences.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["kind", "start", "end", "days", "before", "after"])
        w.writeheader(); w.writerows(gaps)
    OUT.mkdir(exist_ok=True)
    lines = ["# Volume and silence", "", f"Gaps longer than {GAP_DAYS} days between dated documents. "
             "`before`/`after` are the chunks on either side, to read for what surrounds the gap.", "",
             "| Source | From | To | Days | Before | After |", "|---|---|---|---|---|---|"]
    lines += [f"| {g['kind']} | {g['start']} | {g['end']} | {g['days']} | {g['before']} | {g['after']} |" for g in gaps[:40]]
    (OUT / "10_volume_silence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(gaps)} gaps; monthly volume in work/volume_monthly.csv")


if __name__ == "__main__":
    main()
