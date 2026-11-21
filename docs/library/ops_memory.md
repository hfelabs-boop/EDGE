# Task library: operational adaptations of the memory and vigilance tasks

Fourteen working-memory and vigilance tasks of the library have an **operational adaptation** for human-factors
research with operators (see [Operational adaptations](DEFENSE.md) for what these are, the display themes and the
symbol conventions). Each one keeps the classic task's design, trial lists, timing, responses and measures, so its
results can be compared with the classic task and across themes; only the stimuli, the wording and the screen
around them change. Everything shown is generic and fictional.

Choose the display with the variable `theme` (the first entry of `variables:`; the default theme is listed first
below), in the builder when you click **Use this task**, or with `edge library new <id> --theme <theme>`.

| adaptation (id) | classic task | themes | what the participant sees and does |
|---|---|---|---|
| `nback2_ops` | `nback2` | c2, ew, uav | 2-back on reported items: track numbers on a tactical plot (c2), emitter type codes on a spectrum display (ew), or the grid sector a camera looks at (uav); SPACE for a 2-back repeat |
| `nback2_phone_ops` | `nback2_phone` | c2, ew, uav | the same on a phone held upright, MATCH / NO MATCH buttons |
| `touch_nback2_ops` | `touch_nback2` | c2, ew, uav | the same on a tablet or touch monitor |
| `digitspan_ops` | `digitspan` | c2, uav | read back a track number coming in on a message panel (c2) or a grid reference passed in a camera overlay (uav), digit by digit, on a console keypad |
| `rdigitspan_ops` | `rdigitspan` | c2, uav | the same, read back in reverse order |
| `corsi_ops` | `corsi` | c2, uav | waypoints of a route light up on a map (c2), or the boxes a sensor visits in a camera picture (uav); tap them back in order |
| `corsi2_ops` | `corsi2` | c2, uav | the same with the adaptive (staircase) length |
| `backward_corsi_ops` | `backward_corsi` | c2, uav | the same, tapped back in reverse order |
| `aospan_ops` | `aospan` | c2, uav | judge a fuel check (c2) or time-on-station check (uav), each the classic (a x b) +/- c problem, while remembering call-sign letters; recall them on the letter grid |
| `retrocue_ops` | `retrocue` | c2, uav, ew | four contacts (track symbols, vehicles, or emitter traces) flash; a cyan target box cues one place (or all four); report whether the contact that comes back is the same or different |
| `mackworth_ops` | `mackworth` | c2, video | a radar sweep that moves one step per second (c2) or a camera feed that shifts along its orbit (video); SPACE when it skips a step |
| `mackworth2_ops` | `mackworth2` | c2, ew | a ring of 60 perimeter sensor posts polled in turn on a map (c2) or 60 receiver channels scanned in turn (ew); SPACE when one is skipped; 8 minutes, alertness rated before and after |
| `pvtb_ops` | `pvtb` | c2, uav, ew | acknowledge every new contact / new target box / new emitter alert with SPACE as fast as possible; a counter in the alert box shows the reaction time |
| `pvtb_touch_ops` | `pvtb_touch` | c2, uav, ew | the same on a phone or touchscreen, tapping anywhere |

Each task's `meta.yaml` (shown by `edge library show <id>`) has an `adaptation` paragraph saying what each stimulus
stands for in each theme. The trial data record the theme in a column ending in `.shown_theme` (and in
`session.json`), so sessions run in different themes can be pooled and compared.

**How the pictures are made.** The pictures are copies of files of EDGE's defence kit, made by the scripts
`tools/library/make_nback2_ops.py`, `make_digitspan_ops.py`, `make_corsi_ops.py`, `make_aospan_ops.py`,
`make_retrocue_ops.py`, `make_mackworth_ops.py` and `make_pvtb_ops.py` (they also copy the classic tasks' trial
lists). `make_mackworth_ops.py` also draws four task-specific pictures with Pillow: the radar scope and its sweep
beam, the ring of sensor posts and the ring of receiver channels. No extra package is needed to run the tasks.

**Notes.**

* The video theme of `mackworth_ops` moves a still camera frame rather than playing a video, so every step is
  exactly one screen refresh and the same on every computer.
* In the builder's screen preview, items whose position, colour or text is worked out during the session (for
  example the digit of the span tasks or the turned sweep) show their starting values; **Try it** and the Test run
  show them as the participant sees them.
* As in the classic tasks, the touch versions work with a mouse too.
