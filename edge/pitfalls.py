"""Checks for the classic ways an experiment looks fine but times or runs wrong.

* a duration that is not a whole number of screen frames (it gets rounded to the frame before or after)
* compressed audio (MP3, AAC, OGG) for timed sounds: encoders put silence at the start, decoders add delay
* absolute file paths: the experiment breaks on another computer and in bundles
* picture / sound / page files that don't exist, including every file named in a trial list
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any, Iterable

FRAME_TOLERANCE = 0.15            # of a frame
SHORT = 0.25                      # s: rounding to a frame matters for presentations this short
COMPRESSED_AUDIO = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma")
FILE_PROPS = {"image": "image", "sound": "sound", "html": "file"}
VISUAL = {"text", "image", "shape", "fixation", "slider", "gaze_roi"}
BIG_PIXELS = 4096
BIG_FILE = 15_000_000


def image_size(path: Path) -> tuple[int, int] | None:
    """Width and height of a PNG, GIF, BMP, JPEG, WebP, TIFF or SVG from its header (no image library needed)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
            if head[:2] == b"BM":
                return int.from_bytes(head[18:22], "little"), abs(int.from_bytes(head[22:26], "little", signed=True))
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _webp_size(head)
            if head[:4] in (b"II*\x00", b"MM\x00*"):
                f.seek(0)
                return _tiff_size(f.read(65536))
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    m = f.read(4)
                    if len(m) < 4 or m[0] != 0xFF:
                        return None
                    kind, length = m[1], int.from_bytes(m[2:4], "big")
                    if kind in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        d = f.read(5)
                        return int.from_bytes(d[3:5], "big"), int.from_bytes(d[1:3], "big")
                    f.seek(length - 2, 1)
            f.seek(0)
            text = f.read(4096)
            if b"<svg" in text.lower():
                return _svg_size(text.decode("utf-8", errors="replace"))
    except OSError:
        return None
    return None


def _webp_size(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8 " and len(head) >= 30 and head[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(head[26:28], "little") & 0x3FFF, int.from_bytes(head[28:30], "little") & 0x3FFF
    if chunk == b"VP8L" and len(head) >= 25 and head[20] == 0x2F:
        b = int.from_bytes(head[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(head) >= 30:
        return int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1
    return None


def _tiff_size(data: bytes) -> tuple[int, int] | None:
    order = "little" if data[:2] == b"II" else "big"
    try:
        ifd = int.from_bytes(data[4:8], order)
        n = int.from_bytes(data[ifd:ifd + 2], order)
        found: dict[int, int] = {}
        for i in range(n):
            e = data[ifd + 2 + 12 * i: ifd + 14 + 12 * i]
            if len(e) < 12:
                break
            tag, typ = int.from_bytes(e[0:2], order), int.from_bytes(e[2:4], order)
            if tag in (256, 257):
                found[tag] = int.from_bytes(e[8:10], order) if typ == 3 else int.from_bytes(e[8:12], order)
        if 256 in found and 257 in found:
            return found[256], found[257]
    except (IndexError, ValueError):
        return None
    return None


def _svg_size(text: str) -> tuple[int, int] | None:
    import re
    m = re.search(r"<svg\b[^>]*>", text, re.I | re.S)
    if not m:
        return None
    tag = m.group(0)

    def attr(name: str) -> str | None:
        a = re.search(rf"\b{name}\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
        return a.group(1).strip() if a else None

    def num(v: str | None) -> float | None:
        if not v or v.endswith("%"):
            return None
        n = re.match(r"^\s*([\d.]+)\s*(px)?\s*$", v)
        return float(n.group(1)) if n else None

    w, h = num(attr("width")), num(attr("height"))
    if w and h:
        return int(round(w)), int(round(h))
    vb = attr("viewBox")
    if vb:
        parts = re.split(r"[\s,]+", vb.strip())
        try:
            if len(parts) == 4:
                return int(round(float(parts[2]))), int(round(float(parts[3])))
        except ValueError:
            return None
    return None


def pitfall_issues(exp) -> list:
    issues: list = []
    issues += frame_issues(exp)
    issues += file_issues(exp)
    return issues


# ============================================================================ frames
def frame_issues(exp) -> list:
    from .model import Issue
    win = exp.settings.get("window") or {}
    rate = float(win.get("refresh_rate") or 60.0)
    assumed = not win.get("refresh_rate")
    out = []
    for rid, r in exp.routines.items():
        items = [(f"routines.{rid}.{c.id}", c.duration, c.type) for c in r.components if c.duration_frames is None]
        for where, d, ctype in items:
            if ctype not in VISUAL or isinstance(d, bool) or not isinstance(d, (int, float)) or not 0 < d <= SHORT:
                continue
            frames = d * rate
            if abs(frames - round(frames)) <= FRAME_TOLERANCE:
                continue
            lo, hi = max(1, int(frames)), int(frames) + 1
            out.append(Issue(
                "warning", where,
                f"{d:g} s is {frames:.1f} frames at {rate:g} Hz{' (assumed)' if assumed else ''}: the screen can only show it "
                f"for {lo} or {hi} frames ({lo / rate * 1e3:.1f} or {hi / rate * 1e3:.1f} ms)",
                hint=f"use {round(frames) / rate:.4f} s or duration_frames: {max(1, round(frames))}"
                     + ("; set settings.window.refresh_rate to your monitor's rate" if assumed else "")))
    return out


# ============================================================================ files
def _loops_around(exp) -> dict[str, list]:
    """Routine id -> the Loop objects around it (every place it appears)."""
    from .model import Branch, Loop, StateMachine
    out: dict[str, list] = {}

    def walk(nodes, stack):
        for n in nodes:
            if isinstance(n, Loop):
                walk(n.children, stack + [n])
            elif isinstance(n, Branch):
                walk(n.then, stack)
                walk(n.else_, stack)
            elif isinstance(n, StateMachine):
                for st in n.states.values():
                    walk(st.run, stack)
            else:
                rid = getattr(n, "routine", None)
                if rid:
                    out.setdefault(rid, [])
                    out[rid] += [lp for lp in stack if lp not in out[rid]]
    walk(exp.flow, [])
    return out


def _column_values(exp, loops: list, col: str) -> list[Any] | None:
    """Every value of a trial-list column in the loops around a routine (None if it can't be known)."""
    from .conditions import load_conditions
    vals: list[Any] = []
    found = False
    for lp in loops:
        if lp.staircase or lp.conditions is None or (isinstance(lp.conditions, str) and lp.conditions.startswith("$")):
            continue
        try:
            rows = load_conditions(lp.conditions, exp.base_dir)
        except Exception:
            return None
        for r in rows:
            if col in r:
                found = True
                vals.append(r[col])
    return vals if found else None


def _near(base: Path, rel: str) -> str:
    """A similarly named existing file, for 'did you mean'."""
    p = base / rel
    folder = p.parent if p.parent.is_dir() else base
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    m = difflib.get_close_matches(p.name, names, 1, 0.6)
    if not m:
        return ""
    return str((folder / m[0]).relative_to(base)) if folder.is_relative_to(base) else m[0]


def file_issues(exp) -> list:
    from .model import Issue
    base = Path(exp.base_dir)
    loops = _loops_around(exp)
    out = []
    for rid, r in exp.routines.items():
        for c in r.components:
            prop = FILE_PROPS.get(c.type)
            if not prop:
                continue
            v = c.props.get(prop)
            where = f"routines.{rid}.{c.id}"
            if c.type == "sound" and (v is None or isinstance(v, (int, float))):
                continue                          # a tone
            if c.type == "html" and not v:
                continue                          # inline html (checked by the component)
            if isinstance(v, str) and v.startswith("$"):
                src = v[1:].strip()
                if not src.isidentifier():
                    continue                      # a formula: can't know the files before running
                vals = _column_values(exp, loops.get(rid, []), src)
                if vals is None:
                    continue
                files = [str(x) for x in vals if isinstance(x, str) and x.strip()]
                if c.type == "sound" and not files:
                    continue
                out += _file_list_issues(Issue, base, where, files, c.type, f"trial-list column '{src}'")
            elif isinstance(v, str) and v:
                if c.type == "html":
                    continue                      # the html component checks its own file
                out += _file_list_issues(Issue, base, where, [v], c.type, None)
    return out


def _file_list_issues(Issue, base: Path, where: str, files: Iterable[str], ctype: str, column: str | None) -> list:
    out = []
    files = list(dict.fromkeys(files))
    absolute = [f for f in files if Path(f).is_absolute() or (len(f) > 1 and f[1] == ":")]
    if absolute:
        out.append(Issue("warning", where, f"absolute path{'s' if len(absolute) > 1 else ''} ({absolute[0]}"
                         f"{' …' if len(absolute) > 1 else ''}): the experiment will break on another computer and in a bundle",
                         hint="put the file in a folder next to the experiment (e.g. images/, sounds/) and use a relative path"))
    missing = [f for f in files if not ((base / f) if not Path(f).is_absolute() else Path(f)).exists()]
    if missing:
        what = {"image": "picture", "sound": "sound file"}.get(ctype, "file")
        near = _near(base, missing[0])
        msg = (f"{len(missing)} of {len(files)} {what}s named in {column} not found: {', '.join(missing[:3])}"
               f"{' …' if len(missing) > 3 else ''}") if column else f"{what} not found: {missing[0]}"
        out.append(Issue("error", where, msg, hint=f"did you mean {near}?" if near else
                         "file names are relative to the experiment's folder; check the spelling and the extension"))
    if ctype == "image":
        big = []
        for f in files:
            fp = (base / f) if not Path(f).is_absolute() else Path(f)
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            dims = image_size(fp)
            if size > BIG_FILE or (dims and max(dims) > BIG_PIXELS):
                big.append((f, dims, size))
        if big:
            f, dims, size = big[0]
            what = f"{dims[0]}×{dims[1]} px" if dims else f"{size / 1e6:.0f} MB"
            out.append(Issue("warning", where, f"very large picture{'s' if len(big) > 1 else ''} ({f}: {what}"
                             f"{f', and {len(big) - 1} more' if len(big) > 1 else ''}): loading them takes time and memory "
                             "and can drop frames when they appear",
                             hint=f"shrink them to the size they are shown at (at most the screen size, e.g. 1920 px wide)"))
    if ctype == "sound":
        comp = [f for f in files if f.lower().endswith(COMPRESSED_AUDIO)]
        if comp:
            out.append(Issue("warning", where, f"compressed audio ({Path(comp[0]).suffix}): MP3/AAC/OGG files start with a few "
                             "to ~50 ms of encoder silence and need decoding, so the sound starts later than its onset time",
                             hint="convert timed sounds to WAV (e.g. in Audacity: File → Export → WAV)"))
    return out
