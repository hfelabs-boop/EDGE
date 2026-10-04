"""Session data on disk.

Layout of one session folder::

    data/001_1_stroop_2027-01-31_1405/
      session.json          metadata, settings, device info, clock models, timing summary
      experiment.yaml       exact copy of the experiment that ran
      trials.jsonl          one record per routine run, written immediately (crash-safe)
      trials.csv            the same, as a spreadsheet (written at the end)
      events.jsonl          every marker with master-clock time and per-device delivery times
      frames.csv            every screen flip (frame index, time, interval, dropped flag)
      streams/<device>.<stream>.csv   device data: device_time, arrival_time, time (aligned), channels...

Everything is plain text so it opens in Excel, R, MATLAB, pandas, or a text
editor, without EDGE.
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .sync import ClockModel


def _json_default(o: Any) -> Any:
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "item"):      # numpy scalars
        return o.item()
    if hasattr(o, "tolist"):    # numpy arrays
        return o.tolist()
    return str(o)


def safe_filename(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)


class StreamWriter:
    """Streams samples to ``<name>.raw.csv``; on close rewrites with an aligned time column."""

    def __init__(self, path: Path, channels: list[str]):
        self.path = path
        self.raw_path = path.with_suffix(".raw.csv")
        self.channels = channels
        self._f = self.raw_path.open("w", newline="", encoding="utf-8", buffering=1 << 16)
        self._w = csv.writer(self._f)
        self._w.writerow(["device_time", "arrival_time"] + channels)
        self._lock = threading.Lock()
        self.count = 0

    def write(self, t_dev: float, t_arr: float, values: list[Any]) -> None:
        with self._lock:
            self._w.writerow([repr(t_dev) if isinstance(t_dev, float) else t_dev, f"{t_arr:.6f}"] + list(values))
            self.count += 1

    def finalize(self, model: ClockModel, time_base: str) -> None:
        with self._lock:
            self._f.close()
        with self.raw_path.open(newline="", encoding="utf-8") as src, \
                self.path.open("w", newline="", encoding="utf-8") as dst:
            r = csv.reader(src)
            w = csv.writer(dst)
            header = next(r)
            w.writerow(["time"] + header)
            for row in r:
                t_dev = float(row[0])
                t = t_dev if time_base == "master" else model.to_master(t_dev)
                w.writerow([f"{t:.6f}"] + row)
        os.remove(self.raw_path)


class SessionData:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "streams").mkdir(exist_ok=True)
        self._trials = (root / "trials.jsonl").open("w", encoding="utf-8", buffering=1)
        self._events = (root / "events.jsonl").open("w", encoding="utf-8", buffering=1)
        self._frames_f = (root / "frames.csv").open("w", newline="", encoding="utf-8", buffering=1 << 16)
        self._frames = csv.writer(self._frames_f)
        self._frames.writerow(["frame", "time", "interval_ms", "dropped", "routine"])
        self.streams: dict[tuple[str, str], StreamWriter] = {}
        self.trial_rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @staticmethod
    def make_dir(base: Path, pattern: str, fields: dict[str, Any]) -> Path:
        fields = dict(fields)
        fields.setdefault("date", datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        name = safe_filename(pattern.format_map(_DefaultDict(fields)))
        path = base / name
        i = 1
        while path.exists():
            i += 1
            path = base / f"{name}_{i}"
        return path

    # ------------------------------------------------------------------ writers
    def add_trial(self, row: dict[str, Any]) -> None:
        with self._lock:
            self.trial_rows.append(row)
            self._trials.write(json.dumps(row, default=_json_default) + "\n")

    def add_event(self, ev: dict[str, Any]) -> None:
        with self._lock:
            self._events.write(json.dumps(ev, default=_json_default) + "\n")

    def add_frame(self, idx: int, t: float, interval: float | None, dropped: bool, routine: str) -> None:
        self._frames.writerow([idx, f"{t:.6f}", "" if interval is None else f"{interval * 1e3:.3f}", int(dropped), routine])

    def open_stream(self, device: str, stream: str, channels: list[str]) -> StreamWriter:
        w = StreamWriter(self.root / "streams" / f"{safe_filename(device)}.{safe_filename(stream)}.csv", channels)
        self.streams[(device, stream)] = w
        return w

    def write_json(self, name: str, obj: Any) -> None:
        (self.root / name).write_text(json.dumps(obj, indent=2, default=_json_default), encoding="utf-8")

    def write_text(self, name: str, text: str) -> None:
        (self.root / name).write_text(text, encoding="utf-8")

    def close(self) -> None:
        self._trials.close()
        self._events.close()
        self._frames_f.close()
        self.write_trials_csv()

    def write_trials_csv(self) -> None:
        cols: list[str] = []
        seen: set[str] = set()
        for row in self.trial_rows:
            for k in row:
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in self.trial_rows:
            w.writerow({k: _cell(v) for k, v in row.items()})
        (self.root / "trials.csv").write_text(buf.getvalue(), encoding="utf-8")


def _cell(v: Any) -> Any:
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, default=_json_default)
    if v is None:
        return ""
    return v


class _DefaultDict(dict):
    def __missing__(self, key: str) -> str:
        return key


def load_session(path: str | Path) -> dict[str, Any]:
    """Load a finished session folder into Python structures (pandas DataFrames if available)."""
    root = Path(path)
    out: dict[str, Any] = {"meta": json.loads((root / "session.json").read_text())}
    trials = [json.loads(l) for l in (root / "trials.jsonl").read_text().splitlines() if l.strip()]
    events = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines() if l.strip()]
    streams = {}
    for f in sorted((root / "streams").glob("*.csv")):
        if f.name.endswith(".raw.csv"):
            continue
        streams[f.stem] = f
    try:
        import pandas as pd  # type: ignore
        out["trials"] = pd.DataFrame(trials)
        out["events"] = pd.DataFrame(events)
        out["streams"] = {k: pd.read_csv(v) for k, v in streams.items()}
    except ImportError:
        out["trials"] = trials
        out["events"] = events
        out["streams"] = {k: list(csv.DictReader(v.open())) for k, v in streams.items()}
    return out
