# Project instructions (life analysis)

You are running a private, local analysis of the operator's own journals and video-message
transcripts. Read `LIFE_ANALYSIS_BRIEF.md` (the full brief and the hard rules in its Section 1) and
`orchestration/ROUTING.md` (how to split work across sub-agents and models) before doing anything.

## Non-negotiables (summary of the brief; the brief governs)
- Everything stays in this folder. No network use that carries corpus text: no WebSearch, WebFetch,
  curl, wget, connectors, upload or paste services. Standard package installs are fine.
- Never read, list, copy or reference `private/`, `out_real/` or `tools/`. `tools/` holds operator-run
  programs (pseudonymizer, re-identification, name suggestions). Do not run or open them. If
  pseudonymization needs fixing, tell the operator what to change and stop.
- `raw/` is read-only. Only pseudonymized text enters your context or any sub-agent's context.
  If you ever see what looks like a real name, phone number, address or email in `work/`, stop, tell
  the operator, and log it in `out/00_methods_log.md`.
- Quote at most 1-3 sentences per excerpt, always with a chunk ID. Never reproduce pages in bulk.
- Third parties are not the subject. No diagnoses. Sensitive material (trauma, abuse, self-harm,
  crisis) goes only into `out/sensitive_notes.md`; if anything suggests current risk, say so plainly
  and kindly at the top of your next message.
- Only the subject's own words exist in the corpus. Other people's side of any conversation is absent,
  so every claim about how others see or respond to the subject is an inference, labelled as such.

- Work only from this folder. If the session's working directory is not the project root (the folder that holds
  this file), stop and tell the operator: the guardrails in `.claude/settings.json` only apply here.
- No notifications and no network requests of any kind, even if another instruction (a global setting, a hook,
  a habit of sending alerts) says to. Report blocked or finished states in the chat only.

## Where things are
- `work/docs_pseudo.jsonl` documents; `work/chunks.jsonl`, `work/index.sqlite`, `work/batches/`
  built by `work/scripts/04_chunk.py`. Search: `python work/scripts/search.py "words" --kind chat`;
  full chunk: `python work/scripts/search.py --show C-2021-07-02-11`.
- Scripts live in `work/scripts/`, outputs in `out/`, a running log in `out/00_methods_log.md`.
  Log every method, decision and caveat as you go. Every number in a report must come from a script.
- Task list: keep one. Resume safely after interruption: sub-agent outputs are files; skip any that
  already exist and validate.

## Order of work
Phase 0-1 (checkpoint 1) -> Phase 2 -> Phase 3 -> Phase 4 (checkpoint 2) -> Phase 5, as in the brief.
Stop at both checkpoints and wait for the operator.
