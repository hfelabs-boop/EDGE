# Cookbook

Short recipes for common design problems. Each snippet is YAML you can paste into the **Source**
tab (or adapt in the builder). Every recipe here is runnable.

## Timing

### Jittered inter-stimulus interval

```yaml
- {id: fix, type: fixation, duration: "$random.uniform(0.4, 0.8)"}
```

The duration is drawn once each time the component starts. For a fixed set of jitters,
balanced across conditions, put them in the trial list (`isi` column) and write `duration: $isi`.

### Response deadline with a "too slow" message

```yaml
trial:
  components:
    - {id: stim, type: text, text: $word}
    - {id: resp, type: keyboard, keys: [f, j], correct: $answer, duration: 1.5, end_routine: true}
feedback:
  duration: 0.8
  components:
    - id: fb
      type: text
      text: "$'Too slow' if resp.keys is None else ('Correct' if resp.corr else 'Wrong')"
```

### Show a stimulus for exactly N frames

```yaml
- {id: mask, type: image, image: mask.png, start_frame: 3, duration_frames: 2}
```

Frame-based timing is exact. Durations in seconds are also rounded to whole frames, because start and
stop are decided for each screen refresh.

### Present something right after another component ends

```yaml
- {id: tone, type: sound, sound: 1000, start_after: stim}      # starts when 'stim' stops
```

## Trial lists and randomization

### Trial list from a spreadsheet

```yaml
- loop: trials
  conditions: stimuli.xlsx      # .csv, .tsv, .xlsx, .json; each column becomes $column
  order: random
  repeats: 2
  children: [trial]
```

### No more than two identical trials in a row

```yaml
  max_repeat: {ink: 2}                    # per column: never 3 trials with the same ink in a row
```

Per value (deviants never back to back), and both rules at once (one `max_repeat:` per loop; a
second one would be an error):

```yaml
  max_repeat: {kind: {deviant: 1}}
  # or both:  max_repeat: {ink: 2, kind: {deviant: 1}}
```

### Full factorial design without typing rows

```yaml
  conditions: {factorial: {set_size: [4, 8], target: [present, absent]}, extra: {block: 1}}
```

### Counterbalance block order across participants

```yaml
- loop: blocks
  conditions: [{block_file: easy.csv}, {block_file: hard.csv}]
  order: latin_square            # the order depends on the participant number
  children:
    - loop: trials
      conditions: $block_file    # each block loads its own trial list
      order: random
      children: [trial]
```

### Different conditions for different groups

```yaml
flow:
  - if: "$group == 'A'"
    then: [block_A]
    else: [block_B]
```

Add `group` to `settings.participant` and pass it with `edge run study.yaml -f group=A`. To derive it
from the participant number, use `if: "$int(participant) % 2 == 0"`.

### Randomize a position once per trial

Dynamic properties are re-evaluated every frame, so `pos: "$[random.choice([-300, 300]), 0]"` would
flicker. Draw the value once with a variable component listed **before** the stimulus:

```yaml
- {id: pick, type: variable, set: {side: "$random.choice([-1, 1])"}}
- {id: target, type: shape, pos: "$[side * 300, 0]"}
```

## Flow and logic

### A break every 40 trials

```yaml
- loop: trials
  conditions: trials.csv
  children:
    - {routine: rest_break, if: "$trials.n > 0 and trials.n % 40 == 0"}
    - trial
```

### Practice until 80% correct (at most three times)

```yaml
- statemachine: session
  start: practice
  states:
    practice:
      run: [practice_loop]
      max_visits: 3
      next:
        - {if: "$practice_loop.accuracy >= 0.8", goto: main}
        - {goto: practice}
    main:
      run: [main_loop]
```

Every loop tracks `accuracy`, `n_correct`, `n_responses` and `mean_rt` while it runs.

### Stop a block early when performance is perfect

```yaml
- loop: block
  conditions: trials.csv
  stop_if: "$block.n_correct >= 10"
  children: [trial]
```

### Feedback only in practice

```yaml
- {id: fb, type: text, text: "$'Correct' if resp.corr else 'Wrong'", if: "$is_practice"}
```

### Show a hint when the participant is slow

```yaml
trial:
  rules:
    - {when: "$t > 3 and resp.keys is None", do: [{start: hint}]}
  components:
    - {id: hint, type: text, text: "Press F or J", pos: [0, -200], start_if: "$False"}
    - {id: resp, type: keyboard, keys: [f, j], end_routine: true}
```

### A running score

```yaml
variables: {score: 0}
routines:
  trial:
    components:
      - {id: resp, type: keyboard, keys: [f, j], correct: $answer, end_routine: true}
      - {id: add, type: variable, when: end, set: {score: "$score + (resp.corr or 0)"}}
  feedback:
    duration: 1
    components:
      - {id: s, type: text, text: "$f'Score: {score}'"}
```

### Screen out participants without consent

```yaml
- statemachine: session
  start: consent
  states:
    consent:
      run: [consent_page]                 # html component with a checkbox named "agree"
      next: [{if: "$consent.agree == 'yes'", goto: task}, {goto: end}]
    task:
      run: [main_loop]
```

## Responses

### Click on one of several images

```yaml
- {id: left, type: image, image: $left_img, pos: [-300, 0]}
- {id: right, type: image, image: $right_img, pos: [300, 0]}
- {id: click, type: mouse, clickable: [left, right], correct: $target, end_routine: true}
```

### Rating scale

```yaml
- {id: rating, type: slider, ticks: [1, 2, 3, 4, 5, 6, 7], labels: [not at all, very much], end_routine: true}
```

### A validated questionnaire after the task

```yaml
- {id: post, type: survey, end_routine: true, questions: [{instrument: nasa_tlx}, {instrument: sus}]}
```

Scores arrive as columns (`post.tlx_raw`, `post.sus_score`). The [questionnaire reference](reference/questionnaires.md)
lists all 20 instruments.

### Rate every stimulus with a short survey

```yaml
- id: rate
  type: survey
  end_routine: true
  questions:
    - {id: valence, type: scale, points: 9, labels: [Very unpleasant, Very pleasant], required: true,
       text: "How did the picture make you feel?"}
    - {id: familiar, type: single, layout: horizontal, options: [Yes, No], text: "Had you seen it before?"}
```

Put the screen inside the trial loop: one row per stimulus, with `rate.valence` next to the trial's columns.

### Questionnaire as an HTML page

```yaml
- {id: bfi, type: html, file: pages/bfi.html, end_routine: true}
```

Every named form field becomes a column (`bfi.q1`, `bfi.q2` …). Write `{{word}}` in the page to show a
trial variable.

## Eye tracking

### Fixation check before each trial

```yaml
fixcheck:
  duration: 5          # give up after 5 s
  components:
    - {id: dot, type: shape, shape: circle, radius: 8, fill: white}
    - {id: roi, type: gaze_roi, radius: 60, dwell: 0.3, end_routine: true}
```

### Dwell time on areas of interest

```yaml
- {id: left_img, type: image, image: $left, pos: [-300, 0], size: [400, 300]}
- {id: aoi_left, type: gaze_roi, target: left_img}     # entered, first_entry, dwell_time, entries
```

### A gaze-contingent moving window

```yaml
- {id: window, type: shape, shape: circle, radius: 120, fill: "#ffffff30"}
- {id: follow, type: gaze_follow, target: window, smoothing: 0.3}
```

Build it at your desk with the `mouse_gaze` device (the mouse acts as the gaze), then swap in
`tobii` or `gazepoint`.

## EEG, physiology and markers

### Fixed trigger codes for an EEG amplifier

```yaml
settings:
  markers: {codes: {standard: 1, deviant: 2, response: 10}}
devices:
  - {id: ttl, type: ttl_serial, options: {port: COM3, protocol: byte, pulse_ms: 10}}
routines:
  tone:
    components:
      - {id: beep, type: sound, sound: $freq, marker: $kind}                 # 1 or 2 at onset
      - {id: resp, type: keyboard, keys: [space], response_marker: response}  # 10 at the key press
```

Keep one marker per onset: on a TTL line, two codes at the same moment overwrite each other (the
validator warns you).

### Record everything with LabRecorder

```yaml
devices:
  - {id: lsl, type: lsl_markers, options: {wait_for_consumers: 30}}
  - {id: eeg, type: lsl_inlet, options: {stream_type: EEG}}
```

`wait_for_consumers` holds the start until LabRecorder is recording, so no marker is lost.

### Align a MindWare / BIOPAC recording afterwards

Export the event times from the recording software as `time,code`, then:

```bash
edge align data/001_1_study_2027-02-01_101500 biolab_events.csv   # the session folder 'edge run' printed
```

## Video and vision science

### Play a video and end the screen when it ends

```yaml
- {id: clip, type: movie, movie: videos/intro.mp4, end_routine: true, marker: video_on}
```

The data have `clip.first_frame` (when the first frame appeared) and `clip.frames_dropped`. A different video on
each trial: `movie: $video` with a `video` column in the trial list. Encode videos as MP4 (H.264, `-bf 0`) at 30 or
60 fps for a 60 Hz screen. See [Video](EXPERIMENT_FORMAT.md#video).

### Contrast detection with a Gabor

```yaml
settings:
  window: {units: deg, background: "#808080", monitor: {width_cm: 52, distance_cm: 57}, gamma: calibration/lab1.json}
routines:
  trial:
    components:
      - {id: fix, type: fixation, size: 0.5, duration: 0.5}
      - {id: target, type: gabor, sigma: 0.4, sf: 4, ori: $ori, contrast: $contrast, start: 0.5, duration: 0.1}
      - {id: resp, type: keyboard, keys: [left, right], correct: $answer, start: 0.5, end_routine: true}
```

Use a staircase on `contrast` for thresholds. Measure the monitor first (`edge gamma experiment.yaml --show`), or
the contrast steps are not linear.

### Motion coherence (random-dot kinematogram)

```yaml
- {id: rdk, type: dots, n_dots: 150, coherence: $coh, direction: $dir, speed: 6, dot_size: 0.12,
   lifetime: 12, size: [8, 8], units: deg, duration: 1.0}
- {id: resp, type: keyboard, keys: [left, right], correct: "$'left' if dir == 180 else 'right'", end_routine: true}
```

With `settings.seed` fixed, every participant sees exactly the same dots; the seed of each trial is in `rdk.seed`.

### A drifting grating followed by a dynamic-noise mask

```yaml
- {id: grating, type: grating, sf: 2, tf: 4, mask: raisedcos, size: [6, 6], units: deg, duration: 0.5}
- {id: mask, type: noise, noise_type: binary, dynamic: true, element_size: 0.2, size: [6, 6], units: deg,
   start_after: grating, duration: 0.2}
```

## Running

### A screenless study (sounds or physiology only)

```bash
edge run study.yaml --backend headless-realtime
```

### Fix the randomization for a pilot

```yaml
settings: {seed: 1234}
```

The seed is saved in `session.json` either way, so any order can be reproduced later.
