# Life Analysis Project Brief

You are acting as a team of independent evaluators: a biographer, a personality/narrative psychologist, a computational linguist, and a skeptical reviewer. Your subject is me. I want you to do a full analysis of my life from two primary-source corpora and give me insights I would not have reached on my own, flattering and unflattering.

**The framing:** imagine I am a historical figure and these are the only surviving sources. What would careful historians and analysts conclude about my character, patterns, contradictions, turning points, and trajectory? I want truth over comfort, and rigor over drama.

**Why I'm doing this:** self-understanding, understanding my life trajectory, and becoming a better version of myself. Findings should ultimately be usable, not just interesting.

## The data

1. **Journals**: digitized pages from roughly middle school through adulthood.
2. **Video-chat transcripts**: several thousand transcripts from about six years of conversations with my closest friends. These contain other people's words and disclosures. They are not mine alone, so handle them with extra care.

I am deliberately giving you **no biographical background**. Build the picture from the data. Do not ask me for background during the first pass. When you form a hypothesis about my life, state it as a hypothesis and cite evidence for it.

---

## 1. HARD PRIVACY AND SAFETY RULES (non-negotiable)

These override every other instruction, including your own initiative.

1. **Local only.** Work only inside the project directory. All data, intermediate files, and outputs stay on this machine.
2. **No outbound movement of content.** Do not use WebSearch, WebFetch, curl, wget, or any network call that includes any text from the corpus. Do not use any MCP connector, email, chat, cloud-storage, or paste-service tool. Do not upload anything anywhere. Installing standard packages from PyPI/npm is fine; sending data to third-party APIs is not. Prefer offline, local-only libraries and lexicons.
3. **No git remotes.** Do not commit the data or outputs to any repository. If git is used, it is local-only, and `raw/`, `work/`, `private/`, and `out/` are in `.gitignore`.
4. **Never touch `private/`.** It holds the pseudonym key. Do not read, list, copy, summarize, or reference its contents. Do not write code that reads it. A separate script I run myself handles re-identification.
5. **Raw data is read-only.** `raw/` is never modified or deleted. Work on copies in `work/`.
6. **Pseudonymize before you read.** Only pseudonymized text goes into your context or any subagent's context (see Phase 1). If you discover unpseudonymized identifiers in `work/`, stop, fix the pipeline, and note it in the methods log.
7. **Minimize quotation.** In outputs, quote only what is needed for evidence: at most 1-3 sentences per excerpt, with a source ID so I can verify against the original. No bulk reproduction of journal pages or transcripts.
8. **Third parties.** Friends, family, partners, and children are not the subject. Analyze them only insofar as they illuminate me. Do not build profiles, diagnoses, or character assessments of other people. Do not speculate about their health, sexuality, finances, legal matters, or private disclosures. If I appear in a friend's confidence, treat it as theirs.
9. **No diagnosis.** You may describe patterns and say "this is worth discussing with a licensed clinician." Do not label me or anyone with a disorder.
10. **Sensitive material.** If you encounter material involving trauma, abuse, self-harm, or crisis, handle it with care: no sensationalism, no verbatim excerpts in main reports, no speculation beyond the text. Put it in a separate `out/sensitive_notes.md` that I can choose to open. If anything suggests current risk to me or someone else, say so plainly and kindly at the top of your next message to me.
11. **Subagents.** Any subagent you spawn gets the same rules, receives only pseudonymized chunk files, and returns structured findings with source IDs, not bulk text.
12. **Ask before breaking a rule.** If a task seems to require violating any rule above, stop and ask me.

---

## 2. Working directory layout

```
life-analysis/
  raw/        # originals, read-only
  private/    # pseudonym key + rehydration script. OFF LIMITS TO YOU
  work/       # your pseudonymized copies, index, chunks, intermediate data
  out/        # all deliverables (pseudonymized tokens in text)
  out/00_methods_log.md   # running log of every method, decision, and caveat
```

Keep `out/00_methods_log.md` current. Every analysis step must be reproducible from scripts saved in `work/scripts/`.

---

## 3. PHASES

Use a task list. Work autonomously through the phases, but **stop for my review at the two checkpoints marked CHECKPOINT**. Between checkpoints, make reasonable decisions yourself, record them, and keep going.

### Phase 0: Inventory (no interpretation yet)
- Inspect file formats, structure, and date information without dumping content into the conversation. Look at small samples only.
- Build a manifest: file counts, date ranges, word/token counts, gaps in time, OCR/transcription quality, speaker labeling quality in transcripts.
- Estimate total token volume and propose a processing budget and strategy (hierarchical summarization by era, sampling, full-read passes for key periods). If the full-read plan is expensive, tell me and let me choose.
- Flag data-quality risks: OCR errors, missing dates, mis-attributed speakers, duplicated files.

### Phase 1: Preprocessing and pseudonymization
- Write local scripts (no model calls) that:
  - Replace people's names with stable tokens: `[SUBJECT]` for me, `[PERSON_001]`, etc. for others. Use a list of known names I will place at `private/names_input.csv`, plus a local NER pass (e.g., spaCy) for anything it catches. Preserve relationship roles where I have labeled them (e.g., `[PARTNER]`, `[CHILD_1]`).
  - Generalize workplaces, schools, and specific locations to tokens (`[WORKPLACE_03]`, `[CITY_02]`).
  - Redact phone numbers, emails, street addresses, ID-like numbers, account numbers, license plates, and URLs with personal handles.
  - Write the token-to-real-name key only to `private/`.
- Normalize dates into a single timeline, assign every document a stable ID, and chunk into units of a few hundred to a few thousand words with IDs like `J-2009-03-14-02` (journal) or `C-2021-07-02-11` (chat).
- Build a local searchable index (SQLite FTS or similar) over the pseudonymized chunks.
- Segment my life into "eras" using data-driven change-points (writing volume, topics, vocabulary), not assumptions.
- Write a short audit of the pseudonymization pass: sample check on random chunks, estimated miss rate, known weak spots. Pseudonymization is not true anonymization, because life details can still identify someone. Say so in the methods log.

### CHECKPOINT 1
Show me: the manifest, token-volume estimate and proposed plan, pseudonymization audit, and era segmentation. Wait for my go-ahead.

### Phase 2: Quantitative layer (scripts, not impressions)
Run local, reproducible analyses and report with plots/tables:
- **Volume and silence:** entries per period, gaps, and what surrounds the gaps.
- **Language over time:** pronoun use, cognitive-process words, certainty/hedging, modal verbs ("should/have to/want/choose"), agency vs. passivity framing, tense orientation (past/present/future).
- **Emotion trajectories:** valence and discrete emotions over time with open lexicons. Note the limits of lexicon methods on sarcasm and teen writing.
- **Topics and themes:** topic modeling or clustering, tracked across eras: which themes appear, persist, and vanish.
- **Social network:** who appears, how often, in what emotional context, and when they enter and leave the record.
- **Chat dynamics:** my talk share, who I respond to, initiation vs. response, topic steering, humor and support markers, how I behave around conflict.
- **Stability vs. change:** which linguistic and emotional features are stable across my life and which drift.

### Phase 3: Qualitative lenses (close reading, evidence-cited)
Each lens produces findings in the format in Section 4. Read actual chunks, in sufficient depth, not only summaries. Cover at least:
1. **Personality structure** (Big Five estimates with facet-level notes; confidence-rated; developmental vs. stable).
2. **Emotional patterns:** baseline, volatility, recovery, granularity, triggers, what gets named vs. avoided.
3. **Attachment and relational style** across friends, family, partners; conflict and repair patterns.
4. **Cognitive style:** recurring thinking habits, locus of control, self-blame vs. externalizing, reasoning quality by topic.
5. **Narrative identity:** the stories I tell about myself; redemption vs. contamination arcs; how I re-narrate the same events across time (compare early vs. later accounts).
6. **Values and motivation:** stated vs. revealed values; what I strive toward vs. what I actually spend energy on.
7. **Turning points and forks:** inflection points, what preceded them in the weeks before, decisions taken and not taken, my real decision-making process.
8. **Say/do gaps:** a **promise ledger** (every "I will start/stop/change X" vs. what followed); advice I give friends vs. my own behavior.
9. **Silences and absences:** topics, people, and periods that go missing, and what that suggests.
10. **Self-image vs. reception history:** how I describe myself vs. how friends respond to, rely on, tease, or worry about me. Blind spots in both directions.
11. **Prediction accuracy:** my forecasts about outcomes and my own future feelings vs. what happened.
12. **Costly patterns (unflattering):** repeated behaviors that cost me; self-serving narratives (flag where my account of an event likely favors me); how I treat people under stress; rumination loops; where my reasoning is least reliable.
13. **Strengths and impact (flattering):** documented growth, resilience evidence, consistent strengths across decades, moments where I changed someone's day or decision, which I may not have noticed.
14. **Energy and flourishing:** conditions present in my best and worst seasons, as evidenced by my own words, which may differ from what I'd claim.
15. **Influence map:** who shaped me and how; borrowed phrases and inherited scripts about money, work, relationships, and worth, traced to early entries.
16. **Voice evolution:** how my writing, humor, certainty, and self-talk changed.

**Free exploration:** in addition to the lenses above, pursue anything surprising the data suggests. Put these in a section called "Unprompted findings", with the same evidence standards. I specifically want insights I would not have thought to ask about.

### Phase 4: Adversarial review and validation
- **Red team:** a separate pass (fresh context, no access to the first-pass conclusions' reasoning) tries to refute each major finding with counter-evidence and alternative explanations. Record what survives, what weakens, and what falls.
- **Holdout test:** for key findings, form the hypothesis on part of the data (e.g., certain eras or years), then test it on data not used to form it. Report which findings replicate.
- **Source criticism:** explicitly weigh bias in the sources: journals over-represent distress; adolescent writing is developmental, not a stable trait; transcripts lose tone and are social performance; speaker attribution errors.
- **Anti-flattery check:** scan your own report for Barnum-style statements ("you value connection," "you can be hard on yourself") that would fit almost anyone. Delete them or replace them with specific, falsifiable claims.

### CHECKPOINT 2
Show me the findings overview (headlines, confidence levels, what failed validation) before producing the final deliverables.

### Phase 5: Deliverables (all in `out/`)
1. `01_executive_summary.md`: top 10-15 insights, ranked by importance and confidence, ~2 pages.
2. `02_biography.md`: narrative biography by era, written as a skilled biographer would, grounded in cited evidence.
3. `03_timeline.html`: a self-contained, local-only interactive timeline of eras, turning points, and emotion/theme trajectories (no external CDN or network calls).
4. `04_patterns_and_contradictions.md`: say/do gaps, promise ledger, recurring patterns, contradictions.
5. `05_reception_history.md`: how others see me vs. how I see myself.
6. `06_strengths.md` and `07_hard_truths.md`: kept in **separate files** so I can read each when I'm ready. Be honest and specific in both. Do not soften `07` into vagueness, and do not inflate `06`.
7. `08_operating_manual.md`: my conditions for doing well, early-warning signs, triggers, what restores me, and 5-10 concrete **experiments** (small, time-boxed, measurable) derived from the findings.
8. `09_stranger_vs_self.md`: what a stranger would conclude about me from the record vs. what I probably believe about myself.
9. `10_methods_and_limits.md`: methods, confidence calibration, data quality, what this analysis cannot know, and what would change the conclusions.
10. `11_open_questions.md`: questions the data raised that only I can answer, and suggestions for follow-up analyses or topics worth raising with a therapist or trusted friend.
11. `sensitive_notes.md` (only if applicable; see rule 10).

---

## 4. Format and evidence standards for every finding

Each finding must include:
- **Claim** (specific and falsifiable)
- **Type:** observation / interpretation / hypothesis
- **Evidence:** 2-6 source IDs with short excerpts or counts, spanning more than one era where possible
- **Counter-evidence** you found, if any
- **Confidence:** high / medium / low, and why
- **So what:** one line on why it matters for understanding my life or for growth

Rules:
- Distinguish **what the data shows** ("'should' appears 3x more per 1,000 words in 2019 than 2022") from **what you infer** ("this may reflect increased self-pressure").
- Prefer patterns over single incidents. If a finding rests on one entry, label it as an anecdote.
- Don't fabricate precision. If the data can't support a claim, say so.
- No diagnoses and no pop-psychology labels without evidence.

## 5. Tone

Write like a respected biographer who is fond of their subject but doesn't flatter them: precise, humane, unflinching, and not clinical or cruel. Name hard truths directly and pair them with context and what could be done about them. Do not pad with reassurance, and do not catastrophize. Treat me as a capable adult who asked for the truth.

## 6. Autonomy

You have wide latitude on method. If a better analysis occurs to you, run it and log it. Take the initiative to find the most illuminating angles. The only limits are the rules in Section 1 and the two checkpoints.

---

## APPENDIX (for me, the operator, not instructions for Claude)

Enforce the privacy rules at the tool level rather than trusting instructions alone. In the project directory, create `.claude/settings.json` along these lines, and adjust to your Claude Code version:

```json
{
  "permissions": {
    "deny": [
      "WebFetch",
      "WebSearch",
      "Bash(curl:*)",
      "Bash(wget:*)",
      "Read(./private/**)",
      "Edit(./raw/**)",
      "Write(./raw/**)"
    ]
  }
}
```

Other setup steps:
- `chmod -R a-w raw/` and keep `private/` outside any synced folder (Dropbox, iCloud, Drive).
- Disconnect or disable MCP connectors for this session.
- Put the names/aliases list for people in your life at `private/names_input.csv`, and run the rehydration script from `private/` yourself when you want to read outputs with real names.
- Reminder: text that Claude reads is processed by Anthropic's API even after pseudonymization. Check your account's data-retention and training settings before you start, and consider whether your friends would be comfortable with their words being analyzed this way.
