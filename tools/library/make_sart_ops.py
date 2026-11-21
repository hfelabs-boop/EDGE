"""Make the stimuli of sart_ops, the operational adaptation of the SART (edge/library/tasks/sart_ops/).

    python tools/library/make_sart_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and copies the classic task's trial list unchanged (digit 1-9 x five sizes; the digit now picks the object, 3 is
the no-go object). Re-run it after re-making the kit. make_sart2_ops.py does the same for sart2_ops.

Per theme (the no-go object "3" / the eight go objects), as in sart_ops.yaml's `looks`:
  c2   friendly air track / hostile, unknown and neutral tracks                       on the radar-style plot
  uav  vehicle in a cleared (green) box / vehicles in candidate, selected and         on a camera frame
       confirmed boxes and point markers
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "sart_ops"

KIT_FILES = [
    # c2: radar-style plot and nine track symbols (64 px)
    "backgrounds/plot_radar_1280x720.png",
    "symbols/hostile_air_64.png", "symbols/hostile_surface_64.png", "symbols/friendly_air_64.png",
    "symbols/hostile_ground_64.png", "symbols/unknown_air_64.png", "symbols/unknown_surface_64.png",
    "symbols/unknown_ground_64.png", "symbols/neutral_air_64.png", "symbols/neutral_surface_64.png",
    # uav: a camera frame, reticle, target boxes and point markers in four states, vehicles
    "terrain/terrain_01_farmland.jpg", "reticles/reticle_cross.png",
    "boxes/box_confirmed_128.png", "boxes/box_candidate_128.png", "boxes/box_cleared_128.png",
    "boxes/box_selected_128.png", "boxes/ring_confirmed_64.png", "boxes/ring_candidate_64.png",
    "boxes/ring_selected_64.png",
    "vehicles/vehicle_tracked_light.png", "vehicles/vehicle_wheeled_light.png",
]


def make(task: str, base: str) -> None:
    copied = copy_from_kit(task, KIT_FILES)
    copy_lists(task, base, {f"{base}.csv": f"{task}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {task}.csv")


if __name__ == "__main__":
    make(TASK, "sart")
