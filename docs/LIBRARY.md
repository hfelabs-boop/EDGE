# The task library

EDGE comes with a **task library**: ready-made, tested versions of the classic paradigms of experimental
psychology (Stroop, flanker, Simon, go/no-go, stop-signal, n-back, Corsi blocks, Posner cueing, the Iowa gambling
task, the implicit association test …). Each task is a complete experiment: plain-language instructions, a practice
block with feedback where the paradigm normally has one, the main block(s) with the usual numbers of trials and
timing, and a thank-you screen. Its measures (the paradigm's main outcomes, such as the Stroop effect) are
declared, so the session summary and `measures.csv` show them straight away.

Use a task as it is, or as the starting point for your own study: you get your own copy, and you can change
anything in it.

## Starting from a task

**In the builder.** On **Home**, choose **Task library** (next to *Start from an example*; also in the examples
gallery and in **Ctrl+K**). Pick a category on the left or search (*Stroop*, *memory*, *touch* …). Each card says
what the task does, how long it takes, how participants answer (keyboard, mouse or touch screen), what it measures
and which papers it comes from; **More** shows the full description and the references, and **See also
PsyToolkit** opens PsyToolkit's page about the same paradigm. **Use this task** asks for a name and creates the
experiment in your experiments folder, then opens it; **Use and try it** also starts *Try it* at once, so you can
do the task yourself.

**On the command line.**

```bash
edge library list                         # every task, by category
edge library list --category memory       # one category (the start of its name is enough)
edge library list --search "go no-go"     # tasks that mention all these words
edge library list --input touch           # tasks for touch screens (also: keyboard, mouse, keyboard+mouse)
edge library show flanker                 # what it does, measures, references
edge library new flanker                  # copy it into ./flanker/ (never over anything: ./flanker_2/ …)
edge library new flanker studies --name flanker_pilot
```

**With Claude (MCP).** `list_library` lists the tasks (with the same filters) and `create_from_library` copies one
into the workspace. The builder's assistant knows about the library too and suggests it when you ask for a classic
task.

## What you get

A new folder with:

* `<name>.yaml`: the experiment (the first line says which library task it came from);
* its pictures and sounds (`stimuli/`) and trial-list files, if it has any;
* `CITATION.md`: what to cite (see below).

Nothing in your experiments folder is ever overwritten: if a folder of that name exists, the copy gets the next
free name (`flanker_2`). Run a **Test run** first; it should pass without changes.

## Adapting a task

Everything is ordinary EDGE: open the copy in the builder and change what you need.

* **Number of trials**: the trial list's *Repeats* (or the rows of its table). Practice and main blocks are separate
  trial lists.
* **Timing**: each screen's items (fixation, stimulus, response window) show their start and duration on the
  timeline; many tasks keep the main timings in variables (Settings › Variables) so you change them in one place.
* **Keys or touch**: the response item's keys and correct answers. The correct answer and the condition of each
  trial are columns of the trial list, so the data has condition labels and `corr` for every trial. Touch-screen
  versions use tap targets instead of keys.
* **Texts and language**: the instruction and feedback screens are plain text items. Some tasks have versions in
  other languages (the card lists the languages).
* **Measures**: the *Measures* page lists what the task measures; add your own (a covariate, a check).

Say in your methods which version you ran (numbers of trials, timing, keys) and what you changed.

## Operational adaptations (defence human factors)

For research with operators (selection, workload, display design, training), some tasks have an **operational
adaptation** (id `<task>_ops`, e.g. `search_ops`): the same paradigm, design and measures, with stimuli and wording
from operator consoles in one of four **display themes**, chosen by the variable `theme`: `c2` (tactical map with
track symbols), `uav` (camera view with reticle and telemetry), `ew` (spectrum and waterfall) and `video` (camera
feed with crosshair and target boxes). Everything in them is synthetic and fictional. In the builder they are under
**Operational adaptations** in the Task library (**Use this task** asks for the theme); on the command line
`edge library list --domain defense --theme uav` and `edge library new search_ops --theme uav`. The classic task's
card links to its adaptation. See [Operational adaptations](library/DEFENSE.md) for the themes, the symbol
conventions, the shared stimulus kit and how to make a new adaptation.

## Citing a task

Each task names the original papers it implements (on its card, in `edge library show <id>` and in the copy's
`CITATION.md`). When you use a task, cite those papers for the paradigm, as you would for any implementation,
and describe your version in the methods.

## EDGE's own implementations, and PsyToolkit

The tasks are **EDGE's own implementations**, written for EDGE from the published method of each paradigm (the
cited papers and the common knowledge of the paradigm), with their own instructions and their own pictures and
sounds. They are covered by EDGE's licence (MIT).

The choice of paradigms follows the experiment library of [PsyToolkit](https://www.psytoolkit.org), Prof. Gijsbert
Stoet's free platform for online and lab experiments, which has a page with background and references for each
paradigm. Each EDGE task links to the matching PsyToolkit page (*See also PsyToolkit*) as further reading. EDGE does
not contain PsyToolkit's scripts, texts or pictures: PsyToolkit's library code is available to registered users (a
free account) for non-commercial use. If you want to run PsyToolkit's own version of a task in EDGE, download it
from your PsyToolkit account and import the zip (see [Importing](IMPORT.md#psytoolkit-zip-psy));
PsyToolkit's terms then apply to it.

## Contributing a task

A task is one folder, `edge/library/tasks/<id>/` (`<id>`: lower-case letters, digits and `_`, e.g. `go_no_go`):

```
edge/library/tasks/go_no_go/
  go_no_go.yaml      the experiment
  meta.yaml          what it is (below)
  stimuli/           pictures and sounds you made yourself (optional)
```

`meta.yaml`:

```yaml
id: go_no_go                          # the folder's name
title: Go/no-go task
category: Inhibition and conflict     # Attention, Inhibition and conflict, Cognitive control, Working memory,
                                      # Vigilance, Decision making, Language, Social and implicit,
                                      # Perception and motor, Problem solving
summary: Press for one kind of picture, hold back for the other.
description: >
  One paragraph in your own words: what it measures, the design (trials, conditions, timing) and the main outcome.
measures: ["commission errors (no-go trials)", "go reaction time"]
duration_min: 5
input: keyboard                       # keyboard, mouse, touch or keyboard+mouse
languages: [en]
variant_of: go_no_go                  # only for a phone/touch or language version of another task
references: ["Author, A. (Year). Title. Journal, volume, pages."]
see_also: {psytoolkit: "https://www.psytoolkit.org/experiment-library/go_no_go.html"}
notes: optional limits ("uses a code item for the scoring rule")
```

An operational adaptation adds `domain: defense`, `themes: [c2, uav, …]` (the default first) and `adaptation:` (one
paragraph), and needs `variant_of`; see *Making a new adaptation* in [Operational adaptations](library/DEFENSE.md).

Before you send it:

* `edge validate` shows 0 errors and 0 warnings, and `edge run <file> --dry-run` passes;
* `measures:` declares the paradigm's main outcomes; conditions and correct answers are trial-list columns;
* there are instructions, practice (where usual), the main block(s) and an end screen; 3 to 10 minutes;
* every text, picture and sound is your own (write instructions in your own words; draw pictures with a script and
  commit it as `tools/library/make_<id>.py` so they can be made again); facts such as timings from papers are fine;
* `edge library list` shows the task (a `meta.yaml` that does not follow the format is left out with a warning
  that says what to fix); `EDGE_LIBRARY_DIR=<folder of task folders> edge library list` tries tasks that are not
  in EDGE yet.

The library ships with EDGE (the task folders are part of the package), so a new task appears in the builder,
the command line and MCP after an update.
