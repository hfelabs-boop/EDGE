"""Gamma (colour) calibration: make contrast linear on the experiment's monitor.

A monitor's light output is not proportional to the pixel value: L(v) ≈ L0 + k · v^γ with γ around 2.2. Gratings,
Gabors and noise are specified in linear contrast, so EDGE needs γ to show them right.

Settings (``settings.window``)::

    gamma: 2.2                      # one value for all three channels
    gamma: [2.1, 2.2, 2.3]          # per channel (red, green, blue)
    gamma: calibration/lab1.json    # a calibration file with the measured luminance table (``edge gamma``)
    monitor: {calibration: calibration/lab1.json}   # the same, next to the monitor's size and distance
    gamma_method: auto              # auto | ramp | stimuli

``ramp`` loads a correction into the graphics card's gamma table (the whole screen becomes linear, pictures and text
too, as in PsychoPy); ``stimuli`` corrects only the procedural stimuli (gratings, Gabors, noise) and the background
colour, computing their texture values through the inverse of the measured curve. ``auto`` uses the ramp where the
system allows it and falls back to ``stimuli``. session.json says which calibration was used and how.

The procedure (``edge gamma``, or Experiment settings → Colour & gamma in the builder) shows full-screen grey patches
at N levels; you read each with a photometer, EDGE fits γ (and the black level) and saves a calibration file in the
experiment's ``calibration/`` folder.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

METHODS = ("auto", "ramp", "stimuli")
CHANNELS = ("r", "g", "b")
FOLDER = "calibration"
GAMMA_RANGE = (0.3, 6.0)       # anything outside is a typo, not a monitor


# ============================================================================ fitting
def _normalize_levels(levels: Sequence[float]) -> list[float]:
    lv = [float(x) for x in levels]
    if lv and max(lv) > 1.0:      # 0..255 pixel values
        lv = [x / 255.0 for x in lv]
    return lv


def fit_gamma(levels: Sequence[float], luminance: Sequence[float]) -> dict[str, Any]:
    """Fit L(v) = L0 + k · v^γ to measured luminance (any units, e.g. cd/m²) at pixel levels v (0..1 or 0..255).
    Returns {gamma, l0, k, lmin, lmax, rmse, r2}. Least squares: for each γ the best L0 and k are linear, and γ
    is found by a golden-section search (no scipy needed)."""
    lv = _normalize_levels(levels)
    lum = [float(x) for x in luminance]
    if len(lv) != len(lum):
        raise ValueError(f"{len(lv)} levels but {len(lum)} readings: give one reading per level")
    pts = [(v, L) for v, L in zip(lv, lum) if math.isfinite(v) and math.isfinite(L)]
    if len(pts) < 3:
        raise ValueError("at least 3 readings are needed to fit gamma (9 or more is better)")
    if len({v for v, _ in pts}) < 3:
        raise ValueError("the readings must be at 3 or more different grey levels")
    if max(L for _, L in pts) <= min(L for _, L in pts):
        raise ValueError("the readings don't increase with the grey level: is the photometer pointed at the patch?")

    def solve(g: float) -> tuple[float, float, float]:
        xs = [v ** g for v, _ in pts]
        ys = [L for _, L in pts]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx > 0 else 0.0
        l0 = my - k * mx
        sse = sum((l0 + k * x - y) ** 2 for x, y in zip(xs, ys))
        return sse, l0, k

    lo, hi = math.log(GAMMA_RANGE[0]), math.log(GAMMA_RANGE[1])
    phi = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = solve(math.exp(c))[0], solve(math.exp(d))[0]
    for _ in range(80):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = solve(math.exp(c))[0]
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = solve(math.exp(d))[0]
    g = math.exp((a + b) / 2)
    sse, l0, k = solve(g)
    ys = [L for _, L in pts]
    my = sum(ys) / len(ys)
    sst = sum((y - my) ** 2 for y in ys)
    return {"gamma": round(g, 4), "l0": round(l0, 6), "k": round(k, 6), "lmin": min(ys), "lmax": max(ys),
            "rmse": round(math.sqrt(sse / len(pts)), 6), "r2": round(1 - sse / sst, 6) if sst > 0 else None}


def default_levels(n: int = 9) -> list[float]:
    n = max(3, min(64, int(n)))
    return [round(i / (n - 1), 4) for i in range(n)]


def read_readings_csv(text: str) -> tuple[list[float], dict[str, list[float]]]:
    """Readings from CSV text: a level column (level / value / v, 0..1 or 0..255) and a luminance column
    (luminance / lum / cd/m2 / grey / y) or one column per channel (r, g, b). A file of one number per line is read as
    luminance at evenly spaced levels."""
    rows = [r for r in csv.reader(io.StringIO(text.strip())) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("the CSV is empty")

    def num(x: str) -> float | None:
        try:
            return float(x.strip().replace(",", "."))
        except ValueError:
            return None

    if all(len(r) == 1 and num(r[0]) is not None for r in rows):
        lum = [num(r[0]) for r in rows]
        return default_levels(len(lum)), {"grey": [float(x) for x in lum if x is not None]}
    head = [c.strip().lower() for c in rows[0]]
    if all(num(c) is not None for c in rows[0]):          # no header: level, luminance
        head = ["level", "luminance"] + [f"c{i}" for i in range(len(rows[0]) - 2)]
        body = rows
    else:
        body = rows[1:]
    def col(*names: str) -> int | None:
        for nm in names:
            for i, h in enumerate(head):
                if h == nm or h.startswith(nm + " ") or h.startswith(nm + "("):
                    return i
        return None
    li = col("level", "value", "v", "pixel", "grey level", "gray level", "input")
    chans: dict[str, int] = {}
    for key, names in (("grey", ("luminance", "lum", "cd/m2", "cd/m²", "grey", "gray", "y", "l", "reading")),
                       ("r", ("r", "red")), ("g", ("g", "green")), ("b", ("b", "blue"))):
        i = col(*names)
        if i is not None and i != li:
            chans[key] = i
    if not chans:
        raise ValueError("no luminance column: name it 'luminance' (or r, g, b for one column per channel)")
    levels: list[float] = []
    out: dict[str, list[float]] = {k: [] for k in chans}
    for r in body:
        lvl = num(r[li]) if li is not None and li < len(r) else None
        vals = {k: num(r[i]) if i < len(r) else None for k, i in chans.items()}
        if any(v is None for v in vals.values()):
            continue
        levels.append(lvl if lvl is not None else float("nan"))
        for k, v in vals.items():
            out[k].append(float(v))  # type: ignore[arg-type]
    if not levels:
        raise ValueError("no readings found in the CSV (numbers under a 'luminance' column, one row per level)")
    if li is None or any(math.isnan(x) for x in levels):
        levels = default_levels(len(next(iter(out.values()))))
    return levels, out


def make_calibration(levels: Sequence[float], readings: dict[str, Sequence[float]] | Sequence[float],
                     monitor: str = "", units: str = "cd/m2", note: str = "") -> dict[str, Any]:
    """A calibration file's contents: the measured table and the fitted γ per channel."""
    if not isinstance(readings, dict):
        readings = {"grey": list(readings)}
    lv = _normalize_levels(levels)
    fits = {k: fit_gamma(lv, v) for k, v in readings.items()}
    if all(k in fits for k in CHANNELS):
        gamma = [fits[k]["gamma"] for k in CHANNELS]
    else:
        g = fits.get("grey") or next(iter(fits.values()))
        gamma = [g["gamma"]] * 3
    return {"edge_calibration": 1, "created": datetime.now().isoformat(timespec="seconds"), "monitor": monitor,
            "units": units, "levels": lv, "luminance": {k: [float(x) for x in v] for k, v in readings.items()},
            "fit": fits, "gamma": gamma, **({"note": note} if note else {})}


def safe_name(name: str) -> str:
    n = re.sub(r"[^\w.\- ]+", "_", str(name or "").strip()).strip(". ") or "monitor"
    return n[:-5] if n.lower().endswith(".json") else n


def save_calibration(exp_dir: Path, name: str, cal: dict[str, Any]) -> Path:
    """Write calibration/<name>.json in the experiment's folder (never outside it); returns the path."""
    folder = Path(exp_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    p = (folder / f"{safe_name(name)}.json").resolve()
    if folder.resolve() not in p.parents:
        raise PermissionError("the calibration file must be in the experiment's calibration folder")
    p.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    return p


# ============================================================================ the calibration in use
class Calibration:
    """Turns wanted linear intensity (0..1) into device values (0..1) per channel."""

    def __init__(self, gamma: Sequence[float], table: dict[str, Any] | None = None, source: str = "value",
                 file: str | None = None, sha256: str | None = None):
        self.gamma = [float(g) for g in gamma]
        self.source = source
        self.file = file
        self.sha256 = sha256
        self.table = None
        # a measured table is inverted directly (interpolation), which follows a curve that is not a pure power law
        if table and table.get("levels") and table.get("luminance"):
            lv = _normalize_levels(table["levels"])
            lum = table["luminance"]
            per: list[tuple[list[float], list[float]] | None] = []
            for i, ch in enumerate(CHANNELS):
                ys = lum.get(ch) or lum.get("grey") or lum.get("gray") or (next(iter(lum.values())) if lum else None)
                per.append(_monotone_table(lv, ys) if ys else None)
            if all(p is not None for p in per):
                self.table = per

    def linearize(self, v: Any, ch: int = 0) -> Any:
        """Device value for linear intensity v (a float or a numpy array), channel 0/1/2."""
        tab = self.table[ch] if self.table else None
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            np = None  # type: ignore[assignment]
        if tab is not None:
            xs, ys = tab                      # ys: normalized luminance (0..1, increasing) at device values xs
            if np is not None and not isinstance(v, (int, float)):
                return np.interp(np.clip(v, 0.0, 1.0), ys, xs)
            return _interp(min(1.0, max(0.0, float(v))), ys, xs)
        g = self.gamma[ch] if ch < len(self.gamma) else self.gamma[0]
        if np is not None and not isinstance(v, (int, float)):
            return np.power(np.clip(v, 0.0, 1.0), 1.0 / g)
        return min(1.0, max(0.0, float(v))) ** (1.0 / g)

    def device_color(self, rgba: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """A colour given in linear terms (e.g. the background grey) as the device value that shows it."""
        r, g, b, a = rgba
        return (round(self.linearize(r / 255, 0) * 255), round(self.linearize(g / 255, 1) * 255),
                round(self.linearize(b / 255, 2) * 255), a)

    def ramp(self, n: int = 256) -> list[list[int]]:
        """The graphics card's gamma table (16-bit values, n entries per channel) that makes the screen linear."""
        return [[int(round(min(1.0, max(0.0, self.linearize(i / (n - 1), ch))) * 65535)) for i in range(n)]
                for ch in range(3)]

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "gamma": self.gamma, "file": self.file, "sha256": self.sha256,
                "table": bool(self.table)}


def _monotone_table(levels: list[float], lum: Sequence[float]) -> tuple[list[float], list[float]] | None:
    pts = sorted((float(v), float(L)) for v, L in zip(levels, lum))
    if len(pts) < 2:
        return None
    lo, hi = pts[0][1], pts[-1][1]
    if hi <= lo:
        return None
    xs, ys = [], []
    best = -1.0
    for v, L in pts:
        y = (L - lo) / (hi - lo)
        if y <= best:                         # noise in the readings: keep the curve increasing
            continue
        best = y
        xs.append(v)
        ys.append(y)
    if xs[0] != 0.0 or ys[0] != 0.0:
        xs.insert(0, 0.0)
        ys.insert(0, 0.0)
    return xs, ys


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1]) if xs[i] > xs[i - 1] else 0.0
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def gamma_setting(window: dict[str, Any]) -> Any:
    """The calibration the window settings ask for: window.gamma, or window.monitor.calibration."""
    g = (window or {}).get("gamma")
    if g in (None, "", [], False):
        mon = (window or {}).get("monitor")
        g = mon.get("calibration") if isinstance(mon, dict) else None
    return g if g not in ("", [], False) else None


def load_calibration(setting: Any, base_dir: Path | str = ".") -> Calibration | None:
    """The Calibration for a gamma setting (number, [r, g, b] or a file), or None for no correction.
    Raises ValueError with a plain message when the setting can't be used."""
    if setting is None:
        return None
    if isinstance(setting, bool):
        raise ValueError("gamma must be a number such as 2.2, three numbers [r, g, b], or a calibration file")
    if isinstance(setting, (int, float)):
        g = float(setting)
        _check_gamma(g)
        return Calibration([g, g, g], source="value")
    if isinstance(setting, (list, tuple)):
        if len(setting) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in setting):
            raise ValueError("per-channel gamma must be three numbers [red, green, blue], e.g. [2.1, 2.2, 2.3]")
        for x in setting:
            _check_gamma(float(x))
        return Calibration([float(x) for x in setting], source="value")
    if isinstance(setting, str):
        s = setting.strip()
        try:
            return load_calibration(float(s), base_dir)
        except ValueError as e:
            if re.fullmatch(r"[-+]?\d+(\.\d*)?", s):
                raise e
        p = Path(s)
        if not p.is_absolute():
            p = Path(base_dir) / p
        if not p.is_file():
            raise ValueError(f"calibration file not found: {s} (make one with 'edge gamma' or in Experiment settings "
                             "→ Colour & gamma)")
        raw = p.read_bytes()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"{s} is not a calibration file EDGE can read (not JSON: {e})") from None
        if not isinstance(data, dict):
            raise ValueError(f"{s} is not a calibration file (expected gamma and/or levels with luminance)")
        gamma = data.get("gamma")
        if gamma is None and data.get("levels") and data.get("luminance"):
            gamma = make_calibration(data["levels"], data["luminance"])["gamma"]
        if isinstance(gamma, (int, float)) and not isinstance(gamma, bool):
            gamma = [gamma] * 3
        if not (isinstance(gamma, list) and len(gamma) == 3):
            raise ValueError(f"{s} has no gamma and no measured luminance table (levels + luminance)")
        for x in gamma:
            _check_gamma(float(x))
        table = {"levels": data["levels"], "luminance": data["luminance"]} \
            if data.get("levels") and isinstance(data.get("luminance"), dict) else None
        return Calibration(gamma, table=table, source="file", file=s, sha256=hashlib.sha256(raw).hexdigest())
    raise ValueError("gamma must be a number such as 2.2, three numbers [r, g, b], or a calibration file")


def _check_gamma(g: float) -> None:
    if not math.isfinite(g) or not GAMMA_RANGE[0] <= g <= GAMMA_RANGE[1]:
        raise ValueError(f"gamma {g:g} is not a monitor's gamma (they are between 1.5 and 3, usually about 2.2)")


# ============================================================================ validation
def gamma_issues(exp: Any) -> list:
    """Problems with settings.window.gamma / gamma_method / monitor.calibration (and a note when procedural
    stimuli run without a calibration)."""
    from .model import Issue
    win = exp.settings.get("window") or {}
    out: list = []
    if not isinstance(win, dict):
        return out
    method = win.get("gamma_method")
    if method is not None and method not in METHODS:
        out.append(Issue("error", "settings.window.gamma_method", f"must be one of {', '.join(METHODS)}",
                         hint="auto uses the graphics card's gamma table where it can, stimuli corrects only gratings, "
                              "Gabors and noise"))
    mon = win.get("monitor")
    if mon is not None and not isinstance(mon, dict):
        out.append(Issue("error", "settings.window.monitor", "must be a mapping (width_cm, distance_cm, calibration)"))
    elif isinstance(mon, dict):
        for k in ("width_cm", "distance_cm", "width_px"):
            v = mon.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                out.append(Issue("error", f"settings.window.monitor.{k}", "must be a positive number"))
    where = "settings.window.gamma" if win.get("gamma") not in (None, "", [], False) else "settings.window.monitor.calibration"
    setting = gamma_setting(win)
    cal = None
    try:
        cal = load_calibration(setting, exp.base_dir)
    except ValueError as e:
        out.append(Issue("error", where, str(e),
                         hint="e.g. gamma: 2.2, gamma: [2.1, 2.2, 2.3], or gamma: calibration/monitor.json"))
    except OSError as e:
        out.append(Issue("error", where, f"can't read the calibration file: {e}"))
    if cal is not None and isinstance(setting, str) and Path(setting).is_absolute():
        out.append(Issue("warning", where, "absolute path: the experiment will break on another computer",
                         hint="keep calibration files in the experiment's calibration/ folder"))
    linear_types = {"grating", "gabor", "noise"}
    uses = [f"routines.{rid}.{c.id}" for rid, r in exp.routines.items() for c in r.components if c.type in linear_types]
    if uses and setting is None:
        out.append(Issue("info", uses[0], "no gamma calibration: contrast of gratings, Gabors and noise is not linear "
                         "on an uncalibrated monitor", hint="measure the monitor with 'edge gamma' (or Experiment "
                         "settings → Colour & gamma) and set settings.window.gamma"))
    return out


# ============================================================================ at session start
def apply_gamma(session: Any) -> dict[str, Any] | None:
    """Load the experiment's calibration and hand it to the backend. Returns what session.json records."""
    win = session.settings.get("window") or {}
    setting = gamma_setting(win)
    if setting is None:
        return None
    try:
        cal = load_calibration(setting, session.exp.base_dir)
    except (ValueError, OSError) as e:
        session.warnings.append(f"gamma calibration not used: {e}")
        return {"used": False, "setting": setting, "error": str(e)}
    if cal is None:
        return None
    method = win.get("gamma_method") or "auto"
    applied = "stimuli"
    note = ""
    setter = getattr(session.backend, "set_gamma", None)
    if setter is not None:
        try:
            applied, note = setter(cal, method)
        except Exception as e:     # never stop a session over this: fall back to correcting the stimuli
            applied, note = "stimuli", f"the graphics card's gamma table could not be set ({e})"
    if applied == "stimuli":
        session.backend.linearize = cal.linearize
        try:   # the background is the mean grey of the patterns: correct it the same way
            session.backend.set_background(win.get("background", "#000000"))
        except Exception:
            pass
    if method == "ramp" and applied != "ramp":
        session.warnings.append(f"gamma: the screen's gamma table could not be set ({note or 'not supported here'}); "
                                "only gratings, Gabors, noise and the background are corrected")
    return {"used": True, **cal.to_dict(), "method": applied, "requested": method, **({"note": note} if note else {})}


# ============================================================================ the measurement procedure
def patch_levels(n: int = 9) -> list[float]:
    return default_levels(n)


def run_procedure(backend: Any, levels: Iterable[float], ask, background: str = "#000000",
                  patch_fraction: float = 1.0) -> list[float]:
    """Show each grey level full screen (or a centred patch) and ask for the photometer reading.

    ``ask(i, level)`` is called while the patch is on the screen and returns the reading (float) or None to stop.
    The backend keeps flipping between calls through ``ask`` itself when it is interactive."""
    out = []
    w, h = backend.size
    for i, lv in enumerate(levels):
        v = int(round(float(lv) * 255))
        patch = backend.make_shape("rect", pos=(0, 0), size=(w * patch_fraction, h * patch_fraction),
                                   fill=(v, v, v), line_color=None, opacity=1.0, ori=0)
        def draw(patch=patch):
            patch.draw()
        r = ask(i, float(lv), draw)
        if r is None:
            break
        out.append(float(r))
    return out


# ============================================================================ `edge gamma`
PROCEDURE = """How to measure the monitor (about 10 minutes):

 1. Warm the monitor up for 30 minutes; set its brightness and contrast as they will be in the study and
    turn off dynamic contrast, eco modes, night light / True Tone and any "picture mode" processing.
 2. Darken the room as it will be during the study. Point a photometer (or a colorimeter that reports
    luminance, cd/m²) at the centre of the screen, perpendicular and close to it.
 3. EDGE shows {n} grey levels, from black (0) to white (1), one after the other, filling the window.
    Read the luminance of each; type it (in the window, or here) and press Enter.
 4. EDGE fits gamma (L = L0 + k·v^γ) and saves the readings and the fit in calibration/{name}.json next to
    the experiment. Use it with settings.window.gamma: calibration/{name}.json (--use does that for you).

Levels: {levels}
"""


def add_cli(sub: Any) -> None:
    """The `edge gamma` command (registered by edge/cli.py)."""
    g = sub.add_parser("gamma", help="measure the monitor's gamma with a photometer and save a calibration file")
    g.add_argument("experiment", help="the experiment file; the calibration is saved in its calibration/ folder")
    g.add_argument("--levels", type=int, default=9, help="number of grey levels to measure (default 9)")
    g.add_argument("--csv", help="read the readings from a CSV file (level, luminance; or level, r, g, b)")
    g.add_argument("--readings", help="the readings, comma-separated, one per level from black to white")
    g.add_argument("--show", action="store_true", help="show the grey patches in the experiment window and type "
                   "each reading there (otherwise: type them in this terminal)")
    g.add_argument("--name", default="monitor", help="calibration file name (default: monitor → calibration/monitor.json)")
    g.add_argument("--monitor", default="", help="a description of the monitor (model, settings) saved in the file")
    g.add_argument("--use", action="store_true", help="also set the experiment's settings.window.gamma to the new file")
    g.add_argument("--fit-only", action="store_true", help="show the fit without saving anything")
    g.set_defaults(fn=cmd_gamma)


def cmd_gamma(a: Any) -> int:
    from .model import Experiment
    exp = Experiment.load(a.experiment)
    exp_dir = Path(exp.base_dir)
    name = safe_name(a.name)
    levels = default_levels(a.levels)
    readings: dict[str, list[float]] | None = None
    if a.csv:
        levels, readings = read_readings_csv(Path(a.csv).read_text(encoding="utf-8-sig"))
    elif a.readings:
        vals = [float(x) for x in re.split(r"[,;\s]+", a.readings.strip()) if x]
        if len(vals) != len(levels):
            levels = default_levels(len(vals))
        readings = {"grey": vals}
    else:
        print(PROCEDURE.format(n=len(levels), name=name, levels=", ".join(f"{v:g}" for v in levels)))
        vals = _show_and_ask(exp, levels) if a.show else _ask_terminal(levels)
        if vals is None or len(vals) < len(levels):
            print("edge gamma: stopped before every level was measured; nothing saved")
            return 1
        readings = {"grey": vals}
    cal = make_calibration(levels, readings, monitor=a.monitor)
    print(describe_fit(cal))
    if a.fit_only:
        return 0
    path = save_calibration(exp_dir, name, cal)
    rel = path.relative_to(exp_dir.resolve()).as_posix() if exp_dir.resolve() in path.parents else str(path)
    print(f"Saved {path}")
    if a.use:
        from .storage import load_document, save_document
        doc = load_document(a.experiment)
        win = doc.doc.setdefault("settings", {}).setdefault("window", {})
        win["gamma"] = rel
        save_document(a.experiment, doc.doc, doc.fingerprint, label="gamma calibration")
        print(f"settings.window.gamma is now {rel}")
    else:
        print(f"To use it: settings.window.gamma: {rel}   (or run again with --use)")
    return 0


def describe_fit(cal: dict[str, Any]) -> str:
    lines = []
    for ch, f in cal["fit"].items():
        r2 = f" (R² {f['r2']:.4f})" if f.get("r2") is not None else ""
        lines.append(f"  {ch:>4}: gamma {f['gamma']:.3f}, black {f['l0']:.3g}, white {f['lmax']:.4g} "
                     f"{cal.get('units', '')}, fit error {f['rmse']:.3g}{r2}")
    g = cal["gamma"]
    head = f"Gamma {g[0]:.3f}" if len(set(g)) == 1 else "Gamma r/g/b " + " / ".join(f"{x:.3f}" for x in g)
    return head + "\n" + "\n".join(lines)


def _ask_terminal(levels: list[float]) -> list[float] | None:
    out = []
    for i, lv in enumerate(levels):
        while True:
            try:
                s = input(f"  level {i + 1}/{len(levels)} ({lv:g}, pixel value {round(lv * 255)}): luminance = ")
            except EOFError:
                return None
            s = s.strip().replace(",", ".")
            if s.lower() in ("q", "quit", "stop"):
                return None
            try:
                out.append(float(s))
                break
            except ValueError:
                print("    a number, please (or q to stop)")
    return out


_DIGIT_KEYS = {**{str(i): str(i) for i in range(10)}, **{f"num_{i}": str(i) for i in range(10)},
               "period": ".", "num_decimal": ".", "comma": "."}


def window_reader(b: Any, n: int):
    """ask() for :func:`run_procedure` that takes the reading typed into the experiment window."""
    def ask(i: int, lv: float, draw) -> float | None:
        typed = ""
        while True:
            draw()
            label = b.make_text(text=f"{i + 1}/{n}  level {lv:g}   reading: {typed}_   (Enter: next, Esc: stop)",
                                color="#ff3030", height=14, pos=(0, -b.size[1] / 2 + 14), font="", bold=False,
                                italic=False, wrap_width=None, direction="ltr", opacity=1.0, ori=0)
            label.draw()
            b.flip()
            for ev in b.poll_events():
                if ev.kind != "key" or not ev.down:
                    continue
                if ev.name == "escape":
                    return None
                if ev.name in ("return", "num_enter") and typed:
                    try:
                        return float(typed)
                    except ValueError:
                        typed = ""
                elif ev.name == "backspace":
                    typed = typed[:-1]
                elif ev.name in _DIGIT_KEYS:
                    typed += _DIGIT_KEYS[ev.name]
            if getattr(b, "escape_at", None) is None and hasattr(b, "_escape"):
                b._escape = False
    return ask


def _show_and_ask(exp: Any, levels: list[float]) -> list[float] | None:     # pragma: no cover - needs a screen
    """Full-window patches in the experiment window; the reading is typed in the window (digits, Enter)."""
    from .backends.pyglet_backend import PygletBackend
    b = PygletBackend()
    b.open({**exp.settings["window"], "background": "#000000"})
    try:
        vals = run_procedure(b, levels, window_reader(b, len(levels)))
        return vals if len(vals) == len(levels) else None
    finally:
        b.close()


# ============================================================================ the builder (POST /api/gamma)
def gamma_api(exp_file: Path, body: dict[str, Any]) -> dict[str, Any]:
    """Fit readings sent by the builder's Colour & gamma section; with save: true write calibration/<name>.json next
    to the experiment (exp_file is already confined to the builder's folder). Raises ValueError in plain words."""
    levels = body.get("levels")
    readings = body.get("readings")

    def nums(v: Any, what: str) -> list[float]:
        if not isinstance(v, list) or not v:
            raise ValueError(f"{what} must be a list of numbers")
        out = []
        for x in v:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
                raise ValueError(f"{what} must be numbers; {x!r} is not")
            out.append(float(x))
        return out

    lv = nums(levels, "levels")
    if len(lv) > 256:
        raise ValueError("at most 256 levels")
    if isinstance(readings, dict):
        rd = {str(k): nums(v, f"readings for {k}") for k, v in readings.items() if k in ("grey", *CHANNELS)}
        if not rd:
            raise ValueError("readings need 'grey' (or r, g, b)")
    else:
        rd = {"grey": nums(readings, "readings")}
    cal = make_calibration(lv, rd, monitor=str(body.get("monitor") or ""))
    out: dict[str, Any] = {"gamma": cal["gamma"], "fit": cal["fit"], "summary": describe_fit(cal), "file": None}
    if body.get("save"):
        exp_dir = Path(exp_file).parent
        p = save_calibration(exp_dir, str(body.get("name") or "monitor"), cal)
        out["file"] = p.relative_to(exp_dir.resolve()).as_posix()
    return out
