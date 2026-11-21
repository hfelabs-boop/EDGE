"""Make the operational adaptation of multitasking (edge/library/tasks/multitasking_ops/).

    python tools/library/make_multitasking_ops.py

The frame of the classic task (top half: SHAPE task, bottom half: FILLING task) becomes two sensor feeds that the
operator monitors; a GROUP of 2 or 3 contacts of one kind appears in one feed. In the top feed the operator reports
the kind of the group (the classic shape: diamond = A, rectangle = L), in the bottom feed its size (the classic
dots: 2 = A, 3 = L):
  c2   top: AIR PICTURE, affiliation (hostile air tracks = A, friendly = L); bottom: GROUP SIZE; on a radar plot
  uav  top: CAMERA 1, vehicle type (tracked = A, wheeled = L); bottom: CAMERA 2, number of vehicles; two camera frames
The trial lists are the classic task's (tools/library/make_multitasking.py), copied unchanged; `shape` diamond /
rectangle stands for the two kinds and `dots` for the group size.
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

TASK, BASE = "multitasking_ops", "multitasking"
KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "symbols/hostile_air_48.png", "symbols/friendly_air_48.png",
    "terrain/terrain_01_farmland.jpg", "terrain/terrain_04_river.jpg",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_wheeled_light.png",
]
LISTS = ["practice_shape.csv", "shape.csv", "practice_filling.csv", "filling.csv", "practice_mixed.csv", "mixed.csv"]


def main() -> None:
    copied = copy_from_kit(TASK, KIT_FILES)
    for name in LISTS:
        shutil.copyfile(TASKS / BASE / name, TASKS / TASK / name)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), {len(LISTS)} trial lists from {BASE}")


if __name__ == "__main__":
    main()
