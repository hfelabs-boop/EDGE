# Task library: operational adaptations (defence human factors)

Human-factors research for operators in defence settings (operator selection, workload, display design, training)
often needs the classic paradigms, but with stimuli that look like the operator's work: tracks on a tactical map
instead of letters, vehicles in a camera picture, emitters on a waterfall display. The task library therefore has
**operational adaptations**: for a library task, a version with the **same paradigm, design, timing, response
mapping and measures**, whose pictures, wording and screen layout come from operator consoles.

They remain research on people's attention, memory and decisions at consoles. Everything in them is **generic and
fictional**: "Track 0417", "Sector BRAVO", "high-threat pulsed emitter". There are no real weapons data, platforms,
units, places, call signs, frequencies or signal parameters, and no instructions for real operations. All pictures
and videos are drawn by a script (no photographs).

An adaptation's id is the base task's id with `_ops` (the first one is `search_ops`, visual search). In the
builder's **Task library** they have their own entry, **Operational adaptations**, with a filter by display theme;
the classic task's card links to its adaptation (*Operational version: C2 · UAV · EW · Video*).

## The four display themes

Every adaptation supports at least two of these themes. One variable, `theme`, chooses the theme.

| theme | operator role | what the screen looks like |
|---|---|---|
| `c2` | command and control | a tactical map or radar-style plot with track symbols (below), track numbers, a message / status panel, alerts |
| `uav` | UAV payload operator | a camera picture (still frame or synthetic video) seen from above, a reticle at the centre, telemetry text (ALT / HDG / SPD), targets marked with rounded-rectangle boxes |
| `ew` | electronic-warfare operator | a spectrum display and a waterfall (time runs downwards), emitter traces, signal kinds (pulsed vs continuous), threat-level colours |
| `video` | video interface | a camera feed with a crosshair and rounded-rectangle target markers in states (candidate, selected, confirmed, cleared) |

The theme changes what the participant sees and the words of the instructions, never the design: the trial lists,
timing, keys, correct answers and declared measures are the same in every theme (and the same as in the classic
task). Results from different themes can therefore be compared directly (the theme is recorded in
`session.json`'s variables, and an adaptation can also put it in the trial data, as `search_ops` does with
`layout.shown_theme`).

## Symbols and colours

Track symbols follow the common symbology convention in a simplified, generic form: the **frame shape and colour**
give the affiliation, the **icon inside** gives the kind of track.

| affiliation | frame | colour |
|---|---|---|
| friendly | rectangle (wider than high) | light blue `#80e0ff` |
| hostile | diamond | light red `#ff8080` |
| neutral | square | light green `#aaffaa` |
| unknown | quatrefoil (four lobes) | light yellow `#ffff80` |

Icons: **air** (a swept-wing chevron), **surface** (a hull), **ground** (a rounded vehicle outline). Every
affiliation x icon exists at 32, 48 and 64 pixels with a transparent background.

Target boxes and point markers come in four states: **candidate** (amber `#ffc400`, dashed), **selected** (cyan
`#00e5ff`, with a small tab), **confirmed** (red `#ff3b30`, thick, with corner ticks), **cleared** (green
`#34c759`, thin, half transparent). Threat colours (EW): high `#ff3b30`, medium `#ffb000`, low `#3ad0ff`.

## Using an adaptation

**Builder.** Home › **Task library** › **Operational adaptations** (or search, e.g. *UAV*). **Use this task** first
asks for the display theme (the default is listed first), then for a name; the new experiment starts in that
theme. To switch later, change the variable `theme` (Settings › Variables, or the first line of `variables:` in
the file) to another of the task's themes; the card lists them. The preview and the storyboard show the current
theme.

**Command line.**

```bash
edge library list --domain defense              # all operational adaptations
edge library list --domain defense --theme uav  # those with a UAV theme
edge library list --domain none                 # only the classic tasks
edge library show search_ops                    # what each stimulus stands for, themes, references
edge library new search_ops --theme ew          # a copy that starts in the EW theme
```

**With Claude (MCP).** `list_library(domain="defense", theme="uav")` and
`create_from_library(task="search_ops", theme="uav")`.

Run a **Test run** in the theme you will use. A copy holds everything it needs (pictures, videos, trial lists).

## How theme switching works inside a task

Open `edge/library/tasks/search_ops/search_ops.yaml`: it is the reference pattern, with comments. Two mechanisms:

1. **Stimuli are data.** A variable (in `search_ops`: `looks`) maps each theme to its pictures and drawing
   settings. The trial is planned in theme-free terms (which place holds the target, which holds which kind of
   distractor), and each picture item looks its file up for the current theme:

   ```yaml
   variables:
     theme: c2                     # the first variable: c2, uav, ew or video
     looks:
       c2:  {target: [stimuli/hostile_air_48.png], other_colour: [stimuli/friendly_air_48.png], …}
       uav: {target: [stimuli/vehicle_tracked_light.png], …}
   …
   - {id: item0, type: image, image: "$looks[theme][kinds[0]][picks[0]]", size: "$looks[theme]['size']", …}
   ```

   One set of items serves every theme, and the builder's preview shows the current theme's pictures.

2. **The display around the stimuli is guarded.** Backgrounds, reticles, telemetry, status lines and the
   instruction texts are items with a condition, one per theme where needed:

   ```yaml
   - {id: camera_uav, type: image, if: "$theme == 'uav'", image: $camera, size: [1280, 720]}
   - {id: tel_uav, type: text, if: "$theme == 'uav'", text: "$f'ALT {alt} m   HDG {hdg:03d}   SPD {spd} kt'", …}
   - {id: text_ew, type: text, if: "$theme == 'ew'", text: "You are monitoring the waterfall display …"}
   ```

   Conditions are worked out when the screen starts; the builder's preview leaves out the other themes' items.

Where a theme needs different trial lists (rare: the design should stay the same), name the file by theme
(`conditions: $f'trials_{theme}.csv'`); validation then checks those files more leniently, so prefer one list.

## Making a new adaptation

1. **Folder.** `edge/library/tasks/<id>_ops/` with `<id>_ops.yaml`, `meta.yaml`, the trial list(s) and `stimuli/`.
   Start from the base task (`edge library new <id>`) and from `search_ops` as the pattern.
2. **Keep the paradigm.** Same structure (instructions, practice with feedback where the base has it, main
   block(s), thanks), same trial lists and columns (conditions and `correct_key`), same timing and keys, same
   `measures:` (ids, columns, summaries). Only stimuli, wording and display change.
3. **Theme variable.** `theme: <default>` as the first entry of `variables:` (two-space indent, so
   `edge library new --theme` can set it). Support at least two themes; every theme must validate with 0 errors
   and pass a test run.
4. **Pictures.** Take them from the kit (below). Write a generator `tools/library/make_<id>_ops.py` that copies the
   kit files the task needs into its `stimuli/` with `kit_copy.copy_from_kit(...)` (see `make_search_ops.py`) and
   draws any task-specific pictures (Pillow). Keep the task small: copy only what it shows; one or two videos at
   most.
5. **Wording.** Plain operator-style instructions in your own words ("You are monitoring a sensor feed …"). Say
   which keys mean what, and which items do not count.
6. **meta.yaml.** As for every task (see [the task library](../LIBRARY.md#contributing-a-task)), plus:

   ```yaml
   id: stroop_ops
   title: Stroop task (operational)
   category: Inhibition and conflict        # the base task's category
   variant_of: stroop                       # required for an adaptation
   domain: defense
   themes: [c2, ew]                         # the default (the file's `theme`) first; at least two
   adaptation: >
     One paragraph: what each stimulus stands for operationally, per theme.
   references: [ the base task's papers, plus human-factors work that used the paradigm with operators
                 (only real, verifiable citations) ]
   ```

   `edge library list` leaves out (with a message) an adaptation whose `domain`, `themes` or `adaptation` is missing
   or wrong, whose `variant_of` is missing, or whose experiment's `theme` is not the first of `themes`.
7. **Tests.** Validate and dry-run the task in every theme: copy it with `copy_task(id, folder, theme=…)` (or
   `edge library new <id> --theme …`) and run `edge run <copy> --dry-run`; check that the measures appear in
   `measures.csv`. `tests/test_library_defense_kit.py` shows how.

## The stimulus kit

`edge/library/defense_kit/` holds the shared pictures and videos; its index **`kit.yaml`** lists every file with a
short description, its size and the theme it is meant for, plus the colour palette and two text recipes. The kit is
made by `python tools/library/make_defense_kit.py` (Pillow, numpy and ffmpeg with libx264; every run gives the same
files). About 3 MB in all. The kit is part of EDGE's source repository (for people who make adaptations); the
installed package carries only the task folders, which hold copies of the kit files they use.

| folder | contents | themes |
|---|---|---|
| `backgrounds/` | radar-style tactical plot and map grid (1280x720 and 800x800), spectrum display, empty waterfall | c2, ew |
| `terrain/` | six synthetic camera frames 1280x720 seen from above: farmland, village, forest, river, an infrared ("white-hot") frame, a hazy dusk frame | uav, video |
| `waterfall/` | five waterfall frames with made-up emitter patterns: continuous, pulsed, short bursts, sweeps, mixed | ew |
| `video/` | four 10-second looping camera feeds, 640x360, H.264 without B-frames (`-bf 0`), about 120-150 kB each: pan, zoom, infrared orbit, and one with vehicles driving along roads | uav, video |
| `symbols/` | friendly / hostile / neutral / unknown x air / surface / ground, 32, 48 and 64 px | c2 |
| `vehicles/` | generic vehicles seen from above (tracked, wheeled, car) in light (hot) and dark (cold), 48 px | uav, video |
| `emitters/` | waterfall emitter marks: pulsed (dashed) and continuous (solid) in high / medium / low threat colours | ew |
| `reticles/` | three reticles (cross, corner brackets, ring), 240 px, and a full-screen crosshair 1280x720 | uav, video |
| `boxes/` | rounded-rectangle target boxes in the four states (64, 96, 128 px) and round point markers (64 px) | uav, video |
| `panels/` | a message / status panel background 400x240 | all |

Two things are **recipes** (text items, not pictures), so their numbers and messages can change during a session:
the **telemetry overlay** (monospace text in the corners: `ALT … m  HDG …  SPD … kt`, sensor, track number) and the
**message panel** (the panel picture with a header and message lines). Their items are in `kit.yaml` under
`recipes:`; paste them into a screen and set the variables they name.

The spectrum and waterfall pictures have their data area at pixels x 70-1250, y 50-690 (from the top left of the
1280x720 picture; `plot_area` in `kit.yaml`), which is x -570 to 610, y 310 to -330 in EDGE's centred pixel
coordinates. Channels are labelled CH 0-100 in relative units: they are not real frequencies.

## Adaptations of decision, language, motor and problem-solving tasks

Fourteen adaptations keep the design, keys and measures of their classic task and change only what the stimuli
stand for. The first theme listed is the default.

| adaptation | themes | what the operator sees |
|---|---|---|
| `bart_ops` | c2, uav | Keeps a patrol or a surveillance air vehicle on station pass by pass for coverage points. The datalink can be lost at any pass, like the balloon's burst. |
| `igt_ops` | c2, uav | Chooses among four patrol routes or sensor packages A-D with the hidden payoff schedules of the four decks. |
| `iat2_ops` | c2, ew | Sorts Own systems vs Other systems (friendly vs hostile track symbols, or named emitters) and Reliable vs Unreliable status words. The categories are about systems only. |
| `ldt_ops` | c2, uav | Decides whether a string in an incoming message line is a real message word or a malformed one. |
| `pacedreading1_ops`, `pacedreading2_ops`, `pacedreading3_ops` | c2, uav | Reads short fictional situation reports and orders (subject- vs object-relative) on a message terminal, then answers a question about each. |
| `mentalrotation_ops` | c2, uav | Judges same vs mirrored for area outlines on the plot or vehicles seen from above. |
| `deary_liewald_ops` | c2, video | Responds to an alert in one of four places: a hostile track in a sector panel, or a target box on a camera feed turning red. |
| `digit_substitution_ops` | c2, ew | Types the code of each track symbol or emitter mark, using a code table. |
| `fitts_ops` | uav, video | Moves the cursor from the reticle's centre onto rounded-rectangle target boxes of different widths and distances. |
| `tower_hanoi_ops` | c2, uav | Re-orders a stack of tasked assets (or waiting air vehicles) between three holding points under the Tower of Hanoi rules. |
| `vaast_words_ops` | c2, uav | Approaches or avoids status words that signal safety or threat, moving into a console display or through a camera. |
| `vaast_images_ops` | c2, uav | Approaches or avoids friendly vs hostile track symbols, or vehicles that the tracker has boxed as cleared or hostile. |

Their pictures are kit copies plus a few drawn for the task by its generator: the IAT's numbered tracks, the
rotation shapes and vehicles, the hopping emitter marks, the Fitts target boxes and the VAAST pictures. Each
generator is `tools/library/make_<id>.py`; the three reading tasks share `make_reading_ops.py`. The tests are in
`tests/test_library_ops_decision.py`.
