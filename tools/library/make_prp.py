"""Write the trial lists of the psychological refractory period (PRP) task in the EDGE task library.

    python tools/library/make_prp.py

Task 1: a tone, low (400 Hz) or high (900 Hz): left hand, A = low, S = high.
Task 2: a letter, X or O, shown SOA seconds after the tone onset: right hand, K = X, L = O.
SOAs 50, 150, 300, 600 and 1000 ms. 2 tones x 2 letters x 5 SOAs = 20 rows (trials.csv);
practice.csv has 10 of them (every SOA twice).
"""

from __future__ import annotations

import csv
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "prp"
TONES = {"low": (400, "a"), "high": (900, "s")}
LETTERS = {"X": "k", "O": "l"}
SOAS = [0.05, 0.15, 0.3, 0.6, 1.0]


def rows() -> list[list]:
    out = []
    for tone, (hz, key1) in TONES.items():
        for letter, key2 in LETTERS.items():
            for soa in SOAS:
                out.append([tone, hz, key1, letter, key2, soa, int(round(soa * 1000))])
    return out


def main() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    data = rows()
    practice = [r for i, r in enumerate(data) if i // 5 in (0, 3)]       # low tone + X, high tone + O
    for name, subset in (("trials.csv", data), ("practice.csv", practice)):
        with (FOLDER / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["tone", "tone_hz", "correct_key1", "letter", "correct_key2", "soa", "soa_ms"])
            w.writerows(subset)
        print("wrote", FOLDER / name, len(subset), "rows")


if __name__ == "__main__":
    main()
