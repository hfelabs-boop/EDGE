"""Make the stimuli of the operational Corsi adaptations (edge/library/tasks/{corsi_ops, corsi2_ops,
backward_corsi_ops}/).

    python tools/library/make_corsi_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the tasks show into their own stimuli/ folders, so a copy of a task is self-contained. The
sequences are drawn during the session (as in corsi / corsi2 / backward_corsi), so there is no trial list to write.
The nine places keep the classic layout; they are drawn as shapes (so they are clickable) over:

  c2   the map grid: the places are waypoints (dark squares with a friendly-blue outline; amber when lit)
  uav  a camera frame of a forest: the places are candidate boxes (amber outline; cyan when the sensor visits)
"""

from __future__ import annotations

from kit_copy import copy_from_kit

TASKS = ["corsi_ops", "corsi2_ops", "backward_corsi_ops"]

KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "terrain/terrain_03_forest.jpg"]


if __name__ == "__main__":
    for task in TASKS:
        copied = copy_from_kit(task, KIT_FILES)
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
