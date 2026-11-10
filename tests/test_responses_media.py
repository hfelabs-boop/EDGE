"""Spoken responses (microphone), touchscreens (mouse taps, swipes, multi-touch) and gamepads."""

from __future__ import annotations

import csv
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import audio
from edge.backends.base import InputEvent
from edge.backends.headless import HeadlessBackend
from edge.engine import Runner, run_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant
from edge.runtime import Session


def _exp(tmp_path, routines, flow=None, devices=None, conditions=None):
    doc = {"name": "media", "settings": {"window": {"size": [1280, 720], "units": "px"}},
           "devices": devices or [], "routines": routines,
           "flow": flow or [{"loop": "trials", "conditions": conditions or [{"w": "cat"}, {"w": "dog"}],
                             "children": list(routines)}]}
    return Experiment.from_dict(doc, base_dir=tmp_path)


def _dry(exp, tmp_path, **kw):
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None, **kw)
    root = Path(s["data_dir"])
    rows = [json.loads(line) for line in (root / "trials.jsonl").read_text().splitlines() if line.strip()]
    return root, rows, s


def _issues(exp):
    return [(i.level, i.message) for i in exp.validate()]


# ============================================================================ microphone
def test_wav_roundtrip_and_the_voice_key_detector_on_a_simulated_recording(tmp_path):
    x = audio.simulate_recording(2.0, 44100, onset=0.5, length=0.6, seed=3)
    on, off = audio.detect_speech(x, 44100, -30, 15, 300)
    assert 0.5 <= on < 0.515 and 1.09 < off < 1.12
    p = audio.write_wav(tmp_path / "a.wav", x, 44100, channels=2)
    sr, ch, mono = audio.read_wav(p)
    assert (sr, ch, len(mono)) == (44100, 2, len(x))
    assert audio.detect_speech(mono, sr, -30, 15, 300) == pytest.approx((on, off), abs=1e-3)
    silent = audio.simulate_recording(1.0, 16000, onset=None)
    assert audio.detect_speech(silent, 16000) == (None, None)
    # the same detector as the voice key device
    from edge.devices.inputs import VoiceDetector
    det = VoiceDetector(44100, -30, 0.015, 0.3)
    events = det.process(x, 0.0)
    assert events[0][1] is True and events[0][0] == pytest.approx(on, abs=1e-6)


def test_microphone_dry_run_saves_a_wav_per_trial_and_times_speech_from_the_recording(tmp_path):
    exp = _exp(tmp_path, {"naming": {"components": [
        {"id": "word", "type": "text", "text": "$w", "duration": 2.0},
        {"id": "voice", "type": "microphone", "duration": 2.0, "samplerate": 16000, "channels": 2}]}})
    assert not [i for i in _issues(exp) if i[0] != "info"]
    root, rows, _ = _dry(exp, tmp_path)
    assert len(rows) == 2
    for r in rows:
        f = root / r["voice.file"]
        assert r["voice.file"] == f"audio/{r['routine_index']:04d}_naming_voice.wav" and f.is_file()
        sr, ch, mono = audio.read_wav(f)
        assert (sr, ch) == (16000, 2) and abs(len(mono) / sr - r["voice.duration"]) < 0.01
        assert r["voice.duration"] == pytest.approx(2.0, abs=0.02)
        assert r["voice.source"] == "recording" and 0.12 < r["voice.rt"] < 1.9
        assert r["voice.offset"] is None or r["voice.offset"] > r["voice.rt"]
    # the manifest for transcription, written with the session
    with (root / "audio" / "manifest.csv").open(encoding="utf-8-sig") as fh:
        man = list(csv.DictReader(fh))
    assert [m["file"] for m in man] == [r["voice.file"] for r in rows]
    assert {m["w"] for m in man} == {"cat", "dog"} and all(m["exists"] == "1" and m["transcript"] == "" for m in man)
    # the trial tables list the files
    with (root / "trials_wide.csv").open(encoding="utf-8-sig") as fh:
        wide = list(csv.DictReader(fh))
    assert any(k.endswith("voice.file") for k in wide[0]) and all(
        any(str(v).startswith("audio/") for v in row.values()) for row in wide)
    # the recording plan / data dictionary know the columns
    dd = (root / "data_dictionary.csv").read_text(encoding="utf-8-sig")
    assert "voice.file" in dd and "WAV" in dd


def test_microphone_with_a_voice_key_and_stop_after_speech(tmp_path):
    exp = _exp(tmp_path, {"naming": {"components": [
        {"id": "voice", "type": "microphone", "stop_after_speech": True, "end_routine": True, "release_ms": 200}]}},
        devices=[{"id": "vk", "type": "voice_key"}])
    assert not [i for i in _issues(exp) if i[0] != "info"]
    root, rows, s = _dry(exp, tmp_path)
    for r in rows:
        assert r["voice.source"] == "voice_key"
        # stopped by itself soon after speaking (no duration was given)
        assert r["voice.rt"] < r["voice.offset"] < r["voice.duration"] < r["voice.offset"] + 0.6
        assert (root / r["voice.file"]).is_file()
    inputs = (root / "streams" / "vk.inputs.csv").read_text()
    assert inputs.count("voice,1") == 2 and s["simulated_devices"] == {"vk": "sim_inputs"}


def test_microphone_without_a_voice_key_stops_after_speech_from_the_recording(tmp_path):
    exp = _exp(tmp_path, {"say": {"components": [
        {"id": "voice", "type": "microphone", "stop_after_speech": True, "end_routine": True, "duration": 5,
         "response_marker": "spoke"}]}})
    root, rows, _ = _dry(exp, tmp_path)
    for r in rows:
        assert r["voice.source"] == "recording" and r["voice.duration"] < 2.5
        assert r["voice.offset"] is not None and r["voice.offset"] - r["voice.rt"] > 0.3
    labels = [json.loads(line)["label"] for line in (root / "events.jsonl").read_text().splitlines()]
    assert labels.count("spoke") == 2


def test_microphone_validation(tmp_path):
    def issues(props, routine_extra=None, devices=None, duration=None):
        comp = {"id": "mic", "type": "microphone", **props}
        if duration is not None:
            comp["duration"] = duration
        r = {"components": [comp] + (routine_extra or [])}
        return _issues(_exp(tmp_path, {"r": r}, devices=devices))

    assert not [i for i in issues({}, duration=3) if i[0] != "info"]
    assert any(l == "error" and "sample rate" in m for l, m in issues({"samplerate": 100}, duration=3))
    assert any(l == "error" and "'channels' must be one of" in m for l, m in issues({"channels": 5}, duration=3))
    assert any(l == "error" and "no device called 'vk'" in m for l, m in issues({"voice_key": "vk"}, duration=3))
    assert any(l == "error" and "not a voice key" in m for l, m in issues(
        {"voice_key": "box"}, duration=3, devices=[{"id": "box", "type": "serial_inputs"}]))
    assert any(l == "error" and "'release_ms'" in m for l, m in issues({"release_ms": 0}, duration=3))
    forever = issues({})
    assert any(l == "warning" and "record for ever" in m for l, m in forever)
    assert not any("for ever" in m for _, m in issues({"stop_after_speech": True}))
    # another item ends the screen: fine
    assert not any("for ever" in m for _, m in issues({}, [{"id": "k", "type": "keyboard", "end_routine": True}]))
    assert any("closes before" in m for _, m in issues({}, duration=0))


def test_microphone_needs_sounddevice_for_a_real_session(tmp_path, monkeypatch):
    monkeypatch.setattr(audio, "have_sounddevice", lambda: False)
    exp = _exp(tmp_path, {"r": {"components": [{"id": "mic", "type": "microphone", "duration": 1}]}})
    be = HeadlessBackend(realtime=True)        # a screenless real session: no virtual participant
    session = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    from edge.diagnostics import ExperimentError
    with pytest.raises(ExperimentError) as e:
        Runner(session).run()
    assert "pip install edge-experiments[audio]" in str(e.value.report)
    from edge.syscheck import check_software
    assert any(c.id == "software:microphone" and c.level == "error" for c in check_software(exp))


def test_export_audio_manifest_cli(tmp_path, capsys):
    exp = _exp(tmp_path, {"naming": {"components": [{"id": "voice", "type": "microphone", "duration": 1.0,
                                                    "samplerate": 8000}]}})
    _dry(exp, tmp_path)
    _dry(exp, tmp_path)
    from edge.cli import main
    main(["export", str(tmp_path / "data"), "--formats", "csv", "--include-dry-runs", "--audio-manifest",
          "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "4 recordings to transcribe" in out
    with (tmp_path / "out" / "audio_manifest.csv").open(encoding="utf-8-sig") as fh:
        man = list(csv.DictReader(fh))
    assert len(man) == 4 and all(Path(m["path"]).is_file() for m in man)
    assert len({m["session_folder"] for m in man}) == 2


# ============================================================================ gamepad
def test_gamepad_dry_run_buttons_axes_and_track(tmp_path):
    exp = _exp(tmp_path, {
        "pad": {"components": [{"id": "gp", "type": "gamepad", "buttons": ["lb", "rb"], "correct": "$side",
                                "end_routine": True, "track": True}]},
        "stick": {"components": [{"id": "gs", "type": "gamepad", "axis_threshold": 0.5,
                                  "buttons": ["stick_left", "stick_right"], "correct": "stick_left",
                                  "end_routine": True}]}},
        conditions=[{"side": "lb"}, {"side": "rb"}, {"side": "lb"}])
    assert not [i for i in _issues(exp) if i[0] != "info"]
    root, rows, _ = _dry(exp, tmp_path, virtual_participant=VirtualParticipant(accuracy=1.0, seed=1))
    pad = [r for r in rows if r["routine"] == "pad"]
    stick = [r for r in rows if r["routine"] == "stick"]
    assert [r["gp.button"] for r in pad] == [r["side"] for r in pad] and all(r["gp.corr"] == 1 for r in pad)
    assert all(0.1 < r["gp.rt"] < 3 and r["gp.gamepad"] == "simulated gamepad" for r in pad)
    assert all(len(r["gp.path"]) > 5 and len(r["gp.path"][0]) == 5 for r in pad)
    assert any(any(p[1] != 0 for p in r["gp.path"]) for r in pad)            # the stick moved
    assert all(r["gs.button"] == "stick_left" and r["gs.axes"]["lx"] <= -0.5 for r in stick)


def test_gamepad_events_deadzone_threshold_and_key_stand_ins(tmp_path):
    exp = _exp(tmp_path, {"r": {"components": [
        {"id": "gp", "type": "gamepad", "axis_threshold": 0.6, "deadzone": 0.2, "keys": {"f": "a"},
         "end_routine": True, "duration": 3}]}}, flow=["r"])
    be = HeadlessBackend()
    session = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    t0 = be.clock()
    be.move_stick("ry", 0.15, t0 + 0.2)          # inside the deadzone: recorded as 0
    be.move_stick("lx", 0.5, t0 + 0.3)           # not far enough
    be.gamepad("x", t0 + 0.35, index=1)          # another gamepad, but any counts
    be.move_stick("lx", 0.7, t0 + 0.5)
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["gp.button"] == "x" and row["gp.time"] == pytest.approx(t0 + 0.35, abs=0.02)
    # a keyboard stand-in
    exp2 = _exp(tmp_path, {"r": {"components": [{"id": "gp", "type": "gamepad", "buttons": ["a"], "keys": {"f": "a"},
                                                 "gamepad": 0, "end_routine": True, "duration": 3}]}}, flow=["r"])
    be = HeadlessBackend()
    session = Session(exp2, be, data_dir=tmp_path / "d2", log=lambda *a: None)
    be.gamepad("a", be.clock() + 0.2, index=1)     # not gamepad 0: ignored
    be.press("f", be.clock() + 0.4)
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["gp.button"] == "a" and row["gp.gamepad"] == "keyboard" and 0.35 < row["gp.rt"] < 0.45
    # stick threshold with the deadzone
    exp3 = _exp(tmp_path, {"r": {"components": [{"id": "gp", "type": "gamepad", "axis_threshold": 0.6, "deadzone": 0.2,
                                                 "end_routine": True, "duration": 3}]}}, flow=["r"])
    be = HeadlessBackend()
    session = Session(exp3, be, data_dir=tmp_path / "d3", log=lambda *a: None)
    t0 = be.clock()
    be.move_stick("ry", 0.15, t0 + 0.2)
    be.move_stick("ly", -0.5, t0 + 0.3)
    be.move_stick("ly", -0.8, t0 + 0.5)
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["gp.button"] == "stick_down" and row["gp.axes"] == {"ry": 0.0, "ly": -0.8}


def test_gamepad_validation(tmp_path):
    def issues(props):
        return _issues(_exp(tmp_path, {"r": {"components": [{"id": "gp", "type": "gamepad", "duration": 2, **props}]}}))
    assert not [i for i in issues({"buttons": ["a", "button3", "up"], "correct": "a"}) if i[0] != "info"]
    msgs = [m for _, m in issues({"buttons": ["A_button", "lbb"]})]
    assert any("'lbb' isn't a gamepad button" in m for m in msgs)
    assert any("sticks only count with an axis threshold" in m for _, m in issues({"buttons": ["stick_left"]}))
    assert any(l == "error" and "beyond the deadzone" in m for l, m in issues({"axis_threshold": 0.1, "deadzone": 0.2}))
    assert any(l == "error" and "'deadzone' must be between" in m for l, m in issues({"deadzone": 2}))
    assert any("not a key name" in m for _, m in issues({"keys": {"Enter": "a"}}))


def test_gamepad_hub_maps_pyglet_controllers_and_joysticks():
    from edge.backends.gamepads import GamepadHub

    class Vec2:
        def __init__(self, x, y):
            self.x, self.y = x, y

    class Pad:
        name = "Xbox Controller"

    class Stick:
        name = "Flight stick"

    got: list[InputEvent] = []
    hub = GamepadHub(got.append, clock=lambda: 5.0)
    pad, joy = Pad(), Stick()
    hub.on_button_press(pad, "leftshoulder")
    hub.on_button_release(pad, "leftshoulder")
    hub.on_stick_motion(pad, "leftstick", Vec2(-0.5, 0.25))        # pyglet 2.1
    hub.on_stick_motion(pad, "rightstick", 0.1, -0.9)              # pyglet 2.0
    hub.on_trigger_motion(pad, "righttrigger", 0.8)
    hub.on_dpad_motion(pad, Vec2(0, 1))
    hub.on_joybutton_press(joy, 0)
    hub.on_joyaxis_motion(joy, "y", 0.5)                           # down on a joystick
    hub.on_joyhat_motion(joy, -1, 0)
    names = [(e.kind, e.name, e.down, e.meta["gamepad"]) for e in got]
    assert ("gamepad", "lb", True, 0) in names and ("gamepad", "lb", False, 0) in names
    assert ("gamepad", "rt", True, 0) in names and ("gamepad", "up", True, 0) in names
    assert ("gamepad", "button1", True, 1) in names and ("gamepad", "left", True, 1) in names
    assert hub.axes[0] == {"lx": -0.5, "ly": 0.25, "rx": 0.1, "ry": -0.9, "rt": 0.8}
    assert hub.axes[1] == {"ly": -0.5} and hub.names == ["Xbox Controller", "Flight stick"]
    assert all(e.time == 5.0 for e in got)


# ============================================================================ touchscreens
def test_swipes_taps_and_multi_touch(tmp_path):
    exp = _exp(tmp_path, {
        "swipe": {"components": [{"id": "card", "type": "shape", "shape": "rect", "size": [200, 300]},
                                 {"id": "sw", "type": "mouse", "clickable": ["card"], "swipe": ["left", "right"],
                                  "correct": "$dir", "end_routine": True, "record_touches": True}]},
        "drag": {"components": [{"id": "dr", "type": "mouse", "swipe": ["up", "down"], "touch": False,
                                 "correct": "up", "end_routine": True}]},
        "tap": {"components": [{"id": "a", "type": "shape", "shape": "circle", "radius": 80, "pos": [-200, 0]},
                               {"id": "b", "type": "shape", "shape": "circle", "radius": 80, "pos": [200, 0]},
                               {"id": "tp", "type": "mouse", "clickable": ["a", "b"], "correct": "a",
                                "record_touches": True, "end_routine": True}]}},
        conditions=[{"dir": "left"}, {"dir": "right"}])
    assert not [i for i in _issues(exp) if i[0] != "info"]
    root, rows, _ = _dry(exp, tmp_path, virtual_participant=VirtualParticipant(accuracy=1.0, seed=2))
    sw = [r for r in rows if r["routine"] == "swipe"]
    assert [r["sw.swipe"] for r in sw] == [r["dir"] for r in sw] and all(r["sw.corr"] == 1 for r in sw)
    assert all(r["sw.button"] == "touch" and r["sw.clicked"] == "card" and r["sw.n_touches"] == 1 for r in sw)
    # (a finger lifted from the previous screen is recorded too: it was on the screen during this one)
    assert all([t[2] for t in r["sw.touches"]][-3:] == ["down", "move", "up"] for r in sw), [r["sw.touches"] for r in sw]
    dr = [r for r in rows if r["routine"] == "drag"]
    assert all(r["dr.swipe"] == "up" and r["dr.button"] == "left" for r in dr)       # a mouse drag is a swipe too
    tp = [r for r in rows if r["routine"] == "tap"]
    assert all(r["tp.clicked"] == "a" and r["tp.corr"] == 1 and r["tp.x"] == -200 for r in tp)


def test_two_fingers_and_short_swipes(tmp_path):
    exp = _exp(tmp_path, {"r": {"components": [
        {"id": "sw", "type": "mouse", "swipe": ["left"], "record_touches": True, "end_routine": True, "duration": 2}]}},
        flow=["r"])
    be = HeadlessBackend()
    session = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    t0 = be.clock()
    be.touch((0, 0), t0 + 0.1, "down", 1)
    be.touch((100, 100), t0 + 0.12, "down", 2)          # a second finger
    be.touch((-20, 0), t0 + 0.2, "up", 1)              # too short for a swipe: a tap
    be.touch((100, 100), t0 + 0.25, "up", 2)
    be.touch((0, 0), t0 + 0.4, "down", 3)
    be.touch((-300, 10), t0 + 0.5, "up", 3)            # a swipe to the left
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["sw.swipe"] == "left" and row["sw.n_touches"] == 2
    assert row["sw.rt"] == pytest.approx(0.4, abs=0.03)          # RT = when the finger went down
    assert {t[1] for t in row["sw.touches"]} == {1, 2, 3}


def test_touch_can_be_turned_off_and_mouse_validation(tmp_path):
    exp = _exp(tmp_path, {"r": {"components": [{"id": "m", "type": "mouse", "touch": False, "duration": 1}]}}, flow=["r"])
    be = HeadlessBackend()
    session = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    be.tap((0, 0), be.clock() + 0.1)
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["m.button"] is None
    bad = _issues(_exp(tmp_path, {"r": {"components": [
        {"id": "m", "type": "mouse", "swipe": ["sideways"], "correct": "left", "swipe_distance": 3, "duration": 1}]}}))
    assert any(l == "error" and "'sideways' isn't a swipe direction" in m for l, m in bad)
    assert any(l == "error" and "swipe distance" in m for l, m in bad)
    assert any(l == "warning" and "isn't one of the swipe directions" in m for l, m in bad)


def test_slider_answers_a_tap(tmp_path):
    exp = _exp(tmp_path, {"r": {"components": [{"id": "s", "type": "slider", "end_routine": True, "duration": 2}]}},
               flow=["r"])
    be = HeadlessBackend()
    session = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    be.tap((400, -150), be.clock() + 0.3)
    Runner(session).run()
    row = json.loads((Path(session.data.root) / "trials.jsonl").read_text().splitlines()[0])
    assert row["s.rating"] == 7


# ============================================================================ Try it
@pytest.fixture
def server(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, app
    httpd.shutdown()


def _post(url, body, raw=False, headers=None):
    data = body if raw else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "audio/wav" if raw else "application/json",
                                                         **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _wait(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.03)
    raise AssertionError("timed out")


def test_try_it_records_in_the_browser_and_uploads_into_the_try_session(server, tmp_path):
    url, root, app = server
    doc = {"name": "say", "settings": {"window": {"size": [800, 600]}},
           "routines": {"r": {"components": [{"id": "voice", "type": "microphone", "stop_after_speech": True,
                                              "end_routine": True, "release_ms": 100}]},
                        "g": {"components": [{"id": "gp", "type": "gamepad", "axis_threshold": 0.5, "end_routine": True}]},
                        "t": {"components": [{"id": "m", "type": "mouse", "swipe": ["right"], "record_touches": True,
                                              "end_routine": True}]}},
           "flow": ["r", "g", "t"]}
    assert _post(url + "/api/play/start", {"experiment": doc})["ok"]
    rec = _wait(lambda: (_get(url + "/api/play/frame").get("record") or [None])[0])
    assert rec["file"] == "audio/0001_r_voice.wav" and rec["samplerate"] == 44100 and rec["release_ms"] == 100
    wav = audio.write_wav(tmp_path / "clip.wav", audio.simulate_recording(1.0, 44100, 0.3, 0.4), 44100)
    # only the file the item asked for, only WAV
    assert _post(url + "/api/play/audio?file=../../evil.wav", wav.read_bytes(), raw=True)["ok"] is False
    assert _post(url + "/api/play/audio?file=audio/0001_r_voice.wav", b"not a wav", raw=True)["ok"] is False
    # a page of another site can't upload
    assert _post(url + "/api/play/audio?file=audio/0001_r_voice.wav", wav.read_bytes(), raw=True,
                 headers={"Origin": "http://evil.example"})["status"] == 403
    # the browser's detector says when speech started and stopped
    assert _post(url + "/api/play/input", {"kind": "speech", "name": "voice", "down": True})["ok"]
    time.sleep(0.15)
    assert _post(url + "/api/play/input", {"kind": "speech", "name": "voice", "down": False})["ok"]
    _wait(lambda: not _get(url + "/api/play/frame").get("record"))
    up = _post(url + "/api/play/audio?file=audio/0001_r_voice.wav", wav.read_bytes(), raw=True)
    assert up == {"ok": True, "saved": "audio/0001_r_voice.wav"}
    # the gamepad (the browser's Gamepad API) and touch
    _wait(lambda: app.play.player.runner and app.play.player.runner.routine_count >= 1)
    time.sleep(0.1)
    assert _post(url + "/api/play/input", {"kind": "gamepad_axis", "name": "lx", "value": 0.9, "gamepad": 0})["ok"]
    _wait(lambda: app.play.player.runner.routine_count >= 2)
    time.sleep(0.1)
    for phase, x in (("down", 0), ("move", 50), ("up", 200)):
        assert _post(url + "/api/play/input", {"kind": "touch", "name": phase, "down": phase != "up", "pos": [x, 0],
                                               "id": 7})["ok"]
    f = _wait(lambda: (lambda fr: fr if not fr["running"] else None)(_get(url + "/api/play/frame")))
    assert not f.get("error"), f
    session = Path(f["result"]["data_dir"])
    assert session.parent.name == "try" and (session / "audio" / "0001_r_voice.wav").is_file()
    rows = [json.loads(line) for line in (session / "trials.jsonl").read_text().splitlines()]
    assert rows[0]["voice.source"] == "browser" and rows[0]["voice.rt"] is not None
    assert rows[1]["gp.button"] == "stick_right" and rows[1]["gp.axes"]["lx"] == 0.9
    assert rows[2]["m.swipe"] == "right" and rows[2]["m.touches"][0][1] == 7
