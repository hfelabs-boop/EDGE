# FAQ and troubleshooting

## General

**Do I need to know Python?**
No. The builder, the YAML file and the expressions (`$word`, `$resp.rt < 0.5`) cover nearly everything.
Python is there when you want it: `code` components run full Python.

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

**"dry run: routine 'X' did not end after 600 s"**
Nothing ends that routine. Give it a `duration`, tick `end_routine` on a response, or add `end_if`.
A component without a duration runs until the routine ends, so a routine made only of such components
never ends.

**"error evaluating '…': NameError: name 'x' is not defined"**
The expression uses a variable that doesn't exist at that point. Check the spelling, and check that
the routine really is inside the loop whose trial list has that column. Type `$` in the field to see
the names available there.

**"syntax error in expression"**
Expressions are Python. Quote strings (`$ink == 'red'`, not `$ink == red`) and use `==` to compare.

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

**… make a value change from trial to trial?** Put it in the loop's trial list and write `$column` in
the property.

**… show something only sometimes?** Component `if: "$condition"`; for a whole routine, a flow entry
`{routine: name, if: "$condition"}`.

**… repeat practice until people get it?** A workflow; see the
[Cookbook](COOKBOOK.md#practice-until-80-correct-at-most-three-times) and the interactive tutorial.

**… send triggers to my EEG?** Add a `ttl_serial` or `parallel_port` device and set `marker:` on the
stimulus. See [Cookbook](COOKBOOK.md#fixed-trigger-codes-for-an-eeg-amplifier).

**… add a consent form or questionnaire?** An `html` component; see the HTML tutorial.

**… undo a change from yesterday?** **Versions** in the builder, or `edge backups study.yaml`.

**… share an experiment?** **Bundle** (or `edge bundle study.yaml`) makes one `.edgez` file with
everything it needs.

**… let Claude build it for me?** See [MCP](MCP.md).

## Glossary

| term | meaning |
|---|---|
| **routine** | one screen or event sequence (a trial, instructions, feedback) |
| **component** | an element of a routine: stimulus, response, eye-tracking area, marker, logic step |
| **flow** | the order in which routines run, with loops, branches and workflows |
| **loop** | repeats routines once per row of a trial list |
| **trial list / conditions** | the table a loop iterates over; columns become variables |
| **workflow / state machine** | states (blocks) with conditional routes between them |
| **route** | a rule saying which state comes next ("if accuracy ≥ 0.8 go to main") |
| **rule** | inside a routine: "when this becomes true, do that" |
| **expression** | a value starting with `$`, computed while the experiment runs |
| **marker** | an event sent to every device (TTL code, LSL sample, eye-tracker message) at a stimulus onset |
| **flip** | the moment a new frame appears on screen; all onsets are stamped with flip times |
| **dry run** | a fast simulated run with simulated devices and a virtual participant |
| **virtual participant** | the simulated person who responds during dry runs |
| **session** | one run of the experiment for one participant; one data folder |
| **bundle** | a `.edgez` file containing an experiment and all its files |
