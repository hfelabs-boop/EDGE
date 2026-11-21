"""Make the stimuli of cueing_ops, the operational adaptation of spatial cueing (edge/library/tasks/cueing_ops/).

    python tools/library/make_cueing_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and copies the classic task's trial list unchanged. Re-run it after re-making the kit. make_endo_exo_cueing_ops.py
and make_ior_ops.py use the same pictures (make() below).

Per theme, as in cueing_ops.yaml's `looks`:
  c2   two sensor sectors (outlined boxes) on a radar-style plot; the target is a new unknown air contact
  uav  two candidate boxes on a camera frame under a reticle; the target is a vehicle appearing in one of them
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "cueing_ops"

KIT_FILES = [
    # c2: radar-style plot, the contact symbol
    "backgrounds/plot_radar_1280x720.png", "symbols/unknown_air_48.png",
    # uav: camera frame, reticle, candidate boxes, the vehicle
    "terrain/terrain_03_forest.jpg", "reticles/reticle_cross.png", "boxes/box_candidate_128.png",
    "vehicles/vehicle_tracked_light.png",
]


def make(task: str, base: str, lists: dict[str, str], kit_files: list[str] = KIT_FILES) -> None:
    copied = copy_from_kit(task, kit_files)
    copy_lists(task, base, lists)
    size = sum(p.stat().st_size for p in copied)
    print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {', '.join(lists.values())}")


if __name__ == "__main__":
    make(TASK, "cueing", {"cueing.csv": f"{TASK}.csv"})
