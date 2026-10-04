# Importing from other platforms

```bash
edge import stroop.psyexp                 # PsychoPy Builder
edge import Stroop.ebs3                   # E-Prime 2/3 (generated script + List exports)
edge import task.osexp                    # OpenSesame
edge import experiment.html               # jsPsych 6/7
```

You can also use the builder's **Import** button (drop all the files at once: experiment,
conditions, images, list exports), or ask Claude through MCP (`import_experiment`).

Each import creates a folder with the EDGE experiment, copies of every file it needs, and
**`IMPORT_REPORT.md`**, which lists:

* **Not converted:** things that need manual work (unsupported components, E-Basic InLine code,
  JavaScript functions);
* **Converted approximately:** check these against the original (e.g. a staircase's variable,
  a slide sub-object without a position);
* **Notes:** conversions worth knowing about.

The result is validated, and you should **always dry-run it** (`edge run file --dry-run --report`)
and compare trial counts and timing with the original. While these importers were being built,
dry runs caught several conversion gaps that are now handled automatically.

## PsychoPy (.psyexp)

The most complete conversion, since the format is open XML.

| PsychoPy | EDGE |
|---|---|
| settings: units, window size, full screen, colour, experiment info | `settings.window`, `settings.participant` |
| Text, Textbox | `text` (editable textboxes → note: use an html form) |
| Image, Polygon (rect/circle/cross/line/triangle) | `image`, `shape` |
| Keyboard (allowed keys, store, correct answer, force end) | `keyboard` |
| Mouse, Slider, Sound (files, notes like A, Hz) | `mouse`, `slider`, `sound` |
| Static period | `wait` |
| Code (Begin/Each Frame/End Routine; Begin Experiment → setup routine) | `code` (`on_begin`/`on_frame`/`on_end`) |
| ParallelOut / SerialOut | `marker` (reaches every TTL/LSL device) |
| ROI (eye tracking) | `gaze_roi` |
| start/stop as time, frame, duration or condition | `start`/`duration`/`start_frame`/`duration_frames`/`start_if`/`stop_if` |
| colours in rgb (−1…1), rgb1, rgb255, hex, names | hex / names |
| Loops: conditions file, nReps, random/sequential/fullRandom, selected rows | `loop` |
| Staircase loops | `staircase` (check the variable name and the correctness source) |
| `trials.thisN`, `thisRepN`, `expInfo['x']`, `continueRoutine = False` | `trials.n`, `.repeat`, `x`, `end_routine()` |

Not converted: movies, microphone, joystick, button boxes, PsychoPy Forms (use an html page), and
code that calls PsychoPy APIs directly (`win`, `thisExp`, `event` …), which is flagged.

## E-Prime 2/3

`.es3`/`.es2` files are a closed binary format. In E-Studio, press **Generate** (Ctrl+F7). It writes
the E-Basic script (`.ebs3`/`.ebs2`) next to your experiment, and that script is what you import.
For list contents, also **save each List to a text file** (right-click the List → Save to file) as
`<ListName>.txt` in the same folder. The importer picks these up automatically. Lists that load
rows from an external file work as well.

| E-Prime | EDGE |
|---|---|
| TextDisplay, ImageDisplay, SoundOut, Wait | one routine each |
| Slide with SlideText/SlideImage sub-objects (X/Y in %, px or center) | routine with positioned components |
| Duration (ms, −1 = until response) | routine/response durations (s) |
| Input masks: allowed keys (`{SPACE}`, `{ANY}`, `rgb`), correct answer, time limit, terminate | `keyboard` (keys, correct, duration, end_routine) |
| `[Attribute]` references, `c.GetAttrib("x")`, `[Subject]`/`[Session]` | `$attribute`, f-strings, `participant`/`session` |
| Procedures | sequences in the flow |
| List: rows and Weight, order (sequential/random/permuted/counterbalance/offset), Cycles, Samples | `loop` (weights expand rows) |
| FeedbackDisplay | text using the previous response (`prev_corr`), flagged for checking |

Not converted: InLine E-Basic (copied into the report), movies, and some advanced Slide features. The
generated script differs between E-Prime versions, so this importer is best effort: check the report.

## OpenSesame (.osexp, .opensesame)

Settings, sequences (including run-if conditions), loops (`setcycle` tables, repeat, order,
`break_if`, file sources), sketchpads and feedback items (textline, fixdot, rect, circle, ellipse,
line, image), keyboard and mouse responses, samplers, synths, delays, and inline_script (kept as
Python, flagged). A sketchpad with duration 0 followed by a keyboard_response becomes one routine, the
usual OpenSesame trial pattern. OpenSesame's built-in `[correct]`, `[response]` and
`[response_time]` are provided, so run-if conditions keep working. Coordinates are converted from
OpenSesame's y-down system. File-pool contents of `.osexp` archives are extracted.

## jsPsych (6/7, .html or .js)

A tolerant parser reads the timeline from inline scripts: object literals, variables,
`timeline.push(...)`, `jsPsych.timelineVariable()`, nested timelines with `timeline_variables`,
`randomize_order`, `repetitions`.

| jsPsych plugin | EDGE |
|---|---|
| html-keyboard-response, image-keyboard-response, audio-keyboard-response | text / image / sound + keyboard |
| html-slider-response | text + slider |
| html-button-response, image-button-response | html page with buttons |
| instructions | one html page per instruction page |
| survey-likert, survey-text, survey-multi-choice, survey-multi-select, survey-html-form | real html forms (answers saved as data) |
| fullscreen | window setting; preload/call-function/browser-check are skipped |

JavaScript functions (dynamic durations, `on_finish`, `conditional_function`, `loop_function`)
can't be translated. They are listed in the report with suggestions: a workflow for loop
functions, a component `if` or branch for conditional functions, an expression such as
`$random.choice([0.25, 0.5])` for random durations.
