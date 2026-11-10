"""Eye movements: fixations and saccades from a recorded gaze stream, and areas-of-interest (AOI) reports.

* ``gaze_samples``  the gaze stream of any EDGE eye tracker as one layout: time (master clock), x, y (px from
                    the screen centre, +y up: EDGE's own units), pupil (mm, mean of the valid eyes), NaN when
                    the tracker lost the eyes. Tobii and Gazepoint screen fractions are converted.
* ``detect_fixations``  I-VT (velocity threshold, like Tobii's I-VT filter: 30 deg/s over a 20 ms window, gaps up
                    to 75 ms filled, fixations closer than 75 ms and 0.5 deg merged, shorter than 60 ms dropped)
                    or I-DT (dispersion threshold, Salvucci & Goldberg 2000: 1 deg within at least 100 ms).
                    Positions become visual angle with the screen geometry of the experiment
                    (settings.window.monitor: width_cm, distance_cm) and the window size in pixels.
* ``fixations``     runs the detection on a session and writes ``analysis/fixations.csv`` and ``saccades.csv``
* ``aoi_report``    AOIs from the experiment (gaze areas, pictures and shapes) plus your own; per trial: first
                    fixation latency, dwell time, fixation count, visits, revisits, proportion of fixation time;
                    and per condition. Writes ``aoi_trials.csv`` and ``aoi_summary.csv``.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from .. import expressions
from .common import NAN, AnalysisError, Session, isnan, write_csv

IVT_DEFAULTS = {"velocity_threshold": 30.0, "velocity_window": 0.020, "max_gap": 0.075,
                "merge_time": 0.075, "merge_angle": 0.5, "min_duration": 0.060, "noise_filter": 3}
IDT_DEFAULTS = {"dispersion_threshold": 1.0, "min_duration": 0.100, "max_gap": 0.075, "noise_filter": 3}
METHODS = ("ivt", "idt")
AOI_SOURCES = ("gaze_roi", "image", "shape")

FIXATION_COLS = ["fixation", "trial", "routine", "start", "end", "duration", "onset", "x", "y", "x_deg", "y_deg",
                 "dispersion_deg", "n_samples", "pupil", "aoi"]
SACCADE_COLS = ["saccade", "trial", "routine", "start", "end", "duration", "onset", "x_start", "y_start", "x_end",
                "y_end", "amplitude_deg", "peak_velocity_deg_s"]
AOI_TRIAL_METRICS = ["fixated", "first_fixation_latency", "first_fixation_duration", "dwell_time", "fixation_count",
                     "visits", "revisits", "proportion"]


# ============================================================================ samples
def gaze_samples(sess: Session, stream: str = "") -> dict[str, Any]:
    """Times and positions of a session's gaze stream (``stream``: device id or name; default: the first gaze
    stream)."""
    s = sess.find_stream(stream, kinds=("gaze",)) if stream else _first_gaze(sess)
    ch = set(s["channels"])
    frac = "fraction" in (s["coordinates"] or "").lower() or "screen fraction" in s["units"]

    def eyes(pairs: list[tuple[str, str, str | None]], times: list[float], data: dict[str, list[float]]):
        xs, ys = [], []
        for i in range(len(times)):
            px, py = [], []
            for cx, cy, cv in pairs:
                x, y = data[cx][i], data[cy][i]
                ok = not isnan(x) and not isnan(y) and (cv is None or data[cv][i] == 1)
                if ok:
                    px.append(x)
                    py.append(y)
            xs.append(sum(px) / len(px) if px else NAN)
            ys.append(sum(py) / len(py) if py else NAN)
        return xs, ys

    if {"x", "y"} <= ch:
        pairs = [("x", "y", "valid" if "valid" in ch else None)]
        pupils = [(p, "valid" if "valid" in ch else None) for p in ("pupil_l", "pupil_r", "pupil") if p in ch]
    elif {"left_x", "left_y", "right_x", "right_y"} <= ch:         # Tobii Pro
        pairs = [("left_x", "left_y", "left_valid" if "left_valid" in ch else None),
                 ("right_x", "right_y", "right_valid" if "right_valid" in ch else None)]
        pupils = [(p, v if v in ch else None) for p, v in (("left_pupil", "left_pupil_valid"),
                                                            ("right_pupil", "right_pupil_valid")) if p in ch]
        frac = True
    elif {"BPOGX", "BPOGY"} <= ch:                                  # Gazepoint
        pairs = [("BPOGX", "BPOGY", "BPOGV" if "BPOGV" in ch else None)]
        pupils = [(p, v if v in ch else None) for p, v in (("LPMM", "LPMMV"), ("RPMM", "RPMMV")) if p in ch]
        frac = True
    else:
        raise AnalysisError(f"stream {s['name']} doesn't look like gaze data (no x/y channels): "
                            f"{', '.join(s['channels'])}")
    need = sorted({c for p in pairs for c in p if c} | {c for p in pupils for c in p if c})
    times, data = sess.load(s, need)
    xs, ys = eyes(pairs, times, data)
    if frac:     # screen fraction from the top-left corner, +y down -> px from the centre, +y up
        xs = [(x - 0.5) * sess.width if not isnan(x) else NAN for x in xs]
        ys = [(0.5 - y) * sess.height if not isnan(y) else NAN for y in ys]
    pupil = []
    for i in range(len(times)):
        vals = [data[p][i] for p, v in pupils if not isnan(data[p][i]) and data[p][i] > 0
                and (v is None or data[v][i] == 1)]
        pupil.append(sum(vals) / len(vals) if vals else NAN)
    srate = s["srate"] or _estimate_srate(times)
    return {"stream": s["name"], "time": times, "x": xs, "y": ys, "pupil": pupil, "srate": srate}


def _first_gaze(sess: Session) -> dict[str, Any]:
    streams = sess.streams()
    for s in streams:
        if s["kind"].lower() == "gaze" or {"x", "y"} <= set(s["channels"]) or "BPOGX" in s["channels"] \
                or "left_x" in s["channels"]:
            return s
    raise AnalysisError(f"{sess.root.name} has no gaze recording: add an eye tracker in Devices (or the simulated "
                        "one) and run the session again")


def _estimate_srate(times: list[float]) -> float:
    d = [b - a for a, b in zip(times, times[1:]) if b > a]
    return 1.0 / statistics.median(d) if d else 0.0


def _fill_gaps(t: list[float], v: list[float], max_gap: float) -> list[float]:
    """Linear interpolation across runs of NaN no longer than ``max_gap`` seconds."""
    out = list(v)
    n = len(v)
    i = 0
    while i < n:
        if isnan(out[i]):
            j = i
            while j < n and isnan(out[j]):
                j += 1
            if i > 0 and j < n and t[j] - t[i - 1] <= max_gap + 1e-9:
                a, b = out[i - 1], out[j]
                for k in range(i, j):
                    f = (t[k] - t[i - 1]) / (t[j] - t[i - 1])
                    out[k] = a + f * (b - a)
            i = j
        else:
            i += 1
    return out


# ============================================================================ detection
def detect_fixations(t: list[float], x_deg: list[float], y_deg: list[float], method: str = "ivt",
                     srate: float | None = None, **opts: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fixations and saccades from gaze in degrees (NaN = no gaze). Returns (fixations, saccades); each fixation
    has start, end, duration, i0, i1 (sample range, end exclusive), x_deg, y_deg, dispersion_deg."""
    method = (method or "ivt").lower().replace("-", "")
    if method not in METHODS:
        raise AnalysisError(f"unknown fixation method '{method}': choose ivt (velocity) or idt (dispersion)")
    known = IVT_DEFAULTS if method == "ivt" else IDT_DEFAULTS
    bad = [k for k in opts if k not in known]
    if bad:
        raise AnalysisError(f"'{bad[0]}' is not a setting of {method.upper()}; its settings: {', '.join(known)}")
    o = {**known, **{k: float(v) for k, v in opts.items() if v is not None}}
    srate = srate or _estimate_srate(t)
    dt = 1.0 / srate if srate else 0.0
    x = _median(_fill_gaps(t, x_deg, o["max_gap"]), int(o["noise_filter"]))
    y = _median(_fill_gaps(t, y_deg, o["max_gap"]), int(o["noise_filter"]))
    if method == "ivt":
        fix, sac = _ivt(t, x, y, dt, o, srate)
    else:
        fix, sac = _idt(t, x, y, dt, o)
    return fix, sac


def _median(v: list[float], n: int) -> list[float]:
    """Moving median over ``n`` samples (odd; 0 or 1 = off), as trackers' noise reduction does; NaN stays NaN."""
    if n <= 1:
        return list(v)
    h = n // 2
    out = list(v)
    for i in range(h, len(v) - h):
        if isnan(v[i]):
            continue
        win = [w for w in v[i - h:i + h + 1] if not isnan(w)]
        out[i] = sorted(win)[len(win) // 2]
    return out


def _fixation(t: list[float], x: list[float], y: list[float], i0: int, i1: int, dt: float) -> dict[str, Any]:
    xs, ys = x[i0:i1], y[i0:i1]
    end = t[i1] if i1 < len(t) and t[i1] - t[i1 - 1] <= 2 * dt + 1e-9 else t[i1 - 1] + dt
    return {"i0": i0, "i1": i1, "start": t[i0], "end": end, "duration": end - t[i0],
            "x_deg": sum(xs) / len(xs), "y_deg": sum(ys) / len(ys),
            "dispersion_deg": (max(xs) - min(xs)) + (max(ys) - min(ys)), "n_samples": i1 - i0}


def _velocity(t: list[float], x: list[float], y: list[float], k: int) -> list[float]:
    n = len(t)
    v = [NAN] * n
    for i in range(n):
        a, b = max(0, i - k), min(n - 1, i + k)
        if b == a or isnan(x[a]) or isnan(x[b]) or isnan(x[i]):
            continue
        d = t[b] - t[a]
        if d > 0:
            v[i] = math.hypot(x[b] - x[a], y[b] - y[a]) / d
    return v


def _ivt(t, x, y, dt, o, srate):
    k = max(1, round(o["velocity_window"] / 2 * srate)) if srate else 1
    v = _velocity(t, x, y, k)
    n = len(t)
    raw: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not isnan(v[i]) and v[i] < o["velocity_threshold"]:
            j = i
            while j < n and not isnan(v[j]) and v[j] < o["velocity_threshold"]:
                j += 1
            raw.append((i, j))
            i = j
        else:
            i += 1
    fix = [_fixation(t, x, y, a, b, dt) for a, b in raw]
    merged: list[dict[str, Any]] = []
    for f in fix:
        if merged:
            p = merged[-1]
            gap = f["start"] - p["end"]
            if gap <= o["merge_time"] + 1e-9 and math.hypot(f["x_deg"] - p["x_deg"], f["y_deg"] - p["y_deg"]) <= o["merge_angle"] \
                    and all(not isnan(x[q]) for q in range(p["i1"], f["i0"])):
                merged[-1] = _fixation(t, x, y, p["i0"], f["i1"], dt)
                continue
        merged.append(f)
    fixes = [f for f in merged if f["duration"] >= o["min_duration"] - 1e-9]
    return fixes, _saccades(t, x, y, fixes, v)


def _idt(t, x, y, dt, o):
    n = len(t)
    thr = o["dispersion_threshold"]
    fixes = []
    i = 0
    while i < n:
        if isnan(x[i]):
            i += 1
            continue
        j = i
        while j < n and not isnan(x[j]) and t[j] - t[i] < o["min_duration"] - dt / 2:
            j += 1
        if j >= n or isnan(x[j]):
            i = j + 1 if j < n else n
            continue
        xs, ys = x[i:j + 1], y[i:j + 1]
        lox, hix, loy, hiy = min(xs), max(xs), min(ys), max(ys)
        if (hix - lox) + (hiy - loy) > thr:
            i += 1
            continue
        j += 1
        while j < n and not isnan(x[j]):
            nlox, nhix = min(lox, x[j]), max(hix, x[j])
            nloy, nhiy = min(loy, y[j]), max(hiy, y[j])
            if (nhix - nlox) + (nhiy - nloy) > thr:
                break
            lox, hix, loy, hiy = nlox, nhix, nloy, nhiy
            j += 1
        fixes.append(_fixation(t, x, y, i, j, dt))
        i = j
    return fixes, _saccades(t, x, y, fixes, _velocity(t, x, y, 1))


def _saccades(t, x, y, fixes, v, max_duration: float = 0.15):
    """The movement between two consecutive fixations, when the eyes were tracked all the way (no blink or
    lost data) and it took at most ``max_duration``: start/end position, amplitude, peak velocity."""
    sac = []
    for a, b in zip(fixes, fixes[1:]):
        span = range(a["i1"] - 1, b["i0"] + 1)
        if any(isnan(x[q]) for q in span) or b["start"] - a["end"] > max_duration:
            continue
        x0, y0, x1, y1 = x[a["i1"] - 1], y[a["i1"] - 1], x[b["i0"]], y[b["i0"]]
        peak = max((v[q] for q in span if not isnan(v[q])), default=NAN)
        sac.append({"i0": a["i1"], "i1": b["i0"], "start": a["end"], "end": b["start"],
                    "duration": b["start"] - a["end"], "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "amplitude_deg": math.hypot(x1 - x0, y1 - y0), "peak_velocity_deg_s": peak})
    return sac


# ============================================================================ on a session
def fixations(session: str | Path | Session, method: str = "ivt", stream: str = "", out: str | Path | None = None,
              write: bool = True, **opts: float) -> dict[str, Any]:
    """Detect fixations and saccades in a session's gaze recording and write ``fixations.csv`` and
    ``saccades.csv`` (in ``<session>/analysis/`` unless ``out`` says otherwise).

    ``opts`` are the method's settings in seconds and degrees (see IVT_DEFAULTS, IDT_DEFAULTS)."""
    sess = session if isinstance(session, Session) else Session(session)
    g = gaze_samples(sess, stream)
    if not g["time"]:
        raise AnalysisError(f"the gaze stream {g['stream']} of {sess.root.name} has no samples")
    xd, yd = [], []
    for x, y in zip(g["x"], g["y"]):
        if isnan(x) or isnan(y):
            xd.append(NAN)
            yd.append(NAN)
        else:
            a, b = sess.to_deg(x, y)
            xd.append(a)
            yd.append(b)
    fix, sac = detect_fixations(g["time"], xd, yd, method, g["srate"], **opts)
    k = sess.px_per_cm() * sess.distance_cm
    fix_rows = []
    for n, f in enumerate(fix, 1):
        w = sess.window_at(f["start"])
        pup = [p for p in g["pupil"][f["i0"]:f["i1"]] if not isnan(p)]
        fix_rows.append({"fixation": n, "trial": w["trial"] if w else None, "routine": w["routine"] if w else "",
                         "start": f["start"], "end": f["end"], "duration": f["duration"],
                         "onset": f["start"] - w["start"] if w else None,
                         "x": k * math.tan(math.radians(f["x_deg"])), "y": k * math.tan(math.radians(f["y_deg"])),
                         "x_deg": f["x_deg"], "y_deg": f["y_deg"], "dispersion_deg": f["dispersion_deg"],
                         "n_samples": f["n_samples"], "pupil": sum(pup) / len(pup) if pup else None, "aoi": ""})
    sac_rows = []
    for n, s in enumerate(sac, 1):
        w = sess.window_at(s["start"])
        sac_rows.append({"saccade": n, "trial": w["trial"] if w else None, "routine": w["routine"] if w else "",
                         "start": s["start"], "end": s["end"], "duration": s["duration"],
                         "onset": s["start"] - w["start"] if w else None,
                         "x_start": k * math.tan(math.radians(s["x0"])), "y_start": k * math.tan(math.radians(s["y0"])),
                         "x_end": k * math.tan(math.radians(s["x1"])), "y_end": k * math.tan(math.radians(s["y1"])),
                         "amplitude_deg": s["amplitude_deg"], "peak_velocity_deg_s": s["peak_velocity_deg_s"]})
    settings = {**(IVT_DEFAULTS if method == "ivt" else IDT_DEFAULTS), **{k2: v for k2, v in opts.items() if v is not None}}
    res: dict[str, Any] = {"session": sess.root.name, "stream": g["stream"], "method": method, "settings": settings,
                           "srate": g["srate"], "samples": len(g["time"]),
                           "lost_samples": sum(1 for x in g["x"] if isnan(x)),
                           "fixations": len(fix_rows), "saccades": len(sac_rows),
                           "mean_fixation_duration": statistics.fmean([f["duration"] for f in fix_rows]) if fix_rows else None,
                           "screen": {"width_px": sess.width, "height_px": sess.height, "width_cm": sess.width_cm,
                                      "distance_cm": sess.distance_cm,
                                      "px_per_deg": round(k * math.tan(math.radians(1)), 3)},
                           "files": [], "notes": [], "fixation_rows": fix_rows, "saccade_rows": sac_rows}
    if not fix_rows:
        res["notes"].append("no fixations found: check the screen size and distance (settings.window.monitor) "
                            "and the thresholds, or the recording quality (edge report)")
    if write:
        d = sess.out_dir(out)
        res["files"] += [str(write_csv(d / "fixations.csv", FIXATION_COLS, fix_rows)),
                         str(write_csv(d / "saccades.csv", SACCADE_COLS, sac_rows))]
    return res


# ============================================================================ AOIs
def _comp_geometry(sess: Session, comp: dict[str, Any], ns: dict[str, Any]) -> dict[str, Any] | None:
    """A component's area in px (centre origin, +y up), or None if it has none we can know."""
    def val(key: str, default: Any = None) -> Any:
        v = comp.get(key, default)
        return expressions.resolve(v, ns) if v is not None else default
    units = val("units") or None
    pos = val("pos", [0, 0]) or [0, 0]
    cx, cy = sess.to_px(pos[0], units, "x"), sess.to_px(pos[1], units, "y")
    typ = comp.get("type")
    shape = val("shape", "circle" if typ == "gaze_roi" else "rect") if typ in ("shape", "gaze_roi") else "rect"
    if shape == "circle":
        r = val("radius", 100 if typ == "gaze_roi" else 50)
        return {"shape": "circle", "x": cx, "y": cy, "r": sess.to_px(r, units, "y")}
    if shape == "polygon":
        verts = val("vertices") or []
        if verts:
            return {"shape": "polygon", "x": cx, "y": cy,
                    "vertices": [(cx + sess.to_px(v[0], units, "x"), cy + sess.to_px(v[1], units, "y")) for v in verts]}
    size = val("size", [200, 200] if typ == "gaze_roi" else [100, 100])
    if size is None:
        return None      # a picture at its own size: unknown here
    if not isinstance(size, (list, tuple)):
        size = [size, size]
    w, h = sess.to_px(size[0], units, "x"), sess.to_px(size[1], units, "y")
    return {"shape": "ellipse" if shape == "ellipse" else "rect", "x": cx, "y": cy, "w": abs(w), "h": abs(h)}


def inside(a: dict[str, Any], x: float, y: float) -> bool:
    if a["shape"] == "circle":
        return math.hypot(x - a["x"], y - a["y"]) <= a["r"]
    if a["shape"] == "ellipse":
        rx, ry = a["w"] / 2, a["h"] / 2
        return rx > 0 and ry > 0 and ((x - a["x"]) / rx) ** 2 + ((y - a["y"]) / ry) ** 2 <= 1
    if a["shape"] == "polygon":
        v = a["vertices"]
        hit = False
        for (x1, y1), (x2, y2) in zip(v, v[1:] + v[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
        return hit
    return abs(x - a["x"]) <= a["w"] / 2 and abs(y - a["y"]) <= a["h"] / 2


def user_aoi(spec: Any) -> dict[str, Any]:
    """An AOI you define: a dict ({name, shape: rect|circle|ellipse, pos: [x, y], size: [w, h] | radius,
    units, routine}) or text ``name:rect:x,y,w,h`` / ``name:circle:x,y,r`` (px from the centre, +y up)."""
    if isinstance(spec, str):
        parts = spec.split(":")
        if len(parts) < 3:
            raise AnalysisError(f"AOI '{spec}': write name:rect:x,y,width,height or name:circle:x,y,radius "
                                "(pixels from the screen centre, +y up), optionally :routine at the end")
        try:
            nums = [float(v) for v in parts[2].split(",")]
        except ValueError:
            raise AnalysisError(f"AOI '{spec}': the numbers after the shape must be like 0,0,200,100") from None
        shape = parts[1].lower()
        need = 3 if shape == "circle" else 4
        if len(nums) != need:
            raise AnalysisError(f"AOI '{spec}': a {shape} needs {need} numbers")
        spec = {"name": parts[0], "shape": shape, "pos": nums[:2],
                **({"radius": nums[2]} if shape == "circle" else {"size": nums[2:4]}),
                **({"routine": parts[3]} if len(parts) > 3 and parts[3] else {})}
    if not isinstance(spec, dict) or not spec.get("name"):
        raise AnalysisError(f"an AOI needs a name, a shape and a position: {spec!r}")
    shape = str(spec.get("shape") or "rect").lower()
    if shape not in ("rect", "circle", "ellipse", "polygon"):
        raise AnalysisError(f"AOI '{spec['name']}': shape must be rect, circle, ellipse or polygon")
    return {**spec, "shape": shape, "type": "user"}


def experiment_aois(sess: Session) -> dict[str, list[dict[str, Any]]]:
    """Routine -> its AOI components (gaze areas, pictures, shapes). A picture or shape that a gaze area
    targets is represented by that gaze area."""
    out: dict[str, list[dict[str, Any]]] = {}
    for rid, r in (sess.st.experiment.get("routines") or {}).items():
        comps = [c for c in (r or {}).get("components", []) or [] if isinstance(c, dict)]
        targeted = {c.get("target") for c in comps if c.get("type") == "gaze_roi" and c.get("target")}
        lst = [c for c in comps if c.get("type") in AOI_SOURCES and c.get("id") not in targeted
               and not c.get("disabled")]
        if lst:
            out[rid] = lst
    return out


def _aois_for(sess: Session, w: dict[str, Any], exp_aois: dict[str, list[dict[str, Any]]],
              users: list[dict[str, Any]], notes: list[str]) -> list[dict[str, Any]]:
    row = w["row"]
    ns = {**(sess.meta.get("variables") or {}), **row}
    comps = {c.get("id"): c for c in ((sess.st.experiment.get("routines") or {}).get(w["routine"]) or {})
             .get("components", []) or [] if isinstance(c, dict)}
    out = []
    for c in exp_aois.get(w["routine"], []):
        src = comps.get(c.get("target")) if c.get("type") == "gaze_roi" and c.get("target") else c
        if src is None:
            continue
        onset_key = f"{src.get('id')}.onset"
        onset = row.get(onset_key)
        if src is not c and not isinstance(onset, (int, float)):
            continue
        if src.get("type") != "gaze_roi" and not isinstance(onset, (int, float)):
            continue        # never shown on this screen (start_if, a branch …)
        try:
            geo = _comp_geometry(sess, src, ns)
        except Exception as e:     # an expression we can't evaluate after the fact
            msg = f"AOI {c.get('id')} on '{w['routine']}' left out: its position or size can't be worked out ({e})"
            if msg not in notes:
                notes.append(msg)
            continue
        if geo is None:
            msg = (f"AOI {c.get('id')} on '{w['routine']}' left out: a picture shown at its own size has no known "
                   "size here; give it a size, or define the area yourself (--aoi)")
            if msg not in notes:
                notes.append(msg)
            continue
        out.append({"name": c.get("id"), "source": c.get("type") + (f" -> {src.get('id')}" if src is not c else ""),
                    "onset": w["start"] + float(onset if isinstance(onset, (int, float)) else 0.0), **geo})
    # your own AOIs: on the screen you name; otherwise on the screens with AOIs of their own, or (none) on every
    # screen of a trial list
    in_loops = any(x["row"].get("loop") for x in sess.windows())
    for u in users:
        if u.get("routine"):
            if u["routine"] != w["routine"]:
                continue
        elif exp_aois:
            if w["routine"] not in exp_aois:
                continue
        elif in_loops and not row.get("loop"):
            continue
        geo = _comp_geometry(sess, {"type": "shape", **u}, ns)
        out.append({"name": u["name"], "source": "user", "onset": w["start"], **(geo or {})})
    return out


def aoi_report(session: str | Path | Session, aois: Iterable[Any] = (), by: list[str] | None = None,
               method: str = "ivt", stream: str = "", out: str | Path | None = None, include_experiment: bool = True,
               **opts: float) -> dict[str, Any]:
    """Per trial and AOI: fixated, first fixation latency and duration, dwell time, fixation count, visits,
    revisits and proportion of the trial's fixation time; and the means per condition. Writes fixations.csv
    (with the AOI of every fixation), saccades.csv, aoi_trials.csv and aoi_summary.csv."""
    sess = session if isinstance(session, Session) else Session(session)
    users = [user_aoi(a) for a in aois or []]
    names = [u["name"] for u in users]
    if len(set(names)) != len(names):
        raise AnalysisError("two of your AOIs have the same name")
    exp_aois = experiment_aois(sess) if include_experiment else {}
    if not exp_aois and not users:
        raise AnalysisError("no areas of interest: this experiment has no gaze areas, pictures or shapes; "
                            "define your own (--aoi name:rect:x,y,width,height)")
    fx = fixations(sess, method, stream, out, write=False, **opts)
    fix = fx["fixation_rows"]
    notes = list(fx["notes"])
    by = list(by) if by is not None else sess.condition_columns()
    missing = [c for c in by if c not in sess.cols]
    if missing:
        raise AnalysisError(f"no column {missing[0]} in the trial table; columns: {', '.join(sess.cols)}")
    rows: list[dict[str, Any]] = []
    for w in sess.windows():
        areas = _aois_for(sess, w, exp_aois, users, notes)
        if not areas:
            continue
        trial_fix = [f for f in fix if f["end"] > w["start"] and f["start"] < w["end"]]
        for a in areas:
            mine = [f for f in trial_fix if f["end"] > a["onset"]]
            total = sum(min(f["end"], w["end"]) - max(f["start"], a["onset"]) for f in mine)
            hits = [inside(a, f["x"], f["y"]) for f in mine]
            for f, h in zip(mine, hits):
                if h and a["name"] not in f["aoi"].split(";"):
                    f["aoi"] = (f["aoi"] + ";" if f["aoi"] else "") + a["name"]
            in_fix = [f for f, h in zip(mine, hits) if h]
            visits = sum(1 for i, h in enumerate(hits) if h and (i == 0 or not hits[i - 1]))
            dwell = sum(min(f["end"], w["end"]) - max(f["start"], a["onset"]) for f in in_fix)
            r = {"trial": w["trial"], "routine": w["routine"], "aoi": a["name"], "aoi_source": a["source"],
                 **{c: w["trial_row"].get(c) for c in by},
                 "fixated": int(bool(in_fix)),
                 "first_fixation_latency": max(0.0, in_fix[0]["start"] - a["onset"]) if in_fix else None,
                 "first_fixation_duration": min(in_fix[0]["end"], w["end"]) - max(in_fix[0]["start"], a["onset"])
                 if in_fix else None,
                 "dwell_time": dwell, "fixation_count": len(in_fix), "visits": visits,
                 "revisits": max(0, visits - 1), "proportion": dwell / total if total > 0 else None,
                 "trial_fixation_time": total, "screen_duration": w["end"] - a["onset"]}
            rows.append(r)
    trial_cols = ["trial", "routine", "aoi", "aoi_source", *by, *AOI_TRIAL_METRICS, "trial_fixation_time",
                  "screen_duration"]
    summary = aoi_summary(rows, by)
    sum_cols = ["routine", "aoi", *by, "n_trials", "n_fixated", "p_fixated", "first_fixation_latency",
                "first_fixation_duration", "dwell_time", "fixation_count", "visits", "revisits", "proportion"]
    d = sess.out_dir(out)
    files = [str(write_csv(d / "fixations.csv", FIXATION_COLS, fix)),
             str(write_csv(d / "saccades.csv", SACCADE_COLS, fx["saccade_rows"])),
             str(write_csv(d / "aoi_trials.csv", trial_cols, rows)),
             str(write_csv(d / "aoi_summary.csv", sum_cols, summary))]
    if not rows:
        notes.append("no screen showed an AOI while gaze was recorded")
    return {**{k: v for k, v in fx.items() if k not in ("files", "notes")}, "by": by,
            "aois": sorted({r["aoi"] for r in rows}), "trial_rows": rows, "summary_rows": summary,
            "files": files, "notes": notes}


def aoi_summary(rows: list[dict[str, Any]], by: list[str]) -> list[dict[str, Any]]:
    """Means per routine, AOI and condition cell (latency and first-fixation duration over fixated trials)."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["routine"], r["aoi"], *[str(r.get(c)) for c in by]), []).append(r)
    out = []
    for key, rs in groups.items():
        def mean(col: str) -> float | None:
            vals = [r[col] for r in rs if r.get(col) is not None]
            return statistics.fmean(vals) if vals else None
        fixated = sum(r["fixated"] for r in rs)
        out.append({"routine": key[0], "aoi": key[1], **{c: rs[0].get(c) for c in by}, "n_trials": len(rs),
                    "n_fixated": fixated, "p_fixated": fixated / len(rs),
                    **{m: mean(m) for m in ("first_fixation_latency", "first_fixation_duration", "dwell_time",
                                            "fixation_count", "visits", "revisits", "proportion")}})
    return out
