"""Make the stimuli of digit_substitution_ops, the operational adaptation of the digit symbol substitution test
(edge/library/tasks/digit_substitution_ops/).

    python tools/library/make_digit_substitution_ops.py

Nine symbols per theme, paired with the digits 1-9 in digit_substitution_ops.yaml (variable `symbols`):
  c2  the kit's track symbols: friendly / hostile / neutral x air / surface / ground (48 px)
  ew  waterfall emitter marks: pulsed / continuous x high / medium / low threat from the kit, and three "hopping"
      marks (short offset bursts, drawn here in the kit's style and threat colours): stimuli/emitter_hopping_<threat>.png
Also copies the backgrounds. There is no trial list file (the digits are listed in the flow, as in the classic task).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

from kit_copy import TASKS, copy_from_kit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_defense_kit import THREAT, rgb  # noqa: E402

TASK = "digit_substitution_ops"

KIT_FILES = [
    "backgrounds/map_grid_1280x720.jpg", "backgrounds/waterfall_1280x720.jpg",
    *[f"symbols/{a}_{d}_48.png" for a in ("friendly", "hostile", "neutral") for d in ("air", "surface", "ground")],
    *[f"emitters/emitter_{k}_{t}.png" for k in ("pulsed", "continuous") for t in ("high", "medium", "low")],
]


def hopping(threat: str) -> Image.Image:
    """A 'hopping' emitter mark, 28 x 84 like the kit's: short bursts that jump left and right down the trace."""
    w, h, k = 28, 84, 4
    img = Image.new("RGBA", (w * k, h * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col, glow = rgb(THREAT[threat], 255), rgb(THREAT[threat], 80)
    seg = h * k / 6
    for i, dx in enumerate((-0.22, 0.2, -0.05, 0.24, -0.2, 0.08)):
        cx = w * k * (0.5 + dx)
        y = i * seg + seg * 0.15
        d.rounded_rectangle([cx - 22, y - 6, cx + 22, y + seg * 0.7 + 6], radius=14, fill=glow)
        d.rounded_rectangle([cx - 12, y, cx + 12, y + seg * 0.7], radius=8, fill=col)
    return img.resize((w, h), Image.LANCZOS)


if __name__ == "__main__":
    copied = copy_from_kit(TASK, KIT_FILES)
    for t in ("high", "medium", "low"):
        hopping(t).save(TASKS / TASK / "stimuli" / f"emitter_hopping_{t}.png", optimize=True)
    size = sum(p.stat().st_size for p in (TASKS / TASK / "stimuli").iterdir())
    print(f"{TASK}: {len(copied)} kit files and 3 hopping emitter marks ({size / 1e6:.2f} MB in stimuli/)")
