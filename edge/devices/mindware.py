"""MindWare physiology (BioNex, Mobile Impedance Cardiograph, EDA/ECG/EMG modules).

MindWare's BioLab acquires and stores the physiology itself. EDGE integrates in
the two ways the hardware supports:

1. **Event markers (always):** BioLab records digital event lines. Wire a TTL
   trigger output (``ttl_serial`` or ``parallel_port``) into the MindWare
   event/digital input. This driver wraps the trigger output, so markers sent
   by the experiment become event codes inside the BioLab file, sample-exact.

2. **Live data (optional):** if BioLab (or a bridge) publishes the channels on
   LSL, set ``lsl_name``/``lsl_type`` and EDGE records them into the session,
   aligned with everything else; physiology-contingent tasks (e.g. heart-rate
   biofeedback) can then read ``latest`` values.

After the session, ``edge align`` matches the TTL events found in the exported
BioLab file to EDGE's event log to put BioLab data on the master clock.
"""

from __future__ import annotations

from typing import Any

from ..events import Marker
from . import register
from .base import Device, DeviceError
from .lsl import LSLInlet
from .triggers import LoopbackTrigger, ParallelPort, SerialTrigger


@register
class MindWare(Device):
    type_name = "mindware"
    description = "MindWare BioLab: TTL event codes into the acquisition + optional live data over LSL."
    capabilities = {"markers", "stream", "ttl"}
    options_schema = {
        "trigger": {"type": "choice", "choices": ["serial", "parallel", "none", "loopback"], "default": "serial"},
        "port": {"type": "str", "default": "", "help": "serial port or parallel address of the TTL output"},
        "baudrate": {"type": "int", "default": 115200},
        "protocol": {"type": "choice", "choices": ["byte", "cedrus", "ascii"], "default": "byte"},
        "pulse_ms": {"type": "float", "default": 10.0},
        "code_map": {"type": "dict", "default": {}},
        "lsl_name": {"type": "str", "default": "", "help": "LSL stream name of live MindWare data (optional)"},
        "lsl_type": {"type": "str", "default": "", "help": "LSL stream type of live MindWare data (optional)"},
    }

    @classmethod
    def planned_streams(cls, options=None):
        o = cls.resolve_options(options or {})
        if not (o.get("lsl_name") or o.get("lsl_type")):
            return []
        return [{"name": o.get("lsl_name") or o.get("lsl_type"), "kind": "Physio", "channels": None, "srate": None,
                 "what": "live physiology channels from BioLab (via LSL)"}]

    @classmethod
    def records_note(cls, options=None):
        o = cls.resolve_options(options or {})
        return "" if o.get("trigger") == "none" else \
            "sends event codes (TTL) into BioLab, which records them with the physiology"

    def connect(self) -> None:
        o = self.options
        trig_opts: dict[str, Any] = {"pulse_ms": o["pulse_ms"], "code_map": o["code_map"]}
        kind = o["trigger"]
        self.trigger: Device | None
        if kind == "serial":
            self.trigger = SerialTrigger(self.id + ".ttl", {**trig_opts, "port": o["port"], "baudrate": o["baudrate"],
                                                            "protocol": o["protocol"]}, clock=self.clock)
        elif kind == "parallel":
            self.trigger = ParallelPort(self.id + ".ttl", {**trig_opts, "address": o["port"] or "0x378"}, clock=self.clock)
        elif kind == "loopback":
            self.trigger = LoopbackTrigger(self.id + ".ttl", {"code_map": o["code_map"]}, clock=self.clock)
        else:
            self.trigger = None
        if self.trigger is not None:
            self.trigger.connect()
        self.inlet: LSLInlet | None = None
        if o["lsl_name"] or o["lsl_type"]:
            self.inlet = LSLInlet(self.id, {"name": o["lsl_name"], "stream_type": o["lsl_type"]}, clock=self.clock)
            self.inlet._sinks = self._sinks
            try:
                self.inlet.connect()
            except DeviceError as e:
                raise DeviceError(f"MindWare live stream not found on LSL: {e}") from e
            self.streams = self.inlet.streams
            self.n_samples = self.inlet.n_samples
        self.connected = True

    def start(self) -> None:
        if self.inlet:
            self.inlet.start()
        self.recording = True

    def send_marker(self, marker: Marker) -> None:
        if self.trigger is not None:
            self.trigger.send_marker(marker)

    def close(self) -> None:
        if self.inlet:
            self.inlet.close()
        if self.trigger:
            self.trigger.close()
        super().close()

    def finalize_clock(self):
        return self.clock_model  # LSL data is already master-aligned

    def info(self) -> dict[str, Any]:
        return {"trigger": self.options["trigger"], "live_stream": bool(self.inlet)}
