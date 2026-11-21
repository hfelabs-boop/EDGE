"""Make the stimuli and trial list of igt_ops, the operational adaptation of the Iowa Gambling Task
(edge/library/tasks/igt_ops/).

    python tools/library/make_igt_ops.py

Copies the defence-kit pictures the task shows into its stimuli/ folder (so a copy of the task is self-contained)
and writes igt_trials.csv: 100 choices in 5 blocks of 20, the same list as the classic `igt`. The payoff schedules
are in igt_ops.yaml (variables gains / losses), unchanged from `igt`. Re-run it after re-making the kit.

Per theme (what the four decks stand for), as in igt_ops.yaml:
  c2   four routes A-D for a patrol, on the tactical map
  uav  four sensor packages A-D for the next tasking, over the camera picture
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK = "igt_ops"

KIT_FILES = [
    "backgrounds/map_grid_1280x720.jpg",                         # c2
    "terrain/terrain_02_village.jpg", "reticles/reticle_cross.png",  # uav
]


def trial_list(path) -> None:
    """100 choices, block = 1..5 (20 choices each), as in `igt`."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["trial", "block"])
        for t in range(1, 101):
            w.writerow([t, (t - 1) // 20 + 1])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    trial_list(TASKS / TASK / "igt_trials.csv")
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and igt_trials.csv")
