# Experiment format reference

An experiment is one YAML (or JSON) document. The visual builder reads and writes this same format.

```yaml
name: my_study
description: optional text
settings: {...}
devices: [...]
variables: {score: 0}
routines: {name: {components: [...]}}
flow: [...]
```

## Expressions

Any string property that starts with `$` is a Python expression evaluated at runtime. Write `$$` for
a literal leading dollar sign.

```yaml
text: $word                          # a conditions column
color: "$'green' if resp.corr else 'red'"
text: "$f'Score: {score} / {trials.total}'"
pos: "$[side * 300, 0]"
opacity: $contrast                   # staircase variable
```

Names in scope, from lowest to highest priority:
participant fields (`participant`, `session`, …), experiment `variables`, loop columns (outer to inner),
loop state (`trials.n`, `trials.total`, `trials.remaining`, `trials.first`, `trials.last`, `trials.repeat`),
earlier components' results (`resp.rt`, `resp.corr`, …), the current routine's components, `t`
(routine time) and `frame`. `math`, `random`, `statistics`, `mean` and common builtins are available.

Expressions run in a sandbox: no imports, no attribute names starting with `_`, no lambdas, so an
experiment file shared between labs can't run arbitrary code. Use a `code` component when you need
full Python.

Properties marked *dynamic* (position, size, color, opacity, orientation, text, image) are
re-evaluated every frame when they are expressions, so `pos: "$[frame * 2, 0]"` animates.

## settings

```yaml
settings:
  window:
    size: [1920, 1080]
    fullscreen: true
    screen: 1                 # monitor index
    background: "#808080"
    units: px                 # px | norm | height | deg
    refresh_rate: null        # null = measure at startup
    monitor: {width_cm: 53, distance_cm: 60}   # for deg units
  participant: {participant: "001", session: "1", group: A}   # defaults; override on the command line
  data:
    dir: data
    filename: "{participant}_{session}_{experiment}_{date}"
  markers:
    codes: {stim_on: 10, response: 20}         # fixed TTL codes; other labels get codes automatically
  timing:
    frame_drop_tolerance: 1.5
    dry_run_routine_limit: 600
  seed: null                  # null = random per session (always saved in session.json)
```

Colors can be `#rrggbb`, `#rrggbbaa`, names (`red`, `gray` …), 0–255 tuples, 0–1 floats, or
PsychoPy-style −1…1 triplets.

## devices

```yaml
devices:
  - id: et                     # name used in components and data files
    type: tobii                # see `edge devices`
    options: {frequency: 300}
    required: true             # abort if it can't connect (false = warn and continue)
    record: true               # write its streams to disk
    markers: true              # receive broadcast markers
    calibrate: true            # calibrate at session start
```

## routines and components

```yaml
routines:
  trial:
    duration: 3                # optional hard cap (number or expression)
    end_if: "$resp.keys == 'q'"
    components:
      - id: word               # identifier: letters, digits, _
        type: text
        # --- scheduling (any component) ---
        start: 0.5             # seconds from the routine's first flip (or expression)
        duration: 1.0          # seconds; omit = until the routine ends
        start_frame: 30        # alternative: frame-based
        duration_frames: 6
        start_after: fix       # start when another component stops (+ optional start delay)
        start_if: "$frame > 10"
        stop_if: "$resp.keys is not None"
        end_routine: false     # true: the routine ends when this responds or times out
        disabled: false        # bool or expression
        save: true             # include results in trials.csv
        marker: "$f'word_{cond}'"   # or {onset: ..., offset: ..., code: 12}
        # --- component properties ---
        text: $word
```

Timing model: routine `t = 0` is the routine's first screen flip. Starts and stops are decided for
the upcoming flip, so durations are an exact number of frames. Onsets, offsets and markers are
stamped with the measured flip time. Response times are event time minus onset flip time.

Draw order: visual components draw in list order, so later ones appear on top. Non-visual logic
(gaze, code) runs before any drawing in each frame.

### Component types

Run `edge components` for the live list with descriptions; the builder shows every property with
help text.

| category | type | key properties | results |
|---|---|---|---|
| stimulus | `text` | text, color, height, font, bold, italic, wrap_width, pos, ori, opacity | onset, duration |
| | `shape` | shape (rect/circle/ellipse/polygon/line/cross), size, radius, vertices, fill, line_color | onset, duration |
| | `fixation` | size, line_width | |
| | `image` | image, size | |
| | `sound` | sound (file or Hz), volume, tone_duration | onset |
| response | `keyboard` | keys, store (first/last/all), correct, record_release, response_marker | keys, rt, corr, time, duration |
| | `mouse` | buttons, clickable (component ids), correct, track, response_marker | x, y, button, clicked, rt, corr, path |
| | `slider` | ticks, labels, granularity, require_confirm | rating, rt, history |
| eye tracking | `gaze_roi` | device, target or pos+radius/size, dwell, show | entered, first_entry, dwell_time, entries, completed, rt |
| | `gaze_follow` | device, target, offset, smoothing | |
| | `calibrate` | device | result |
| hardware | `marker` | label, code, devices, offset_label | label, code |
| logic | `variable` | set: {name: expr}, when (start/end) | the values set |
| | `code` | on_begin, on_frame, on_end (Python) | |
| | `wait` | (duration only) | |

`code` snippets have `vars`, `session`, `marker(label, code=None)`, `end_routine()`, `t` and all
names in scope. Names you assign become experiment variables. `on_begin` runs while the routine
is prepared, so components listed after the code component already see the new values.

## flow

```yaml
flow:
  - instructions                              # a routine
  - {routine: practice_feedback, if: "$practice_mode"}
  - loop: trials
    conditions: trials.csv                    # .csv .tsv .xlsx .json .yaml, inline list, or factorial
    order: random                             # sequential | random | fullrandom | latin_square | counterbalance
    repeats: 4
    max_repeat: {color: 2, kind: {deviant: 1}}
    select: "0:40"                            # or [0, 5, 7]
    stop_if: "$resp.keys == 'escape'"
    children: [fixation, trial, feedback]
  - if: "$trials_threshold < 0.2"
    then: [bonus_block]
    else: [standard_block]
```

* `random` shuffles each repeat separately; `fullrandom` shuffles all repeats together.
* `latin_square` uses a balanced Williams design indexed by the participant number;
  `counterbalance` uses all permutations (up to 6 rows).
* `factorial`: `conditions: {factorial: {color: [red, green], size: [1, 2]}, extra: {block: 1}}`.
* Each trial row keeps `<loop>.row` (its index in the conditions file) and `<loop>.n`.

### Staircases

```yaml
- loop: stairs
  staircase: {variable: contrast, start: 0.6, step: [0.1, 0.05, 0.02], down: 3, up: 1,
              min: 0.01, max: 1, log: false, reversals: 8, max_trials: 80, correct: resp.corr}
  children: [trial]
```

The threshold (mean of the final reversals) is saved in `session.json` and becomes the
variable `stairs_threshold` for the rest of the experiment.
