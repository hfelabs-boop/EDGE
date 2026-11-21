"""Make the operational adaptation of the Dimensional Change Card Sort (edge/library/tasks/dccs_ops/).

    python tools/library/make_dccs_ops.py

The coloured shapes of the classic cards become contact reports that differ on two dimensions; the colour game
becomes sorting by the first dimension and the shape game sorting by the second:
            target left (blue triangle)  target right (red circle)  test cards (red triangle / blue circle)
  c2        friendly air track            hostile surface track      hostile air / friendly surface
            colour rule = AFFILIATION (hostile / friendly), shape rule = DOMAIN (air / surface)
  uav       dark tracked vehicle          light wheeled vehicle      light tracked / dark wheeled
            colour rule = SHADE (light / dark), shape rule = TYPE (tracked / wheeled)
The border game's black border becomes an amber PRIORITY frame. The trial lists are the classic task's
(tools/library/make_dccs.py) with the same rows and answers; only the `hint` column (the classic game names, shown
on screen) is left out, because the rule names now depend on the theme (variable `hints`).
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK, BASE = "dccs_ops", "dccs"
KIT_FILES = [
    "symbols/friendly_air_64.png", "symbols/hostile_surface_64.png", "symbols/hostile_air_64.png",
    "symbols/friendly_surface_64.png", "vehicles/vehicle_tracked_dark.png", "vehicles/vehicle_wheeled_light.png",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_wheeled_dark.png",
]
LISTS = ["practice.csv", "pre_switch.csv", "post_switch.csv", "border.csv"]


def main() -> None:
    copied = copy_from_kit(TASK, KIT_FILES)
    for name in LISTS:
        with (TASKS / BASE / name).open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        cols = [c for c in rows[0] if c != "hint"]
        with (TASKS / TASK / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, cols, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), {len(LISTS)} trial lists from {BASE}")


if __name__ == "__main__":
    main()
