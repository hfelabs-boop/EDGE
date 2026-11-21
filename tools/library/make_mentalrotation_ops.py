"""Make the stimuli and trial lists of mentalrotation_ops, the operational adaptation of mental rotation
(edge/library/tasks/mentalrotation_ops/).

    python tools/library/make_mentalrotation_ops.py

Draws, for each of the four shapes of the classic task (F, L, N, P), a picture and its mirror image (Pillow), in two
themes, and copies the defence-kit backgrounds the task shows:
  c2   area outlines on the tactical plot: the four chiral five-square shapes of `mentalrotation` (the same square
       centres), drawn as friendly-blue areas with an outline: stimuli/area_<shape>.png, area_<shape>_mirror.png
  uav  four generic vehicles seen from above, each with parts placed off its centre line so that it cannot be
       turned into its mirror image (tracked vehicle, truck, boat, aircraft): stimuli/top_<shape>.png, ..._mirror.png
Every picture is 220 x 220 px with the shape's centre in the middle, so turning it (the image item's `ori`) turns it
about its centre, like the polygons of the classic task. Mirror images are flipped left-right. Also writes
mr_trials.csv and mr_practice.csv with the design of `mentalrotation` (4 shapes x 8 angles x same/mirror; 8 practice).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from kit_copy import TASKS, copy_from_kit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_defense_kit import AFFIL, rgb  # noqa: E402

TASK = "mentalrotation_ops"
OUT = TASKS / TASK
S, K = 220, 4                      # picture size, supersampling

KIT_FILES = ["backgrounds/plot_radar_1280x720.png", "terrain/terrain_01_farmland.jpg", "reticles/reticle_brackets.png"]

# the classic task's shapes: centres of the five squares, in squares (x right, y up)
SHAPES = {
    "F": [[0, 1], [1, 1], [-1, 0], [0, 0], [0, -1]],
    "L": [[-0.5, 1.5], [-0.5, 0.5], [-0.5, -0.5], [-0.5, -1.5], [0.5, -1.5]],
    "N": [[-0.5, 1.5], [-0.5, 0.5], [-0.5, -0.5], [0.5, -0.5], [0.5, -1.5]],
    "P": [[-0.5, 1], [0.5, 1], [-0.5, 0], [0.5, 0], [-0.5, -1]],
}
CELL = 40


def area(shape: str) -> Image.Image:
    """The five squares as one area: translucent friendly-blue fill, a solid outline around the whole shape."""
    W = S * K
    c = W / 2
    mask = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(mask)
    for x, y in SHAPES[shape]:
        x0, y0 = c + (x - 0.5) * CELL * K, c - (y + 0.5) * CELL * K
        d.rectangle([x0, y0, x0 + CELL * K, y0 + CELL * K], fill=255)
    grown = mask.filter(ImageFilter.MaxFilter(13))
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (W, W), rgb(AFFIL["friendly"], 255)), (0, 0), grown)       # outline
    img.paste(Image.new("RGBA", (W, W), (24, 70, 96, 235)), (0, 0), mask)                    # fill
    d = ImageDraw.Draw(img)
    for x, y in SHAPES[shape]:                                                               # faint grid inside
        x0, y0 = c + (x - 0.5) * CELL * K, c - (y + 0.5) * CELL * K
        d.rectangle([x0 + 6, y0 + 6, x0 + CELL * K - 6, y0 + CELL * K - 6], outline=(128, 224, 255, 90), width=3)
    return img.resize((S, S), Image.LANCZOS)


def vehicle(shape: str) -> Image.Image:
    """A generic vehicle seen from above, pointing up, light (as in a daylight camera picture), with a soft dark rim."""
    W = S * K
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = W / 2
    body, dark, edge = (214, 212, 200, 255), (120, 118, 104, 255), (34, 34, 30, 255)

    def rr(x0, y0, x1, y1, r, fill, outline=edge, width=10):     # box in units of the picture (y down), centred
        d.rounded_rectangle([c + x0 * K, c + y0 * K, c + x1 * K, c + y1 * K], radius=r * K, fill=fill,
                            outline=outline, width=width)

    def shadowed(draw):          # a soft dark rim all round (no cast shadow: its direction would be a cue of its own)
        sh = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        draw(ImageDraw.Draw(sh), (0, 0, 0, 255))
        rim = sh.getchannel("A").filter(ImageFilter.MaxFilter(17)).point(lambda v: v * 0.45)
        img.paste(Image.new("RGBA", (W, W), (0, 0, 0, 255)), (0, 0), rim)
    if shape == "F":       # tracked vehicle: turret off to the left, a stowage box at the right rear, hatch front right
        shadowed(lambda dd, col: dd.rounded_rectangle([c - 34 * K, c - 75 * K, c + 34 * K, c + 75 * K], radius=10 * K, fill=col))
        rr(-34, -75, 34, 75, 10, body)
        for sx in (-1, 1):
            for k in range(11):
                y = -70 + k * 14
                d.line([c + (sx * 27 - 6) * K, c + y * K, c + (sx * 27 + 6) * K, c + y * K], fill=edge, width=8)
        d.ellipse([c - 30 * K, c - 22 * K, c + 6 * K, c + 14 * K], fill=dark, outline=edge, width=10)
        rr(6, 40, 30, 70, 3, dark)
        rr(8, -66, 22, -48, 2, dark)
    elif shape == "L":     # truck: cab at the front, spare wheel on its left, cargo bed with a crane at the right rear
        shadowed(lambda dd, col: dd.rounded_rectangle([c - 28 * K, c - 85 * K, c + 28 * K, c + 85 * K], radius=8 * K, fill=col))
        for y in (-60, 40, 66):
            for sx in (-1, 1):
                rr(sx * 28 - 7, y - 11, sx * 28 + 7, y + 11, 4, edge)
        rr(-28, -85, 28, -38, 10, body)
        rr(-28, -32, 28, 85, 4, body)
        d.ellipse([c - 46 * K, c - 75 * K, c - 30 * K, c - 59 * K], fill=dark, outline=edge, width=8)
        rr(4, 46, 22, 78, 2, dark)
        d.line([c + 13 * K, c + 62 * K, c - 14 * K, c + 4 * K], fill=edge, width=12)
    elif shape == "N":     # boat: pointed bow, superstructure off to the right, a small craft on the left foredeck
        hull = [(c, c - 95 * K), (c + 34 * K, c - 40 * K), (c + 34 * K, c + 85 * K), (c - 34 * K, c + 85 * K),
                (c - 34 * K, c - 40 * K)]
        shadowed(lambda dd, col: dd.polygon(hull, fill=col))
        d.polygon(hull, fill=body, outline=edge, width=10)
        rr(-4, 0, 28, 52, 4, dark)
        rr(-26, -42, -8, -12, 7, (240, 240, 232, 255))
        d.ellipse([c - 22 * K, c + 62 * K, c - 8 * K, c + 76 * K], fill=dark, outline=edge, width=8)
    else:                  # aircraft: a pod under the left wing only, an antenna fairing on the right of the tail
        def plane(dd, col, outline=None, width=0):
            dd.polygon([(c - 90 * K, c + 8 * K), (c - 10 * K, c - 22 * K), (c + 10 * K, c - 22 * K), (c + 90 * K, c + 8 * K),
                        (c + 90 * K, c + 22 * K), (c - 90 * K, c + 22 * K)], fill=col, outline=outline, width=width)
            dd.polygon([(c - 38 * K, c + 82 * K), (c - 6 * K, c + 64 * K), (c + 6 * K, c + 64 * K), (c + 38 * K, c + 82 * K),
                        (c + 38 * K, c + 92 * K), (c - 38 * K, c + 92 * K)], fill=col, outline=outline, width=width)
            dd.rounded_rectangle([c - 11 * K, c - 95 * K, c + 11 * K, c + 95 * K], radius=10 * K, fill=col, outline=outline, width=width)
        shadowed(lambda dd, col: plane(dd, col))
        plane(d, body, edge, 10)
        rr(-62, -6, -48, 40, 6, dark)
        d.ellipse([c + 10 * K, c + 40 * K, c + 30 * K, c + 60 * K], fill=dark, outline=edge, width=8)
    return img.resize((S, S), Image.LANCZOS)


def trial_lists() -> None:
    """The design of `mentalrotation`: 4 shapes x 8 angles (0-315, steps of 45) x same / mirror; disparity = the
    smaller angle between the two (0-180); 8 practice trials."""
    fields = ["shape", "angle", "disparity", "match", "mirror_sign", "corr_key"]

    def row(shape, angle, match):
        return [shape, angle, min(angle, 360 - angle), match, 1 if match == "same" else -1, "f" if match == "same" else "j"]
    with open(OUT / "mr_trials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fields)
        for shape in SHAPES:
            for angle in range(0, 360, 45):
                for match in ("same", "mirror"):
                    w.writerow(row(shape, angle, match))
    with open(OUT / "mr_practice.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(fields)
        for shape, angle, match in (("P", 90, "same"), ("P", 90, "mirror"), ("F", 180, "mirror"), ("F", 45, "same"),
                                    ("L", 270, "same"), ("N", 135, "mirror"), ("N", 0, "same"), ("L", 315, "mirror")):
            w.writerow(row(shape, angle, match))


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    for shape in SHAPES:
        for prefix, draw in (("area", area), ("top", vehicle)):
            img = draw(shape)
            img.save(OUT / "stimuli" / f"{prefix}_{shape}.png", optimize=True)
            ImageOps.mirror(img).save(OUT / "stimuli" / f"{prefix}_{shape}_mirror.png", optimize=True)
    trial_lists()
    size = sum(p.stat().st_size for p in (OUT / "stimuli").iterdir())
    print(f"{TASK}: {len(copied)} kit files and 16 shape pictures ({size / 1e6:.2f} MB in stimuli/), mr_trials.csv, mr_practice.csv")
