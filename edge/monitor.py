"""Live session monitor: what the experimenter sees while a participant is running.

When a session is started from the builder (environment variable ``EDGE_MONITOR=1``) the runtime
prints one JSON line per event to stdout, prefixed with ``@edge-monitor``:

* ``start``: participant, expected number of trials, declared measures, devices and their streams;
* ``trial``: progress, the routine that just ended, the latest responses, this trial's value of each
  measure and the running summary so far;
* ``devices`` (every second): samples per second of every stream against its nominal rate, and
  whether a stream has gone silent;
* ``end``: whether the session finished or was stopped, and where the data is.

``EDGE_STOP_FILE``: when this file appears the session stops at the next frame, exactly like
pressing Esc (everything recorded so far is kept).
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
    return Monitor(session, stop_file=os.environ.get("EDGE_STOP_FILE") or None)


def parse(line: str) -> dict[str, Any] | None:
    """A monitor event from a line of output, or None for ordinary log lines."""
    if not line.startswith(PREFIX):
        return None
    try:
        return json.loads(line[len(PREFIX):])
    except ValueError:
        return None


class Monitor:
    def __init__(self, session, stop_file: str | None = None, emit=_emit, interval: float = 1.0):
        from .measures import declared
        self.session = session
        self.stop_file = stop_file
        self.emit = emit
        self.interval = interval
        self.measures = declared({"measures": session.exp.measures})
        self.values: dict[str, list[Any]] = {m["id"]: [] for m in self.measures}
        self.n_trials = 0
        self.n_rows = 0
        self._last_key = ""
        self.t0 = time.monotonic()
        self._last_counts: dict[tuple[str, str], tuple[float, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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
                   "trials": self.n_trials, "elapsed": round(time.monotonic() - self.t0, 1),
                   "running": self._running(), "data_dir": str(self.session.data.root) if self.session.data else None})

    def stop_requested(self) -> bool:
        return bool(self.stop_file) and os.path.exists(self.stop_file)

    # -------------------------------------------------------------- per trial
    def trial(self, row: dict[str, Any]) -> None:
        from .measures import _select
        self.n_rows += 1
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
                if n == n_prev and now - self.t0 > 2:
                    status = "silent"
                elif nominal and rate < 0.8 * nominal and now - self.t0 > 2:
                    status = "low"
                streams[name] = {"samples": n, "rate": round(rate, 1), "nominal": nominal or None, "status": status}
            out[did] = {"type": dev.type_name, "streams": streams, "errors": len(dev.errors)}
        return out

    def _health_loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.emit({"type": "devices", "elapsed": round(time.monotonic() - self.t0, 1), "devices": self.device_health()})
            except Exception:
                pass
