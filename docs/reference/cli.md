# Command-line reference

Generated from the code by `edge docs build`.

## edge start

open the builder on your experiments folder (what `edge` alone does)

```
edge start [-h] [--port PORT] [--no-browser] [directory]
```

| argument | description |
|---|---|
| `directory` | experiments folder (default: ~/Documents/EDGE Experiments) |
| `--port` | local port for the builder |
| `--no-browser` | do not open a browser window |

## edge desktop-shortcut

put an EDGE icon on the desktop / in the app menu

```
edge desktop-shortcut [-h] [--workspace WORKSPACE]
```

| argument | description |
|---|---|
| `--workspace` | folder the icon opens (default: ~/Documents/EDGE Experiments) |

## edge wizard

answer a few questions and get a finished experiment

```
edge wizard [-h] [--answers ANSWERS] [directory]
```

| argument | description |
|---|---|
| `directory` | where to create it |
| `--answers` | JSON file with the answers instead of asking |

## edge run

run an experiment

```
edge run [-h] [-p PARTICIPANT] [-s SESSION] [-f FIELD] [--dry-run]
                [--simulate-devices]
                [--backend {pyglet,headless,headless-realtime}]
                [--data-dir DATA_DIR] [--report] [--fullscreen | --windowed]
                experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file (.yaml or .json) |
| `-p, --participant` | participant id (also used for counterbalancing) |
| `-s, --session` | session id |
| `-f, --field` | extra participant field key=value |
| `--dry-run` | headless, simulated devices, virtual participant |
| `--simulate-devices` | replace hardware with simulators |
| `--backend` | headless-realtime: no window, real clock (screenless tasks with real hardware) |
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

## edge report

timing / data / sync quality report for a session

```
edge report [-h] [--json] session_dir
```

| argument | description |
|---|---|
| `session_dir` | a session folder in data/ |
| `--json` | machine-readable output |

## edge align

align an external recording via shared TTL codes

```
edge align [-h] [--tolerance TOLERANCE] session_dir external
```

| argument | description |
|---|---|
| `session_dir` | the EDGE session folder |
| `external` | CSV with columns time,code (external clock) |
| `--tolerance` | maximum timing mismatch (s) when pairing events |

## edge new

create an experiment from a template

```
edge new [-h] template [directory]
```

| argument | description |
|---|---|
| `template` | blank, freeview_eyetracking, eeg_oddball or staircase |
| `directory` | where to create it |

## edge builder

open the visual experiment builder

```
edge builder [-h] [--host HOST] [--port PORT] [--no-browser]
                    [directory]
```

| argument | description |
|---|---|
| `directory` | folder with your experiments (default: current) |
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
| `--formats` | csv,tsv,xlsx,json,jsonl,parquet,mat,bids |
| `--layout` | wide: one row per trial; long: one row per routine |
| `--out` | output folder (default: <path>/exports) |
| `--name` | file name stem for merged exports |
| `--include-dry-runs` | also include dry-run sessions |

## edge bundle

pack an experiment and its files into a .edgez archive

```
edge bundle [-h] [--out OUT] experiment
```

| argument | description |
|---|---|
| `experiment` | experiment file |
| `--out` | bundle path (default: <experiment>.edgez) |

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

regenerate the reference documentation from the code

```
edge docs [-h] [--check] [{build}]
```

| argument | description |
|---|---|
| `action` | build: regenerate reference pages and TUTORIALS.md |
| `--check` | only report whether generated pages are up to date |

## edge mcp

run the MCP server (natural-language control from Claude / VS Code)

```
edge mcp [-h] [--root ROOT] [--transport {stdio,sse,streamable-http}]
```

| argument | description |
|---|---|
| `--root` | workspace folder the server may read and write |
| `--transport` | stdio for Claude/VS Code; http transports for remote clients |

