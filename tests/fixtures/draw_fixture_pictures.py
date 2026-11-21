"""Draws the small pictures the test fixtures use (plain Python, no imaging library), so they can be made again:

    python tests/fixtures/draw_fixture_pictures.py

library_sample/colour_choice/stimuli/: a red and a blue patch.
psytoolkit/: the bitmaps of the PsyToolkit-syntax fixture scripts (colour words on black, a fixation cross,
left/right squares, a tick and a cross for feedback), packed into simon_task.zip as a PsyToolkit download would be.
"""

from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def png(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    h, w = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def canvas(w: int, h: int, bg: tuple[int, int, int]) -> list[list[tuple[int, int, int]]]:
    return [[bg] * w for _ in range(h)]


def rect(px, x0, y0, x1, y1, c) -> None:
    for y in range(max(0, y0), min(len(px), y1)):
        for x in range(max(0, x0), min(len(px[0]), x1)):
            px[y][x] = c


def patch(w: int, h: int, c) -> list[list[tuple[int, int, int]]]:
    return canvas(w, h, c)


def cross(size: int, fg, bg, thick: int = 4) -> list[list[tuple[int, int, int]]]:
    px = canvas(size, size, bg)
    m = size // 2
    rect(px, m - thick // 2, 4, m + thick // 2 + 1, size - 4, fg)
    rect(px, 4, m - thick // 2, size - 4, m + thick // 2 + 1, fg)
    return px


def diagonal_cross(size: int, fg, bg, thick: int = 4) -> list[list[tuple[int, int, int]]]:
    px = canvas(size, size, bg)
    for i in range(4, size - 4):
        for d in range(-thick // 2, thick // 2 + 1):
            for x in (i + d, size - 1 - i + d):
                if 0 <= x < size:
                    px[i][x] = fg
    return px


def tick(size: int, fg, bg, thick: int = 5) -> list[list[tuple[int, int, int]]]:
    px = canvas(size, size, bg)
    for x in range(6, size - 4):
        y = size - 8 - (x - 6) if x > size // 3 else size // 2 + (x - 6)
        for d in range(-thick // 2, thick // 2 + 1):
            if 0 <= y + d < size:
                px[y + d][x] = fg
    return px


def bars(w: int, h: int, c, bg) -> list[list[tuple[int, int, int]]]:
    """A coloured block letter-ish word stand-in: three horizontal bars of the ink colour."""
    px = canvas(w, h, bg)
    for i in range(3):
        rect(px, 8, 8 + i * (h - 16) // 3, w - 8, 8 + i * (h - 16) // 3 + (h - 16) // 6, c)
    return px


def main() -> None:
    png(HERE / "library_sample/colour_choice/stimuli/red.png", patch(64, 64, (210, 40, 40)))
    png(HERE / "library_sample/colour_choice/stimuli/blue.png", patch(64, 64, (40, 60, 210)))
    pt = HERE / "psytoolkit"
    black = (0, 0, 0)
    png(pt / "stroop_pictures/fixpoint.png", cross(32, (255, 255, 255), black))
    png(pt / "stroop_pictures/right.png", tick(48, (60, 200, 60), black))
    png(pt / "stroop_pictures/wrong.png", diagonal_cross(48, (230, 50, 50), black))
    png(pt / "stroop_pictures/instruction.png", bars(160, 90, (200, 200, 200), (30, 30, 30)))
    # the Simon task arrives as a zip, as downloaded from a PsyToolkit account: script + bitmaps
    simon = {"fix.png": cross(32, (255, 255, 255), black), "red_square.png": patch(60, 60, (220, 30, 30)),
             "green_square.png": patch(60, 60, (30, 200, 60)), "oops.png": diagonal_cross(48, (230, 50, 50), black)}
    tmp = pt / "_simon_build"
    for name, px in simon.items():
        png(tmp / name, px)
    with zipfile.ZipFile(pt / "simon_task.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(pt / "simon_code.psy", "simon_task/code.psy")
        for name in simon:
            z.write(tmp / name, f"simon_task/{name}")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()


if __name__ == "__main__":
    main()
