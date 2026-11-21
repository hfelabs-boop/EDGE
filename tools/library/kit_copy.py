"""Copy files of the shared defence kit (edge/library/defense_kit/) into an adaptation's own stimuli/ folder.

Every operational adaptation (edge/library/tasks/<id>_ops/) is self-contained: `edge library new` copies only the
task's folder, so the kit files it shows must be inside it. Use this from the adaptation's generator:

    # tools/library/make_<id>_ops.py
    from kit_copy import copy_from_kit
    copy_from_kit("stroop_ops", ["symbols/hostile_air_48.png", "backgrounds/map_grid_1280x720.jpg"])

Files land flat in edge/library/tasks/<task>/stimuli/ under their own names (stimuli/hostile_air_48.png); pass
{"kit/path.png": "new_name.png"} to rename. Files of that stimuli/ folder that came from the kit earlier but are no
longer wanted are NOT deleted (the folder can hold the task's own pictures too); delete them by hand.
Run the defence kit generator first if the kit is missing: python tools/library/make_defense_kit.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "edge" / "library" / "defense_kit"
TASKS = ROOT / "edge" / "library" / "tasks"


def copy_from_kit(task: str, files: list[str] | dict[str, str], subfolder: str = "stimuli") -> list[Path]:
    """Copy kit files (paths relative to defense_kit/) into tasks/<task>/<subfolder>/; returns the copies."""
    pairs = files.items() if isinstance(files, dict) else [(f, Path(f).name) for f in files]
    dest = TASKS / task / subfolder
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for src, name in pairs:
        s = KIT / src
        if not s.is_file():
            raise SystemExit(f"{src} is not in the defence kit (see edge/library/defense_kit/kit.yaml; "
                             "make the kit with: python tools/library/make_defense_kit.py)")
        out.append(Path(shutil.copy2(s, dest / name)))
    return out
