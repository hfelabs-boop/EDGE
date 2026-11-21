"""Make the stimuli and word lists of vaast_words_ops, the operational adaptation of the VAAST with words
(edge/library/tasks/vaast_words_ops/).

    python tools/library/make_vaast_words_ops.py

Copies the defence-kit pictures the task shows (camera frame and reticle of the uav theme) into its stimuli/ folder
and writes words.csv (8 'safe' and 8 'threat' status words, each shown twice per block) and practice_words.csv
(4 + 4 others), with the same design and columns as the classic `vaast_words` (stimulus, valence). The words are
generic status-message words; none names a person, group, place or weapon.
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK = "vaast_words_ops"
KIT_FILES = ["terrain/terrain_05_farmland_ir.jpg", "reticles/reticle_cross.png"]

SAFE = ["CLEAR", "SECURE", "NOMINAL", "SAFE", "STABLE", "RESOLVED", "CALM", "NORMAL"]
THREAT = ["THREAT", "DANGER", "ALARM", "HOSTILE", "HAZARD", "BREACH", "INTRUSION", "EMERGENCY"]
PRACTICE_SAFE = ["OKAY", "STEADY", "ROUTINE", "QUIET"]
PRACTICE_THREAT = ["WARNING", "INCOMING", "MAYDAY", "FIRE"]


def write(path, safe, threat) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["stimulus", "valence"])
        w.writerows([[s, "safe"] for s in safe] + [[s, "threat"] for s in threat])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    write(TASKS / TASK / "words.csv", SAFE, THREAT)
    write(TASKS / TASK / "practice_words.csv", PRACTICE_SAFE, PRACTICE_THREAT)
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), words.csv and practice_words.csv")
