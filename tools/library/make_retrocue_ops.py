"""Make the stimuli of retrocue_ops, the operational adaptation of the retro-cue task (edge/library/tasks/retrocue_ops/).

    python tools/library/make_retrocue_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the task shows into its own stimuli/ folder, so a copy of the task is self-contained. The
trials are a factorial design in the experiment file (as in retrocue), so there is no trial list to write.

The contacts of each theme (the "colours" of the classic task; four different ones per trial):
  c2   eight track symbols: friendly / hostile / neutral / unknown x air / ground (64 px)     on the tactical plot
  uav  six vehicles seen from above: tracked / wheeled / car x light / dark                  on a dusk camera frame
  ew   six emitter traces: pulsed / continuous x high / medium / low threat                 on the spectrum display
The cue frames are the kit's "selected" target box (cyan rounded rectangle) in every theme.
"""

from __future__ import annotations

from kit_copy import copy_from_kit

TASK = "retrocue_ops"

KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png",
    *[f"symbols/{a}_{d}_64.png" for d in ("air", "ground") for a in ("friendly", "hostile", "neutral", "unknown")],
    "terrain/terrain_06_desert_dusk.jpg",
    *[f"vehicles/vehicle_{k}_{t}.png" for k in ("tracked", "wheeled", "car") for t in ("light", "dark")],
    "backgrounds/spectrum_1280x720.png",
    *[f"emitters/emitter_{k}_{t}.png" for k in ("pulsed", "continuous") for t in ("high", "medium", "low")],
    "boxes/box_selected_128.png",
]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
