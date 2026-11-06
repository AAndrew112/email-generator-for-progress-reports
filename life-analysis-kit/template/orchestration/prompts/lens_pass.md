{{include _contract.md}}

TASK (tier 2 lens pass). Era: {{ERA_ID}} ({{ERA_START}} to {{ERA_END}}). Lens pack: {{PACK}} with lenses {{LENSES}}.
You have: (a) the era's extractions, `work/extractions/` filtered to chunk IDs from this era (use
`python work/scripts/20_aggregate.py --era {{ERA_ID}} --compact` to print them), (b) the era's aggregates in
`work/aggregates/`, (c) `search.py` to pull full chunks. Pull 20-40 full chunks: the highest-salience ones,
plus chunks that test your leading hypotheses, plus a few random ones to avoid cherry-picking.

Produce `work/lens/{{PACK}}/{{ERA_ID}}.md`: for each lens in the pack, 2-6 findings, each with:
- Claim (specific and falsifiable)  - Type (observation / interpretation / hypothesis)
- Evidence (2-6 chunk IDs, excerpts <= 25 words, or counts from the aggregates)
- Counter-evidence you looked for and what you found  - Confidence (high/medium/low) and why
- So what (one line)

Rules: hypotheses, not verdicts; patterns over single incidents (label a one-chunk finding "anecdote");
journals over-represent distress and early journals are adolescent writing, so say when an era is
adolescent; spoken messages are social performance and lose tone; only the subject's side exists, so
claims about how others see the subject are inferences from what the subject reports. Prefer a specific
claim that could be wrong over a general one that would fit anyone. Sensitive material: do not quote;
write it to `work/lens/sensitive/{{ERA_ID}}.md` instead and mention only the flag here.
