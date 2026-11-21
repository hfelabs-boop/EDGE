"""Make the stimuli of bart_ops, the operational adaptation of the BART (edge/library/tasks/bart_ops/).

    python tools/library/make_bart_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the task shows into its own stimuli/ folder, so a copy of the task is self-contained. The
BART has no trial list file (30 sorties of a one-row list, as in `bart`). Re-run it after re-making the kit.

Per theme (what stands for the balloon), as in bart_ops.yaml:
  c2   a friendly air patrol on the map; its coverage area (blue ellipse) grows with every extra pass
  uav  the aircraft's camera picture under a reticle; the surveyed area (cyan box) grows with every extra orbit
"""

from __future__ import annotations

from kit_copy import copy_from_kit

TASK = "bart_ops"

KIT_FILES = [
    # c2: map and the patrol's track symbol
    "backgrounds/map_grid_1280x720.jpg", "symbols/friendly_air_48.png",
    # uav: one camera frame and the reticle
    "terrain/terrain_03_forest.jpg", "reticles/reticle_brackets.png",
]

if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
