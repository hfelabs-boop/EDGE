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
  measures.csv         ★ your declared measures, overall and per condition cell (see "Measures")
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

Test runs (`edge run --dry-run`, the builder's **▶ Test run**) write the same folders under
`data/dry_runs/`, and **▶ Try it** under `data/dry_runs/try/`. They are left out of merged exports
and of the participant-ID suggestion unless you ask for them (*include test runs* in the Data tab,
`--include-dry-runs` on the command line).

Surveys add one column per answer (`about.age`, `about.phq9_3`), one 0/1 column per option of
checkbox questions, rank and constant-sum columns per option, `<id>_other` texts, `pageN_time`, the
scores of library questionnaires (`about.phq9_total`, `about.phq9_total_band`) and `<id>_order` for
shuffled questions. The data dictionary describes each with the question's wording and answer codes.
Signatures, uploaded files, video/audio recordings and screenshots are saved in the session's
`survey_files/` folder; their columns hold the path.

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

## Measures: saying what the experiment measures

Everything above is recorded automatically. **Measures** say which of it is the point of the
study: the outcomes (dependent variables), the factors (independent variables), covariates and
checks. Declare them in the builder (**Measures & data**), with the MCP tool `set_measures`, or in
the experiment file:

```yaml
measures:
  - {id: rt, label: Reaction time, role: outcome, column: resp.rt, trials: $resp.corr == 1,
     loop: trials, summary: median, units: s, expect: [0.15, 2.5]}
  - {id: accuracy, label: Accuracy, role: outcome, column: resp.corr, loop: trials, summary: proportion}
  - {id: congruent, role: factor, column: congruent}
```

| key | meaning |
|---|---|
| `column` | a recorded column: `<component>.<what>` (e.g. `resp.rt`, `about.phq9_total`), a trial-list column, a variable or a participant field |
| `role` | `outcome` (default), `factor`, `covariate`, `check` (manipulation/attention check), `info` |
| `summary` | `mean` (default), `median`, `sd`, `min`, `max`, `sum`, `count`, `proportion` (share of 1s, for correctness), `first`, `last`, `none` |
| `trials` | only the trials where this expression is true, e.g. `$resp.corr == 1` (correct trials only) |
| `loop` | only trials of this loop, e.g. leave out practice |
| `expect` | `[lowest, highest]` plausible values; anything outside is flagged after each session |
| `label`, `units`, `description` | for people reading the data |

What each component records is declared by the component itself, so EDGE knows before anything
runs which columns will exist. **Check** reports a measure that points at a column nobody records
("'resp' (keyboard) records keys, rt, corr, time, not 'rtt'; did you mean resp.rt?"), at a
component whose saving is switched off, at a loop that doesn't exist, or with a broken filter. The
design wizard declares accuracy, reaction time and the condition factor for you; the builder
suggests measures for experiments that have none.

After every session:

* `measures.csv` holds each measure overall and per cell of the factors (one row per cell, with
  `n`, `missing` and `value`). Merged exports add a measures table/sheet for all participants.
* The session report (`edge report`, the builder's Test results, `analyze_session`) lists the
  measures and warns when one was never recorded, is missing on more than 20% of its trials, or has
  values outside `expect`.
* Declared factors become the default `by` of `summary.csv`.

While a session runs from the builder, the run window shows each measure live (see
[Builder guide](BUILDER_GUIDE.md#live-session-monitor)).

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
