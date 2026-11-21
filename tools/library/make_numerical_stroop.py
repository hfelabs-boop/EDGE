"""Write the trial lists of the numerical Stroop (size congruity) tasks in the EDGE task library.

    python tools/library/make_numerical_stroop.py

Design (after Henik & Tzelgov, 1982): two digits side by side; choose the numerically larger one.
Digit pairs at numerical distance 1 and 5; physical size congruent (the larger number is also printed
larger), incongruent (the larger number is printed smaller) or neutral (same print size); the larger
number on the left or on the right. 8 pairs x 3 congruity x 2 sides = 48 rows.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"

PAIRS = [(2, 3), (4, 5), (6, 7), (7, 8), (1, 6), (2, 7), (3, 8), (4, 9)]   # (smaller, larger)
BIG, SMALL, NEUTRAL = 1.0, 0.5, 0.75          # print sizes relative to the task's digit size
PRACTICE_ROWS = [0, 9, 16, 19, 26, 33, 36, 47]


def rows() -> list[dict]:
    out = []
    for small, large in PAIRS:
        for condition in ("congruent", "incongruent", "neutral"):
            size_large = {"congruent": BIG, "incongruent": SMALL, "neutral": NEUTRAL}[condition]
            size_small = {"congruent": SMALL, "incongruent": BIG, "neutral": NEUTRAL}[condition]
            for side in ("left", "right"):
                left, right = (large, small) if side == "left" else (small, large)
                lsize, rsize = (size_large, size_small) if side == "left" else (size_small, size_large)
                out.append({"left_digit": left, "right_digit": right, "left_size": lsize, "right_size": rsize,
                            "larger_side": side, "distance": large - small, "condition": condition,
                            "correct_key": "a" if side == "left" else "l",
                            "correct_box": "box_left" if side == "left" else "box_right"})
    return out


def write(path: Path, data: list[dict], drop: str) -> None:
    cols = [c for c in data[0] if c != drop]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(data)


def main() -> None:
    data = rows()
    practice = [data[i] for i in PRACTICE_ROWS]
    for task, drop in (("numerical_stroop", "correct_box"), ("numerical_stroop_touch", "correct_key")):
        folder = ROOT / task
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / "trials.csv", data, drop)
        write(folder / "practice.csv", practice, drop)
        print("wrote", folder)


if __name__ == "__main__":
    main()
