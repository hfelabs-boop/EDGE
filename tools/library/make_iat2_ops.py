"""Make the stimuli and trial lists of iat2_ops, the operational adaptation of the IAT (edge/library/tasks/iat2_ops/).

    python tools/library/make_iat2_ops.py

The categories are about systems, never about people or groups:
  target A  Own systems        c2: friendly (blue rectangle) track symbols with a track number   ew: own emitters (words)
  target B  Other systems      c2: hostile (red diamond) track symbols with a track number       ew: other emitters (words)
  positive  Reliable           status words (both themes)
  negative  Unreliable         status words (both themes)

What it does:
  * copies the defence-kit backgrounds the task shows into stimuli/ (so a copy of the task is self-contained);
  * draws the 16 c2 target pictures (a 64 px kit symbol with a fictional track number under it): stimuli/own_*.png and
    stimuli/other_*.png;
  * writes lists/block1.csv - block7.csv: the same design as the classic `iat2` (20/20/20/40/40/20/40 trials; blocks 1
    and 5 the targets, block 2 the attributes, blocks 3, 4, 6, 7 half targets, half attributes). Instead of the word,
    each row has `item` (0-7), the place of the stimulus in its category's list; iat2_ops.yaml looks the stimulus up
    for the current theme (variables targets and attr_words), so the same lists serve every theme.
Re-run it after changing the word lists in iat2_ops.yaml (keep 8 per category) or re-making the kit.
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from kit_copy import KIT, TASKS, copy_from_kit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_defense_kit import font  # noqa: E402

TASK = "iat2_ops"
OUT = TASKS / TASK

KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "backgrounds/spectrum_1280x720.png"]

# 8 c2 target pictures per category: kit symbol (air / surface / ground) + a made-up track number
OWN = [("air", 412), ("surface", 1207), ("ground", 2316), ("air", 3045), ("surface", 4120), ("ground", 5531),
       ("air", 6074), ("surface", 7318)]
OTHER = [("ground", 418), ("air", 1293), ("surface", 2350), ("ground", 3012), ("air", 4187), ("surface", 5506),
         ("ground", 6649), ("air", 7372)]

# trials per block and phase (Greenwald, Nosek & Banaji, 2003), as in make_iat2.py
N = {1: 20, 2: 20, 3: 20, 4: 40, 5: 40, 6: 20, 7: 40}
PHASE = {1: "single", 2: "single", 3: "practice", 4: "test", 5: "single", 6: "practice", 7: "test"}


def track_picture(affil: str, kind: str, number: int) -> Image.Image:
    """The kit symbol (64 px) with the track number under it, on a transparent 120 x 110 picture."""
    sym = Image.open(KIT / "symbols" / f"{affil}_{kind}_64.png").convert("RGBA")
    img = Image.new("RGBA", (120, 110), (0, 0, 0, 0))
    img.paste(sym, (28, 4), sym)
    d = ImageDraw.Draw(img)
    colour = {"friendly": (128, 224, 255, 255), "hostile": (255, 128, 128, 255)}[affil]
    text = f"T{number:04d}"
    f = font(20, bold=True)
    w = d.textlength(text, font=f)
    d.text(((120 - w) / 2 + 1, 79), text, font=f, fill=(0, 0, 0, 200))
    d.text(((120 - w) / 2, 78), text, font=f, fill=colour)
    return img


def take(role: str, kind: str, n: int, rng: random.Random) -> list[dict]:
    """n rows of one category, every one of its 8 stimuli in turn (shuffled), as `take` in make_iat2.py."""
    pool: list[int] = []
    while len(pool) < n:
        more = list(range(8))
        rng.shuffle(more)
        pool += more
    return [{"item": i, "role": role, "kind": kind} for i in pool[:n]]


def lists() -> None:
    rng = random.Random(1998)
    (OUT / "lists").mkdir(parents=True, exist_ok=True)
    for b, n in N.items():
        if b in (1, 5):
            rows = take("target_a", "target", n // 2, rng) + take("target_b", "target", n // 2, rng)
        elif b == 2:
            rows = take("positive", "attribute", n // 2, rng) + take("negative", "attribute", n // 2, rng)
        else:
            q = n // 4
            rows = (take("target_a", "target", q, rng) + take("target_b", "target", q, rng)
                    + take("positive", "attribute", q, rng) + take("negative", "attribute", q, rng))
        combined = b in (3, 4, 6, 7)
        for r in rows:
            r.update(block=b, phase=PHASE[b], alternate=r["kind"] if combined else "free")
        with open(OUT / "lists" / f"block{b}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["block", "phase", "item", "role", "kind", "alternate"], lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    for prefix, affil, items in (("own", "friendly", OWN), ("other", "hostile", OTHER)):
        for i, (kind, number) in enumerate(items, 1):
            track_picture(affil, kind, number).save(OUT / "stimuli" / f"{prefix}_{i}.png", optimize=True)
    lists()
    size = sum(p.stat().st_size for p in (OUT / "stimuli").iterdir())
    print(f"{TASK}: {len(copied)} kit files, 16 track pictures ({size / 1e6:.2f} MB in stimuli/) and lists/block1-7.csv")
