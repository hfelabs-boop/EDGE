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
  A key given twice in one place (two `max_repeat:` lines in one loop) is an error that names both
  lines, instead of YAML silently keeping only the last one.
* **Your comments stay.** When EDGE saves a YAML file (builder, MCP tools, `edge` commands), each
  `# comment` stays with the key or list item it was written next to; comments about something you
  deleted go with it. The layout is EDGE's own: `{a: 1, b: 2}` on one line becomes one key per line.
  Saved files keep their permissions.
* **Portable bundles.** `edge bundle study.yaml` (or the builder's **Bundle** button) writes a
  `.edgez` archive with the experiment, exactly as written, and every file it references (conditions
  tables, images, sounds). `edge unbundle study.edgez dest/` unpacks it on another computer. It never
  replaces files already in `dest/` that differ from the bundle's (an edited trial list, another
  experiment's files): it stops before writing anything and asks for a new folder.

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
  audio/*.wav          voice recordings (microphone items), one per screen; audio/manifest.csv lists them
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
edge export data/ --formats sav,rds,rdata                                 # SPSS and R, labelled
```

| format | what you get |
|---|---|
| `csv`, `tsv` | trials, summary, dictionary (and a sessions table when merging); UTF-8 with BOM so Excel shows accents |
| `xlsx` | one workbook: trials, summary, dictionary, events/sessions. Typed cells, bold frozen header, filters, sized columns; no extra packages needed |
| `json`, `jsonl` | records |
| `parquet` | needs `pyarrow` |
| `mat` | MATLAB struct `trials` (needs `scipy`) |
| `sav` | SPSS: `*_trials.sav` and `*_summary.sav` with variable labels, value labels and measurement levels (see below); no extra packages needed |
| `rds` | R: `*_trials.rds` and `*_summary.rds`, each one data frame (`readRDS("..._trials.rds")`) with factors and column labels; no extra packages needed |
| `rdata` | R: one `.RData` with every table as a data frame (`load("....RData")` gives `trials`, `summary`, `dictionary`, `events`, `session`, and `sessions`/`measures` when there are any) |
| `bids` | BIDS-style tree: `sub-XX/ses-YY/beh/*_beh.tsv` + JSON sidecar (column descriptions), `*_events.tsv` (onsets from session start, labels, TTL codes), `*_physio.tsv.gz` + JSON (sampling rate, start time, columns and their units) per device stream, `dataset_description.json`, `participants.tsv`. Every time in it counts from the session start; two folders with the same participant and session become `run-1`, `run-2` |

`parquet` and `mat` need a package that is not installed by default: the export says so, with the
command that installs it for your EDGE, before writing anything. (`spss` is another name for `sav`,
`r` for `rds` and `rda` for `rdata`.)

### SPSS and R files

The `.sav`, `.rds` and `.RData` files are written by EDGE itself (no SPSS, R or Python package needed)
and carry the data dictionary with them:

* **Names.** Column names become names that are valid in both SPSS and R: letters, digits, `.` and
  `_`, starting with a letter, at most 64 characters, unique ignoring case (`resp.rt` stays `resp.rt`;
  `with space` becomes `with_space`, `2nd` becomes `v_2nd`, a reserved word such as `if` or `ALL`
  gets `_v`). Every variable's **label** is its description from the data dictionary; when the name had
  to change, the label starts with the original column name.
* **Types.** Numbers stay numbers (whole numbers are integers in R), true/false becomes logical in R and
  0/1 with the labels false/true in SPSS, lists (mouse paths, slider histories) become JSON text, long
  texts (typed answers) are kept whole (SPSS long strings).
* **Conditions and responses as categories.** A text column of the trial list or a response with at most
  20 different values (`kind` = standard/deviant, `resp.keys`) becomes an R **factor** and, in SPSS,
  numeric codes 1, 2, … with **value labels** (codes in alphabetical order of the values; numbers sort
  numerically). Correctness (`.corr`) gets 0 = incorrect, 1 = correct; gaze flags (`.entered`,
  `.completed`) 0 = no, 1 = yes. Measurement levels: categories are nominal, numbers scale.
* **Missing values.** Empty cells are system-missing in SPSS and `NA` in R.
* **R extras.** Each column has a `label` attribute (RStudio's viewer and the labelled/haven packages show
  it), and the data frame has `variable.labels` (the convention of `foreign::read.spss`).

Merging many sessions (`edge export data/`) adds a `session_folder` column (also to the summary and
measures, so two sessions of one participant stay apart), unions columns across participants in a
stable order, stacks the per-participant summaries, and writes a **sessions** table (date, aborted,
dropped frames, devices, errors) for screening. A folder that holds several experiments gets one set
of files per experiment, and a session folder that can't be read is skipped and named.

Voice recordings (the `microphone` item) are listed in the trial tables (`<item>.file`, relative to
the session folder). `edge export data/ --audio-manifest` also writes `exports/audio_manifest.csv`:
one row per recording of every session, with its full path, trial, trial-list values, detected
speech onset and empty `transcript` and `notes` columns to fill in (see
[Devices](DEVICES.md#spoken-answers-touchscreens-and-gamepads)).

To export automatically after every session, list the formats in the experiment:
`settings: {data: {exports: [csv, xlsx, bids]}}`.

The same exports are in the builder (**Data** tab), and are available to Claude over MCP
(`export_data`, `analyze_session`).

## Analyses: epochs, pupil, fixations and areas of interest

EDGE can analyse what devices recorded in a session: cut EEG or pupil epochs around markers and average
them per condition, find fixations and saccades in gaze data, and report how each area of interest
(AOI) was looked at in every trial. Everything uses EDGE's master clock, so markers, trials and samples
line up without a trigger channel. Results go to the session's `analysis/` folder.

* **Builder:** **Data** tab, choose a session, then **Eye & signals** (shown when the session has a gaze,
  EEG or other recording). Run an analysis, read the first rows and download the files.
* **Command line:** `edge analyze epochs|fixations|aoi SESSION_FOLDER …` (below).
* **Python:** `from edge.analysis import epochs, fixations, aoi_report`.

No extra packages are needed. The ERP / pupil plot (`.png`) needs matplotlib
(`pip install edge-experiments[plots]`); without it the plot is skipped with a note, and the CSV has the
same numbers.

### Epochs and averages (EEG, pupil)

```bash
edge analyze epochs data/001_1_auditory_oddball_… --stream eeg --markers standard,deviant \
    --tmin -0.2 --tmax 0.8 --baseline -0.2 0
edge analyze epochs data/001_1_freeview_… --stream pupil --markers "view_*" --tmin -0.5 --tmax 3 \
    --baseline -0.5 0 --by left_color
```

```python
from edge.analysis import epochs
res = epochs("data/001_1_auditory_oddball_…", stream="eeg", markers=["standard", "deviant"],
             tmin=-0.2, tmax=0.8, baseline=(-0.2, 0), reject=100)
res["erp"]["deviant"]["Pz"]          # the average, one value per time in res["times"]
```

1. **Markers:** labels as they appear in `events.jsonl` (the item's marker), separated by commas;
   wildcards work (`view_*`) and a number matches the TTL code.
2. **Signal:** `--stream` is a device id (`eeg`), `device.stream`, a kind, or `pupil` for the eye
   tracker's pupil size. All channels except trigger/status channels are used, or name them with
   `--channels Fz,Cz,Pz`.
3. **Pupil:** blinks and short losses (up to 1 s) are filled by linear interpolation first, from 50 ms
   before to 100 ms after each gap (the eyelid distorts the samples next to a blink). Both eyes are
   averaged.
4. **Cutting:** every epoch is sampled on the same grid from `tmin` to `tmax` at the stream's rate,
   interpolating between the two nearest samples, so the times are exact whatever the amplifier's
   sampling phase.
5. **Baseline:** the mean of the baseline window is subtracted, per epoch and channel
   (`--no-baseline` to skip).
6. **Rejection:** an epoch is left out of the averages when its peak-to-peak range on any channel is above
   `--reject` (default 150 for channels in µV, none for other units; `--reject none` keeps all), or when
   more than half of a channel's samples are missing.
7. **Conditions:** the marker's label, or trial-list columns with `--by` (`--by kind,isi`; `marker` in
   `--by` adds the label). Each epoch belongs to the trial during which its marker happened.

| file | what it holds |
|---|---|
| `epochs_<stream>.npz` | for Python/MNE (`numpy.load`): `data` (epochs × channels × times), `times`, `channels`, `event_times`, `markers`, `conditions`, `trials`, `rejected`, `srate`, `erp` (conditions × channels × times), `erp_conditions` |
| `epochs_<stream>.csv` | long format, one row per epoch, channel and time: `epoch`, `trial`, `condition`, `marker`, `rejected` (1 = left out of the averages), `channel`, `time` (s from the marker), `value` (baseline-corrected, in the channel's units) |
| `epochs_<stream>_info.csv` | one row per epoch: `epoch`, `trial` (row of trials_wide.csv), `routine` (screen), `marker`, `code` (TTL), `event_time` (master clock, s), `condition`, the trial-list columns, `rejected`, `reason` (e.g. "peak-to-peak 183.2 uV on Fz"), and for pupil `interpolated` (share of the epoch filled in) |
| `erp_<stream>.csv` | the averages: `condition`, `channel`, `time` (s), `mean`, `sd`, `se` (SD/√n), `n` (epochs that had a value), `units` |
| `erp_<stream>.png` | one panel per channel, one line per condition (needs matplotlib) |

### Fixations and saccades

```bash
edge analyze fixations data/001_1_freeview_…                   # I-VT, 30 deg/s
edge analyze fixations data/001_1_freeview_… --method idt --dispersion 1.0 --min-duration 0.1
```

Gaze from any EDGE eye tracker (simulated, mouse, Tobii, Gazepoint: their screen fractions are converted)
is turned into visual angle with the experiment's screen geometry: `settings.window.monitor`
(`width_cm`: the width of the visible screen, `distance_cm`: eyes to screen) and the window size in
pixels. Set them to your lab's values, or the degrees (and so the thresholds) are off.

* **I-VT** (velocity threshold, the default; like Tobii's I-VT filter): gaps up to 75 ms are filled, a
  3-sample moving median reduces noise, the speed of the eyes is measured over a 20 ms window, samples
  slower than 30 deg/s belong to fixations; fixations less than 75 ms and 0.5 deg apart are merged, and
  fixations shorter than 60 ms are dropped. Change them with `--velocity`, `--min-duration`,
  `--noise-filter` (1 = off).
* **I-DT** (dispersion threshold, Salvucci & Goldberg 2000): a fixation is at least 100 ms of gaze whose
  spread (x range + y range) stays within 1 deg. Change them with `--dispersion` and `--min-duration`.
* **Saccades** are the movements between two fixations when the eyes were tracked all the way (no blink
  in between) and took at most 150 ms.
* The simulated eye tracker is noisier than real ones (8 px); I-VT works on it, I-DT needs a larger
  `--dispersion` (about 2).

`fixations.csv` (one row per fixation):

| column | meaning |
|---|---|
| `fixation` | number, in time order |
| `trial`, `routine` | the row of trials_wide.csv and the screen it started on (empty between screens) |
| `start`, `end`, `duration` | master-clock times and length (s) |
| `onset` | start from the beginning of its screen (s) |
| `x`, `y` | mean position in pixels from the screen centre, +y up (EDGE's own units) |
| `x_deg`, `y_deg` | the same as visual angle from the screen centre (deg) |
| `dispersion_deg` | x range + y range of its samples (deg) |
| `n_samples` | samples in it |
| `pupil` | mean pupil diameter (mm), when the tracker records it |
| `aoi` | the AOI(s) it landed in, separated by `;` (filled by `edge analyze aoi`) |

`saccades.csv`: `saccade`, `trial`, `routine`, `start`, `end`, `duration`, `onset`, `x_start`, `y_start`,
`x_end`, `y_end` (px), `amplitude_deg` (distance travelled, deg) and `peak_velocity_deg_s`.

### Areas of interest (AOI)

```bash
edge analyze aoi data/001_1_freeview_…
edge analyze aoi data/001_1_freeview_… --aoi face:rect:0,100,300,200 --aoi centre:circle:0,0,80:view --by condition
```

AOIs come from the experiment: every **gaze area** item (`gaze_roi`; one that follows a picture or shape
uses that item's area), every **picture** and every **shape** (rectangles and triangles by their box,
circles, ellipses and polygons by their outline), on the screens where they were shown, with positions and
sizes worked out per trial (also `$` expressions such as `$[side * 250, 0]`), in the experiment's units.
A picture shown at its own size has no known size here: give it one, or define the area yourself.

Your own AOIs: `--aoi name:rect:x,y,width,height` or `--aoi name:circle:x,y,radius` (pixels from the
screen centre, +y up), with `:screen` at the end to limit it to one screen; or a YAML/JSON file
(`--aoi-file aois.yaml`) with a list of `{name, shape: rect|circle|ellipse|polygon, pos: [x, y],
size: [w, h] | radius | vertices, units, routine}`; in Python `aoi_report(session, aois=[...])`. They are
used on the screens that have AOIs of their own, or on every screen of a trial list.
`--no-experiment-aois` uses only yours.

`aoi_trials.csv` (one row per trial, screen and AOI):

| column | meaning |
|---|---|
| `trial`, `routine`, `aoi` | the trial (row of trials_wide.csv), the screen and the AOI |
| `aoi_source` | where the AOI came from: `gaze_roi`, `shape`, `image`, `gaze_roi -> left_img`, `user` |
| *condition columns* | the trial-list columns of `--by` (default: the trial list's factors) |
| `fixated` | 1 if any fixation landed in the AOI after it appeared |
| `first_fixation_latency` | s from the AOI's onset (the item appearing) to the start of the first fixation in it (0 if the eyes were already there) |
| `first_fixation_duration` | s, of that first fixation |
| `dwell_time` | total s of fixations in the AOI (from its onset to the end of the screen) |
| `fixation_count` | fixations in the AOI |
| `visits` | separate visits (runs of consecutive fixations in the AOI) |
| `revisits` | visits after the first (`visits - 1`) |
| `proportion` | `dwell_time` / all fixation time on the screen since the AOI appeared |
| `trial_fixation_time` | that total fixation time (s) |
| `screen_duration` | s from the AOI's onset to the end of the screen |

`aoi_summary.csv` (one row per screen, AOI and condition cell): `n_trials`, `n_fixated`, `p_fixated`
(share of trials with a fixation in the AOI) and the means of `first_fixation_latency` and
`first_fixation_duration` (over the trials where the AOI was fixated), `dwell_time`, `fixation_count`,
`visits`, `revisits` and `proportion` (over all trials).

## Scripting EDGE from Python

Everything the `edge` command does is also available from Python, e.g. to run a batch of test
participants or to load the data into your own analysis:

```python
import edge
from edge.export import SessionTables, export_many, summarize, wide_trials

summary = edge.run("stroop.yaml", participant="012", dry_run=True)   # like: edge run stroop.yaml -p 012 --dry-run
print(summary["data_dir"])                       # the session folder

st = SessionTables(summary["data_dir"])          # one session folder
cols, rows = wide_trials(st)                     # the trial table: column names, one dict per trial
sum_cols, sum_rows, info = summarize(st, rows)   # accuracy and RT per participant and condition

export_many("data", formats=["csv", "xlsx"])     # like: edge export data/ (add include_dry_runs=True for test runs)
```

* `edge.run(experiment, participant=..., **options)` loads the file (or takes an `edge.Experiment`)
  and runs it. `participant` is the ID (`"012"`) or a dict of participant fields
  (`{"participant": "012", "session": "2", "group": "A"}`), the same as `-p 012 -s 2 -f group=A`;
  IDs are stored as text, as on the command line. Options: `dry_run=True` (simulated devices and a
  virtual participant), `data_dir="..."`, `backend="headless"`. It returns the session summary.
* `edge.Experiment.load(path)` reads an experiment file (to change it in code before `edge.run`).
* `edge.export.export_session(folder, formats=["csv", "xlsx"])` exports one session, and
  `export_many(folder)` merges every session under a folder, like `edge export`.
