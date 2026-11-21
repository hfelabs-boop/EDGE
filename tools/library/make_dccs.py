"""Write the trial lists of the Dimensional Change Card Sort (DCCS) in the EDGE task library.

    python tools/library/make_dccs.py

Target cards (always on screen): left = a BLUE TRIANGLE, right = a RED CIRCLE.
Test cards conflict with both: a RED TRIANGLE and a BLUE CIRCLE.
  colour game:  red triangle -> right (red),      blue circle -> left (blue)
  shape game:   red triangle -> left (triangle),  blue circle -> right (circle)
  border game:  a card with a black border is sorted by colour, without a border by shape
Phases (after Zelazo, 2006): pre-switch (colour, 6 cards), post-switch (shape, 6), border (12, half with
a border). practice.csv: 2 colour-game cards for the demonstration with feedback.
"""

from __future__ import annotations

import csv
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "dccs"
CARDS = {"red_triangle": ("triangle", "red", "#e8312f"), "blue_circle": ("circle", "blue", "#3d6df2")}
ANSWER = {   # (card, rule) -> the target card it goes to
    ("red_triangle", "colour"): "card_right", ("blue_circle", "colour"): "card_left",
    ("red_triangle", "shape"): "card_left", ("blue_circle", "shape"): "card_right",
}
COLS = ["phase", "hint", "card", "shape", "colour", "colour_rgb", "border", "rule", "correct_card"]
HINTS = {"demo": "Colour game", "pre_switch": "Colour game", "post_switch": "Shape game", "border": "Border game"}


def row(phase: str, card: str, rule: str, border: int = 0) -> list:
    shape, colour, rgb = CARDS[card]
    return [phase, HINTS[phase], card, shape, colour, rgb, border, rule, ANSWER[(card, rule)]]


def main() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    lists = {
        "practice.csv": [row("demo", "red_triangle", "colour"), row("demo", "blue_circle", "colour")],
        "pre_switch.csv": [row("pre_switch", c, "colour") for c in CARDS] * 3,
        "post_switch.csv": [row("post_switch", c, "shape") for c in CARDS] * 3,
        "border.csv": ([row("border", c, "colour", 1) for c in CARDS] + [row("border", c, "shape", 0) for c in CARDS]) * 3,
    }
    for name, rows in lists.items():
        with (FOLDER / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLS)
            w.writerows(rows)
        print("wrote", FOLDER / name, len(rows), "rows")


if __name__ == "__main__":
    main()
