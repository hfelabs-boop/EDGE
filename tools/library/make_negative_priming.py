"""Write the trial list of the negative priming task in the EDGE task library.

    python tools/library/make_negative_priming.py

Each row is a prime-probe pair. Two overlapping letters (from D, F, J, K): the RED one is the target,
the GREEN one is to be ignored.
  ignored_repetition: the probe's target is the letter that was ignored in the prime
  control:            the probe's two letters are both new (neither appeared in the prime)
With four letters there are exactly 24 pairs of each kind; all are used (48 rows).
"""

from __future__ import annotations

import csv
from itertools import permutations
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "negative_priming"
LETTERS = ["D", "F", "J", "K"]


def rows() -> list[dict]:
    out = []
    for a, b in permutations(LETTERS, 2):                 # prime target a, prime distractor b
        rest = [x for x in LETTERS if x not in (a, b)]
        for c in rest:                                     # ignored repetition: probe target b, distractor new
            out.append(dict(prime_target=a, prime_distractor=b, probe_target=b, probe_distractor=c,
                            condition="ignored_repetition"))
        for c in rest:                                     # control: both probe letters new
            d = [x for x in rest if x != c][0]
            out.append(dict(prime_target=a, prime_distractor=b, probe_target=c, probe_distractor=d,
                            condition="control"))
    for r in out:
        r["prime_key"] = r["prime_target"].lower()
        r["probe_key"] = r["probe_target"].lower()
    return out


def main() -> None:
    data = rows()
    FOLDER.mkdir(parents=True, exist_ok=True)
    cols = list(data[0])
    for name, subset in (("trials.csv", data), ("practice.csv", [data[i * 8 + (i % 2) * 2] for i in range(6)])):
        with (FOLDER / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, cols, lineterminator="\n")
            w.writeheader()
            w.writerows(subset)
    print("wrote", FOLDER, len(data), "pairs")


if __name__ == "__main__":
    main()
