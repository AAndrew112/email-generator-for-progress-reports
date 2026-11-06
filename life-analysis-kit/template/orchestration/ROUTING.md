# Model routing and sub-agent plan

Goal: read every chunk cheaply once, spend the strong models only where judgment matters, and make
every claim traceable to chunk IDs. The main session (strongest model) orchestrates; it does not read
the whole corpus itself.

## Tiers

| Tier | Model (Agent tool `model`) | Job | Reads | Writes |
|---|---|---|---|---|
| 1 Extract | `haiku` | Structured extraction per chunk | one batch file (about 30k tokens) | `work/extractions/B-xxxx.json` |
| 2 Lens | `sonnet` | One lens pack for one era: close reading plus findings | that era's extractions plus 20-40 full chunks it pulls with `search.py` | `work/lens/<pack>/<era>.md` |
| 3 Synthesize | `opus` (or the strongest available) | Cross-era findings per lens, contradictions, adjudication, deliverables | tier-2 findings plus the cited chunks it spot-checks | `out/*.md`, `work/synthesis/*.md` |
| 4 Red team | `opus`, fresh context | Try to refute each major finding | the claim, its cited IDs, and the search tool, not the writer's reasoning | `work/redteam/*.md` |
| 5 Holdout | `sonnet` | Re-test a finding on eras not used to form it | the claim text and the holdout era's chunks | `work/holdout/*.md` |

The main session picks the model with the Agent tool's `model` parameter. If a model name is not
accepted in this installation, use the nearest tier and note it in the methods log.

## Privacy contract (put this block at the top of every sub-agent prompt, verbatim)
See `prompts/_contract.md`. Sub-agents receive only pseudonymized chunk files or IDs, write only under
`work/`, make no network calls, and reply to the main session with a status line and file path, never
with bulk text.

## How the main session builds a sub-agent prompt
Read the file in `orchestration/prompts/`, replace the line `{{include _contract.md}}` with the full text of
`_contract.md`, replace each `{{VARIABLE}}` (batch ID, era, lens list and so on), and pass the result as the
Agent prompt with the tier's `model`. Never add corpus text to a prompt; give IDs and file paths.

## Pipeline

1. **Extraction (Tier 1).** For each file in `work/batches/` (see `index.json`) without a matching
   `work/extractions/B-xxxx.json`, spawn one `haiku` agent with `prompts/extract_chunks.md` and the
   batch ID. Run up to 6 at once. After each wave run `python work/scripts/07_validate_extractions.py`:
   it rejects records whose quotes are not real passages of the chunk. Re-run only the rejected
   chunks. Do not move on until the rejection rate is under 3%. Log it.
2. **Aggregate (script).** Write `work/scripts/20_aggregate.py` to roll the extractions up by month,
   era and person token: emotions by month, commitments list (the promise ledger), predictions,
   conflict and repair rates, agency and blame scores, sensitive flags, salience. Numbers in reports
   come from here.
3. **Lens passes (Tier 2).** For every era x lens pack (below), spawn one `sonnet` agent with
   `prompts/lens_pass.md`. Eras too large for one context (over about 120k tokens of material) are
   split into windows. Up to 6 at once. Each agent returns findings in the brief's Section 4 format.
4. **Synthesis (Tier 3).** For each lens, one `opus` agent merges the era findings
   (`prompts/synthesis.md`), checks stability across eras, and keeps only claims with evidence in more
   than one era or labels them anecdote. Reception-history and conflict lenses must say "only the
   subject's side exists".
5. **Validation (Phase 4).** Red team every high- or medium-confidence finding (`prompts/red_team.md`);
   holdout test the key ones (`prompts/holdout.md`); run source criticism and the anti-flattery check
   (`prompts/anti_flattery.md`). Record what survives, weakens, falls.
6. **Deliverables (Phase 5).** Main session plus `opus` writers, one file per deliverable, each citing
   chunk IDs. `06_strengths.md` and `07_hard_truths.md` are written by separate agents.

## Lens packs

| Pack | Lenses from the brief |
|---|---|
| A Emotion and cognition | 2 emotional patterns, 4 cognitive style, 12 costly patterns |
| B Relationships | 3 attachment and relational style, 10 self-image vs reception, 13 strengths and impact, 15 influence map |
| C Narrative and values | 5 narrative identity, 6 values and motivation, 14 energy and flourishing, 16 voice evolution |
| D Change and behavior | 7 turning points, 8 say/do gaps (promise ledger), 11 prediction accuracy |
| E Absence and structure | 9 silences and absences, 1 personality structure |

Free exploration ("Unprompted findings") is done by one extra `sonnet` agent per era with
`prompts/free_exploration.md`, then the synthesis agent selects the survivors.

## Cost control
- Read each chunk in full at most once at Tier 1; later tiers work from extractions and pull full text
  only through `search.py`, in small numbers.
- Choose the depth at Checkpoint 1 from `out/03_budget.md` (Skim / Standard / Deep).
- Batch outputs are files, so an interrupted run resumes where it stopped.
- Do not launch more than 6 agents at once.

## Evidence rules for all tiers
Every finding: claim, type (observation / interpretation / hypothesis), 2-6 chunk IDs spanning more
than one era where possible with short excerpts (at most 25 words each), counter-evidence, confidence
with reason, and a one-line "so what". Separate what the data shows from what is inferred. No
diagnoses. Third parties appear only as evidence about the subject.
