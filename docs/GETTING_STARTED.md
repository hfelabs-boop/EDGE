# Getting started

This page takes you from nothing to a tested experiment in about 15 minutes.

## 1. Install

You need **Python 3.10 or newer** (python.org, or Anaconda/Miniconda).

```bash
git clone https://github.com/hfelabs-boop/EDGE.git
cd EDGE
pip install -e ".[all]"
```

`[all]` adds the experiment window (pyglet), Lab Streaming Layer, serial trigger boxes and the
MCP server. Extras you might also want:

| extra | for |
|---|---|
| `pip install -e ".[tobii]"` | Tobii Pro eye trackers |
| `pip install -e ".[html]"` | showing HTML pages in a native full-screen window (otherwise the browser is used) |
| `pip install -e ".[export]"` | Parquet and MATLAB exports |

Check the installation:

```bash
edge --version
edge devices          # which device drivers are usable on this computer
```

## 2. Open the builder

```bash
mkdir my_study && cd my_study
edge builder
```

Your browser opens the builder. The welcome screen offers **interactive tutorials**, templates, and
importing from PsychoPy, E-Prime, OpenSesame or jsPsych.

## 3. Do the first tutorial

Click **Your first experiment (a Stroop task)**. A coach appears in the corner. It highlights where to
click and moves on when you've done each step. In about ten minutes you'll have built routines,
timing, a trial list, randomization and a dry run.

You can also start it from a terminal: `edge tutorial first_experiment`.

## 4. Test with a dry run

**Dry run** (green button, or `edge run study.yaml --dry-run --report`) runs the whole experiment in
seconds:

* every device is simulated on its own drifting clock, so the synchronization is tested too;
* a *virtual participant* answers with realistic reaction times and 90% accuracy;
* the output is a real data folder, so your analysis can be written before anyone is tested.

A routine that can never end, a missing file, or a broken expression shows up here, not in front of
a participant.

## 5. Run it for real

```bash
edge run study.yaml -p 001 -s 1          # participant 001, session 1
```

or press **Run** in the builder. Press **Escape** to abort; data recorded so far is saved.
Afterwards:

```bash
edge report data/001_1_study_*           # timing and synchronization check
edge export data/ --formats csv,xlsx     # one table for all participants
```

## 6. Where to go next

* [Tutorials](TUTORIALS.md): trial lists, workflows (practice until criterion), eye tracking,
  questionnaires, rules, data.
* [Cookbook](COOKBOOK.md): ready-made solutions to common design problems.
* [Devices](DEVICES.md): connecting eye trackers, EEG and physiology.
* [MCP](MCP.md): let Claude build experiments from a description.

## The five ideas behind EDGE

1. A **routine** is one screen or event sequence (a trial, instructions, feedback). It contains
   **components** (text, images, sounds, key presses, gaze areas, markers …) placed on a timeline.
2. The **flow** puts routines in order. **Loops** repeat routines over a **trial list** whose columns
   become variables (`$word`, `$ink`). **Branches** and **workflows** decide what happens next.
3. Any value starting with **`$`** is an **expression**, computed while the experiment runs:
   `$word`, `$resp.rt < 0.5`, `$f'Score: {score}'`.
4. **Devices** (eye trackers, EEG, physiology, LSL, TTL) are recorded and synchronized automatically.
   A component's **marker** reaches all of them at the moment the stimulus appears.
5. Everything is a plain **YAML file**, readable and versionable. The builder, the command line and
   Claude all edit the same file.
