import csv
import json
import socket
import threading
import time

import pytest

from edge.align import align
from edge.devices import create_device, device_registry
from edge.devices.gazepoint import parse_messages
from edge.events import Marker
from edge.participant import VirtualParticipant
from edge.report import analyze_session


def test_registry_has_builtin_drivers():
    reg = device_registry()
    for name in ("tobii", "gazepoint", "gtec", "mindware", "lsl_markers", "lsl_inlet", "ttl_serial",
                 "parallel_port", "sim_eyetracker", "sim_eeg", "sim_physio", "mouse_gaze", "ttl_loopback"):
        assert name in reg
        desc = reg[name].describe()
        assert desc["type"] == name and isinstance(desc["options"], dict)


def test_simulated_devices_sync_end_to_end(run):
    """Every simulated device runs on its own drifting clock; after alignment, the trigger
    channel of each stream must line up with EDGE's flip-locked markers within one sample."""
    d = {"devices": [{"id": "eeg", "type": "sim_eeg", "options": {"srate": 500, "clock_offset": 12345.6,
                                                                   "clock_drift_ppm": 50}},
                     {"id": "physio", "type": "sim_physio"},
                     {"id": "et", "type": "sim_eyetracker"}],
         "routines": {"r": {"duration": 1.0, "components": [
             {"id": "s", "type": "shape", "start": 0.3, "duration": 0.2, "marker": "$f'stim_{L.n % 3}'"}]}},
         "flow": [{"loop": "L", "repeats": 30, "children": ["r"]}]}
    summary, session, _ = run(d)
    rep = analyze_session(session.data.root)
    for name, period_ms in (("eeg.eeg", 2.0), ("physio.physio", 2.0), ("et.gaze", 1000 / 120)):
        tr = rep["streams"][name]["triggers"]
        assert tr["matched"] == tr["expected"] >= 30, name
        assert 0 <= tr["latency_mean_ms"] <= period_ms + 0.5, name
        assert tr["latency_max_abs_ms"] <= period_ms + 1.0, name
    cm = summary["devices"]["eeg"]["clock_model"]
    assert abs((cm["slope"] - 1) * 1e6 + 50) < 1.0  # recovered the 50 ppm drift
    assert rep["verdict"][0].startswith("OK")


def test_dry_run_substitutes_hardware(run):
    d = {"devices": [{"id": "et", "type": "tobii"}, {"id": "amp", "type": "gtec"},
                     {"id": "bio", "type": "mindware"}, {"id": "ttl", "type": "ttl_serial"}],
         "routines": {"r": {"components": [{"id": "k", "type": "keyboard", "end_routine": True}]}},
         "flow": ["r"]}
    summary, _, _ = run(d, vp=VirtualParticipant(), simulate=True)
    assert {v["type"] for v in summary["devices"].values()} == {"sim_eyetracker", "sim_eeg", "sim_physio", "ttl_loopback"}


def test_optional_device_failure_does_not_abort(run):
    d = {"devices": [{"id": "gp", "type": "gazepoint", "required": False, "options": {"port": 1, "connect_timeout": 0.2}}],
         "routines": {"r": {"duration": 0.1, "components": []}}, "flow": ["r"]}
    summary, session, _ = run(d)
    assert "gp" not in session.devices and any("gp" in e for e in summary["errors"])


def test_required_device_failure_raises(run):
    d = {"devices": [{"id": "gp", "type": "gazepoint", "options": {"port": 1, "connect_timeout": 0.2}}],
         "routines": {"r": {"duration": 0.1, "components": []}}, "flow": ["r"]}
    with pytest.raises(Exception, match="Gazepoint"):
        run(d)


def test_loopback_code_map():
    dev = create_device("ttl_loopback", "t", {"code_map": {"stim": 7}})
    dev.connect()
    dev.send_marker(Marker("stim", 0.0, code=1))
    dev.send_marker(Marker("other", 0.0, code=9))
    dev.send_marker(Marker("nocode", 0.0))
    assert [c for _, c in dev.sent] == [7, 9]


# ------------------------------------------------------------------ Gazepoint protocol against a mock server
def test_parse_messages_handles_partial_buffers():
    msgs, rest = parse_messages('<ACK ID="X" STATE="1" />\r\n<REC TIME="1.5" FPOGX="0.5" />\r\n<REC TIME="1')
    assert [m[0] for m in msgs] == ["ACK", "REC"] and msgs[1][1]["FPOGX"] == "0.5"
    assert rest.strip() == '<REC TIME="1'


class MockGazepoint(threading.Thread):
    """Speaks enough of the Open Gaze API to exercise the driver."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.received: list[str] = []
        self.stop = threading.Event()

    def run(self):
        conn, _ = self.srv.accept()
        conn.settimeout(0.005)
        streaming, t0, n, user = False, time.monotonic(), 0, ""
        buf = ""
        while not self.stop.is_set():
            try:
                data = conn.recv(4096).decode()
                buf += data
            except socket.timeout:
                pass
            except OSError:
                break
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                self.received.append(line)
                if 'ID="ENABLE_SEND_DATA" STATE="1"' in line:
                    streaming = True
                if 'ID="USER_DATA"' in line:
                    user = line.split('VALUE="')[1].split('"')[0]
                if line.startswith("<SET"):
                    ident = line.split('ID="')[1].split('"')[0]
                    conn.sendall(f'<ACK ID="{ident}" STATE="1" />\r\n'.encode())
                if 'ID="CALIBRATE_START"' in line:
                    conn.sendall(b'<CAL ID="CALIB_RESULT" CALX1="0.5" CALY1="0.5" LX1="0.51" LY1="0.5" LV1="1" '
                                 b'RX1="0.5" RY1="0.49" RV1="1" />\r\n')
            if streaming:
                elapsed = time.monotonic() - t0
                while n < elapsed * 150:
                    rec = (f'<REC CNT="{n}" TIME="{n / 150:.5f}" FPOGX="0.75" FPOGY="0.25" FPOGV="1" '
                           f'BPOGX="0.75" BPOGY="0.25" BPOGV="1" USER="{user}" />\r\n')
                    user = ""
                    conn.sendall(rec.encode())
                    n += 1
        conn.close()


def test_gazepoint_driver_with_mock_server():
    srv = MockGazepoint()
    srv.start()
    dev = create_device("gazepoint", "gp", {"port": srv.port, "screen_size": [1000, 800]})
    samples = []
    dev.add_sink(lambda d, s, td, ta, v: samples.append((td, v)))
    dev.connect()
    cal = dev.calibrate(None)
    assert cal["result"] == "ok" and cal["valid_points"] == 1
    dev.start()
    time.sleep(0.3)
    dev.send_marker(Marker("stim_on", 0.0, code=3))
    time.sleep(0.2)
    dev.stop()
    dev.close()
    srv.stop.set()
    assert len(samples) > 20
    # normalized (0.75, 0.25) top-left origin -> window px centre origin, y up
    assert dev.latest_gaze() == pytest.approx((250.0, 200.0))
    users = [v[-1] for _, v in samples if v[-1]]
    assert "stim_on" in users
    assert any('ID="ENABLE_SEND_POG_FIX"' in r for r in srv.received)
    m = dev.finalize_clock()
    assert m.n >= 1


# ------------------------------------------------------------------ external alignment
def test_align_external_recording(run, tmp_path):
    d = {"devices": [{"id": "ttl", "type": "ttl_loopback"}],
         "routines": {"r": {"duration": 0.7, "components": [{"id": "m", "type": "marker", "label": "$f'c{L.n % 5}'",
                                                               "start": 0.2}]}},
         "flow": [{"loop": "L", "repeats": 40, "children": ["r"]}]}
    _, session, _ = run(d)
    events = [json.loads(l) for l in (session.data.root / "events.jsonl").read_text().splitlines()]
    # fake an external recorder (e.g. MindWare BioLab) that saw the same TTL codes on its own clock
    ext = tmp_path / "biolab_events.csv"
    with ext.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "code"])
        for i, e in enumerate(events):
            if i % 7 == 3:
                continue  # some events missed by the external system
            w.writerow([f"{(e['time'] - 1000) * 1.0001 + 33.3:.6f}", e["code"]])
        w.writerow(["5.0", "99"])  # spurious extra event
    res = align(session.data.root, ext)
    assert res["matched"] >= len(events) * 0.8
    cm = res["model"]
    assert abs(cm["slope"] - 1 / 1.0001) < 1e-7
    assert (session.data.root / "alignment.json").exists()


# ------------------------------------------------------------------ real LSL (skipped if liblsl is unavailable)
def _lsl():
    try:
        import pylsl
        pylsl.local_clock()
        return pylsl
    except Exception:
        return None


@pytest.mark.skipif(_lsl() is None, reason="liblsl not available")
def test_lsl_inlet_and_markers_real_time(tmp_path):
    pylsl = _lsl()
    from tests.conftest import run_headless

    # a fake 200 Hz amplifier on the LSL network
    info = pylsl.StreamInfo("EdgeTestAmp", "EEG", 2, 200, pylsl.cf_float32, "edge-test-amp")
    ch = info.desc().append_child("channels")
    for name in ("C3", "C4"):
        ch.append_child("channel").append_child_value("label", name)
    outlet = pylsl.StreamOutlet(info)
    stop = threading.Event()

    def pump():
        i = 0
        t0 = pylsl.local_clock()
        while not stop.is_set():
            target = t0 + i / 200
            if pylsl.local_clock() >= target:
                outlet.push_sample([float(i), -float(i)], target)
                i += 1
            else:
                time.sleep(0.0005)

    threading.Thread(target=pump, daemon=True).start()

    # an independent consumer of EDGE's marker stream (like LabRecorder)
    received = []

    def listen():
        streams = pylsl.resolve_byprop("name", "EDGE-Test-Markers", 1, 5.0)
        inlet = pylsl.StreamInlet(streams[0], processing_flags=pylsl.proc_clocksync)
        while not stop.is_set():
            s, ts = inlet.pull_sample(timeout=0.05)
            if s:
                received.append((s[0], ts))

    listener = threading.Thread(target=listen, daemon=True)
    listener.start()

    d = {"devices": [{"id": "amp", "type": "lsl_inlet", "options": {"name": "EdgeTestAmp"}},
                     {"id": "mk", "type": "lsl_markers", "options": {"name": "EDGE-Test-Markers", "wait_for_consumers": 10}}],
         "routines": {"r": {"duration": 0.3, "components": [
             {"id": "s", "type": "shape", "start": 0.1, "duration": 0.1, "marker": "$f'stim_{L.n}'"}]}},
         "flow": [{"loop": "L", "repeats": 5, "children": ["r"]}]}
    summary, session, be = run_headless(d, tmp_path, realtime=True)
    time.sleep(0.3)
    stop.set()
    amp = summary["devices"]["amp"]["streams"]["EdgeTestAmp"]
    assert amp["channels"] == ["C3", "C4"] and amp["samples"] > 200
    events = [json.loads(l) for l in (session.data.root / "events.jsonl").read_text().splitlines()]
    sent = {e["label"]: e["time"] for e in events if e["label"].startswith("stim_")}
    got = {lab: ts for lab, ts in received if lab.startswith("stim_")}
    assert set(got) == set(sent) == {f"stim_{i}" for i in range(5)}
    for lab, t in sent.items():
        assert abs(got[lab] - t) < 0.002  # LSL timestamps are the flip times on the shared clock
    rows = list(csv.reader((session.data.root / "streams/amp.EdgeTestAmp.csv").open()))
    assert rows[0][:5] == ["time", "device_time", "arrival_time", "C3", "C4"]
