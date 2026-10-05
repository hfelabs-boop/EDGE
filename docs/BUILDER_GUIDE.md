# Builder guide

Double-click the **EDGE** icon, or run `edge` (your experiments folder) or `edge builder [folder]`.
The builder opens in your browser and reads and writes experiment files in that folder. Nothing
leaves your computer.

![The builder](builder.png)

## Simple and Expert mode

The **Simple / Expert** button (top right) decides how much you see. Your choice is remembered.

| | Simple (default) | Expert |
|---|---|---|
| Things you can add | Show (text, picture, shape, fixation cross, sound, web page), Responses (key press, mouse click, rating scale), Pause, Set a variable; *Where they look* once an eye tracker is added | everything, including Python code, event markers, gaze following and calibration |
| Properties | the essentials; the rest under **More options** (with a count of options already set) | every property |
| Top bar | New, Open, Save, Settings, Check, Test run, Try it, Run with a participant | also Import, Versions, Bundle |
| Console | Check, Test results, Data | also Source (YAML), Hardware |
| Check messages | must-fix problems and things to check | also notes (info) |

Searching the list on the left always finds every kind of thing, in either mode.

## Words used in the builder

| builder | means | in the YAML file |
|---|---|---|
| screen | one step: a trial, instructions, feedback | `routines:` |
| thing on a screen | text, picture, key press … | `components:` |
| trial list | repeats screens once per row | `loop:` with `conditions:` |
| workflow | states with routes (practice until …, screening) | `statemachine:` |
| Check | finds mistakes | `edge validate` |
| Test run | a virtual participant does the whole experiment in seconds | `edge run --dry-run` |
| Try it | you do the experiment inside the builder | (builder only) |
| Run with a participant | the real session in the experiment window | `edge run -p 001` |

## Layout

| area | what it's for |
|---|---|
| **Top bar** | New, Open, Save, Undo/Redo, Settings, Check, ▶ Test run, ▶ Try it, Run with a participant, Simple/Expert, Help (?) |
| **Left** | what you can **add to this screen** (click, or drag onto the timeline) and the **devices** list |
| **Centre top** | the **storyboard**, or one screen's **timeline** with its plain-language summary and live preview. When a workflow is selected, a **diagram** replaces it. |
| **Centre middle** | the **flow**: the order of screens, trial lists, if/else and workflows |
| **Centre bottom** | the **console**: Check, Test results, Data (Expert: Source, Hardware) |
| **Right** | **properties** of whatever is selected |

## Starting a new experiment

**New** opens the welcome screen:

* **✨ Make a new experiment: answer a few questions** is the design wizard. Six pages ask what
  participants see (and the list of stimuli, which you can paste from a spreadsheet), how they respond,
  the timing, practice (none, once, or until a criterion via a workflow) and feedback, blocks and texts,
  and optional devices. A live line shows how many trials and minutes your answers make. **Create
  experiment** saves it in its own folder, opens it and runs a test run straight away.
* **Examples** (templates), **tutorials**, your **recent** files and **import** from PsychoPy,
  E-Prime, OpenSesame or jsPsych.

## The storyboard

The **▦ Storyboard** tab shows the whole experiment as pictures, in the order participants see them.
Each card is one screen drawn at the moment its main stimulus is up, with a line saying how it ends
("waits for f / j (max 2s)", "0.8s"). Trial lists are green boxes ("⟳ trials: 6 rows × 3, random
order"), workflows purple boxes with their states, if/else dashed boxes. The header estimates the
whole session: *"about 120 trials, about 9 minutes"*.

Click a card to open that screen; **← Storyboard** goes back. Simple mode opens experiments on the
storyboard; Expert mode opens the first screen.

## Screens and the timeline

* **+ screen** creates a screen; double-click a tab to rename it.
* Click something on the left to add it to the open screen (or drag it onto the timeline). A new
  stimulus gets a 1 s placeholder duration until you add a response that ends the screen; then it
  stays up until the response.
* Each thing is a bar: **drag** it to change when it starts, drag its **right edge** to change how
  long it lasts. Faded bars run until the screen ends; striped bars start on a condition.
* The grey **summary** above the timeline says in plain words what the screen does, for example:
  *"fix shows a fixation cross from the start, for 0.5 s. resp waits for f/j (correct: $answer) at
  0.5 s, for 2 s; this ends the screen."* Read it to check your logic.
* The **preview** draws the screen at the time chosen with the slider, using the first row of the
  trial list. **▶** plays it at real speed. HTML pages are previewed live.
* Things listed later are drawn on top. Use ↑/↓ in Properties to change the order.

### Arranging the screen on the preview

The preview is also an editor. **⤢** makes it bigger.

| do this | to |
|---|---|
| click a text, picture or shape | select it (Properties shows it) |
| drag it | move it; it snaps to the centre of the screen and to the centres of other things (hold **Alt** to stop snapping, **Shift** to move in a straight line) |
| drag a corner square | resize: letter height for text, width × height for pictures and rectangles, the radius for circles. Pictures keep their proportions (hold **Shift** to stretch); shapes stretch freely (hold **Shift** to keep proportions) |
| drag the round handle above it | rotate (hold **Shift** for 15° steps) |
| double-click text | type the text right on the screen (**Enter** to finish, **Shift+Enter** for a new line, **Esc** to cancel) |
| double-click a picture | choose another picture |
| arrow keys (after clicking the preview) | nudge by one pixel; **Shift** for ten |
| drag an item from the left onto the preview | add it exactly there |
| drop picture, sound or .html files from your computer onto the preview | copy them into the experiment folder and add them where you dropped them |

Every change can be undone. If a position or size comes from the trial list, the preview says so
instead of moving it: change it in the trial list, or set the property back to **Fixed**.

### Pictures, sounds and pages

Adding a **Picture** or **Sound** opens a chooser straight away. It shows what is already in the
experiment's folder (thumbnails for pictures, ▶ to listen to sounds), with a search box.
**⬆ Upload from computer**, or dropping files on the chooser, copies them into `images/`, `sounds/`
or `pages/` next to the experiment (save the experiment first; EDGE asks if needed). For sounds you
can also pick a beep: low, middle, high, very high or any frequency. In Properties the file shows as
a card with a thumbnail or ▶; **Change…** reopens the chooser, and you can drop a file on the card.

## Properties and where values come from

Every property has help text, and **📖 docs** opens its reference. Next to most properties a small
menu says where the value comes from:

| choice | what it does |
|---|---|
| **Fixed** | the same value on every trial |
| **⟳ column** (e.g. ⟳ word) | each trial uses that column of the trial list around this screen; the box shows an example value and clicking it opens the trial list |
| **+ New trial-list column…** | asks for a name and adds the column to the trial list around this screen, filled with the current value. If the screen has no trial list yet, EDGE wraps it in a new one with two rows. |
| **Formula ($…)** | an expression, computed while the experiment runs. Type `$` to see what's available here: columns, results of other things (`$resp.corr`), trial-list statistics (`$practice.accuracy`), workflow state, variables. |

Typing a value that starts with `$` also makes it a formula.

Fixed values have editors that fit them:

* **colours**: a row of swatches, a colour picker for any other colour, or type a name or `#hex`;
  fills and outlines have a "none" swatch.
* **numbers with a range** (opacity, rotation, letter height, line thickness, volume …): a slider
  that updates the preview as you drag, next to a box for exact values.
* **position** and **size**: X/Y or W/H boxes. Drag the letter (X, Y, W, H) sideways to change the
  value (Shift for bigger steps). The small 3×3 grid puts the item in a standard place (centre,
  top left, bottom right …). A picture's size keeps its proportions while 🔒 is on, and has
  **Original size**, ½×, ¾×, 1½× and 2× buttons.
* **shape** and other short choices: buttons with icons (▭ ◯ ⬭ ⬠ ╱ ✚).
* **font**: a menu of common fonts, each shown in its own typeface, and **Other…** for any font.

The **When** section has *starts at*, *lasts*, and *ends the screen* (move on when this gets a
response). Under **More options**: *starts after* another thing, *starts when* / *stops when* a
condition, frame-based timing, and **only if** (include it only when a condition is true).

## The flow

* The round **+** buttons insert a screen, a new screen, a **trial list** (loop), an **if / else**
  (branch), or a **workflow** (state machine) at that position.
* **Drag** any screen, trial list or workflow onto another + to move it, including into or out of
  trial lists and workflow states.
* Right-click an item to move it, repeat it (wrap in a loop), run it only if a condition holds, or
  remove it.

### Trial lists (loops)

Select a trial list's green header. Choose where it comes from (**table** typed right there, a
**file** (CSV/TSV/XLSX, with preview), a **factorial** design, or an adaptive **staircase**), then
the **order** and how many times to **repeat** it. The panel shows the count ("6 rows × 3 = 18 runs").
Under More options: *no more than N in a row*, *use only rows*, *stop early when*.

### Workflows (state machines)

Select the purple header to see the **diagram**. Click a state (in the diagram or the flow) to edit
its **routes**: conditions checked top to bottom (*if … go to …, else if …, otherwise …*), optional
variable assignments, and **max_visits**. Put screens and trial lists into a state with its **+**
buttons or by dragging.

### Rules

In a screen's properties (Simple mode: under *Rules: react while the screen runs*), **Rules
(when → do)** react while the screen runs: *when* a condition becomes true, *do* actions (end the
screen, start/stop something, set a variable, send a marker, go to a workflow state).

## Measures & data

**Measures & data** (top bar) answers two questions: *what does this experiment measure?* and
*what exactly is recorded?*

* **What this experiment measures**: one card per measure: a name, its role (outcome, factor,
  covariate, check, info), the column it comes from, how it is summarised, which trials count
  (*use trials of …*, *only when …*, e.g. correct trials only) and the range you expect. Each card
  repeats it in plain words and shows problems right there. Experiments without measures get
  suggestions (**Add all** takes them); the design wizard declares them for you.
* **Everything that is recorded**: participant fields, trial-list columns, every screen's
  components with the columns they record (meaning, units, kind), variables, and each device's
  streams (channels, sample rate, file) or what it sends elsewhere (TTL codes, LSL markers). Untick
  a component or device to stop saving it; **☆** turns any column into a measure (a trial-list
  column becomes a factor, `resp.rt` a reaction time on correct trials, `resp.corr` an accuracy).

### Live session monitor

**Run with a participant** first lists the measures and what will be recorded. While the session
runs, the window shows:

* progress: trial *n* of about *N*, time elapsed and left;
* each measure: its value so far (median RT, % correct, mean rating …), how many trials it is
  based on and how many are missing, and a small chart of every trial (the expected range shaded,
  values outside it and missing ones marked);
* the last response: what was pressed, how fast, correct or not, in which condition;
* every device stream: samples per second against its nominal rate, green / amber (too slow) /
  red (no data);
* warnings: *no response on the last 5 trials*, a measure missing on more than 20% of trials,
  values outside the expected range, a device that went silent;
* **■ Stop session** ends it like Esc in the experiment window: everything so far is saved.

**Hide** closes the window; the session keeps running.

## Surveys and questionnaires

**Survey / questionnaire** (under *Show*) adds a questionnaire page; if the screen already has something
on it, the survey gets its own screen after it. **✎ Edit questions** opens the survey editor: questions on
the left (drag to reorder, duplicate, delete, page breaks), the selected question in the middle (text,
data name, options or a standard scale, required, shuffle, "other, please specify", limits, validation,
display logic), and the real participant page live on the right. **+ From library** adds validated
questionnaires with their citation, licence and scoring; **Customize** copies a library questionnaire's
items in for editing. See [Surveys](SURVEYS.md).

## Checking, testing and trying

* **Check** runs automatically while you edit; the tab shows a ✓ or the number of problems. Messages
  are in plain words and say where: *"The trial list has no column called 'ink'. Did you mean 'colour'?
  · columns here: colour, key, word · screen “trial” › word › color"*. Click one to jump there.
  It also catches a screen that uses a column outside its trial list, and a thing named like a column.
* **▶ Test run**: a virtual participant does the whole experiment in seconds, with every device
  simulated. The **Test results** tab shows the session length, the number of trials, accuracy, the
  verdict, synchronization per device, and the data.
* **▶ Try it**: you do it. Choose the whole experiment or (when a screen is open) just that screen for
  five trials with real values from its trial list. The experiment runs with the real engine and fills
  the window; press keys and click as a participant would, **Esc** stops. Web pages (consent forms,
  questionnaires) appear in place. At the end you see your trials, accuracy and mean response time;
  the data is saved with the test runs (*include test runs* in the Data tab). Times measured in a
  browser are approximate, so use Run with a participant for real data.

## Run with a participant

**Run with a participant** saves the experiment if needed, refuses to start while Check shows
must-fix problems, and asks:

* **Participant ID**: the next free number is suggested; reusing an ID is allowed (a new session
  folder is made) but you're warned.
* **Session**.
* **Hardware**: real devices, or simulated (when no hardware is connected).
* **Screen**: full screen or in a window.

The experiment window opens on this computer. The dialog follows the session; afterwards **See the
data** opens it in the Data tab and **Next participant** starts over. If the window can't open (no
monitor, missing library) or a device can't be reached, the dialog says so in plain words.

## Devices

**+** next to *Devices* adds an eye tracker, EEG, physiology recorder, LSL stream or TTL output.
**Scan for hardware** (Expert) finds connected LSL streams, serial ports, Tobii trackers and
Gazepoint, each with a one-click *add*. Simulated devices (`sim_eyetracker`, `sim_eeg`, `sim_physio`,
`mouse_gaze`) let you build without hardware. Test runs and Try it simulate every device automatically.

## The console

| tab | shows |
|---|---|
| **Check** | problems while you edit, in plain words; click one to jump to it |
| **Test results** | session length, trials, accuracy, verdict, per-device synchronization, data preview |
| **Data** | recorded sessions: trial table, summary, data dictionary, and exports (CSV, Excel, BIDS …) |
| **Source (YAML)** (Expert) | the experiment file. Edit it and click *Apply YAML*. |
| **Hardware** (Expert) | results of *Scan for hardware* |

## Saving, versions and sharing

* **Save** (Ctrl/⌘+S) writes the file safely. The previous version is always kept: **Versions**
  (Expert) lists them and restores any of them; `edge backups` does the same in a terminal.
* If the file is changed elsewhere (another window, a text editor, Claude via MCP), the builder
  reloads it automatically when you have no unsaved changes. Otherwise it asks which version to keep.
* Unsaved changes survive a browser crash: you're offered a restore next time.
* **Bundle** (Expert) downloads a `.edgez` file with the experiment and every file it uses, ready to
  send to a colleague (`edge unbundle file.edgez`).

## Help and tutorials

* **?** opens the Help Center: all guides, search, and the interactive tutorials.
* Tutorials run *in* the builder: the coach highlights what to use and advances when you've done the
  step. Each tutorial switches to the mode it was written for. Completed tutorials are ticked ✓.

## Keyboard shortcuts

| keys | action |
|---|---|
| Ctrl/⌘ S | save |
| Ctrl/⌘ Z, Ctrl/⌘ Shift Z | undo, redo |
| Delete / Backspace | remove the selected thing |
| arrow keys, Shift + arrow keys | nudge the selected thing on the preview by 1 or 10 pixels |
| ? | help |
| Esc | close dialogs; stop Try it |
