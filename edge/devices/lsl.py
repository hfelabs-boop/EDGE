"""Lab Streaming Layer drivers.

* ``lsl_markers`` publishes every EDGE marker as an LSL string stream, so
  LabRecorder (or any LSL consumer) records them next to EEG, physiology, eye
  tracking, motion capture, etc.
* ``lsl_inlet`` records any LSL stream (g.tec, Brain Products, OpenBCI, Muse,
  Pupil Labs, MindWare/BIOPAC bridges, ...) straight into the EDGE session,
  already aligned to the master clock using LSL's own clock synchronization.

Because EDGE's master clock *is* ``pylsl.local_clock`` when pylsl is
installed, marker timestamps pushed to LSL need no conversion at all.
"""

from __future__ import annotations

import json
from typing import Any

from ..events import Marker
from . import register
from .base import Device, DeviceError


def _pylsl():
    try:
        import pylsl
        return pylsl
    except Exception as e:  # ImportError or missing liblsl binary
        raise DeviceError(f"LSL is unavailable: {e}. Install with: pip install pylsl") from e


@register
class LSLMarkers(Device):
    type_name = "lsl_markers"
    description = "Publish EDGE markers as an LSL marker stream (string labels, optional JSON payload)."
    capabilities = {"markers"}
    requires = ["pylsl"]
    options_schema = {
        "name": {"type": "str", "default": "EDGE-Markers"},
        "stream_type": {"type": "str", "default": "Markers"},
        "source_id": {"type": "str", "default": "edge-markers"},
        "format": {"type": "choice", "choices": ["label", "code", "json"], "default": "label",
                   "help": "label: 'stim_onset'; code: '12'; json: full marker incl. trial fields"},
        "wait_for_consumers": {"type": "float", "default": 0.0,
                               "help": "seconds to wait at startup until a recorder (e.g. LabRecorder) is "
                                       "connected; markers pushed before anyone listens are lost"},
    }

    def connect(self) -> None:
        lsl = _pylsl()
        info = lsl.StreamInfo(self.options["name"], self.options["stream_type"], 1, lsl.IRREGULAR_RATE,
                              lsl.cf_string, self.options["source_id"])
        info.desc().append_child_value("software", "EDGE")
        self.outlet = lsl.StreamOutlet(info)
        wait = float(self.options.get("wait_for_consumers") or 0)
        if wait > 0 and not self.outlet.wait_for_consumers(wait):
            raise DeviceError(f"no LSL consumer connected to '{self.options['name']}' within {wait} s "
                              "(start LabRecorder and select the stream)")
        self.connected = True

    def send_marker(self, marker: Marker) -> None:
        fmt = self.options["format"]
        if fmt == "code":
            payload = str(marker.code if marker.code is not None else marker.label)
        elif fmt == "json":
            payload = json.dumps({"label": marker.label, "code": marker.code, "source": marker.source,
                                  "fields": marker.fields}, default=str)
        else:
            payload = marker.label
        # marker.time is on the master clock == lsl.local_clock, so it can be pushed as-is.
        self.outlet.push_sample([payload], marker.time)

    def info(self) -> dict[str, Any]:
        return {"name": self.options["name"], "source_id": self.options["source_id"]}


@register
class LSLInlet(Device):
    type_name = "lsl_inlet"
    description = "Record any LSL stream (EEG, physiology, eye tracking, motion ...) into the session."
    capabilities = {"stream"}
    requires = ["pylsl"]
    options_schema = {
        "name": {"type": "str", "default": "", "help": "stream name to match (optional)"},
        "stream_type": {"type": "str", "default": "", "help": "stream type to match, e.g. EEG (optional)"},
        "source_id": {"type": "str", "default": "", "help": "source id to match (optional)"},
        "timeout": {"type": "float", "default": 5.0, "help": "seconds to wait for the stream"},
        "max_buffered": {"type": "int", "default": 360},
        "gaze_channels": {"type": "list", "default": None,
                          "help": "[x_channel, y_channel] to enable gaze-contingent use (normalized coords)"},
        "impedance_stream": {"type": "str", "default": "",
                             "help": "an LSL stream of electrode impedances to show on the Run page: its name, or "
                                     "auto = a stream of type 'Impedance' from the same computer (EEG streams only); "
                                     "empty (default) for none"},
    }

    @classmethod
    def planned_streams(cls, options=None):
        o = cls.resolve_options(options or {})
        label = o.get("name") or o.get("stream_type") or "stream"
        return [{"name": label, "kind": o.get("stream_type") or "", "channels": None, "srate": None,
                 "what": f"every channel of the LSL stream {label!r}, at its own rate"}]

    def connect(self) -> None:
        lsl = _pylsl()
        preds = []
        for key, prop in (("name", "name"), ("stream_type", "type"), ("source_id", "source_id")):
            if self.options.get(key):
                preds.append(f"{prop}='{self.options[key]}'")
        pred = " and ".join(preds) or "true()"
        found = lsl.resolve_bypred(pred, 1, float(self.options["timeout"]))
        if not found:
            raise DeviceError(f"no LSL stream matching [{pred}] found within {self.options['timeout']} s")
        si = found[0]
        self.inlet = lsl.StreamInlet(si, max_buflen=int(self.options["max_buffered"]),
                                     processing_flags=lsl.proc_clocksync | lsl.proc_dejitter)
        full = self.inlet.info()
        chans, units = [], []
        ch = full.desc().child("channels").child("channel")
        for _ in range(full.channel_count()):
            label = ch.child_value("label") if not ch.empty() else ""
            chans.append(label or f"ch{len(chans) + 1}")
            units.append((ch.child_value("unit") if not ch.empty() else "") or "")    # as the sender declares it
            ch = ch.next_sibling()
        self.stream_name = full.name() or "lsl"
        # proc_clocksync converts remote timestamps to our local_clock, i.e. the master clock.
        self.add_stream(self.stream_name, chans, full.nominal_srate(), full.type(), time_base="master",
                        units=units if any(units) else None,
                        source_id=full.source_id(), hostname=full.hostname())
        self._gaze_idx = None
        gc = self.options.get("gaze_channels")
        if gc:
            self._gaze_idx = (chans.index(gc[0]), chans.index(gc[1]))
        self._latest = None
        self._connect_impedance(lsl, full)
        self.connected = True

    # ------------------------------------------------------------ impedance (optional companion stream)
    def _connect_impedance(self, lsl: Any, full: Any) -> None:
        self._imp_inlet, self._imp_names, self._imp_scale, self._imp = None, [], 1.0, None
        want = str(self.options.get("impedance_stream") or "").strip()
        if not want or want == "auto" and str(full.type()).upper() != "EEG":
            return
        pred = f"name='{want}'" if want != "auto" else f"type='Impedance' and hostname='{full.hostname()}'"
        try:
            found = lsl.resolve_bypred(pred, 1, 0.5)
            if not found:
                return
            self._imp_inlet = lsl.StreamInlet(found[0])
            info = self._imp_inlet.info()
            ch = info.desc().child("channels").child("channel")
            unit = ""
            for _ in range(info.channel_count()):
                self._imp_names.append((ch.child_value("label") if not ch.empty() else "") or f"ch{len(self._imp_names) + 1}")
                unit = unit or ((ch.child_value("unit") if not ch.empty() else "") or "")
                ch = ch.next_sibling()
            # values in kOhm unless the channels say otherwise
            self._imp_scale = {"ohm": 1e-3, "ohms": 1e-3, "Ω": 1e-3, "MOhm": 1e3, "MΩ": 1e3}.get(unit.strip(), 1.0)
            if unit.strip().lower() in ("ohm", "ohms"):
                self._imp_scale = 1e-3
        except Exception:
            self._imp_inlet = None

    def impedance(self) -> dict[str, float] | None:
        inlet = getattr(self, "_imp_inlet", None)
        if inlet is None:
            return None
        try:
            chunk, _ = inlet.pull_chunk(timeout=0.0)
            if chunk:
                last = chunk[-1]
                self._imp = {n: float(v) * self._imp_scale for n, v in zip(self._imp_names, last)
                             if isinstance(v, (int, float)) and v == v}
        except Exception:
            pass
        return self._imp

    def impedance_note(self) -> str:
        return ("no impedance stream (an LSL stream of type 'Impedance') was found: not available from this device"
                if self.options.get("impedance_stream") else "not available from this device")

    def start(self) -> None:
        self.inlet.open_stream()
        self.recording = True
        self.spawn(self._reader)

    def _reader(self) -> None:
        while not self.should_stop:
            chunk, stamps = self.inlet.pull_chunk(timeout=0.05)
            for values, ts in zip(chunk, stamps):
                self.emit(self.stream_name, ts, list(values), sync=False)
                if self._gaze_idx is not None:
                    x, y = values[self._gaze_idx[0]], values[self._gaze_idx[1]]
                    if x == x and y == y:  # not NaN
                        self._latest = self.norm_to_window(x, y)

    def latest_gaze(self):
        return self._latest

    def info(self) -> dict[str, Any]:
        return {"stream": self.stream_name, "channels": self.streams[self.stream_name].channels}
