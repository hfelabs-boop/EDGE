"""Make the operational adaptations of the Simon task (edge/library/tasks/simon_ops/ and touch_simon_ops/).

    python tools/library/make_simon_ops.py

The blue and orange circles of the classic task become two kinds of contact that appear left or right of the
centre; the operator classifies the contact (left hand / left button for one kind, right for the other) and
ignores where it appears:
  c2   friendly air track (classic "blue") or hostile air track ("orange") left or right of own ship on a radar plot
  uav  light wheeled vehicle ("blue") or light tracked vehicle ("orange") left or right of the reticle in a camera frame
The trial lists are the classic task's, copied unchanged (colour, side, x, correct answer, condition).
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "symbols/friendly_air_64.png", "symbols/hostile_air_64.png",
    "terrain/terrain_01_farmland.jpg", "terrain/terrain_05_farmland_ir.jpg", "reticles/reticle_cross.png",
    "vehicles/vehicle_wheeled_light.png", "vehicles/vehicle_tracked_light.png",
]
PLAN = {"simon_ops": "simon", "touch_simon_ops": "touch_simon"}


def main() -> None:
    for task, base in PLAN.items():
        copied = copy_from_kit(task, KIT_FILES)
        shutil.copyfile(TASKS / base / "trials.csv", TASKS / task / "trials.csv")
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB), trials.csv from {base}")


if __name__ == "__main__":
    main()
