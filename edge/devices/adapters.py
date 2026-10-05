"""Trigger adapters: send EDGE's event markers into an EEG / fNIRS / physiology system.

The same job as the cables PST sells as "Chronos adapters": pick the system you record with and
EDGE sets the connection, the number of trigger lines, the pulse width and how codes are reset, and
tells you how to wire it and where the triggers end up in that system's file. The actual output is
one of EDGE's trigger outputs (serial trigger box, parallel port, LabJack, or an LSL marker stream).

    devices:
      - {id: eeg_trig, type: trigger_adapter, options: {target: biosemi, address: "0x378"}}
"""

from __future__ import annotations

from typing import Any

from ..events import Marker
from . import register
from .base import Device, DeviceError

# connection: serial | parallel | labjack | lsl ; bits: trigger lines (1 = a single TTL line)
TARGETS: dict[str, dict[str, Any]] = {
    "biosemi": {
        "name": "BioSemi ActiveTwo", "connection": "parallel", "alternatives": ["serial", "labjack"], "bits": 8,
        "pulse_ms": 10.0,
        "wiring": "Parallel port (DB25) into the 37-pin trigger input of the ActiveTwo USB2 receiver (DB25-to-DB37 "
                  "cable), or BioSemi's USB trigger interface (a serial port: connection serial).",
        "recorded_as": "the Status channel of the .bdf file (lowest 8 bits)"},
    "brainproducts": {
        "name": "Brain Products TriggerBox (actiCHamp, BrainAmp, LiveAmp)", "connection": "serial",
        "alternatives": ["parallel", "labjack", "lsl"], "bits": 8, "pulse_ms": 10.0, "baudrate": 2000000,
        "wiring": "TriggerBox USB into this computer (it appears as a serial port), its 26-pin output into the "
                  "amplifier's trigger input (BrainAmp: through the USB2 Adapter).",
        "recorded_as": "stimulus markers S  1 … S255 in the .vmrk file (BrainVision Recorder)"},
    "brainamp_parallel": {
        "name": "BrainAmp / actiCHamp from a parallel port", "connection": "parallel", "alternatives": ["labjack"],
        "bits": 8, "pulse_ms": 10.0,
        "wiring": "Parallel port into the trigger input of the BrainAmp USB2 Adapter or the actiCHamp 8-bit trigger port.",
        "recorded_as": "stimulus markers S  1 … S255 in the .vmrk file"},
    "egi": {
        "name": "Magstim EGI Net Amps (DIN inputs)", "connection": "parallel", "alternatives": ["serial", "labjack"],
        "bits": 8, "pulse_ms": 10.0,
        "wiring": "Parallel port into the Net Amps DIN cable (8 TTL lines). Net Station shows them as DIN events.",
        "recorded_as": "DIN1 … DIN8 events (one per line) in Net Station"},
    "ant_neuro": {
        "name": "ANT Neuro eego", "connection": "parallel", "alternatives": ["serial", "labjack", "lsl"], "bits": 8,
        "pulse_ms": 10.0,
        "wiring": "Parallel port (or a USB trigger box) into the eego amplifier's 25-pin trigger input.",
        "recorded_as": "trigger events in the eego recording (.evt next to the .cnt file)"},
    "nirx": {
        "name": "NIRx NIRSport2 / NIRScout", "connection": "parallel", "alternatives": ["serial", "labjack", "lsl"],
        "bits": 8, "pulse_ms": 10.0,
        "wiring": "Parallel port into the NIRx trigger input (8 lines); with Aurora you can use the LSL marker "
                  "stream instead (connection lsl). Older NIRScout systems read only 4 lines: set bits to 4.",
        "recorded_as": "triggers (conditions) in the .tri / .evt file of the recording"},
    "artinis": {
        "name": "Artinis (OxySoft: PortaSync, LabStreamer)", "connection": "lsl", "alternatives": ["labjack"],
        "bits": None, "pulse_ms": 10.0,
        "wiring": "OxySoft reads the EDGE marker stream over LSL (enable it in OxySoft). For a TTL instead, wire one "
                  "line into the PortaSync / LabStreamer BNC input (connection labjack, bits 1).",
        "recorded_as": "events with the marker labels in the OxySoft recording"},
    "bitbrain": {
        "name": "Bitbrain (Versatile, Hero, Diadem)", "connection": "lsl", "alternatives": ["serial"], "bits": None,
        "pulse_ms": 10.0,
        "wiring": "The Bitbrain Viewer records the EDGE marker stream over LSL.",
        "recorded_as": "markers in the Bitbrain recording"},
    "biopac": {
        "name": "BIOPAC MP160 / MP36 (STP digital inputs)", "connection": "parallel", "alternatives": ["serial", "labjack"],
        "bits": 8, "pulse_ms": 10.0,
        "wiring": "Parallel port (or a USB-TTL box) into the STP100D / STP35 isolated digital interface.",
        "recorded_as": "digital channels D1 … D8 in AcqKnowledge (enable them as digital inputs)"},
    "adinstruments": {
        "name": "ADInstruments PowerLab (LabChart)", "connection": "labjack", "alternatives": ["serial", "parallel"],
        "bits": 1, "pulse_ms": 10.0,
        "wiring": "One TTL line into the PowerLab trigger input (BNC). A single line cannot carry codes: every marker "
                  "is the same pulse; use the event log (events.jsonl) to tell them apart.",
        "recorded_as": "trigger events in LabChart"},
    "mri": {
        "name": "MRI scanner log / any single TTL line", "connection": "serial", "alternatives": ["parallel", "labjack"],
        "bits": 1, "pulse_ms": 10.0,
        "wiring": "One TTL line (e.g. a BNC) into the system's event or trigger input.",
        "recorded_as": "a pulse per marker in that system's log"},
    "generic": {
        "name": "Any 8-line TTL input", "connection": "serial", "alternatives": ["parallel", "labjack", "lsl"],
        "bits": 8, "pulse_ms": 10.0,
        "wiring": "The trigger output of your interface into the 8-bit trigger input of the recording system.",
        "recorded_as": "the event/trigger channel of that system"},
}
CONNECTIONS = ("auto", "serial", "parallel", "labjack", "lsl")


def preset(options: dict[str, Any]) -> dict[str, Any]:
    t = TARGETS.get(str(options.get("target") or "generic"), TARGETS["generic"])
    conn = options.get("connection") or "auto"
    out = dict(t)
    out["connection"] = t["connection"] if conn == "auto" else conn
    if options.get("bits") not in (None, "", 0):
        out["bits"] = int(options["bits"])
    if out["connection"] == "lsl":
        out["bits"] = None
    if options.get("pulse_ms") not in (None, ""):
        out["pulse_ms"] = float(options["pulse_ms"])
    return out


def code_for_lines(code: int, bits: int | None) -> int:
    """What actually reaches the lines: 1 line = always a pulse; 4 lines = the low 4 bits."""
    if bits is None:
        return code
    if bits <= 1:
        return 1
    return code & ((1 << bits) - 1)


@register
class TriggerAdapter(Device):
    type_name = "trigger_adapter"
    description = ("Send event markers into an EEG, fNIRS or physiology system: BioSemi, Brain Products, EGI, "
                   "ANT Neuro, NIRx, Artinis, Bitbrain, BIOPAC, ADInstruments, an MRI scanner log, or any TTL input. "
                   "Pick the system; EDGE sets the connection, lines and pulse width and explains the wiring.")
    capabilities = {"markers", "ttl"}
    options_schema = {
        "target": {"type": "choice", "choices": list(TARGETS), "default": "generic",
                   "help": "the system that records the triggers"},
        "connection": {"type": "choice", "choices": list(CONNECTIONS), "default": "auto",
                       "help": "auto = the usual one for that system"},
        "port": {"type": "str", "default": "", "help": "serial port of a trigger box (COM3, /dev/ttyACM0); empty = the only one"},
        "address": {"type": "str", "default": "0x378", "help": "parallel port address (Windows) or /dev/parport0 (Linux)"},
        "bits": {"type": "int", "default": None, "help": "trigger lines the system reads (empty = the system's usual number)"},
        "pulse_ms": {"type": "float", "default": None, "help": "pulse width in ms (empty = 10 ms)"},
        "code_map": {"type": "dict", "default": {}, "help": "label -> code for markers without a code"},
    }

    def connect(self) -> None:
        p = preset(self.options)
        conn, pulse = p["connection"], float(p["pulse_ms"])
        common = {"pulse_ms": pulse, "code_map": {}}
        if conn == "serial":
            from .triggers import SerialTrigger
            out: Device = SerialTrigger(self.id, {**common, "port": self.options["port"],
                                                  "baudrate": p.get("baudrate", 115200), "protocol": "byte"}, clock=self.clock)
        elif conn == "parallel":
            from .triggers import ParallelPort
            out = ParallelPort(self.id, {**common, "address": self.options["address"]}, clock=self.clock)
        elif conn == "labjack":
            from .inputs import LabJack
            out = LabJack(self.id, {**common, "digital_inputs": [], "markers_out": True}, clock=self.clock)
        elif conn == "lsl":
            from .lsl import LSLMarkers
            out = LSLMarkers(self.id, {"name": f"EDGE-Markers-{self.id}", "format": "label"}, clock=self.clock)
        else:
            raise DeviceError(f"unknown connection '{conn}' (use {', '.join(CONNECTIONS)})")
        out.connect()
        self.out, self.preset = out, p
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        from .triggers import resolve_code
        if self.preset["connection"] == "lsl":
            self.out.send_marker(marker)
            return
        code = resolve_code(marker, self.options.get("code_map") or {})
        if code is not None:
            lines = code_for_lines(code, self.preset["bits"])
            self.out.send_marker(Marker(label=marker.label, time=marker.time, code=lines, source=marker.source,
                                        on_flip=marker.on_flip))

    def close(self) -> None:
        try:
            self.out.close()
        except Exception:
            pass
        super().close()

    def info(self) -> dict[str, Any]:
        p = getattr(self, "preset", preset(self.options))
        return {"target": p["name"], "connection": p["connection"], "bits": p["bits"]}

    @classmethod
    def records_note(cls, options=None):
        p = preset(cls.resolve_options(options or {}))
        how = "as an LSL marker stream" if p["connection"] == "lsl" else \
            f"as {p['bits']}-line TTL pulses of {p['pulse_ms']:g} ms via {p['connection']}"
        return f"sends the event markers to {p['name']} {how}; they are recorded in {p['recorded_as']}"

    @classmethod
    def describe(cls) -> dict[str, Any]:
        d = super().describe()
        d["targets"] = {k: {"name": v["name"], "connection": v["connection"], "bits": v["bits"],
                            "wiring": v["wiring"], "recorded_as": v["recorded_as"]} for k, v in TARGETS.items()}
        return d

    @classmethod
    def validate_options(cls, spec, exp) -> list:
        from ..model import Issue
        where = f"devices.{spec.id}"
        o = cls.resolve_options(spec.options)
        issues = []
        if o.get("target") not in TARGETS:
            issues.append(Issue("error", where, f"unknown target '{o.get('target')}'", hint=", ".join(TARGETS)))
            return issues
        if o.get("connection") not in CONNECTIONS:
            issues.append(Issue("error", where, f"unknown connection '{o.get('connection')}'", hint=", ".join(CONNECTIONS)))
            return issues
        p = preset(o)
        t = TARGETS[o["target"]]
        if p["connection"] not in [t["connection"], *t.get("alternatives", [])]:
            issues.append(Issue("warning", where, f"{t['name']} is not usually connected via {p['connection']}",
                                hint="usual: " + ", ".join([t["connection"], *t.get("alternatives", [])])))
        if p["connection"] == "lsl" and t["bits"] is not None:
            issues.append(Issue("info", where, f"LSL markers reach {t['name']} only if its recording software reads LSL"))
        bits = p["bits"]
        if bits:
            codes = _experiment_codes(exp, o.get("code_map") or {})
            limit = (1 << bits) - 1
            too_big = sorted({c for c in codes if c > limit})
            if bits == 1 and len(codes) > 1:
                issues.append(Issue("info", where, f"{t['name']} reads one line: all {len(codes)} marker codes arrive as the same pulse",
                                    hint="the event log (events.jsonl) still tells them apart"))
            elif too_big:
                issues.append(Issue("warning", where, f"codes {', '.join(map(str, too_big[:6]))} don't fit in {bits} trigger lines "
                                    f"(max {limit}); they would arrive as {', '.join(str(c & limit) for c in too_big[:6])}",
                                    hint=f"use codes 1–{limit} (settings.markers.codes or the marker's code)"))
        return issues


def _experiment_codes(exp, code_map: dict[str, Any]) -> set[int]:
    codes = {int(v) for v in ((exp.settings.get("markers") or {}).get("codes") or {}).values() if isinstance(v, int)}
    codes |= {int(v) for v in code_map.values() if isinstance(v, int)}
    for r in exp.routines.values():
        for c in r.components:
            m = c.props.get("marker")
            if isinstance(m, dict):
                for k in ("code", "offset_code"):
                    if isinstance(m.get(k), int):
                        codes.add(int(m[k]))
            if c.type == "marker" and isinstance(c.props.get("code"), int):
                codes.add(int(c.props["code"]))
    return codes
