"""Make the stimuli of the operational 2-back adaptations (edge/library/tasks/{nback2_ops, nback2_phone_ops,
touch_nback2_ops}/).

    python tools/library/make_nback2_ops.py

Everything comes from the shared defence kit (edge/library/defense_kit/, made by make_defense_kit.py); this script
only copies the files each task shows into its own stimuli/ folder, so a copy of the task is self-contained, and
copies the classic tasks' trial lists unchanged (practice.csv and main.csv of nback2 / nback2_phone / touch_nback2,
made by make_nback2.py): the letter column stays, and each theme names the ten letters its own way (the variable
`names` in the experiment):

  c2   a track number next to an unknown-air track symbol on the tactical plot   (B -> TRK 0417 ...)
  ew   an emitter type code under an emitter mark on the spectrum display        (B -> TYPE 21 ...)
  uav  the grid sector the camera is looking at, in the camera overlay           (B -> SECTOR BRAVO ...)
"""

from __future__ import annotations

import shutil

from kit_copy import TASKS, copy_from_kit

# adaptation -> (base task, background of the c2 plot: wide for landscape screens, square for the phone)
ADAPTATIONS = {"nback2_ops": ("nback2", "backgrounds/plot_radar_1280x720.png"),
               "nback2_phone_ops": ("nback2_phone", "backgrounds/plot_radar_800x800.png"),
               "touch_nback2_ops": ("touch_nback2", "backgrounds/plot_radar_1280x720.png")}

COMMON = [
    "symbols/unknown_air_64.png",                       # c2: the track whose number is reported
    "backgrounds/spectrum_1280x720.png", "emitters/emitter_pulsed_medium.png",   # ew
    "terrain/terrain_01_farmland.jpg", "reticles/reticle_brackets.png",          # uav
]


if __name__ == "__main__":
    for task, (base, plot) in ADAPTATIONS.items():
        copied = copy_from_kit(task, [plot, *COMMON])
        for name in ("practice.csv", "main.csv"):
            shutil.copyfile(TASKS / base / name, TASKS / task / name)
        size = sum(p.stat().st_size for p in copied)
        print(f"{task}: {len(copied)} kit files ({size / 1e6:.2f} MB) and the trial lists of {base}")
