"""Plug and play: identification (hardware_db), detection backends with fake providers, the watcher's diffs,
the builder endpoints behind the guard, adding suggested devices (valid + dry-runs), passive detection (no serial
writes), the session monitor's unplug report, `edge scan` and MCP scan_hardware."""

import copy
import json
import shutil
import sys
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from edge import hardware_db, hotplug

ROOT = Path(__file__).resolve().parent.parent

RB840 = {"kind": "serial", "port": "COM3", "vid": "0403", "pid": "6001", "serial_number": "FT1", "manufacturer": "FTDI",
         "description": "RB-840"}
ARDUINO = {"kind": "serial", "port": "/dev/ttyACM0", "vid": "2341", "pid": "0043", "serial_number": "7543",
           "description": "Arduino Uno"}
MIC = {"kind": "audio", "name": "USB Microphone", "index": 3}
PAD = {"kind": "gamepad", "name": "Xbox Controller", "index": 0}
MON2 = {"kind": "monitor", "index": 1, "width": 1920, "height": 1080, "rate": 144}
BIOSEMI = {"kind": "lsl", "name": "BioSemi", "lsl_type": "EEG", "channel_count": 72, "srate": 2048.0, "source_id": "bs1",
           "host": "amp-pc"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv(hotplug.FAKE_ENV, raising=False)
    hardware_db._user_cache["key"] = None


def ident(item):
    return hardware_db.identify(item)


# ============================================================================ identification table
@pytest.mark.parametrize("item, entry, certainty, dtype, options", [
    (RB840, "cedrus_rb", "probably", "serial_inputs", {"port": "COM3", "protocol": "cedrus", "baudrate": 115200}),
    ({"kind": "serial", "port": "COM4", "vid": "0403", "pid": "6001", "description": "StimTracker"}, "cedrus_stimtracker",
     "probably", "ttl_serial", {"port": "COM4", "protocol": "cedrus"}),
    ({"kind": "serial", "port": "COM5", "vid": "0403", "pid": "6001", "description": "Lumina LP-400"}, "cedrus_lumina",
     "probably", "serial_inputs", {"port": "COM5", "protocol": "cedrus", "baudrate": 115200}),
    ({"kind": "serial", "port": "COM6", "vid": "0403", "pid": "6001", "description": "c-pod"}, "cedrus_cpod", "probably",
     "ttl_serial", {"port": "COM6", "protocol": "cedrus"}),
    ({"kind": "serial", "port": "COM7", "description": "TriggerBox VirtualSerial Port"}, "bp_triggerbox", "probably",
     "trigger_adapter", {"target": "brainproducts", "connection": "serial", "port": "COM7"}),
    ({"kind": "serial", "port": "COM8", "vid": "0403", "pid": "6001", "description": "BBTK USB TTL Module"}, "bbtk", "probably",
     "ttl_serial", {"port": "COM8", "protocol": "byte"}),
    ({"kind": "serial", "port": "COM9", "description": "Current Designs fORP 932"}, "forp", "probably", "serial_inputs",
     {"port": "COM9", "protocol": "ascii", "baudrate": 57600, "inputs": {5: "trigger"}}),
    ({"kind": "serial", "port": "COM10", "description": "Standard Serial over Bluetooth link (UN-2019.05.08)"}, "unicorn_bt",
     "probably", "gtec", {"mode": "unicorn", "serial": "UN-2019.05.08"}),
    ({"kind": "serial", "port": "COM11", "manufacturer": "MindWare Technologies"}, "mindware", "probably", "mindware",
     {"trigger": "serial", "port": "COM11"}),
    (ARDUINO, "arduino", "ask", "ttl_serial", {"port": "/dev/ttyACM0", "protocol": "byte"}),
    ({"kind": "serial", "port": "/dev/ttyACM1", "vid": "2a03", "pid": "0043"}, "arduino_org", "ask", "ttl_serial", None),
    ({"kind": "serial", "port": "/dev/ttyACM2", "vid": "16c0", "pid": "0483"}, "teensy", "ask", "ttl_serial", None),
    ({"kind": "serial", "port": "COM12", "vid": "0403", "pid": "6015", "description": "USB Serial Port"}, "ftdi", "ask",
     "ttl_serial", {"port": "COM12", "protocol": "byte"}),
    ({"kind": "serial", "port": "COM13", "vid": "1a86", "pid": "7523", "description": "USB-SERIAL CH340"}, "ch340", "ask",
     "ttl_serial", None),
    ({"kind": "serial", "port": "COM14", "vid": "067b", "pid": "2303"}, "prolific", "ask", "ttl_serial", None),
    ({"kind": "serial", "port": "COM15", "vid": "10c4", "pid": "ea60"}, "cp210x", "ask", "ttl_serial", None),
    ({"kind": "serial", "port": "/dev/ttyUSB9"}, "serial_unknown", "ask", "ttl_serial", None),
    (BIOSEMI, "biosemi", "probably", "lsl_inlet", {"name": "BioSemi", "stream_type": "EEG"}),
    ({"kind": "lsl", "name": "LiveAmpSN-054", "lsl_type": "EEG", "channel_count": 32, "srate": 500}, "brainproducts",
     "probably", "lsl_inlet", {"name": "LiveAmpSN-054", "stream_type": "EEG"}),
    ({"kind": "lsl", "name": "Unicorn", "lsl_type": "Data", "channel_count": 17, "srate": 250}, "gtec_lsl", "probably", "gtec",
     {"mode": "lsl", "lsl_name": "Unicorn", "lsl_type": "Data"}),
    ({"kind": "lsl", "name": "obci_eeg1", "lsl_type": "EEG", "channel_count": 8, "srate": 250}, "openbci", "probably",
     "lsl_inlet", None),
    ({"kind": "lsl", "name": "Muse-1A2B", "lsl_type": "EEG", "channel_count": 5, "srate": 256}, "muse", "probably", "lsl_inlet",
     None),
    ({"kind": "lsl", "name": "pupil_capture", "lsl_type": "Gaze", "channel_count": 22, "srate": 200,
      "channels": ["confidence", "norm_pos_x", "norm_pos_y"]}, "pupil_lsl", "probably", "lsl_inlet",
     {"name": "pupil_capture", "stream_type": "Gaze", "gaze_channels": ["norm_pos_x", "norm_pos_y"]}),
    ({"kind": "lsl", "name": "TobiiPro", "lsl_type": "Gaze", "channel_count": 4, "srate": 120}, "tobii_lsl", "probably",
     "lsl_inlet", None),
    ({"kind": "lsl", "name": "PsychoPyMarkers", "lsl_type": "Markers", "channel_count": 1, "srate": 0}, "lsl_markers",
     "probably", "lsl_inlet", None),
    ({"kind": "lsl", "name": "MyAmp", "lsl_type": "EEG", "channel_count": 64, "srate": 1000}, "lsl_eeg", "probably", "lsl_inlet",
     {"name": "MyAmp", "stream_type": "EEG"}),
    ({"kind": "lsl", "name": "Accel", "lsl_type": "Mocap", "channel_count": 3, "srate": 100}, "lsl_any", "probably", "lsl_inlet",
     None),
    ({"kind": "tobii", "model": "Tobii Pro Spectrum", "serial_number": "TPS-1", "address": "tobii-prp://TPS-1"}, "tobii", "sure",
     "tobii", {"address": "tobii-prp://TPS-1"}),
    ({"kind": "gazepoint", "host": "127.0.0.1", "tcp_port": 4242}, "gazepoint", "probably", "gazepoint",
     {"host": "127.0.0.1", "port": 4242}),
    ({"kind": "labjack", "model": "U6", "serial_number": "360012345"}, "labjack", "sure", "labjack", {"model": "U6"}),
    ({"kind": "parallel", "port": "/dev/parport0"}, "parallel", "sure", "parallel_port", {"address": "/dev/parport0"}),
    (MIC, "microphone", "sure", "voice_key", {"device": "USB Microphone"}),
])
def test_identification_table(item, entry, certainty, dtype, options):
    r = ident(item)
    assert r["entry"] == entry
    assert r["certainty"] == certainty
    devs = [o["device"] for o in r["offers"] if o.get("device")]
    assert devs and devs[0]["type"] == dtype if dtype != "voice_key" else any(d["type"] == dtype for d in devs)
    if options is not None:
        d = next(d for d in devs if d["type"] == dtype)
        for k, v in options.items():
            assert d["options"][k] == v, (k, d["options"])
    if certainty == "ask":
        assert len(r["offers"]) >= 3 and r.get("question")
    # every device an offer adds is a known type with known options
    from edge.devices import device_registry
    reg = device_registry()
    for d in devs:
        assert d["type"] in reg
        assert set(d["options"]) <= set(reg[d["type"]].options_schema), (d["type"], d["options"])


def test_cedrus_pad_gets_named_buttons_and_a_button_box_item():
    r = ident(RB840)
    assert r["name"] == "Cedrus RB-840 response pad" and r["identify"] == "cedrus"
    o = r["offers"][0]
    assert o["device"]["options"]["inputs"] == {i: f"b{i}" for i in range(1, 9)}
    assert o["item"]["type"] == "device_response" and o["item"]["props"]["inputs"] == [f"b{i}" for i in range(1, 9)]
    assert ident({**RB840, "description": "RB-540"})["offers"][0]["item"]["props"]["inputs"] == [f"b{i}" for i in range(1, 6)]


def test_gamepad_microphone_and_second_monitor_offers():
    pad = ident(PAD)
    assert pad["name"] == "Xbox Controller" and pad["offers"][0]["item"]["type"] == "gamepad" and "device" not in pad["offers"][0]
    mic = ident(MIC)
    assert mic["offers"][0]["item"] == {"type": "microphone", "label": "Voice recording", "props": {"device": "USB Microphone"}}
    mon = ident(MON2)
    assert mon["name"] == "Monitor 2 (1920 × 1080, 144 Hz)"
    assert mon["offers"][0]["setting"] == {"path": ["settings", "window", "screen"], "value": 1}
    assert ident({"kind": "monitor", "index": 0, "width": 800, "height": 600})["offers"] == []


def test_a_labs_own_entry_wins_and_bad_entries_are_reported(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "hardware.yaml").write_text(yaml.safe_dump([
        {"id": "lab_box", "name": "Lab 3 button box", "kind": "serial", "certainty": "sure",
         "match": {"vid": "2341", "serial_number": "^75"},
         "offers": [{"label": "Button box", "buttons": 2,
                     "device": {"type": "serial_inputs", "id": "buttons", "options": {"port": "{port}", "protocol": "byte"}},
                     "item": {"type": "device_response", "label": "Button box", "props": {}}}]},
        {"name": "broken", "match": {"text": "("}},
    ]))
    r = ident(ARDUINO)
    assert r["entry"] == "lab_box" and r["certainty"] == "sure" and r["source"] == "your lab's list"
    assert r["offers"][0]["device"]["options"] == {"port": "/dev/ttyACM0", "protocol": "byte", "inputs": {1: "b1", 2: "b2"}}
    assert ident({**ARDUINO, "serial_number": "99"})["entry"] == "arduino"      # another Arduino: the built-in entry
    entries, errors = hardware_db.user_entries()
    assert len(entries) == 1 and any("not a valid pattern" in e for e in errors)


# ============================================================================ detection backends (fake providers)
class _Port:
    def __init__(self, device, vid=None, pid=None, serial_number=None, manufacturer=None, product=None, description="n/a",
                 location=None):
        self.__dict__.update(locals())


@pytest.fixture
def no_serial_writes(monkeypatch):
    """Any attempt to open a serial port fails the test: detection must be passive."""
    import serial
    opened = []

    class Refuse:
        def __init__(self, *a, **k):
            opened.append(a)
            raise AssertionError("detection opened a serial port")

    monkeypatch.setattr(serial, "Serial", Refuse)
    return opened


def test_serial_backend_reads_list_ports_and_never_opens_a_port(monkeypatch, no_serial_writes):
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports, "comports", lambda: [
        _Port("COM3", 0x0403, 0x6001, "FT1", "FTDI", None, "RB-840"),
        _Port("/dev/ttyS0"),                                     # a motherboard port: skipped on Linux
        _Port("/dev/ttyACM0", 0x2341, 0x0043, "7543", "Arduino (www.arduino.cc)", "Uno", "Arduino Uno")])
    for k in hotplug.BACKENDS:
        if k != "serial":
            monkeypatch.setitem(hotplug.BACKENDS, k, lambda *a: [])
    snap = hotplug.snapshot()
    assert "serial:0403:6001:FT1" in snap and "serial:2341:0043:7543" in snap
    assert snap["serial:0403:6001:FT1"]["vid"] == "0403"
    if sys.platform.startswith("linux"):
        assert not any(it.get("port") == "/dev/ttyS0" for it in snap.values())
    items = hotplug.scan()
    assert {it["identified"]["entry"] for it in items} == {"cedrus_rb", "arduino"}
    w = hotplug.Watcher(interval=0.01)
    w.poll()
    w.poll()
    from edge.scan import scan_all
    scan_all(timeout=0)
    assert no_serial_writes == []


def test_lsl_backend_reads_channel_names_and_units(monkeypatch):
    class XML:
        def __init__(self, kids=None, vals=None, empty=False, nxt=None):
            self.kids, self.vals, self._empty, self.nxt = kids or {}, vals or {}, empty, nxt

        def child(self, name):
            return self.kids.get(name, XML(empty=True))

        def child_value(self, name):
            return self.vals.get(name, "")

        def empty(self):
            return self._empty

        def next_sibling(self):
            return self.nxt or XML(empty=True)

    ch2 = XML(vals={"label": "Cz", "unit": "microvolts"})
    ch1 = XML(vals={"label": "Fz", "unit": "microvolts"}, nxt=ch2)

    class Info:
        def name(self): return "BioSemi"
        def type(self): return "EEG"
        def channel_count(self): return 2
        def nominal_srate(self): return 2048.0
        def source_id(self): return "bs1"
        def hostname(self): return "amp-pc"
        def desc(self): return XML(kids={"channels": XML(kids={"channel": ch1})})

    fake = types.SimpleNamespace(resolve_streams=lambda timeout: [Info()])
    monkeypatch.setitem(sys.modules, "pylsl", fake)
    got = hotplug.list_lsl(0.1)
    assert got == [{"kind": "lsl", "name": "BioSemi", "lsl_type": "EEG", "channel_count": 2, "srate": 2048.0, "source_id": "bs1",
                    "host": "amp-pc", "channels": ["Fz", "Cz"], "units": ["microvolts", "microvolts"]}]
    assert hotplug.identity(got[0]) == "lsl:bs1@amp-pc"


def test_gamepad_audio_monitor_backends(monkeypatch):
    import pyglet
    pad = types.SimpleNamespace(name="Xbox Controller", guid="030000005e04", device=object())
    joy = types.SimpleNamespace(device=types.SimpleNamespace(name="Flight stick"))
    fake_input = types.SimpleNamespace(get_controllers=lambda: [pad], get_joysticks=lambda: [joy])
    monkeypatch.setitem(sys.modules, "pyglet.input", fake_input)
    monkeypatch.setattr(pyglet, "input", fake_input, raising=False)
    got = hotplug.list_gamepads()
    assert [g["name"] for g in got] == ["Xbox Controller", "Flight stick"] and got[1]["index"] == 1

    sd = types.SimpleNamespace(query_devices=lambda: [
        {"name": "Speakers", "max_input_channels": 0, "default_samplerate": 48000},
        {"name": "USB Microphone", "max_input_channels": 1, "default_samplerate": 44100}])
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    assert hotplug.list_audio_inputs() == [{"kind": "audio", "name": "USB Microphone", "index": 1, "channels_in": 1, "rate": 44100}]

    import edge.syscheck
    monkeypatch.setattr(edge.syscheck, "screens", lambda: [{"width": 2560, "height": 1440, "x": 0, "y": 0, "rate": 60},
                                                         {"width": 1920, "height": 1080, "x": 2560, "y": 0, "rate": 144}])
    mons = hotplug.list_monitors()
    assert [m["index"] for m in mons] == [0, 1] and hotplug.identity(mons[1]) == "monitor:1:1920x1080"


def test_missing_libraries_are_skipped(monkeypatch):
    for mod in ("pylsl", "sounddevice", "tobii_research", "LabJackPython"):
        monkeypatch.setitem(sys.modules, mod, None)       # import fails
    assert hotplug.list_lsl(0) == [] and hotplug.list_audio_inputs() == [] and hotplug.list_tobii() == []


def test_gazepoint_is_only_looked_for_on_this_computer(monkeypatch):
    seen = []

    def conn(addr, timeout):
        seen.append(addr)
        raise OSError("refused")

    monkeypatch.setattr(hotplug.socket, "create_connection", conn)
    assert hotplug.list_gazepoint() == [] and seen == [("127.0.0.1", 4242)]


def test_fake_hardware_file(tmp_path, monkeypatch):
    f = tmp_path / "hw.json"
    f.write_text(json.dumps({"items": [RB840, MIC]}))
    monkeypatch.setenv(hotplug.FAKE_ENV, str(f))
    assert set(hotplug.snapshot()) == {"serial:0403:6001:FT1", "audio:USB Microphone"}
    assert set(hotplug.snapshot(("audio",))) == {"audio:USB Microphone"}
    f.write_text("not json")
    assert hotplug.snapshot() == {}


# ============================================================================ the watcher
class Plug:
    """A fake snapshot provider: the test plugs items in and out."""

    def __init__(self, *items):
        self.items = list(items)

    def __call__(self, kinds=None, **kw):
        return {hotplug.identity(it): {**it, "id": hotplug.identity(it)} for it in self.items}


def test_watcher_connect_disconnect_and_replug_keeps_identity():
    plug = Plug(MIC)
    w = hotplug.Watcher(snap=plug)
    assert w.poll() == []                         # the first look only sets what is there
    plug.items.append(RB840)
    ev = w.poll()
    assert [(e["event"], e["item"]["id"]) for e in ev] == [("connected", "serial:0403:6001:FT1")]
    assert ev[0]["item"]["identified"]["entry"] == "cedrus_rb" and ev[0]["seq"] == 1
    assert w.poll() == []                         # nothing changed
    plug.items.remove(RB840)
    ev = w.poll()
    assert [(e["event"], e["item"]["id"]) for e in ev] == [("disconnected", "serial:0403:6001:FT1")]
    plug.items.append(RB840)                      # the same box again, same socket: same identity, no "was_port"
    ev = w.poll()
    assert ev[0]["event"] == "connected" and ev[0]["item"]["id"] == "serial:0403:6001:FT1" and "was_port" not in ev[0]
    assert [e["seq"] for e in w.events] == [1, 2, 3]


def test_watcher_follows_a_renumbered_port():
    plug = Plug(RB840)
    w = hotplug.Watcher(snap=plug)
    w.poll()
    plug.items = []
    w.poll()
    plug.items = [{**RB840, "port": "COM5"}]      # plugged into another socket: Windows gives it another COM port
    ev = w.poll()
    assert ev[0]["event"] == "connected" and ev[0]["item"]["id"] == "serial:0403:6001:FT1" and ev[0]["was_port"] == "COM3"
    # the experiment still says COM3: the box is found, on its new port
    st = hotplug.presence([{"id": "buttons", "type": "serial_inputs", "options": {"port": "COM3"}}], list(w.current.values()),
                          w.ports_seen)
    assert st["buttons"]["state"] == "moved" and st["buttons"]["port_now"] == "COM5"
    # renumbered between two looks (no empty snapshot in between): a disconnect and a connect of the same identity
    plug.items = [{**RB840, "port": "COM6"}]
    ev = w.poll()
    assert [e["event"] for e in ev] == ["disconnected", "connected"] and ev[1]["was_port"] in ("COM3", "COM5")


def test_watcher_without_serial_number_uses_the_port():
    a = {"kind": "serial", "port": "COM9", "vid": "1a86", "pid": "7523"}
    assert hotplug.identity(a) == "serial:COM9"


def test_watcher_thread_and_wait():
    plug = Plug()
    w = hotplug.Watcher(snap=plug, interval=0.02).start()
    try:
        assert w.ready.wait(5)
        r = w.wait(0, timeout=0)
        assert r["events"] == [] and r["seq"] == 0
        t = threading.Timer(0.1, lambda: plug.items.append(PAD))
        t.start()
        r = w.wait(0, timeout=5)
        assert [e["event"] for e in r["events"]] == ["connected"] and r["connected"][0]["kind"] == "gamepad"
        assert w.wait(99, timeout=0)["seq"] == 1      # a client ahead of a restarted watcher starts again
    finally:
        w.stop()


def test_watcher_stops_when_nobody_asks():
    w = hotplug.Watcher(snap=Plug(), interval=0.01, idle_stop=0.05).start()
    import time
    time.sleep(0.4)
    assert not w.running


# ============================================================================ is the experiment's hardware there?
def test_presence_of_each_kind_of_device():
    items = [hotplug.describe({**it, "id": hotplug.identity(it)}) for it in (RB840, MIC, BIOSEMI,
             {"kind": "gazepoint", "host": "127.0.0.1", "tcp_port": 4242}, {"kind": "parallel", "port": "/dev/parport0"})]
    st = hotplug.presence([
        {"id": "buttons", "type": "serial_inputs", "options": {"port": "COM3"}},
        {"id": "trig", "type": "ttl_serial", "options": {"port": "COM4"}},
        {"id": "eeg", "type": "lsl_inlet", "options": {"name": "BioSemi"}},
        {"id": "eeg2", "type": "lsl_inlet", "options": {"stream_type": "NIRS"}},
        {"id": "et", "type": "gazepoint"},
        {"id": "far", "type": "gazepoint", "options": {"host": "10.0.0.5"}},
        {"id": "tobii", "type": "tobii"},
        {"id": "vk", "type": "voice_key", "options": {"device": "usb micro"}},
        {"id": "lpt", "type": "parallel_port", "options": {"address": "/dev/parport0"}},
        {"id": "lptwin", "type": "parallel_port", "options": {"address": "0x378"}},
        {"id": "bp", "type": "trigger_adapter", "options": {"target": "brainproducts", "port": "COM3"}},
        {"id": "sim", "type": "sim_eeg"},
        {"id": "lj", "type": "labjack"},
    ], items)
    want = {"buttons": "connected", "trig": "missing", "eeg": "connected", "eeg2": "missing", "et": "connected",
            "far": "unknown", "tobii": "missing", "vk": "connected", "lpt": "connected", "lptwin": "unknown",
            "bp": "connected", "sim": "unknown", "lj": "missing"}
    assert {k: v["state"] for k, v in st.items()} == want
    assert st["buttons"]["item"] == "serial:0403:6001:FT1" and "RB-840" in st["buttons"]["label"]
    # an empty port: fine when there is exactly one serial port
    assert hotplug.presence([{"id": "b", "type": "serial_inputs"}], items)["b"]["state"] == "connected"


# ============================================================================ adding a suggestion: valid and dry-runs
def _stroop(tmp_path):
    d = tmp_path / "exps"
    shutil.copytree(ROOT / "examples" / "stroop", d / "stroop")
    return d, yaml.safe_load((d / "stroop" / "stroop.yaml").read_text())


@pytest.mark.parametrize("item, pick", [(RB840, 0), (RB840, 1), (ARDUINO, 1), (ARDUINO, 2), (MIC, 1), (PAD, 0), (MON2, 0),
                                         (BIOSEMI, 0), ({"kind": "serial", "port": "COM7", "description": "TriggerBox"}, 0),
                                         ({"kind": "labjack", "model": "U3"}, 0), ({"kind": "parallel", "port": "/dev/parport0"}, 1)])
def test_adding_a_suggested_device_gives_a_valid_experiment_that_dry_runs(tmp_path, item, pick):
    from edge.builder.server import BuilderApp
    from edge.model import Experiment
    root, doc = _stroop(tmp_path)
    offer = ident(item)["offers"][pick]
    added = hardware_db.apply_offer(doc, json.loads(json.dumps(offer)), screen="trial")   # through JSON, like the builder
    assert added
    if offer.get("item") and offer.get("device") and offer["item"]["type"] == "device_response":
        comp = next(c for c in doc["routines"]["trial"]["components"] if c["id"] == added["item"][1])
        assert comp["device"] == added["device"]
    exp = Experiment.from_dict(copy.deepcopy(doc), base_dir=root / "stroop")
    errors = [i for i in exp.validate() if i.level == "error"]
    assert not errors, errors
    res = BuilderApp(root).dry_run(doc, "stroop/stroop.yaml", {"participant": "t1"})
    assert res["ok"], res.get("problem") or res.get("issues")


def test_the_second_monitor_becomes_the_participants_monitor(tmp_path):
    _, doc = _stroop(tmp_path)
    hardware_db.apply_offer(doc, ident(MON2)["offers"][0])
    assert doc["settings"]["window"]["screen"] == 1


# ============================================================================ the builder endpoints
@pytest.fixture
def builder(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer
    from edge.builder.server import BuilderApp, make_handler
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps([MIC]))
    monkeypatch.setenv(hotplug.FAKE_ENV, str(hw))
    monkeypatch.setattr(hotplug, "POLL_SECONDS", 0.05)
    app = BuilderApp(tmp_path)
    app.hardware_watcher = hotplug.Watcher(interval=0.05, idle_stop=60)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", hw, app
    httpd.shutdown()
    app.hardware_watcher.stop()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_events_endpoint_long_polls_connect_and_disconnect(builder):
    base, hw, app = builder
    code, r = _get(base + "/api/hardware/events")
    assert code == 200 and r["events"] == [] and [it["kind"] for it in r["connected"]] == ["audio"]
    since = r["seq"]
    threading.Timer(0.2, lambda: hw.write_text(json.dumps([MIC, RB840]))).start()
    code, r = _get(base + f"/api/hardware/events?since={since}&wait=10")
    assert code == 200 and [(e["event"], e["item"]["identified"]["name"]) for e in r["events"]] == \
        [("connected", "Cedrus RB-840 response pad")]
    since = r["seq"]
    code, st = _post(base + "/api/hardware/status", {"devices": [{"id": "buttons", "type": "serial_inputs",
                                                                  "options": {"port": "COM3"}}]})
    assert code == 200 and st["status"]["buttons"]["state"] == "connected"
    hw.write_text(json.dumps([MIC]))
    code, r = _get(base + f"/api/hardware/events?since={since}&wait=10")
    assert [e["event"] for e in r["events"]] == ["disconnected"]
    code, st = _post(base + "/api/hardware/status", {"devices": [{"id": "buttons", "type": "serial_inputs",
                                                                  "options": {"port": "COM3"}}]})
    assert st["status"]["buttons"]["state"] == "missing"
    code, now = _get(base + "/api/hardware/now")
    assert code == 200 and now["fake"] is True and now["connected"][0]["identified"]["entry"] == "microphone"
    # a waiting request comes back empty after `wait`
    code, r = _get(base + f"/api/hardware/events?since={r['seq']}&wait=0.2")
    assert code == 200 and r["events"] == []


def test_endpoints_are_behind_the_guard_and_check_their_input(builder):
    base, hw, app = builder
    port = base.rsplit(":", 1)[1]
    assert _get(base + "/api/hardware/events", {"Host": "evil.example:" + port})[0] == 403
    assert _get(base + "/api/hardware/now", {"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})[0] == 403
    assert _post(base + "/api/hardware/status", {"devices": []}, {"Origin": "http://evil.example"})[0] == 403
    assert _post(base + "/api/hardware/status", {"devices": []}, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    req = urllib.request.Request(base + "/api/hardware/status", data=b'{"devices": []}', method="POST",
                                 headers={"Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 415
    assert _post(base + "/api/hardware/status", {})[0] == 400
    assert _post(base + "/api/hardware/status", {"devices": "x"})[0] == 400
    assert _get(base + "/api/hardware/events?since=abc")[0] == 400
    assert _get(base + "/api/hardware/events?since=nan")[0] == 400
    assert _get(base + "/api/hardware/nothing")[0] == 404
    # Identify only for devices recognised as Cedrus
    assert _post(base + "/api/hardware/identify", {"id": "audio:USB Microphone"})[0] == 400
    assert _post(base + "/api/hardware/identify", {"id": "nope"})[0] == 400
    hw.write_text(json.dumps([MIC, RB840]))
    since = _get(base + "/api/hardware/events")[1]["seq"]
    _get(base + f"/api/hardware/events?since={max(0, since - 1)}&wait=5")
    for _ in range(50):
        if "serial:0403:6001:FT1" in app.hardware_watcher.current:
            break
        import time
        time.sleep(0.05)
    code, r = _post(base + "/api/hardware/identify", {"id": "serial:0403:6001:FT1"})
    assert code == 200 and r["ok"] and r["fake"]


# ============================================================================ the session monitor reports an unplugged device
def test_monitor_reports_an_unplugged_device(tmp_path, monkeypatch):
    from edge.monitor import Monitor
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps([RB840]))
    monkeypatch.setenv(hotplug.FAKE_ENV, str(hw))
    spec = types.SimpleNamespace(id="buttons", type="serial_inputs", options={"port": "COM3"})
    sim = types.SimpleNamespace(id="eye", type="tobii", options={})
    session = types.SimpleNamespace(
        exp=types.SimpleNamespace(measures=None, devices=[spec, sim]),
        devices={"buttons": types.SimpleNamespace(type_name="serial_inputs"),
                 "eye": types.SimpleNamespace(type_name="sim_eyetracker")})      # simulated in this session: not checked
    sent = []
    m = Monitor(session, emit=sent.append, hardware_interval=1)
    assert [s["id"] for s in m.hardware_specs()] == ["buttons"]
    assert m.hardware_check() is None                   # all there at the start: nothing to say
    hw.write_text("[]")
    ev = m.hardware_check()
    assert ev["type"] == "hardware" and ev["missing"] == ["buttons"] and ev["devices"]["buttons"]["state"] == "missing"
    assert m.hardware_check() is None                   # only when it changes
    hw.write_text(json.dumps([RB840]))
    ev = m.hardware_check()
    assert ev["missing"] == [] and ev["devices"]["buttons"]["state"] == "connected"


# ============================================================================ CLI and MCP
def test_edge_scan_shows_the_identification(tmp_path, monkeypatch, capsys):
    from edge.cli import main, scan_event_line
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps([RB840, ARDUINO, MIC, MON2]))
    monkeypatch.setenv(hotplug.FAKE_ENV, str(hw))
    assert main(["scan", "--timeout", "0"]) == 0
    out = capsys.readouterr().out
    assert "probably Cedrus RB-840 response pad" in out
    assert "{id: buttons, type: serial_inputs, options: {port: COM3, protocol: cedrus" in out
    assert "What does this Arduino do? It could be:" in out and "Trigger output" in out
    assert "Record spoken answers: add a Voice recording item" in out
    assert "Show the experiment on this monitor: set settings.window.screen: 1" in out
    assert main(["scan", "--json", "--timeout", "0"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["serial_ports"][0]["what"] == "Cedrus RB-840 response pad" and data["serial_ports"][0]["suggested"]["type"] == "serial_inputs"
    it = hotplug.describe({**RB840, "id": hotplug.identity(RB840)})
    line = scan_event_line({"event": "connected", "time": 0, "item": it, "was_port": "COM1"})
    assert "+ connected" in line and "probably Cedrus RB-840 response pad, on COM3" in line and "(was on COM1)" in line
    assert "add as: Response box | Trigger output through the pad" in line
    assert "- disconnected" in scan_event_line({"event": "disconnected", "time": 0, "item": it})


def test_mcp_scan_hardware_returns_identifications_and_additions(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import asyncio
    from edge.mcp_server import create_server
    hw = tmp_path / "hw.json"
    hw.write_text(json.dumps([RB840, ARDUINO]))
    monkeypatch.setenv(hotplug.FAKE_ENV, str(hw))
    server = create_server(tmp_path)
    res = asyncio.run(server.call_tool("scan_hardware", {"timeout": 0}))
    data = res[1] if isinstance(res, tuple) else json.loads(res[0].text)
    adds = {a["what"]: a for a in data["suggested_additions"]}
    assert adds["Cedrus RB-840 response pad"]["add"]["device"]["type"] == "serial_inputs"
    assert adds["Arduino board"]["add"] is None and len(adds["Arduino board"]["choices"]) == 3
