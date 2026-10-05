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
    if ctype == "sound":
        comp = [f for f in files if f.lower().endswith(COMPRESSED_AUDIO)]
        if comp:
            out.append(Issue("warning", where, f"compressed audio ({Path(comp[0]).suffix}): MP3/AAC/OGG files start with a few "
                             "to ~50 ms of encoder silence and need decoding, so the sound starts later than its onset time",
                             hint="convert timed sounds to WAV (e.g. in Audacity: File → Export → WAV)"))
    return out
