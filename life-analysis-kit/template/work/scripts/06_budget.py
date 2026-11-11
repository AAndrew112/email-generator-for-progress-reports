#!/usr/bin/env python3
"""Token budget and strategy options for Checkpoint 1. Estimates only; prices are never assumed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.common import OUT, WORK, read_jsonl  # noqa: E402

PRICES = WORK / "budget_prices.json"  # optional: {"haiku": {"in": 0.0, "out": 0.0}, ...} dollars per million tokens
EXTRACT_OUT_RATIO = 0.18   # extraction JSON is roughly 18% of the chunk text it describes
LENS_PACKS = 5             # lens packs per era (see orchestration/ROUTING.md)


def scenarios(corpus: int, eras: int) -> list[dict]:
    ext = {"haiku_in": corpus, "haiku_out": int(corpus * EXTRACT_OUT_RATIO)}
    summaries = int(corpus * EXTRACT_OUT_RATIO)
    return [
        {"name": "Skim", "describe": "Extraction on every chunk; lens passes read extractions plus a 10% sample of full chunks; synthesis on findings only.",
         **ext, "sonnet_in": int(summaries * LENS_PACKS + corpus * 0.10 * 2), "sonnet_out": 60_000 * eras // 4 + 40_000,
         "opus_in": 250_000, "opus_out": 90_000},
        {"name": "Standard (recommended starting point)", "describe": "Extraction on every chunk; lens passes read extractions plus ~30% of chunks in full, chosen by salience and lens queries; red team and holdout on the main findings.",
         **ext, "sonnet_in": int(summaries * LENS_PACKS + corpus * 0.30 * 2), "sonnet_out": 90_000 * eras // 4 + 60_000,
         "opus_in": 450_000, "opus_out": 140_000},
        {"name": "Deep", "describe": "Standard, plus every chunk read in full once by a mid-tier model for the close-reading lenses, and the strongest model reading the top 10% most salient chunks itself.",
         **ext, "sonnet_in": int(summaries * LENS_PACKS + corpus * 1.0 * 2), "sonnet_out": 160_000 * eras // 4 + 90_000,
         "opus_in": int(corpus * 0.10 + 650_000), "opus_out": 200_000},
    ]


def main() -> None:
    chunks = list(read_jsonl(WORK / "chunks.jsonl"))
    corpus = sum(c["tokens_est"] for c in chunks)
    eras = len(json.loads((WORK / "eras.json").read_text())) if (WORK / "eras.json").exists() else 6
    prices = json.loads(PRICES.read_text()) if PRICES.exists() else None
    rows = scenarios(corpus, eras)
    lines = ["# Token budget and strategy options", "",
             f"Corpus: {len(chunks):,} chunks, about {corpus:,} tokens (words x 1.35; an estimate). Eras: {eras}.", "",
             "Input tokens count every time a model reads text, so reading the corpus twice costs twice. "
             "These are planning estimates, not quotes.", "",
             "| Option | Light model in/out | Mid model in/out | Top model in/out |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['haiku_in']:,} / {r['haiku_out']:,} | {r['sonnet_in']:,} / {r['sonnet_out']:,} | {r['opus_in']:,} / {r['opus_out']:,} |")
    lines += [""] + [f"- **{r['name']}**: {r['describe']}" for r in rows]
    if prices:
        lines += ["", "## Estimated cost (from work/budget_prices.json, dollars)", ""]
        for r in rows:
            cost = sum(r[f"{t}_{d}"] / 1e6 * prices[t][d] for t in ("haiku", "sonnet", "opus") for d in ("in", "out"))
            lines.append(f"- {r['name']}: about ${cost:,.0f}")
    else:
        lines += ["", "Prices are not assumed. To see dollar estimates, put current per-million-token prices from your plan "
                  "in work/budget_prices.json as {\"haiku\": {\"in\": 0, \"out\": 0}, \"sonnet\": {...}, \"opus\": {...}}. "
                  "On a subscription plan the limit that matters is your usage allowance, so compare the token columns."]
    OUT.mkdir(exist_ok=True)
    (OUT / "03_budget.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
