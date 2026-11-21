"""Make the stimuli of flanker_ops, the operational adaptation of the letter flanker task (edge/library/tasks/flanker_ops/).

    python tools/library/make_flanker_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and copies the classic task's trial list unchanged (its letters pick the objects). Re-run it after re-making the kit.

Per theme, the objects that stand for the letters (H, K: one key; S, C: the other; X: no answer), as in
flanker_ops.yaml's `looks`:
  c2   H hostile air, K hostile surface, S friendly air, C friendly surface, X neutral air track   on the map grid
  uav  H light tracked, K dark tracked, S light wheeled, C dark wheeled vehicle, X light car       on a camera frame
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "flanker_ops"

KIT_FILES = [
    # c2: map grid and five track symbols (64 px)
    "backgrounds/map_grid_1280x720.jpg",
    "symbols/hostile_air_64.png", "symbols/hostile_surface_64.png", "symbols/friendly_air_64.png",
    "symbols/friendly_surface_64.png", "symbols/neutral_air_64.png",
    # uav: camera frame, reticle, five vehicles
    "terrain/terrain_01_farmland.jpg", "reticles/reticle_brackets.png",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_tracked_dark.png", "vehicles/vehicle_wheeled_light.png",
    "vehicles/vehicle_wheeled_dark.png", "vehicles/vehicle_car_light.png",
]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    copy_lists(TASK, "flanker", {"flanker.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
