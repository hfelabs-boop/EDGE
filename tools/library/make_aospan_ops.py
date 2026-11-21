"""Make the stimuli of aospan_ops, the operational adaptation of the automated operation span task
(edge/library/tasks/aospan_ops/).

    python tools/library/make_aospan_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the task shows into its own stimuli/ folder, so a copy of the task is self-contained. The
problems and letter sets are drawn during the session (as in aospan), so there is no trial list to write.

  c2   fuel checks over a dimmed map grid; call-sign letters come in on a message panel over the map
  uav  time-on-station checks over a dimmed camera frame; call-sign letters come in a box over the camera frame
"""

from __future__ import annotations

from kit_copy import copy_from_kit

TASK = "aospan_ops"

KIT_FILES = [
    "backgrounds/map_grid_1280x720.jpg", "panels/message_panel_400x240.png",     # c2
    "terrain/terrain_04_river.jpg",                                              # uav
]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
