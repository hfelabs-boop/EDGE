"""Device driver base class.

A driver is a small class that knows how to talk to one kind of hardware. The
runtime handles everything else: connecting at session start, broadcasting
markers, recording streams to disk, aligning clocks, and closing cleanly even
if the experiment crashes.

Minimal driver::

    from edge.devices import Device, register

    @register
    class MyAmp(Device):
        type_name = "my_amp"
        description = "Acme amplifier over TCP"
        capabilities = {"stream", "markers"}
        options_schema = {"host": {"type": "str", "default": "127.0.0.1"}}

        def connect(self):
            self.sock = ...
            self.add_stream("eeg", channels=["C3", "C4"], srate=500, kind="EEG")

        def poll(self):                       # called every frame (or use a thread)
            for t_dev, values in self.read_available():
                self.emit("eeg", t_dev, values)

        def send_marker(self, marker):
            self.sock.send(marker.label.encode())
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from ..clock import now as master_now
from ..events import Marker
from ..sync import ArrivalSync, ClockModel

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime import Session


class DeviceError(RuntimeError):
    pass


@dataclass
class StreamInfo:
    name: str
    channels: list[str]
    srate: float = 0.0          # nominal; 0 = irregular
    kind: str = ""              # EEG, Gaze, ECG, EDA, Markers ...
    units: list[str] | None = None
    time_base: str = "device"   # "device" (needs ClockModel) or "master" (already aligned)
    meta: dict[str, Any] = field(default_factory=dict)


SampleSink = Callable[[str, str, float, float, list[Any]], None]  # device, stream, t_dev, t_arrival, values


class Device:
    type_name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    capabilities: ClassVar[set[str]] = set()   # markers, stream, gaze, calibration, ttl, input
    options_schema: ClassVar[dict[str, dict[str, Any]]] = {}
    # Optional Python packages this driver needs; listed by `edge devices`.
    requires: ClassVar[list[str]] = []

    def __init__(self, id: str, options: dict[str, Any] | None = None,
                 clock: Callable[[], float] = master_now):
        self.id = id
        self.clock = clock
        self.options = self.resolve_options(options or {})
        self.streams: dict[str, StreamInfo] = {}
        self.clock_model = ClockModel()
        self.arrival_sync = ArrivalSync(latency=float(self.options.get("latency", 0.0) or 0.0))
        self.connected = False
        self.recording = False
        self.session: Session | None = None
        self._sinks: list[SampleSink] = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.errors: list[str] = []
        self.n_samples: dict[str, int] = {}
        self.latest: dict[str, tuple[float, list[Any]]] = {}    # stream -> (arrival time, values) of the last sample

    # ----------------------------------------------------------- options
    @classmethod
    def resolve_options(cls, given: dict[str, Any]) -> dict[str, Any]:
        out = {k: v.get("default") for k, v in cls.options_schema.items()}
        out.update(given)
        return out

    @classmethod
    def planned_streams(cls, options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """What this device will record, known before it connects:
        [{name, kind, channels (list, or None = whatever the hardware reports), srate (Hz, None = the
        device's own rate), what (plain words)}]. Devices that only send markers return []."""
        if "stream" not in cls.capabilities:
            return []
        return [{"name": "data", "kind": "", "channels": None, "srate": None,
                 "what": "the samples the device sends, at its own rate"}]

    @classmethod
    def validate_options(cls, spec: Any, exp: Any) -> list:
        """Device-specific checks of an experiment's device entry (Issues)."""
        return []

    def drain(self) -> list:
        """Input events (responses) collected since the last call; only input devices have any."""
        return []

    @classmethod
    def records_note(cls, options: dict[str, Any] | None = None) -> str:
        """What happens to data that is not saved by EDGE itself (e.g. TTL codes in another recorder)."""
        if "ttl" in cls.capabilities:
            return "sends event codes (TTL) to the acquisition system, where they are recorded with its data"
        if "markers" in cls.capabilities and "stream" not in cls.capabilities:
            return "publishes event markers for another recorder (e.g. LabRecorder)"
        return ""

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "type": cls.type_name,
            "description": cls.description,
            "capabilities": sorted(cls.capabilities),
            "planned_streams": cls.planned_streams(cls.resolve_options({})),
            "options": cls.options_schema,
            "requires": cls.requires,
            "available": cls.available()[0],
            "unavailable_reason": cls.available()[1],
        }

    @classmethod
    def available(cls) -> tuple[bool, str]:
        """Whether this driver's dependencies are importable."""
        import importlib.util
        for mod in cls.requires:
            if importlib.util.find_spec(mod) is None:
                return False, f"python package '{mod}' is not installed"
        return True, ""

    # ----------------------------------------------------------- lifecycle (override)
    def connect(self) -> None:
        """Open the connection and declare streams via add_stream()."""
        self.connected = True

    def start(self) -> None:
        """Begin streaming/recording."""
        self.recording = True

    def stop(self) -> None:
        self.recording = False

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self.connected = False

    def poll(self) -> None:
        """Called once per frame from the main thread. Non-threaded drivers read data here."""

    def send_marker(self, marker: Marker) -> None:
        """Deliver an event marker to the device (TTL, network message ...)."""

    def calibrate(self, session: "Session") -> dict[str, Any]:
        raise DeviceError(f"{self.type_name} does not support calibration")

    def live(self) -> dict[str, Any]:
        """The latest value of every channel, for expressions: ``$devices.<id>.<channel>`` (or
        ``$devices.<id>.<stream>.<channel>``), plus ``age`` (seconds since that sample)."""
        from ..components.base import Results
        out = Results()
        newest = None
        for stream, (t, values) in list(self.latest.items()):
            info = self.streams.get(stream)
            names = info.channels if info else [f"ch{i + 1}" for i in range(len(values))]
            per = Results({str(n): v for n, v in zip(names, values)})
            out[stream] = per
            for n, v in per.items():
                out.setdefault(n, v)
            newest = t if newest is None or t > newest else newest
        out["age"] = (self.clock() - newest) if newest is not None else None
        return out

    def latest_gaze(self) -> tuple[float, float] | None:
        """Latest valid gaze position in window coordinates (px, origin centre, y up)."""
        return None

    def info(self) -> dict[str, Any]:
        return {}

    # ----------------------------------------------------------- helpers for drivers
    def add_stream(self, name: str, channels: list[str], srate: float = 0.0, kind: str = "",
                   units: list[str] | None = None, time_base: str = "device", **meta: Any) -> StreamInfo:
        info = StreamInfo(name, list(channels), srate, kind, units, time_base, meta)
        self.streams[name] = info
        self.n_samples[name] = 0
        return info

    def add_sink(self, sink: SampleSink) -> None:
        self._sinks.append(sink)

    def emit(self, stream: str, device_time: float, values: list[Any], arrival: float | None = None,
             sync: bool = True) -> None:
        """Hand one sample to the recorder. Safe to call from any thread."""
        t_arr = self.clock() if arrival is None else arrival
        if sync and self.streams[stream].time_base == "device":
            self.arrival_sync.add(device_time, t_arr)
        self.n_samples[stream] = self.n_samples.get(stream, 0) + 1
        self.latest[stream] = (t_arr, values)
        for sink in self._sinks:
            sink(self.id, stream, device_time, t_arr, values)

    def spawn(self, target: Callable[[], None], name: str = "") -> threading.Thread:
        """Start a daemon reader thread that records (not raises) exceptions."""

        def run() -> None:
            try:
                target()
            except Exception:  # pragma: no cover - surfaced through self.errors
                self.errors.append(traceback.format_exc())

        t = threading.Thread(target=run, name=name or f"{self.id}-reader", daemon=True)
        self._threads.append(t)
        t.start()
        return t

    @property
    def should_stop(self) -> bool:
        return self._stop.is_set()

    def finalize_clock(self) -> ClockModel:
        """Called at the end of the session to fix the device->master mapping."""
        if any(s.time_base == "device" for s in self.streams.values()) and self.clock_model.method == "identity":
            self.clock_model = self.arrival_sync.model()
        return self.clock_model

    def window_size(self) -> tuple[int, int]:
        if self.session is not None and self.session.backend is not None:
            return self.session.backend.size
        return tuple(self.options.get("screen_size") or (1920, 1080))  # type: ignore[return-value]

    def norm_to_window(self, x: float, y: float) -> tuple[float, float]:
        """Convert normalized top-left-origin coords (Tobii, Gazepoint) to window px."""
        w, h = self.window_size()
        return (x - 0.5) * w, (0.5 - y) * h

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r}>"
