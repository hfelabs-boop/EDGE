"""Write the letter-digit stimulus list of the task-switching tasks in the EDGE task library.

    python tools/library/make_taskswitching.py

Each stimulus is a letter-digit pair (e.g. "G7"). Letter task: vowel = A key, consonant = L key.
Digit task: even = A key, odd = L key. Each letter appears once with an even and once with an odd
digit (16 pairs), so half the pairs are congruent (both tasks give the same key), half incongruent.
Used by taskswitching (alternating runs) and taskswitching_cued. For the cued version a second list,
trials.csv, crosses the 16 pairs with the task (letter / digit) and the cue-target interval (0.2 / 1.0 s):
64 rows, with the correct key for the cued task.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"
VOWELS, CONSONANTS = ["A", "E", "I", "U"], ["G", "K", "M", "R"]
EVEN, ODD = ["2", "4", "6", "8"], ["3", "5", "7", "9"]
CUE_RGB = {"letter": "#4da6ff", "digit": "#ffb347"}       # cue word and frame colour per task


def rows() -> list[list[str]]:
    out = []
    for i, letter in enumerate(VOWELS + CONSONANTS):
        for digit_class, digits in (("even", EVEN), ("odd", ODD)):
            letter_key = "a" if letter in VOWELS else "l"
            digit_key = "a" if digit_class == "even" else "l"
            out.append([letter + digits[i % 4], "vowel" if letter in VOWELS else "consonant", digit_class,
                        letter_key, digit_key, "congruent" if letter_key == digit_key else "incongruent"])
    return out


def main() -> None:
    for task in ("taskswitching",):
        folder = ROOT / task
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "stimuli.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["pair", "letter_class", "digit_class", "letter_key", "digit_key", "congruency"])
            w.writerows(rows())
        print("wrote", folder / "stimuli.csv")
    cued = ROOT / "taskswitching_cued" / "trials.csv"
    with cued.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["pair", "task", "cti", "cue", "cue_rgb", "correct_key", "congruency"])
        for pair, _lc, _dc, letter_key, digit_key, congruency in rows():
            for task in ("letter", "digit"):
                for cti in (0.2, 1.0):
                    w.writerow([pair, task, cti, task.upper(), CUE_RGB[task],
                                letter_key if task == "letter" else digit_key, congruency])
    print("wrote", cued)


if __name__ == "__main__":
    main()
