"""Draw the cards and write the trial list of the operational card sorting task (edge/library/tasks/wcst_ops/).

    python tools/library/make_wcst_ops.py          (needs Pillow and numpy, like make_defense_kit.py)

The 64 cards of the WCST-inspired task (4 colours x 4 shapes x 1-4 symbols) become contact report cards with
three dimensions that map one to one onto colour, shape and number, drawn here in two display themes
(stimuli/<theme>/<number>_<colour>_<shape>.png, 200 x 280 px, the classic codes in the file names):

  classic     c2: track symbols (kit style)                ew: emitter traces
  colour      AFFILIATION: red = hostile, green = neutral,  THREAT: red = high, green = own/cleared,
              yellow = unknown, blue = friendly             yellow = medium, blue = low
              (frame colour and frame shape)
  shape       TYPE (the icon in the frame): triangle = air, SIGNAL: triangle = continuous, star = pulsed,
              star = surface, cross = ground,               cross = burst, circle = sweep
              circle = subsurface
  number      1-4 tracks on the card                        1-4 emitters on the card

The four key cards are, as in the classic deck, 1 red triangle, 2 green stars, 3 yellow crosses, 4 blue circles
(c2: 1 hostile air, 2 neutral surface, 3 unknown ground, 4 friendly subsurface tracks). cards.csv lists the 64
cards (theme-free: `card` names the file in either theme's folder) with, for each rule, the key card (1-4) that
matches, exactly like the classic task's list. Frame shapes and colours come from the defence kit's symbol
drawing (make_defense_kit.frame_mask / draw_icon); the subsurface icon and the emitter traces are drawn here.
"""

from __future__ import annotations

import csv

from PIL import Image, ImageDraw, ImageFilter

from kit_copy import TASKS
from make_defense_kit import AFFIL, AFFIL_FRAME, draw_icon, frame_mask, rgb

TASK = "wcst_ops"
COLOURS = ["red", "green", "yellow", "blue"]
SHAPES = ["triangle", "star", "cross", "circle"]
KEY_OF = {"colour": {c: i + 1 for i, c in enumerate(COLOURS)}, "shape": {s: i + 1 for i, s in enumerate(SHAPES)}}
W, H = 200, 280
SLOTS = {1: [(100, 140)], 2: [(100, 85), (100, 195)], 3: [(100, 62), (100, 140), (100, 218)],
         4: [(58, 85), (142, 85), (58, 195), (142, 195)]}
AFFIL_OF = {"red": "hostile", "green": "neutral", "yellow": "unknown", "blue": "friendly"}
TYPE_OF = {"triangle": "air", "star": "surface", "cross": "ground", "circle": "subsurface"}
THREAT_RGB = {"red": "#ff3b30", "green": "#34c759", "yellow": "#ffb000", "blue": "#3ad0ff"}
SIGNAL_OF = {"triangle": "continuous", "star": "pulsed", "cross": "burst", "circle": "sweep"}
EW_SLOTS = {1: [100], 2: [68, 132], 3: [48, 100, 152], 4: [37, 79, 121, 163]}   # emitters side by side (x)
CARD_BG, CARD_EDGE = (10, 34, 50), (90, 122, 138)


def track_symbol(affil: str, kind: str, size: int = 60) -> Image.Image:
    """A track symbol like the kit's (frame shape and colour = affiliation), with a subsurface icon added."""
    ss = size * 4
    m = frame_mask(AFFIL_FRAME[affil], ss)
    stroke = m.filter(ImageFilter.MaxFilter(2 * max(1, ss // 40) + 1))
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (ss, ss), (0, 0, 0, 255)), (0, 0), stroke)
    img.paste(Image.new("RGBA", (ss, ss), rgb(AFFIL[affil], 255)), (0, 0), m)
    d = ImageDraw.Draw(img)
    if kind == "subsurface":                  # an inverted arc (a hull seen under the surface line)
        c, lw = ss / 2, max(2, int(ss * 0.06))
        d.arc([c - 0.2 * ss, c - 0.22 * ss, c + 0.2 * ss, c + 0.14 * ss], 0, 180, fill=(0, 0, 0, 255), width=lw)
        d.line([(c - 0.22 * ss, c - 0.04 * ss), (c + 0.22 * ss, c - 0.04 * ss)], fill=(0, 0, 0, 255), width=lw)
    else:
        draw_icon(d, kind, ss, (0, 0, 0, 255))
    return img.resize((size, size), Image.LANCZOS)


def emitter_trace(signal: str, colour: str, w: int = 34, h: int = 160, k: int = 4) -> Image.Image:
    """One emitter as seen on a waterfall: a vertical trace whose pattern gives the signal type."""
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col, glow = rgb(THREAT_RGB[colour], 255), rgb(THREAT_RGB[colour], 70)
    cx, hw = w * k / 2, w * k * 0.16
    if signal == "continuous":
        d.rounded_rectangle([cx - hw - 12, 0, cx + hw + 12, h * k], radius=18, fill=glow)
        d.rounded_rectangle([cx - hw, 6, cx + hw, h * k - 6], radius=10, fill=col)
    elif signal == "pulsed":
        seg = h * k / 13
        for i in range(0, 13, 2):
            d.rounded_rectangle([cx - hw - 10, i * seg - 4, cx + hw + 10, (i + 1) * seg + 4], radius=14, fill=glow)
            d.rounded_rectangle([cx - hw, i * seg, cx + hw, (i + 1) * seg], radius=8, fill=col)
    elif signal == "burst":                   # three short bursts of two dots
        r = hw * 0.9
        for y in (0.1, 0.36, 0.64, 0.9):
            for dx in (-1.1, 1.1):
                x0, y0 = cx + dx * r, y * h * k
                d.ellipse([x0 - r - 8, y0 - r - 8, x0 + r + 8, y0 + r + 8], fill=glow)
                d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=col)
    else:                                     # sweep: a zigzag across the channel
        pts = [(cx + (hw * 2.0 if i % 2 else -hw * 2.0), 8 + i * (h * k - 16) / 10) for i in range(11)]
        d.line(pts, fill=glow, width=int(hw * 1.6), joint="curve")
        d.line(pts, fill=col, width=int(hw * 0.8), joint="curve")
    return img.resize((w, h), Image.LANCZOS)


def card(theme: str, number: int, colour: str, shape: str) -> Image.Image:
    img = Image.new("RGB", (W, H), CARD_BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, H - 1], outline=CARD_EDGE, width=3)
    if theme == "c2":
        sym = track_symbol(AFFIL_OF[colour], TYPE_OF[shape])
        for x, y in SLOTS[number]:
            img.paste(sym, (int(x - sym.width / 2), int(y - sym.height / 2)), sym)
    else:
        for y in range(28, H - 20, 28):        # faint waterfall grid
            d.line([(10, y), (W - 10, y)], fill=(20, 52, 70), width=1)
        tr = emitter_trace(SIGNAL_OF[shape], colour)
        for x in EW_SLOTS[number]:
            img.paste(tr, (int(x - tr.width / 2), int(H / 2 - tr.height / 2)), tr)
    return img


def main() -> None:
    rows = []
    for theme in ("c2", "ew"):
        folder = TASKS / TASK / "stimuli" / theme
        folder.mkdir(parents=True, exist_ok=True)
        for number in range(1, 5):
            for colour in COLOURS:
                for shape in SHAPES:
                    name = f"{number}_{colour}_{shape}"
                    card(theme, number, colour, shape).save(folder / f"{name}.png", optimize=True)
                    if theme == "c2":
                        rows.append([name, colour, shape, number, KEY_OF["colour"][colour], KEY_OF["shape"][shape], number])
    with (TASKS / TASK / "cards.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["card", "colour", "shape", "number", "key_colour", "key_shape", "key_number"])
        w.writerows(rows)
    size = sum(p.stat().st_size for p in (TASKS / TASK / "stimuli").rglob("*.png"))
    print(f"{TASK}: 2 x 64 cards ({size / 1e6:.2f} MB) and cards.csv ({len(rows)} rows)")


if __name__ == "__main__":
    main()
