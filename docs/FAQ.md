# FAQ and troubleshooting

## General

**Do I need to know Python or any programming?**
No. **Answer a few questions** (on Home) builds a complete, tested task, the [assistant](ASSISTANT.md) builds
one from a description in your own words, and the builder covers nearly everything else with menus: the button
next to each property picks a trial-list column, or makes one, so you rarely type a formula. Formulas
(`$resp.rt < 0.5`) are there when you want them, and Python code items (Expert mode) for anything beyond that.

**Is this computer good enough for precise timing?**
Run `edge doctor` (or **⋯** › **Check this computer** in the builder; the **Run** page runs the same check before a session). It looks for the
known culprits: a laptop on battery, a generic display driver, several monitors with Windows
fullscreen optimizations, USB power saving that puts response boxes to sleep, slow USB-serial
adapters, input method editors. It explains each one and fixes what it can (`edge doctor --fix`).
Every session also measures the real refresh rate and reports problems in its report. See
[Known issues on lab computers](KNOWN_ISSUES.md).

**How do I install it without a terminal?**
Use the installer for your system (see [Getting started](GETTING_STARTED.md#1-install)); it puts an
EDGE icon on the desktop. If you installed with pip, `edge desktop-shortcut` makes the icon.

**The EDGE icon is on the desktop but nothing opens.**
The icon starts EDGE quietly in the background (no black window), so problems used to be invisible. Now
a failure shows a message box with the reason, and everything is written to `~/.edge/launch.log`
(Windows: `C:\Users\<you>\.edge\launch.log`). Things to check, in this order:
1. Wait 5 seconds, then open <http://127.0.0.1:8765/> in your browser: EDGE may be running without a
   browser having opened (EDGE shows this address when it can't open a browser).
2. Open `launch.log`: the last lines say what happened.
3. In a terminal, run `edge doctor`, then `edge` (it prints what is going on).
4. Make the icon again with `edge desktop-shortcut`, or run the installer again; it also checks that
   EDGE really installed (a missing `git` or no internet connection are the usual causes).

**What's the difference between a test run, Try it and Run?**
A **test run** (Test page): a virtual participant does the whole experiment in seconds with simulated hardware,
to catch mistakes and show the data you'll get. **Try it**: *you* do the experiment inside the builder, to
see and feel it. **Run**: the real session with a participant in the experiment window, with real hardware and
precise timing.

**Do I need the assistant? Does it send my data anywhere?**
No, it is optional: everything else works without it. With **Ollama** or **LM Studio** it runs on this computer
and nothing leaves it. With an online service (Claude by Anthropic, OpenAI, OpenRouter …), what you type, the
experiment you are editing and the files you attach are sent to that company; your participants' data (the data
folders) never is, and your API key stays on this computer. The line under the box you type in always says which.
See [The assistant](ASSISTANT.md#what-is-sent-where).

**Which model should I use for the assistant?**
Claude (with an API key) gives the best results. Locally, use a model that can call tools, e.g. `qwen2.5:14b` in
Ollama: small models (7–8 B) manage single changes; for building whole experiments from a description use 14 B or
more. See [Set up Ollama](ASSISTANT.md#set-up-ollama).

**The assistant says Ollama isn't running, or the model isn't downloaded.**
Start the Ollama app (or run `ollama serve`), and download the model with `ollama pull <model>`. Then press **Test
connection** in **Assistant settings**. Other messages and what to do are in
[When something goes wrong](ASSISTANT.md#when-something-goes-wrong).

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
pick the column with the button next to the field (**From the trial list**), or add it with **New trial-list
column…**.

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
never ends. (In the builder: switch on **Ends the screen** on the response, or set **Lasts at most** on the screen.)

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

**"This experiment was changed elsewhere"**
Another window, an editor, or Claude (via MCP) saved the same file. Choose **Keep my version** or **Load the other
version**. The other one is still available under **History…** in the Experiment menu.

**"E-Prime .es3/.es2 files are a closed binary format"**
In E-Studio press *Generate* (Ctrl+F7) and import the `.ebs3` it writes. Also save each List as
`<ListName>.txt` next to it.

## How do I …

**… make a value change from trial to trial?** Click the button next to the property's label (*Fixed*) and
choose **New trial-list column…** (or **From the trial list** › an existing column), then fill in the trial
list: one row per trial.
In the file that's `$column` in the property and the column in the loop's `conditions`.

**… show something only sometimes?** An item's **Only if** (under More options; `if: "$condition"` in the file);
for a whole screen, **Show only if…** on its card or an **If / otherwise** frame (`{routine: name, if: "$condition"}`).

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

**… undo a change from yesterday?** **History…** in the Experiment menu, or `edge backups study.yaml`.

**… see every option?** Switch to **Expert** (bottom right, in the status bar). Simple mode folds rare options
under **More options**; **Ctrl+K** finds everything in both modes.

**… share an experiment?** **Share as one file (.edgez)** in the Experiment menu (or `edge bundle study.yaml`)
makes one `.edgez` file with everything it needs.

**… let Claude build it for me?** In the builder, the [assistant](ASSISTANT.md) (Claude, an OpenAI-compatible
service, Ollama or LM Studio); from Claude Code or VS Code, [MCP](MCP.md).

## Glossary

| term | meaning |
|---|---|
| **screen** / **routine** | one step: a trial, instructions, feedback. The builder says *screen*; the file says `routines` |
| **item** / **component** | a thing on a screen: stimulus, response, eye-tracking area, marker, logic step. The builder says *item*; the file says `components` |
| **storyboard** / **flow** | the order in which screens run, with trial lists, if / otherwise and workflows |
| **trial list** / **loop** | repeats screens once per row of a table; each column can be used as a value (**From the trial list** next to a field, `$column` in a formula) |
| **conditions** | the rows of a trial list in the file |
| **workflow** / **state machine** | **phases** (states) with conditional routes between them |
| **route** | a rule saying which phase comes next ("when accuracy ≥ 0.8 go to main") |
| **rule** | inside a screen: "when this becomes true, do that" |
| **formula / expression** | a value starting with `$`, computed while the experiment runs |
| **marker** | an event sent to every device (TTL code, LSL sample, eye-tracker message) at a stimulus onset |
| **flip** | the moment a new frame appears on screen; all onsets are stamped with flip times |
| **test run / dry run** | a fast simulated run with simulated devices and a virtual participant (`edge run --dry-run`) |
| **Try it** | doing the experiment yourself inside the builder |
| **virtual participant** | the simulated person who responds during test runs |
| **survey** | a questionnaire page built from questions (choice, Likert, matrix, slider, text, rank …), with scoring |
| **instrument** | a validated questionnaire from the library, added with `{instrument: phq9}` |
| **display logic** | `show_if`: show a question only for certain earlier answers |
| **design wizard** | **Answer a few questions** on Home, or `edge wizard`: a finished experiment from plain answers |
| **assistant** | builds and changes experiments from a description in your own words, with a preview you apply or discard |
| **Simple / Expert mode** | how much of the builder is shown |
| **session** | one run of the experiment for one participant; one data folder |
| **bundle** | a `.edgez` file containing an experiment and all its files |
