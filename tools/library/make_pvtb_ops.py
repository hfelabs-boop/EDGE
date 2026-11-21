"""Make the stimuli of the operational PVT-B adaptations (edge/library/tasks/{pvtb_ops, pvtb_touch_ops}/).

    python tools/library/make_pvtb_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files the tasks show into their own stimuli/ folders, so a copy of a task is self-contained. The
waits are drawn during the session (as in pvtb / pvtb_touch), so there is no trial list to write.

The alert that appears with the counter, per theme:
  c2   a new contact (unknown-air track symbol) on the tactical plot (wide plot for pvtb_ops, square for the phone)
  uav  a new confirmed target box in a camera frame, under a reticle
  ew   a new high-threat pulsed emitter on the spectrum display
"""

from __future__ import annotations

from kit_copy import copy_from_kit

ADAPTATIONS = {"pvtb_ops": "backgrounds/plot_radar_1280x720.png",
               "pvtb_touch_ops": "backgrounds/plot_radar_800x800.png"}

COMMON = [
    "symbols/unknown_air_64.png",                                                  # c2
    "terrain/terrain_01_farmland.jpg", "reticles/reticle_brackets.png", "boxes/box_confirmed_96.png",   # uav
    "backgrounds/spectrum_1280x720.png", "emitters/emitter_pulsed_high.png",       # ew
]


if __name__ == "__main__":
    for task, plot in ADAPTATIONS.items():
        copied = copy_from_kit(task, [plot, *COMMON])
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB)")
