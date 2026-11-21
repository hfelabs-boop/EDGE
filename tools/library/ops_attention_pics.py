"""Shared helpers of the attention-group operational adaptations (make_<id>_ops.py for ab, abba, ant, ax_cpt,
cueing, endo_exo_cueing, ior, dotprobe, go_no_go, sart, sart2, stopsignal, flanker, flanker_arrows, maabrams).

  copy_lists(task, base, names)   copy the classic task's trial lists unchanged into the adaptation (or renamed)
  heading_pictures(task)          draw the "which way is it heading" pictures that stand for the arrows of
                                  flanker_arrows, ant and stopsignal (Pillow, from defence-kit pictures):
      c2_heading_left/right/none.png   a hostile surface track with a course leader (a line with an arrowhead
                                       from the frame towards the way it moves); none = no leader (not moving)
      uav_heading_left/right/none.png  a light tracked vehicle seen from above, turned to drive left or right,
                                       with the tracker's cyan motion vector; none = facing up, no vector
All pictures are 120 x 56 px with a transparent background, the symbol / vehicle centred, so a row of them lines up
like a row of arrows.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from kit_copy import KIT, TASKS

W, H = 120, 56


def copy_lists(task: str, base: str, names: list[str] | dict[str, str]) -> None:
    """Copy trial lists of the classic task (edge/library/tasks/<base>/) into tasks/<task>/ unchanged;
    {"sart.csv": "sart_ops.csv"} renames."""
    pairs = names.items() if isinstance(names, dict) else [(n, n) for n in names]
    for src, dst in pairs:
        shutil.copy2(TASKS / base / src, TASKS / task / dst)


def _arrow(draw, y: int, x_from: int, x_to: int, colour: tuple, width: int) -> None:
    draw.line([(x_from, y), (x_to, y)], fill=colour, width=width)
    d = 1 if x_to > x_from else -1
    draw.polygon([(x_to + 4 * d, y), (x_to - 8 * d, y - 7), (x_to - 8 * d, y + 7)], fill=colour)


def heading_pictures(task: str, ways: tuple[str, ...] = ("left", "right", "none")) -> list[Path]:
    from PIL import Image, ImageDraw

    out_dir = TASKS / task / "stimuli"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    # c2: hostile surface track (48 px; the hull icon points nowhere) with a course leader from the diamond's side
    sym = Image.open(KIT / "symbols" / "hostile_surface_48.png").convert("RGBA")
    for way in ways:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        im.alpha_composite(sym, ((W - 48) // 2, (H - 48) // 2))
        if way != "none":
            d = ImageDraw.Draw(im)
            x0 = W // 2 + (24 if way == "right" else -24)
            _arrow(d, H // 2, x0, x0 + (30 if way == "right" else -30), (255, 128, 128, 255), 3)
        p = out_dir / f"c2_heading_{way}.png"
        im.save(p, optimize=True)
        made.append(p)
    # uav: light tracked vehicle (48 px, drawn facing up) turned to face the way it drives, with a motion vector
    veh = Image.open(KIT / "vehicles" / "vehicle_tracked_light.png").convert("RGBA")
    for way in ways:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        v = veh.rotate({"left": 90, "right": -90, "none": 0}[way], expand=True)
        im.alpha_composite(v, ((W - v.width) // 2, (H - v.height) // 2))
        if way != "none":
            d = ImageDraw.Draw(im)
            x0 = W // 2 + (22 if way == "right" else -22)
            _arrow(d, H // 2, x0, x0 + (30 if way == "right" else -30), (0, 229, 255, 255), 3)
        p = out_dir / f"uav_heading_{way}.png"
        im.save(p, optimize=True)
        made.append(p)
    return made
