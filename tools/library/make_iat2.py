"""Write the trial lists of the IAT in edge/library/tasks/iat2 (re-runnable).

To measure a different association:
  1. change the four word lists below (two target categories, two attribute categories) and run
         python tools/library/make_iat2.py
  2. change the four category names under `variables:` at the top of iat2.yaml (cat_a, cat_b, attr_pos, attr_neg).
Nothing else needs changing: iat2.yaml works out the keys, the corner labels and the pairing from the role of each
word (target_a, target_b, positive, negative), the block and the participant's order.
Target A is the category expected to go with the positive attribute in the "compatible" blocks.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

TARGET_A = ["rose", "tulip", "daisy", "lily", "orchid", "violet", "poppy", "iris"]               # Flowers
TARGET_B = ["wasp", "flea", "mosquito", "beetle", "cockroach", "hornet", "moth", "gnat"]         # Insects
POSITIVE = ["joy", "love", "peace", "laughter", "happy", "sunshine", "gentle", "wonderful"]      # Pleasant
NEGATIVE = ["agony", "awful", "horrible", "nasty", "pain", "failure", "hurt", "disaster"]        # Unpleasant

# trials per block (Greenwald, Nosek & Banaji, 2003: 20 / 20 / 20 / 40 / 40 / 20 / 40)
N = {1: 20, 2: 20, 3: 20, 4: 40, 5: 40, 6: 20, 7: 40}
PHASE = {1: "single", 2: "single", 3: "practice", 4: "test", 5: "single", 6: "practice", 7: "test"}

OUT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "iat2"


def take(words: list[str], role: str, kind: str, n: int, rng: random.Random) -> list[dict]:
    pool: list[str] = []
    while len(pool) < n:
        more = list(words)
        rng.shuffle(more)
        pool += more
    return [{"word": w, "role": role, "kind": kind} for w in pool[:n]]


def main() -> None:
    rng = random.Random(1998)
    (OUT / "lists").mkdir(parents=True, exist_ok=True)
    for b, n in N.items():
        if b in (1, 5):          # the two target categories only
            rows = take(TARGET_A, "target_a", "target", n // 2, rng) + take(TARGET_B, "target_b", "target", n // 2, rng)
        elif b == 2:             # the two attributes only
            rows = take(POSITIVE, "positive", "attribute", n // 2, rng) + take(NEGATIVE, "negative", "attribute", n // 2, rng)
        else:                    # combined blocks: half targets, half attributes
            q = n // 4
            rows = (take(TARGET_A, "target_a", "target", q, rng) + take(TARGET_B, "target_b", "target", q, rng)
                    + take(POSITIVE, "positive", "attribute", q, rng) + take(NEGATIVE, "negative", "attribute", q, rng))
        combined = b in (3, 4, 6, 7)
        for r in rows:
            # 'alternate' makes target and attribute words take turns in the combined blocks (max_repeat in iat2.yaml)
            r.update(block=b, phase=PHASE[b], alternate=r["kind"] if combined else "free")
        with open(OUT / "lists" / f"block{b}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["block", "phase", "word", "role", "kind", "alternate"])
            w.writeheader()
            w.writerows(rows)
    print(f"wrote the IAT trial lists in {OUT / 'lists'}; set the category names in iat2.yaml (variables)")


if __name__ == "__main__":
    main()
