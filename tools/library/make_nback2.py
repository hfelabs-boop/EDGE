"""Make the letter sequences (trial lists) of the 2-back tasks in the EDGE task library.

    python tools/library/make_nback2.py

Writes practice.csv and main.csv (blocks 1-3 one after the other, column 'block') into
edge/library/tasks/{nback2, nback2_phone, touch_nback2}.
Each block starts with 2 filler letters (nothing to compare with yet), followed by trials of which one third
are targets (the letter shown two trials back). Non-targets never repeat the letter one or two back, so the
only repeats are the real 2-back matches. Fixed seed: re-running gives the same lists.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

LETTERS = list("BCDFGHKLMNPRSTVZ")[:10]      # ten consonants: B C D F G H K L M N
TASKS = ["nback2", "nback2_phone", "touch_nback2"]
ROOT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks"


def block(rng: random.Random, n_scored: int, n_targets: int, name: str) -> list[dict]:
    kinds = ["target"] * n_targets + ["nontarget"] * (n_scored - n_targets)
    while True:                                  # no more than two targets in a row
        rng.shuffle(kinds)
        if all(not (kinds[i] == kinds[i + 1] == kinds[i + 2] == "target") for i in range(len(kinds) - 2)):
            break
    seq: list[str] = []
    rows = []
    for i, kind in enumerate(["filler", "filler"] + kinds):
        if kind == "target":
            letter = seq[-2]
        else:
            avoid = set(seq[-2:])
            letter = rng.choice([x for x in LETTERS if x not in avoid])
        seq.append(letter)
        is_target = int(kind == "target")
        rows.append({"block": name, "trial": i + 1, "letter": letter, "cond": kind, "target": is_target,
                     "corr_key": "space" if is_target else "none",
                     "corr_button": "b_match" if is_target else "b_nomatch",
                     "last_in_block": int(i == n_scored + 1)})
    return rows


def main() -> None:
    rng = random.Random(20261121)
    lists = {"practice": block(rng, 20, 7, "practice"), "main": []}
    for b in (1, 2, 3):
        lists["main"] += block(rng, 30, 10, f"block{b}")
    for task in TASKS:
        folder = ROOT / task
        folder.mkdir(parents=True, exist_ok=True)
        for name, rows in lists.items():
            with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8") as f:   # (csv writes CRLF)
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        print(f"wrote {len(lists)} trial lists to {folder}")


if __name__ == "__main__":
    main()
