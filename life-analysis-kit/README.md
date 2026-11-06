# Life-analysis kit

A private, local system for running the "Life Analysis Project Brief" (`template/LIFE_ANALYSIS_BRIEF.md`)
on your journals and Marco Polo transcripts. It contains **no data**. You copy it to a folder on your Mac,
add your export, and run Claude Code there. Your corpus never goes through the cloud session that built this.

## What is in it

| Part | Who runs it | What it does |
|---|---|---|
| `tools/` (operator tools) | **You**, in a normal terminal | Suggest names, pseudonymize, check guardrails, put real names back. The assistant is blocked from running or reading these. |
| `work/scripts/` | The assistant | Chunk and index the pseudonymized text, manifest, era segmentation, token budget, volume and silence, language metrics, who-appears-when, topics, extraction validation and aggregation. |
| `orchestration/` | The assistant | Model routing (cheap model extracts, mid-tier reads closely, strongest model synthesizes, a fresh strong model red-teams), the sub-agent prompts, the extraction schema. |
| `.claude/settings.json` | Claude Code | Blocks web access, curl/wget/ssh, git push, edits to `raw/`, and reading `private/`, `out_real/` and `tools/`. |
| `CLAUDE.md`, `START_PROMPT.md` | The assistant / you | Standing rules for the local session, and the first message to paste. |

## Before you start

1. **Check your Anthropic account's data-retention and training settings.** Even pseudonymized, whatever the
   assistant reads is processed by Anthropic's API. Pseudonymization is not anonymization: life details can
   still identify people. Consider whether your friends would be comfortable with their words being used this way.
2. Python 3.10+ and `pip install numpy scikit-learn` (optional: `vaderSentiment` for valence; `spacy` plus its
   English model for the optional extra name finder, which is untested in this kit).
3. Claude Code installed on the Mac.
4. In Claude Code, **turn off MCP connectors** (Gmail, Drive, and so on) for this folder.

## Steps (about 2 to 3 hours of your time, mostly step 2)

**1. Create the project folder** (not in iCloud, Dropbox or Drive; the script refuses synced folders):
```bash
cd ~/email-generator-for-progress-reports && git pull
./life-analysis-kit/setup.sh ~/life-analysis \
  ~/email-generator-for-progress-reports/personal-history-archive/archive_data/export/archive.json
cd ~/life-analysis
```
The archive file is copied into `raw/` and made read-only. File names, paths and the pipeline's record IDs are
never carried into the analysis; only a pseudonymized title for journals.

**2. Write your names list** (the step that decides how safe this is):
```bash
python3 tools/suggest_names.py
```
Open `private/name_candidates.csv` (frequent capitalized words, to jog your memory) and edit
`private/names_input.csv`. One row per person or place:

| column | meaning |
|---|---|
| `name` | full name as you would write it |
| `category` | `SUBJECT` (you), `PERSON`, `PARTNER`, `CHILD`, `FAMILY`, `WORKPLACE`, `SCHOOL`, `CITY`, `PLACE` |
| `token` | optional label such as `PARTNER` or `CHILD_1`; blank gives `PERSON_001` and so on |
| `aliases` | other spellings, nicknames, **speech-recognition misspellings**, separated by `;` |
| `case_sensitive` | `yes` for names that are also words (Hope, Mark, Rose) so only the capitalized form is replaced |

Include your own name and nicknames (`SUBJECT`), family, partners, kids, friends, workplaces, schools, towns,
neighborhoods, group chat names. **Add new rows at the bottom**; inserting in the middle renumbers tokens.

**3. Pseudonymize and audit:**
```bash
python3 tools/pseudonymize.py
```
Read the printed report, then open `private/residual_candidates.csv`: these are capitalized words still in the
text. Any real name, place or organization there goes into `names_input.csv`; run the tool again. Repeat until the
list holds only ordinary words. Also check `tokens_never_matched` (a typo in your list) and
`tokens_matching_over_5_per_1000_words` (a name that is also a common word; set `case_sensitive`).
Do this **before** the analysis begins: re-running it later renumbers tokens and invalidates findings.

**4. Check the guardrails:**
```bash
python3 tools/check_setup.py
```
Everything should say PASS. Then check your account's retention settings (above).

**5. Start the analysis:**
```bash
cd ~/life-analysis && claude
```
Paste the message in `START_PROMPT.md`. The assistant builds the chunk index, manifest, eras and budget, audits
the pseudonymization itself (sampling chunks and estimating a miss rate), and stops at **Checkpoint 1** with the
manifest, token estimates for three depths (Skim, Standard, Deep), the audit and the eras. You choose the depth.
It then continues through the phases and stops again at **Checkpoint 2** before writing the deliverables.

**6. Read the results with real names:**
```bash
python3 tools/rehydrate.py        # out/ -> out_real/
```
Never paste real-name outputs into any assistant.

## Things you should know

- **Only your side exists.** Other people's videos were excluded and deleted at the source. Conversation
  dynamics (talk share, initiation, who you answer) cannot be measured, and "how friends see me" is inferred
  only from what you report about their reactions. The kit labels those findings as limited.
- Speech-recognition errors, mis-dated entries and early adolescent writing affect the results; the methods
  log and `10_methods_and_limits.md` should say how.
- Sensitive material (trauma, abuse, self-harm, crisis) goes to `out/sensitive_notes.md`, not the main reports.
  If anything suggests current risk, the assistant is instructed to say so first.
- Nothing here diagnoses anyone. Patterns worth discussing are flagged for "a licensed clinician or trusted friend".

## What has and has not been tested

Tested on **synthetic data only** (`tests/`, 16 tests): pseudonymization of planted names, aliases, misspellings,
emails, phones, URLs, handles and addresses; case-sensitive names; no file names or paths in the output;
re-identification; chunk IDs and partial dates; search; era detection near a planted shift; the extraction
validator (rejecting invented quotes); aggregation; the setup script and the deny rules. Not tested: real
transcripts, the optional spaCy name finder, and Claude Code's behavior with the deny rules on your version
(`check_setup.py` verifies the file, not enforcement; try asking the assistant to read `private/` once to confirm
it is refused). Pseudonymization quality on your real data depends on your names list and is checked at Checkpoint 1.
