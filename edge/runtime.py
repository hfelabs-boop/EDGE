"""A running session: backend + devices + data + markers, with guaranteed cleanup."""

from __future__ import annotations

import hashlib
import json
import platform
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__
from .backends.base import Backend
from .clock import CLOCK_SOURCE
from .data import SessionData
from .devices import Device, DeviceError, create_device
from .events import EventBus, Marker
from .model import Experiment


class ExperimentAborted(Exception):
    pass


class MarkerCodebook:
    """Stable label -> TTL code mapping (1..254), saved with the session."""

    def __init__(self, preset: dict[str, int] | None = None):
        self.codes: dict[str, int] = dict(preset or {})
        self._next = 1

    def code_for(self, label: str) -> int:
        if label not in self.codes:
            used = set(self.codes.values())
            while self._next in used:
                self._next += 1
            if self._next > 254:
                return 255  # overflow code; the label is still logged everywhere else
            self.codes[label] = self._next
        return self.codes[label]


class Session:
    def __init__(self, experiment: Experiment, backend: Backend, participant: dict[str, Any] | None = None,
                 data_dir: str | Path | None = None, virtual_participant: Any = None,
                 device_overrides: dict[str, dict[str, Any]] | None = None,
                 simulate_devices: bool = False, log=print):
        self.exp = experiment
        self.backend = backend
        self.settings = experiment.settings
        self.participant = {**self.settings.get("participant", {}), **(participant or {})}
        self.vars: dict[str, Any] = dict(experiment.variables)
        self.code_globals: dict[str, Any] = {}
        self.virtual_participant = virtual_participant
        self.simulate_devices = simulate_devices
        self.device_overrides = device_overrides or {}
        self.log = log
        self.bus = EventBus()
        self.devices: dict[str, Device] = {}
        self.marker_targets: dict[str, bool] = {}
        self.codebook = MarkerCodebook(self.settings.get("markers", {}).get("codes"))
        self.calibrations: list[dict[str, Any]] = []
        self.loop_summaries: dict[str, Any] = {}
        self.frame_index = 0
        self.last_flip: float | None = None
        self.frame_intervals: list[float] = []
        self.dropped_frames = 0
        self.errors: list[str] = []
        self.aborted = False
        self.data_root = Path(data_dir) if data_dir else experiment.base_dir / self.settings["data"]["dir"]
        self.data: SessionData | None = None
        seed = self.settings.get("seed")
        self.seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
        self.rng = random.Random(self.seed)
        self.started_at: str | None = None
        from .monitor import from_env
        self.monitor = from_env(self)

    # ------------------------------------------------------------------ setup
    @property
    def clock(self):
        return self.backend.clock

    def open(self) -> None:
        self.started_at = datetime.now().isoformat(timespec="seconds")
        fields = {**self.participant, "experiment": self.exp.name}
        root = SessionData.make_dir(self.data_root, self.settings["data"]["filename"], fields)
        self.data = SessionData(root)
        if self.exp.source:
            from .storage import dumps
            self.data.write_text("experiment.yaml", dumps(self.exp.source))
        if hasattr(self.backend, "base_dir"):
            self.backend.base_dir = self.exp.base_dir
        self.backend.open(self.settings["window"])
        if self.backend.refresh_rate > 300:
            self.log(f"[edge] WARNING: measured refresh rate {self.backend.refresh_rate:.0f} Hz: vsync is not "
                     "working, stimulus durations will not be frame-accurate (check GPU driver settings)")
            self.errors.append("vsync appears disabled")
        self._connect_devices()
        for spec in self.exp.devices:
            dev = self.devices.get(spec.id)
            if dev is not None and spec.calibrate and "calibration" in dev.capabilities:
                self.log(f"[edge] calibrating {spec.id} ...")
                res = dev.calibrate(self)
                self.calibrations.append({"device": spec.id, "time": self.clock(), **res})
        for dev in self.devices.values():
            dev.start()
        self.marker("session_start", source="edge")
        if self.monitor:
            self.monitor.start()

    def _connect_devices(self) -> None:
        sim_map = {"tobii": "sim_eyetracker", "gazepoint": "sim_eyetracker", "gtec": "sim_eeg",
                   "mindware": "sim_physio", "lsl_inlet": "sim_eeg", "ttl_serial": "ttl_loopback",
                   "parallel_port": "ttl_loopback", "lsl_markers": "ttl_loopback"}
        for spec in self.exp.devices:
            dtype = spec.type
            options = {**spec.options, **self.device_overrides.get(spec.id, {})}
            if self.simulate_devices and dtype in sim_map:
                self.log(f"[edge] {spec.id}: simulating '{dtype}' with '{sim_map[dtype]}'")
                dtype, options = sim_map[dtype], {}
            try:
                dev = create_device(dtype, spec.id, options, clock=self.clock)
                dev.session = self
                dev.connect()
            except Exception as e:
                msg = f"device '{spec.id}' ({dtype}) failed to connect: {e}"
                if spec.required:
                    raise DeviceError(msg) from e
                self.log(f"[edge] WARNING {msg} (optional device, continuing)")
                self.errors.append(msg)
                continue
            if spec.record:
                for sname, sinfo in dev.streams.items():
                    self.data.open_stream(spec.id, sname, sinfo.channels)
                dev.add_sink(self._on_sample)
            self.devices[spec.id] = dev
            self.marker_targets[spec.id] = spec.markers and "markers" in dev.capabilities
            self.log(f"[edge] connected {spec.id} ({dtype}) {dev.info() or ''}")

    def _on_sample(self, device: str, stream: str, t_dev: float, t_arr: float, values: list[Any]) -> None:
        w = self.data.streams.get((device, stream)) if self.data else None
        if w is not None:
            w.write(t_dev, t_arr, values)

    # ------------------------------------------------------------------ markers
    def marker(self, label: str, code: int | None = None, source: str = "", time: float | None = None,
               devices: list[str] | None = None, on_flip: bool = False, fields: dict[str, Any] | None = None) -> Marker:
        if code is None:
            code = self.codebook.code_for(label)
        else:
            self.codebook.codes.setdefault(label, int(code))
        m = Marker(label=label, time=self.clock() if time is None else time, code=code, source=source,
                   fields=fields or {}, on_flip=on_flip)
        for did, dev in self.devices.items():
            if not self.marker_targets.get(did) or (devices and did not in devices):
                continue
            try:
                dev.send_marker(m)
                m.delivered[did] = self.clock()
            except Exception as e:
                self.errors.append(f"marker '{label}' to {did} failed: {e}")
        if self.data:
            self.data.add_event(m.to_dict())
        self.bus.publish("marker", m)
        return m

    def notify_response_window(self, component: Any, allowed: Any, correct: Any) -> None:
        if self.virtual_participant is not None and hasattr(self.backend, "press"):
            self.virtual_participant.respond(component, allowed, correct, self.backend)

    # ------------------------------------------------------------------ frames
    def flip(self, routine: str = "") -> float:
        t = self.backend.flip()
        interval = None if self.last_flip is None else t - self.last_flip
        dropped = False
        if interval is not None:
            self.frame_intervals.append(interval)
            tol = float(self.settings["timing"]["frame_drop_tolerance"])
            dropped = interval > tol * self.backend.frame_interval
            self.dropped_frames += int(dropped)
        if self.data and self.settings["data"].get("save_frame_log", True):
            self.data.add_frame(self.frame_index, t, interval, dropped, routine)
        self.last_flip = t
        self.frame_index += 1
        return t

    def poll_devices(self) -> None:
        for dev in self.devices.values():
            dev.poll()

    def check_abort(self) -> None:
        if self.backend.check_escape():
            raise ExperimentAborted("escape pressed")
        if self.monitor and self.frame_index % 10 == 0 and self.monitor.stop_requested():
            self.log("[edge] stopped by the experimenter")
            raise ExperimentAborted("stopped by the experimenter")

    # ------------------------------------------------------------------ teardown
    def close(self) -> dict[str, Any]:
        try:
            if self.devices:
                self.marker("session_end", source="edge")
        except Exception:
            pass
        # keep reading devices briefly so the final marker and in-flight samples are captured
        if self.backend.name != "headless" or getattr(self.backend, "realtime", False):
            end = self.clock() + float(self.settings["timing"].get("end_grace", 0.25))
            while self.clock() < end:
                self.poll_devices()
                time.sleep(0.005)
        self.poll_devices()
        clock_models = {}
        for did, dev in self.devices.items():
            try:
                dev.stop()
            except Exception as e:
                self.errors.append(f"stopping {did}: {e}")
            try:
                clock_models[did] = dev.finalize_clock()
            except Exception as e:
                self.errors.append(f"clock model for {did}: {e}")
        if self.data:
            for (did, sname), w in self.data.streams.items():
                dev = self.devices.get(did)
                if dev is None:
                    continue
                try:
                    w.finalize(clock_models.get(did, dev.clock_model), dev.streams[sname].time_base)
                except Exception as e:
                    self.errors.append(f"finalizing stream {did}.{sname}: {e}")
        for did, dev in self.devices.items():
            try:
                dev.close()
            except Exception as e:
                self.errors.append(f"closing {did}: {e}")
            self.errors += [f"{did}: {err}" for err in dev.errors]
        summary = self.summary(clock_models)
        if self.monitor:
            try:
                self.monitor.end(summary)
            except Exception:
                pass
        if self.data:
            self.data.close()
            self.data.write_json("session.json", summary)
            try:
                from .export import auto_export
                auto_export(self.data.root, self.settings)
            except Exception as e:  # never lose a session because an export failed
                self.errors.append(f"automatic export failed: {type(e).__name__}: {e}")
                summary["errors"] = self.errors
                self.data.write_json("session.json", summary)
        try:
            self.backend.close()
        except Exception:
            pass
        return summary

    def timing_summary(self) -> dict[str, Any]:
        iv = self.frame_intervals
        if not iv:
            return {"frames": self.frame_index}
        ms = [x * 1e3 for x in iv]
        return {
            "frames": self.frame_index,
            "refresh_rate_hz": self.backend.refresh_rate,
            "expected_interval_ms": 1e3 / self.backend.refresh_rate,
            "mean_interval_ms": statistics.fmean(ms),
            "sd_interval_ms": statistics.pstdev(ms),
            "max_interval_ms": max(ms),
            "dropped_frames": self.dropped_frames,
            "dropped_pct": 100.0 * self.dropped_frames / len(iv),
        }

    def summary(self, clock_models: dict[str, Any]) -> dict[str, Any]:
        src = json.dumps(self.exp.source, sort_keys=True, default=str).encode()
        return {
            "edge_version": __version__,
            "experiment": self.exp.name,
            "experiment_sha256": hashlib.sha256(src).hexdigest(),
            "participant": self.participant,
            "started": self.started_at,
            "ended": datetime.now().isoformat(timespec="seconds"),
            "aborted": self.aborted,
            "seed": self.seed,
            "backend": self.backend.name,
            "window_size": list(self.backend.size),
            "master_clock": "virtual" if getattr(self.backend, "clock", None) is getattr(self.backend, "vclock", 0)
            else CLOCK_SOURCE,
            "platform": {"python": sys.version.split()[0], "os": platform.platform()},
            "dry_run": self.virtual_participant is not None,
            "timing": self.timing_summary(),
            "devices": {did: {"type": dev.type_name, "info": _safe(dev.info), "streams": {
                k: {"channels": s.channels, "srate": s.srate, "kind": s.kind, "samples": dev.n_samples.get(k, 0)}
                for k, s in dev.streams.items()},
                "clock_model": clock_models[did].to_dict() if did in clock_models else None}
                for did, dev in self.devices.items()},
            "marker_codebook": self.codebook.codes,
            "calibrations": self.calibrations,
            "loops": self.loop_summaries,
            "variables": {k: v for k, v in self.vars.items() if isinstance(v, (int, float, str, bool, type(None)))},
            "errors": self.errors,
        }


def _safe(fn) -> Any:
    try:
        return fn()
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}

