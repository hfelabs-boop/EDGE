# Saving, loading and data

## Experiment files

* **Plain YAML or JSON.** Diffable and reviewable; works with git.
* **Atomic saves.** EDGE writes to a temporary file and renames it into place, so a crash or power
  loss can't corrupt an experiment.
* **Automatic version history.** Every save keeps the previous version in
  `.edge/backups/<file>/` (the 50 most recent).
  * Builder: **Versions** button
  * CLI: `edge backups study.yaml` lists versions; `edge backups study.yaml --restore [id]` restores one
  * MCP: `undo`, `list_versions`, `restore_version`
* **Conflict detection.** If the file changed since you opened it (another builder window, your
  editor, Claude over MCP), saving asks before overwriting. The other version is always kept as a
  backup. An open builder reloads automatically when the file changes and you have no unsaved
  edits.
* **Crash recovery.** The builder keeps a draft of unsaved changes in the browser and offers to
  restore it after a crash or accidental close.
* **Format migrations.** Files record `edge_format`. Older files are upgraded on load, and the
  builder tells you what changed. Files from a newer EDGE are refused instead of being
  misread.
* **Clear syntax errors.** Malformed YAML/JSON produces `invalid YAML at line 12, column 5: …`.
* **Portable bundles.** `edge bundle study.yaml` (or the builder's **Bundle** button) writes a
  `.edgez` archive with the experiment and every file it references (conditions tables, images,
  sounds). `edge unbundle study.edgez dest/` unpacks it on another computer.

## Session data (written automatically)

```
data/<participant>_<session>_<experiment>_<date>/
  trials_wide.csv      ★ one row per trial, ready for R / Python / SPSS / Excel
  summary.csv          ★ accuracy and RT per participant, overall and per condition level
  data_dictionary.csv  ★ what every column means: group, type, units, levels, range, missing
  README.txt           guide to the folder
  trials.csv / .jsonl  one row per routine run (long format; .jsonl is written live and crash-safe)
  events.jsonl         every marker with flip time, TTL code and per-device delivery time
  frames.csv           every screen flip
  streams/*.csv        device data: aligned time, device time, arrival time, channels
  session.json         settings, devices, clock models, marker codebook, timing, seed, versions
  experiment.yaml      the exact experiment that ran
  exports/             extra formats from settings.data.exports (e.g. xlsx, bids)
```

### How the trial table is built (`trials_wide.csv`)

* All routines of one loop iteration (for example `trial` and `feedback`) are merged into
  **one row**. Routines outside loops (instructions, breaks) get their own rows.
* Columns are ordered for analysis: **ids** (experiment, participant, session, start time) →
  **design** (trial number, loop, iteration, repetition, conditions-table row) → **conditions**
  (columns of your conditions file) → **responses** (keys, rt, corr …, grouped per component) →
  **timing** (onsets, durations, routine start times) → **variables**.
* Names stay unique: if two routines both have a component called `text`, the second becomes
  `feedback.text.onset`.
* Columns that are always empty are dropped. Float noise from clock arithmetic is rounded to
  microseconds. Lists (mouse paths, slider histories) are stored as JSON.
* A session that crashed mid-write still exports (a truncated last line is ignored).

### How the summary is built (`summary.csv`)

* **Main response:** the component with the most recorded RTs (its `.corr`, if any, is used for
  accuracy).
* **Factors:** condition columns with 2–12 levels. Answer-key, file and image columns are
  skipped.
* **Per participant:** an `(all)` row plus one row per level of each factor, with n_trials,
  n_responses, miss_rate, accuracy, and rt_mean / rt_median / rt_sd.
* **RT rules:** correct trials only, anticipations (< 100 ms) excluded, values beyond ±3 SD
  excluded; `n_rt_outliers` reports how many were removed.
* Override any of this in the experiment:
  `settings: {data: {summary: {by: [congruency], rt: resp.rt, correct: resp.corr}}}`.

### The data dictionary (`data_dictionary.csv`)

Every column gets a description generated from the experiment definition, for example "Response
time (s) of 'resp' (keyboard), from its onset flip to the response" or "Condition variable from loop
'trials' (stroop.csv)". It also lists group, type, units, number present and missing, min/max, and
levels for categorical columns. Ready for a preregistration or a data paper.

## Exports

```bash
edge export data/001_1_stroop_2027-02-01_101500 --formats xlsx,bids     # one session
edge export data/ --formats csv,xlsx                                      # every participant, merged
edge export data/ --layout long --formats parquet                         # one row per routine
```

| format | what you get |
|---|---|
| `csv`, `tsv` | trials, summary, dictionary (and a sessions table when merging); UTF-8 with BOM so Excel shows accents |
| `xlsx` | one workbook: trials, summary, dictionary, events/sessions. Typed cells, bold frozen header, filters, sized columns; no extra packages needed |
| `json`, `jsonl` | records |
| `parquet` | needs `pyarrow` |
| `mat` | MATLAB struct `trials` (needs `scipy`) |
| `bids` | BIDS-style tree: `sub-XX/ses-YY/beh/*_beh.tsv` + JSON sidecar (column descriptions), `*_events.tsv` (onsets from session start, labels, TTL codes), `*_physio.tsv.gz` + JSON (sampling rate, start time, columns) per device stream, `dataset_description.json`, `participants.tsv` |

Merging many sessions (`edge export data/`) adds a `session_folder` column, unions columns
across participants in a stable order, stacks the per-participant summaries, and writes a
**sessions** table (date, aborted, dropped frames, devices, errors) for screening.

To export automatically after every session, list the formats in the experiment:
`settings: {data: {exports: [csv, xlsx, bids]}}`.

The same exports are in the builder (**Data** tab), and are available to Claude over MCP
(`export_data`, `analyze_session`).
