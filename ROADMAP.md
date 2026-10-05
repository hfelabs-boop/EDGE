# Roadmap

## Done in 0.1
- Experiment model, sandboxed expressions, validator with TTL-collision warnings
- Frame-locked engine; loops (5 orders, constraints, Latin squares), branches, staircases
- Components: text, shape, fixation, image, sound, keyboard, mouse, slider, gaze ROI, gaze follow,
  calibrate, marker, variable, code, wait
- Drivers: Tobii Pro, Gazepoint, g.tec (LSL/Unicorn/gds), MindWare, LSL in/out, serial TTL,
  parallel port, simulators
- Clock models, aligned stream files, quality report, external alignment
- Browser builder: timeline, flow, properties, live preview, devices, hardware scan, dry run, YAML
- Dry runs with a virtual participant; real-time headless mode for screenless studies
- Storage: atomic saves, version history/undo, conflict detection, live builder sync, crash-recovery drafts,
  format migrations, .edgez bundles
- Data: one-row-per-trial tables, automatic summaries and data dictionaries, xlsx/csv/tsv/json/parquet/mat/BIDS
  exports, multi-participant merge, builder Data tab
- MCP server (44 tools, resources, prompts) for Claude Code, Claude Desktop and VS Code
- Workflow logic: state machines with a visual diagram editor, routine "when → do" rules, component `if`,
  live loop performance
- HTML pages as experiment steps (forms, questionnaires, JS tasks) with saved answers
- Importers: PsychoPy, E-Prime (generated script), OpenSesame, jsPsych; builder start screen and import dialog
- Learning: 8 interactive in-builder tutorials, Help Center with search and contextual links, getting-started,
  builder guide, tested cookbook, FAQ; component/device/CLI references generated from the code; `edge help`
- For new users: design wizard (builder, `edge wizard`, MCP), storyboard view, Simple/Expert modes with "More options",
  human names for components and terms (screen, trial list, Test run), value-source menu (fixed / trial-list column /
  new column / formula), Try it inside the builder (real engine, browser display, sounds, web pages), run dialog
  (next participant ID, hardware, full screen), plain-language errors with "did you mean", a static check for names
  that aren't defined where they're used, one-command installers, desktop shortcut, `edge` with no arguments

- Surveys: 35 question types (the professional catalogue incl. side by side, form fields, pick-group-rank, hot spot,
  heat map, drill down, highlight, signature, timing, meta info, file upload, captcha, autocomplete, tree testing,
  video response, screen capture, location), full right-to-left support with translated messages
- Surveys (first version): survey component with display logic, piped text, randomization, scores; library of
  20 validated free-to-use questionnaires with citations; survey editor with live preview; wizard, MCP and tutorial

## Next: hardware validation (highest priority)
- [ ] Run every driver against physical devices; photodiode + TTL loopback timing benchmarks
      published per OS/GPU (Windows 11, macOS, Ubuntu)
- [ ] `edge latency-test`: a guided photodiode/trigger self-test that writes a lab timing certificate
- [ ] Low-latency audio backend (PortAudio/WASAPI exclusive) with measured onset latency
- [ ] Hardware keyboard/button boxes (Cedrus RB, Black Box ToolKit, Arduino) with µs timestamps

## More devices
- [ ] EyeLink (pylink), Pupil Labs Neon/Core, Smart Eye, Tobii Pro Lab external presenter events
- [ ] Brain Products (RDA/RCS), BioSemi, ANT Neuro, OpenBCI, Muse via native APIs
- [ ] BIOPAC (AcqKnowledge network data transfer), Shimmer, Empatica, Polar H10
- [ ] fNIRS (NIRx, Artinis), MRI scanner trigger input (TR sync), TMS/tDCS triggering
- [ ] Generic "device from a description file" (serial/TCP/UDP protocols declared in YAML)

## Import
- [ ] Inquisit (.iqx), Gorilla, PsyToolkit, Presentation (.sce/.pcl), Psychtoolbox scripts (common patterns)
- [ ] Validate importers against large public corpora of real experiments (Pavlovia, OSF)

## Learning
- [ ] Video walkthroughs; translated documentation and tutorials (DE, ES, FR, ZH, JA)
- [ ] Published documentation site (`mkdocs` from docs/), versioned per release

## Builder
- [ ] Multi-select, copy/paste between experiments, drag positions in the stimulus preview
- [ ] Conditions spreadsheet editor with xlsx round trip
- [ ] Inline expression checking as you type (the Check tab already reports unknown names with suggestions)
- [ ] Wizard: picture upload from the dialog, more designs (go/no-go, n-back, visual search, questionnaires only)
- [ ] Try it: render text with the same font metrics as the experiment window; slider dragging feedback
- [ ] Surveys: online services (reCAPTCHA, ArcGIS maps), unmoderated user testing of external sites,
      interview scheduling; more message translations (tr, zh, ja …)
- [ ] Surveys: per-question timing, loop & merge (repeat a block per selected option), carry-forward choices,
      side-by-side and heat-map questions, image choice, validated translations of the library
- [ ] Signed stand-alone apps (PyInstaller recipe exists; needs testing and code signing on macOS/Windows)
- [ ] Live device dashboards (gaze overlay, signal quality, impedance) during sessions
- [ ] Experimenter console: participant queue, session notes, run log, abort and resume

## Runtime
- [ ] Movie component (hardware-decoded, frame-locked)
- [ ] Online runner: compile the same YAML to a browser runtime (JATOS / Pavlovia / Prolific)
- [ ] VR/AR backend (OpenXR) with eye tracking in headsets
- [ ] Resume interrupted sessions from `trials.jsonl`
- [ ] Full BIDS-EEG (EDF/BrainVision writing) and BEP020 eye-tracking compliance; XDF export
- [ ] SPSS (.sav) and R (.rds) exports with value labels from the data dictionary

## Analysis
- [ ] Built-in epoching (EEG/physio/pupil around markers), fixation/saccade detection, AOI reports
- [ ] One-click export to MNE-Python, EEGLAB, R
