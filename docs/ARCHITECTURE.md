# Architecture

```
edge/
  model.py          Experiment document: parse, validate, save (YAML/JSON)
  expressions.py    sandboxed $expressions, plain-language error messages
  scope.py          static check: is every name an expression reads defined where it's used?
  conditions.py     trial lists: files, factorial, ordering, constraints, Latin squares, staircases
  engine.py         Runner (flow, loops, branches) + RoutineRun (frame loop)
  runtime.py        Session: backend + devices + data + markers + guaranteed cleanup
  clock.py          the master clock
  events.py         markers and the event bus that routes them to every connected device
  components/       stimulus, response, eye-tracking, hardware and logic components (registry + plugins)
  backends/         pyglet (OpenGL window) and headless (virtual clock or real-time)
  devices/          drivers + registry + base class (streams, sinks, threads, clock models), trigger adapters,
                    response inputs, UDP messages (closed loop), simulators
  sync.py           clock models: linear fit, round trip, arrival envelope
  data.py           session folder writers (raw logs)
  storage.py        atomic save/load, backups & undo, conflict detection, migrations, .edgez bundles
  editing.py        validated document-editing API (used by the MCP server and scripts)
  measures.py       what an experiment measures (outcomes, factors, checks) and everything it records
  export.py         wide trial tables, summaries, data dictionary, xlsx/csv/json/parquet/mat/BIDS, merging
  mcp_server.py     MCP server: natural-language control from Claude / VS Code
  report.py         post-session timing / integrity / sync analysis
  align.py          external-recording alignment via TTL code sequences
  participant.py    virtual participant for dry runs
  scan.py           hardware discovery
  importers/        PsychoPy, E-Prime, OpenSesame and jsPsych importers (`edge import`)
  templates.py      starter experiments (and hidden starting points for tutorials)
  survey.py         survey questions: model, validation, display logic, page renderer, auto-answers, data, scoring
  survey_library.py validated questionnaires and answer scales (citations, licences, scoring rules)
  survey_i18n.py    the survey page's buttons and messages per language (right to left for Hebrew)
  survey_lists.py   lists for autocomplete questions (countries, languages)
  survey_page/      the survey page's CSS and JavaScript
  bidi.py           right-to-left text (Hebrew, Yiddish) in the experiment window
  htmlview.py       one HTML page in a native window (pywebview), for the `html` component
  wizard.py         design wizard: answers -> finished experiment; trial/duration estimates
  play.py           "Try it": BrowserBackend (real engine, frames published to the builder), single-screen runs
  monitor.py        live session monitor: what the experimenter sees while a participant runs
  pitfalls.py       static checks for experiments that look fine but time or run wrong
  preflight.py      go / no-go before collecting data (`edge preflight`)
  reproduce.py      lock a piloted experiment and verify nothing changed since (`edge lock`, `edge verify`)
  syscheck.py       computer check (`edge doctor`): the known causes of bad timing and lost responses
  devtest.py        test one device before a session (`edge test-device`)
  diagnostics.py    structured error reports: what failed, where, when and in what state
  support.py        support bundle: one zip to ask for help, without participant data
  launcher.py       `edge` with no arguments, default workspace, desktop shortcuts, terminal wizard
  updater.py        `edge update`: git clones and installed copies; `edge.__version__` names the exact commit
  help.py           docs topics, search, tutorials, generated reference pages (`edge help`, `edge docs build`)
  tutorials/        interactive tutorial definitions (YAML; also rendered into docs/TUTORIALS.md)
  assets/           the EDGE icon in every size the desktop shortcuts need
  builder/          local web server + single-page builder (no build step): app.js (editor), simple.js
                    (storyboard, wizard, Try it, run dialog), survey.js (survey editor, questionnaire library),
                    measures.js (Measures & data), stage.js (property widgets, file pickers)
  cli.py            `edge` command
docs/               the guides (copied into the package as edge/docs when a wheel is built, see setup.py)
install/            installer scripts (sh, PowerShell), experimental PyInstaller recipe (edge.spec)
update.sh, .bat     `edge update` for clones, finding the Python that has the clone installed
```

## Frame loop (RoutineRun.run)

```
prepare components (code on_begin and variable(start) run here, in order)
loop:
  predict next flip time
  decide which components start / stop on that flip   (time, frame, start_after, start_if, stop_if, finished)
  non-visual on_frame  →  visual on_frame (draw, list order)
  flip  →  measured flip time
  starting: on_start(flip) + onset markers  ·  stopping: on_stop(flip) + offset markers
  input events → active components
  poll devices (non-threaded drivers read here)
  escape → abort (data is still saved)
  end conditions: end_routine component done/timed out · routine duration · end_if · all finished
```

## Design principles

* **The document is the experiment.** The builder, the CLI and scripts all edit the same YAML.
  Nothing is generated and then hand-edited.
* **Every device is a driver with the same small interface.** connect, start, poll, send_marker,
  stop, close. Streams go through one sink to disk. Clock models are per device.
* **Simulate everything.** Each backend and driver has a simulated twin, so a whole study can be
  tested on a laptop and in CI.
* **Data you can trust without EDGE.** Plain CSV/JSON, raw and aligned times side by side, the exact
  experiment and seed saved with every session.
* **Fail loudly before participants arrive.** Validation (including names used where they don't exist),
  dry runs (a routine that can never end is an error) and the quality report.
* **Explain, don't just reject.** Every error says what is wrong, where, and what to try, in the words
  the builder uses (screen, trial list), with the closest match for misspellings.
