"""Make the stimuli of ab_ops, the operational adaptation of the attentional blink (edge/library/tasks/ab_ops/).

    python tools/library/make_ab_ops.py

Copies the defence-kit backgrounds the task shows into its own stimuli/ folder (so a copy of the task is
self-contained) and copies the classic task's trial list unchanged (lag 1, 2, 3, 5, 6). The stream itself is
text (track identity codes / emitter codes in a readout window), drawn by text items. Re-run it after re-making
the kit.

  c2  identity readout over the radar-style plot
  ew  emitter-code readout over the waterfall
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "ab_ops"

KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "backgrounds/waterfall_1280x720.jpg"]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    copy_lists(TASK, "ab", {"ab.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
