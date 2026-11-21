"""Make the stimuli of the operational Mackworth clock adaptations (edge/library/tasks/{mackworth_ops,
mackworth2_ops}/).

    python tools/library/make_mackworth_ops.py          (needs Pillow for the task-specific pictures)

The trial lists are the classic tasks' (ticks.csv and practice.csv of mackworth / mackworth2, made by
make_mackworth.py), copied unchanged: one row per step of the pointer (1 s), double = 1 for the double jumps.
The kit files are copied with kit_copy; the pictures below are drawn here (procedurally, in the kit's console
colours) because the kit has no scope without a fixed sweep and no ring of 60 positions:

mackworth_ops
  stimuli/scope_600.png    c2: an empty radar scope, 600 px: range rings, bearing labels and 60 bearing ticks
                           (one per scan step, as the 60 marks of the clock)
  stimuli/sweep_600.png    c2: the sweep beam, pointing up (bearing 000) from the centre, with a short fading trail
                           behind it; the task turns it by 6 degrees per step (ori), like the clock pointer
  kit: terrain/terrain_02_village.jpg, reticles/crosshair_full_1280x720.png (video: the camera feed and crosshair)
mackworth2_ops
  stimuli/sensor_ring_600.png   c2: 60 perimeter sensor posts (small diamonds) on a ring of radius 250 px, ticks
                                every 5 posts with the post numbers 00-55
  stimuli/channel_ring_600.png  ew: 60 receiver channel cells on a ring of radius 250 px, labelled CH 00-55 every 5
  kit: backgrounds/map_grid_800x800.jpg (c2), backgrounds/spectrum_1280x720.png (ew)
The lit position (drawn by the task at radius 250 px, 6 degrees per step) falls on a post / cell of the rings.
"""

from __future__ import annotations

import math
import shutil

from kit_copy import TASKS, copy_from_kit

SIZE = 600
C = SIZE / 2
GRID = (29, 74, 94, 255)          # console grid  #1d4a5e
TEXT = (159, 232, 255, 255)       # console text  #9fe8ff
BEAM = (52, 230, 160)             # sweep green


def font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSansMono.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def polar(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return C + r * math.sin(a), C - r * math.cos(a)


def scope(path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([C - 290, C - 290, C + 290, C + 290], fill=(4, 18, 28, 255), outline=(60, 130, 160, 255), width=3)
    for k in range(1, 5):                                     # range rings
        r = 260 * k / 4
        d.ellipse([C - r, C - r, C + r, C + r], outline=GRID, width=1)
    for b in range(0, 360, 30):                               # bearing lines and labels
        d.line([C, C, *polar(260, b)], fill=(29, 74, 94, 160), width=1)
        d.text(polar(276, b), f"{b:03d}", fill=TEXT, font=font(12), anchor="mm")
    for k in range(60):                                       # 60 scan steps
        d.line([*polar(250 if k % 5 else 240, k * 6), *polar(262, k * 6)], fill=(120, 200, 230, 255),
               width=3 if k % 5 == 0 else 2)
    d.ellipse([C - 4, C - 4, C + 4, C + 4], fill=(0, 229, 255, 255))
    img.save(path, optimize=True)


def sweep(path) -> None:
    """The beam at bearing 000 with a 24-degree trail fading out anticlockwise (behind a clockwise sweep)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [C - 258, C - 258, C + 258, C + 258]
    for i in range(24):                                       # PIL angles: 0 = east, clockwise; bearing 000 = -90
        a1 = -90 - i
        d.pieslice(box, a1 - 1, a1, fill=(*BEAM, int(110 * (1 - i / 24))))
    d.line([C, C, *polar(258, 0)], fill=(*BEAM, 255), width=4)
    img.save(path, optimize=True)


def ring(path, kind: str) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([C - 250, C - 250, C + 250, C + 250], outline=GRID, width=2)
    for k in range(60):
        x, y = (round(v) for v in polar(250, k * 6))
        if kind == "sensor":                                  # a small diamond post
            s = 9
            d.polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], fill=(10, 34, 50, 255),
                      outline=(128, 224, 255, 255))
        else:                                                 # a channel cell
            d.rectangle([x - 8, y - 8, x + 8, y + 8], fill=(10, 34, 50, 255), outline=(255, 176, 0, 255))
        if k % 5 == 0:
            label = f"{k:02d}" if kind == "sensor" else f"CH {k:02d}"
            d.text(polar(282, k * 6), label, fill=TEXT, font=font(12), anchor="mm")
    d.text((C, C - 14), "PERIMETER SENSORS" if kind == "sensor" else "RECEIVER SCAN", fill=TEXT, font=font(14),
           anchor="mm")
    d.text((C, C + 10), "active post lit" if kind == "sensor" else "active channel lit", fill=(159, 232, 255, 160),
           font=font(12), anchor="mm")
    img.save(path, optimize=True)


if __name__ == "__main__":
    for task, base in (("mackworth_ops", "mackworth"), ("mackworth2_ops", "mackworth2")):
        (TASKS / task / "stimuli").mkdir(parents=True, exist_ok=True)
        for name in ("practice.csv", "ticks.csv"):
            shutil.copyfile(TASKS / base / name, TASKS / task / name)
    copy_from_kit("mackworth_ops", ["terrain/terrain_02_village.jpg", "reticles/crosshair_full_1280x720.png"])
    copy_from_kit("mackworth2_ops", ["backgrounds/map_grid_800x800.jpg", "backgrounds/spectrum_1280x720.png"])
    try:
        scope(TASKS / "mackworth_ops" / "stimuli" / "scope_600.png")
        sweep(TASKS / "mackworth_ops" / "stimuli" / "sweep_600.png")
        ring(TASKS / "mackworth2_ops" / "stimuli" / "sensor_ring_600.png", "sensor")
        ring(TASKS / "mackworth2_ops" / "stimuli" / "channel_ring_600.png", "channel")
    except ImportError:
        print("Pillow is not installed: the trial lists and kit files were copied, the pictures were not drawn "
              "(pip install pillow)")
    print("done")
