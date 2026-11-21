"""Make the stimuli and trial lists of deary_liewald_ops, the operational adaptation of the Deary-Liewald reaction
time task (edge/library/tasks/deary_liewald_ops/).

    python tools/library/make_deary_liewald_ops.py

Copies the defence-kit pictures the task shows into its stimuli/ folder and writes the choice trial lists (the same
as the classic `deary_liewald`: four boxes, keys Z X N M). Per theme (box / what appears in it):
  c2     sector panels on the tactical plot / a hostile air track symbol (an alert)
  video  candidate target boxes (amber, dashed) on a looping camera feed with a crosshair / a confirmed target box
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK = "deary_liewald_ops"

KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "symbols/hostile_air_64.png",                                # c2
    "video/feed_04_vehicles.mp4", "reticles/crosshair_full_1280x720.png",                              # video
    "boxes/box_candidate_128.png", "boxes/box_confirmed_128.png",
]


def lists() -> None:
    for phase, name in (("practice", "choice_practice.csv"), ("test", "choice_test.csv")):
        with open(TASKS / TASK / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["task", "phase", "box", "xpos", "corr_key"])
            for box, x, key in ((1, -330, "z"), (2, -110, "x"), (3, 110, "n"), (4, 330, "m")):
                w.writerow(["choice", phase, box, x, key])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    lists()
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), choice_practice.csv and choice_test.csv")
