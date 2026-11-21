"""Make the stimuli of search_ops, the operational adaptation of visual search (edge/library/tasks/search_ops/).

    python tools/library/make_search_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the task shows into its own stimuli/ folder, so a copy of the task is self-contained, and
writes its trial list (the same design as the classic `search` task). Re-run it after re-making the kit.

Per theme (target / same shape, other colour / same colour, other shape), as in search_ops.yaml's `looks`:
  c2     hostile air track / friendly or neutral air track / hostile ground track         on the map grid
  uav    light tracked vehicle / dark tracked vehicle / light wheeled vehicle             on camera frames
  ew     high-threat pulsed emitter / low-threat pulsed / high-threat continuous         on the waterfall
  video  confirmed (red) box / candidate (amber) box / confirmed (red) point marker      on a camera feed video
"""

from __future__ import annotations

import csv
from pathlib import Path

from kit_copy import TASKS, copy_from_kit

TASK = "search_ops"

KIT_FILES = [
    # c2: tactical map and track symbols (48 px)
    "backgrounds/map_grid_1280x720.jpg",
    "symbols/hostile_air_48.png", "symbols/friendly_air_48.png", "symbols/neutral_air_48.png",
    "symbols/hostile_ground_48.png",
    # uav: four camera frames (one infrared), vehicles, reticle
    "terrain/terrain_01_farmland.jpg", "terrain/terrain_02_village.jpg", "terrain/terrain_04_river.jpg",
    "terrain/terrain_05_farmland_ir.jpg",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_tracked_dark.png", "vehicles/vehicle_wheeled_light.png",
    "reticles/reticle_cross.png",
    # ew: waterfall and emitter marks
    "backgrounds/waterfall_1280x720.jpg",
    "emitters/emitter_pulsed_high.png", "emitters/emitter_pulsed_low.png", "emitters/emitter_continuous_high.png",
    # video: camera feed, full-screen crosshair, target boxes and point markers
    "video/feed_01_pan.mp4", "reticles/crosshair_full_1280x720.png",
    "boxes/box_confirmed_64.png", "boxes/box_candidate_64.png", "boxes/ring_confirmed_64.png",
]


def trial_list(path: Path) -> None:
    """search type x set size x target present/absent: 12 rows, M = present, Z = absent (as in `search`)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["search_type", "set_size", "target", "correct_key"])
        for kind in ("feature", "conjunction"):
            for n in (4, 8, 16):
                for present in ("present", "absent"):
                    w.writerow([kind, n, present, "m" if present == "present" else "z"])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    trial_list(TASKS / TASK / f"{TASK}.csv")
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
