"""Write the trial lists of the Stroop family in the EDGE task library.

    python tools/library/make_stroop.py

Creates stroop.csv / practice.csv in edge/library/tasks/{stroop, stroop_de, stroop_en, stroop_phone}.
Design: 4 colours; every word x ink combination once (12 incongruent rows) plus each congruent
combination three times (12 congruent rows), so a pass through the list is 50% congruent (24 rows).
Re-running gives the same files (no randomness: EDGE shuffles the rows at run time).
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"

INKS = {"red": "#e8312f", "green": "#22b14c", "blue": "#3d6df2", "yellow": "#f2d230"}
WORDS = {
    "en": {"red": "RED", "green": "GREEN", "blue": "BLUE", "yellow": "YELLOW"},
    "de": {"red": "ROT", "green": "GRÜN", "blue": "BLAU", "yellow": "GELB"},
}
# keys: first letters for the English version; position keys (d f j k) for the others, so the
# keys don't depend on the language of the colour words
KEYS = {
    "first_letter": {"red": "r", "green": "g", "blue": "b", "yellow": "y"},
    "position": {"red": "d", "green": "f", "blue": "j", "yellow": "k"},
}
PRACTICE = [("red", "red"), ("green", "blue"), ("blue", "yellow"), ("yellow", "yellow"),
            ("red", "green"), ("green", "green"), ("blue", "blue"), ("yellow", "red")]


def main_rows() -> list[tuple[str, str]]:
    rows = []
    for word in INKS:
        for ink in INKS:
            rows += [(word, ink)] * (3 if word == ink else 1)
    return rows


def write(path: Path, pairs, lang: str | None, keys: str | None, button: bool = False) -> None:
    cols = ["word", "ink", "ink_rgb", "congruent", "condition"]
    if lang is None:
        cols[0] = "word_id"           # translatable version: the word is looked up in the text variables
    cols.append("correct_button" if button else "correct_key")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for word, ink in pairs:
            congruent = int(word == ink)
            answer = f"btn_{ink}" if button else KEYS[keys][ink]
            w.writerow([WORDS[lang][word] if lang else word, ink, INKS[ink], congruent,
                        "congruent" if congruent else "incongruent", answer])


def main() -> None:
    plan = {"stroop": ("en", "first_letter", False), "stroop_de": ("de", "position", False),
            "stroop_en": (None, "position", False), "stroop_phone": ("en", None, True)}
    for task, (lang, keys, button) in plan.items():
        folder = ROOT / task
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / "stroop.csv", main_rows(), lang, keys, button)
        write(folder / "practice.csv", PRACTICE, lang, keys, button)
        print("wrote", folder)


if __name__ == "__main__":
    main()
