"""Make the stimuli of dotprobe_ops, the operational adaptation of the dot-probe task (edge/library/tasks/dotprobe_ops/).

    python tools/library/make_dotprobe_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder and writes the trial lists: the classic
task's lists (dotprobe.csv: 20 threat/neutral pairs x threat top/bottom x probe top/bottom = 80 rows;
practice.csv: 4 neutral pairs x 4 = 16 rows) with the word columns replaced by the pair's number (`pair`, 0-19),
which picks the two pictures in dotprobe_ops.yaml's `looks`. Re-run it after re-making the kit.

Per theme (threat / neutral; practice pairs: two neutral kinds):
  c2   hostile air, surface or ground track / neutral air, surface or ground track         on the map grid
       (practice: friendly track / neutral track)
  uav  light or dark tracked (armoured) vehicle / light or dark civilian car               on a camera frame
       (practice: wheeled vehicle / civilian car)
"""

from __future__ import annotations

import csv
from pathlib import Path

from kit_copy import TASKS, copy_from_kit

TASK = "dotprobe_ops"

KIT_FILES = [
    # c2: map grid and track symbols (64 px)
    "backgrounds/map_grid_1280x720.jpg",
    "symbols/hostile_air_64.png", "symbols/hostile_surface_64.png", "symbols/hostile_ground_64.png",
    "symbols/neutral_air_64.png", "symbols/neutral_surface_64.png", "symbols/neutral_ground_64.png",
    "symbols/friendly_air_64.png", "symbols/friendly_surface_64.png", "symbols/friendly_ground_64.png",
    # uav: camera frame and vehicles
    "terrain/terrain_02_village.jpg",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_tracked_dark.png",
    "vehicles/vehicle_car_light.png", "vehicles/vehicle_car_dark.png",
    "vehicles/vehicle_wheeled_light.png", "vehicles/vehicle_wheeled_dark.png",
]

KEEP = ["pair_type", "pair", "threat_pos", "probe_pos", "congruence", "probe_y", "correct_key"]


def trial_list(src: Path, dst: Path) -> None:
    """The classic list with the words replaced by the pair's number (in order of first appearance)."""
    with open(src, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    pairs: dict[tuple[str, str], int] = {}
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(KEEP)
        for r in rows:
            r["pair"] = pairs.setdefault((r["threat_word"], r["neutral_word"]), len(pairs))
            w.writerow([r[k] for k in KEEP])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    trial_list(TASKS / "dotprobe" / "dotprobe.csv", TASKS / TASK / f"{TASK}.csv")
    trial_list(TASKS / "dotprobe" / "practice.csv", TASKS / TASK / "practice.csv")
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), {TASK}.csv and practice.csv")
