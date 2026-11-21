"""Make the stimuli of ax_cpt_ops, the operational adaptation of the AX-CPT (edge/library/tasks/ax_cpt_ops/).

    python tools/library/make_ax_cpt_ops.py

Copies the defence-kit files the task shows into its own stimuli/ folder (so a copy of the task is self-contained)
and copies the classic task's trial list unchanged (cue_kind A/B, probe_kind X/Y). The probes are words (status
readouts), drawn by text items. Re-run it after re-making the kit.

Per theme (cue A / other cues B; probe X / other probes Y are words in ax_cpt_ops.yaml), as in its `looks`:
  c2  hostile air track / friendly, neutral or unknown tracks; probe CLOSING / other track status   radar plot
  ew  high-threat pulsed emitter / other emitters; probe TRACKING / other emitter modes             waterfall
"""

from __future__ import annotations

from kit_copy import copy_from_kit
from ops_attention_pics import copy_lists

TASK = "ax_cpt_ops"

KIT_FILES = [
    # c2: radar-style plot and ten track symbols (64 px)
    "backgrounds/plot_radar_1280x720.png", "symbols/hostile_air_64.png",
    "symbols/friendly_air_64.png", "symbols/friendly_surface_64.png", "symbols/friendly_ground_64.png",
    "symbols/neutral_air_64.png", "symbols/neutral_surface_64.png", "symbols/neutral_ground_64.png",
    "symbols/unknown_air_64.png", "symbols/unknown_surface_64.png", "symbols/unknown_ground_64.png",
    # ew: waterfall and the six emitter marks
    "backgrounds/waterfall_1280x720.jpg", "emitters/emitter_pulsed_high.png", "emitters/emitter_pulsed_medium.png",
    "emitters/emitter_pulsed_low.png", "emitters/emitter_continuous_high.png", "emitters/emitter_continuous_medium.png",
    "emitters/emitter_continuous_low.png",
]


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    copy_lists(TASK, "ax_cpt", {"ax_cpt.csv": f"{TASK}.csv"})
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB) and {TASK}.csv")
