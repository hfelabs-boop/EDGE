"""Make the operational adaptation of negative priming (edge/library/tasks/negative_priming_ops/).

    python tools/library/make_negative_priming_ops.py

The overlapping red and green letters of the classic task become two overlapping designator letters on an
operator display; the operator reports the designator of the one that matters and ignores the other:
  c2   a HOSTILE track's designator (hostile red) over a FRIENDLY track's designator (friendly blue), on a radar plot
  ew   a HIGH-THREAT emitter's designator (threat red) over a LOW-THREAT emitter's designator (threat blue), on the
       spectrum display
The trial lists are the classic task's (tools/library/make_negative_priming.py), copied unchanged: 48 prime-probe
pairs, 24 ignored repetition and 24 control, letters D F J K, the key of the target letter.
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

TASK, BASE = "negative_priming_ops", "negative_priming"
KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "backgrounds/spectrum_1280x720.png"]


def main() -> None:
    copied = copy_from_kit(TASK, KIT_FILES)
    for name in ("trials.csv", "practice.csv"):
        shutil.copyfile(TASKS / BASE / name, TASKS / TASK / name)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), trials.csv and practice.csv from {BASE}")


if __name__ == "__main__":
    main()
