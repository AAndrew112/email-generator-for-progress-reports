# LifeLog

A private, fast iPhone and Apple Watch app for collecting personal well-being data.
It only collects data. There are no charts, no accounts and no cloud. Exports are
built for analysis in Python or R.

- **Quick log.** Tap a tile to record something now. Tiles appear on the Today screen,
  the Watch, home-screen widgets, Siri/Shortcuts and the Action button. Items that need
  an answer (for example "how long?") open a short sheet, and tapping the answer saves it.
  After each log you can **Undo** or **Edit**.
- **Morning and evening check-ins.** One question per screen, and one tap per rating.
  Each answer is saved as soon as you give it. Sleep times are pre-filled from last
  night or, if you turn it on, from Apple Health. You confirm or correct them.
- **Measures you can edit in the app.** You can add, edit, reorder, star, deactivate
  or delete measures. A field can be a rating scale (every point labelled), number,
  yes/no, single or multiple choice, time, duration, text or photo. You set the units,
  anchors, options, defaults and presets, and whether a measure is once per day or
  can be logged many times.
- **Data you can rely on.** Every entry stores when it happened, the time zone and
  UTC offset, which device recorded it, how it was recorded, and a full edit history.
  Deletions can be undone. Missing values are never stored as zero.
- **Exports.** You get a zip with a data dictionary, tidy and daily-wide CSVs, check-ins,
  the edit history, complete JSON and your photos.

## Install on your iPhone and Apple Watch

Requirements:

- A Mac with **Xcode 26** or later. The project builds in CI with Xcode 26.3.
- An iPhone on **iOS 17** or later.
- An Apple Watch on **watchOS 10** or later.
- Your paid Apple Developer account.

1. **Get the code.**
   ```sh
   git clone https://github.com/AAndrew112/email-generator-for-progress-reports.git
   cd email-generator-for-progress-reports
   git checkout claude/lifelog-wellbeing-tracker-62yabv
   cd LifeLog
   ```
2. **Set your team and bundle ID prefix.** Create `Config/Signing.local.xcconfig`
   (git ignores this file):
   ```
   LIFELOG_TEAM_ID = ABCDE12345
   LIFELOG_BUNDLE_ID_PREFIX = com.yourname
   ```
   Your Team ID is under developer.apple.com → Account → Membership details. The prefix
   can be anything you own in reverse-DNS form. The app's bundle ID will be
   `com.yourname.lifelog` and its App Group will be `group.com.yourname.lifelog`.
3. **Open `LifeLog.xcodeproj`** in Xcode. Sign in under Xcode → Settings → Accounts
   if you haven't already.
4. **Turn on Developer Mode.** On the iPhone, go to Settings → Privacy & Security →
   Developer Mode. The Watch has the same setting; it appears after the Watch has
   been connected to Xcode once.
5. **Run on the iPhone.** Pick the **LifeLog** scheme and choose your iPhone as the
   destination, then press ⌘R. Automatic signing registers the App IDs, the App Group
   and the HealthKit capability for you. If Xcode asks to register the App Group or
   add a capability, accept.
6. **Install on the Watch.** The Watch app is embedded in the iPhone app. It installs
   automatically if "Automatic App Install" is on in the Watch app on your iPhone.
   Otherwise, open the Watch app on the iPhone, go to My Watch, find LifeLog and tap
   Install. To debug the Watch app directly, run the **LifeLogWatch** scheme with your
   Watch as the destination.
7. **Optional extras:**
   - **Widgets:** long-press the Home Screen, tap +, then LifeLog. Quick Log shows your
     starred items as one-tap buttons. Check-in is a Lock Screen widget.
   - **Watch complications:** edit a watch face and add LifeLog Quick Log or Check-in.
   - **Action button or Back Tap:** go to Settings → Action Button → Shortcut → LifeLog
     "Quick Log" and pick an item. For Back Tap, use Accessibility → Touch → Back Tap.
   - **Reminders and Apple Health:** turn these on in LifeLog → Settings.

A build signed with a paid account stays installed until its provisioning profile
expires, which is about a year, so it easily covers a 42-day study. Updating the app
from Xcode keeps your data. **Deleting the app deletes its data, so export first.**

If you'd rather not use Xcode for updates, use Product → Archive → Distribute → TestFlight
(Internal Testing). TestFlight builds expire after 90 days.

## Daily use

| When | What | Taps |
| --- | --- | --- |
| Morning | Today → **Morning**. Confirm sleep times, then tap sleep quality and restedness. | about 4 |
| Any time | Tap a tile: Urge resisted, Gave in, Automatic pickup, Coffee… | 1 |
| Any time | Scrolling episode → tap a duration chip. Tap Edit on the toast to add the app or trigger. | 2 |
| Any time | Seborrheic dermatitis → tap a severity, then Edit to add locations or a photo. | 2+ |
| Evening | Today → **Evening**. Eight ratings, one tap each. | about 9 |
| Later | Tap any entry to change its time, values or note. To delete, long-press it on Today or swipe it in History. History → ⋯ → Recently deleted restores it. | |

To log something that happened earlier, tap +, turn on "Log at an earlier time", and pick
the item. You can also edit the time on any entry.

**On the Watch**, tap a starred item. If it needs an answer, tap the answer and it's saved.
The Watch keeps working without the iPhone nearby and sends changes when the two reconnect.

### The 42-day study

A study period called "Scrolling & focus study" (19 Oct – 29 Nov 2026, 42 days) is set up
on first launch. The Today screen shows the study day, and every export row gets `study`
and `study_day` columns. You can edit it or add more periods in Settings → Study periods.

## Measures included at first launch

All subjective ratings use five-point 0–4 scales, and every point is labelled.

| Group | Measure | Where | Fields |
| --- | --- | --- | --- |
| Sleep | Sleep times | Morning | bedtime, sleep onset, wake time, time asleep (calculated, editable) |
| Sleep | Sleep quality | Morning | 0 Very poor … 4 Very good |
| Sleep | Restedness | Morning | 0 Not at all … 4 Completely |
| Mind | Mood | Evening | 0 Very low … 4 Very good |
| Mind | Anxiety, Brain fog, Work avoidance | Evening | 0 Not at all … 4 Extremely |
| Mind | Mental energy | Evening | 0 Very low … 4 Very high |
| Mind | Focus | Evening | 0 Very poorly … 4 Very well |
| Mind | Meaningful progress | Evening | 0 None … 4 A great deal |
| Mind | Fulfillment | Evening | 0 Not at all … 4 Extremely |
| Screen | Scrolling episode | Quick log ★ | duration (required), app/platform, trigger(s), device. The time is the start of the episode. |
| Screen | Screen urge | Presets ★ "Urge resisted" and "Gave in" | outcome (required), strength 0–4, trigger(s), platform |
| Screen | Automatic pickup | Quick log ★ | trigger(s), device (optional) |
| Screen | Screen Time total | Evening (inactive) | duration copied from iOS Screen Time |
| Intake | Caffeine | Preset ★ "Coffee 95 mg" | source, amount (mg) |
| Intake | Medication | Quick log ★ | name (with suggestions), dose, unit, side effects. Save each medication you take as a preset. |
| Skin | Seborrheic dermatitis | Quick log ★ | severity 0–4 (required), locations (multiple), photo(s) |

You can edit or deactivate any of these. Keys never change, so renaming a measure, field
or option never breaks earlier data. Fields and options you remove are archived, not deleted.

## Export format

Go to Settings → **Export CSV + JSON**. You get a zip you can share or save to Files.

| File | Contents |
| --- | --- |
| `README.txt` | Explains the conventions below, generated with each export. |
| `measures.csv` | Data dictionary: one row per field, with type, unit, scale anchors, options, how it's summarised by day, and whether it's archived. |
| `observations.csv` | **Tidy / long format.** One row per answered field. Columns include `value`, `value_numeric`, `value_label`, `unit`, `occurred_at` (local time with offset), `occurred_at_utc`, `day`, `study_day`, `context`, `source`. |
| `entries.csv` | One row per entry. Columns include start and end times, note, preset, `backdated`, revision, device and check-in ID. |
| `daily.csv` | **Wide format.** One row per day from the first to the last day with data, including days with nothing logged (`has_data = 0`). |
| `checkins.csv` | Each check-in, with which questions were shown, answered and skipped. |
| `edit_history.csv` | Every saved version of every entry, including deletions. |
| `lifelog.json` | Everything, including deleted entries and every version of each measure definition. You can import it back into LifeLog. |
| `photos/` | Photo files. `observations.csv` refers to them by relative path. |

Conventions:

- An unanswered field has no row in `observations.csv` and an empty cell in `daily.csv`. A zero only appears when 0 was recorded. A count or total is 0 on a day that has data but nothing of that kind logged.
- The `day` column uses a day boundary, 4 AM by default, so 1 AM scrolling counts toward the night before.
- Durations are in minutes. For time-of-day fields, `value_numeric` is clock hours (23.5 means 23:30).

```python
import pandas as pd
obs = pd.read_csv("observations.csv", parse_dates=["occurred_at_utc"])
daily = pd.read_csv("daily.csv")
```
```r
library(readr)
obs <- read_csv("observations.csv")
daily <- read_csv("daily.csv")
```

## Privacy

- All data lives in an on-device SQLite database. On iPhone it's in the App Group container,
  shared only with LifeLog's own widget. The iPhone and Watch talk directly over
  WatchConnectivity.
- The app makes no network requests, has no analytics or third-party SDKs, and has no account.
- Apple Health is optional and read-only: it only reads sleep, to suggest morning times.
- Photos are re-encoded when saved, which strips location and other metadata. They're stored
  in the app's container.
- Data leaves the device only when you export it, or through your own encrypted iPhone backup.

## Project layout

```
LifeLog/
  project.yml              XcodeGen spec (LifeLog.xcodeproj is generated from it and committed)
  Config/Project.xcconfig  Team / bundle-prefix settings
  LifeLogKit/              Swift package: model, SQLite store, sync merge, exporters (+ tests)
  App/Shared/              App model, quick-log logic, Watch sync (iPhone + Watch)
  App/iOS/                 iPhone UI, App Intents, HealthKit, reminders, export
  App/Intents/             Widget-button intent (app + widget extension)
  App/Watch/               Watch UI
  Widgets/iOS/             Home/Lock Screen widgets
  Widgets/Watch/           Watch complications
```

Development:

- `cd LifeLogKit && swift test` runs the core tests on macOS or Linux.
- CI (`.github/workflows/lifelog.yml`) does four things:
  - runs the core tests;
  - builds every target for the simulator and for a device;
  - runs the iPhone UI tests: one-tap log and undo, a preset, the two-tap scrolling
    episode, the full morning check-in, creating a measure, and export;
  - runs the Watch UI tests.
- In Xcode, ⌘U on the LifeLog or LifeLogWatch scheme runs the same UI tests against a
  fresh throwaway database (the `-uiTesting` launch argument).
- After adding or removing files, run `brew install xcodegen && xcodegen generate`.

How sync works: each change is saved locally first and marked pending. It's then sent
with `WCSession.transferUserInfo`, which the system queues until the other device can
receive it. Merges are last-writer-wins per record, with deletions recorded as tombstones,
so sending the same change twice is harmless. The Watch keeps the measure definitions
and the last 14 days of entries. The iPhone keeps everything.
