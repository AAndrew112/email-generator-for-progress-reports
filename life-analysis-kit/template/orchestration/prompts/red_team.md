{{include _contract.md}}

TASK (red team, fresh context). You are given only the claims below and their cited chunk IDs: you do not see
how they were reached. For each claim: read the cited chunks, search for counter-evidence with `search.py`
(at least 3 searches per claim), and propose alternative explanations (adolescence, source bias, transcription
error, a one-off event, selective quoting, the social setting of video messages). Verdict per claim:
SURVIVES / WEAKENED (say how) / FALLS (say why). Write `work/redteam/{{CLAIM_SET}}.md`. Be adversarial but
honest: do not manufacture objections.

CLAIMS:
{{CLAIMS}}
