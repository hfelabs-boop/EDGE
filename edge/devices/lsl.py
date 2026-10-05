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
        chans = []
        ch = full.desc().child("channels").child("channel")
        for _ in range(full.channel_count()):
            label = ch.child_value("label") if not ch.empty() else ""
            chans.append(label or f"ch{len(chans) + 1}")
            ch = ch.next_sibling()
        self.stream_name = full.name() or "lsl"
        # proc_clocksync converts remote timestamps to our local_clock, i.e. the master clock.
        self.add_stream(self.stream_name, chans, full.nominal_srate(), full.type(), time_base="master",
                        source_id=full.source_id(), hostname=full.hostname())
        self._gaze_idx = None
        gc = self.options.get("gaze_channels")
        if gc:
            self._gaze_idx = (chans.index(gc[0]), chans.index(gc[1]))
        self._latest = None
        self.connected = True

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
