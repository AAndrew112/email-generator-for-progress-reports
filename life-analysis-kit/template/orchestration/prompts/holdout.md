{{include _contract.md}}

TASK (holdout test). The claim below was formed from eras {{TRAIN_ERAS}}. You see only era(s) {{TEST_ERAS}}.
Search them (`search.py` with date filters) and decide whether the claim replicates: REPLICATES / PARTIAL / NOT
REPLICATED / NO DATA. Cite chunk IDs and say what you searched for. Do not reinterpret the claim to make it fit.
Write `work/holdout/{{CLAIM_ID}}.md`.

CLAIM: {{CLAIM}}
