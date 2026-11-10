"""Running a study day: the participant queue, session notes, live signal quality, pause, the second screen."""

import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import quality, studyday
from edge.devices import create_device

SR = 250


def _t(n=500):
    return [i / SR for i in range(n)]


# =============================================================================== signal quality
def test_quality_on_synthetic_signals():
    rng = random.Random(3)
    clean = [10 * math.sin(2 * math.pi * 10 * t) + rng.gauss(0, 4) for t in _t()]
    hum50 = [v + 40 * math.sin(2 * math.pi * 50 * t) for v, t in zip(clean, _t())]
    hum60 = [v + 40 * math.sin(2 * math.pi * 60 * t) for v, t in zip(clean, _t())]
    flat = [12.0] * 500
    noisy = [rng.gauss(0, 220) for _ in _t()]
    clipped = [max(-50.0, min(50.0, v * 10)) for v in clean]
    m = quality.channel_metrics(clean, SR)
    assert m["status"] == "ok" and m["reasons"] == [] and 5 < m["rms"] < 15
    m = quality.channel_metrics(hum50, SR)
    assert m["status"] == "bad" and m["line_hz"] == 50 and 25 < m["line_uv"] < 31 and m["line_ratio"] > 0.5
    assert "50 Hz" in m["reasons"][0]
    assert quality.channel_metrics(hum60, SR)["line_hz"] == 60
    m = quality.channel_metrics(flat, SR)
    assert m["status"] == "bad" and m["flat"] and "flat" in m["reasons"][0]
    m = quality.channel_metrics(noisy, SR)
    assert m["status"] == "bad" and "noisy" in m["reasons"][0]
    m = quality.channel_metrics(clipped, SR)
    assert m["status"] == "bad" and m["clipped"] > 0.05 and "saturated" in m["reasons"][0]
    # a little hum is only worth a look
    mild = [v + 9 * math.sin(2 * math.pi * 50 * t) for v, t in zip(clean, _t())]
    assert quality.channel_metrics(mild, SR)["status"] == "warn"
    # too little data: wait
    assert quality.channel_metrics(clean[:10], SR)["status"] == "wait"


def test_goertzel_amplitude_with_and_without_numpy(monkeypatch):
    x = [10 * math.sin(2 * math.pi * 50 * t) for t in _t()]
    a = quality.goertzel_amplitude(x, SR, 50)
    monkeypatch.setattr(quality, "_np", None)
    b = quality.goertzel_amplitude(x, SR, 50)
    assert abs(a - 10 / math.sqrt(2)) < 0.05 and abs(a - b) < 1e-6


def test_signal_quality_units_trigger_channels_and_impedance():
    rows = [[v * 1e-6, 0.0, 0] for v in [30 * math.sin(2 * math.pi * 50 * t) for t in _t()]]   # volts
    q = quality.signal_quality(["C3", "C4", "TRIG"], ["V", "V", "code"], rows, SR, "EEG", impedance={"C3": 30.0})
    names = [c["name"] for c in q["channels"]]
    assert names == ["C3", "C4"]                     # the trigger channel is not an electrode
    c3, c4 = q["channels"]
    assert c3["line_uv"] > 15 and c3["impedance_kohm"] == 30.0 and c3["status"] == "bad"
    assert c4["flat"] and q["impedance"]["available"]
    q = quality.signal_quality(["C3"], None, [[1.0]] * 10, SR, "EEG")
    assert q["impedance"] == {"available": False, "applies": True, "note": "not available from this device"}


def test_gaze_quality():
    chans = ["x", "y", "valid", "pupil_l", "pupil_r", "user"]
    rows = [[0, 0, 1, 3.5, 3.6, 0]] * 400 + [[None, None, 0, None, None, 0]] * 200 + [[0, 0, 1, 3.5, 3.6, 0]] * 50
    q = quality.gaze_quality(chans, rows, 120.0)
    assert q["kind"] == "gaze" and q["losses"] == 1 and q["longest_loss_s"] == pytest.approx(200 / 120, abs=0.01)
    assert 60 < q["validity_pct"] < 80 and q["status"] == "warn" and "tracking lost" in " ".join(q["reasons"])
    q = quality.gaze_quality(chans, [[0, 0, 0, None, None, 0]] * 300, 120.0)
    assert q["status"] == "bad" and q["validity_pct"] == 0
    # Tobii-style: one validity per eye
    tob = ["left_x", "left_y", "left_valid", "right_x", "right_y", "right_valid", "left_pupil", "right_pupil"]
    q = quality.gaze_quality(tob, [[.5, .5, 1, .5, .5, 0, 3, 0]] * 300, 60.0)
    assert q["left_pct"] == 100 and q["right_pct"] == 0 and q["validity_pct"] == 100


def test_simulated_eeg_has_bad_channels_and_impedance():
    dev = create_device("sim_eeg", "eeg", {"seed": 1})
    dev.connect()
    dev.start()
    dev._last -= 3.0               # pretend 3 s have passed: poll() makes up the samples
    dev.poll()
    q = dev.quality()["eeg"]
    by = {c["name"]: c for c in q["channels"]}
    assert "TRIG" not in by
    assert by["C4"]["status"] == "bad" and by["C4"]["line_hz"] == 50
    assert by["P4"]["flat"] and by["Oz"]["status"] in ("warn", "bad")
    assert by["Cz"]["status"] == "ok" and by["Cz"]["impedance_kohm"] < 10
    assert q["impedance"]["available"] and by["P4"]["impedance_kohm"] > 100
    assert "C4" in quality.summary_words(q)
    clean = create_device("sim_eeg", "eeg", {"seed": 1, "faults": {}})
    clean.connect(); clean.start(); clean._last -= 3.0; clean.poll()
    assert clean.quality()["eeg"]["status"] == "ok"


def test_devices_without_impedance_say_so_and_events_have_no_quality():
    dev = create_device("sim_physio", "ph", {"seed": 2})
    dev.connect(); dev.start(); dev._last -= 2.0; dev.poll()
    q = dev.quality()["physio"]
    assert q["kind"] == "signal" and q["impedance"]["applies"] is False
    assert [c["name"] for c in q["channels"]] == ["ecg", "eda", "resp"]
    loop = create_device("ttl_loopback", "ttl")
    loop.connect()
    assert loop.quality() == {}
    from edge.devices.base import Device
    assert Device("x").impedance() is None and Device("x").impedance_note() == "not available from this device"


def test_test_device_reports_quality():
    from edge.devtest import test_device
    r = test_device("sim_eeg", "eeg", seconds=1.2)
    assert r["quality"]["eeg"]["kind"] == "signal"
    assert any(m.startswith("signal quality eeg:") for m in r["messages"])


# =============================================================================== the monitor
def test_monitor_events_carry_quality_screen_and_pause(tmp_path):
    exp = tmp_path / "e.yaml"
    exp.write_text("name: e\nroutines:\n  a:\n    components:\n      - {id: t, type: text, text: hi, duration: 1.2}\n"
                   "  b:\n    components:\n      - {id: t, type: text, text: bye, duration: 0.3}\n"
                   "flow: [a, b]\ndevices:\n  - {id: eeg, type: sim_eeg}\n")
    pause = tmp_path / "pause"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent), "EDGE_MONITOR": "1",
           "EDGE_QUALITY_INTERVAL": "0.3", "EDGE_PAUSE_FILE": str(pause), "EDGE_STOP_FILE": str(tmp_path / "stop")}
    proc = subprocess.Popen([sys.executable, "-m", "edge", "run", str(exp), "--backend", "headless-realtime", "-p", "001"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=str(tmp_path))
    events = []
    from edge.monitor import parse
    for line in proc.stdout:
        ev = parse(line.rstrip())
        if ev is None:
            continue
        events.append(ev)
        if ev["type"] == "screen" and ev["routine"] == "a":
            pause.touch()                        # pause before the next screen
        if ev["type"] == "paused":
            threading.Timer(0.6, lambda: pause.unlink()).start()
    assert proc.wait(60) == 0
    kinds = [e["type"] for e in events]
    assert "quality" in kinds and "paused" in kinds and "resumed" in kinds
    q = next(e for e in events if e["type"] == "quality")["devices"]["eeg"]["streams"]["eeg"]
    assert {c["name"] for c in q["channels"] if c["status"] == "bad"} >= {"C4", "P4"}
    assert [e["routine"] for e in events if e["type"] == "screen"] == ["a", "b"]
    p = next(e for e in events if e["type"] == "paused")
    assert p["before"] == "b" and next(e for e in events if e["type"] == "resumed")["paused_s"] >= 0.4
    data = next(e for e in events if e["type"] == "end")["data_dir"]
    labels = [json.loads(x)["label"] for x in Path(data, "events.jsonl").read_text().splitlines()]
    assert "pause" in labels and "resume" in labels


def test_png_of_a_mirror_frame_is_valid():
    from edge.backends.pyglet_backend import _shrink
    from edge.monitor import png_bytes
    w, h = 8, 4
    raw = bytes([(x * 30) % 256 for x in range(w * h * 3)])
    sw, sh, small = _shrink(raw, w, h, 2)
    assert (sw, sh) == (4, 2) and len(small) == 4 * 2 * 3
    assert small[:3] == raw[(h - 1) * w * 3:(h - 1) * w * 3 + 3]     # first row = the top (OpenGL's last row)
    png = png_bytes(sw, sh, small)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in png


def test_monitor_mirror_is_opt_in():
    from types import SimpleNamespace
    from edge.monitor import Monitor
    got = []
    sess = SimpleNamespace(exp=SimpleNamespace(measures=[]), devices={}, data=None)
    m = Monitor(sess, emit=got.append)
    assert not m.mirror_due()
    m = Monitor(sess, emit=got.append, mirror_interval=1.0)
    assert m.mirror_due() and not m.mirror_due()          # once per interval
    m.mirror_frame(2, 1, b"\x00\x00\x00\xff\xff\xff")
    m._send_mirror()
    assert got[-1]["type"] == "mirror" and got[-1]["w"] == 2 and got[-1]["png"]


# =============================================================================== the queue
def test_next_ids_and_groups_in_rotation(tmp_path):
    assert studyday.next_ids(["001", "002", "007", "x"], 3) == ["008", "009", "010"]
    assert studyday.next_ids([], 2) == ["001", "002"]
    assert studyday.next_ids(["001"], 2, start="010") == ["010", "011"]
    q = {"groups": [], "entries": []}
    studyday.add_planned(q, 3, used=["004"], groups=["A", "B"])
    assert [(e["participant"], e["group"]) for e in q["entries"]] == [("005", "A"), ("006", "B"), ("007", "A")]
    studyday.add_planned(q, 1, used=[])                    # keeps the groups and the rotation
    assert (q["entries"][-1]["participant"], q["entries"][-1]["group"]) == ("008", "B")
    with pytest.raises(studyday.StudyDayError):
        studyday.add_planned(q, 0, used=[])
    with pytest.raises(studyday.StudyDayError):
        studyday.make_entry(q, "../evil")


def test_queue_crud(tmp_path):
    exp = tmp_path / "study.yaml"
    exp.write_text("name: s\nroutines: {}\nflow: []\n")
    q = studyday.load_queue(exp)
    assert q["entries"] == []
    e = studyday.make_entry(q, "001", "1", "A")
    e2 = studyday.make_entry(q, "002", "1", "B")
    studyday.update_entry(q, e["id"], {"comment": "left-handed", "group": "B"})
    studyday.move_entry(q, e2["id"], -1)
    studyday.save_queue(exp, q)
    q = studyday.load_queue(exp)
    assert [x["participant"] for x in q["entries"]] == ["002", "001"]
    assert q["entries"][1]["comment"] == "left-handed" and q["entries"][1]["group"] == "B"
    assert studyday.queue_file(exp) == tmp_path / ".edge" / "queue" / "study.json"
    with pytest.raises(studyday.StudyDayError):
        studyday.update_entry(q, e["id"], {"status": "finished"})
    q["entries"][0]["status"] = "running"
    with pytest.raises(studyday.StudyDayError):
        studyday.delete_entry(q, q["entries"][0]["id"])
    studyday.delete_entry(q, e["id"])
    assert len(q["entries"]) == 1
    assert studyday.next_planned(q) is None


def test_csv_round_trip():
    text = "Subject;Condition;Session;handedness\n101;A;1;left\n102;B;1;right\n103;A;2;\n"
    q = {"groups": [], "entries": []}
    assert studyday.import_csv(q, text) == {"added": 3, "updated": 0}
    assert [(e["participant"], e["session"], e["group"]) for e in q["entries"]] == [("101", "1", "A"), ("102", "1", "B"), ("103", "2", "A")]
    assert q["entries"][0]["extra"] == {"handedness": "left"} and q["groups"] == ["A", "B"]
    q["entries"][1]["status"] = "no-show"
    out = studyday.export_csv(q)
    q2 = {"groups": [], "entries": []}
    studyday.import_csv(q2, out)
    strip = lambda es: [(e["participant"], e["session"], e["group"], e["status"], e["extra"]) for e in es]   # noqa: E731
    assert strip(q2["entries"]) == strip(q["entries"])
    # importing again updates instead of duplicating; replace starts over
    assert studyday.import_csv(q2, "participant,group\n101,C\n") == {"added": 0, "updated": 1}
    assert q2["entries"][0]["group"] == "C" and len(q2["entries"]) == 3
    studyday.import_csv(q2, "id\n900\n", replace=True)
    assert [e["participant"] for e in q2["entries"]] == ["900"]
    with pytest.raises(studyday.StudyDayError):
        studyday.import_csv(q2, "name,age\nx,3\n")


def test_run_log(tmp_path):
    exp = tmp_path / "s.yaml"
    studyday.log_event(exp, "start", "started participant 001", participant="001")
    studyday.log_event(exp, "note", "electrode re-gelled")
    log = studyday.read_log(exp)
    assert [e["kind"] for e in log] == ["start", "note"] and log[0]["participant"] == "001"
    assert studyday.read_log(exp, "1999-01-01") == [] and len(studyday.read_log(exp, "all")) == 2


# =============================================================================== notes
def test_notes_saved_with_the_session_and_exported(tmp_path):
    from edge.cli import main
    from edge.export import SessionTables, export_many, timing_row
    exp = tmp_path / "e.yaml"
    exp.write_text("name: e\nroutines:\n  a:\n    components:\n      - {id: t, type: text, text: hi, duration: 0.1}\nflow: [a]\n")
    assert main(["run", str(exp), "--backend", "headless", "-p", "005"]) == 0
    folder = next((tmp_path / "data").glob("005_*"))
    notes = studyday.edit_notes([], "add", "electrode C4 re-gelled", elapsed=65.0)
    notes = studyday.edit_notes(notes, "add", "sneezed during block 2")
    notes = studyday.edit_notes(notes, "edit", "sneezed twice during block 2", index=1)
    studyday.write_notes(folder, notes, "participant 005")
    assert studyday.read_notes(folder)[1]["text"] == "sneezed twice during block 2"
    md = (folder / "notes.md").read_text()
    assert "electrode C4 re-gelled" in md and "(+1:05)" in md and "(edited" in md
    row = timing_row(SessionTables(folder))
    assert "electrode C4 re-gelled" in row["notes"] and " | " in row["notes"]
    res = export_many(tmp_path / "data", ["csv"])
    sess_csv = next(Path(f) for f in res["files"] if f.endswith("_sessions.csv"))
    assert "electrode C4 re-gelled" in sess_csv.read_text()
    with pytest.raises(studyday.StudyDayError):
        studyday.edit_notes(notes, "delete", index=5)


# =============================================================================== the builder's endpoints
@pytest.fixture
def server(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    shutil.copytree("examples/stroop", tmp_path / "stroop", ignore=shutil.ignore_patterns("data"))
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()


def _get(url, raw=False):
    with urllib.request.urlopen(url) as r:
        data = r.read()
        return data if raw else json.loads(data)


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _status(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


P = "stroop/stroop.yaml"


def test_queue_endpoints(server):
    url, app = server
    q = _get(url + f"/api/studyday/queue?path={P}")
    assert q["entries"] == [] and q["next"] is None
    q = _post(url + "/api/studyday/queue", {"path": P, "op": "add", "count": 2, "groups": ["A", "B"]})
    assert [e["participant"] for e in q["entries"]] == ["001", "002"] and q["next"] == q["entries"][0]["id"]
    eid = q["entries"][0]["id"]
    q = _post(url + "/api/studyday/queue", {"path": P, "op": "update", "id": eid, "fields": {"comment": "glasses"}})
    assert q["entries"][0]["comment"] == "glasses"
    q = _post(url + "/api/studyday/noshow", {"path": P, "id": eid, "reason": "ill"})
    assert q["entries"][0]["status"] == "no-show" and q["next"] == q["entries"][1]["id"]
    assert any(ev["kind"] == "no-show" for ev in q["log"])
    csv_text = _get(url + f"/api/studyday/export?path={P}", raw=True).decode("utf-8-sig")
    assert csv_text.startswith("participant,session,group,status") and "no-show" in csv_text
    q = _post(url + "/api/studyday/queue", {"path": P, "op": "import", "csv": "participant,group\n050,B\n"})
    assert q["added"] == 1 and q["entries"][-1]["participant"] == "050"
    q = _post(url + "/api/studyday/queue", {"path": P, "op": "delete", "id": q["entries"][-1]["id"]})
    assert len(q["entries"]) == 2
    assert (Path(app.root) / "stroop/.edge/queue/stroop.json").exists()


def test_studyday_endpoints_are_guarded(server):
    url, _ = server
    body = {"path": P, "op": "add", "count": 1}
    js = {"Content-Type": "application/json"}
    assert _status(url + "/api/studyday/queue", body, {**js, "Origin": "http://evil.example"}) == 403
    assert _status(url + "/api/studyday/queue", body, {**js, "Sec-Fetch-Site": "cross-site"}) == 403
    assert _status(url + f"/api/studyday/queue?path={P}", None, {"Origin": "http://evil.example"}) == 403
    assert _status(url + "/api/studyday/queue", body, {"Content-Type": "text/plain"}) == 415
    assert _status(url + "/api/studyday/queue", {"path": "../../etc/passwd", "op": "add"}, js) == 400
    assert _status(url + "/api/studyday/queue", {"path": P}, js) == 400                         # no op
    assert _status(url + "/api/studyday/queue", {"path": P, "op": "explode"}, js) == 400
    assert _status(url + "/api/studyday/queue", {"path": P, "op": "add", "count": "lots"}, js) == 400
    assert _status(url + "/api/studyday/notes?session=../..", None) == 400
    assert _status(url + "/api/studyday/notes?session=stroop", None) == 400                     # not a session folder
    assert _status(url + "/api/studyday/pause", {"id": "nope", "pause": True}, js) == 400
    assert _status(url + "/api/studyday/mirror?id=nope", None) == 400
    assert _status(url + "/api/studyday/export", None) == 400                                    # needs ?path=


class FakeProc:
    """A session subprocess that prints monitor events (as `edge run` does with EDGE_MONITOR=1)."""

    def __init__(self, lines):
        self.pid = 4242
        self.stdout = io.StringIO("".join(lines))
        self.returncode = None
        self._done = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._done.wait(timeout)
        return self.returncode

    def finish(self, rc=0):
        self.returncode = rc
        self._done.set()

    def terminate(self):
        self.finish(1)


def _monitor_lines(data_dir, aborted=False):
    from edge.monitor import PREFIX
    evs = [{"type": "start", "data_dir": str(data_dir), "expected_trials": 2, "measures": [], "devices": {}},
           {"type": "screen", "routine": "trial"},
           {"type": "quality", "devices": {"eeg": {"type": "sim_eeg", "streams": {"eeg": {"kind": "signal", "status": "bad"}}}}},
           {"type": "end", "aborted": aborted, "trials": 2, "data_dir": str(data_dir)}]
    return [PREFIX + json.dumps(e) + "\n" for e in evs]


def test_a_queued_session_runs_takes_notes_and_ends(server, monkeypatch, tmp_path):
    url, app = server
    from edge.builder import server as srv
    data_dir = Path(app.root) / "stroop/data/001_1_stroop_x"
    data_dir.mkdir(parents=True)
    procs = []

    def popen(cmd, **kw):
        procs.append((cmd, kw, FakeProc(_monitor_lines(data_dir))))
        return procs[-1][2]
    monkeypatch.setattr(srv.subprocess, "Popen", popen)
    q = _post(url + "/api/studyday/queue", {"path": P, "op": "add", "count": 2, "groups": ["A", "B"]})
    r = _post(url + "/api/studyday/start", {"path": P, "mirror": True})
    cmd, kw, proc = procs[0]
    assert r["participant"] == "001" and "group=A" in cmd and "participant=001" in cmd
    assert kw["env"]["EDGE_MIRROR"] == "2" and kw["env"]["EDGE_PAUSE_FILE"]
    rid = r["run_id"]
    q = _get(url + f"/api/studyday/queue?path={P}")
    assert q["entries"][0]["status"] == "running" and q["entries"][0]["live"]
    for _ in range(100):           # the pump reads the monitor lines
        if app.runs[rid]["monitor"].get("end"):
            break
        time.sleep(0.02)
    st = _get(url + f"/api/run_status?id={rid}")
    assert st["monitor"]["quality"]["devices"]["eeg"] and st["monitor"]["screen"]["routine"] == "trial"
    n = _post(url + "/api/studyday/notes", {"run": rid, "op": "add", "text": "C4 re-gelled"})
    assert n["notes"][0]["text"] == "C4 re-gelled" and (data_dir / "notes.md").exists()
    assert _post(url + "/api/studyday/pause", {"id": rid, "pause": True}) == {"paused": True}
    assert Path(kw["env"]["EDGE_PAUSE_FILE"]).exists()
    _post(url + "/api/studyday/pause", {"id": rid, "pause": False})
    assert not Path(kw["env"]["EDGE_PAUSE_FILE"]).exists()
    proc.finish(0)
    for _ in range(100):
        q = _get(url + f"/api/studyday/queue?path={P}")
        if q["entries"][0]["status"] != "running":
            break
        time.sleep(0.02)
    e = q["entries"][0]
    assert e["status"] == "done" and e["data"] == "stroop/data/001_1_stroop_x" and q["next"] == q["entries"][1]["id"]
    kinds = [ev["kind"] for ev in q["log"]]
    assert kinds[:3] == ["start", "note", "end"]
    # after the session: the notes are edited through the session folder (the Data page)
    (data_dir / "session.json").write_text('{"participant": {"participant": "001", "session": "1"}}')
    n = _post(url + "/api/studyday/notes", {"session": "stroop/data/001_1_stroop_x", "op": "edit", "index": 0,
                                           "text": "C4 and P4 re-gelled"})
    assert studyday.read_notes(data_dir)[0]["text"] == "C4 and P4 re-gelled"
    assert _get(url + "/api/studyday/notes?session=stroop/data/001_1_stroop_x")["notes"][0]["edited"]


def test_stop_with_a_reason_marks_the_participant_stopped_early(server, monkeypatch):
    url, app = server
    from edge.builder import server as srv
    data_dir = Path(app.root) / "stroop/data/002_1_stroop_x"
    data_dir.mkdir(parents=True)
    procs = []
    monkeypatch.setattr(srv.subprocess, "Popen", lambda cmd, **kw: procs.append(FakeProc(_monitor_lines(data_dir, True))) or procs[-1])
    # started from the Run page (not the queue): it is still linked to the planned participant
    _post(url + "/api/studyday/queue", {"path": P, "op": "import", "csv": "participant\n002\n"})
    rid = _post(url + "/api/run", {"path": P, "participant": {"participant": "002", "session": "1"}})["run_id"]
    for _ in range(100):
        if app.runs[rid].get("data_dir"):
            break
        time.sleep(0.02)
    _post(url + "/api/studyday/stop", {"id": rid, "reason": "participant unwell"})
    assert app.runs[rid]["stop_file"].exists()
    procs[0].finish(1)
    for _ in range(100):
        q = _get(url + f"/api/studyday/queue?path={P}")
        if q["entries"][0]["status"] != "running":
            break
        time.sleep(0.02)
    e = q["entries"][0]
    assert e["status"] == "aborted" and e["reason"] == "participant unwell"
    assert "participant unwell" in studyday.read_notes(data_dir)[0]["text"]
    assert q["log"][-1]["kind"] == "abort" and "participant unwell" in q["log"][-1]["text"]


def test_a_session_that_never_started_stays_planned(server, monkeypatch):
    url, app = server
    from edge.builder import server as srv
    procs = []
    monkeypatch.setattr(srv.subprocess, "Popen", lambda cmd, **kw: procs.append(FakeProc(["EDGE could not run the experiment: no screen\n"])) or procs[-1])
    _post(url + "/api/studyday/queue", {"path": P, "op": "add", "count": 1})
    rid = _post(url + "/api/studyday/start", {"path": P})["run_id"]
    procs[0].finish(1)
    for _ in range(100):
        q = _get(url + f"/api/studyday/queue?path={P}")
        if q["entries"][0]["status"] != "running":
            break
        time.sleep(0.02)
    assert q["entries"][0]["status"] == "planned" and q["entries"][0]["run_id"] is None
    assert q["log"][-1]["kind"] == "failed" and rid


def test_keep_focus_setting_is_validated():
    from edge.model import validate_settings, DEFAULT_SETTINGS, deep_merge
    s = deep_merge(DEFAULT_SETTINGS, {"window": {"keep_focus": "no"}})
    assert any(i.where == "settings.window.keep_focus" for i in validate_settings(s))
    assert not validate_settings(deep_merge(DEFAULT_SETTINGS, {"window": {"keep_focus": False}}))


def test_lsl_impedance_stream():
    pylsl = pytest.importorskip("pylsl")
    eeg = pylsl.StreamInfo("EdgeImpAmp", "EEG", 2, 100, pylsl.cf_float32, "edge-imp-amp")
    imp = pylsl.StreamInfo("EdgeImpAmp-Z", "Impedance", 2, pylsl.IRREGULAR_RATE, pylsl.cf_float32, "edge-imp-z")
    for info in (eeg, imp):
        ch = info.desc().append_child("channels")
        for name in ("C3", "C4"):
            c = ch.append_child("channel")
            c.append_child_value("label", name)
            if info is imp:
                c.append_child_value("unit", "ohm")
    out_eeg, out_imp = pylsl.StreamOutlet(eeg), pylsl.StreamOutlet(imp)
    dev = create_device("lsl_inlet", "amp", {"name": "EdgeImpAmp", "impedance_stream": "EdgeImpAmp-Z"})
    dev.connect()
    try:
        got = None
        for _ in range(100):
            out_imp.push_sample([4000.0, 31000.0])
            out_eeg.push_sample([1.0, 2.0])
            got = dev.impedance()
            if got:
                break
            time.sleep(0.05)
        assert got == {"C3": 4.0, "C4": 31.0}
    finally:
        dev.close()
