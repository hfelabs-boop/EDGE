# EDGE documentation

Welcome! EDGE builds and runs behavioural, eye-tracking, EEG and physiology experiments. These pages
are also built into the app: press **?** in the builder, or run `edge help` in a terminal.

## Start here

| | |
|---|---|
| [Getting started](GETTING_STARTED.md) | install EDGE (one command, desktop icon), answer a few questions to get a finished experiment, try it, run it (15 minutes) |
| [Tutorials](TUTORIALS.md) | eight hands-on lessons, also available as **interactive tutorials** in the builder |
| [Builder guide](BUILDER_GUIDE.md) | a tour of every part of the visual builder |
| [FAQ & troubleshooting](FAQ.md) | common questions, error messages, glossary |
| [Known issues on lab computers](KNOWN_ISSUES.md) | power saving, display drivers, monitors, USB adapters, sound: what EDGE checks and fixes (`edge doctor`) |

## Building experiments

| | |
|---|---|
| [Cookbook](COOKBOOK.md) | copy-and-adapt recipes: jittered ISIs, breaks, counterbalancing, practice criteria, gaze-contingent trials, EEG triggers … |
| [Surveys and questionnaires](SURVEYS.md) | question types, display logic, scores, and the library of validated questionnaires (PHQ-9, GAD-7, Big Five, NASA-TLX …) |
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
| [Questionnaires](reference/questionnaires.md) | every library questionnaire: items, answers, scoring, citation |
| [Command line](reference/cli.md) | every `edge` command |
| [Architecture](ARCHITECTURE.md) | how EDGE is built (for contributors) |

## Getting help in the app

* **?** (top right of the builder, or the `?` key) opens the Help Center: guides, search and tutorials.
* **📖 docs** links next to components, devices, loops, workflows and rules open the matching reference.
* The grey **summary** above each screen's timeline describes in plain words what the screen does.
* **Check** explains problems in plain words and jumps to them; **▶ Try it** lets you do the experiment yourself.
* `edge help <words>` searches the docs from a terminal; `edge tutorial` lists the tutorials.
