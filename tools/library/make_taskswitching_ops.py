"""Make the operational adaptations of task switching (edge/library/tasks/taskswitching_ops/ and taskswitching_cued_ops/).

    python tools/library/make_taskswitching_ops.py

The letter-digit pair of the classic tasks becomes one CONTACT that has two attributes, and the two tasks judge
one attribute each (A key / L key), exactly like the letter task and the digit task:
  identity task   c2: AFFILIATION, hostile = A, friendly = L       ew: THREAT, high = A, low = L
  kind task       c2: DOMAIN, air = A, surface = L                 ew: SIGNAL, pulsed = A, continuous = L
In the trial lists a contact is coded theme-free as identity (hostile / friendly) x kind (air / surface); the
experiment's variable `looks` gives each theme's picture for it (c2: the track symbol; ew: the emitter trace, with
hostile = high threat and air = pulsed). Each of the 4 contacts appears 4 times with different track numbers (16
rows, like the 16 letter-digit pairs), so half the rows are congruent (both tasks give the same key).
  taskswitching_ops/stimuli.csv       16 rows (the alternating-runs task takes the task from the grid position)
  taskswitching_cued_ops/trials.csv   the 16 rows x task (identity / kind) x cue-target interval (0.2 / 1.0 s)
"""

from __future__ import annotations

import csv

from kit_copy import TASKS, copy_from_kit

KIT_FILES = [
    "backgrounds/plot_radar_1280x720.png", "backgrounds/spectrum_1280x720.png",
    "symbols/hostile_air_64.png", "symbols/hostile_surface_64.png",
    "symbols/friendly_air_64.png", "symbols/friendly_surface_64.png",
    "emitters/emitter_pulsed_high.png", "emitters/emitter_continuous_high.png",
    "emitters/emitter_pulsed_low.png", "emitters/emitter_continuous_low.png",
]
TRACK_NOS = [[214, 388, 507, 731], [126, 452, 619, 873], [341, 566, 702, 958], [183, 295, 640, 817]]


def rows() -> list[list]:
    out = []
    for i, (identity, kind) in enumerate([(a, b) for a in ("hostile", "friendly") for b in ("air", "surface")]):
        identity_key = "a" if identity == "hostile" else "l"
        kind_key = "a" if kind == "air" else "l"
        for no in TRACK_NOS[i]:
            out.append([f"{identity}_{kind}", identity, kind, no, identity_key, kind_key,
                        "congruent" if identity_key == kind_key else "incongruent"])
    return out


def main() -> None:
    cols = ["contact", "identity", "kind", "track_no"]
    for task in ("taskswitching_ops", "taskswitching_cued_ops"):
        copy_from_kit(task, KIT_FILES)
    with (TASKS / "taskswitching_ops" / "stimuli.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols + ["identity_key", "kind_key", "congruency"])
        w.writerows(rows())
    with (TASKS / "taskswitching_cued_ops" / "trials.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols + ["task", "cti", "correct_key", "congruency"])
        for contact, identity, kind, no, identity_key, kind_key, congruency in rows():
            for task in ("identity", "kind"):
                for cti in (0.2, 1.0):
                    w.writerow([contact, identity, kind, no, task, cti,
                                identity_key if task == "identity" else kind_key, congruency])
    print("taskswitching_ops: stimuli.csv (16 rows); taskswitching_cued_ops: trials.csv (64 rows); kit pictures copied")


if __name__ == "__main__":
    main()
