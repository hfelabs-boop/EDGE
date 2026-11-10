"""Live session monitor: what the experimenter sees while a participant is running.

When a session is started from the builder (environment variable ``EDGE_MONITOR=1``) the runtime
prints one JSON line per event to stdout, prefixed with ``@edge-monitor``:

* ``start``: participant, expected number of trials, declared measures, devices and their streams;
* ``trial``: progress, the routine that just ended, the latest responses, this trial's value of each
  measure and the running summary so far;
* ``devices`` (every second): samples per second of every stream against its nominal rate, and
  whether a stream has gone silent;
* ``end``: whether the session finished or was stopped, where the data is, and each measure against what
  was expected (``measures``: recorded, not too many missing values, inside its ``expect`` range).
* ``screen`` (when a screen starts): its name, so the experimenter sees where the participant is;
* ``quality`` (every ``EDGE_QUALITY_INTERVAL`` seconds, default 2): signal quality of every device stream
  (EEG channels: RMS, 50/60 Hz line noise, flat, saturated, impedance when the amplifier reports it; eye
  trackers: valid samples, tracking losses), see :mod:`edge.quality`;
* ``paused`` / ``resumed``: the experimenter paused the session between two screens;
* ``mirror`` (opt-in, ``EDGE_MIRROR=<seconds>``): a small PNG of the participant's screen, base64.

``EDGE_STOP_FILE``: when this file appears the session stops at the next frame, exactly like
pressing Esc (everything recorded so far is kept). ``EDGE_PAUSE_FILE``: while this file exists the
session waits before the next screen (a blank screen saying "Paused"), then carries on.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

PREFIX = "@edge-monitor "
_lock = threading.Lock()


def _emit(obj: dict[str, Any]) -> None:
    line = PREFIX + json.dumps(obj, default=str)
    with _lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def from_env(session) -> "Monitor | None":
    if os.environ.get("EDGE_MONITOR") != "1":
        return None
    def num(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name) or default)
        except ValueError:
            return default
    return Monitor(session, stop_file=os.environ.get("EDGE_STOP_FILE") or None,
                   pause_file=os.environ.get("EDGE_PAUSE_FILE") or None,
                   quality_interval=num("EDGE_QUALITY_INTERVAL", 2.0), mirror_interval=num("EDGE_MIRROR", 0.0))


def parse(line: str) -> dict[str, Any] | None:
    """A monitor event from a line of output, or None for ordinary log lines."""
    if not line.startswith(PREFIX):
        return None
    try:
        return json.loads(line[len(PREFIX):])
    except ValueError:
        return None


class Monitor:
    def __init__(self, session, stop_file: str | None = None, emit=_emit, interval: float = 1.0,
                 pause_file: str | None = None, quality_interval: float = 2.0, mirror_interval: float = 0.0):
        from .measures import declared
        self.session = session
        self.stop_file = stop_file
        self.emit = emit
        self.interval = interval
        self.measures = declared({"measures": session.exp.measures})
        self.values: dict[str, list[Any]] = {m["id"]: [] for m in self.measures}
        self.n_trials = 0
        self.n_rows = 0
        self.rows: list[dict[str, Any]] = []     # every row, for the after-session "Measures vs expected" checks
        self._last_key = ""
        self.t0 = time.monotonic()
        self._last_counts: dict[tuple[str, str], tuple[float, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.pause_file = pause_file
        self.quality_interval = quality_interval
        self.mirror_interval = mirror_interval
        self._last_quality = 0.0
        self._last_mirror = 0.0
        self._mirror_job: tuple[int, int, bytes] | None = None
        self._mirror_ready = threading.Event()

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        s = self.session
        try:
            from .wizard import estimate_experiment
            est = estimate_experiment(s.exp)
        except Exception:
            est = {}
        self.emit({"type": "start", "experiment": s.exp.name, "participant": s.participant,
                   "data_dir": str(s.data.root) if s.data else None,
                   "expected_trials": est.get("trials"), "expected_minutes": est.get("minutes"),
                   "measures": [{k: m.get(k) for k in ("id", "label", "role", "column", "summary", "units", "expect")}
                                for m in self.measures],
                   "devices": {did: {"type": dev.type_name, "streams": {k: {"srate": st.srate, "channels": len(st.channels),
                                                                            "kind": st.kind}
                                                                        for k, st in dev.streams.items()}}
                               for did, dev in s.devices.items()}})
        self._thread = threading.Thread(target=self._health_loop, daemon=True)
        self._thread.start()

    def end(self, summary: dict[str, Any]) -> None:
        self._stop.set()
        self.emit({"type": "end", "aborted": bool(summary.get("aborted")), "errors": summary.get("errors") or [],
                   "crash": summary.get("crash"),
                   "trials": self.n_trials, "elapsed": round(time.monotonic() - self.t0, 1),
                   "running": self._running(), "measures": self.measure_checks(),
                   "data_dir": str(self.session.data.root) if self.session.data else None})

    def measure_checks(self) -> list[dict[str, Any]]:
        """Each declared measure against what was expected (recorded, few missing values, inside ``expect``):
        [{id, label, role, value, n, missing, units, expect, ok, notes}] (factors are left out)."""
        from .measures import measure_checks
        try:
            notes = measure_checks({"measures": self.session.exp.measures}, self.rows)
        except Exception:
            return []
        running = self._running()
        out = []
        for m in self.measures:
            if m["role"] == "factor":
                continue
            mine = [n["message"] for n in notes if n.get("measure") == m["id"]]
            r = running.get(m["id"], {})
            out.append({"id": m["id"], "label": m.get("label") or m["id"], "role": m["role"], "value": r.get("value"),
                        "n": r.get("n", 0), "missing": r.get("missing", 0), "units": m.get("units", ""),
                        "expect": m.get("expect"), "ok": not mine, "notes": mine})
        return out

    def stop_requested(self) -> bool:
        return bool(self.stop_file) and os.path.exists(self.stop_file)

    def pause_requested(self) -> bool:
        return bool(self.pause_file) and os.path.exists(self.pause_file)

    def screen(self, routine: str) -> None:
        """A screen starts: the experimenter's console shows where the participant is."""
        self.emit({"type": "screen", "routine": routine, "n": self.n_trials,
                   "elapsed": round(time.monotonic() - self.t0, 1)})

    # -------------------------------------------------------------- the participant's screen, small (opt-in)
    def mirror_due(self) -> bool:
        if self.mirror_interval <= 0:
            return False
        now = time.monotonic()
        if now - self._last_mirror < self.mirror_interval or self._mirror_job is not None:
            return False
        self._last_mirror = now
        return True

    def mirror_frame(self, width: int, height: int, rgb: bytes) -> None:
        """Hand over a small RGB picture of the screen; it is encoded and sent from the monitor's thread."""
        self._mirror_job = (width, height, rgb)
        self._mirror_ready.set()

    def _send_mirror(self) -> None:
        job, self._mirror_job = self._mirror_job, None
        if not job:
            return
        import base64
        w, h, rgb = job
        self.emit({"type": "mirror", "w": w, "h": h, "elapsed": round(time.monotonic() - self.t0, 1),
                   "png": base64.b64encode(png_bytes(w, h, rgb)).decode("ascii")})

    # -------------------------------------------------------------- signal quality
    def device_quality(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for did, dev in list(self.session.devices.items()):
            try:
                q = dev.quality()
            except Exception as e:
                q = {"_error": {"kind": "error", "status": "wait", "reasons": [f"{type(e).__name__}: {e}"]}}
            if q:
                out[did] = {"type": dev.type_name, "streams": q}
        return out

    # -------------------------------------------------------------- per trial
    def trial(self, row: dict[str, Any]) -> None:
        from .measures import _select
        self.n_rows += 1
        if len(self.rows) < 100_000:
            self.rows.append(row)
        key = row.get("trial_key") or ""
        if key and key != self._last_key:      # a new loop iteration = a new trial
            self.n_trials += 1
        self._last_key = key
        this: dict[str, Any] = {}
        for m in self.measures:
            if m["role"] == "factor" or m["column"] not in row:
                continue
            sel, _ = _select(m, [row])
            if sel:
                v = row.get(m["column"])
                self.values[m["id"]].append(v)
                this[m["id"]] = v
        factors = {m["id"]: row.get(m["column"]) for m in self.measures if m["role"] == "factor" and m["column"] in row}
        responses = {k: v for k, v in row.items() if k.rpartition(".")[2] in ("keys", "input", "rt", "corr", "rating", "clicked")
                     and isinstance(v, (str, int, float, bool, type(None)))}
        self.emit({"type": "trial", "n": self.n_trials, "row": self.n_rows, "routine": row.get("routine"),
                   "loop": row.get("loop") or None, "loop_n": row.get(f"{row.get('loop')}.n") if row.get("loop") else None,
                   "elapsed": round(time.monotonic() - self.t0, 1), "values": this, "factors": factors,
                   "responses": responses, "running": self._running()})

    def _running(self) -> dict[str, Any]:
        from .measures import _summary
        out = {}
        for m in self.measures:
            if m["role"] == "factor":
                continue
            vals = self.values[m["id"]]
            kind = m["summary"] if m["summary"] != "none" else "last"
            out[m["id"]] = {"value": _summary(kind, vals), "n": sum(v not in (None, "") for v in vals),
                            "missing": sum(v in (None, "") for v in vals)}
        return out

    # -------------------------------------------------------------- devices
    def device_health(self) -> dict[str, Any]:
        now = time.monotonic()
        out: dict[str, Any] = {}
        for did, dev in list(self.session.devices.items()):
            streams = {}
            for name, st in list(dev.streams.items()):
                n = int(dev.n_samples.get(name, 0))
                t_prev, n_prev = self._last_counts.get((did, name), (self.t0, 0))
                rate = (n - n_prev) / (now - t_prev) if now > t_prev else 0.0
                self._last_counts[(did, name)] = (now, n)
                nominal = float(st.srate or 0)
                status = "ok"
                if not nominal:
                    status = "events"          # button boxes, markers: quiet between events is normal
                elif n == n_prev and now - self.t0 > 2:
                    status = "silent"
                elif nominal and rate < 0.8 * nominal and now - self.t0 > 2:
                    status = "low"
                streams[name] = {"samples": n, "rate": round(rate, 1), "nominal": nominal or None, "status": status}
            out[did] = {"type": dev.type_name, "streams": streams, "errors": len(dev.errors)}
        return out

    def _health_loop(self) -> None:
        next_health = time.monotonic() + self.interval
        while not self._stop.is_set():
            self._mirror_ready.wait(max(0.0, min(next_health - time.monotonic(), 0.25)))
            if self._mirror_ready.is_set():
                self._mirror_ready.clear()
                try:
                    self._send_mirror()
                except Exception:
                    pass
            now = time.monotonic()
            if now < next_health or self._stop.is_set():
                continue
            next_health = now + self.interval
            try:
                self.emit({"type": "devices", "elapsed": round(now - self.t0, 1), "devices": self.device_health()})
            except Exception:
                pass
            if self.quality_interval > 0 and now - self._last_quality >= self.quality_interval:
                self._last_quality = now
                try:
                    q = self.device_quality()
                    if q:
                        self.emit({"type": "quality", "elapsed": round(now - self.t0, 1), "devices": q})
                except Exception:
                    pass


def png_bytes(width: int, height: int, rgb: bytes) -> bytes:
    """A PNG file of an RGB picture (rows top to bottom), with nothing but the standard library."""
    import struct
    import zlib
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
