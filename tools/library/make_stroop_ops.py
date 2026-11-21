"""Make the operational adaptations of the Stroop family (edge/library/tasks/{stroop,stroop_de,stroop_en,stroop_phone}_ops/).

    python tools/library/make_stroop_ops.py

The colour words of the classic task become track AFFILIATION words and the inks become the affiliation colours of
the common symbology convention (EDGE's defence kit palette): hostile = red, neutral = green, friendly = blue,
unknown = yellow. The operator reports the COLOUR of the label and ignores what it says (HOSTILE written in blue
-> the key for blue). The design is the classic one (tools/library/make_stroop.py): every word x ink combination
once plus each congruent one three times (24 rows, 50 % congruent), and the same 8 practice pairs; the keys are the
classic ones (r g b y for the English task, the position keys d f j k for the German and translatable versions,
four colour buttons on the phone).

Each task copies its kit pictures into its own stimuli/ folder (kit_copy) and gets its trial lists:
  c2   a track label on the tactical plot (radar-style), with a track number
  uav  a target tag under the reticle of a camera frame, with telemetry text
"""

from __future__ import annotations

import csv
from pathlib import Path

from kit_copy import TASKS, copy_from_kit

INKS = {"hostile": "#ff8080", "neutral": "#aaffaa", "friendly": "#80e0ff", "unknown": "#ffff80"}   # kit palette
COLOUR_NAME = {"hostile": "red", "neutral": "green", "friendly": "blue", "unknown": "yellow"}
WORDS = {
    "en": {"hostile": "HOSTILE", "neutral": "NEUTRAL", "friendly": "FRIENDLY", "unknown": "UNKNOWN"},
    "de": {"hostile": "FEIND", "neutral": "NEUTRAL", "friendly": "FREUND", "unknown": "UNBEKANNT"},
}
KEYS = {
    "first_letter": {"hostile": "r", "neutral": "g", "friendly": "b", "unknown": "y"},   # r(ed) g(reen) b(lue) y(ellow)
    "position": {"hostile": "d", "neutral": "f", "friendly": "j", "unknown": "k"},
}
# the classic practice pairs (word, ink), red -> hostile, green -> neutral, blue -> friendly, yellow -> unknown
PRACTICE = [("hostile", "hostile"), ("neutral", "friendly"), ("friendly", "unknown"), ("unknown", "unknown"),
            ("hostile", "neutral"), ("neutral", "neutral"), ("friendly", "friendly"), ("unknown", "hostile")]

KIT_FILES = [
    # c2: the tactical plot
    "backgrounds/plot_radar_1280x720.png",
    # uav: camera frames (one infrared) and the reticle
    "terrain/terrain_01_farmland.jpg", "terrain/terrain_05_farmland_ir.jpg",
    "reticles/reticle_brackets.png",
]
PHONE_FILES = ["backgrounds/plot_radar_800x800.png", "terrain/terrain_01_farmland.jpg",
               "terrain/terrain_05_farmland_ir.jpg", "reticles/reticle_brackets.png"]


def main_rows() -> list[tuple[str, str]]:
    rows = []
    for word in INKS:
        for ink in INKS:
            rows += [(word, ink)] * (3 if word == ink else 1)
    return rows


def write(path: Path, pairs, lang: str | None, keys: str | None, button: bool = False) -> None:
    cols = ["word", "ink", "ink_colour", "ink_rgb", "congruent", "condition"]
    if lang is None:
        cols[0] = "word_id"           # translatable version: the word is looked up in the text variables
    cols.append("correct_button" if button else "correct_key")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for word, ink in pairs:
            congruent = int(word == ink)
            answer = f"btn_{ink}" if button else KEYS[keys][ink]
            w.writerow([WORDS[lang][word] if lang else word, ink, COLOUR_NAME[ink], INKS[ink], congruent,
                        "congruent" if congruent else "incongruent", answer])


def main() -> None:
    plan = {"stroop_ops": ("en", "first_letter", False), "stroop_de_ops": ("de", "position", False),
            "stroop_en_ops": (None, "position", False), "stroop_phone_ops": ("en", None, True)}
    for task, (lang, keys, button) in plan.items():
        copied = copy_from_kit(task, PHONE_FILES if button else KIT_FILES)
        write(TASKS / task / "stroop.csv", main_rows(), lang, keys, button)
        write(TASKS / task / "practice.csv", PRACTICE, lang, keys, button)
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB), stroop.csv and practice.csv")


if __name__ == "__main__":
    main()
