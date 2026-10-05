# FAQ and troubleshooting

## General

**Do I need to know Python or any programming?**
No. **New → Make a new experiment: answer a few questions** builds a complete, tested task, and the
builder covers nearly everything else with menus: the value menu next to each property picks a trial-list
column, or makes one, so you rarely type a formula. Formulas (`$resp.rt < 0.5`) are there when you want
them, and Python `code` components (Expert mode) for anything beyond that.

**How do I install it without a terminal?**
Use the installer for your system (see [Getting started](GETTING_STARTED.md#1-install)); it puts an
EDGE icon on the desktop. If you installed with pip, `edge desktop-shortcut` makes the icon.

**What's the difference between Test run, Try it and Run with a participant?**
**Test run**: a virtual participant does the whole experiment in seconds with simulated hardware, to
catch mistakes and show the data you'll get. **Try it**: *you* do the experiment inside the builder, to
see and feel it. **Run with a participant**: the real session in the experiment window, with real
hardware and precise timing.

**Can I open my PsychoPy / E-Prime experiments?**
Yes, see [Importing](IMPORT.md). PsychoPy converts most completely. For E-Prime, import the
*generated script* (`.ebs3`); `.es3` files are a closed binary format.

**How accurate is the timing?**
Starts and stops are decided for each screen refresh and stamped with the measured flip time; RTs
are measured from that flip. `edge report` shows dropped frames and, per device, how precisely the
markers were aligned. For publication-grade claims, measure your setup once with a photodiode and a
trigger loopback: no software can see the monitor's own input lag.

**Which devices have been tested on real hardware?**
LSL is tested for real; Gazepoint is tested against a protocol-level simulator. The Tobii, g.tec,
MindWare, serial and parallel-port drivers follow the vendors' documentation but should be checked
on your hardware before data collection (see [Devices](DEVICES.md)).

**Where is my data?**
In `data/` next to the experiment, one folder per session (`<participant>_<session>_<experiment>_<date>`).
Start with `trials_wide.csv`, `summary.csv` and `data_dictionary.csv`. See [Data](DATA.md).

## Error messages

Check messages are written to be read: they say what's wrong, where (*screen “trial” › word › color*),
and usually what to do. The most common ones:

**"The trial list has no column called 'ink'. Did you mean 'colour'?"**
A property uses `$ink`, but the trial list around this screen has no such column. Fix the spelling,
pick the column from the value menu (⟳), or add it with **+ New trial-list column…**.

**"'word' comes from the trial list of loop 'trials', but this screen also runs outside that loop"**
The same screen is in the flow twice, once outside the trial list, where `$word` has no value. Use a
separate screen there, or give the value with a *Set a variable* step.

**"'x' isn't defined anywhere in this experiment"**
Nothing defines that name: no trial-list column, variable or component. Often it's plain text that
starts with `$` by accident: remove the `$` (or write `$$` for a literal dollar sign).

**"this component has the same name as the trial-list column 'word'"** (note)
`$word` gives the column's value, so the component's own results (`word.onset`) can't be used by
name. Rename the component (e.g. `word_text`) if you need them.

**"Could not start: no screen is available to open the experiment window on"**
The experiment window needs a monitor, so it can't open over SSH or in a container. Run on the lab
computer, or use Test run / Try it, which need no window.

**"test run: routine 'X' did not end after 600 s"** (also "dry run: …")
Nothing ends that routine. Give it a `duration`, tick `end_routine` on a response, or add `end_if`.
A component without a duration runs until the routine ends, so a routine made only of such components
never ends. (In the builder: tick **ends the screen** on the response, or set **lasts at most** on the screen.)

**"'x' isn't defined here (in '…'). Did you mean 'y'? Names available: …"** (while running)
The formula uses a name that doesn't exist at that moment. The message lists what does exist and
the closest match. Usually Check has already warned about it.

**"'…' isn't a valid expression (syntax error …)"**
Formulas are Python. Quote text (`$ink == 'red'`, not `$ink == red`) and use `==` to compare; the
message adds a hint for the common slips (a single `=`, a missing quote or bracket, plain text after `$`).

**"a value is still empty, e.g. no response yet"**
A formula used a response before there was one (`resp.rt * 1000` when nobody pressed). Check for it
first: `$resp.rt is not None and resp.rt < 1`.

**"'…' is not allowed in expression"**
Expressions are sandboxed (no imports, no `_private` attributes, no lambdas), so shared experiment files
are safe to open. Use a `code` component for anything more.

**"markers from A, B all fire at t=0.5s"** (warning)
Two components send markers at the same moment. On a TTL line the second overwrites the first.
Use one marker per onset, or encode both in one label.

**"WARNING: measured refresh rate 1000 Hz: vsync is not working"**
The graphics driver isn't synchronizing to the monitor (common on remote desktops, virtual machines
and some laptops). Turn on vsync in the GPU control panel, connect the experiment monitor directly,
or set `settings.window.refresh_rate`, knowing that frame-exact timing is then not guaranteed.

**"device 'X' failed to connect"**
The device or its software isn't running. Gazepoint: start Gazepoint Control. Tobii: check Tobii Pro
Eye Tracker Manager and `pip install tobii-research`. LSL: start the streaming app and check with
`edge scan`. Mark devices that aren't essential with `required: false` so a session can continue
without them.

**"no LSL consumer connected"**
`wait_for_consumers` is set and nothing is recording the marker stream. Start LabRecorder and select
`EDGE-Markers`.

**"This file was changed outside the builder"**
Another window, an editor, or Claude (via MCP) saved the same file. Choose whose version to keep. The
other one is still available under **Versions**.

**"E-Prime .es3/.es2 files are a closed binary format"**
In E-Studio press *Generate* (Ctrl+F7) and import the `.ebs3` it writes. Also save each List as
`<ListName>.txt` next to it.

## How do I …

**… make a value change from trial to trial?** In the value menu next to the property choose
**+ New trial-list column…** (or an existing **⟳ column**), then fill in the trial list: one row per trial.
In the file that's `$column` in the property and the column in the loop's `conditions`.

**… show something only sometimes?** Component `if: "$condition"`; for a whole routine, a flow entry
`{routine: name, if: "$condition"}`.

**… repeat practice until people get it?** A workflow; see the
[Cookbook](COOKBOOK.md#practice-until-80-correct-at-most-three-times) and the interactive tutorial.

**… send triggers to my EEG?** Add a `ttl_serial` or `parallel_port` device and set `marker:` on the
stimulus. See [Cookbook](COOKBOOK.md#fixed-trigger-codes-for-an-eeg-amplifier).

**… add a consent form or questionnaire?** The **Survey / questionnaire** component: its editor has every
common question type and a library of validated questionnaires (consent, demographics, PHQ-9, GAD-7, Big Five,
NASA-TLX, SUS …) that score themselves. See [Surveys](SURVEYS.md) and the interactive survey tutorial. For a
page you designed yourself, use an `html` component.

**… run a survey in Hebrew (right to left)?** Write the questions in Hebrew: the page switches to
right-to-left with Hebrew buttons and messages. Or set `language: he` or `direction: rtl` on the survey. Text components have `direction: auto | ltr | rtl` too.
See [Surveys](SURVEYS.md#right-to-left-hebrew).

**… score a questionnaire?** Library questionnaires score themselves. For your own, add `scores` (sum, mean,
reverse items, bands); see [Surveys](SURVEYS.md#scores).

**… undo a change from yesterday?** **Versions** in the builder (Expert mode), or `edge backups study.yaml`.

**… see every option?** Switch to **Expert** (top right). Simple mode folds rare options under **More options**.

**… share an experiment?** **Bundle** (or `edge bundle study.yaml`) makes one `.edgez` file with
everything it needs.

**… let Claude build it for me?** See [MCP](MCP.md).

## Glossary

| term | meaning |
|---|---|
| **screen** / **routine** | one step: a trial, instructions, feedback. The builder says *screen*; the file says `routines` |
| **component** / **thing on a screen** | an element of a screen: stimulus, response, eye-tracking area, marker, logic step |
| **flow** | the order in which routines run, with loops, branches and workflows |
| **loop** | repeats routines once per row of a trial list |
| **trial list / conditions** | the table a loop iterates over; each column can be used as a value (⟳ in the value menu, `$column` in a formula) |
| **workflow / state machine** | states (blocks) with conditional routes between them |
| **route** | a rule saying which state comes next ("if accuracy ≥ 0.8 go to main") |
| **rule** | inside a routine: "when this becomes true, do that" |
| **formula / expression** | a value starting with `$`, computed while the experiment runs |
| **marker** | an event sent to every device (TTL code, LSL sample, eye-tracker message) at a stimulus onset |
| **flip** | the moment a new frame appears on screen; all onsets are stamped with flip times |
| **test run / dry run** | a fast simulated run with simulated devices and a virtual participant (`edge run --dry-run`) |
| **Try it** | doing the experiment yourself inside the builder |
| **virtual participant** | the simulated person who responds during test runs |
| **survey** | a questionnaire page built from questions (choice, Likert, matrix, slider, text, rank …), with scoring |
| **instrument** | a validated questionnaire from the library, added with `{instrument: phq9}` |
| **display logic** | `show_if`: show a question only for certain earlier answers |
| **design wizard** | **New → answer a few questions**, or `edge wizard`: a finished experiment from plain answers |
| **Simple / Expert mode** | how much of the builder is shown |
| **session** | one run of the experiment for one participant; one data folder |
| **bundle** | a `.edgez` file containing an experiment and all its files |
