"""External devices: response boxes, TTL inputs, light sensors, voice keys and trigger adapters."""

import sys
import types
from pathlib import Path

import pytest

from edge.devices import create_device, device_registry
from edge.devices.adapters import TARGETS, TriggerAdapter, code_for_lines, preset
from edge.devices.inputs import Threshold, VoiceDetector, decode_mask, parse_ascii, parse_cedrus
from edge.engine import run_experiment
from edge.events import Marker
from edge.measures import recording_plan
from edge.model import Experiment

BOX = {
    "name": "boxtask",
    "settings": {"window": {"size": [800, 600]}},
    "devices": [
        {"id": "box", "type": "serial_inputs", "options": {"protocol": "cedrus", "inputs": {1: "left", 2: "right", 8: "light"}}},
        {"id": "eeg", "type": "trigger_adapter", "options": {"target": "biosemi"}},
        {"id": "mic", "type": "voice_key"},
    ],
    "routines": {
        "trial": {"components": [
            {"id": "fix", "type": "fixation", "duration": 0.3},
            {"id": "arrow", "type": "text", "text": "$arrow", "start": 0.3, "marker": {"onset": "arrow", "code": 7}},
            {"id": "press", "type": "device_response", "device": "box", "inputs": ["left", "right"], "correct": "$side",
             "start": 0.3, "duration": 2, "end_routine": True},
        ]},
        "name_it": {"components": [
            {"id": "pic", "type": "text", "text": "apple"},
            {"id": "say", "type": "device_response", "device": "mic", "inputs": ["voice"], "duration": 2, "end_routine": True},
        ]},
    },
    "flow": [{"loop": "trials", "conditions": [{"arrow": "<", "side": "left"}, {"arrow": ">", "side": "right"}],
              "repeats": 5, "children": ["trial", "name_it"]}],
}


def _exp(doc=None, tmp_path=None):
    import copy
    return Experiment.from_dict(copy.deepcopy(doc or BOX), base_dir=tmp_path or Path("."))


# ============================================================================ protocols
def test_line_masks_ascii_and_cedrus_packets():
    assert decode_mask(0b0000, 0b0101) == [(1, True), (3, True)]
    assert decode_mask(0b0101, 0b0100) == [(1, False)]
    assert parse_ascii("5") == ("5", True) and parse_ascii("B3\r") == ("3", True)
    assert parse_ascii("left up") == ("left", False) and parse_ascii("  ") is None
    pkt = b"k" + bytes([(2 << 5) | (1 << 4) | 0]) + (1234).to_bytes(4, "little")
    assert parse_cedrus(pkt) == (0, 3, True, 1234)
    assert parse_cedrus(b"x12345") is None


def test_threshold_and_voice_onsets():
    th = Threshold(1.0, min_on=0.005, min_off=0.01)
    events = []
    for i in range(100):
        t = i * 0.001
        events += th.feed(t, 2.0 if 20 <= i < 60 else 0.0)
    assert [(round(t, 3), on) for t, on in events] == [(0.02, True), (0.06, False)]
    np = pytest.importorskip("numpy")
    sr = 10000
    sig = np.zeros(sr)                                # 1 s of silence with a "word" from 300 to 500 ms
    sig[3000:5000] = 0.3 * np.sin(np.arange(2000) * 2 * np.pi * 200 / sr)
    det = VoiceDetector(sr, threshold_db=-30, min_on=0.015, release=0.1)
    out = []
    for i in range(0, sr, 64):                         # fed in blocks, like the microphone callback
        out += det.process(sig[i:i + 64], 10.0 + i / sr)
    onset, offset = out
    assert onset[1] and abs(onset[0] - 10.3) < 0.004
    assert not offset[1] and abs(offset[0] - 10.5) < 0.005


# ============================================================================ trigger adapters
def test_presets_cover_the_common_recording_systems():
    for key in ("biosemi", "brainproducts", "egi", "ant_neuro", "nirx", "artinis", "bitbrain", "biopac",
                "adinstruments", "mri", "generic"):
        t = TARGETS[key]
        assert t["name"] and t["wiring"] and t["recorded_as"] and t["connection"] in ("serial", "parallel", "labjack", "lsl")
    assert preset({"target": "brainproducts"})["connection"] == "serial"
    assert preset({"target": "biosemi", "connection": "serial"})["connection"] == "serial"
    assert preset({"target": "nirx", "bits": 4})["bits"] == 4
    assert preset({"target": "nirx", "connection": "lsl"})["bits"] is None
    assert code_for_lines(300, 8) == 44 and code_for_lines(12, 4) == 12 and code_for_lines(17, 4) == 1
    assert code_for_lines(99, 1) == 1 and code_for_lines(99, None) == 99
    note = TriggerAdapter.records_note({"target": "biosemi"})
    assert "BioSemi" in note and "Status channel" in note
    assert "targets" in TriggerAdapter.describe()


def test_trigger_codes_are_checked_against_the_lines(tmp_path):
    doc = dict(BOX)
    doc["routines"] = {**BOX["routines"], "trial": {"components": [
        {**c, "marker": {"onset": "arrow", "code": 300}} if c["id"] == "arrow" else c for c in BOX["routines"]["trial"]["components"]]}}
    msgs = [str(i) for i in _exp(doc, tmp_path).validate() if i.where == "devices.eeg"]
    assert any("codes 300 don't fit in 8 trigger lines" in m and "arrive as 44" in m for m in msgs)
    doc["devices"] = [{"id": "eeg", "type": "trigger_adapter", "options": {"target": "adinstruments"}}]
    doc["settings"] = {"markers": {"codes": {"a": 1, "b": 2}}}
    assert any("all 3 marker codes arrive as the same pulse" in str(i) for i in _exp(doc, tmp_path).validate())
    doc["devices"] = [{"id": "eeg", "type": "trigger_adapter", "options": {"target": "nope"}}]
    assert any("unknown target 'nope'" in str(i) for i in _exp(doc, tmp_path).validate())
    doc["devices"] = [{"id": "eeg", "type": "trigger_adapter", "options": {"target": "biosemi", "connection": "lsl"}}]
    assert any("not usually connected via lsl" in str(i) for i in _exp(doc, tmp_path).validate())


def test_trigger_adapter_writes_the_right_byte_to_a_trigger_box(monkeypatch):
    written = []

    class FakeSerial:
        def __init__(self, port, baud, **kw):
            self.port, self.baud = port, baud

        def write(self, b):
            written.append(bytes(b))

        def close(self):
            pass

    fake = types.ModuleType("serial")
    fake.Serial = FakeSerial
    tools = types.ModuleType("serial.tools")
    lp = types.ModuleType("serial.tools.list_ports")
    lp.comports = lambda: [types.SimpleNamespace(device="COM7")]
    tools.list_ports = lp
    fake.tools = tools
    monkeypatch.setitem(sys.modules, "serial", fake)
    monkeypatch.setitem(sys.modules, "serial.tools", tools)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", lp)
    dev = create_device("trigger_adapter", "trig", {"target": "nirx", "connection": "serial", "bits": 4, "pulse_ms": 0})
    dev.connect()
    assert dev.out.port == "COM7" and dev.info()["bits"] == 4
    dev.send_marker(Marker("stim", 1.0, code=18))
    assert written[-1] == bytes([18 & 15])
    dev = create_device("trigger_adapter", "bp", {"target": "brainproducts", "pulse_ms": 0})
    dev.connect()
    assert dev.out.ser.baud == 2000000
    dev.send_marker(Marker("stim", 1.0, code=200))
    assert written[-1] == bytes([200])


# ============================================================================ inputs as responses
def test_input_devices_declare_streams_and_are_responses():
    reg = device_registry()
    for t in ("serial_inputs", "parallel_inputs", "labjack", "voice_key", "sim_inputs"):
        assert "input" in reg[t].capabilities
        assert reg[t].planned_streams({})[0]["name"] == "inputs"
    assert [s["name"] for s in reg["voice_key"].planned_streams({})] == ["inputs", "envelope"]
    plan = recording_plan(_exp())
    box = next(d for d in plan["devices"] if d["id"] == "box")
    assert "left, right, light" in box["streams"][0]["what"] and box["files"] == ["streams/box.inputs.csv"]
    press = next(c for c in plan["components"] if c["id"] == "press")
    assert {o["key"] for o in press["outputs"]} == {"input", "rt", "corr", "time", "device"}


def test_button_box_and_voice_key_in_a_dry_run(tmp_path):
    import csv
    from edge.report import analyze_session
    s = run_experiment(_exp(tmp_path=tmp_path), dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    root = Path(s["data_dir"])
    with (root / "trials_wide.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 10
    pressed = [r for r in rows if r["press.input"]]
    assert len(pressed) >= 8 and all(r["press.device"] == "box" for r in pressed)
    assert all((r["press.input"] == r["side"]) == (r["press.corr"] == "1") for r in pressed)
    assert sum(r["press.corr"] == "1" for r in pressed) >= 6
    assert all(r["say.input"] == "voice" and 0.1 < float(r["say.rt"]) < 3 for r in rows if r["say.input"])
    with (root / "streams" / "box.inputs.csv").open() as f:
        inputs = list(csv.DictReader(f))
    assert {r["input"] for r in inputs} >= {"left", "light"} or {r["input"] for r in inputs} >= {"right", "light"}
    with (root / "data_dictionary.csv").open(encoding="utf-8-sig") as f:
        dd = {r["column"]: r for r in csv.DictReader(f)}
    assert dd["press.input"]["group"] == "response" and "Which input" in dd["press.input"]["description"]
    rep = analyze_session(root)
    dl = rep["display_latency"]
    assert dl["matched"] == dl["light_onsets"] > 5 and abs(dl["mean_ms"] - 8.0) < 0.5
    assert rep["streams"]["eeg.ttl"]["triggers"]["matched"] == rep["streams"]["eeg.ttl"]["triggers"]["expected"]


def test_keyboard_stand_ins_when_there_is_no_box(tmp_path):
    import csv
    doc = {"name": "k", "settings": {"window": {"size": [400, 300]}},
           "routines": {"t": {"components": [
               {"id": "b", "type": "device_response", "inputs": ["left", "right"], "keys": {"f": "left", "j": "right"},
                "correct": "$side", "duration": 2, "end_routine": True}]}},
           "flow": [{"loop": "L", "conditions": [{"side": "left"}, {"side": "right"}], "repeats": 3, "children": ["t"]}]}
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    assert not [i for i in exp.validate() if i.level in ("error", "warning")]
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    with (Path(s["data_dir"]) / "trials_wide.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert {r["b.device"] for r in rows if r["b.input"]} == {"keyboard"}
    assert {r["b.input"] for r in rows} <= {"left", "right", ""}


def test_device_response_explains_missing_or_wrong_devices(tmp_path):
    doc = {"name": "x", "devices": [{"id": "eye", "type": "sim_eyetracker"}],
           "routines": {"t": {"components": [{"id": "b", "type": "device_response", "device": "eye", "duration": 1}]}},
           "flow": ["t"]}
    assert any("'eye' (sim_eyetracker) has no inputs" in str(i) for i in Experiment.from_dict(doc).validate())
    doc["routines"]["t"]["components"][0].pop("device")
    doc["devices"] = []
    assert any("no input device" in str(i) for i in Experiment.from_dict(doc).validate())


def test_input_device_queue_and_names():
    dev = create_device("sim_inputs", "box", {"inputs": {1: "left"}, "record_releases": False})
    dev.connect()
    samples = []
    dev.add_sink(lambda *a: samples.append(a))
    dev.push(1, 5.0)
    dev.push(2, 5.1, down=False)              # a release, not recorded but still an event
    evs = dev.drain()
    assert [(e.kind, e.name, e.down, e.device) for e in evs] == [("device", "left", True, "box"), ("device", "2", False, "box")]
    assert dev.drain() == [] and len(samples) == 1


def test_builder_device_menu_targets_come_from_the_schema():
    from edge.builder.server import schema
    d = schema()["devices"]
    assert set(d["trigger_adapter"]["targets"]) == set(TARGETS)
    assert d["serial_inputs"]["planned_streams"][0]["name"] == "inputs"
    js = (Path(__file__).resolve().parent.parent / "edge" / "builder" / "static" / "app.js").read_text()
    for t in ("serial_inputs", "labjack", "parallel_inputs", "voice_key", "device_response"):
        assert t in js
