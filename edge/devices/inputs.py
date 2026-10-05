"""External inputs: response boxes, TTL lines, light sensors, voice keys.

The open-hardware counterpart of a multifunction response box (PST Chronos, Cedrus, Black Box
ToolKit): every input becomes a time-stamped event on the master clock that the ``device_response``
component can use as a response (``$box.input``, ``$box.rt``), and that is saved to
``streams/<device>.inputs.csv``.

Drivers
  * ``serial_inputs``   USB/serial boxes: Cedrus XID (RB-x40, Lumina, StimTracker light sensors),
                        fMRI button boxes and scanner triggers (Current Designs fORP, NNL, Cambridge
                        Research) that send characters, Arduino/Teensy/BBTK boxes that send a byte
                        with the state of 8 lines
  * ``parallel_inputs`` the 5 status pins of a parallel port (buttons, scanner trigger, light sensor)
  * ``labjack``         LabJack U3/U6: 16 digital lines in or out, analog inputs with a threshold
                        (a photodiode or a microphone envelope), TTL markers out on EIO0-7
  * ``voice_key``       a microphone: the onset (and offset) of speech, with a recorded loudness envelope
  * ``sim_inputs``      stands in for all of the above in dry runs and tests

Input names: each line/button/key is given a name with the ``inputs`` option, e.g.
``{1: left, 2: right, 5: trigger, photo: light}``. Unnamed inputs keep their number as the name.
An input called ``light`` (or any name listed in ``light_inputs``) is treated as a light sensor: the
session report compares it with the screen flips to measure the real display latency.
"""

from __future__ import annotations

import collections
import math
import sys
import threading
import time
from typing import Any

from ..backends.base import InputEvent
from ..events import Marker
from . import register
from .base import Device, DeviceError

INPUT_CHANNELS = ["input", "down", "value"]
_COMMON = {
    "inputs": {"type": "dict", "default": {},
               "help": "names for lines/buttons/keys, e.g. {1: left, 2: right, 5: trigger}; unnamed ones keep their number"},
    "light_inputs": {"type": "list", "default": ["light"],
                     "help": "inputs that are light sensors on the screen: the report measures display latency with them"},
    "record_releases": {"type": "bool", "default": True, "help": "also record when a button is released / a line goes low"},
}


class InputDevice(Device):
    """Base for devices that produce response events."""

    capabilities = {"input", "stream"}
    options_schema = dict(_COMMON)

    def _init_inputs(self) -> None:
        self._queue: collections.deque[InputEvent] = collections.deque()
        self._names = {str(k): str(v) for k, v in (self.options.get("inputs") or {}).items()}
        self.add_stream("inputs", INPUT_CHANNELS, 0.0, "Events", time_base="master")

    def name_of(self, raw: Any) -> str:
        return self._names.get(str(raw), str(raw))

    def push(self, raw: Any, t: float | None = None, down: bool = True, value: Any = None, **meta: Any) -> None:
        """Record one input (thread-safe). ``t`` is master-clock time; default = now."""
        t = self.clock() if t is None else t
        name = self.name_of(raw)
        if down or self.options.get("record_releases", True):
            self.emit("inputs", t, [name, int(bool(down)), "" if value is None else value], sync=False)
        self._queue.append(InputEvent("device", name, t, down, device=self.id, meta={"raw": raw, **meta}))

    def drain(self) -> list[InputEvent]:
        out = []
        while self._queue:
            out.append(self._queue.popleft())
        return out

    @classmethod
    def planned_streams(cls, options=None):
        o = cls.resolve_options(options or {})
        names = ", ".join(str(v) for v in (o.get("inputs") or {}).values()) or "every line/button"
        return [{"name": "inputs", "kind": "Events", "channels": INPUT_CHANNELS, "srate": None,
                 "what": f"time of every press and release ({names})"}]

    @classmethod
    def records_note(cls, options=None):
        return "its inputs can be responses (Button box / external input component)"


# ============================================================================ protocol decoding (pure, testable)
def decode_mask(prev: int, cur: int, bits: int = 8) -> list[tuple[int, bool]]:
    """Lines (1-based) that changed between two bit masks: [(line, down), ...]."""
    out = []
    changed = prev ^ cur
    for b in range(bits):
        if changed >> b & 1:
            out.append((b + 1, bool(cur >> b & 1)))
    return out


def parse_ascii(text: str) -> tuple[str, bool] | None:
    """'1', 'B3', '5\\r', 'left down', 'left up', 'right 0' -> (name, down)."""
    parts = text.strip().split()
    if not parts:
        return None
    name = parts[0]
    if len(name) > 1 and name[0] in "bB" and name[1:].isdigit():
        name = name[1:]
    down = not (len(parts) > 1 and parts[1].lower() in ("up", "0", "release", "released", "off"))
    return name, down


def parse_cedrus(packet: bytes) -> tuple[int, int, bool, int] | None:
    """A Cedrus XID response packet ('k', info, 4-byte ms timer) -> (port, key 1-8, pressed, device ms)."""
    if len(packet) != 6 or packet[0:1] != b"k":
        return None
    info = packet[1]
    return info & 0x0F, ((info >> 5) & 0x07) + 1, bool(info >> 4 & 1), int.from_bytes(packet[2:6], "little")


class Threshold:
    """Turns a sampled signal (light sensor, microphone envelope, analog line) into on/off events with
    hysteresis: on above ``high`` for ``min_on`` seconds, off below ``low`` for ``min_off``."""

    def __init__(self, high: float, low: float | None = None, min_on: float = 0.0, min_off: float = 0.02):
        self.high, self.low = high, high * 0.7 if low is None else low
        self.min_on, self.min_off = min_on, min_off
        self.on = False
        self._cand: float | None = None

    def feed(self, t: float, v: float) -> list[tuple[float, bool]]:
        if not self.on:
            if v >= self.high:
                self._cand = t if self._cand is None else self._cand
                if t - self._cand >= self.min_on:
                    self.on, t0, self._cand = True, self._cand, None
                    return [(t0, True)]
            else:
                self._cand = None
        else:
            if v < self.low:
                self._cand = t if self._cand is None else self._cand
                if t - self._cand >= self.min_off:
                    self.on, t0, self._cand = False, self._cand, None
                    return [(t0, False)]
            else:
                self._cand = None
        return []


# ============================================================================ drivers
@register
class SerialInputs(InputDevice):
    type_name = "serial_inputs"
    description = ("Response box, fMRI button box or scanner trigger on a USB/serial port: Cedrus XID (RB-x40, "
                   "Lumina, StimTracker light sensor), Current Designs fORP / NNL / CRS boxes that send characters, "
                   "Arduino, Teensy or Black Box ToolKit boxes that send the state of 8 lines.")
    capabilities = {"input", "stream"}
    requires = ["serial"]
    options_schema = {
        "port": {"type": "str", "default": "", "help": "COM3, /dev/ttyACM0 … (empty = the only serial port)"},
        "baudrate": {"type": "int", "default": 115200, "help": "Cedrus XID: 115200; fORP: 57600 or 19200"},
        "protocol": {"type": "choice", "choices": ["ascii", "byte", "cedrus"], "default": "ascii",
                     "help": "ascii: characters/lines ('1', '5', 'B2 down'); byte: one byte = state of 8 lines; cedrus: XID packets"},
        **_COMMON,
    }

    def connect(self) -> None:  # pragma: no cover - needs hardware
        try:
            import serial
            from serial.tools import list_ports
        except ImportError as e:
            raise DeviceError("pyserial is required: pip install pyserial") from e
        port = self.options["port"]
        if not port:
            ports = [p.device for p in list_ports.comports()]
            if len(ports) != 1:
                raise DeviceError(f"set 'port'; serial ports found: {ports or 'none'}")
            port = ports[0]
        self.port = port
        self._open_port()
        if self.options["protocol"] == "cedrus":
            self.ser.write(b"c10")          # XID mode
            self.ser.write(b"e5")           # reset the response timer
        self._init_inputs()
        self.connected = True

    def start(self) -> None:  # pragma: no cover - needs hardware
        self.recording = True
        self._stop.clear()
        th = threading.Thread(target=self._read, daemon=True)
        th.start()
        self._threads.append(th)

    def _open_port(self) -> None:  # pragma: no cover - needs hardware
        import serial
        self.ser = serial.Serial(self.port, int(self.options["baudrate"]), timeout=0.001)
        low_latency(self.ser)

    def _read(self) -> None:  # pragma: no cover - needs hardware
        proto, buf, mask = self.options["protocol"], b"", 0
        while not self._stop.is_set():
            try:
                data = self.ser.read(64)
            except Exception as e:      # unplugged, or put to sleep by USB selective suspend: reconnect
                self.errors.append(f"{self.port}: connection lost ({e}); reconnecting")
                if not reconnect(self, self._open_port, self._stop):
                    return
                continue
            if not data:
                continue
            t = self.clock()
            if proto == "byte":
                for b in data:
                    for line, down in decode_mask(mask, b):
                        self.push(line, t, down, value=b)
                    mask = b
            elif proto == "cedrus":
                buf += data
                while len(buf) >= 6:
                    i = buf.find(b"k")
                    if i < 0:
                        buf = b""
                        break
                    buf = buf[i:]
                    if len(buf) < 6:
                        break
                    res = parse_cedrus(buf[:6])
                    buf = buf[6:]
                    if res:
                        port, key, pressed, ms = res
                        self.push(key if port == 0 else f"p{port}.{key}", t, pressed, value=ms, port=port)
            else:
                buf += data
                parts = buf.replace(b"\r", b"\n").split(b"\n")
                if len(parts) == 1 and len(buf) <= 2 and buf.strip():
                    parts = [buf, b""]           # single characters without newline (fORP, scanner '5')
                buf = parts[-1]
                for p in parts[:-1]:
                    res = parse_ascii(p.decode(errors="replace"))
                    if res:
                        self.push(res[0], t, res[1])

    def close(self) -> None:  # pragma: no cover - needs hardware
        super().close()
        try:
            self.ser.close()
        except Exception:
            pass

    def info(self) -> dict[str, Any]:
        return {"port": getattr(self, "port", None), "protocol": self.options["protocol"]}


@register
class ParallelInputs(InputDevice):
    type_name = "parallel_inputs"
    description = "Buttons, a scanner trigger or a light sensor on the 5 status pins of a parallel port (10, 11, 12, 13, 15)."
    capabilities = {"input", "stream"}
    options_schema = {
        "address": {"type": "str", "default": "0x379", "help": "status register: base + 1 (Windows, e.g. 0x379), or /dev/parport0 (Linux)"},
        "poll_hz": {"type": "float", "default": 2000.0, "help": "how often the pins are read"},
        **_COMMON,
    }
    PINS = {10: 0x40, 11: 0x80, 12: 0x20, 13: 0x10, 15: 0x08}

    def connect(self) -> None:  # pragma: no cover - needs hardware
        addr = str(self.options["address"])
        if sys.platform.startswith("win"):
            import ctypes
            try:
                dll = ctypes.windll.inpoutx64  # type: ignore[attr-defined]
            except OSError as e:
                raise DeviceError("inpoutx64.dll not found (install it next to python.exe)") from e
            port = int(addr, 16)
            self._read_status = lambda: dll.Inp32(port)
        else:
            try:
                import parallel
            except ImportError as e:
                raise DeviceError("pyparallel is required on Linux: pip install pyparallel") from e
            p = parallel.Parallel(addr if addr.startswith("/dev") else "/dev/parport0")
            self._read_status = lambda: (p.getInError() << 3 | p.getInSelected() << 4 | p.getInPaperOut() << 5
                                         | p.getInAcknowledge() << 6 | (not p.getInBusy()) << 7)
        self._init_inputs()
        self.connected = True

    def start(self) -> None:  # pragma: no cover - needs hardware
        self.recording = True
        th = threading.Thread(target=self._poll, daemon=True)
        th.start()
        self._threads.append(th)

    def _poll(self) -> None:  # pragma: no cover - needs hardware
        period = 1.0 / float(self.options["poll_hz"])
        prev = {pin: False for pin in self.PINS}
        while not self._stop.is_set():
            s = self._read_status() ^ 0x80        # pin 11 (busy) is inverted in hardware
            t = self.clock()
            for pin, bit in self.PINS.items():
                on = bool(s & bit)
                if on != prev[pin]:
                    prev[pin] = on
                    self.push(pin, t, on)
            time.sleep(period)


@register
class LabJack(InputDevice):
    type_name = "labjack"
    description = ("LabJack U3/U6 as a response box and trigger interface: digital lines in (buttons, scanner trigger), "
                   "analog inputs with a threshold (photodiode, microphone), and TTL markers out on EIO0-7.")
    capabilities = {"input", "stream", "markers", "ttl"}
    requires = ["u3"]
    options_schema = {
        "model": {"type": "choice", "choices": ["U3", "U6"], "default": "U3"},
        "digital_inputs": {"type": "list", "default": ["FIO4", "FIO5", "FIO6", "FIO7"], "help": "lines read as inputs"},
        "analog_inputs": {"type": "dict", "default": {}, "help": "{AIN0: 1.5} analog line -> threshold in volts (e.g. a photodiode)"},
        "markers_out": {"type": "bool", "default": True, "help": "send marker codes as 8-bit TTL on EIO0-7"},
        "pulse_ms": {"type": "float", "default": 10.0},
        "poll_hz": {"type": "float", "default": 1000.0},
        "code_map": {"type": "dict", "default": {}},
        **_COMMON,
    }

    def connect(self) -> None:  # pragma: no cover - needs hardware
        try:
            if self.options["model"] == "U6":
                import u6 as lj
                self.lj = lj.U6()
            else:
                import u3 as lj
                self.lj = lj.U3()
                self.lj.configIO(FIOAnalog=sum(1 << int(a[3:]) for a in self.options["analog_inputs"] if a.startswith("AIN")))
        except ImportError as e:
            raise DeviceError("LabJackPython is required: pip install LabJackPython (and the LabJack driver)") from e
        except Exception as e:
            raise DeviceError(f"no LabJack found: {e}") from e
        self._mod = lj
        from .triggers import _Pulser
        self.pulser = _Pulser(lambda code: self.lj.getFeedback(lj.PortStateWrite(State=[0, code & 0xFF, 0], WriteMask=[0, 0xFF, 0])),
                              float(self.options["pulse_ms"]), 0)
        self._init_inputs()
        self.connected = True

    def start(self) -> None:  # pragma: no cover - needs hardware
        self.recording = True
        th = threading.Thread(target=self._poll, daemon=True)
        th.start()
        self._threads.append(th)

    def _poll(self) -> None:  # pragma: no cover - needs hardware
        lines = {name: int(name[3:]) + (8 if name.startswith("EIO") else 16 if name.startswith("CIO") else 0)
                 for name in self.options["digital_inputs"]}
        prev = {n: False for n in lines}
        thr = {a: Threshold(float(v)) for a, v in (self.options["analog_inputs"] or {}).items()}
        period = 1.0 / float(self.options["poll_hz"])
        while not self._stop.is_set():
            t = self.clock()
            for n, ionum in lines.items():
                on = not bool(self.lj.getDIState(ionum))      # buttons pull the line low
                if on != prev[n]:
                    prev[n] = on
                    self.push(n, t, on)
            for a, th in thr.items():
                v = self.lj.getAIN(int(a[3:]))
                for t0, on in th.feed(t, v):
                    self.push(a, t0, on, value=round(v, 4))
            time.sleep(period)

    def send_marker(self, marker: Marker) -> None:  # pragma: no cover - needs hardware
        from .triggers import resolve_code
        if self.options["markers_out"]:
            code = resolve_code(marker, self.options.get("code_map") or {})
            if code is not None:
                self.pulser.send(code)

    @classmethod
    def records_note(cls, options=None):
        o = cls.resolve_options(options or {})
        return "its inputs can be responses; " + ("sends event codes (TTL) on EIO0-7" if o.get("markers_out") else "")


@register
class VoiceKey(InputDevice):
    type_name = "voice_key"
    description = "Voice key: the moment speech starts (and stops) from a microphone, for naming and reading tasks."
    capabilities = {"input", "stream"}
    requires = ["sounddevice", "numpy"]
    options_schema = {
        "device": {"type": "str", "default": "", "help": "microphone name or number (empty = the default input)"},
        "samplerate": {"type": "int", "default": 44100},
        "block": {"type": "int", "default": 64, "help": "samples per block (64 at 44.1 kHz = 1.5 ms resolution)"},
        "threshold_db": {"type": "float", "default": -30.0, "help": "loudness (dB below full scale) that counts as speech"},
        "min_ms": {"type": "float", "default": 15.0, "help": "it must stay loud this long to count (ignores clicks)"},
        "release_ms": {"type": "float", "default": 150.0, "help": "quiet this long = the utterance ended"},
        "input_name": {"type": "str", "default": "voice", "help": "name of the input events"},
        **{k: v for k, v in _COMMON.items() if k == "record_releases"},
    }

    def connect(self) -> None:  # pragma: no cover - needs hardware
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            raise DeviceError("the voice key needs sounddevice and numpy: pip install sounddevice numpy") from e
        o = self.options
        sr, blk = int(o["samplerate"]), int(o["block"])
        self._np = np
        self.detector = VoiceDetector(sr, float(o["threshold_db"]), float(o["min_ms"]) / 1e3, float(o["release_ms"]) / 1e3)
        self._init_inputs()
        self.add_stream("envelope", ["db"], sr / blk, "Audio", time_base="master")

        def cb(indata, frames, tinfo, status):
            now = self.clock()
            t0 = now - max(0.0, tinfo.currentTime - tinfo.inputBufferAdcTime)    # when the block was sampled
            x = indata[:, 0]
            for t, down in self.detector.process(x, t0):
                self.push(o["input_name"], t, down)
            rms = float(np.sqrt(np.mean(x.astype("float64") ** 2)) + 1e-12)
            self.emit("envelope", t0, [round(20 * math.log10(rms), 1)], sync=False)

        dev = o["device"]
        self.stream = sd.InputStream(samplerate=sr, blocksize=blk, channels=1, dtype="float32", latency="low",
                                     device=int(dev) if str(dev).isdigit() else (dev or None), callback=cb)
        self.connected = True

    def start(self) -> None:  # pragma: no cover - needs hardware
        self.stream.start()
        self.recording = True

    def close(self) -> None:  # pragma: no cover - needs hardware
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        super().close()

    @classmethod
    def planned_streams(cls, options=None):
        o = cls.resolve_options(options or {})
        return InputDevice.planned_streams.__func__(cls, {"inputs": {o["input_name"]: o["input_name"]}}) + [
            {"name": "envelope", "kind": "Audio", "channels": ["db"], "srate": o["samplerate"] / o["block"],
             "what": "microphone loudness (dBFS), to check the voice onsets afterwards"}]


class VoiceDetector:
    """Speech onset/offset in an audio signal: loud for ``min_on`` s = onset (at the first loud sample),
    quiet for ``release`` s = offset."""

    def __init__(self, samplerate: int, threshold_db: float = -30.0, min_on: float = 0.015, release: float = 0.15):
        self.sr = samplerate
        self.level = 10 ** (threshold_db / 20)
        self.th = Threshold(self.level, self.level * 0.5, min_on, release)
        self.win = max(1, int(samplerate * 0.002))      # 2 ms loudness window

    def process(self, samples, t0: float) -> list[tuple[float, bool]]:
        out = []
        n = len(samples)
        for i in range(0, n, self.win):
            chunk = samples[i:i + self.win]
            peak = max(abs(float(v)) for v in chunk) if len(chunk) else 0.0
            out += self.th.feed(t0 + i / self.sr, peak)
        return out


@register
class SimInputs(InputDevice):
    type_name = "sim_inputs"
    description = "Simulated response box / TTL inputs for dry runs: the virtual participant presses its buttons; " \
                  "a simulated light sensor sees every screen change a few ms after the flip."
    capabilities = {"input", "stream", "markers"}
    options_schema = {**_COMMON,
                      "light_latency_ms": {"type": "float", "default": 8.0, "help": "simulated display latency"},
                      "simulate_light": {"type": "bool", "default": False}}

    def connect(self) -> None:
        self._init_inputs()
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        # a light sensor taped to the screen sees the change that came with a flip-locked marker
        if self.options.get("simulate_light") and marker.on_flip and marker.time is not None:
            name = (self.options.get("light_inputs") or ["light"])[0]
            t = float(marker.time) + float(self.options["light_latency_ms"]) / 1e3
            self.emit("inputs", t, [name, 1, ""], sync=False)
            self.emit("inputs", t + 0.016, [name, 0, ""], sync=False)


INPUT_TYPES = ("serial_inputs", "parallel_inputs", "labjack", "voice_key", "sim_inputs")


def low_latency(ser: Any) -> bool:
    """Ask the serial driver not to hold bytes back (Linux ASYNC_LOW_LATENCY; FTDI adapters otherwise
    wait up to their latency timer, 16 ms by default, before passing data on)."""
    try:
        ser.set_low_latency_mode(True)
        return True
    except Exception:
        return False


def reconnect(dev: Device, opener, stop: threading.Event, every: float = 0.5, give_up: float = 30.0) -> bool:
    """Reopen a lost connection until it works (True) or ``give_up`` seconds pass / the device stops (False)."""
    t_end = time.monotonic() + give_up
    while not stop.is_set() and time.monotonic() < t_end:
        try:
            opener()
            dev.errors.append(f"{dev.id}: reconnected")
            return True
        except Exception:
            stop.wait(every)
    dev.errors.append(f"{dev.id}: could not reconnect within {give_up:.0f} s")
    return False
