"""Make the stimuli of go_no_go_ops, the operational adaptation of the go/no-go task (edge/library/tasks/go_no_go_ops/).

    python tools/library/make_go_no_go_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and writes its trial list (the classic task's design: 3 go rows, 1 no-go row; the letter column is
left out, since the picture of each trial type depends on the theme). Re-run it after re-making the kit.

Per theme (go / no-go), as in go_no_go_ops.yaml's `looks`:
  c2     hostile air track (engage)           / friendly air track (hold)          on the radar-style plot
  video  vehicle in a confirmed (red) box     / vehicle in a cleared (green) box   on a camera feed video
"""

from __future__ import annotations

import csv
from pathlib import Path

from kit_copy import TASKS, copy_from_kit

TASK = "go_no_go_ops"

KIT_FILES = [
    # c2: radar-style plot and two track symbols (64 px)
    "backgrounds/plot_radar_1280x720.png", "symbols/hostile_air_64.png", "symbols/friendly_air_64.png",
    # video: camera feed, full-screen crosshair, target boxes, vehicles
    "video/feed_01_pan.mp4", "reticles/crosshair_full_1280x720.png",
    "boxes/box_confirmed_96.png", "boxes/box_cleared_96.png",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_wheeled_light.png",
]


def trial_list(path: Path) -> None:
    """3 go rows and 1 no-go row (75% go), as in `go_no_go`."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["trial_type", "correct_key"])
        for _ in range(3):
            w.writerow(["go", "space"])
        w.writerow(["nogo", "none"])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    trial_list(TASKS / TASK / f"{TASK}.csv")
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
