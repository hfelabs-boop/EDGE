"""Make the shared stimulus kit of the operational (defence) adaptations: edge/library/defense_kit/.

    python tools/library/make_defense_kit.py            (needs Pillow and numpy; videos need ffmpeg with libx264)
    python tools/library/make_defense_kit.py --no-video (pictures only)

Everything is drawn here, procedurally (no photographs, no map data, no real platforms, places or signals): random
fields, roads and buildings seen from above, generic track symbols, reticles, target boxes, a made-up spectrum and
waterfall. A fixed seed makes every run give the same pictures (videos can differ by a few bytes between ffmpeg
versions). The kit's index, edge/library/defense_kit/kit.yaml, is written last and lists every file with what it
shows and which theme it is meant for; docs/library/DEFENSE.md explains the themes and conventions.

What it makes (sizes in pixels):

* backgrounds/  tactical plot (radar scope) and map grid, 1280x720 and 800x800; spectrum display and empty waterfall
* terrain/      six synthetic camera frames 1280x720 (four daylight views, one infrared "white-hot", one hazy dusk)
* waterfall/    five waterfall frames 1280x720, each with a different (made-up) emitter pattern
* video/        four looping camera-feed videos 640x360, 10 s, H.264 without B-frames (-bf 0): pan, zoom, orbit,
                and one with moving vehicles
* symbols/      friendly / hostile / neutral / unknown frames x air / surface / ground icons, 32, 48 and 64 px
* vehicles/     small top-down generic vehicles (tracked, wheeled, car x light / dark), 48 px
* emitters/     waterfall emitter marks (pulsed / continuous x high / medium / low threat), 28x84
* reticles/     three reticle styles 240 px and a full-screen crosshair 1280x720
* boxes/        rounded-rectangle target boxes (candidate, selected, confirmed, cleared) 64, 96, 128 px, and round
                point markers in the same states 64 px
* panels/       a message-panel background 400x240 (its text is a recipe in kit.yaml, so it can change)
"""

from __future__ import annotations

import argparse
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "edge" / "library" / "defense_kit"
SEED = 4117

# ---------------------------------------------------------------- palette (also written to kit.yaml)
# affiliation colours after the common symbology convention (light fill on dark displays)
AFFIL = {"friendly": "#80e0ff", "hostile": "#ff8080", "neutral": "#aaffaa", "unknown": "#ffff80"}
AFFIL_FRAME = {"friendly": "rectangle", "hostile": "diamond", "neutral": "square", "unknown": "quatrefoil"}
DIMENSIONS = ("air", "surface", "ground")
SYMBOL_SIZES = (32, 48, 64)
# target-box states (colour, line style)
STATES = {"candidate": "#ffc400", "selected": "#00e5ff", "confirmed": "#ff3b30", "cleared": "#34c759"}
THREAT = {"high": "#ff3b30", "medium": "#ffb000", "low": "#3ad0ff"}
CONSOLE = {"background": "#04121c", "grid": "#1d4a5e", "text": "#9fe8ff", "accent": "#00e5ff", "warning": "#ffb000",
           "alert": "#ff3b30", "ok": "#34c759", "panel": "#0a2232"}

INDEX: list[dict] = []         # every file made, for kit.yaml


def note(path: Path, description: str, themes: list[str], **extra) -> None:
    INDEX.append({"file": path.relative_to(KIT).as_posix(), "description": description, "themes": themes, **extra})


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for name in (("DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def rgb(hex_colour: str, alpha: int | None = None) -> tuple:
    h = hex_colour.lstrip("#")
    c = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return c if alpha is None else (*c, alpha)


def save(img: Image.Image, path: Path, quality: int = 82) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jpg":
        img.convert("RGB").save(path, quality=quality, optimize=True, progressive=False)
    else:
        img.save(path, optimize=True)
    return path


def noise_layer(w: int, h: int, sigma: float, rng: np.random.Generator) -> np.ndarray:
    return rng.normal(0.0, sigma, (h, w, 1)).astype(np.float32)


def smooth_noise(w: int, h: int, scale: int, rng: np.random.Generator) -> np.ndarray:
    """Value noise 0..1 with features about `scale` pixels wide (a few octaves)."""
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    s = scale
    while s >= 8:
        small = rng.random((max(2, h // s + 2), max(2, w // s + 2))).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8)).resize((w + 2 * s, h + 2 * s), Image.BICUBIC)
        out += amp * np.asarray(img, np.float32)[s:s + h, s:s + w] / 255.0
        total += amp
        amp *= 0.5
        s //= 2
    return out / total


# ================================================================ backgrounds: tactical plot, map grid
def radar_plot(w: int, h: int) -> Image.Image:
    rng = random.Random(SEED + w)
    img = Image.new("RGB", (w, h), rgb(CONSOLE["background"]))
    # faint clutter speckles
    arr = np.asarray(img, np.float32)
    nrng = np.random.default_rng(SEED + w)
    speck = (nrng.random((h, w)) > 0.9985).astype(np.float32)[..., None] * np.array([40, 110, 90], np.float32)
    img = Image.fromarray(np.clip(arr + speck, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy = w / 2, h / 2
    rmax = min(w, h) / 2 - 36
    # sweep wedge: a fading sector behind the current bearing
    sweep = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(sweep)
    for i in range(40):
        a0 = -60 - i * 1.0
        sd.pieslice([cx - rmax, cy - rmax, cx + rmax, cy + rmax], a0 - 1.2, a0, fill=int(70 * (1 - i / 40)))
    img.paste(Image.new("RGB", (w, h), (20, 200, 150)), (0, 0), sweep)
    grid = rgb(CONSOLE["grid"], 255)
    label = font(13)
    for k in range(1, 6):                                   # range rings
        r = rmax * k / 5
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=grid, width=1 if k < 5 else 2)
        d.text((cx + 4, cy - r + 2), f"{k * 10}", fill=rgb(CONSOLE["text"], 150), font=label)
    for b in range(0, 360, 30):                             # bearing lines and labels
        a = math.radians(b - 90)
        d.line([cx, cy, cx + rmax * math.cos(a), cy + rmax * math.sin(a)], fill=rgb(CONSOLE["grid"], 170), width=1)
        tx, ty = cx + (rmax + 12) * math.cos(a), cy + (rmax + 12) * math.sin(a)
        d.text((tx, ty), f"{b:03d}", fill=rgb(CONSOLE["text"], 170), font=label, anchor="mm")
    for b in range(0, 360, 5):                              # bearing ticks on the outer ring
        a = math.radians(b - 90)
        r0 = rmax - (8 if b % 30 == 0 else 4)
        d.line([cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + rmax * math.cos(a), cy + rmax * math.sin(a)],
               fill=grid, width=1)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=rgb(CONSOLE["accent"]))   # own position
    if w > h:                                               # wide version: side strips for panels
        d.text((16, 14), "PLOT  RANGE 50", fill=rgb(CONSOLE["text"], 200), font=font(15, True))
        d.text((w - 16, 14), "SECTOR BRAVO", fill=rgb(CONSOLE["text"], 200), font=font(15, True), anchor="ra")
    _ = rng
    return img


def map_grid(w: int, h: int) -> Image.Image:
    nrng = np.random.default_rng(SEED + 7 + w)
    land = smooth_noise(w, h, 260, nrng)
    water = np.array([10, 28, 44], np.float32)
    ground = np.array([30, 44, 38], np.float32)
    high = np.array([52, 62, 50], np.float32)
    t = np.clip((land - 0.48) * 12, 0, 1)[..., None]
    hh = np.clip((land - 0.62) * 6, 0, 1)[..., None]
    arr = water * (1 - t) + (ground * (1 - hh) + high * hh) * t
    img = Image.fromarray(arr.astype(np.uint8))
    # coastline: a thin brighter edge where land meets water
    above = land > 0.48
    shore = np.zeros_like(above)
    shore[:-1, :] |= above[:-1, :] != above[1:, :]
    shore[:, :-1] |= above[:, :-1] != above[:, 1:]
    edge = Image.fromarray((shore * 255).astype(np.uint8))
    img.paste(Image.new("RGB", (w, h), (90, 140, 150)), (0, 0), edge)
    d = ImageDraw.Draw(img, "RGBA")
    step = 80
    f = font(12)
    for i, x in enumerate(range(0, w + 1, step)):
        d.line([x, 0, x, h], fill=rgb(CONSOLE["grid"], 200), width=1)
        if x + step <= w:
            d.text((x + step / 2, 4), chr(65 + i % 26), fill=rgb(CONSOLE["text"], 160), font=f, anchor="ma")
    for j, y in enumerate(range(0, h + 1, step)):
        d.line([0, y, w, y], fill=rgb(CONSOLE["grid"], 200), width=1)
        if y + step <= h:
            d.text((4, y + step / 2), f"{j + 1:02d}", fill=rgb(CONSOLE["text"], 160), font=f, anchor="lm")
    big = font(16, True)
    for (fx, fy, name) in ((0.25, 0.25, "ALPHA"), (0.75, 0.25, "BRAVO"), (0.25, 0.75, "CHARLIE"), (0.75, 0.75, "DELTA")):
        d.text((w * fx, h * fy), f"SECTOR {name}", fill=(62, 100, 116), font=big, anchor="mm")
    d.line([w / 2, 0, w / 2, h], fill=(159, 232, 255, 60), width=2)
    d.line([0, h / 2, w, h / 2], fill=(159, 232, 255, 60), width=2)
    return img


# ================================================================ spectrum and waterfall (all generic, relative units)
WF_MAP = np.array([[0, 0, 0], [8, 16, 60], [0, 90, 160], [0, 200, 200], [240, 230, 60], [255, 90, 30], [255, 255, 255]],
                  np.float32)


def colormap(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0, 1) * (len(WF_MAP) - 1)
    i = np.minimum(v.astype(int), len(WF_MAP) - 2)
    f = (v - i)[..., None]
    return WF_MAP[i] * (1 - f) + WF_MAP[i + 1] * f


PLOT_BOX = (70, 50, 1250, 690)     # the data area of spectrum / waterfall pictures (x0, y0, x1, y1)


def axes(img: Image.Image, title: str, ylabel: str) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = PLOT_BOX
    f = font(12)
    d.rectangle([x0, y0, x1, y1], outline=rgb(CONSOLE["grid"], 255), width=1)
    for k in range(11):
        x = x0 + (x1 - x0) * k / 10
        d.line([x, y1, x, y1 + 6], fill=rgb(CONSOLE["text"], 200))
        d.text((x, y1 + 8), f"CH {k * 10}", fill=rgb(CONSOLE["text"], 180), font=f, anchor="ma")
    d.text((x0, 18), title, fill=rgb(CONSOLE["text"], 220), font=font(15, True))
    d.text((x1, 18), "relative units, synthetic", fill=rgb(CONSOLE["text"], 140), font=f, anchor="ra")
    d.text((20, (y0 + y1) / 2), ylabel, fill=rgb(CONSOLE["text"], 160), font=f, anchor="mm")


def spectrum_bg() -> Image.Image:
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), (2, 10, 14))
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = PLOT_BOX
    for k in range(1, 10):
        x = x0 + (x1 - x0) * k / 10
        d.line([x, y0, x, y1], fill=rgb(CONSOLE["grid"], 120))
    for k in range(1, 8):
        y = y0 + (y1 - y0) * k / 8
        d.line([x0, y, x1, y], fill=rgb(CONSOLE["grid"], 120))
    rng = np.random.default_rng(SEED + 31)
    n = x1 - x0
    floor = 0.12 + 0.03 * smooth_noise(n, 1, 120, rng)[0] + rng.normal(0, 0.012, n)
    ys = y1 - floor * (y1 - y0)
    d.line(list(zip(range(x0, x1), ys.tolist())), fill=(60, 255, 160, 230), width=1)
    axes(img, "SPECTRUM", "level")
    return img


def waterfall(pattern: str, seed: int) -> Image.Image:
    """A waterfall (time runs downwards) of noise plus made-up emitters drawn by `pattern`."""
    w, h = 1280, 720
    x0, y0, x1, y1 = PLOT_BOX
    pw, ph = x1 - x0, y1 - y0
    rng = np.random.default_rng(seed)
    v = 0.2 + 0.06 * smooth_noise(pw, ph, 64, rng) + rng.normal(0, 0.05, (ph, pw))
    yy, xx = np.mgrid[0:ph, 0:pw]

    def line(cx: float, width: float, level: float, on: np.ndarray | None = None) -> None:
        prof = level * np.exp(-((xx - cx) ** 2) / (2 * width ** 2))
        v[:] += prof if on is None else prof * on

    if pattern in ("continuous", "mixed"):
        for cx, wd, lv in ((pw * 0.18, 2.5, 0.55), (pw * 0.46, 4, 0.45), (pw * 0.83, 2, 0.6)):
            line(cx, wd, lv)
    if pattern in ("pulsed", "mixed"):
        for cx, period, duty in ((pw * 0.3, 26, 0.35), (pw * 0.64, 40, 0.25)):
            on = ((yy % period) < period * duty).astype(np.float32)
            line(cx, 3, 0.7, on)
    if pattern == "hopping":
        for _ in range(70):
            y = int(rng.integers(0, ph - 12))
            cx = float(rng.integers(20, pw - 20))
            on = ((yy >= y) & (yy < y + 10)).astype(np.float32)
            line(cx, 3, 0.65, on)
    if pattern == "sweep":
        for start, slope in ((0.0, 2.2), (0.5, 2.2)):
            cx = ((start * pw + yy * slope) % pw)
            v[:] += 0.55 * np.exp(-((xx - cx) ** 2) / (2 * 3.0 ** 2))
    if pattern in ("wideband", "mixed"):
        band = ((xx > pw * 0.52) & (xx < pw * 0.6)).astype(np.float32)
        v[:] += band * (0.18 + 0.08 * rng.random((ph, pw)))
    img = Image.new("RGB", (w, h), (2, 10, 14))
    img.paste(Image.fromarray(colormap(v).astype(np.uint8)), (x0, y0))
    title = {"empty": "WATERFALL", "continuous": "WATERFALL  pattern: continuous carriers",
             "pulsed": "WATERFALL  pattern: pulsed", "hopping": "WATERFALL  pattern: short bursts (hopping)",
             "sweep": "WATERFALL  pattern: sweeps", "wideband": "WATERFALL  pattern: wideband",
             "mixed": "WATERFALL  pattern: mixed"}[pattern]
    axes(img, title, "time")
    return img


# ================================================================ terrain (synthetic camera frames, top-down)
FIELD_COLOURS = [(96, 120, 62), (120, 132, 70), (140, 128, 84), (84, 104, 56), (150, 142, 96), (110, 98, 66),
                 (128, 140, 92), (76, 92, 52)]


def split_fields(rng: random.Random, box: tuple, depth: int, out: list) -> None:
    x0, y0, x1, y1 = box
    if depth == 0 or (x1 - x0) < 120 or (y1 - y0) < 90:
        out.append(box)
        return
    if (x1 - x0) > (y1 - y0) * rng.uniform(0.8, 1.4):
        c = rng.uniform(x0 + (x1 - x0) * 0.3, x0 + (x1 - x0) * 0.7)
        split_fields(rng, (x0, y0, c, y1), depth - 1, out)
        split_fields(rng, (c, y0, x1, y1), depth - 1, out)
    else:
        c = rng.uniform(y0 + (y1 - y0) * 0.3, y0 + (y1 - y0) * 0.7)
        split_fields(rng, (x0, y0, x1, c), depth - 1, out)
        split_fields(rng, (x0, c, x1, y1), depth - 1, out)


def terrain(w: int, h: int, seed: int, style: str = "farmland", fixed_roads: list | None = None) -> tuple[Image.Image, list]:
    """A top-down synthetic landscape. Returns (picture, roads) where roads are polylines (for moving vehicles);
    ``fixed_roads`` draws these polylines instead of random roads."""
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    base = {"farmland": (104, 118, 66), "village": (112, 116, 76), "forest": (60, 82, 46), "river": (100, 118, 70),
            "desert": (168, 150, 112)}.get(style, (104, 118, 66))
    img = Image.new("RGB", (w, h), base)
    d = ImageDraw.Draw(img, "RGBA")
    fields: list = []
    split_fields(rng, (-40, -40, w + 40, h + 40), 7 if style != "desert" else 4, fields)
    for (x0, y0, x1, y1) in fields:
        if style == "forest" and rng.random() < 0.55:
            continue
        col = rng.choice(FIELD_COLOURS)
        if style == "desert":
            col = tuple(min(255, int(c * 0.5 + b * 0.6)) for c, b in zip(col, base))
        j = lambda: rng.uniform(-10, 10)  # noqa: E731
        poly = [(x0 + 3 + j(), y0 + 3 + j()), (x1 - 3 + j(), y0 + 3 + j()), (x1 - 3 + j(), y1 - 3 + j()),
                (x0 + 3 + j(), y1 - 3 + j())]
        d.polygon(poly, fill=col)
        if rng.random() < 0.45:                       # plough lines
            dark = tuple(max(0, c - 14) for c in col)
            step = rng.choice((6, 8, 10))
            if rng.random() < 0.5:
                for x in np.arange(x0 + 6, x1 - 6, step):
                    d.line([x, y0 + 8, x, y1 - 8], fill=dark, width=2)
            else:
                for y in np.arange(y0 + 6, y1 - 6, step):
                    d.line([x0 + 8, y, x1 - 8, y], fill=dark, width=2)
    # tree clusters / forest
    n_trees = {"forest": 2600, "village": 500, "desert": 60}.get(style, 700)
    centres = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(max(3, n_trees // 60))]
    for _ in range(n_trees):
        cx, cy = rng.choice(centres)
        x, y = cx + rng.gauss(0, 60), cy + rng.gauss(0, 45)
        r = rng.uniform(4, 9)
        d.ellipse([x - r + 2, y - r + 3, x + r + 2, y + r + 3], fill=(20, 26, 14, 90))
        g = rng.randint(50, 80)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(g - 20, g + 10, g - 30))
    roads: list = []
    if style == "river":
        pts = [(x, h * 0.55 + 70 * math.sin(x / 170.0 + seed) + 30 * math.sin(x / 61.0)) for x in range(-20, w + 30, 20)]
        d.line(pts, fill=(64, 84, 92), width=34, joint="curve")
        d.line(pts, fill=(78, 104, 116), width=24, joint="curve")
    # roads: a few straight-ish polylines across the frame
    n_roads = {"village": 4, "desert": 2, "forest": 1}.get(style, 3)
    for k in range(n_roads if fixed_roads is None else len(fixed_roads)):
        if fixed_roads is not None:
            pts = fixed_roads[k]
        elif k % 2 == 0:
            y = rng.uniform(h * 0.15, h * 0.85)
            pts = [(-50, y), (w * 0.35, y + rng.uniform(-60, 60)), (w * 0.7, y + rng.uniform(-60, 60)), (w + 50, y + rng.uniform(-40, 40))]
        else:
            x = rng.uniform(w * 0.15, w * 0.85)
            pts = [(x, -50), (x + rng.uniform(-60, 60), h * 0.5), (x + rng.uniform(-60, 60), h + 50)]
        roads.append(pts)
        d.line(pts, fill=(70, 70, 64), width=16, joint="curve")
        d.line(pts, fill=(132, 128, 116), width=12, joint="curve")
    # buildings
    n_build = {"village": 90, "farmland": 18, "river": 14, "forest": 4, "desert": 30}.get(style, 15)
    anchors = [rng.choice(roads) for _ in range(n_build)] if roads else []
    for pts in anchors:
        a, b = rng.sample(range(len(pts)), 2) if len(pts) > 1 else (0, 0)
        t = rng.random()
        x = pts[a][0] * (1 - t) + pts[b][0] * t + rng.choice((-1, 1)) * rng.uniform(18, 70)
        y = pts[a][1] * (1 - t) + pts[b][1] * t + rng.choice((-1, 1)) * rng.uniform(18, 70)
        bw, bh = rng.uniform(14, 34), rng.uniform(10, 24)
        roof = rng.choice([(150, 70, 60), (120, 120, 124), (170, 160, 150), (90, 92, 96), (180, 110, 80)])
        d.rectangle([x + 4, y + 5, x + bw + 4, y + bh + 5], fill=(10, 12, 8, 110))       # shadow
        d.rectangle([x, y, x + bw, y + bh], fill=roof)
        d.line([x, y + bh / 2, x + bw, y + bh / 2], fill=tuple(max(0, c - 25) for c in roof), width=1)
    # sensor look: soft blur, haze, vignette, grain
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    arr = np.asarray(img, np.float32)
    haze_amt = {"desert": 0.38, "forest": 0.12}.get(style, 0.2)
    haze_col = np.array([186, 196, 206], np.float32) if style != "desert" else np.array([214, 190, 160], np.float32)
    hz = haze_amt * (0.6 + 0.8 * smooth_noise(w, h, 320, nrng))[..., None]
    arr = arr * (1 - hz) + haze_col * hz
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1 - 0.28 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)[..., None]
    arr = arr * vig + noise_layer(w, h, 5.0, nrng)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), roads


def infrared(img: Image.Image) -> Image.Image:
    """'White-hot' look: grey, roads and roofs bright, vegetation dark."""
    arr = np.asarray(img, np.float32)
    lum = 0.2 * arr[..., 0] + 0.3 * arr[..., 1] + 0.5 * arr[..., 2] - 0.35 * (arr[..., 1] - arr[..., 2])
    lum = (lum - lum.min()) / max(1.0, lum.max() - lum.min()) * 220 + 15
    return Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).convert("RGB")


def dusk(img: Image.Image) -> Image.Image:
    arr = np.asarray(img, np.float32) * np.array([0.8, 0.7, 0.6], np.float32) + np.array([6, 8, 20], np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ================================================================ symbols (generic track symbols)
def frame_mask(shape: str, s: int) -> Image.Image:
    """The frame's filled area on an s x s canvas (s is the supersampled size)."""
    m = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(m)
    c = s / 2
    if shape == "rectangle":                 # friendly: wider than high
        d.rectangle([c - 0.46 * s, c - 0.30 * s, c + 0.46 * s, c + 0.30 * s], fill=255)
    elif shape == "square":                  # neutral
        d.rectangle([c - 0.34 * s, c - 0.34 * s, c + 0.34 * s, c + 0.34 * s], fill=255)
    elif shape == "diamond":                 # hostile
        r = 0.46 * s
        d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=255)
    elif shape == "quatrefoil":              # unknown: four overlapping lobes
        r, off = 0.2 * s, 0.22 * s
        for dx, dy in ((-off, 0), (off, 0), (0, -off), (0, off)):
            d.ellipse([c + dx - r, c + dy - r, c + dx + r, c + dy + r], fill=255)
        d.rectangle([c - off, c - off, c + off, c + off], fill=255)
    return m


def draw_icon(d: ImageDraw.ImageDraw, kind: str, s: int, col: tuple) -> None:
    """A generic dimension icon in the frame's centre: air (swept wing), surface (hull), ground (vehicle outline)."""
    c = s / 2
    lw = max(2, int(s * 0.06))
    if kind == "air":
        d.line([(c - 0.2 * s, c + 0.08 * s), (c, c - 0.14 * s), (c + 0.2 * s, c + 0.08 * s)], fill=col, width=lw, joint="curve")
        d.line([(c, c - 0.16 * s), (c, c + 0.16 * s)], fill=col, width=lw)
    elif kind == "surface":
        d.polygon([(c - 0.22 * s, c - 0.02 * s), (c + 0.22 * s, c - 0.02 * s), (c + 0.14 * s, c + 0.12 * s),
                   (c - 0.14 * s, c + 0.12 * s)], fill=col)
        d.rectangle([c - 0.06 * s, c - 0.12 * s, c + 0.06 * s, c - 0.02 * s], fill=col)
    elif kind == "ground":
        d.rounded_rectangle([c - 0.2 * s, c - 0.1 * s, c + 0.2 * s, c + 0.1 * s], radius=0.09 * s, outline=col, width=lw)


def symbol(affil: str, kind: str, size: int) -> Image.Image:
    ss = size * 4
    m = frame_mask(AFFIL_FRAME[affil], ss)
    stroke = m.filter(ImageFilter.MaxFilter(2 * max(1, ss // 40) + 1))
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (ss, ss), (0, 0, 0, 255)), (0, 0), stroke)
    img.paste(Image.new("RGBA", (ss, ss), rgb(AFFIL[affil], 255)), (0, 0), m)
    draw_icon(ImageDraw.Draw(img), kind, ss, (0, 0, 0, 255))
    return img.resize((size, size), Image.LANCZOS)


# ================================================================ vehicles (top-down, pointing up)
def vehicle(kind: str, tone: str, size: int = 48) -> Image.Image:
    ss = size * 4
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = ss / 2
    body = (226, 224, 214, 255) if tone == "light" else (52, 54, 44, 255)
    edge = (30, 30, 26, 255) if tone == "light" else (190, 190, 176, 255)
    shadow = (0, 0, 0, 90)
    if kind == "tracked":
        w2, h2 = 0.22 * ss, 0.38 * ss
        d.rounded_rectangle([c - w2 + 10, c - h2 + 12, c + w2 + 10, c + h2 + 12], radius=12, fill=shadow)
        d.rounded_rectangle([c - w2, c - h2, c + w2, c + h2], radius=12, fill=body, outline=edge, width=5)
        for sx in (-1, 1):                    # tracks along both sides
            x = c + sx * (w2 - 0.05 * ss)
            for k in range(9):
                y = c - h2 + 10 + k * (2 * h2 - 20) / 8
                d.line([x - 0.04 * ss, y, x + 0.04 * ss, y], fill=edge, width=4)
        d.rounded_rectangle([c - 0.1 * ss, c - 0.12 * ss, c + 0.1 * ss, c + 0.14 * ss], radius=10, outline=edge, width=4)
    elif kind == "wheeled":
        w2, h2 = 0.17 * ss, 0.4 * ss
        d.rounded_rectangle([c - w2 + 10, c - h2 + 12, c + w2 + 10, c + h2 + 12], radius=10, fill=shadow)
        for k in (-0.26, 0.0, 0.26):          # wheels
            for sx in (-1, 1):
                d.rounded_rectangle([c + sx * w2 - 9, c + k * ss - 16, c + sx * w2 + 9, c + k * ss + 16], radius=5, fill=edge)
        d.rounded_rectangle([c - w2, c - h2, c + w2, c + h2], radius=10, fill=body, outline=edge, width=5)
        d.line([c - w2, c - 0.18 * ss, c + w2, c - 0.18 * ss], fill=edge, width=5)    # cab
    else:                                     # car
        w2, h2 = 0.14 * ss, 0.26 * ss
        d.rounded_rectangle([c - w2 + 8, c - h2 + 10, c + w2 + 8, c + h2 + 10], radius=18, fill=shadow)
        d.rounded_rectangle([c - w2, c - h2, c + w2, c + h2], radius=18, fill=body, outline=edge, width=5)
        d.rounded_rectangle([c - w2 + 10, c - 0.1 * ss, c + w2 - 10, c + 0.08 * ss], radius=8, outline=edge, width=4)
    return img.resize((size, size), Image.LANCZOS)


# ================================================================ emitter marks (waterfall), reticles, boxes, panels
def emitter(kind: str, threat: str) -> Image.Image:
    w, h, k = 28, 84, 4
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = rgb(THREAT[threat], 255)
    glow = rgb(THREAT[threat], 80)
    x0, x1 = w * k * 0.3, w * k * 0.7
    if kind == "continuous":
        d.rounded_rectangle([x0 - 14, 0, x1 + 14, h * k], radius=20, fill=glow)
        d.rounded_rectangle([x0, 6, x1, h * k - 6], radius=12, fill=col)
    else:
        seg = h * k / 9
        for i in range(9):
            if i % 2 == 0:
                y = i * seg
                d.rounded_rectangle([x0 - 14, y - 6, x1 + 14, y + seg + 6], radius=16, fill=glow)
                d.rounded_rectangle([x0, y, x1, y + seg], radius=10, fill=col)
    return img.resize((w, h), Image.LANCZOS)


def outlined_lines(size: tuple, lines: list, colour: tuple, width: int, k: int = 4) -> Image.Image:
    """Lines (and ellipses) in `colour` with a dark outline, so they read on any background."""
    W, H = size[0] * k, size[1] * k
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for col, wd in (((0, 0, 0, 170), width + 2), (colour, width)):
        d = ImageDraw.Draw(img)
        for item in lines:
            if item[0] == "line":
                d.line([v * k for v in item[1]], fill=col, width=wd * k)
            elif item[0] == "ellipse":
                d.ellipse([v * k for v in item[1]], outline=col, width=wd * k)
            elif item[0] == "dot":
                x, y, r = item[1]
                d.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=col)
    return img.resize(size, Image.LANCZOS)


def reticle(style: str) -> Image.Image:
    s, c = 240, 120
    col = (235, 255, 235, 255)
    if style == "cross":                      # thin cross with a gap and range ticks
        lines = [("line", [c, 10, c, c - 14]), ("line", [c, c + 14, c, s - 10]),
                 ("line", [10, c, c - 14, c]), ("line", [c + 14, c, s - 10, c]), ("dot", [c, c, 2])]
        for k in (40, 70, 100):
            lines += [("line", [c - k, c - 6, c - k, c + 6]), ("line", [c + k, c - 6, c + k, c + 6]),
                      ("line", [c - 6, c + k, c + 6, c + k])]
        return outlined_lines((s, s), lines, col, 1)
    if style == "brackets":                   # four corner brackets and a small centre cross
        a, L = 70, 26
        lines = [("line", [c - 8, c, c + 8, c]), ("line", [c, c - 8, c, c + 8])]
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = c + sx * a, c + sy * a
                lines += [("line", [x, y, x - sx * L, y]), ("line", [x, y, x, y - sy * L])]
        return outlined_lines((s, s), lines, col, 2)
    # "circle": ring with cross hairs that stop at the ring, and stadia ticks
    r = 90
    lines = [("ellipse", [c - r, c - r, c + r, c + r]), ("line", [c, c - r, c, c - 12]), ("line", [c, c + 12, c, c + r]),
             ("line", [c - r, c, c - 12, c]), ("line", [c + 12, c, c + r, c]), ("dot", [c, c, 2.5])]
    for k in (30, 60):
        lines += [("line", [c - 5, c + k, c + 5, c + k]), ("line", [c + k, c - 5, c + k, c + 5]), ("line", [c - k, c - 5, c - k, c + 5])]
    return outlined_lines((s, s), lines, col, 2)


def crosshair_full() -> Image.Image:
    w, h, c = 1280, 720, (640, 360)
    col = (235, 255, 235, 200)
    lines = [("line", [0, c[1], c[0] - 40, c[1]]), ("line", [c[0] + 40, c[1], w, c[1]]),
             ("line", [c[0], 0, c[0], c[1] - 40]), ("line", [c[0], c[1] + 40, c[0], h]), ("dot", [c[0], c[1], 2])]
    return outlined_lines((w, h), lines, col, 1, k=2)


def box(state: str, size: int) -> Image.Image:
    """A rounded-rectangle target box. candidate: dashed amber; selected: solid cyan; confirmed: thick red with
    corner ticks; cleared: thin green, half transparent."""
    k = 4
    S = size * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = rgb(STATES[state], 255 if state != "cleared" else 170)
    lw = {"candidate": 2, "selected": 3, "confirmed": 4, "cleared": 2}[state] * k
    m = 4 * k + lw
    rad = S * 0.18
    rect = [m, m, S - m, S - m]
    d.rounded_rectangle([v + (2 if i < 2 else -2) for i, v in enumerate(rect)], radius=rad, outline=(0, 0, 0, 140), width=lw + 2 * k)
    d.rounded_rectangle(rect, radius=rad, outline=col, width=lw)
    if state == "candidate":                  # cut the outline into dashes
        mask = Image.new("L", (S, S), 255)
        md = ImageDraw.Draw(mask)
        dash = S / 8
        for i in range(8):
            md.rectangle([i * dash + dash * 0.62, 0, (i + 1) * dash, S], fill=0)
        mask2 = Image.new("L", (S, S), 255)
        md2 = ImageDraw.Draw(mask2)
        for i in range(8):
            md2.rectangle([0, i * dash + dash * 0.62, S, (i + 1) * dash], fill=0)
        # keep a pixel when it is on a dash both horizontally (top/bottom edges) and vertically (left/right edges)
        a = np.asarray(img).copy()
        horiz = np.asarray(mask) > 0
        vert = np.asarray(mask2) > 0
        yy, xx = np.mgrid[0:S, 0:S]
        on_tb = (yy < S * 0.3) | (yy > S * 0.7)
        keep = np.where(on_tb, horiz, vert)
        a[..., 3] = a[..., 3] * keep
        img = Image.fromarray(a)
        d = ImageDraw.Draw(img)
    if state == "confirmed":                  # corner ticks outside the box
        t = 5 * k
        for x, y, dx, dy in ((m, m, -1, -1), (S - m, m, 1, -1), (m, S - m, -1, 1), (S - m, S - m, 1, 1)):
            d.line([x + dx * 2 * k, y + dy * 2 * k, x + dx * (2 * k + t), y + dy * (2 * k + t)], fill=col, width=lw)
    if state == "selected":                   # small centre-top tab
        d.polygon([(S / 2 - 3 * k, m - lw / 2), (S / 2 + 3 * k, m - lw / 2), (S / 2, m + 4 * k)], fill=col)
    return img.resize((size, size), Image.LANCZOS)


def ring(state: str, size: int = 64) -> Image.Image:
    k = 4
    S = size * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = rgb(STATES[state], 255 if state != "cleared" else 170)
    lw = {"candidate": 2, "selected": 3, "confirmed": 4, "cleared": 2}[state] * k
    m = 6 * k + lw
    d.ellipse([m - 2, m - 2, S - m + 2, S - m + 2], outline=(0, 0, 0, 140), width=lw + 2 * k)
    d.ellipse([m, m, S - m, S - m], outline=col, width=lw)
    if state == "candidate":
        a = np.asarray(img).copy()
        yy, xx = np.mgrid[0:S, 0:S]
        ang = np.degrees(np.arctan2(yy - S / 2, xx - S / 2)) % 30
        a[..., 3] = a[..., 3] * (ang < 19)
        img = Image.fromarray(a)
    return img.resize((size, size), Image.LANCZOS)


def message_panel() -> Image.Image:
    w, h = 400, 240
    k = 2
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=10 * k, fill=(*rgb(CONSOLE["panel"]), 225),
                        outline=(*rgb(CONSOLE["grid"]), 255), width=2 * k)
    d.rounded_rectangle([0, 0, w * k - 1, 34 * k], radius=10 * k, fill=(16, 58, 80, 255))
    d.rectangle([0, 20 * k, w * k - 1, 34 * k], fill=(16, 58, 80, 255))
    d.line([0, 34 * k, w * k, 34 * k], fill=(*rgb(CONSOLE["accent"]), 200), width=k)
    return img.resize((w, h), Image.LANCZOS)


# ================================================================ videos
def ffmpeg_path() -> str | None:
    for p in ("/usr/bin/ffmpeg", shutil.which("ffmpeg")):
        if p and Path(p).is_file():
            return p
    return None


def encode(frames, out: Path, w: int, h: int, fps: int) -> None:
    """Pipe raw RGB frames into ffmpeg: H.264 (libx264), no B-frames, yuv420p, faststart, no audio."""
    ff = ffmpeg_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-bf", "0", "-g", str(fps * 2),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map_metadata", "-1", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for fr in frames:
            proc.stdin.write(fr.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit(f"ffmpeg failed making {out}")


VW, VH, FPS, SECONDS = 640, 360, 25, 10


def camera_frames(world: Image.Image, path_fn, n: int, overlay=None):
    """Crop a moving window out of `world` (path_fn(t in 0..1) -> centre x, centre y, zoom) and scale it to the
    video size. t runs once round a closed path, so the video loops without a jump."""
    W, H = world.size
    grain_rng = np.random.default_rng(SEED + 99)
    grain = [grain_rng.normal(0, 3.0, (VH, VW, 1)).astype(np.float32) for _ in range(4)]
    for i in range(n):
        t = i / n
        cx, cy, zoom = path_fn(t)
        cw, ch = VW * 1.5 / zoom, VH * 1.5 / zoom
        x0 = min(max(cx - cw / 2, 0), W - cw)
        y0 = min(max(cy - ch / 2, 0), H - ch)
        src = world if overlay is None else overlay(world, t)
        fr = src.resize((VW, VH), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))
        arr = np.asarray(fr, np.float32) + grain[i % 4]
        yield Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


WORLD_W, WORLD_H = 1600, 900
# (file name, terrain style, seed, infrared?, camera path t -> (centre x, centre y, zoom), description)
VIDEO_SPECS = [
    ("feed_01_pan", "farmland", 21, False,
     lambda t: (WORLD_W / 2 + 260 * math.sin(2 * math.pi * t), WORLD_H / 2 + 60 * math.sin(4 * math.pi * t), 1.0),
     "Camera feed: slow pan back and forth over farmland (daylight), loops seamlessly."),
    ("feed_02_zoom", "village", 22, False,
     lambda t: (WORLD_W / 2 + 40 * math.sin(2 * math.pi * t), WORLD_H / 2, 1.25 + 0.25 * math.sin(2 * math.pi * t)),
     "Camera feed: slow zoom in and out over a village (daylight), loops seamlessly."),
    ("feed_03_orbit_ir", "river", 23, True,
     lambda t: (WORLD_W / 2 + 180 * math.cos(2 * math.pi * t), WORLD_H / 2 + 100 * math.sin(2 * math.pi * t), 1.1),
     "Camera feed (infrared, white-hot): slow circular drift over a river valley, loops seamlessly."),
    ("feed_04_vehicles", "farmland", 24, False,
     lambda t: (WORLD_W / 2 + 120 * math.sin(2 * math.pi * t), WORLD_H / 2 + 40 * math.cos(2 * math.pi * t), 1.15),
     "Camera feed with generic vehicles driving along the roads (daylight), loops seamlessly."),
]


def note_video(name: str, desc: str) -> None:
    note(KIT / "video" / f"{name}.mp4", desc, ["uav", "video"], size=[VW, VH], seconds=SECONDS, fps=FPS, loops=True,
         moving_vehicles=name.endswith("vehicles"))


def make_videos(world_specs: list) -> None:
    n = FPS * SECONDS
    for name, style, seed, ir, path_fn, desc in world_specs:
        fixed = VEHICLE_ROADS if name.endswith("vehicles") else None
        world, roads = terrain(WORLD_W, WORLD_H, seed, style, fixed)
        if ir:
            world = infrared(world)
        overlay = None
        if name.endswith("vehicles"):
            overlay = vehicle_overlay(roads)
        out = KIT / "video" / f"{name}.mp4"
        encode(camera_frames(world, path_fn, n, overlay), out, VW, VH, FPS)
        note_video(name, desc)


# the roads of the vehicles video: they cross the middle of the world, where the camera looks
VEHICLE_ROADS = [[(-60, 400), (500, 430), (1100, 470), (1660, 450)],
                 [(760, -60), (780, 400), (820, 960)],
                 [(-60, 700), (700, 610), (1660, 560)]]
# per road: the vehicle (kind, tone) that drives on it, how many, and which way
VEHICLE_TRAFFIC = [(("wheeled", "light"), 3, 1), (("car", "dark"), 3, -1), (("tracked", "dark"), 2, 1)]


def vehicle_overlay(roads: list):
    """Identical vehicles evenly spaced along each road; in one loop of the video each moves on by one spacing, so
    the last frame leads into the first without a jump (and they drive slowly)."""
    tracks = []
    for pts in roads:
        seglen = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
        tracks.append((pts, seglen, sum(seglen)))
    sprites = [vehicle(k, t, 36) for (k, t), _, _ in VEHICLE_TRAFFIC]

    def at(track, s):
        pts, seglen, total = track
        s %= total
        for (a, b), L in zip(zip(pts, pts[1:]), seglen):
            if s <= L:
                f = s / L
                return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
            s -= L
        return pts[-1][0], pts[-1][1], 0.0

    def overlay(world: Image.Image, t: float) -> Image.Image:
        img = world.copy()
        for tr, sp, (_, count, direction) in zip(tracks, sprites, VEHICLE_TRAFFIC):
            spacing = tr[2] / count
            for i in range(count):
                x, y, ang = at(tr, spacing * (i + direction * t))
                rot = sp.rotate(-ang - 90 + (180 if direction < 0 else 0), expand=True, resample=Image.BICUBIC)
                off = 4 * direction                                # keep to one side of the road
                img.paste(rot, (int(x - rot.width / 2), int(y - rot.height / 2 + off)), rot)
        return img
    return overlay


# ================================================================ kit.yaml
RECIPES = {
    "telemetry_overlay": {
        "about": ("Generic telemetry text in a UAV camera view: four small monospace text items in the corners, "
                  "numbers from variables or expressions so they can change every trial (no picture). Paste the items "
                  "into a screen and set alt / hdg / spd (e.g. in a variable item: alt: \"$random.randint(1800, 2600)\")."),
        "themes": ["uav", "video"],
        "components": [
            {"id": "tel_tl", "type": "text", "font": "DejaVu Sans Mono", "height": 18, "color": "#d8ffd8",
             "pos": [-400, 330], "text": "$f'ALT {alt:>5} m   HDG {hdg:03d}   SPD {spd:>3} kt'"},
            {"id": "tel_tr", "type": "text", "font": "DejaVu Sans Mono", "height": 18, "color": "#d8ffd8",
             "pos": [470, 330], "text": "$f'SENSOR EO   FOV {fov:.1f}'"},
            {"id": "tel_bl", "type": "text", "font": "DejaVu Sans Mono", "height": 18, "color": "#d8ffd8",
             "pos": [-540, -330], "text": "$f'TRACK {track_no:04d}'"},
            {"id": "tel_br", "type": "text", "font": "DejaVu Sans Mono", "height": 18, "color": "#d8ffd8",
             "pos": [580, -330], "text": "REC  ●"},
        ],
        "variables": {"alt": 2200, "hdg": 45, "spd": 90, "fov": 12.5, "track_no": 417},
    },
    "message_panel": {
        "about": ("A message / status panel: panels/message_panel_400x240.png as the background, a header text and up "
                  "to four message lines as text items (change them per trial). Place it in a free corner (here: the "
                  "right edge of a 1280x720 screen). Colours: text #9fe8ff, warning #ffb000, alert #ff3b30."),
        "themes": ["c2", "ew", "uav", "video"],
        "components": [
            {"id": "panel", "type": "image", "image": "stimuli/message_panel_400x240.png", "size": [400, 240],
             "pos": [430, 220]},
            {"id": "panel_head", "type": "text", "font": "DejaVu Sans Mono", "height": 17, "bold": True,
             "color": "#9fe8ff", "pos": [430, 323], "text": "MESSAGES"},
            {"id": "panel_l1", "type": "text", "font": "DejaVu Sans Mono", "height": 16, "color": "#9fe8ff",
             "pos": [430, 270], "wrap_width": 370, "text": "$msg1"},
            {"id": "panel_l2", "type": "text", "font": "DejaVu Sans Mono", "height": 16, "color": "#ffb000",
             "pos": [430, 236], "wrap_width": 370, "text": "$msg2"},
        ],
        "variables": {"msg1": "0412  Track 0417 updated", "msg2": "0413  Sector BRAVO: check contact"},
    },
}


def write_index() -> None:
    import yaml
    total = sum((KIT / e["file"]).stat().st_size for e in INDEX)
    doc = {
        "about": ("Shared stimulus kit of EDGE's operational (defence human-factors) task adaptations. Everything is "
                  "synthetic and generic: drawn by tools/library/make_defense_kit.py (re-run it to make the kit "
                  "again). Copy the files a task needs into its own stimuli/ folder. See docs/library/DEFENSE.md."),
        "generator": "tools/library/make_defense_kit.py",
        "themes": {
            "c2": "Command and control: tactical plot / map with track symbols, a message panel and alerts",
            "uav": "UAV payload operator: camera frame or feed, reticle at the centre, telemetry text, boxed targets",
            "ew": "Electronic-warfare operator: spectrum and waterfall displays, emitter marks, threat colours",
            "video": "Video interface: a feed with a crosshair and rounded-rectangle target boxes in states",
        },
        "palette": {"affiliation": AFFIL, "frame_shape": AFFIL_FRAME, "box_states": STATES, "threat": THREAT,
                    "console": CONSOLE},
        "plot_area": {"spectrum_and_waterfall": {"x0": PLOT_BOX[0], "y0": PLOT_BOX[1], "x1": PLOT_BOX[2],
                                                  "y1": PLOT_BOX[3], "note": "pixel box of the data area in the "
                                                  "1280x720 spectrum / waterfall pictures (origin top left)"}},
        "total_bytes": total,
        "assets": INDEX,
        "recipes": RECIPES,
    }
    class Dumper(yaml.SafeDumper):
        pass

    def short_lists(dumper, data):          # [1280, 720], [c2, uav]: on one line
        flow = all(isinstance(x, (str, int, float)) for x in data) and len(str(data)) < 80
        return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)
    Dumper.add_representer(list, short_lists)
    text = ("# The defence kit's index, written by tools/library/make_defense_kit.py (do not edit by hand: re-run it).\n"
            + yaml.dump(doc, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=110))
    (KIT / "kit.yaml").write_text(text, encoding="utf-8")


# ================================================================ main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-video", action="store_true", help="skip the videos (no ffmpeg needed)")
    a = ap.parse_args(argv)
    if KIT.exists():
        for p in KIT.rglob("*"):
            if p.is_file() and p.suffix in (".png", ".jpg", ".mp4", ".yaml") and not (a.no_video and p.suffix == ".mp4"):
                p.unlink()
    KIT.mkdir(parents=True, exist_ok=True)

    for w, h in ((1280, 720), (800, 800)):
        p = save(radar_plot(w, h), KIT / "backgrounds" / f"plot_radar_{w}x{h}.png")
        note(p, "Tactical plot (radar-scope style): range rings, bearing lines, a sweep, faint clutter; dark console "
             "colours. Place track symbols on it.", ["c2"], size=[w, h])
        p = save(map_grid(w, h), KIT / "backgrounds" / f"map_grid_{w}x{h}.jpg", quality=85)
        note(p, "Map grid: a made-up coastline, an 80 px grid with letters/numbers, four sectors ALPHA-DELTA.",
             ["c2"], size=[w, h])
    p = save(spectrum_bg(), KIT / "backgrounds" / "spectrum_1280x720.png")
    note(p, "Spectrum display: grid, channel axis CH 0-100 (relative units), a flat noise-floor trace.", ["ew"],
         size=[1280, 720])
    p = save(waterfall("empty", SEED + 40), KIT / "backgrounds" / "waterfall_1280x720.jpg", quality=80)
    note(p, "Empty waterfall (noise only, time runs downwards): background for emitter marks.", ["ew"], size=[1280, 720])
    for i, pat in enumerate(("continuous", "pulsed", "hopping", "sweep", "mixed"), 1):
        p = save(waterfall(pat, SEED + 40 + i), KIT / "waterfall" / f"waterfall_{i:02d}_{pat}.jpg", quality=80)
        note(p, f"Waterfall with a made-up '{pat}' emitter pattern (generic, not a real signal).", ["ew"],
             size=[1280, 720], pattern=pat)

    terrains = [("farmland", 11, None, "Daylight camera frame: fields, crossing roads, a few farm buildings."),
                ("village", 12, None, "Daylight camera frame: a village of small buildings along roads."),
                ("forest", 13, None, "Daylight camera frame: forest with clearings and a track."),
                ("river", 14, None, "Daylight camera frame: a river through fields, roads and buildings."),
                ("farmland", 15, "ir", "Infrared ('white-hot') camera frame of farmland: grey, roads and roofs bright."),
                ("desert", 16, "dusk", "Hazy dusk camera frame of dry open terrain with a few buildings.")]
    for i, (style, seed, look, desc) in enumerate(terrains, 1):
        img, _ = terrain(1280, 720, seed, style)
        img = infrared(img) if look == "ir" else dusk(img) if look == "dusk" else img
        tag = style + ("_ir" if look == "ir" else "_dusk" if look == "dusk" else "")
        p = save(img, KIT / "terrain" / f"terrain_{i:02d}_{tag}.jpg", quality=78)
        note(p, desc, ["uav", "video"], size=[1280, 720])

    for affil in AFFIL:
        for kind in DIMENSIONS:
            for s in SYMBOL_SIZES:
                p = save(symbol(affil, kind, s), KIT / "symbols" / f"{affil}_{kind}_{s}.png")
                note(p, f"{affil.capitalize()} {kind} track symbol ({AFFIL_FRAME[affil]} frame, {AFFIL[affil]}), "
                     f"{s} px, transparent.", ["c2"], size=[s, s], affiliation=affil, dimension=kind)
    for kind in ("tracked", "wheeled", "car"):
        for tone in ("light", "dark"):
            p = save(vehicle(kind, tone), KIT / "vehicles" / f"vehicle_{kind}_{tone}.png")
            note(p, f"Generic {kind} vehicle seen from above, {tone} ({'hot in infrared' if tone == 'light' else 'cold in infrared'}), "
                 "pointing up, 48 px, transparent.", ["uav", "video"], size=[48, 48], kind=kind, tone=tone)
    for kind in ("pulsed", "continuous"):
        for threat in THREAT:
            p = save(emitter(kind, threat), KIT / "emitters" / f"emitter_{kind}_{threat}.png")
            note(p, f"Waterfall emitter mark: {kind} ({'dashed' if kind == 'pulsed' else 'solid'} trace), {threat} "
                 f"threat colour {THREAT[threat]}; 28x84, transparent.", ["ew"], size=[28, 84], signal=kind, threat=threat)
    for style, desc in (("cross", "thin cross with a centre gap and range ticks"),
                        ("brackets", "four corner brackets and a small centre cross"),
                        ("circle", "ring with cross hairs and stadia ticks")):
        p = save(reticle(style), KIT / "reticles" / f"reticle_{style}.png")
        note(p, f"Reticle: {desc}; light lines with a dark edge, 240 px, transparent. Put it at the centre.",
             ["uav", "video"], size=[240, 240])
    p = save(crosshair_full(), KIT / "reticles" / "crosshair_full_1280x720.png")
    note(p, "Full-screen crosshair (lines across the whole 1280x720 view, gap at the centre), transparent.",
         ["video", "uav"], size=[1280, 720])
    for state in STATES:
        for s in (64, 96, 128):
            p = save(box(state, s), KIT / "boxes" / f"box_{state}_{s}.png")
            note(p, f"Rounded-rectangle target box, state '{state}' ({STATES[state]}), {s} px, transparent.",
                 ["uav", "video"], size=[s, s], state=state)
        p = save(ring(state), KIT / "boxes" / f"ring_{state}_64.png")
        note(p, f"Round point marker, state '{state}' ({STATES[state]}), 64 px, transparent.", ["uav", "video"],
             size=[64, 64], state=state)
    p = save(message_panel(), KIT / "panels" / "message_panel_400x240.png")
    note(p, "Message / status panel background with a header bar (semi-transparent). Its text is the "
         "'message_panel' recipe below.", ["c2", "ew", "uav", "video"], size=[400, 240])

    if not a.no_video:
        if not ffmpeg_path():
            print("ffmpeg was not found: the videos are left as they are (install ffmpeg, or use --no-video)",
                  file=sys.stderr)
        else:
            make_videos(VIDEO_SPECS)
    else:
        for name, *_, desc in VIDEO_SPECS:                   # keep (and index) the videos made earlier
            if (KIT / "video" / f"{name}.mp4").is_file():
                note_video(name, desc)
    write_index()
    total = sum(f.stat().st_size for f in KIT.rglob("*") if f.is_file())
    print(f"defense kit: {len(INDEX)} files, {total / 1e6:.2f} MB in {KIT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
