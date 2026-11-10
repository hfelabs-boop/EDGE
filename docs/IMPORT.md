# Importing from other platforms

```bash
edge import stroop.psyexp                 # PsychoPy Builder
edge import Stroop.ebs3                   # E-Prime 2/3 (generated script + List exports)
edge import task.osexp                    # OpenSesame
edge import experiment.html               # jsPsych 6/7
edge import stroop.iqx                    # Inquisit (.iqx, older .exp scripts)
edge import stroop.sce                    # Presentation (scenario + its .pcl program)
edge import task.json                     # Gorilla (task structure and/or spreadsheet .csv/.xlsx)
edge import stroop.m                      # Psychtoolbox (MATLAB script; partial translation)
```

You can also use the builder's **Import** button (drop all the files at once: experiment,
conditions, images, list exports), or ask Claude through MCP (`import_experiment`). EDGE recognises
the platform from the file itself; `--platform` (CLI) or `platform` (MCP) is only needed for an
unusual file.

Each import creates a folder with the EDGE experiment, copies of every file it needs, and
**`IMPORT_REPORT.md`**, which lists:

* **Won't run until fixed:** problems the check of the result found (for example a list export or
  conditions file that is missing); `edge import` then ends with exit code 1;
* **Not converted:** things that need manual work (unsupported components, E-Basic InLine code,
  JavaScript functions);
* **Converted approximately:** check these against the original (e.g. a staircase's variable,
  a slide sub-object without a position);
* **Notes:** conversions worth knowing about.

The result is validated, and you should **always dry-run it** (`edge run file --dry-run --report`)
and compare trial counts and timing with the original. While these importers were being built,
dry runs caught several conversion gaps that are now handled automatically.

An import never overwrites earlier work. Importing the same file again (say, after exporting a
missing list) updates the earlier import if nobody has changed it since, keeping the previous
experiment file as a backup (`edge backups`). If you have edited that import, recorded sessions
with it, or the folder holds another experiment or a file of the same name with other contents,
the new import is saved next to it in a folder ending in `_2` (`stroop_edge_2`), and the output
says so. A file from which nothing
could be converted (cut short, damaged, or not an experiment of that program) is refused with an
explanation, and nothing is written. Files saved as UTF-16 ("Unicode" in Windows programs) and
Windows paths such as `stimuli\red.png` are read as well.

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
| FeedbackDisplay | text using the previous response (`prev_corr`: 1 correct, 0 wrong, empty when there was no response, shown as "Too slow"), flagged for checking |

Not converted: InLine E-Basic (copied into the report), movies, and some advanced Slide features. The
generated script differs between E-Prime versions, so this importer is best effort: check the report.

## OpenSesame (.osexp, .opensesame)

Settings, sequences (including run-if conditions), loops (`setcycle` tables, repeat, order,
`break_if`, file sources), sketchpads and feedback items (textline, fixdot, rect, circle, ellipse,
line, image), keyboard and mouse responses, samplers, synths, delays, and inline_script (kept as
Python, flagged). A sketchpad with duration 0 followed by a keyboard_response becomes one routine, the
usual OpenSesame trial pattern. OpenSesame's built-in `[correct]`, `[response]` and
`[response_time]` are provided, so run-if conditions keep working. Coordinates are converted from
OpenSesame's y-down system. File-pool contents of `.osexp` archives are extracted. Text keeps its
line breaks (`<br />`) and, when it applies to all of the text, its colour, bold and italic; font
sizes stay in pixels.

## jsPsych (6/7, .html or .js)

A tolerant parser reads the timeline from the page's inline scripts and from its own script files
next to it (`<script src="experiment.js">`; jsPsych and its plugins are skipped): object literals,
variables, `timeline.push(...)`, `jsPsych.timelineVariable()`, nested timelines with
`timeline_variables`, `randomize_order`, `repetitions`. Routines and loops are named after the
variables that hold the trials (`fixation`, `test_procedure`).

Text is shown dark on jsPsych's white page. Simple inline HTML styling (colour, font size, bold,
italic) becomes text properties; when timeline variables hold HTML, its text and colour go into
new columns (`stimulus_text`, `stimulus_color`) next to the original. Styling that can't be kept is
listed in the report. A trial's `data` fields (`task: 'response'`) are saved as columns of the
trials table, as in jsPsych.

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

## Inquisit (.iqx, .exp)

Import the script with its pictures and sounds next to it (in the folders the script names, such
as `stimuli/`). Trials that differ only in their stimulus and correct key, as in most Stroop and
flanker scripts (`redcongruent`, `greencongruent` …), become **one screen** with a trial list: what
differs between them (the word, its colour, the correct key) becomes the columns `stim_text`,
`stim_color`, `correct_response`, and the column `trial` keeps the Inquisit trial name.

| Converted | EDGE |
|---|---|
| `<defaults>` screen colour, text colour, font size and bold | window background, text items |
| `<values>` | experiment variables |
| `<text>`, `<picture>`, `<sound>`, `<shape>`, `<port>` with `items` (inline or an `<item>` set), `txcolor`, `position`, `size`, `fontstyle` | text, image, sound, shape, marker items (sizes in % of a 1024×768 screen) |
| `stimulustimes` / `stimulusframes` | item `start` / `start_frame`; a later stimulus at the same place ends the earlier one (as Inquisit's text background covers it) |
| `validresponse` (letters, `" "`, scan codes such as 57 = space), `correctresponse`, `timeout`, `trialduration`, `beginresponsetime`, `responseinterrupt` | keyboard: keys, correct, duration (from the last stimulus onset, as in Inquisit), end of screen |
| `validresponse` naming stimuli or mouse buttons | a mouse with those stimuli clickable |
| `pretrialpause` / `posttrialpause` | blank screens before/after the trial |
| `correctmessage` / `errormessage = true(element, ms)` | a feedback screen shown only after a correct/wrong response |
| `branch = [if (trial.x.correct) trial.y]` (and `.error`) | the trial `y`, shown only when the condition holds |
| `ontrialbegin` / `ontrialend` / `onblockbegin` assignments such as `values.n = values.n + 1`, `values.n += 1`, `if (trial.x.correct) values.n = …` | variable items |
| `<block>` `trials = [1 = a; 2-13 = noreplace(b, c); …]`, `sequence(…)`, `replace(…)` | screens and trial lists (random or in order, with repeats) |
| `<expt>` `blocks = […]`, `preinstructions` / `postinstructions` | the flow; a block list with `noreplace(…)` becomes a trial list over blocks |
| `<page>` with `<instruct>` `nextkey` | text screens that wait for that key (or the space bar) |
| `<survey>` / `<surveypage>` with `<textbox>` (number masks, `range`), `<radiobuttons>`, `<dropdown>`, `<checkboxes>`, `<slider>`, `<caption>` | a survey item with number / text / single / dropdown / multiple / slider questions |

**Not converted** (each listed in the report): `<list>` and `<counter>` selection (use a trial list
column instead), elements with several `items` chosen by `select` (become a random choice on each
trial), expressions that use Inquisit properties (`list.x.nextvalue`, `script.…`, `block.x.percentcorrect`),
`<include>`, `<video>`, `<likert>`, `<openended>`, `<html>`, `onexptbegin`/`onexptend`, `skip`/`stop`
conditions and several `<expt>` elements (only the first is used). `<data>` settings are not needed:
EDGE saves every response, RT, correctness and trial-list column.

## Presentation (.sce, .pcl)

Import the scenario (`.sce`). Its PCL program (`pcl_file = "…"`), TEMPLATE files, pictures and
sounds must be next to it; importing the `.pcl` file imports the scenario that names it.

| Converted | EDGE |
|---|---|
| header: `default_background_color`, `default_font_size`, `default_text_color`, `active_buttons`, `screen_width/height` | window and text settings, number of response keys |
| `text`, `bitmap`, `wavefile`/`sound`, `box`, `picture` (named or inline, with `x`/`y` in pixels from the centre) | text, image, sound, shape items |
| `trial` with `trial_duration` (ms, `forever`, `stimuli_length`), `trial_type = first_response` | screen duration, a keyboard that ends the screen |
| `stimulus_event` `time`, `duration` (ms, `response`, `next_picture`), `target_button`, `code`, `port_code` | item start/duration, correct answer, markers (with their port code) |
| `TEMPLATE "file.tem" { columns; rows }` and `LOOP $i N; … ENDLOOP;` | a trial list whose columns fill the template's `$variables`, repeats |
| PCL arrays (`array<string> words[3] = {…}`, 2-D arrays, `rgb_color(…)`), `.shuffle()` | trial-list columns, random order |
| PCL `loop int i = 1 until i > n begin … end;` over the trials (also through an index array such as `order[i]`) | a trial list (repeated rows become `repeats`) |
| `set_caption`, `set_font_color`, `set_filename`, `set_target_button`, `set_port_code`, `set_event_code`, `set_duration` (also `random(a, b)`) inside the loop | item properties taken from the columns |
| `trial.present()`, `if last.type() == stimulus_hit then … else … end;` (also `response_manager.last_response() == n`) | the screens in the loop, shown only after a correct/wrong response |

**Not converted** (listed in the report with their PCL line numbers): other PCL statements, such
as score counters, subroutines, `while` loops, adaptive procedures, and anything that reads
responses in another way. Writing an `output_file` and log codes are not needed: EDGE saves every
response. **Response buttons**: Presentation maps buttons to keys in its Settings, which are not part
of the scenario. Button 1 becomes the key `1`, button 2 the key `2` and so on. Change the keys of
the `resp` items to the keys you used. Without a PCL program, the trials run in the order they are
written in the scenario, as in Presentation.

## Gorilla (task structure .json, spreadsheet .csv / .xlsx)

From Gorilla, download the task's **spreadsheet** (CSV, or XLSX, which needs `pip install openpyxl`)
and, when you have it, the **task structure** as JSON, and import them together (with the stimuli,
either next to them or in a `stimuli/` folder). Gorilla names stimuli without folders; EDGE finds
them in either place. Task Builder 1 and Task Builder 2 zone names are both understood, as are
spreadsheet bindings written `$${Column}`, `${spreadsheet:Column}` or `{"spreadsheet": "Column"}`.

| Converted | EDGE |
|---|---|
| displays and their screens | one screen per Gorilla screen (named `display_Screen`) |
| Text / Rich Text zones (simple HTML styling), Image, Audio, Fixation | text, image, sound, fixation items |
| Keyboard Response (keys, correct answer from a column) | keyboard (ends the screen) |
| Continue Button, Button Response (several buttons) | clickable buttons (a mouse item) |
| Time Limit (Screen), Time Limit (Response), also from a column (`${spreadsheet:ITI}`) | screen duration, response time limit |
| Feedback zone | a text showing the two messages after a correct/wrong response (please check) |
| spreadsheet rows, in order, with the `display` column | trial lists; rows showing different displays in one randomised group choose their screens by the `display` column |
| `randomise_trials` (rows with the same number are shuffled together) | trial lists in random order |
| `randomise_blocks` (blocks shuffled as a whole) | a trial list over the blocks (`randomise_blocks` column) in random order |
| your own columns | kept in every trial list, so they are saved with each trial |

**Not converted**: other zones (video, sliders, rating scales, questionnaires, scripts, …) are listed
in the report; Experiment Builder nodes other than the task (consent, questionnaires, branching,
counterbalancing between participants), `ShowProgressBar`, and several spreadsheets (the first is
used: import again with another). Without the task structure, one screen per display is built from
the spreadsheet columns (pictures, sounds, a text column, the answer column as the correct key): a
rough start, marked as approximate in the report.

## Psychtoolbox (.m)

A Psychtoolbox experiment is a MATLAB **program**, not a description of screens, so the translation
is **partial**: EDGE recognises the common patterns and lists every other line in the report with
its line number. Always compare the result with the original. Files the script reads (conditions
tables, pictures, sounds) must be next to it.

| Converted | EDGE |
|---|---|
| `Screen('OpenWindow')` / `PsychImaging('OpenWindow', …, colour)`, `Screen('TextSize')`, `WhiteIndex`/`BlackIndex` | window background, text size, colours (0–1 or 0–255) |
| drawing (`DrawFormattedText`, `Screen('DrawText')`, `Screen('DrawTexture')` of `imread` + `MakeTexture`, `Screen('DrawLines')` as a fixation cross) followed by `Screen('Flip')` | one screen with those items |
| `WaitSecs(…)` after a flip (also from a table column, e.g. `WaitSecs(T.fixdur(row) / 1000)`) | the screen's duration |
| `KbStrokeWait` / `KbWait` / `GetClicks` | wait for any key / a click |
| `while` loop with `KbCheck` and `keyCode(KbName(…))` tests, `GetSecs - start < limit` | keyboard with those keys and the time limit |
| `KbQueueCreate` / `KbQueueStart` … `KbQueueCheck` | keyboard with the queue's keys, for the screen's duration |
| `audioread` + `PsychPortAudio('FillBuffer'/'Start')`, also inside `if ~correct` | sound item (shown only after a wrong response) |
| `for t = 1:n` over a condition matrix (`[1 1; 1 2; …]`, `repmat`, `Shuffle`/`randperm`) | trial list (columns named after the variables they are read into; repeats; random when shuffled) |
| values looked up in cell arrays and colour matrices (`words{wordNum}`, `colors(colorNum, :)`) | extra columns (`theWord`, `theColor` as #rrggbb) |
| `readtable('conditions.csv')` with `T.column(row)` / `T.column{row}`, `csvread`/`readmatrix` | trial list with the table's rows |
| `correct = response == colorNum` (with `response = 1/2/3` set per key), `strcmp(KbName(key), T.correct_key{row})` | the correct key (a `correct_key` column) |
| the results matrix, `save`, `writetable`, `fprintf`, `input('Participant…')`, set-up and clean-up lines | not needed: EDGE does this itself |

**Not translated** (listed with line numbers): your own functions, staircases and other adaptive
code, `while` loops that are not response loops, drawing with explicit rectangles and positions
(pictures are centred at their own size; `DrawFormattedText` positions become the centre), screen
colours that change per trial (`FillRect`), frame-exact flip timing other than `(n - 0.5) * ifi`
(converted at 60 Hz), and anything that calls other toolboxes.
