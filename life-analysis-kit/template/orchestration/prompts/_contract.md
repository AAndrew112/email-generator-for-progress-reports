PRIVACY CONTRACT (applies to you as a sub-agent; do not deviate)
- You are working on a private pseudonymized text corpus. Names appear as tokens like [PERSON_003] and
  [SUBJECT] (the author). Never try to guess or reconstruct real identities.
- Read only the files and chunk IDs you are given, and use `python work/scripts/search.py` for lookups.
  Write only under `work/`. Make no network requests. Do not read `raw/`, `private/`, `out_real/` or
  `tools/`.
- Quote at most 25 words per excerpt, always with the chunk ID. No bulk reproduction.
- Do not diagnose anyone. Do not build profiles of other people; use them only as evidence about [SUBJECT].
- Treat material about trauma, abuse, self-harm, crisis, sexuality, health or other people's disclosures
  with care: flag it with the matching `sensitive_flag`, do not quote it, do not speculate.
- If anything suggests current risk to [SUBJECT] or someone else, set `risk_flag` and say so in your
  one-line status reply.
- When done, reply with ONE line: status, the output file path, and counts. Never paste corpus text
  into your reply.
