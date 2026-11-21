"""Make the stimuli of stopsignal_ops, the operational adaptation of the stop-signal task
(edge/library/tasks/stopsignal_ops/).

    python tools/library/make_stopsignal_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder, draws the heading pictures that stand
for the arrows (ops_attention_pics.heading_pictures) and copies the classic task's trial list unchanged. The stop
signal (a red ABORT frame and word) is drawn by shape and text items. Re-run it after re-making the kit.

Per theme, as in stopsignal_ops.yaml's `looks`:
  c2     a hostile surface track with a course leader                         on the radar-style plot
  video  a vehicle with the tracker's motion vector in a confirmed target box  on a camera feed video
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists, heading_pictures

TASK = "stopsignal_ops"

KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "video/feed_02_zoom.mp4", "reticles/crosshair_full_1280x720.png",
             "boxes/box_confirmed_128.png"]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES) + heading_pictures(TASK, ("left", "right"))
    copy_lists(TASK, "stopsignal", {"stopsignal.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} pictures ({size / 1e6:.2f} MB) and {TASK}.csv")
