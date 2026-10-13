# Command-line reference

Generated from the code by `edge docs build`.

## edge start

open the builder on your experiments folder (what `edge` alone does)

```
edge start [-h] [--port PORT] [--no-browser] [directory]
```

| argument | description |
|---|---|
| `directory` | experiments folder, or an experiment file to open the folder it is in (default: 'EDGE Experiments' in your Documents folder, or in your home folder if there is none) |
| `--port` | local port for the builder (default: 8765) |
| `--no-browser` | do not open a browser window |

## edge desktop-shortcut

put an EDGE icon on the desktop / in the app menu

```
edge desktop-shortcut [-h] [--workspace WORKSPACE]
```

| argument | description |
|---|---|
| `--workspace` | folder the icon opens (default: 'EDGE Experiments' in your Documents folder, or in your home folder if there is none) |

## edge wizard

answer a few questions and get a finished experiment

```
edge wizard [-h] [--answers ANSWERS] [directory]
```

| argument | description |
|---|---|
| `directory` | where to create it (default: the current folder) |
| `--answers` | JSON or YAML file with the answers instead of asking |

## edge run

run an experiment

```
edge run [-h] [-p PARTICIPANT] [-s SESSION] [-f KEY=VALUE] [--dry-run]
                [--simulate-devices]
                [--backend {pyglet,headless,headless-realtime}]
                [--data-dir DATA_DIR] [--report] [--fullscreen | --windowed]
                experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file (.yaml or .json) |
| `-p, --participant` | participant id (also used for counterbalancing; default: the experiment's, usually 001). EDGE warns if it already has data |
| `-s, --session` | session number (default: 1) |
| `-f, --field` | another participant field, e.g. -f age=30 (repeat for more) |
| `--dry-run` | test run: no window, simulated devices, a virtual participant; saved under data/dry_runs |
| `--simulate-devices` | replace hardware with simulators |
| `--backend` | pyglet (default): the experiment window; headless-realtime: no window, real clock (screenless tasks with real hardware); headless: no window, simulated clock, for automated tests (to test an experiment use --dry-run) |
| `--data-dir` | where to write data (default: data/ next to the experiment) |
| `--report` | print the quality report afterwards |
| `--fullscreen` | full screen (overrides the experiment setting) |
| `--windowed` | in a window |

## edge validate

check an experiment for errors

```
edge validate [-h] [--json] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--json` | machine-readable output |

## edge devices

list device drivers

```
edge devices [-h] [--json]
```

| argument | description |
|---|---|
| `--json` | full driver descriptions as JSON |

## edge components

list components

```
edge components [-h] [--json]
```

| argument | description |
|---|---|
| `--json` | full component descriptions as JSON |

## edge scan

discover connected hardware (LSL, serial, Tobii, Gazepoint)

```
edge scan [-h] [--timeout TIMEOUT] [--json]
```

| argument | description |
|---|---|
| `--timeout` | seconds to listen for LSL streams |
| `--json` | machine-readable output |

## edge doctor

check this computer for known causes of bad timing and lost responses

```
edge doctor [-h] [--fix] [--json] [experiment]
```

| argument | description |
|---|---|
| `experiment` | also check against this experiment's screen and devices |
| `--fix` | fix what can be fixed automatically |
| `--json` | machine-readable output |

## edge preflight

go / no-go before collecting data: checks, test run, lock, computer

```
edge preflight [-h] [--no-golden] [--no-computer] [--json] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--no-golden` | don't re-run the golden participant of the lock |
| `--no-computer` | skip the computer check |
| `--json` | machine-readable output |

## edge test-device

connect an experiment's device(s): data rate, inputs, a test marker

```
edge test-device [-h] [--seconds SECONDS] [--simulate]
                        experiment [device]
```

| argument | description |
|---|---|
| `experiment` | experiment file whose devices to test |
| `device` | device id (default: all of the experiment's devices) |
| `--seconds` | how long to record from each device (default: 3) |
| `--simulate` | test with the device's simulator |

## edge timing-test

create a timing test: real display, audio and trigger latency on this computer

```
edge timing-test [-h] [directory]
```

| argument | description |
|---|---|
| `directory` | where to create it (default: the current folder) |

## edge update

download and install the newest EDGE

```
edge update [-h] [--check] [--stash] [--branch BRANCH]
```

| argument | description |
|---|---|
| `--check` | only look whether there is something new |
| `--stash` | set your own uncommitted changes aside and put them back after |
| `--branch` | git branch to update from (default: the one you are on) |

## edge lock

record versions, file fingerprints and a golden participant after piloting

```
edge lock [-h] [--no-golden] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--no-golden` | skip the golden-participant dry run |

## edge verify

check that the experiment, its files and this computer still match the lock

```
edge verify [-h] [--no-golden] [--json] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file (its lock is the .lock.json next to it) |
| `--no-golden` | skip the golden-participant dry run |
| `--json` | machine-readable output |

## edge support-bundle

pack everything needed to ask for help (no participant data)

```
edge support-bundle [-h] [--out OUT] [--include-data] path
```

| argument | description |
|---|---|
| `path` | an experiment file or a session folder |
| `--out` | where to write the .zip |
| `--include-data` | also include the trial data (participant fields removed) |

## edge report

timing / data / sync quality report for a session

```
edge report [-h] [--json] session_dir [session_dir ...]
```

| argument | description |
|---|---|
| `session_dir` | a session folder in data/ (a data folder or an experiment file means its newest session) |
| `--json` | machine-readable output |

## edge align

align an external recording via shared TTL codes

```
edge align [-h] [--tolerance TOLERANCE] [--json]
                  session_dir [session_dir ...] external
```

| argument | description |
|---|---|
| `session_dir` | the EDGE session folder |
| `external` | CSV with columns time,code (external clock) |
| `--tolerance` | maximum timing mismatch (s) when pairing events (default: 0.05) |
| `--json` | machine-readable output |

## edge new

create an experiment from a template

```
edge new [-h] template [directory]
```

| argument | description |
|---|---|
| `template` | blank, stroop, freeview_eyetracking, eeg_oddball, timing_test, staircase, online_questionnaire |
| `directory` | where to create it |

## edge builder

open the visual experiment builder

```
edge builder [-h] [--host HOST] [--port PORT] [--no-browser]
                    [directory]
```

| argument | description |
|---|---|
| `directory` | folder with your experiments, or an experiment file to open the folder it is in (default: the current folder) |
| `--host` | interface to listen on (keep the default for safety) |
| `--port` | local port for the builder |
| `--no-browser` | do not open a browser window |

## edge export

export analysis-ready tables (one session or a whole data folder)

```
edge export [-h] [--formats FORMATS] [--layout {wide,long}] [--out OUT]
                   [--name NAME] [--include-dry-runs]
                   path
```

| argument | description |
|---|---|
| `path` | session folder or data folder |
| `--formats` | one or more of csv,tsv,xlsx,json,jsonl,parquet,mat,bids, separated by commas (default: csv,xlsx) |
| `--layout` | wide (default): one row per trial; long: one row per routine |
| `--out` | output folder (default: <path>/exports) |
| `--name` | start of the file names (default: the session folder's name, or <experiment>_all_<date> for a data folder) |
| `--include-dry-runs` | also include dry-run sessions |

## edge bundle

pack an experiment and its files into a .edgez archive

```
edge bundle [-h] [--out OUT] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--out` | bundle file, or a folder to put <experiment>.edgez in (default: <experiment>.edgez next to the experiment) |

## edge unbundle

extract a .edgez archive

```
edge unbundle [-h] bundle [directory]
```

| argument | description |
|---|---|
| `bundle` | .edgez file |
| `directory` | folder with your experiments (default: current) |

## edge backups

list or restore automatic backups of an experiment

```
edge backups [-h] [--restore [RESTORE]] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--restore` | restore the newest backup, or the given id |

## edge import

import a PsychoPy, E-Prime, OpenSesame or jsPsych experiment

```
edge import [-h] [--out OUT]
                   [--platform {psychopy,eprime,opensesame,jspsych}]
                   [--name NAME]
                   source
```

| argument | description |
|---|---|
| `source` | .psyexp, .ebs3/.ebs2, .osexp/.opensesame, or jsPsych .html/.js |
| `--out` | output folder (default: <source>_edge next to the source) |
| `--platform` | force the source platform (normally detected) |
| `--name` | name for the imported experiment |

## edge help

read the documentation or search it

```
edge help [-h] [--first] [--raw] [--limit LIMIT] [query ...]
```

| argument | description |
|---|---|
| `query` | a guide name (e.g. cookbook) or search words (e.g. jitter isi) |
| `--first` | show the best search match in full |
| `--raw` | print Markdown as is |
| `--limit` | number of search results |

## edge tutorial

list or start the interactive tutorials

```
edge tutorial [-h] [--print] [--port PORT] [--no-browser]
                     [name] [directory]
```

| argument | description |
|---|---|
| `name` | tutorial id (omit to list) |
| `directory` | folder to work in (default: tutorial_<name>) |
| `--print` | print the tutorial instead of starting it |
| `--port` | local port for the builder |
| `--no-browser` | do not open a browser window |

## edge docs

for EDGE developers: regenerate the reference pages (to read the docs: edge help)

```
edge docs [-h] [--check] [{build}]
```

| argument | description |
|---|---|
| `action` | build: regenerate reference pages and TUTORIALS.md |
| `--check` | only report whether generated pages are up to date |

## edge assistant

change experiments by describing them (Claude, OpenAI-compatible, Ollama or LM Studio)

```
edge assistant [-h] {setup,config,test,models,ask} ...
```

| argument | description |
|---|---|
| `action` | setup, config, test, models or ask (edge assistant <action> -h for its options) |

## edge mcp

run the MCP server (natural-language control from Claude / VS Code)

```
edge mcp [-h] [--root ROOT] [--transport {stdio,sse,streamable-http}]
                [directory]
```

| argument | description |
|---|---|
| `directory` | workspace folder (the same as --root) |
| `--root` | workspace folder the server may read and write |
| `--transport` | stdio for Claude/VS Code; http transports for remote clients |

