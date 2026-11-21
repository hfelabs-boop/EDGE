"""Make the stimuli and problem list of tower_hanoi_ops, the operational adaptation of the Tower of Hanoi
(edge/library/tasks/tower_hanoi_ops/).

    python tools/library/make_tower_hanoi_ops.py

Copies the defence-kit backgrounds the task shows into its stimuli/ folder and writes hanoi_problems.csv (the same
problems as the classic `tower_hanoi`: 3 disks, 4 disks, 4 disks to the middle). The stacks, the assets and their
labels are drawn by shape and text items in tower_hanoi_ops.yaml; per theme:
  c2   three holding points on the tactical map; the disks are tasked assets (cards of four sizes)
  uav  three waypoints on the camera picture; the disks are air vehicles waiting in a stack
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK = "tower_hanoi_ops"
KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "terrain/terrain_04_river.jpg"]

if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    with open(TASKS / TASK / "hanoi_problems.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["title", "phase", "n_disks", "start_peg", "goal_peg", "min_moves"])
        for i, (n, goal) in enumerate(((3, 2), (4, 2), (4, 1)), 1):
            w.writerow([f"Problem {i}", "test", n, 0, goal, 2 ** n - 1])
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and hanoi_problems.csv")
