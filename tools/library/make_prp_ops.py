"""Make the operational adaptation of the psychological refractory period task (edge/library/tasks/prp_ops/).

    python tools/library/make_prp_ops.py

The two tasks of the classic PRP paradigm become a radio message and a track alert that arrive close together:
task 1, the tone (low = A, high = S), is the radio channel's call tone (routine / priority message); task 2, the
letter (X = K, O = L), is an alert that pops up on the display:
  c2   a new air track on a radar plot: hostile (the classic X, K) or friendly (O, L)
  uav  a vehicle detected under the reticle of a camera frame: tracked (X, K) or wheeled (O, L)
The trial lists are the classic task's (tools/library/make_prp.py), copied unchanged: 2 tones x 2 alerts x 5 SOAs.
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

TASK, BASE = "prp_ops", "prp"
KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "symbols/hostile_air_64.png", "symbols/friendly_air_64.png",
    "terrain/terrain_03_forest.jpg", "reticles/reticle_circle.png",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_wheeled_light.png", "boxes/box_selected_96.png",
]


def main() -> None:
    copied = copy_from_kit(TASK, KIT_FILES)
    for name in ("trials.csv", "practice.csv"):
        shutil.copyfile(TASKS / BASE / name, TASKS / TASK / name)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), trials.csv and practice.csv from {BASE}")


if __name__ == "__main__":
    main()
