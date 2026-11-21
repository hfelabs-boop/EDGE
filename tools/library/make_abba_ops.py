"""Make the stimuli of abba_ops, the operational adaptation of the ABBA task (edge/library/tasks/abba_ops/).

    python tools/library/make_abba_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and copies the classic task's trial list unchanged (its blue / yellow circle colours match the pictures below).
The planned order (response A) is an arrow in a text item. Re-run it after re-making the kit.

Per theme (response B: F / J), as in abba_ops.yaml's `looks`:
  c2  friendly air track (blue) / unknown air track (yellow)                      on the radar-style plot
  ew  low-threat pulsed emitter (blue) / medium-threat pulsed emitter (amber)      on the waterfall
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "abba_ops"

KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "symbols/friendly_air_64.png", "symbols/unknown_air_64.png",
    "backgrounds/waterfall_1280x720.jpg", "emitters/emitter_pulsed_low.png", "emitters/emitter_pulsed_medium.png",
]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    copy_lists(TASK, "abba", {"abba.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
