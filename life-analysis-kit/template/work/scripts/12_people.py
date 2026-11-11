#!/usr/bin/env python3
"""Who appears and when: counts of each person/place token by month, first and last appearance."""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, month_key, read_jsonl  # noqa: E402

PERSON = re.compile(r"\[(?:PERSON(?:_NER)?_\d+|PARTNER|CHILD_\d+|FAMILY_\d+|FRIEND_\d+|[A-Z]+_\d+)\]")
SKIP = re.compile(r"\[(?:EMAIL|URL|HANDLE|PHONE|ADDRESS|ID_NUM)_\d+\]")


def main() -> None:
    mentions: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, Counter] = defaultdict(Counter)
    for c in read_jsonl(WORK / "chunks.jsonl"):
        m = month_key(c["date"]) or "undated"
        for tok in PERSON.findall(c["text"]):
            if not SKIP.fullmatch(tok):
                mentions[tok][m] += 1
                kinds[tok][c["kind"]] += 1
    rows = []
    for tok, by_month in mentions.items():
        dated = sorted(m for m in by_month if m != "undated")
        rows.append({"token": tok, "mentions": sum(by_month.values()),
                     "first_month": dated[0] if dated else "", "last_month": dated[-1] if dated else "",
                     "active_months": len(dated), "in_chat": kinds[tok]["chat"], "in_journal": kinds[tok]["journal"]})
    rows.sort(key=lambda r: -r["mentions"])
    with open(WORK / "people_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["token"])
        w.writeheader(); w.writerows(rows)
    with open(WORK / "people_monthly.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["token", "month", "mentions"])
        for tok, by_month in sorted(mentions.items()):
            for m, n in sorted(by_month.items()):
                w.writerow([tok, m, n])
    OUT.mkdir(exist_ok=True)
    lines = ["# Who appears, and when", "", "Mention counts are a proxy for presence in the record, not for closeness. "
             "Only the subject's side of any conversation exists.", "",
             "| Token | Mentions | First | Last | Active months | Chat | Journal |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['token']} | {r['mentions']} | {r['first_month']} | {r['last_month']} | {r['active_months']} | {r['in_chat']} | {r['in_journal']} |" for r in rows[:40]]
    (OUT / "12_people.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(rows)} tokens")


if __name__ == "__main__":
    main()
