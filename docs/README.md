# EDGE documentation

Welcome! EDGE builds and runs behavioural, eye-tracking, EEG and physiology experiments. These pages
are also built into the app: press **?** in the builder, or run `edge help` in a terminal.

## Start here

| | |
|---|---|
| [Getting started](GETTING_STARTED.md) | install EDGE, open the builder, run your first experiment (15 minutes) |
| [Tutorials](TUTORIALS.md) | eight hands-on lessons, also available as **interactive tutorials** in the builder |
| [Builder guide](BUILDER_GUIDE.md) | a tour of every part of the visual builder |
| [FAQ & troubleshooting](FAQ.md) | common questions, error messages, glossary |

## Building experiments

| | |
|---|---|
| [Cookbook](COOKBOOK.md) | copy-and-adapt recipes: jittered ISIs, breaks, counterbalancing, practice criteria, gaze-contingent trials, EEG triggers … |
| [Experiment format](EXPERIMENT_FORMAT.md) | complete reference of the YAML format: settings, components, timing, loops, workflows, rules, HTML pages |
| [Devices and synchronization](DEVICES.md) | eye trackers, EEG, physiology, LSL, TTL; how clocks are aligned and verified |
| [Data](DATA.md) | saving and loading, what is recorded, trial tables, summaries, exports |
| [Importing](IMPORT.md) | bring experiments from PsychoPy, E-Prime, OpenSesame and jsPsych |
| [Claude & VS Code (MCP)](MCP.md) | build and analyse experiments by describing them in plain language |

## Reference (generated from the code)

| | |
|---|---|
| [Components](reference/components.md) | every component and property |
| [Devices](reference/devices.md) | every device driver and option |
| [Command line](reference/cli.md) | every `edge` command |
| [Architecture](ARCHITECTURE.md) | how EDGE is built (for contributors) |

## Getting help in the app

* **?** (top right of the builder, or the `?` key) opens the Help Center: guides, search and tutorials.
* **📖 docs** links next to components, devices, loops, workflows and rules open the matching reference.
* The grey **summary** above each routine's timeline describes in plain words what the routine does.
* `edge help <words>` searches the docs from a terminal; `edge tutorial` lists the tutorials.
