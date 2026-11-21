"""Write the trial lists of the multitasking task in the EDGE task library.

    python tools/library/make_multitasking.py

Design after Stoet, O'Connor, Conner & Laws (2013): a figure (diamond or rectangle, filled with 2 or 3
dots) appears in the top or bottom half of a frame. Top half: shape task (diamond = A, rectangle = L).
Bottom half: filling task (2 dots = A, 3 dots = L). Blocks:
  shape.csv    single-task block, shape task only (top half): 4 figures x 6 = 24 rows
  filling.csv  single-task block, filling task only (bottom half): 24 rows
  mixed.csv    dual-task (mixed) block, top or bottom at random: 2 halves x 4 figures x 8 = 64 rows
and 8-row practice lists for each (practice_shape.csv, practice_filling.csv, practice_mixed.csv).
Every row says its block, block_type (single / mixed) and stage (practice / test).
"""

from __future__ import annotations

import csv
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "multitasking"
COLS = ["block", "block_type", "stage", "half", "task", "shape", "dots", "correct_key", "congruency"]


def row(half: str, shape: str, dots: int) -> list:
    shape_key = "a" if shape == "diamond" else "l"
    dots_key = "a" if dots == 2 else "l"
    task = "shape" if half == "top" else "filling"
    return [half, task, shape, dots, shape_key if task == "shape" else dots_key,
            "congruent" if shape_key == dots_key else "incongruent"]


def figures(half: str) -> list[list]:
    return [row(half, s, d) for s in ("diamond", "rectangle") for d in (2, 3)]


def labelled(block: str, stage: str, rows: list[list]) -> list[list]:
    return [[block, "mixed" if block == "mixed" else "single", stage] + r for r in rows]


def main() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    blocks = {"shape": (figures("top") * 6, figures("top") * 2),
              "filling": (figures("bottom") * 6, figures("bottom") * 2),
              "mixed": ((figures("top") + figures("bottom")) * 8, figures("top") + figures("bottom"))}
    lists = {}
    for block, (test, practice) in blocks.items():
        lists[f"{block}.csv"] = labelled(block, "test", test)
        lists[f"practice_{block}.csv"] = labelled(block, "practice", practice)
    for name, rows in lists.items():
        with (FOLDER / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLS)
            w.writerows(rows)
        print("wrote", FOLDER / name, len(rows), "rows")


if __name__ == "__main__":
    main()
