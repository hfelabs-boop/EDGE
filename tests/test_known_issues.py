"""Known issues on lab computers: the computer check, runtime safeguards and experiment checks."""

import json
import struct
import zlib
from pathlib import Path

import pytest

from edge import syscheck
from edge.backends.pyglet_backend import refresh_warnings
from edge.model import Experiment


def _png(path: Path) -> None:
    raw = b"\x00" + b"\x00\x00\x00"

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ============================================================================ computer check
def test_doctor_runs_anywhere_and_never_raises(capsys):
    from edge.cli import main
    checks = syscheck.run_checks()
    assert all(c.level in ("ok", "info", "warning", "error") for c in checks)
    assert any(c.id == "timer" for c in checks)
    assert main(["doctor", "examples/stroop/stroop.yaml"]) in (0, 1)
    assert "EDGE computer check" in capsys.readouterr().out
    assert main(["doctor", "--json"]) in (0, 1)
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_battery_power_plan_and_usb_suspend(monkeypatch):
    monkeypatch.setattr(syscheck, "on_battery", lambda: True)
    c = syscheck.check_power()[0]
    assert c.id == "battery" and c.level == "warning" and "charger" in c.fix
    monkeypatch.setattr(syscheck, "usb_selective_suspend", lambda: True)
    assert syscheck.check_usb_suspend(True)[0].level == "warning"
    assert syscheck.check_usb_suspend(False)[0].level == "info"
    assert syscheck.check_usb_suspend(True)[0].fixable
    monkeypatch.setattr(syscheck, "usb_selective_suspend", lambda: None)
    assert syscheck.check_usb_suspend(True) == []


def test_display_driver_and_screens():
    bad = syscheck.check_display_driver(["Microsoft Basic Display Adapter"])
    assert bad[0].level == "error" and "driver" in bad[0].fix
    assert syscheck.check_display_driver(["llvmpipe (LLVM 15, 256 bits)"])[0].level == "error"
    assert syscheck.check_display_driver(["NVIDIA GeForce RTX 3060"])[0].level == "ok"
    one = [{"width": 1920, "height": 1080, "x": 0, "y": 0, "rate": 60}]
    two = one + [{"width": 2560, "height": 1440, "x": 1920, "y": 0, "rate": 144}]
    ids = lambda cs: {c.id: c for c in cs}
    c = ids(syscheck.check_screens({"screen": 2}, two, fso=True))
    assert c["screen_index"].level == "error"
    c = ids(syscheck.check_screens({"fullscreen": True, "size": [1280, 720]}, one, fso=True))
    assert c["resolution"].level == "warning" and "1920×1080" in c["resolution"].fix
    c = ids(syscheck.check_screens({"fullscreen": True, "size": [1920, 1080]}, one, fso=True))
    assert "resolution" not in c
    if syscheck.IS_WIN:
        assert ids(syscheck.check_screens({}, two, fso=False))["fullscreen_optimizations"].fixable
    assert ids(syscheck.check_screens({}, one, dpi=1.5))["dpi"].title == "Display scaling is 150%"


def test_serial_latency_and_keyboard():
    cs = syscheck.check_serial([{"port": "COM5", "latency_ms": 16}, {"port": "COM6", "latency_ms": 1}], used={"COM5"})
    assert cs[0].level == "warning" and "16 ms" in cs[0].title and cs[1].level == "ok"
    assert syscheck.check_serial([{"port": "COM5", "latency_ms": 16}], used={"COM9"})[0].level == "info"
    assert syscheck.check_keyboard(0x11)[0].level == "warning"      # Japanese IME
    assert syscheck.check_keyboard(0x09) == []                       # English
    with pytest.raises(ValueError):
        syscheck.apply_fix("battery")


def test_refresh_rate_warnings():
    assert refresh_warnings(60.0, 0.05, None) == []
    assert "not the 75 Hz" in refresh_warnings(60.0, 0.05, 75)[0]
    assert refresh_warnings(59.94, 0.05, 60) == []                   # within 2 %
    assert "G-Sync" in refresh_warnings(144.0, 3.2, None)[0]
    assert "light sensor" in refresh_warnings(240.0, 0.1, None)[0]
    assert refresh_warnings(1600.0, 0.1, 60) == []                   # vsync off is reported elsewhere


# ============================================================================ runtime safeguards
def test_session_records_warnings_display_and_focus(tmp_path):
    from edge.engine import run_experiment
    from edge.report import analyze_session
    doc = {"name": "f", "settings": {"window": {"size": [400, 300]}},
           "routines": {"a": {"components": [{"id": "t", "type": "text", "text": "x", "duration": 0.2}]}}, "flow": ["a"]}
    s = run_experiment(Experiment.from_dict(doc, base_dir=tmp_path), dry_run=True, data_dir=str(tmp_path / "d"),
                       log=lambda *a: None)
    meta = json.loads((Path(s["data_dir"]) / "session.json").read_text())
    assert meta["warnings"] == [] and "display" in meta and meta["system_checks"] == []   # dry runs skip the computer check
    meta["warnings"] = ["the experiment window lost keyboard focus 2 time(s) (first 3.0 s into the session)"]
    meta["system_checks"] = [{"id": "battery", "level": "warning", "title": "Running on battery", "fix": "Plug in"}]
    (Path(s["data_dir"]) / "session.json").write_text(json.dumps(meta))
    v = "\n".join(analyze_session(s["data_dir"])["verdict"])
    assert "lost keyboard focus 2 time(s)" in v and "COMPUTER: Running on battery → Plug in" in v


def test_sounds_are_prepared_before_their_onset(tmp_path):
    from edge.backends.headless import HeadlessBackend
    from edge.engine import run_experiment
    calls = []
    orig = HeadlessBackend.preload_sound

    def spy(self, source, **kw):
        calls.append(("preload", source))
        return orig(self, source, **kw)
    HeadlessBackend.preload_sound = spy
    try:
        doc = {"name": "s", "routines": {"a": {"components": [{"id": "beep", "type": "sound", "sound": 440, "duration": 0.2}]}},
               "flow": ["a", "a"]}
        run_experiment(Experiment.from_dict(doc, base_dir=tmp_path), dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    finally:
        HeadlessBackend.preload_sound = orig
    assert calls == [("preload", 440), ("preload", 440)]


def test_serial_reconnect_and_low_latency():
    import threading
    from edge.devices import create_device
    from edge.devices.inputs import low_latency, reconnect

    class S:
        def set_low_latency_mode(self, on):
            self.on = on
    s = S()
    assert low_latency(s) and s.on and not low_latency(object())
    dev = create_device("sim_inputs", "box")
    tries = []

    def opener():
        tries.append(1)
        if len(tries) < 3:
            raise OSError("not yet")
    assert reconnect(dev, opener, threading.Event(), every=0.001, give_up=2)
    assert len(tries) == 3 and dev.errors[-1] == "box: reconnected"
    assert not reconnect(dev, lambda: (_ for _ in ()).throw(OSError()), threading.Event(), every=0.001, give_up=0.01)


def test_monitor_does_not_call_event_streams_silent():
    from edge.devices.base import StreamInfo
    from edge.monitor import Monitor

    class Dev:
        type_name, errors = "box", []
        streams = {"inputs": StreamInfo("inputs", ["input"], 0.0)}
        n_samples = {"inputs": 0}

    class Sess:
        devices = {"box": Dev()}
        exp = type("E", (), {"measures": None})()
    m = Monitor(Sess(), emit=lambda e: None)
    m.t0 -= 10
    assert m.device_health()["box"]["streams"]["inputs"]["status"] == "events"


# ============================================================================ experiment checks
def _doc(components, flow=None, settings=None):
    return {"name": "c", "settings": settings or {}, "routines": {"a": {"components": components}}, "flow": flow or ["a"]}


def test_durations_that_are_not_whole_frames(tmp_path):
    def msgs(comps, settings=None):
        return [str(i) for i in Experiment.from_dict(_doc(comps, settings=settings), base_dir=tmp_path).validate()
                if "frames at" in i.message]
    m = msgs([{"id": "f", "type": "fixation", "duration": 0.025}])
    assert len(m) == 1 and "1.5 frames at 60 Hz (assumed)" in m[0] and "16.7 or 33.3 ms" in m[0] and "duration_frames: 2" in m[0]
    assert msgs([{"id": "f", "type": "fixation", "duration": 0.05}]) == []          # 3 frames
    assert msgs([{"id": "f", "type": "fixation", "duration": 0.6}]) == []           # long: rounding doesn't matter
    assert msgs([{"id": "k", "type": "keyboard", "duration": 0.025}]) == []         # not shown on screen
    assert msgs([{"id": "f", "type": "fixation", "duration": 0.025}], {"window": {"refresh_rate": 120}}) == []   # 3 frames
    assert msgs([{"id": "f", "type": "fixation", "duration": 0.025, "duration_frames": 2}]) == []


def test_missing_absolute_and_compressed_files(tmp_path):
    _png(tmp_path / "images" / "cat.png")
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "beep.mp3").write_bytes(b"x")

    def issues(comps, flow=None):
        return [str(i) for i in Experiment.from_dict(_doc(comps, flow), base_dir=tmp_path).validate() if i.level != "info"]
    assert issues([{"id": "p", "type": "image", "image": "images/cat.png", "duration": 1}]) == []
    m = issues([{"id": "p", "type": "image", "image": "images/cat.jpg", "duration": 1}])
    assert "picture not found: images/cat.jpg" in m[0] and "did you mean images/cat.png" in m[0]
    m = issues([{"id": "p", "type": "image", "image": str(tmp_path / "images" / "cat.png"), "duration": 1}])
    assert any("absolute path" in x for x in m) and not any("not found" in x for x in m)
    m = issues([{"id": "s", "type": "sound", "sound": "sounds/beep.mp3", "duration": 1}])
    assert len(m) == 1 and "compressed audio (.mp3)" in m[0] and "WAV" in m[0]
    assert issues([{"id": "s", "type": "sound", "sound": 440, "duration": 1}]) == []
    flow = [{"loop": "L", "conditions": [{"pic": "images/cat.png"}, {"pic": "images/dog.png"}, {"pic": "images/cow.png"}],
             "children": ["a"]}]
    m = issues([{"id": "p", "type": "image", "image": "$pic", "duration": 1}], flow)
    assert len(m) == 1 and "2 of 3 pictures named in trial-list column 'pic' not found: images/dog.png, images/cow.png" in m[0]
    assert issues([{"id": "p", "type": "image", "image": "$f'images/{x}.png'", "duration": 1}],
                  [{"loop": "L", "conditions": [{"x": "cat"}], "children": ["a"]}]) == []   # a formula: checked at run time


def test_wizard_picture_experiments_get_placeholder_pictures(tmp_path):
    from edge.storage import save_document
    from edge.wizard import build_experiment, write_placeholders
    doc = build_experiment({"stimulus": {"kind": "picture"}})
    save_document(tmp_path / "p.yaml", doc)
    assert any("not found" in i.message for i in Experiment.load(tmp_path / "p.yaml").validate())
    made = write_placeholders(doc, tmp_path)
    assert made and all((tmp_path / m).read_bytes()[:4] == b"\x89PNG" for m in made)
    assert not [i for i in Experiment.load(tmp_path / "p.yaml").validate() if i.level == "error"]
    assert write_placeholders(doc, tmp_path) == []        # never overwrites


def test_mcp_and_builder_expose_the_check(tmp_path):
    import asyncio
    pytest.importorskip("mcp")
    from edge.builder.server import BuilderApp, make_handler  # noqa: F401  (endpoint is exercised below)
    from edge.mcp_server import create_server
    mcp = create_server(tmp_path)
    r = asyncio.run(mcp.call_tool("check_system", {}))
    content = r[0] if isinstance(r, tuple) else r
    out = json.loads(content[0].text)
    assert "checks" in out and out["fixed"] == []
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        assert "checks" in json.loads(urllib.request.urlopen(base + "/api/system_check").read())
        req = urllib.request.Request(base + "/api/system_fix", data=json.dumps({"id": "battery"}).encode(),
                                     headers={"Content-Type": "application/json"})
        res = json.loads(urllib.request.urlopen(req).read())
        assert res["ok"] is False and "can't be fixed" in res["error"]
    finally:
        httpd.shutdown()


def test_known_issues_page_is_in_the_help():
    from edge import help as hp
    text = hp.read_topic("KNOWN_ISSUES")
    for words in ("edge doctor", "USB selective suspend", "fullscreen optimizations", "latency timer", "G-Sync", "DirectSound"):
        assert words in text
    assert "KNOWN_ISSUES.md" in (Path(hp.__file__).parent.parent / "docs" / "README.md").read_text()
