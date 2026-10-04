"""Simulated devices.

They let you build, test and dry-run a complete multi-device experiment with no
hardware attached. Each simulated device runs on its *own* clock (with a
configurable offset and drift), so the full synchronization pipeline is
exercised exactly as it would be with real hardware.

Samples are generated lazily in ``poll()`` for the interval since the last call,
so they work identically with the real clock and the headless virtual clock.
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Any

from ..events import Marker
from . import register
from .base import Device


class _SimBase(Device):
    options_schema = {
        "srate": {"type": "float", "default": 250.0, "help": "samples per second"},
        "clock_offset": {"type": "float", "default": 1000.0, "help": "device clock offset vs master (s)"},
        "clock_drift_ppm": {"type": "float", "default": 20.0, "help": "device clock drift (parts per million)"},
        "transport_jitter": {"type": "float", "default": 0.002, "help": "max simulated transport delay (s)"},
        "seed": {"type": "int", "default": 0},
    }

    def connect(self) -> None:
        self.rng = random.Random(self.options.get("seed") or 0)
        self._last: float | None = None
        self._n = 0
        self.markers_received: list[tuple[float, str, int | None]] = []
        self._pending: deque[tuple[float, int]] = deque()
        self.connected = True

    def device_time(self, master: float) -> float:
        drift = 1.0 + float(self.options["clock_drift_ppm"]) * 1e-6
        return (master + float(self.options["clock_offset"])) * drift

    def start(self) -> None:
        # random sampling phase: real amplifiers are never phase-locked to the display
        self._last = self.clock() - self.rng.random() / float(self.options["srate"])
        self.recording = True

    def poll(self) -> None:
        if not self.recording or self._last is None:
            return
        now = self.clock()
        srate = float(self.options["srate"])
        n_due = int((now - self._last) * srate)
        jitter = float(self.options["transport_jitter"])
        for i in range(n_due):
            t_master = self._last + (i + 1) / srate
            values = self.sample(t_master)
            # arrival = true time + random non-negative transport delay
            arrival = t_master + self.rng.random() * jitter
            for stream, vals in values.items():
                self.emit(stream, self.device_time(t_master), vals, arrival=arrival)
            self._n += 1
        self._last += n_due / srate

    def sample(self, t: float) -> dict[str, list[Any]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def send_marker(self, marker: Marker) -> None:
        # Behaves like a perfect hardware trigger line: the code appears on the
        # first sample taken at or after the marker's (flip) time.
        self.markers_received.append((marker.time, marker.label, marker.code))
        self._pending.append((marker.time, marker.code or 0))

    def take_code(self, t: float) -> int:
        if self._pending and t >= self._pending[0][0]:
            return self._pending.popleft()[1]
        return 0


@register
class SimEyeTracker(_SimBase):
    type_name = "sim_eyetracker"
    description = "Simulated eye tracker (fixations + saccades + blinks). Follows the mouse if follow_mouse=true."
    capabilities = {"stream", "gaze", "markers", "calibration"}
    options_schema = {**_SimBase.options_schema,
                      "srate": {"type": "float", "default": 120.0},
                      "follow_mouse": {"type": "bool", "default": False},
                      "noise_px": {"type": "float", "default": 8.0}}

    def connect(self) -> None:
        super().connect()
        self.add_stream("gaze", ["x", "y", "valid", "pupil_l", "pupil_r", "user"], self.options["srate"], "Gaze",
                        units=["px", "px", "bool", "mm", "mm", ""])
        self._fix = (0.0, 0.0)
        self._fix_until = 0.0
        self._latest: tuple[float, float] | None = None

    def sample(self, t: float) -> dict[str, list[Any]]:
        if self.options.get("follow_mouse") and self.session is not None and self.session.backend is not None:
            target = self.session.backend.mouse_pos()
        else:
            if t >= self._fix_until:
                w, h = self.window_size()
                self._fix = (self.rng.uniform(-w / 3, w / 3), self.rng.uniform(-h / 3, h / 3))
                self._fix_until = t + self.rng.uniform(0.15, 0.5)
            target = self._fix
        blink = (t % 4.0) < 0.12
        n = float(self.options["noise_px"])
        x = target[0] + self.rng.gauss(0, n)
        y = target[1] + self.rng.gauss(0, n)
        valid = not blink
        if valid:
            self._latest = (x, y)
        pupil = 3.5 + 0.3 * math.sin(t * 0.7)
        user = self.take_code(t)
        return {"gaze": [round(x, 2), round(y, 2), int(valid), round(pupil, 3) if valid else None,
                         round(pupil + 0.05, 3) if valid else None, user]}

    def latest_gaze(self) -> tuple[float, float] | None:
        return self._latest

    def calibrate(self, session) -> dict[str, Any]:
        return {"result": "ok", "simulated": True, "mean_error_deg": 0.4}


@register
class SimPhysio(_SimBase):
    type_name = "sim_physio"
    description = "Simulated physiology (ECG, EDA, respiration) e.g. for prototyping MindWare/BIOPAC setups."
    capabilities = {"stream", "markers"}
    options_schema = {**_SimBase.options_schema, "srate": {"type": "float", "default": 500.0},
                      "heart_rate": {"type": "float", "default": 70.0}}

    def connect(self) -> None:
        super().connect()
        self.add_stream("physio", ["ecg", "eda", "resp", "event"], self.options["srate"], "Physio",
                        units=["mV", "uS", "a.u.", "code"])
        self._eda = 5.0

    def sample(self, t: float) -> dict[str, list[Any]]:
        hr = float(self.options["heart_rate"]) / 60.0
        phase = (t * hr) % 1.0
        ecg = 1.2 * math.exp(-((phase - 0.3) ** 2) / 0.0004) - 0.15 * math.exp(-((phase - 0.27) ** 2) / 0.0002) \
            + 0.25 * math.exp(-((phase - 0.6) ** 2) / 0.004) + self.rng.gauss(0, 0.02)
        self._eda += (5.0 - self._eda) * 0.0005 + self.rng.gauss(0, 0.002)
        code = self.take_code(t)
        if code:
            self._eda += 0.05  # a small phasic response to every event
        resp = math.sin(2 * math.pi * 0.25 * t)
        return {"physio": [round(ecg, 4), round(self._eda, 4), round(resp, 4), code]}


@register
class SimEEG(_SimBase):
    type_name = "sim_eeg"
    description = "Simulated EEG amplifier (alpha rhythm + noise, with a trigger channel)."
    capabilities = {"stream", "markers"}
    options_schema = {**_SimBase.options_schema,
                      "channels": {"type": "list", "default": ["Fz", "Cz", "Pz", "Oz", "C3", "C4", "P3", "P4"]}}

    def connect(self) -> None:
        super().connect()
        chans = list(self.options["channels"])
        self.add_stream("eeg", chans + ["TRIG"], self.options["srate"], "EEG", units=["uV"] * len(chans) + ["code"])

    def sample(self, t: float) -> dict[str, list[Any]]:
        chans = self.options["channels"]
        alpha = 10 * math.sin(2 * math.pi * 10 * t)
        vals: list[Any] = [round(alpha * (1.5 if c.startswith(("O", "P")) else 0.5) + self.rng.gauss(0, 5), 2) for c in chans]
        code = self.take_code(t)
        return {"eeg": vals + [code]}


@register
class MouseGaze(Device):
    type_name = "mouse_gaze"
    description = "Use the mouse as a stand-in eye tracker to develop gaze-contingent tasks without hardware."
    capabilities = {"gaze", "stream"}
    options_schema = {"srate": {"type": "float", "default": 60.0}}

    def connect(self) -> None:
        self.add_stream("gaze", ["x", "y"], self.options["srate"], "Gaze", time_base="master")
        self.connected = True

    def poll(self) -> None:
        if self.recording and self.session is not None and self.session.backend is not None:
            x, y = self.session.backend.mouse_pos()
            self.emit("gaze", self.clock(), [x, y])

    def latest_gaze(self) -> tuple[float, float] | None:
        if self.session is not None and self.session.backend is not None:
            return self.session.backend.mouse_pos()
        return None

    def calibrate(self, session) -> dict[str, Any]:
        return {"result": "ok", "simulated": True}
