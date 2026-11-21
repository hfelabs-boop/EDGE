"""Draw the pictures of edge/library/tasks/vaast_images (re-runnable, no packages needed).

Simple cartoon faces: 10 smiling and 10 frowning, in five face colours and two eye styles (8 + 8 for the test,
2 + 2 for practice). Written as PNG files with the standard library only (zlib), anti-aliased by drawing at 3x
the size and averaging. To use your own pictures instead, put them in the stimuli folder and list them in
images.csv / practice_images.csv (columns stimulus = file name, valence = the category).
"""

from __future__ import annotations

import csv
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "edge" / "library" / "tasks" / "vaast_images"
SIZE = 240          # pixels of the finished picture
SS = 3              # supersampling factor

COLOURS = [(250, 210, 70), (245, 160, 80), (130, 190, 240), (140, 210, 140), (220, 160, 220)]
OUTLINE = (60, 45, 35)


def face(colour: tuple[int, int, int], smile: bool, round_eyes: bool) -> list[bytearray]:
    n = SIZE * SS
    c = n / 2
    s = SS * SIZE / 240           # drawing units are pixels of a 240 px picture
    rows = []
    for py in range(n):
        y = (c - py - 0.5) / s    # y up, centre 0
        row = bytearray(n * 4)
        for px in range(n):
            x = (px + 0.5 - c) / s
            r2 = x * x + y * y
            col = None
            if r2 <= 100 ** 2:
                col = OUTLINE if r2 >= 94 ** 2 else colour
                # eyes
                for ex in (-36, 36):
                    dx, dy = x - ex, y - 28
                    if round_eyes and dx * dx + dy * dy <= 11 ** 2:
                        col = OUTLINE
                    if not round_eyes and (dx / 8) ** 2 + (dy / 15) ** 2 <= 1:
                        col = OUTLINE
                # mouth: a thick curve whose ends turn up (smile) or down (frown)
                if abs(x) <= 46:
                    curve = (-42 + 0.011 * x * x) if smile else (-58 - 0.011 * x * x + 0.011 * 46 * 46 * 0.5)
                    if abs(y - curve) <= 5:
                        col = OUTLINE
            if col is not None:
                row[px * 4:px * 4 + 4] = bytes((*col, 255))
        rows.append(row)
    return rows


def shrink(rows: list[bytearray]) -> list[bytes]:
    out = []
    n = SIZE * SS
    for y in range(SIZE):
        line = bytearray(SIZE * 4)
        for x in range(SIZE):
            acc = [0, 0, 0, 0]
            for yy in range(y * SS, y * SS + SS):
                r = rows[yy]
                for xx in range(x * SS, x * SS + SS):
                    i = xx * 4
                    a = r[i + 3]
                    acc[0] += r[i] * a
                    acc[1] += r[i + 1] * a
                    acc[2] += r[i + 2] * a
                    acc[3] += a
            a = acc[3]
            if a:
                line[x * 4:x * 4 + 4] = bytes((acc[0] // a, acc[1] // a, acc[2] // a, a // (SS * SS)))
        out.append(bytes(line))
    assert len(rows) == n
    return out


def write_png(path: Path, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + r for r in rows)
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> None:
    (OUT / "stimuli").mkdir(parents=True, exist_ok=True)
    test, practice = [], []
    for smile in (True, False):
        k = 0
        for ci, colour in enumerate(COLOURS):
            for round_eyes in (True, False):
                k += 1
                name = f"{'smile' if smile else 'frown'}_{k:02d}.png"
                write_png(OUT / "stimuli" / name, shrink(face(colour, smile, round_eyes)))
                row = {"stimulus": f"stimuli/{name}", "valence": "smiling" if smile else "frowning"}
                (practice if ci == 4 else test).append(row)
    for fname, rows in (("images.csv", test), ("practice_images.csv", practice)):
        with open(OUT / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["stimulus", "valence"])
            w.writeheader()
            w.writerows(rows)
    print(f"drew {len(test) + len(practice)} pictures in {OUT / 'stimuli'}")


if __name__ == "__main__":
    main()
