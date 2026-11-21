"""Make the pictures and trial lists of the Mackworth clock tasks in the EDGE task library.

    python tools/library/make_mackworth.py          (needs Pillow, only to draw the pictures)

mackworth:  stimuli/dial.png (a clock face with 60 marks), practice.csv (40 steps), ticks.csv (300 steps = 5 min)
mackworth2: stimuli/lamps.png (a ring of 60 unlit lamps), practice.csv (40 steps), ticks.csv (4 periods x 120 steps)

One row = one step of the pointer (1 s). double = 1: the pointer jumps two positions (the signal to report);
after = 1 on the step that follows a signal (responses are accepted during the signal's step and the next one);
period = which part of the session (for the vigilance decrement). Signals are at irregular places, at least
8 steps apart, never in the first 5 steps. Fixed seed: re-running gives the same files.
"""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"
SIZE = 600
C = SIZE / 2


def signals(rng: random.Random, n_steps: int, n_signals: int, min_gap: int = 8, lead: int = 5) -> set[int]:
    while True:
        picks = sorted(rng.sample(range(lead, n_steps - 2), n_signals))
        if all(b - a >= min_gap for a, b in zip(picks, picks[1:])):
            return set(picks)


def rows(rng: random.Random, n_periods: int, steps_per_period: int, per_period: int, name: str) -> list[dict]:
    out = []
    for p in range(n_periods):
        sig = signals(rng, steps_per_period, per_period)
        for i in range(steps_per_period):
            out.append({"block": name, "period": p + 1, "step": p * steps_per_period + i + 1,
                        "double": int(i in sig), "after": int(i - 1 in sig)})
    return out


def write_csv(path: Path, data: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)


def draw_dial(path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([C - 285, C - 285, C + 285, C + 285], fill=(235, 235, 228, 255), outline=(60, 60, 60, 255), width=6)
    for k in range(60):
        a = math.radians(k * 6)
        r0 = 235 if k % 5 else 215
        x0, y0 = C + r0 * math.sin(a), C - r0 * math.cos(a)
        x1, y1 = C + 265 * math.sin(a), C - 265 * math.cos(a)
        d.line([x0, y0, x1, y1], fill=(40, 40, 40, 255), width=3 if k % 5 else 6)
    img.save(path)


def draw_lamps(path: Path) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k in range(60):
        a = math.radians(k * 6)
        x, y = C + 250 * math.sin(a), C - 250 * math.cos(a)
        d.ellipse([x - 10, y - 10, x + 10, y + 10], fill=(70, 70, 78, 255), outline=(120, 120, 130, 255), width=2)
    img.save(path)


def main() -> None:
    rng = random.Random(1948)
    one = ROOT / "mackworth"
    two = ROOT / "mackworth2"
    for folder in (one, two):
        (folder / "stimuli").mkdir(parents=True, exist_ok=True)
    write_csv(one / "practice.csv", rows(rng, 1, 40, 3, "practice"))
    write_csv(one / "ticks.csv", rows(rng, 5, 60, 3, "test"))        # 5 min, 15 signals
    write_csv(two / "practice.csv", rows(rng, 1, 40, 3, "practice"))
    write_csv(two / "ticks.csv", rows(rng, 4, 120, 6, "test"))       # 4 x 2 min, 24 signals
    try:
        draw_dial(one / "stimuli" / "dial.png")
        draw_lamps(two / "stimuli" / "lamps.png")
    except ImportError:
        print("Pillow is not installed: the trial lists were written, the pictures were not (pip install pillow)")
    print("done")


if __name__ == "__main__":
    main()
