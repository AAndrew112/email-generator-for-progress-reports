Paste this as the first message of your local Claude Code session, started inside this folder.

---
Read CLAUDE.md, LIFE_ANALYSIS_BRIEF.md and orchestration/ROUTING.md in full. Then begin.

State: the operator has already run the pseudonymization tool, so work/docs_pseudo.jsonl and
work/pseudonymization_report.json exist. Phase 1 scripts for chunking, indexing, eras and the budget
are already written in work/scripts/ (04_chunk.py, 02_manifest.py, 05_eras.py, 06_budget.py).

1. Run them in this order: 02_manifest, 04_chunk, 05_eras, 06_budget. Do not read anything outside
   work/ and out/.
2. Audit the pseudonymization yourself: sample at least 60 random chunks across eras and both
   sources, look for anything that looks like a real name, place, workplace, school, phone, address
   or email, and estimate the miss rate. Write this up in out/00_methods_log.md. Be strict: if you
   find a probable miss, stop and tell me what to add to the names list.
3. Prepare Checkpoint 1: manifest (out/01_manifest.md), token estimate and the three cost options
   (out/03_budget.md), pseudonymization audit, and era segmentation (out/02_eras.md). Add your
   recommendation for depth and why.
4. Stop and wait for my go-ahead. Do not start Phase 2.
---
