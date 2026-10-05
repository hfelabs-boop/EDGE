# Builder guide

`edge builder [folder]` opens the visual builder in your browser. It reads and writes experiment files
in that folder. Nothing leaves your computer.

![The builder](builder.png)

## Layout

| area | what it's for |
|---|---|
| **Top bar** | New, Open, Import, Save, Versions, Bundle, Undo/Redo, Settings, Validate, Dry run, Run, Help (?) |
| **Left** | the **component palette** (click or drag a component into the routine) and the **devices** list |
| **Centre top** | the **routine editor**: tabs for each routine, the timeline, the plain-language summary and the live stimulus preview. When a workflow is selected, a **diagram** replaces it. |
| **Centre middle** | the **flow**: the order of routines, loops, branches and workflows |
| **Centre bottom** | the **console**: Issues, Dry-run results, Source (YAML), Hardware, Data |
| **Right** | **properties** of whatever is selected |

## Routines and the timeline

* **+ routine** creates a routine; double-click a tab to rename it.
* Click a component in the palette to add it to the open routine (or drag it onto the timeline).
* Each component is a bar: **drag** it to change when it starts, drag its **right edge** to change
  its duration. Faded bars run until the routine ends; striped bars start on a condition.
* The grey **summary** above the timeline says in plain words what the routine does, for example:
  *"fix shows a fixation cross from the start, for 0.5 s. resp waits for f/j (correct: $answer) at
  0.5 s, for 2 s; this ends the routine."* Read it to check your logic.
* The **preview** draws the screen at the time chosen with the slider, using the first row of the
  trial list for `$variables`. HTML pages are previewed live.
* Components listed later are drawn on top. Use ↑/↓ in Properties to change the order.

## Properties and expressions

* Every property has help text, and **📖 docs** opens its reference.
* **fx** switches a field to an *expression*. Type `$` to see the variables available at that spot:
  trial-list columns, results of other components (`$resp.corr`), loop statistics
  (`$practice.accuracy`), workflow state, experiment variables.
* **Timing** properties: `start`, `duration`, `start_after` (another component), `start_if` /
  `stop_if` (conditions), frame-based alternatives, `end_routine`, and **`if`** (include the component
  only when a condition is true).

## The flow

* The round **+** buttons insert a routine, a new routine, a **loop**, a **branch** (if/else), or a
  **workflow** (state machine) at that position.
* **Drag** any routine, loop or workflow onto another + to move it, including into or out of loops
  and workflow states.
* Right-click an item to move it, wrap it in a loop, run it only if a condition holds, or remove it.

### Loops

Select a loop's green header. Choose where the trial list comes from (**table** edited right there,
**file** CSV/TSV/XLSX with preview, **factorial** design, or **staircase**), then the **order**, the
number of **repeats**, and optionally **max_repeat** (limit identical values in a row) and **stop_if**.

### Workflows (state machines)

Select the purple header to see the **diagram**. Click a state (in the diagram or the flow) to edit its
**routes**: conditions checked top to bottom (*if … go to …, else if …, otherwise …*), optional
variable assignments, and **max_visits**. Put routines and loops into a state with its **+** buttons or
by dragging.

### Rules

In a routine's properties, **Rules (when → do)** react while the routine runs: *when* a condition
becomes true, *do* actions (end the routine, start/stop a component, set a variable, send a marker,
go to a workflow state).

## Devices

**+** next to *Devices* adds an eye tracker, EEG, physiology recorder, LSL stream or TTL output.
**Scan for hardware** finds connected LSL streams, serial ports, Tobii trackers and Gazepoint, each
with a one-click *add*. Simulated devices (`sim_eyetracker`, `sim_eeg`, `sim_physio`, `mouse_gaze`) let
you build without hardware. Dry runs simulate every device automatically.

## The console

| tab | shows |
|---|---|
| **Issues** | validation errors and warnings while you edit; click one to jump to the problem |
| **Dry-run results** | session length, verdict, per-device synchronization, data preview |
| **Source (YAML)** | the experiment file. Edit it and click *Apply YAML*. |
| **Hardware** | results of *Scan for hardware* |
| **Data** | recorded sessions: trial table, summary, data dictionary, and exports (CSV, Excel, BIDS …) |

## Saving, versions and sharing

* **Save** (Ctrl/⌘+S) writes the file safely. The previous version is always kept: **Versions** lists
  them and restores any of them.
* If the file is changed elsewhere (another window, a text editor, Claude via MCP), the builder
  reloads it automatically when you have no unsaved changes. Otherwise it asks which version to keep.
* Unsaved changes survive a browser crash: you're offered a restore next time.
* **Bundle** downloads a `.edgez` file with the experiment and every file it uses, ready to send
  to a colleague (`edge unbundle file.edgez`).

## Help and tutorials

* **?** opens the Help Center: all guides, search, and the interactive tutorials.
* Tutorials run *in* the builder: the coach highlights what to use and advances when you've done the
  step. Completed tutorials are ticked ✓.

## Keyboard shortcuts

| keys | action |
|---|---|
| Ctrl/⌘ S | save |
| Ctrl/⌘ Z, Ctrl/⌘ Shift Z | undo, redo |
| Delete / Backspace | remove the selected component |
| ? | help |
| Esc | close dialogs |
