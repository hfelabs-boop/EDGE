# Component reference

Generated from the code by `edge docs build`. Every component also accepts the scheduling properties
(see [Timing properties](#timing-properties)) and `marker`.

## Stimulus

### fixation

Fixation cross.

| property | type | default | description |
|---|---|---|---|
| `shape` | choice: cross / circle | `cross` | cross or a dot (circle) |
| `size` | float | `40` | cross width and height |
| `radius` | float | `6` | dot radius (shape: circle) |
| `vertices` | list |  | polygon vertices [[x,y],...] |
| `start` | vec2 | `[-50, 0]` | line start point [x, y] (shape: line) |
| `end` | vec2 | `[50, 0]` | line end point [x, y] (shape: line) |
| `fill` | color | `white` | fill colour; 'transparent' for outlines only |
| `line_color` | color |  | outline colour (empty = no outline) |
| `line_width` | float | `4` | thickness of the cross lines |
| `pos` | vec2 | `[0, 0]` | position (window units, origin centre) |
| `opacity` | float | `1.0` | 0 (invisible) to 1 (opaque) |
| `ori` | float | `0.0` | rotation, degrees clockwise |
| `units` | choice: (default) / px / norm / height / deg |  | empty = experiment default |

### html

An HTML page: consent, questionnaires, demographics, rich instructions or a custom JS task. Form fields become data columns; {{variable}} placeholders show trial values.

| property | type | default | description |
|---|---|---|---|
| `file` | file |  | path to an .html file (relative to the experiment) |
| `html` | text |  | inline HTML (used when no file is given) |
| `display` | choice: auto / webview / browser | `auto` | auto = pywebview window if installed, otherwise the system browser |
| `fullscreen` | bool | `True` | show the page full screen |
| `continue_button` | choice: auto / yes / no | `auto` | auto: add a Continue button when the page has no form |
| `continue_label` | str | `Continue` | text of the automatic Continue button |

### image

Image file (png, jpg, bmp ...). Size defaults to the image's native size.

| property | type | default | description |
|---|---|---|---|
| `image` | file |  | image file (png, jpg …) relative to the experiment, or $column **(required)** |
| `size` | vec2 |  | width, height; empty = native size |
| `pos` | vec2 | `[0, 0]` | position (window units, origin centre) |
| `opacity` | float | `1.0` | 0 (invisible) to 1 (opaque) |
| `ori` | float | `0.0` | rotation, degrees clockwise |
| `units` | choice: (default) / px / norm / height / deg |  | empty = experiment default |

### shape

Rectangle, circle, ellipse, polygon, line or cross.

| property | type | default | description |
|---|---|---|---|
| `shape` | choice: rect / circle / ellipse / polygon / line / cross | `rect` | rect, circle, ellipse, polygon, line or cross |
| `size` | vec2 | `[100, 100]` | width, height (rect/ellipse) or size (cross) |
| `radius` | float | `50` | circle radius |
| `vertices` | list |  | polygon vertices [[x,y],...] |
| `start` | vec2 | `[-50, 0]` | line start point [x, y] (shape: line) |
| `end` | vec2 | `[50, 0]` | line end point [x, y] (shape: line) |
| `fill` | color | `white` | fill colour; 'transparent' for outlines only |
| `line_color` | color |  | outline colour (empty = no outline) |
| `line_width` | float | `2` | outline / line thickness |
| `pos` | vec2 | `[0, 0]` | position (window units, origin centre) |
| `opacity` | float | `1.0` | 0 (invisible) to 1 (opaque) |
| `ori` | float | `0.0` | rotation, degrees clockwise |
| `units` | choice: (default) / px / norm / height / deg |  | empty = experiment default |

### sound

Play a sound file or a pure tone (number = frequency in Hz).

| property | type | default | description |
|---|---|---|---|
| `sound` | file | `440` | file path or tone frequency in Hz |
| `volume` | float | `1.0` | 0 to 1 |
| `tone_duration` | float | `0.2` | length of a pure tone in seconds (for numeric sounds) |

### survey

A questionnaire page: single and multiple choice, Likert items and matrices, sliders, text, rank order, constant sum and more, plus validated scales (PHQ-9, GAD-7, Big Five, SUS …) with automatic scoring. Every answer and score becomes a data column.

| property | type | default | description |
|---|---|---|---|
| `questions` | survey |  | the questions, in order; {instrument: phq9} adds a library questionnaire **(required)** |
| `title` | str |  | heading on the first page |
| `language` | str |  | page language, e.g. en, de, es, fr, he: translates buttons and messages; he switches to right-to-left |
| `direction` | choice: auto / ltr / rtl | `auto` | auto follows the language, or the first letters of the title and questions |
| `intro` | text |  | instructions under the title (HTML allowed) |
| `progress_bar` | bool | `True` | show progress across pages |
| `allow_back` | bool | `True` | participants may go back to earlier pages |
| `submit_label` | str |  | text of the last button (default: Submit) |
| `next_label` | str |  | text of the Next button |
| `back_label` | str |  | text of the Back button |
| `scores` | dict |  | extra scores: {name: {items: [...], method: sum|mean, reverse: [...], bands: [[max, label]]}} |
| `labels` | dict |  | translate messages, e.g. {required: 'Bitte beantworten Sie diese Frage.'} |
| `css` | text |  | extra CSS for the page |
| `display` | choice: auto / webview / browser | `auto` | auto = pywebview window if installed, otherwise the system browser |
| `fullscreen` | bool | `True` | show the page full screen |

### text

Text: instructions, words, feedback. Supports expressions, e.g. "$f'Score: {score}'".

| property | type | default | description |
|---|---|---|---|
| `text` | text |  | what to show; use $column for trial values or an f-string: $f'Score: {score}' **(required)** |
| `color` | color | `white` | name (red), hex (#ff8800), or $expression |
| `height` | float | `40` | letter height (window units) |
| `font` | str |  | font family; empty = system default |
| `bold` | bool | `False` | bold text |
| `italic` | bool | `False` | italic text |
| `wrap_width` | float |  | maximum line width before wrapping (window units) |
| `direction` | choice: auto / ltr / rtl | `auto` | text direction; auto detects Hebrew (right-to-left) |
| `pos` | vec2 | `[0, 0]` | position (window units, origin centre) |
| `opacity` | float | `1.0` | 0 (invisible) to 1 (opaque) |
| `ori` | float | `0.0` | rotation, degrees clockwise |
| `units` | choice: (default) / px / norm / height / deg |  | empty = experiment default |

## Response

### keyboard

Collect key presses with RT measured from the component's onset flip.

| property | type | default | description |
|---|---|---|---|
| `keys` | list |  | allowed keys, e.g. [f, j]; empty = any |
| `store` | choice: first / last / all | `first` | which key to keep when several are pressed: first, last or all |
| `correct` | str |  | correct key (often an expression: $corr_key) |
| `discard_previous` | bool | `True` | ignore keys pressed before onset |
| `record_release` | bool | `False` | also store key-up times (durations) |
| `response_marker` | str |  | marker sent at the moment of the response, e.g. $f'resp_{resp.keys}' |

### mouse

Mouse clicks, optionally restricted to clickable components (e.g. images/shapes).

| property | type | default | description |
|---|---|---|---|
| `buttons` | list | `['left']` | buttons that count as a response: left, middle, right |
| `clickable` | list |  | ids of components in this routine that can be clicked |
| `correct` | str |  | id of the correct clickable component |
| `track` | bool | `False` | save the full mouse trajectory |
| `response_marker` | str |  | marker sent at the moment of the click |

### slider

Rating scale / visual analogue scale answered with the mouse (or arrow keys + return).

| property | type | default | description |
|---|---|---|---|
| `ticks` | list | `[1, 2, 3, 4, 5, 6, 7]` | tick values; the first and last are the ends of the scale |
| `labels` | list |  | labels spread along the scale |
| `granularity` | float | `1` | 0 = continuous |
| `pos` | vec2 | `[0, -150]` | centre of the scale |
| `size` | vec2 | `[800, 30]` | width and height of the scale |
| `color` | color | `white` | colour of the bar, ticks and labels |
| `marker_color` | color | `#ff9900` | colour of the selected-value marker |
| `units` | str |  | empty = experiment default |
| `require_confirm` | bool | `False` | press return/space to confirm |

## Eyetracking

### calibrate

Run the eye tracker's calibration (Tobii: drawn by EDGE; Gazepoint: native window).

| property | type | default | description |
|---|---|---|---|
| `device` | device |  | gaze device id (default: first gaze device) |

### gaze_follow

Move another visual component to the current gaze position (moving windows, masks, gaze cursors).

| property | type | default | description |
|---|---|---|---|
| `device` | device |  | gaze device id (default: first gaze device) |
| `target` | component |  | id of the visual component to move **(required)** |
| `offset` | vec2 | `[0, 0]` | [x, y] added to the gaze position |
| `smoothing` | float | `0.0` | 0..1 exponential smoothing |

### gaze_roi

Area of interest. Tracks entries, first-entry latency and dwell time; can end the routine after a continuous dwell (gaze-contingent triggers, fixation checks).

| property | type | default | description |
|---|---|---|---|
| `device` | device |  | gaze device id (default: first gaze device) |
| `target` | component |  | use another component's area (e.g. an image) |
| `shape` | choice: circle / rect | `circle` | circle or rect (ignored when target is set) |
| `pos` | vec2 | `[0, 0]` | centre of the area |
| `radius` | float | `100` | radius (shape: circle) |
| `size` | vec2 | `[200, 200]` | width, height (shape: rect) |
| `units` | str |  | empty = experiment default |
| `dwell` | float |  | seconds of continuous dwell that complete the ROI |
| `show` | bool | `False` | draw the ROI outline (debug) |

## Hardware

### marker

Send an event marker at this component's onset (time-locked to the screen flip) to all devices or a chosen subset: TTL codes, LSL markers, Gazepoint USER_DATA, Tobii sample tags.

| property | type | default | description |
|---|---|---|---|
| `label` | str |  | e.g. $f'stim_{condition}' **(required)** |
| `code` | int |  | TTL code 1-255 (auto-assigned from the label if empty) |
| `devices` | list |  | device ids; empty = all marker-capable devices |
| `offset_label` | str |  | optional marker sent when the component stops |

## Logic

### code

Full Python for anything the builder can't express. Snippets run when the routine begins (on_begin), every frame (on_frame) and when it ends (on_end), with access to trial variables, component results, `vars`, `session`, `marker(label)` and `end_routine()`. Assigned names persist as variables.

| property | type | default | description |
|---|---|---|---|
| `on_begin` | code |  | runs while the routine is prepared (before stimuli resolve) |
| `on_frame` | code |  | runs every frame (`t` = predicted flip time) |
| `on_end` | code |  | runs when the routine ends |

### variable

Set experiment variables from expressions, e.g. set: {score: '$score + resp.corr'}.

| property | type | default | description |
|---|---|---|---|
| `set` | dict |  | variables to assign: {name: value or $expression} **(required)** |
| `when` | choice: start / end | `start` | start: before the routine is shown (later components see the new value); end: after it |

### wait

Does nothing; use with a duration to hold the routine (ISI, blank screen).

| property | type | default | description |
|---|---|---|---|

## Timing properties

Available on every component:

| property | description |
|---|---|
| `disabled` | skip this component (bool or expression) |
| `duration` | seconds; empty = until the routine ends |
| `duration_frames` | duration in frames |
| `end_routine` | end the routine when this component responds or times out |
| `if` | include this component only when the expression is true (checked at routine start) |
| `save` | include its results in the data |
| `start` | seconds from the routine's first flip (number or expression) |
| `start_after` | start when another component (by id) stops |
| `start_frame` | start on frame N |
| `start_if` | start when an expression becomes true |
| `stop_if` | stop when an expression becomes true |
| `marker` | label (or `{onset, offset, code}`) sent to every device at the component's onset flip |
