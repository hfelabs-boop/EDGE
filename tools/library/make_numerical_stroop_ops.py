"""Make the operational adaptations of the numerical Stroop task
(edge/library/tasks/numerical_stroop_ops/ and numerical_stroop_touch_ops/).

    python tools/library/make_numerical_stroop_ops.py

The two digits of the classic size-congruity task become two COUNTS shown side by side on an operator display, and
the operator reports which count is numerically larger, ignoring the print size:
  c2   hostile tracks reported in sector ALPHA (left) and sector BRAVO (right), on the map grid
  ew   emitters detected in band A (left) and band B (right), on the spectrum display
The trial lists are the classic task's (made by tools/library/make_numerical_stroop.py), copied unchanged, so the
design (congruent / incongruent / neutral x distance 1 or 5), keys and answers are the same.
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

KIT_FILES = ["backgrounds/map_grid_1280x720.jpg", "backgrounds/spectrum_1280x720.png"]
PLAN = {"numerical_stroop_ops": "numerical_stroop", "numerical_stroop_touch_ops": "numerical_stroop_touch"}


def main() -> None:
    for task, base in PLAN.items():
        copied = copy_from_kit(task, KIT_FILES)
        for name in ("trials.csv", "practice.csv"):
            shutil.copyfile(TASKS / base / name, TASKS / task / name)
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB), trials.csv and practice.csv from {base}")


if __name__ == "__main__":
    main()
