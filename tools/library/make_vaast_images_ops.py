"""Make the stimuli and trial lists of vaast_images_ops, the operational adaptation of the VAAST with pictures
(edge/library/tasks/vaast_images_ops/).

    python tools/library/make_vaast_images_ops.py

Draws 10 friendly and 10 hostile pictures per theme (8 for the test, 2 for practice) with the defence kit's drawing
functions (tools/library/make_defense_kit.py), and copies the kit pictures the scene needs:
  c2   track symbols, 150 px, with a fictional track number under them: friendly (blue rectangle frame) or hostile
       (red diamond frame), air / surface / ground icons in turn: stimuli/track_<friendly|hostile>_<n>.png
  uav  240 x 240 close-ups cut from the kit's camera frames, each with a generic vehicle seen from above (tracked,
       wheeled or car; light or dark; any heading) marked by the image tracker's box: green 'cleared' (friendly) or
       red 'confirmed' (hostile). Both categories have the same mix of vehicles and places, so only the box differs:
       stimuli/scene_<friendly|hostile>_<n>.jpg
Also writes images.csv (items 0-7 of each category) and practice_images.csv (items 8-9), in the classic task's
design (16 pictures, each twice per block; 4 practice pictures).
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from kit_copy import KIT, TASKS, copy_from_kit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_defense_kit import AFFIL, box, font, rgb, symbol, vehicle  # noqa: E402

TASK = "vaast_images_ops"
OUT = TASKS / TASK
KIT_FILES = ["terrain/terrain_03_forest.jpg", "reticles/reticle_brackets.png"]
N = 10
KINDS = ["air", "surface", "ground"]
VEHICLES = [("tracked", "light"), ("wheeled", "dark"), ("car", "light"), ("tracked", "dark"), ("wheeled", "light"),
            ("car", "dark"), ("tracked", "light"), ("wheeled", "dark"), ("car", "light"), ("tracked", "dark")]
FRAMES = ["terrain_01_farmland.jpg", "terrain_02_village.jpg", "terrain_04_river.jpg", "terrain_06_desert_dusk.jpg"]


def track(affil: str, kind: str, number: int) -> Image.Image:
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    sym = symbol(affil, kind, 150)
    img.paste(sym, (25, 0), sym)
    d = ImageDraw.Draw(img)
    text, f = f"T{number:04d}", font(30, bold=True)
    w = d.textlength(text, font=f)
    d.text(((200 - w) / 2 + 2, 160), text, font=f, fill=(0, 0, 0, 220))
    d.text(((200 - w) / 2, 158), text, font=f, fill=rgb(AFFIL[affil], 255))
    return img


def scene(i: int, state: str, rng: random.Random) -> Image.Image:
    frame = Image.open(KIT / "terrain" / FRAMES[i % len(FRAMES)]).convert("RGBA")
    x, y = rng.randint(0, 1280 - 240), rng.randint(0, 720 - 240)
    img = frame.crop((x, y, x + 240, y + 240))
    v = vehicle(*VEHICLES[i], size=96).rotate(rng.choice(range(0, 360, 30)), resample=Image.BICUBIC, expand=False)
    img.alpha_composite(v, (72, 72))
    b = box(state, 128)
    img.alpha_composite(b, (56, 56))
    return img.convert("RGB")


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    numbers = random.Random(2018).sample(range(100, 9900), 2 * N)
    for j, affil in enumerate(("friendly", "hostile")):
        for i in range(N):
            track(affil, KINDS[i % 3], numbers[j * N + i]).save(OUT / "stimuli" / f"track_{affil}_{i + 1}.png", optimize=True)
    for affil, state in (("friendly", "cleared"), ("hostile", "confirmed")):
        rng = random.Random(42)          # the same places and headings for both categories
        for i in range(N):
            scene(i, state, rng).save(OUT / "stimuli" / f"scene_{affil}_{i + 1}.jpg", quality=86, optimize=True)
    for name, items in (("images.csv", range(8)), ("practice_images.csv", range(8, 10))):
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["item", "valence"])
            w.writerows([[i, v] for v in ("friendly", "hostile") for i in items])
    size = sum(p.stat().st_size for p in (OUT / "stimuli").iterdir())
    print(f"{TASK}: {len(copied)} kit files and {4 * N} pictures ({size / 1e6:.2f} MB in stimuli/), images.csv, practice_images.csv")
