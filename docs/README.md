# EDGE documentation

Welcome! EDGE builds and runs behavioural, eye-tracking, EEG and physiology experiments. These pages
are also built into the app: press **?** in the builder (Help opens next to your work), or run `edge help` in a
terminal.

## Start here

| | |
|---|---|
| [Getting started](GETTING_STARTED.md) | install EDGE (one command, desktop icon), answer a few questions or describe it to the assistant to get a finished experiment, try it, run it (15 minutes) |
| [Tutorials](TUTORIALS.md) | hands-on lessons (ten, from a first Stroop task to surveys, imports and the assistant), also available as **interactive tutorials** in the builder |
| [Builder guide](BUILDER_GUIDE.md) | a tour of every part of the visual builder: Home, Build, Measures, Test, Run, Data |
| [The assistant](ASSISTANT.md) | build and change experiments by describing them, with your files attached: set up Claude, an OpenAI-compatible service, Ollama or LM Studio; preview, apply and undo; what is sent where |
| [FAQ & troubleshooting](FAQ.md) | common questions, error messages, glossary |
| [The usual pain points](PAIN_POINTS.md) | what goes wrong with experiment software (works here not there, updates, errors, timing, hardware) and how EDGE handles it: preflight, lock, error reports, device and timing tests |
| [Known issues on lab computers](KNOWN_ISSUES.md) | power saving, display drivers, monitors, USB adapters, sound: what EDGE checks and fixes (`edge doctor`) |
| [Security model](SECURITY.md) | what EDGE trusts and what it doesn't: the local-only builder, the expression sandbox, code components as scripts, messages from other programs, data files |

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

* **?** (top right of the builder, or the `?` key) opens **Help** next to your work: search, help about what
  you're looking at, the interactive tutorials (**Learn by doing**) and every guide.
* The book buttons next to items, devices, trial lists, workflows and rules open the matching reference.
* **In words** above each screen's timeline describes in plain words what the screen does.
* The status bar counts the problems; click it to read them in plain words and **Go there**. **Try it** lets you
  do the experiment yourself.
* **Ctrl+K** searches everything (screens, items, actions, help) and can hand your question to the assistant.
* `edge help <words>` searches the docs from a terminal; `edge tutorial` lists the tutorials.
