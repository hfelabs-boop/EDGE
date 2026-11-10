"""What every analysis needs from a session folder: its streams, markers, trials and screen geometry.

Everything here is pure Python (no numpy needed): recorded streams are read from
``streams/<device>.<stream>.csv``, whose ``time`` column is already on EDGE's master clock (the same
clock as ``events.jsonl`` and the trial table), so markers and samples line up without further work.
"""

from __future__ import annotations

import bisect
import csv
import fnmatch
import io
import json
import math
import struct
import zipfile
from pathlib import Path
from typing import Any, Iterable

from ..export import ExportError, SessionTables, detect_factors, wide_trials

NAN = float("nan")
TRIGGER_CHANNELS = {"trig", "trigger", "event", "user", "marker", "code", "valid", "cnt", "time", "time_tick",
                    "device_time_stamp", "system_time_stamp", "fpogid", "fpogv", "bpogv", "lpv", "rpv", "cs",
                    "left_valid", "right_valid", "left_pupil_valid", "right_pupil_valid", "lpmmv", "rpmmv"}


class AnalysisError(ExportError):
    """An analysis can't run as asked (no such stream, no matching markers …), said in words with what to do."""


def isnan(v: float | None) -> bool:
    return v is None or v != v


def fnum(s: Any) -> float:
    """A CSV cell as a float; empty, text and None become NaN."""
    if s is None or s == "":
        return NAN
    try:
        return float(s)
    except (TypeError, ValueError):
        return NAN


# ============================================================================ the session
class Session:
    """One session folder, read once: tables, streams, markers, trial windows and the screen."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        if not (self.root / "session.json").exists():
            if self.root.is_dir() and any(self.root.rglob("session.json")):
                raise AnalysisError(f"{root} is a folder of sessions: choose one of the session folders inside it "
                                    "(they hold a session.json)")
            raise AnalysisError(f"{root} is not an EDGE session folder (it has no session.json)")
        self.st = SessionTables(self.root)
        self.meta = self.st.meta
        self.cols, self.trials = wide_trials(self.st)
        settings = (self.st.experiment.get("settings") or {})
        win = settings.get("window") or {}
        size = self.meta.get("window_size") or win.get("size") or [1280, 720]
        self.width, self.height = float(size[0]), float(size[1])
        mon = win.get("monitor") or {}
        self.width_cm = float(mon.get("width_cm") or 53.0)
        self.distance_cm = float(mon.get("distance_cm") or 60.0)
        self.units = str(win.get("units") or "px")
        self.events = self.st.events
        self._windows: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------ streams
    def streams(self) -> list[dict[str, Any]]:
        """Every recorded stream: name (device.stream), device, stream, kind, channels, units, srate, path."""
        out = []
        devices = self.meta.get("devices") or {}
        for f in sorted((self.root / "streams").glob("*.csv")):
            if f.name.endswith(".raw.csv"):
                continue
            device, _, stream = f.stem.partition(".")
            info = ((devices.get(device) or {}).get("streams") or {}).get(stream) or {}
            channels = info.get("channels")
            if not channels:
                with f.open(newline="", encoding="utf-8") as fh:
                    header = next(csv.reader(fh), [])
                channels = [c for c in header if c not in ("time", "device_time", "arrival_time")]
            out.append({"name": f.stem, "device": device, "stream": stream, "kind": str(info.get("kind") or ""),
                        "channels": list(channels), "units": list(info.get("units") or []),
                        "srate": float(info.get("srate") or 0.0), "coordinates": info.get("coordinates") or "",
                        "type": (devices.get(device) or {}).get("type"), "path": f})
        return out

    def find_stream(self, want: str, kinds: Iterable[str] = ()) -> dict[str, Any]:
        """A stream by ``device.stream``, device id, stream name or kind (``eeg``, ``gaze``)."""
        streams = self.streams()
        if not streams:
            raise AnalysisError(f"{self.root.name} has no recorded streams (no device recorded data in this session)")
        w = (want or "").lower()
        kinds = [k.lower() for k in kinds]
        for test in (lambda s: s["name"].lower() == w, lambda s: s["device"].lower() == w,
                     lambda s: s["stream"].lower() == w, lambda s: s["kind"].lower() == w,
                     lambda s: not w and s["kind"].lower() in kinds):
            hits = [s for s in streams if test(s)]
            if hits:
                return hits[0]
        names = ", ".join(s["name"] + (f" ({s['kind']})" if s["kind"] else "") for s in streams)
        raise AnalysisError(f"no stream '{want}' in {self.root.name}; it recorded: {names}")

    def load(self, stream: dict[str, Any], channels: list[str] | None = None) -> tuple[list[float], dict[str, list[float]]]:
        """(times, {channel: values}) of a stream; missing values are NaN."""
        want = channels if channels is not None else stream["channels"]
        try:
            import pandas as pd       # much faster for long recordings; optional
            df = pd.read_csv(stream["path"], usecols=lambda c: c == "time" or c in want)
            times = [float(x) for x in df["time"].tolist()]
            data = {c: [float(x) for x in pd.to_numeric(df[c], errors="coerce").tolist()]
                    for c in want if c in df.columns}
        except ImportError:
            times, data = [], {c: [] for c in want}
            with Path(stream["path"]).open(newline="", encoding="utf-8") as fh:
                r = csv.reader(fh)
                header = next(r, [])
                idx = {c: header.index(c) for c in want if c in header}
                data = {c: [] for c in idx}
                ti = header.index("time")
                for row in r:
                    if len(row) <= ti:
                        continue
                    times.append(fnum(row[ti]))
                    for c, i in idx.items():
                        data[c].append(fnum(row[i]) if i < len(row) else NAN)
        missing = [c for c in want if c not in data]
        if missing:
            raise AnalysisError(f"stream {stream['name']} has no channel {', '.join(missing)}; "
                                f"its channels: {', '.join(stream['channels'])}")
        return times, data

    # ------------------------------------------------------------ markers and trials
    def markers(self, patterns: Iterable[str]) -> list[dict[str, Any]]:
        """Marker events whose label matches one of ``patterns`` (exact, or wildcards like ``view_*``; a number
        matches the TTL code), in time order."""
        pats = [str(p).strip() for p in patterns if str(p).strip()]
        out = []
        for e in self.events:
            label = str(e.get("label", ""))
            if any(label == p or fnmatch.fnmatchcase(label, p) or (p.isdigit() and e.get("code") == int(p))
                   for p in pats):
                out.append(e)
        return sorted(out, key=lambda e: float(e.get("time") or 0))

    def marker_labels(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.events:
            lab = str(e.get("label", ""))
            if lab and lab not in ("session_start", "session_end"):
                counts[lab] = counts.get(lab, 0) + 1
        return counts

    def windows(self) -> list[dict[str, Any]]:
        """One entry per screen that ran: routine, start, end (master clock), trial number, the raw row and the
        trial's row of the trial table."""
        if self._windows is not None:
            return self._windows
        out, trial_no, last_key = [], 0, None
        for row in self.st.rows:
            key = row.get("trial_key") or ""
            if not (key and key == last_key):
                trial_no += 1
            last_key = key
            start = row.get("routine_start")
            dur = row.get("routine_duration")
            if not isinstance(start, (int, float)):
                continue
            end = start + (dur if isinstance(dur, (int, float)) else 0.0)
            trial = self.trials[trial_no - 1] if 0 < trial_no <= len(self.trials) else {}
            out.append({"routine": row.get("routine", ""), "start": float(start), "end": float(end),
                        "trial": trial_no, "row": row, "trial_row": trial})
        self._windows = out
        return out

    def window_at(self, t: float) -> dict[str, Any] | None:
        ws = self.windows()
        starts = [w["start"] for w in ws]
        i = bisect.bisect_right(starts, t) - 1
        if i >= 0 and t <= ws[i]["end"] + 1e-6:
            return ws[i]
        return None

    def condition_columns(self) -> list[str]:
        """Trial-list columns worth grouping by (2-12 levels, like the summary's factors)."""
        try:
            return detect_factors(self.st, self.trials)
        except Exception:
            return []

    # ------------------------------------------------------------ screen geometry
    def px_per_cm(self) -> float:
        return self.width / self.width_cm

    def to_deg(self, x_px: float, y_px: float) -> tuple[float, float]:
        """Screen position (px from the centre) as visual angle from the screen centre (degrees)."""
        k = self.px_per_cm()
        return (math.degrees(math.atan(x_px / k / self.distance_cm)),
                math.degrees(math.atan(y_px / k / self.distance_cm)))

    def to_px(self, v: Any, units: str | None = None, axis: str = "y") -> float:
        """An experiment length/coordinate in ``units`` (default: the experiment's) as pixels, like the backends."""
        units = units or self.units
        v = float(v)
        if units == "px":
            return v
        if units == "norm":
            return v * (self.width / 2 if axis == "x" else self.height / 2)
        if units == "height":
            return v * self.height
        if units == "deg":
            return 2 * self.distance_cm * math.tan(math.radians(v) / 2) * self.px_per_cm()
        raise AnalysisError(f"unknown units '{units}'")

    def out_dir(self, out: str | Path | None) -> Path:
        d = Path(out) if out else self.root / "analysis"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ============================================================================ writing
def write_csv(path: Path, cols: list[str], rows: list[dict[str, Any]]) -> Path:
    """Plain UTF-8 CSV (NaN and None as empty cells, floats to 6 decimals)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in cols])
    path.write_text(buf.getvalue(), encoding="utf-8")
    return path


def _cell(v: Any) -> Any:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if math.isfinite(v) else ""
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return v


def _npy(shape: tuple[int, ...], descr: str, payload: bytes) -> bytes:
    header = "{'descr': '%s', 'fortran_order': False, 'shape': (%s), }" % (
        descr, "".join(f"{n}, " for n in shape) if len(shape) == 1 else ", ".join(str(n) for n in shape))
    header = header.replace(", )", ",)") if len(shape) == 1 else header
    total = 10 + len(header) + 1
    header += " " * (-total % 64) + "\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin1") + payload


def npy_array(values: Any) -> bytes:
    """A .npy file of a (nested) list: floats (<f8), ints (<i8), bools (|b1) or text (<U)."""
    shape: list[int] = []
    x = values
    while isinstance(x, list):
        shape.append(len(x))
        x = x[0] if x else None
    flat: list[Any] = values
    for _ in range(len(shape) - 1):
        flat = [y for sub in flat for y in sub]
    if all(isinstance(v, bool) for v in flat) and flat:
        return _npy(tuple(shape), "|b1", bytes(int(v) for v in flat))
    if all(isinstance(v, int) and not isinstance(v, bool) for v in flat) and flat:
        return _npy(tuple(shape), "<i8", struct.pack(f"<{len(flat)}q", *flat))
    if all(isinstance(v, str) for v in flat) and flat:
        n = max(1, max(len(v) for v in flat))
        return _npy(tuple(shape), f"<U{n}", b"".join(v.ljust(n, "\0").encode("utf-32-le") for v in flat))
    return _npy(tuple(shape), "<f8", struct.pack(f"<{len(flat)}d", *[NAN if v is None else float(v) for v in flat]))


def write_npz(path: Path, arrays: dict[str, Any]) -> Path:
    """``numpy.load(path)`` reads it; written without numpy."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, values in arrays.items():
            z.writestr(f"{name}.npy", npy_array(values))
    return path


def plot_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


PLOT_NOTE = ("no plot: drawing it needs the 'matplotlib' package, which isn't installed for this EDGE "
             "(pip install edge-experiments[plots]); the CSV has the same numbers")
