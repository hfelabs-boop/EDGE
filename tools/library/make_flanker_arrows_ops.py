"""Make the stimuli of flanker_arrows_ops, the operational adaptation of the arrow flanker task
(edge/library/tasks/flanker_arrows_ops/).

    python tools/library/make_flanker_arrows_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder, draws the heading pictures that stand
for the arrows (ops_attention_pics.heading_pictures: a track or vehicle heading left, heading right, or not moving
for the neutral flankers) and copies the classic task's trial list unchanged. Re-run it after re-making the kit.

Per theme, as in flanker_arrows_ops.yaml's `looks`:
  c2   hostile surface tracks with a course leader (left / right; none = no leader)   on the map grid
  uav  light tracked vehicles with the tracker's motion vector (none = parked)    on a camera frame
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists, heading_pictures

TASK = "flanker_arrows_ops"

KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "terrain/terrain_02_village.jpg", "reticles/reticle_brackets.png"]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES) + heading_pictures(TASK)
    copy_lists(TASK, "flanker_arrows", {"flanker_arrows.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} pictures ({size / 1e6:.2f} MB) and {TASK}.csv")
