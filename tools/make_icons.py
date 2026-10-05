"""Render EDGE's icon (edge/assets/edge-icon.svg) to PNGs, a Windows .ico and a macOS .icns.

    python tools/make_icons.py          # needs Playwright + Chromium to draw the SVG

The results are committed in edge/assets/, so installing EDGE needs none of this; run it only after
editing the SVG. The .ico and .icns containers are written here in plain Python (PNG-compressed
entries, which Windows Vista+ and macOS 10.7+ read).
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "edge" / "assets"
SVG = ASSETS / "edge-icon.svg"
PNG_SIZES = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
ICNS_TYPES = [(b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256), (b"ic09", 512), (b"ic10", 1024)]


def render(sizes: list[int]) -> dict[int, bytes]:
    from playwright.sync_api import sync_playwright
    out: dict[int, bytes] = {}
    svg = SVG.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("EDGE_CHROMIUM") or None)
        for n in sizes:
            page = browser.new_page(viewport={"width": n, "height": n})
            page.set_content(f'<html><body style="margin:0;background:transparent">'
                             f'<div style="width:{n}px;height:{n}px">{svg.replace("<svg ", f"<svg width=%d height=%d " % (n, n), 1)}</div>'
                             f'</body></html>')
            out[n] = page.screenshot(omit_background=True, clip={"x": 0, "y": 0, "width": n, "height": n})
            page.close()
        browser.close()
    return out


def make_ico(pngs: dict[int, bytes], sizes: list[int]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(sizes))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(sizes)
    for n in sizes:
        data = pngs[n]
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    return head + entries + blobs


def make_icns(pngs: dict[int, bytes]) -> bytes:
    chunks = b"".join(t + struct.pack(">I", 8 + len(pngs[n])) + pngs[n] for t, n in ICNS_TYPES)
    return b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks


def main() -> int:
    try:
        pngs = render(PNG_SIZES)
    except ImportError:
        print("Playwright is needed to draw the SVG: pip install playwright && playwright install chromium")
        return 1
    for n in (16, 32, 48, 64, 128, 256, 512):
        (ASSETS / f"edge-{n}.png").write_bytes(pngs[n])
    (ASSETS / "edge.ico").write_bytes(make_ico(pngs, ICO_SIZES))
    (ASSETS / "edge.icns").write_bytes(make_icns(pngs))
    print("wrote", ", ".join(sorted(p.name for p in ASSETS.iterdir())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
