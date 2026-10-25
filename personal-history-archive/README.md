# Personal History Archive

A local-first Python tool that transcribes and chronologically organizes two
kinds of personal records:

1. **Marco Polo videos** you export to a local folder. Only videos verified as
   recorded by you are transcribed and archived.
2. **Handwritten journals** scanned to PDF and stored in Google Drive (folder
   `1 journals`) or in a local folder.

Both pipelines write the same record format to one SQLite database and export
a CSV, a JSON file, per-record UTF-8 text transcripts and a review queue. A
small local web interface lets you check uncertain records, correct them and
re-export.

## Ground rules the code enforces

| Rule | How |
|---|---|
| Originals are never modified, and never deleted unless you turn that on | Videos and PDFs are only opened for reading; audio, page images and Drive downloads go to `archive_data/cache/`. A test checks file hashes and mtimes before and after a run. The one exception is the opt-in `delete_after_processing` setting for videos (below). |
| No guessing about who recorded a video | Ownership comes from sender metadata you confirm, or from voice verification against recordings you label. Anything else goes to the review queue. Filenames and folders are recorded as context only and never decide ownership. |
| Not "the loudest speaker" | Every ~1.6 s window of speech is compared with your voice profile. A video where both you and someone clearly different speak is flagged `multiple speakers detected`. |
| No invented dates | Videos are dated only from metadata fields you confirmed after inspection. Journal entries are dated from what is written on the page. Records without a verified date stay in the **undated** section. |
| File dates are never recording dates | File modification times are only used to detect container timestamps that were rewritten at export or download time. |
| Faithful transcripts | Whisper is primed to keep fillers and false starts. The handwriting prompt forbids corrections and requires `[illegible]` / `[?word?]` markers instead of guesses. |
| Machine and human versions both kept | Pipelines write `raw_transcript` / `machine_*`; your edits go to `corrected_*` and a `corrections` log. Re-running never overwrites a correction. |
| Local AI by default | Speech: faster-whisper. Voice: Resemblyzer (weights ship in the pip package). Handwriting: a vision model served by Ollama on `127.0.0.1`. The cloud backend refuses to start unless `cloud_ai_authorized = true`, and so does Ollama at a non-local address. |
| Google Drive is read-only | Only the `drive.readonly` scope is requested. A stored token with any other scope is rejected. |
| Safe to interrupt and re-run | Each video and each journal page is a checkpoint. Completed work is skipped; identical files are recognised by SHA-256 and every location is recorded; failures are logged and the run continues. |

## Install

Requires Python 3.11+ and FFmpeg (`ffmpeg` and `ffprobe` on `PATH`).

```bash
cd personal-history-archive
python -m venv .venv && source .venv/bin/activate
pip install -e '.[all]'          # transcription, voice, Google Drive
pha init                         # writes config.toml; edit the paths in it
```

On first use, faster-whisper downloads the speech model (`large-v3`, about
3 GB) from Hugging Face. That download is a model, not your data.

For handwriting recognition install [Ollama](https://ollama.com) and pull a
vision model, for example `ollama pull qwen2.5vl:7b`. Larger models usually
read handwriting better if your machine can run them; set
`vision.ollama_model` accordingly. If you do not want any AI to read the
journals, set `vision.backend = "manual"` and type pages in the review UI.

## Step 1: Marco Polo videos

1. Put your exported videos (any folder structure) under the folder named in
   `marco_polo.input_dir`.
   Videos already in iCloud Drive can be used where they are. On a Mac, set
   `input_dir = "~/Library/Mobile Documents/com~apple~CloudDocs/Voice videos"`.
   On Windows, iCloud Drive is usually `C:\Users\<you>\iCloudDrive`. The
   folder is only read. Keep `data_dir` on a local disk outside iCloud so the
   database and transcripts are not synced. If "Optimize Mac Storage" is on,
   right-click the folder in Finder and choose **Download Now** first. Videos
   that exist only in iCloud are listed in the reports and skipped until
   they are downloaded.

2. **Inspect before trusting anything.**

   ```bash
   pha mp inspect            # probes up to 200 videos; --sample 0 for all
   ```

   The report (`archive_data/inspect/marco_polo_*.md`) lists file types,
   filename patterns, sidecar JSON/CSV files and their fields, possible sender
   fields, container tags, and every date-like field with a verdict such as
   `LIKELY EXPORT/DOWNLOAD TIME`. Nothing is modified or transcribed.

3. Pick a few videos whose sender and recording date you know and compare
   them with the report. Then add only the fields you verified:

   ```toml
   [[marco_polo.ownership_rules]]
   kind = "sidecar"          # or "container_tag"
   name = "sender.name"
   owner_values = ["Your Name"]

   [[marco_polo.timestamp_rules]]
   kind = "container_tag"
   name = "com.apple.quicktime.creationdate"
   ```

   **Marco Polo chat exports** name each video
   `YYYY-MM-DD_HH-MM-SS_<TZ>_<First>_<Initial>.mp4`, for example
   `2026-04-28_05-07-33_PDT_Evelyn_E.mp4`. The report's "Metadata in file
   names" section lists every sender with three example files each. Watch
   a few, and if the names match who is speaking, add:

   ```toml
   [[marco_polo.ownership_rules]]
   kind = "filename"
   name = "sender"
   owner_values = ["Amanda W"]   # your name exactly as the report shows it
   spot_checked = true

   [[marco_polo.timestamp_rules]]
   kind = "filename"
   name = "timestamp"
   ```

   Without `spot_checked = true`, a file-name sender only counts when voice
   verification agrees; otherwise the video goes to review. The timezone
   abbreviation (e.g. `PDT`) becomes a UTC offset, and the abbreviation as
   written is kept in the evidence.

4. **If there is no reliable sender field**, use voice verification:
   - Put at least three recordings that you have checked are only you
     speaking in `voice.owner_samples_dir` (videos or audio).
   - Optionally put other people's recordings in `voice.other_samples_dir`,
     one sub-folder per person. This makes calibration meaningful.
   - Run `pha mp calibrate`. It runs a leave-one-out check of your samples,
     says whether your voice separates from the others, and suggests
     `accept_threshold` / `reject_threshold`. If it reports overlap, voice
     verification is not reliable with those samples.

   When both a metadata rule and voice samples are configured, they
   cross-check each other, and any disagreement goes to review.

5. Run the pipeline. It is safe to stop with Ctrl+C and run again.

   ```bash
   pha mp process
   ```

   Options: `--retry-failed`, `--reclassify` (redo automatic ownership
   decisions; manual ones are kept), `--force-retranscribe`, `--limit N`.

If you confirm a timestamp rule after videos are already transcribed,
the next `pha mp process` dates them without re-transcribing.

### Deleting videos when finished (optional, permanent)

Set `delete_after_processing = true` under `[marco_polo]` and each
`pha mp process` run ends by **permanently deleting** original videos it
has finished with:

- other people's videos, once excluded from the archive;
- your videos, once their transcript is saved **and approved**.

Videos that are uncertain, failed, or not yet approved are never deleted,
and neither is any file outside `input_dir` or whose content no longer
matches the video that was processed. Every deletion is recorded in the
database and in `archive.json` (`deleted_originals`); the transcript and
all its details stay in the archive, but the review page can no longer play
the video. Skip deletion for a single run with `pha mp process --keep-files`.

## Step 2: Journals

### Google Drive setup (read-only)

1. In Google Cloud Console create a project, enable the **Google Drive API**,
   configure the OAuth consent screen (External, add yourself as a test user)
   and create an **OAuth client ID** of type *Desktop app*.
2. Download the client JSON as `client_secret.json` next to `config.toml`.
3. Run `pha journals auth`. A browser window asks you to grant **read-only**
   access. The token is stored at `archive_data/google_token.json` (mode 600).

```bash
pha journals list                     # PDFs under "1 journals" and the years in their paths
pha journals process --limit 2        # start with a sample
pha journals process                  # everything; resumable page by page
```

To use a local folder instead (for example a Google Drive for desktop
mirror), set `journals.local_pdf_dir` and run
`pha journals process --source local`.

### How entries and dates are derived

- Each page is rendered to PNG (cache) and transcribed by the vision model,
  which marks each new entry with `=== ENTRY ===`. Date-heading lines are also
  detected directly in case the model misses a marker.
- Text at the top of a page that has no heading continues the previous entry,
  so entries can span pages (`page_number` is the first page; `page_end` is in
  the JSON).
- The date comes from the first lines of the entry. Supported forms include
  `March 4th, 1998`, `4 March 98`, `3/4/98` (order set by
  `journals.date_order`), `March 1998`. Partial dates are kept partial
  (`1998-03`).
- Folder and file names supply supporting evidence only. When a heading has
  no year and the path names exactly one year, that year is used and the
  date is marked `inferred`. Otherwise the entry stays undated.
- Optional: with `journals.date_undated_from_filename = true`, an entry with
  no usable written date takes the month or year its PDF's name points to,
  marked `inferred` (the evidence records the PDF name and the reasoning).
  A name gives at most a month, since a PDF holds many entries:
  `journal june 2019` → `2019-06`, `journal 7.5.19` → `2019-07`,
  `Journal 1998` → `1998`. Names covering a span (`june and july 2005`,
  `starting jan 2002`) give only the year; a span into a new year
  (`dec 20 2001 - january`) or a name with no year gives nothing, and the
  entry stays undated. To apply it to journals already transcribed, without
  running the vision model again:

  ```bash
  pha journals redate
  pha export
  ```
- A written weekday that does not match the date, a year that conflicts with
  the folder, or an assumed century is flagged for review.
- A time is extracted only when written in the entry heading.
- Identical PDFs are detected by hash. Re-scanned pages inside other PDFs are
  detected with a perceptual hash, confirmed by text similarity, and flagged.
  Nothing is deleted.

### Checking handwriting accuracy

Pick several pages, type exactly what is written on each into
`truth/<pdf name without .pdf>__p<page>.txt`, then:

```bash
pha journals evaluate --truth truth
```

This reports character and word error rates per page. Strict scores count
case and punctuation, since your original spelling must be preserved;
relaxed scores ignore them. Use it to compare vision models before you
process the whole archive. You can also compare the scan and the
transcript side by side in the review UI.

## Step 3: Review and export

```bash
pha review          # http://127.0.0.1:8765
pha export          # or use the button in the UI
pha status
```

The review UI shows the original video or page scans next to the transcript.
From there you can correct the transcript, date, time, timezone and
confidence, mark review items as checked, approve a record, decide who
recorded an uncertain video, and export. It listens on 127.0.0.1 only, and
forms carry a per-session token.

Export output (`archive_data/export/`):

| File | Contents |
|---|---|
| `archive.csv` | All records, chronological, undated last (`date = UNDATED`). Shared schema columns only. |
| `archive.json` | Dated records and a separate `undated_records` list, each with full metadata: machine and corrected versions, timestamp evidence, segments and confidence, file hash, every source location, open review items. |
| `transcripts/YYYY/MM/*.txt` | One UTF-8 file per record with a metadata header. Partial dates go to `YYYY/unknown-month/`; undated records go to `transcripts/undated/`. |
| `review_queue.csv` / `.json` | Open items: uncertain ownership, dates, low-confidence or illegible passages, possible duplicates. |

### Record schema

`record_id, source_type (marco_polo | journal), date, time, timezone,
timestamp_confidence (exact | inferred | unknown), transcript,
source_filename, source_location (path or Drive link), page_number
(journals), duration (videos, seconds), speaker_verification (videos),
transcription_status (pending | machine | corrected | manual_needed |
no_audio | failed), review_required`.

`transcript` is your corrected version when one exists, otherwise the
machine transcript. Both are in the JSON.

## What has and has not been verified

The automated tests (`pytest`) use synthetic material. They cover discovery,
de-duplication, resume after interruption, failure isolation, the timestamp
rules and export-time detection, metadata/voice ownership logic, entry
splitting and date parsing, Drive traversal with a fake API, the cloud
guard, the review UI and the exports. Voice verification was also run with
the real pretrained encoder on synthetic speakers (FFmpeg's flite voices),
where it accepted the owner voice, rejected another voice and flagged a
mixed clip.

**None of this has been run on real Marco Polo exports or real journal
scans yet.** In particular:

- Which metadata fields in your export carry the sender and the recording
  time is unknown until you run `pha mp inspect`.
- How well voice verification separates your voice from your contacts'
  voices is unknown until you run `pha mp calibrate` on real samples.
- Handwriting accuracy depends on the vision model and your writing. Measure
  it with `pha journals evaluate` before trusting bulk results.

## Development

```bash
pip install -e '.[dev,voice]'
pytest
```
