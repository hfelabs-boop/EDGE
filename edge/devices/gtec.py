"""g.tec amplifiers.

Three ways in, chosen with ``mode``:

* ``lsl`` (default, works with everything): run g.tec's LSL app (Unicorn LSL,
  g.HIamp/g.USBamp/g.Nautilus via g.NEEDaccess LSL) and EDGE records the stream.
* ``unicorn``: direct acquisition from a Unicorn Hybrid Black through the
  Unicorn Python API (``UnicornPy``, shipped with the Unicorn Suite).
* ``gds``: direct acquisition from g.USBamp / g.HIamp / g.Nautilus through
  g.NEEDaccess (``pygds``).

Markers: g.tec amps record hardware triggers on their digital inputs. Pair this
device with a ``ttl_serial``/``parallel_port`` trigger device wired into the
amp's trigger input for sample-exact event marking; EDGE additionally stamps
each marker into its own aligned event log.
"""

from __future__ import annotations

from typing import Any

from . import register
from .base import Device, DeviceError
from .lsl import LSLInlet


@register
class GTec(Device):
    type_name = "gtec"
    description = "g.tec EEG (Unicorn, g.USBamp, g.HIamp, g.Nautilus) via LSL, UnicornPy or g.NEEDaccess (pygds)."
    capabilities = {"stream"}
    options_schema = {
        "mode": {"type": "choice", "choices": ["lsl", "unicorn", "gds"], "default": "lsl"},
        "lsl_name": {"type": "str", "default": "", "help": "LSL stream name (mode=lsl)"},
        "lsl_type": {"type": "str", "default": "EEG", "help": "LSL stream type (mode=lsl)"},
        "serial": {"type": "str", "default": "", "help": "device serial (unicorn/gds); empty = first found"},
        "srate": {"type": "float", "default": 250.0, "help": "sampling rate (gds)"},
        "scans_per_read": {"type": "int", "default": 8},
    }

    def connect(self) -> None:
        mode = self.options["mode"]
        if mode == "lsl":
            self._impl = LSLInlet(self.id, {"name": self.options["lsl_name"], "stream_type": self.options["lsl_type"]},
                                  clock=self.clock)
            self._impl._sinks = self._sinks
            self._impl.connect()
            self.streams = self._impl.streams
            self.n_samples = self._impl.n_samples
        elif mode == "unicorn":
            self._connect_unicorn()
        elif mode == "gds":
            self._connect_gds()
        else:
            raise DeviceError(f"unknown g.tec mode '{mode}'")
        self.connected = True

    # ------------------------------------------------------------ Unicorn
    def _connect_unicorn(self) -> None:
        try:
            import UnicornPy  # type: ignore
        except ImportError as e:
            raise DeviceError("UnicornPy not found: install the Unicorn Suite Python API") from e
        self._up = UnicornPy
        serials = UnicornPy.GetAvailableDevices(True)
        if not serials:
            raise DeviceError("no paired Unicorn found")
        serial = self.options["serial"] or serials[0]
        self.dev = UnicornPy.Unicorn(serial)
        n = self.dev.GetNumberOfAcquiredChannels()
        cfg = self.dev.GetConfiguration()
        names = [cfg.Channels[i].Name for i in range(len(cfg.Channels)) if cfg.Channels[i].Enabled][:n]
        self.add_stream("eeg", names, UnicornPy.SamplingRate, "EEG", serial=serial)
        self._nch = n

    def _read_unicorn(self) -> None:
        import struct
        scans = int(self.options["scans_per_read"])
        buf = bytearray(scans * self._nch * 4)
        srate = float(self._up.SamplingRate)
        k = 0
        while not self.should_stop:
            self.dev.GetData(scans, buf, len(buf))
            arrival = self.clock()
            vals = struct.unpack(f"<{scans * self._nch}f", buf)
            for s in range(scans):
                # device time = sample index / srate; aligned later by the arrival model
                self.emit("eeg", (k + s) / srate, list(vals[s * self._nch:(s + 1) * self._nch]), arrival=arrival)
            k += scans

    # ------------------------------------------------------------ g.NEEDaccess
    def _connect_gds(self) -> None:
        try:
            import pygds  # type: ignore
        except ImportError as e:
            raise DeviceError("pygds not found: install g.NEEDaccess and its Python wrapper") from e
        self.dev = pygds.GDS(self.options["serial"] or None) if self.options["serial"] else pygds.GDS()
        try:
            self.dev.SamplingRate = int(self.options["srate"])
        except Exception:
            pass
        self.dev.SetConfiguration()
        try:
            n = len(self.dev.GetChannelNames()[0])
            names = list(self.dev.GetChannelNames()[0])
        except Exception:
            n = getattr(self.dev, "NumberOfAcquiredChannels", 16)
            names = [f"ch{i + 1}" for i in range(n)]
        self.add_stream("eeg", names, float(self.options["srate"]), "EEG")

    def _read_gds(self) -> None:
        srate = float(self.options["srate"])
        state = {"k": 0}

        def more(samples) -> bool:
            arrival = self.clock()
            for row in samples:
                self.emit("eeg", state["k"] / srate, list(map(float, row)), arrival=arrival)
                state["k"] += 1
            return not self.should_stop

        self.dev.GetData(int(self.options["scans_per_read"]), more=more)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        mode = self.options["mode"]
        if mode == "lsl":
            self._impl.start()
        elif mode == "unicorn":
            self.dev.StartAcquisition(False)
            self.spawn(self._read_unicorn)
        else:
            self.spawn(self._read_gds)
        self.recording = True

    def stop(self) -> None:
        if self.options["mode"] == "unicorn" and self.recording:
            self._stop.set()
            for t in self._threads:
                t.join(timeout=2)
            self.dev.StopAcquisition()
        self.recording = False

    def close(self) -> None:
        if self.options["mode"] == "lsl":
            self._impl.close()
        super().close()
        if self.options["mode"] == "gds":
            try:
                self.dev.Close()
            except Exception:
                pass

    def finalize_clock(self):
        if self.options["mode"] == "lsl":
            return self.clock_model  # already master-aligned by LSL
        return super().finalize_clock()

    def info(self) -> dict[str, Any]:
        return {"mode": self.options["mode"]}
