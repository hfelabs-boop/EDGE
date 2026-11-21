"""Make the stimuli of maabrams_ops, the operational adaptation of attentional capture and visual grouping
(edge/library/tasks/maabrams_ops/).

    python tools/library/make_maabrams_ops.py

Copies the defence-kit backgrounds the task shows into its own stimuli/ folder (so a copy of the task is
self-contained) and copies the classic task's trial list unchanged. The search display itself (contacts, the
hostile diamond, course lines, the link bar) is drawn by shape items, as in the classic task. Re-run it after
re-making the kit.

  c2     contacts around own position on a radar-style plot
  video  tracker markers around the crosshair on a camera feed video
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "maabrams_ops"

KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "video/feed_03_orbit_ir.mp4", "reticles/crosshair_full_1280x720.png"]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    copy_lists(TASK, "maabrams", {"maabrams.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
