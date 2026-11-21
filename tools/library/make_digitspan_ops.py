"""Make the stimuli of the operational digit-span adaptations (edge/library/tasks/{digitspan_ops, rdigitspan_ops}/).

    python tools/library/make_digitspan_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the tasks show into their own stimuli/ folders, so a copy of a task is self-contained. The
digit lists are drawn during the session (as in digitspan / rdigitspan), so there is no trial list to write.

  c2   the digits are a track number coming in on a message panel over the tactical map
  uav  the digits are a grid reference passed in the overlay of a camera frame, under a reticle
"""

from __future__ import annotations

from kit_copy import copy_from_kit

TASKS = ["digitspan_ops", "rdigitspan_ops"]

KIT_FILES = [
    "backgrounds/map_grid_1280x720.jpg", "panels/message_panel_400x240.png",      # c2
    "terrain/terrain_02_village.jpg", "reticles/reticle_cross.png",               # uav
]


if __name__ == "__main__":
    for task in TASKS:
        copied = copy_from_kit(task, KIT_FILES)
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
