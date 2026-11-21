"""Make the stimuli and trial lists of fitts_ops, the operational adaptation of the Fitts's law pointing task
(edge/library/tasks/fitts_ops/).

    python tools/library/make_fitts_ops.py

Draws the target boxes (Pillow): rounded rectangles in the kit's 'selected' colour (cyan, #00e5ff) with a dark edge
and a faint fill, 260 px high and 20, 40 or 80 px wide, the target widths of the classic task:
stimuli/target_box_<width>x260.png. The box's outer edge is the picture's edge, so the clickable area (the picture)
is exactly the box. Also copies the defence-kit pictures (camera frame, reticle, crosshair, camera feed) and writes
fitts_trials.csv and fitts_practice.csv with the design of the classic `fitts` (3 widths x 3 distances x 2 sides).
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from kit_copy import TASKS, copy_from_kit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_defense_kit import STATES, rgb  # noqa: E402

TASK = "fitts_ops"
WIDTHS, DISTANCES, HEIGHT = (20, 40, 80), (120, 240, 480), 260

KIT_FILES = [
    "terrain/terrain_02_village.jpg", "reticles/reticle_circle.png",          # uav
    "video/feed_01_pan.mp4", "reticles/crosshair_full_1280x720.png",          # video
]


def target_box(width: int, height: int = HEIGHT) -> Image.Image:
    k = 4
    W, H = width * k, height * k
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = min(10, width / 3) * k
    lw = 3 * k
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=(0, 229, 255, 40), outline=(0, 0, 0, 160), width=lw + 2 * k)
    d.rounded_rectangle([k, k, W - 1 - k, H - 1 - k], radius=r, outline=rgb(STATES["selected"], 255), width=lw)
    return img.resize((width, height), Image.LANCZOS)


def lists() -> None:
    fields = ["width", "distance", "side", "index_of_difficulty", "phase"]
    with open(TASKS / TASK / "fitts_trials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fields)
        for width in WIDTHS:
            for dist in DISTANCES:
                for side in (-1, 1):
                    w.writerow([width, dist, side, f"{math.log2(2 * dist / width):.2f}", "test"])
    with open(TASKS / TASK / "fitts_practice.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fields)
        for width, dist, side in ((80, 120, 1), (40, 240, -1), (20, 480, 1), (40, 120, -1)):
            w.writerow([width, dist, side, f"{math.log2(2 * dist / width):.2f}", "practice"])


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    for width in WIDTHS:
        target_box(width).save(TASKS / TASK / "stimuli" / f"target_box_{width}x{HEIGHT}.png", optimize=True)
    lists()
    size = sum(p.stat().st_size for p in (TASKS / TASK / "stimuli").iterdir())
    print(f"{TASK}: {len(copied)} kit files, 3 target boxes ({size / 1e6:.2f} MB in stimuli/), fitts_trials.csv, fitts_practice.csv")
