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

## Builder
- [ ] Multi-select, copy/paste between experiments, drag positions in the stimulus preview
- [ ] Conditions spreadsheet editor with xlsx round trip
- [ ] Inline expression checking and autocompletion of variables in scope
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
