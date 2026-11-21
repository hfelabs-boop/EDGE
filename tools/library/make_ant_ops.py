"""Make the stimuli of ant_ops, the operational adaptation of the Attention Network Test (edge/library/tasks/ant_ops/).

    python tools/library/make_ant_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder, draws the heading pictures that stand
for the arrows (ops_attention_pics.heading_pictures, the same as flanker_arrows_ops) and copies the classic task's
trial list unchanged. Re-run it after re-making the kit.

Per theme, as in ant_ops.yaml's `looks`:
  c2   hostile surface tracks with a course leader; the cue is an amber alert ring        on the map grid
  uav  light tracked vehicles with the tracker's motion vector; the cue is a cyan ring    on a camera frame
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists, heading_pictures

TASK = "ant_ops"

KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "terrain/terrain_04_river.jpg"]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES) + heading_pictures(TASK)
    copy_lists(TASK, "ant", {"ant.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} pictures ({size / 1e6:.2f} MB) and {TASK}.csv")
