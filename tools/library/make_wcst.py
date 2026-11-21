"""Draw the cards and write the trial list of the WCST-inspired card sorting task in the EDGE task library.

    python tools/library/make_wcst.py          (needs Pillow: pip install pillow)

64 cards: every combination of 4 colours x 4 shapes x 1-4 symbols, drawn here from scratch
(stimuli/<number>_<colour>_<shape>.png, 200 x 280 px). The four key cards are
1 red triangle, 2 green stars, 3 yellow crosses, 4 blue circles (as in Berg's / Grant & Berg's deck).
cards.csv lists the 64 cards with, for each sorting rule, which key card (1-4) matches.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw

FOLDER = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "wcst"
COLOURS = {"red": (220, 40, 40), "green": (30, 160, 70), "yellow": (235, 190, 20), "blue": (40, 90, 220)}
SHAPES = ["triangle", "star", "cross", "circle"]
KEY_OF = {"colour": {c: i + 1 for i, c in enumerate(COLOURS)}, "shape": {s: i + 1 for i, s in enumerate(SHAPES)}}
W, H, R = 200, 280, 26          # card size and symbol radius (px)
SLOTS = {1: [(100, 140)], 2: [(100, 85), (100, 195)], 3: [(100, 65), (100, 140), (100, 215)],
         4: [(60, 85), (140, 85), (60, 195), (140, 195)]}


def symbol(d: ImageDraw.ImageDraw, shape: str, cx: float, cy: float, fill, R: float) -> None:  # noqa: N803
    if shape == "circle":
        d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=fill)
    elif shape == "triangle":
        d.polygon([(cx, cy - R), (cx + R * 1.05, cy + R * 0.8), (cx - R * 1.05, cy + R * 0.8)], fill=fill)
    elif shape == "star":
        pts = []
        for k in range(10):
            rad = R * 1.1 if k % 2 == 0 else R * 0.45
            a = -math.pi / 2 + k * math.pi / 5
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        d.polygon(pts, fill=fill)
    elif shape == "cross":
        t = R * 0.38
        d.rectangle([cx - R, cy - t, cx + R, cy + t], fill=fill)
        d.rectangle([cx - t, cy - R, cx + t, cy + R], fill=fill)


def card(number: int, colour: str, shape: str) -> Image.Image:
    scale = 2                                    # draw at double size, then shrink: smooth edges
    img = Image.new("RGB", (W * scale, H * scale), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W * scale - 1, H * scale - 1], outline=(90, 90, 90), width=3 * scale)
    for x, y in SLOTS[number]:
        symbol(d, shape, x * scale, y * scale, COLOURS[colour], R * scale)
    return img.resize((W, H), Image.LANCZOS)


def main() -> None:
    (FOLDER / "stimuli").mkdir(parents=True, exist_ok=True)
    rows = []
    for number in range(1, 5):
        for colour in COLOURS:
            for shape in SHAPES:
                name = f"{number}_{colour}_{shape}"
                card(number, colour, shape).save(FOLDER / "stimuli" / f"{name}.png", optimize=True)
                rows.append([f"stimuli/{name}.png", colour, shape, number,
                             KEY_OF["colour"][colour], KEY_OF["shape"][shape], number])
    with (FOLDER / "cards.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["card_image", "colour", "shape", "number", "key_colour", "key_shape", "key_number"])
        w.writerows(rows)
    print("wrote", len(rows), "cards to", FOLDER)


if __name__ == "__main__":
    main()
