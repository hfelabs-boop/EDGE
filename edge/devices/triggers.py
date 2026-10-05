"""TTL trigger outputs: serial/USB trigger boxes and parallel ports.

These are what you wire into the trigger/event input of an EEG amplifier,
physiology system (MindWare, BIOPAC), fNIRS, MRI scanner log, or eye tracker.
Each marker's ``code`` (1-255) is written as a pulse of ``pulse_ms``.

Supported protocols:
  * ``byte``    - write the code as one byte, then the reset code after the pulse
                  (Brain Products TriggerBox, Neurospec, Arduino/Teensy sketches, BIOPAC STP via USB-TTL)
  * ``cedrus``  - Cedrus StimTracker / c-pod "mh" command
  * ``ascii``   - write the code as text followed by newline (custom microcontrollers)
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from ..events import Marker
from . import register
from .base import Device, DeviceError


class _Pulser:
    """Writes a code, then resets after ``pulse_ms`` without blocking the frame loop."""

    def __init__(self, write, pulse_ms: float, reset_code: int):
        self.write = write
        self.pulse = pulse_ms / 1000.0
        self.reset = reset_code
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def send(self, code: int) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self.write(code)
            if self.pulse > 0:
                self._timer = threading.Timer(self.pulse, self._reset)
                self._timer.daemon = True
                self._timer.start()

    def _reset(self) -> None:
        with self._lock:
            self.write(self.reset)
            self._timer = None


@register
class SerialTrigger(Device):
    type_name = "ttl_serial"
    description = "TTL triggers via a serial/USB trigger box (Brain Products TriggerBox, Cedrus, Arduino, ...)."
    capabilities = {"markers", "ttl"}
    requires = ["serial"]
    options_schema = {
        "port": {"type": "str", "default": "", "help": "COM3, /dev/ttyACM0 ... (empty = auto when only one port)"},
        "baudrate": {"type": "int", "default": 115200},
        "protocol": {"type": "choice", "choices": ["byte", "cedrus", "ascii"], "default": "byte"},
        "pulse_ms": {"type": "float", "default": 10.0, "help": "pulse width; 0 = leave lines set"},
        "reset_code": {"type": "int", "default": 0},
        "code_map": {"type": "dict", "default": {}, "help": "label -> code mapping for markers without a code"},
    }

    def connect(self) -> None:
        try:
            import serial  # pyserial
            from serial.tools import list_ports
        except ImportError as e:
            raise DeviceError("pyserial is required: pip install pyserial") from e
        port = self.options["port"]
        if not port:
            ports = list(list_ports.comports())
            if len(ports) != 1:
                raise DeviceError(f"set 'port' explicitly; found: {[p.device for p in ports]}")
            port = ports[0].device
        self.ser = serial.Serial(port, int(self.options["baudrate"]), timeout=0, write_timeout=0.05)
        from .inputs import low_latency
        low_latency(self.ser)
        self.port = port
        proto = self.options["protocol"]

        def write(code: int) -> None:
            if proto == "cedrus":
                self.ser.write(b"mh" + bytes([code & 0xFF, 0]))
            elif proto == "ascii":
                self.ser.write(f"{code}\n".encode())
            else:
                self.ser.write(bytes([code & 0xFF]))

        self.pulser = _Pulser(write, float(self.options["pulse_ms"]), int(self.options["reset_code"]))
        self.pulser.write(int(self.options["reset_code"]))
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        code = resolve_code(marker, self.options.get("code_map") or {})
        if code is not None:
            self.pulser.send(code)

    def close(self) -> None:
        super().close()
        try:
            self.ser.close()
        except Exception:
            pass

    def info(self) -> dict[str, Any]:
        return {"port": self.port, "protocol": self.options["protocol"]}


@register
class ParallelPort(Device):
    type_name = "parallel_port"
    description = "TTL triggers on a parallel (LPT) port: inpoutx64 on Windows, /dev/parport on Linux."
    capabilities = {"markers", "ttl"}
    options_schema = {
        "address": {"type": "str", "default": "0x378", "help": "port address (Windows) or /dev/parport0 (Linux)"},
        "pulse_ms": {"type": "float", "default": 10.0},
        "reset_code": {"type": "int", "default": 0},
        "code_map": {"type": "dict", "default": {}},
    }

    def connect(self) -> None:
        addr = str(self.options["address"])
        if sys.platform.startswith("win"):
            import ctypes
            try:
                dll = ctypes.windll.inpoutx64  # type: ignore[attr-defined]
            except OSError as e:
                raise DeviceError("inpoutx64.dll not found (install it next to python.exe)") from e
            port = int(addr, 16)

            def write(code: int) -> None:
                dll.Out32(port, code & 0xFF)
        else:
            try:
                import parallel  # pyparallel
            except ImportError as e:
                raise DeviceError("pyparallel is required on Linux: pip install pyparallel") from e
            dev = addr if addr.startswith("/dev") else "/dev/parport0"
            self._p = parallel.Parallel(dev)

            def write(code: int) -> None:
                self._p.setData(code & 0xFF)

        self.pulser = _Pulser(write, float(self.options["pulse_ms"]), int(self.options["reset_code"]))
        self.pulser.write(int(self.options["reset_code"]))
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        code = resolve_code(marker, self.options.get("code_map") or {})
        if code is not None:
            self.pulser.send(code)


@register
class LoopbackTrigger(Device):
    """Records the codes it would have sent. Used in tests and dry runs."""

    type_name = "ttl_loopback"
    description = "Virtual TTL output that logs pulses (for dry runs and testing code maps)."
    capabilities = {"markers", "ttl"}
    options_schema = {"code_map": {"type": "dict", "default": {}}}

    def connect(self) -> None:
        self.sent: list[tuple[float, int]] = []
        self.add_stream("ttl", ["code"], 0.0, "Markers", time_base="master")
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        code = resolve_code(marker, self.options.get("code_map") or {})
        if code is not None:
            t = self.clock()
            self.sent.append((t, code))
            self.emit("ttl", t, [code], sync=False)


def resolve_code(marker: Marker, code_map: dict[str, int]) -> int | None:
    if marker.label in code_map:
        return int(code_map[marker.label])
    if marker.code is not None:
        return int(marker.code)
    return None


def busy_wait(seconds: float) -> None:  # pragma: no cover - used by hardware latency tests
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass
