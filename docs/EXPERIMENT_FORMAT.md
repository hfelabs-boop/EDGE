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
Trial-list columns always win over a component with the same name: in a component called `word`,
`text: $word` shows the column's value. (Check notes the clash, since that component's own results
can't then be used by name.)

**Checked before running.** `edge validate`, the builder's Check tab and every test run look at each
expression where it is used: a name that no trial list, variable, component, loop or workflow
provides at that point is reported in plain words, with the closest match and the names that do
exist (*"the trial list has no column called 'ink'. Did you mean 'colour'?"*). A routine used both
inside and outside a loop gets a warning if it reads that loop's columns. Names assigned in `code`
components count as defined. A trial list named by an outer loop's column (`conditions: $block_file`)
is checked through the files that column lists; any other expression makes the check lenient for
that loop (a note says which names can only be checked at run time). Errors while running
are explained the same way, with a hint for common slips (`=` instead of `==`, missing quotes,
using a response before there is one).

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
    screen: 1                 # monitor index: the one the participant faces (0 = main)
    keep_focus: true          # take the keyboard back when another window gets it (false: the experimenter can
                              # type in another window during the session; see BUILDER_GUIDE "Two monitors")
    background: "#808080"
    units: px                 # px | norm | height | deg
    refresh_rate: null        # null = measure at startup
    monitor: {width_cm: 53, distance_cm: 60}   # for deg units
    gamma: 2.2                # optional: the monitor's gamma, [r, g, b], or a calibration file (see below)
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
        if: "$practice"        # include this component only when true (evaluated when the routine starts)
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
| | `movie` | movie (file or $column), size, loop, volume, pos, opacity (see [Video](#video)) | onset, first_frame, duration, movie_duration, frames_shown, frames_dropped, frames_repeated, ended |
| | `grating` | sf, sf_units (cycles/deg, cycles/px), phase, tf (drift, Hz), wave (sin/sqr), contrast, mask (none/circle/gauss/raisedcos), sigma, size, ori (see [Vision-science stimuli](#vision-science-stimuli-and-gamma)) | onset, duration, frames, sf_cpd, phase |
| | `gabor` | sigma, sf, sf_units, phase, tf, contrast, ori, size (default 6 × sigma) | onset, duration, frames, sf_cpd, phase |
| | `noise` | noise_type (white/pink/brown/binary), element_size, dynamic, update_frames, seed, contrast, mask | onset, duration, frames, seed, samples |
| | `dots` | n_dots, coherence, direction, speed, dot_size, lifetime, noise_dots (same/random_walk/random_position), field_shape, size, seed | onset, duration, frames, seed, n_signal |
| | `html` | file or html, display (auto/webview/browser), fullscreen, continue_button | every form field, submitted, rt |
| | `survey` | questions (incl. `{instrument: phq9}` from the library), title, intro, language, scores, allow_back (see [Surveys](SURVEYS.md)) | every answer and score, submitted, rt |
| response | `keyboard` | keys, store (first/last/all), correct, record_release, response_marker | keys, rt, corr, time, duration |
| | `device_response` | device, inputs, correct, store, keys (keyboard stand-ins), response_marker: a button box, fMRI buttons, foot pedal, voice key or TTL line | input, rt, corr, time, device |
| | `mouse` | buttons, clickable (component ids), correct, track, touch (taps count), swipe (directions), swipe_distance, record_touches, response_marker | x, y, button, clicked, rt, corr, path, swipe, touches, n_touches |
| | `microphone` | samplerate, channels, device, voice_key, stop_after_speech, threshold_db, min_ms, release_ms, response_marker: a WAV file per screen in `audio/` (see [Devices](DEVICES.md#spoken-answers-touchscreens-and-gamepads)) | file, rt (speech onset), offset, duration, source |
| | `gamepad` | buttons (a, b, x, y, lb, rb, lt, rt, up … or stick_left …), correct, axis_threshold, deadzone, track, gamepad, keys | button, rt, corr, time, axes, gamepad, path |
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

## Workflow logic

EDGE has four levels of control flow. Use the simplest one that does the job.

| need | use |
|---|---|
| show a component only on some trials | component `if: "$practice"` |
| skip a routine sometimes | flow entry `{routine: feedback, if: "$practice"}` |
| choose between two sequences once | flow `if` / `then` / `else` |
| react *during* a routine (timeouts, hints, abort keys, gaze events) | routine `rules` |
| repeat a block until a criterion, adaptive paths, screening, multi-stage studies | flow `statemachine` |

### Routine rules ("when → do")

```yaml
routines:
  trial:
    rules:
      - name: hint                       # optional; recorded in the data column rules_fired
        when: "$t > 3 and resp.keys is None"
        do: [{start: hint}, {marker: hint_shown}]
      - when: "$resp.keys == 'q'"
        do: [{goto: debrief}]            # leave the current workflow state immediately
      - when: "$roi.completed"
        do: [{set: {fixated: true}}, end_routine]
        repeat: false                    # true: fire again each time the condition becomes true
    components: [...]
```

Rules are checked every frame after input is processed and fire when their condition *becomes*
true. Actions: `set` (variables), `start` / `stop` (a component of this routine), `marker`,
`end_routine`, `goto` (a state of the enclosing workflow, or `end`), and `log`.

### Workflows (state machines)

```yaml
flow:
  - statemachine: session
    start: practice
    states:
      practice:
        run:
          - loop: prac
            conditions: practice.csv
            children: [trial]
        max_visits: 3                       # after 3 visits, stop repeating and move on
        next:
          - {if: "$prac.accuracy >= 0.8", goto: main, set: {passed: true}}
          - {goto: practice}                # default route (no condition)
      main:
        run: [main_block_loop_or_routines]
        next: [end]
```

After a state's contents finish, its routes are checked top to bottom and the first one whose
`if` is true is taken (a route without `if` always matches; `end` leaves the workflow). `set`
assigns variables on the way. A rule `goto` jumps immediately. `max_visits` bounds repetition:
once reached, routes back to the same state are skipped and, if nothing else matches, the first
route to another state is taken. `max_steps` (default 1000) guards against endless loops.

Workflows can contain loops, branches and other workflows. The data gets `<workflow>.state` and
`<workflow>.visit` columns, and `session.json` records the path taken.

### Live performance of loops

While a loop runs (and after it ends), its results are available to expressions:
`trials.accuracy`, `trials.n_correct`, `trials.n_responses`, `trials.mean_rt`, alongside `trials.n`
and `trials.total`. Accuracy uses every `*.corr` result recorded inside the loop; RT uses every
`*.rt`. These values are what makes adaptive rules like `$prac.accuracy >= 0.8` work.

## Surveys

```yaml
- id: about
  type: survey
  end_routine: true
  title: About you
  questions:
    - {instrument: demographics}                 # library questionnaire, see reference/questionnaires.md
    - {id: mood, type: likert, scale: agree7, text: "I feel good right now.", required: true}
    - {id: why, type: essay, text: "Why?", show_if: {mood: {"<=": 3}}}
    - type: page_break
    - {instrument: gad7}
```

Question types: `text_block`, `single`, `dropdown`, `multiple`, `likert`, `matrix`, `semantic`, `scale`,
`nps`, `slider`, `graphic_slider`, `text`, `essay`, `number`, `date`, `form`, `rank`, `side_by_side`,
`constant_sum`, `group`, `hot_spot`, `heat_map`, `drill_down`, `highlight`, `signature`, `timing`,
`meta_info`, `file_upload`, `captcha`, `autocomplete`, `tree_test`, `video_response`, `screen_capture`,
`location`, `page_break`. Common keys: `id`, `text`, `required`, `help`, `show_if`, `randomize`,
`correct`, `test_answer`. Survey keys `language` and `direction` set the page language and right-to-left
layout. Files (signatures, uploads, recordings, screenshots) are saved in the session's `survey_files/`. Each answer becomes
a column `<survey id>.<question id>` (matrix items by item id); library questionnaires add their scores.
Question text is used as written: a leading `$` is not an expression there. The full guide:
[Surveys](SURVEYS.md).

## Video

```yaml
- id: clip
  type: movie
  movie: videos/$clip_file        # a file next to the experiment, or $column from the trial list
  size: [960, 540]                # empty: the video's own size
  volume: 0.8                     # 0 mutes the sound track
  loop: false                     # true: start again at the end, until the item's duration ends
  end_routine: true               # the screen ends when the video ends
  marker: video_on                # sent on the flip that shows the first frame
```

* **Frame-locked.** On every screen refresh EDGE shows the video frame whose time has come (frame *k* is shown
  from *k / fps* seconds after the first frame), so a 30 fps video on a 60 Hz screen shows each frame for exactly
  two refreshes. The item ends when the video does (unless it loops or its `duration` is shorter).
* **What is recorded:** `onset` and `first_frame` (when the first frame appeared, at the flip),
  `duration` (how long it was on the screen), `movie_duration` (the file's length), `frames_shown`,
  `frames_dropped` (frames never shown although their time came: the decoder fell behind),
  `frames_repeated` (refreshes on which a frame stayed longer than its time) and `ended` (1 if it played to the end).
* **The experiment window** decodes with pyglet and FFmpeg (`pip install edge-experiments[video]`, plus FFmpeg's
  shared libraries: Windows: a "shared" build from ffmpeg.org on PATH; macOS: `brew install ffmpeg`;
  Ubuntu: `sudo apt install ffmpeg`). Without FFmpeg the session stops before it starts and says what to install.
  The sound track plays through a second player started on the first frame; audio-video sync is good to a frame
  or two, not to the millisecond (time sounds that must be exact with a `sound` item).
* **Encode for the lab:** MP4 with H.264 (or WebM), without B-frames, at a frame rate that divides the monitor's
  (30 or 60 fps on a 60 Hz screen): `ffmpeg -i in.mov -c:v libx264 -bf 0 -crf 18 -r 30 out.mp4`. EDGE notes files
  with B-frames: FFmpeg-through-pyglet can skip some of their frames (the data then show them as dropped).
* **Test runs** read the length, the picture size and the frame rate from the file's header (MP4/MOV, WebM/MKV,
  AVI), so a screen with a video lasts as long as in the real session. When the length can't be read, test runs
  use the item's `duration` (or 5 s) and validation says so.
* **Try it** plays the video in the browser, kept in step with the engine (MP4 with H.264 and WebM play in every
  browser; other formats show a placeholder there but play in the experiment window). The builder's preview shows
  the frame at the moment you look at.
* **Checks:** a missing file, a sound-only file (`.m4a`, or an `.mp4` without a picture: use a `sound` item),
  a file that isn't a video, and every file named in a trial-list column.

## Vision-science stimuli and gamma

Gratings, Gabor patches, noise and random-dot kinematograms are items like any other: every property can be a
`$column` of the trial list or a formula, and they work in the experiment window, test runs, Try it and the preview.

```yaml
- {id: grating, type: grating, sf: $sf, sf_units: cycles/deg, ori: $ori, contrast: $contrast,
   tf: 4, mask: raisedcos, size: [6, 6], units: deg, duration: 0.5}
- {id: target, type: gabor, sigma: 0.5, sf: 3, phase: 0.25, ori: 45, contrast: 0.2, units: deg, duration: 0.2}
- {id: mask, type: noise, noise_type: pink, dynamic: true, update_frames: 2, contrast: 0.8, size: [8, 8], units: deg}
- {id: rdk, type: dots, n_dots: 200, coherence: $coh, direction: $dir, speed: 5, dot_size: 0.1,
   lifetime: 10, noise_dots: same, size: [10, 10], units: deg, duration: 1.5}
```

* **Patterns** are luminance modulations around the mean grey: intensity = 0.5 × (1 + contrast × pattern), in
  linear light. `color` tints the bright parts (white = grey levels). Masks are transparent outside the patch;
  use a mid-grey `background` so the edges don't show. `ori` turns the bars clockwise (0 = vertical bars);
  `phase` is in cycles; a positive `tf` (Hz) drifts the bars to the right at `ori: 0`.
* **gabor** is a grating in a Gaussian window of standard deviation `sigma`; its patch is 6 × sigma unless `size`
  is given. A grating's `mask: gauss` uses `sigma` too (default: size / 6); `raisedcos` has a soft `edge`.
* **noise:** white (uniform), pink (1/f amplitude spectrum, like natural images), brown (1/f²) or binary;
  `element_size` sets the size of one check; `dynamic: true` draws a new sample every `update_frames` refreshes.
* **dots:** `coherence` is the fraction of signal dots moving in `direction` (0 = right, 90 = up, counter-clockwise);
  the others move as `noise_dots` says: `same` (each keeps a random direction), `random_walk` (a new direction every
  frame) or `random_position` (re-plotted every frame). Dots that leave the aperture come back on the other side;
  `lifetime` (frames, 0 = forever) re-plots old dots. `speed` is in window units per second.
* **Seeds.** Without `seed`, noise and dots get one made from the session's seed, the screen and how many times
  the item was shown, so a session with the same `settings.seed` shows exactly the same noise and dots; the seed
  used is saved in the item's `seed` column. With `seed: 42` every showing is the same.
* **Degrees** (`units: deg`, `sf_units: cycles/deg`) need the monitor's visible screen width and the viewing
  distance: `settings.window.monitor: {width_cm, distance_cm}` (Experiment settings → Screen). EDGE assumes the
  window fills the screen at its native resolution; if it doesn't, add `width_px` (the screen's width in pixels).
  Validation notes when the defaults (53 cm, 60 cm) are still in place.
* **numpy** computes the patterns (`pip install edge-experiments[vision]`); without it they are computed in plain
  Python (slow for large patches) and pink/brown noise falls back to white noise. Try it draws the same gratings and
  Gabors and the same dots; its noise has the same kind and grain but not the same pixels.

### Gamma calibration

A monitor's light is not proportional to the pixel value: L = L0 + k · v^γ, with γ around 2.2. Contrast is only
linear when EDGE knows γ:

```yaml
settings:
  window:
    background: "#808080"
    gamma: calibration/lab1.json      # or: 2.2   or: [2.1, 2.2, 2.3] (red, green, blue)
    gamma_method: auto                # auto | ramp | stimuli
```

`monitor: {calibration: calibration/lab1.json}` works too. With `ramp` the graphics card's gamma table makes the
whole screen linear (pictures and text too, as in PsychoPy); with `stimuli` only gratings, Gabors, noise and the
background are corrected (their texture values go through the inverse of the measured curve); `auto` uses the
table where the system allows it (Windows, macOS, X11 on Linux; not Wayland) and otherwise corrects the stimuli.
session.json records which calibration was used, its file's SHA-256 and the method (`gamma`).

**Measuring** takes ten minutes and a photometer: `edge gamma experiment.yaml --show` shows N grey levels full
screen in the experiment window; type each luminance reading (cd/m²) into the window and press Enter. EDGE fits γ
(and the black level), shows the fit and saves `calibration/monitor.json` next to the experiment (`--name lab1`,
`--use` also sets `settings.window.gamma`). Readings taken elsewhere: `--readings "0.4,2,6.5,…"` (black to white)
or `--csv readings.csv` (columns `level, luminance`, or `level, r, g, b` for each channel). In the builder:
Experiment settings → Colour & gamma → Measure the monitor (full-screen patches in the browser, a reading per
level, Fit, Save and use). Warm the monitor up for 30 minutes and turn off dynamic contrast, night light / True Tone
and picture modes first.

## Live device values

Expressions can read the latest sample of every device: `$devices.<device>.<channel>` (or
`$devices.<device>.<stream>.<channel>`), and `$devices.<device>.age`, the seconds since that sample.
A `udp_messages` device exposes the fields of the messages another program sent. See
[Devices](DEVICES.md#closed-loop).

## measures

What the experiment measures: outcomes, factors, covariates and checks, each pointing at a recorded
column, with how to summarise it (`mean`, `median`, `proportion` …), on which trials (`trials:`
filter, `loop:`) and the plausible range (`expect`). See [Measures](DATA.md#measures-saying-what-the-experiment-measures).

```yaml
measures:
  - {id: rt, role: outcome, column: resp.rt, trials: $resp.corr == 1, summary: median, expect: [0.15, 2.5]}
  - {id: congruent, role: factor, column: congruent}
```

Every component type declares the columns it records (`edge components --json` lists them under
`outputs`), and every device the streams it records (`planned_streams`).

## HTML pages

```yaml
- id: consent
  type: html
  file: pages/consent.html          # or  html: "<p>Inline page</p>"
  end_routine: true
```

* Any form on the page ends it when submitted. Every named field becomes a data column
  (`consent.agree`, `demo.age` …), with numbers converted, plus `rt` and `submitted`.
* `{{variable}}` placeholders are filled with trial values (HTML-escaped). JavaScript sees all
  values in `window.edge.vars`.
* Custom JS tasks call `edge.submit({...})` to save results and finish, and `edge.marker("label")`
  to send an event marker to every device.
* Pages without a form get a **Continue** button (`continue_button: auto|yes|no`).
* Images, CSS and JS next to the page are served with it and included in `.edgez` bundles.
* Display: a native full-screen window when `pywebview` is installed (`pip install pywebview`),
  otherwise the system browser.
* In dry runs the virtual participant fills in every form (respecting `required`, `min`/`max`,
  options), so questionnaires appear in the test data.
