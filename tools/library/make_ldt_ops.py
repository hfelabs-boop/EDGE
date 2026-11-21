"""Make the stimuli and trial lists of ldt_ops, the operational adaptation of the lexical decision task
(edge/library/tasks/ldt_ops/).

    python tools/library/make_ldt_ops.py

Copies the defence-kit pictures the task shows into its stimuli/ folder and writes the trial lists, with the same
design and columns as the classic `ldt`: 20 frequent and 20 rarer real words of operator messages, and 40 malformed
message words (pronounceable non-words, each made by changing letters of a message word), plus 8 practice strings.
The words are generic English vocabulary of status messages and radio procedure; no real brevity codes, call signs or
code words. The same lists serve every theme (the theme only changes the display around the string).
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

TASK = "ldt_ops"

KIT_FILES = [
    "backgrounds/map_grid_1280x720.jpg", "panels/message_panel_400x240.png",       # c2
    "terrain/terrain_04_river.jpg", "reticles/reticle_cross.png",                  # uav
]

# frequent words of operator messages
HIGH = ["report", "status", "signal", "sector", "route", "check", "clear", "contact", "track", "range",
        "speed", "north", "south", "point", "base", "alert", "hold", "move", "radio", "message"]
# rarer words of operator messages (real English words, but seen much less often)
LOW = ["loiter", "egress", "ingress", "vector", "picket", "waypoint", "azimuth", "dwell", "sortie", "slew",
       "transit", "relay", "beacon", "standby", "abort", "bearing", "datum", "squelch", "gimbal", "tasking"]
# malformed message words: pronounceable, but not words (a letter or two of a message word changed)
NONWORDS = ["stadus", "sigmel", "sentor", "roube", "chenk", "clour", "contoct", "trock", "ronge", "speet",
            "nolth", "soulth", "poind", "bamse", "alorp", "hond", "mobe", "rodio", "messape", "reporf",
            "loiker", "egriss", "ingrest", "vertor", "picnet", "waypont", "azimath", "dwelk", "sortle", "slom",
            "trensit", "rebay", "beacom", "standpy", "abolt", "bearung", "dalum", "squolch", "gimbol", "taskung"]
PRACTICE_WORDS = ["radar", "screen", "map", "orbit"]
PRACTICE_NONWORDS = ["rabar", "scroon", "mab", "orpit"]

FIELDS = ["letters", "lexicality", "frequency", "corr_key", "practice"]


def write(path, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        w.writerows(rows)


if __name__ == "__main__":
    assert len(HIGH) == len(LOW) == 20 and len(NONWORDS) == 40
    assert len(set(HIGH + LOW + NONWORDS + PRACTICE_WORDS + PRACTICE_NONWORDS)) == 88, "a string is listed twice"
    copied = copy_from_kit(TASK, KIT_FILES)
    write(TASKS / TASK / "ldt_trials.csv", [[w, "word", "high", "j", 0] for w in HIGH] + [[w, "word", "low", "j", 0] for w in LOW]
          + [[w, "nonword", "none", "f", 0] for w in NONWORDS])
    write(TASKS / TASK / "ldt_practice.csv", [[w, "word", "practice", "j", 1] for w in PRACTICE_WORDS]
          + [[w, "nonword", "none", "f", 1] for w in PRACTICE_NONWORDS])
    size = sum(p.stat().st_size for p in copied)
    print(f"{TASK}: {len(copied)} kit files ({size / 1e6:.2f} MB), ldt_trials.csv and ldt_practice.csv")
