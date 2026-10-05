"""The common pain points of experiment software, and EDGE's answers to them."""

import json
import shutil
import socket
import struct
import threading
import time
import zipfile
import zlib
from pathlib import Path

import pytest
import yaml

from edge.engine import run_experiment
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
STROOP = ROOT / "examples" / "stroop"


def _copy_stroop(tmp_path) -> Path:
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data", "*.lock.json", "*.preflight.json"))
    return tmp_path / "s" / "stroop.yaml"


def _png(path: Path, w: int = 2, h: int = 2) -> None:
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


CRASHY = {"name": "crashy", "routines": {"t": {"components": [
    {"id": "w", "type": "text", "text": "$word", "duration": 0.2},
    {"id": "calc", "type": "code", "on_frame": "ratio = 1\nratio = total / count"}]}},
    "flow": [{"loop": "trials", "conditions": [{"word": "a", "count": 2, "total": 4}, {"word": "b", "count": 0, "total": 3}],
              "children": ["t"]}]}


# ============================================================================ errors that explain themselves
def test_runtime_errors_say_what_where_when_and_state(tmp_path):
    from edge.diagnostics import ExperimentError, format_report
    with pytest.raises(ExperimentError) as e:
        run_experiment(Experiment.from_dict(CRASHY, base_dir=tmp_path), dry_run=True, data_dir=str(tmp_path / "d"),
                       log=lambda *a: None)
    rep = e.value.report
    assert rep["type"] == "ZeroDivisionError" and rep["component"] == "calc" and rep["routine"] == "t"
    assert rep["phase"] == "frame" and rep["trial"] == {"trials": 1}
    assert rep["user_code"] == {"where": "t.calc.on_frame", "line": 2, "code": "ratio = total / count"}
    assert rep["variables"]["count"] == 0 and "division by zero" in rep["hint"]
    text = format_report(rep)
    assert "trials #2" in text and "line 2 of t.calc.on_frame" in text
    meta = json.loads(next((tmp_path / "d").rglob("session.json")).read_text())
    assert meta["crash"]["component"] == "calc" and meta["aborted"] is True


@pytest.mark.parametrize("comp,phase", [
    ({"id": "k", "type": "keyboard", "keys": ["space"], "start_if": "$undefined_thing > 1", "duration": 1}, "timing"),
    ({"id": "x", "type": "text", "text": "$missing_column", "duration": 0.1}, "prepare"),
])
def test_every_phase_is_named(tmp_path, comp, phase):
    from edge.diagnostics import ExperimentError
    doc = {"name": "p", "routines": {"r": {"components": [comp]}}, "flow": ["r"]}
    with pytest.raises(ExperimentError) as e:
        run_experiment(Experiment.from_dict(doc, base_dir=tmp_path), dry_run=True, data_dir=str(tmp_path / "d"),
                       log=lambda *a: None)
    assert e.value.report["phase"] == phase and e.value.report["component"] == comp["id"]


def test_cli_prints_the_report(tmp_path, capsys):
    from edge.cli import main
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(CRASHY))
    assert main(["run", str(p), "--dry-run"]) == 3
    out = capsys.readouterr().out
    assert "What:   ZeroDivisionError" in out and "Where:  component 'calc'" in out and "Hint:" in out


def test_support_bundle_has_everything_but_participant_data(tmp_path):
    from edge.diagnostics import ExperimentError
    from edge.support import make_bundle
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(CRASHY))
    with pytest.raises(ExperimentError):
        run_experiment(Experiment.load(p), dry_run=False, backend="headless", data_dir=str(tmp_path / "data"),
                       participant={"participant": "P-SECRET"}, log=lambda *a: None)
    r = make_bundle(p)
    z = zipfile.ZipFile(r["bundle"])
    names = z.namelist()
    for want in ("environment.json", "experiment.yaml", "validation.txt", "computer_check.txt", "session/session.json",
                 "session/error.txt", "session/report.txt", "README.txt"):
        assert want in names
    blob = b"".join(z.read(n) for n in names)
    assert b"P-SECRET" not in blob and b"<removed>" in blob
    assert "session/trials_wide.csv" not in names
    with_data = zipfile.ZipFile(make_bundle(p, tmp_path / "b2.zip", include_data=True)["bundle"])
    assert b"P-SECRET" not in b"".join(with_data.read(n) for n in with_data.namelist())


# ============================================================================ reproducibility
def test_lock_verify_and_golden_participant(tmp_path):
    from edge.reproduce import lock, verify
    p = _copy_stroop(tmp_path)
    r = lock(p)
    assert r["files"] == 1 and r["trials"] == 20
    v = verify(p)
    assert all(f["level"] == "ok" for f in v["findings"])
    csv_path = p.parent / "stroop.csv"
    csv_path.write_text(csv_path.read_text().replace("RED,red", "RED,blue", 1))
    text = "\n".join(f["what"] + " " + f.get("detail", "") for f in verify(p)["findings"])
    assert "stroop.csv changed since the lock" in text
    assert "the experiment now behaves differently" in text and "first difference at trial" in text
    doc = yaml.safe_load(p.read_text())
    doc["name"] = "stroop2"
    p.write_text(yaml.safe_dump(doc))
    assert any("changed after it was locked" in f["what"] for f in verify(p, golden=False)["findings"])


def test_lock_notices_version_changes(tmp_path, monkeypatch):
    from edge import reproduce
    p = _copy_stroop(tmp_path)
    reproduce.lock(p, golden=False)
    real = reproduce.environment()
    monkeypatch.setattr(reproduce, "environment", lambda: {**real, "edge": "99.0", "packages": {**real["packages"], "pyglet": "9.9"}})
    whats = [f["what"] for f in reproduce.verify(p, golden=False)["findings"]]
    assert any(w.startswith("EDGE ") and "99.0" in w for w in whats)
    assert any(w.startswith("pyglet:") for w in whats)


def test_bundles_carry_trial_list_files_hashes_and_the_lock(tmp_path):
    from edge.reproduce import lock
    from edge.storage import export_bundle, import_bundle, referenced_files
    d = tmp_path / "e"
    _png(d / "images" / "cat.png")
    doc = {"name": "pics", "routines": {"t": {"components": [{"id": "p", "type": "image", "image": "$pic", "duration": 0.5}]}},
           "flow": [{"loop": "L", "conditions": [{"pic": "images/cat.png"}], "children": ["t"]}]}
    (d / "pics.yaml").write_text(yaml.safe_dump(doc))
    assert referenced_files(doc, d) == {"images/cat.png"}
    lock(d / "pics.yaml")
    res = export_bundle(d / "pics.yaml", tmp_path / "pics.edgez")
    z = zipfile.ZipFile(res["bundle"])
    manifest = json.loads(z.read("manifest.json"))
    assert "files/images/cat.png" in z.namelist() and "images/cat.png" in manifest["sha256"]
    assert manifest["environment"]["edge"] and manifest["lock"] == "pics.lock.json"
    out = import_bundle(res["bundle"], tmp_path / "there")
    assert (tmp_path / "there" / "pics.lock.json").exists() and (tmp_path / "there" / "images" / "cat.png").exists()
    from edge.reproduce import verify
    assert not [f for f in verify(out, golden=False)["findings"] if f["level"] in ("warning", "error")]


def test_sessions_record_versions_and_preflight(tmp_path):
    p = tmp_path / "quick.yaml"
    p.write_text(yaml.safe_dump({"name": "quick", "routines": {"a": {"components": [
        {"id": "t", "type": "text", "text": "x", "duration": 0.1}]}}, "flow": ["a"]}))
    s = run_experiment(Experiment.load(p), backend="headless", data_dir=str(tmp_path / "data"), log=lambda *a: None)
    meta = json.loads((Path(s["data_dir"]) / "session.json").read_text())
    assert meta["environment"]["edge"] and "python" in meta["environment"]
    assert meta["preflight"] == {"verdict": "not run"}


# ============================================================================ preflight
def test_preflight_go_and_no_go(tmp_path):
    from edge.preflight import format_preflight, last_preflight, run_preflight
    p = _copy_stroop(tmp_path)
    res = run_preflight(p, computer=False)
    assert res["verdict"] == "go with warnings" or res["verdict"] == "go"
    ids = {s["id"]: s for s in res["sections"]}
    assert ids["test_run"]["status"] == "ok" and ids["measures"]["status"] == "ok" and ids["lock"]["status"] == "info"
    assert "GO" in format_preflight(res)
    from edge.storage import load_document
    assert last_preflight(p, load_document(p).doc)["verdict"] == res["verdict"]
    doc = load_document(p).doc
    doc["name"] = "changed"
    assert last_preflight(p, doc)["verdict"] == "outdated"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"name": "bad", "devices": [{"id": "eye", "type": "tobii"}],
                                   "routines": {"t": {"components": [{"id": "p", "type": "image", "image": "nope.png",
                                                                      "duration": 0.5}]}}, "flow": ["t"]}))
    res = run_preflight(bad, computer=False)
    ids = {s["id"]: s for s in res["sections"]}
    assert res["verdict"] == "no-go"
    assert ids["experiment"]["status"] == "error" and "picture not found" in ids["experiment"]["items"][0]["text"]
    assert ids["software"]["status"] == "error" and "pip install tobii-research" in ids["software"]["items"][0]["hint"]
    assert ids["test_run"]["items"][0]["text"].startswith("skipped")


def test_preflight_catches_a_crash_in_the_test_run(tmp_path):
    from edge.preflight import run_preflight
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(CRASHY))
    res = run_preflight(p, computer=False, save=False)
    tr = next(s for s in res["sections"] if s["id"] == "test_run")
    assert res["verdict"] == "no-go" and "ZeroDivisionError" in tr["items"][0]["text"] and tr["items"][0]["crash"]


def test_huge_pictures_are_flagged(tmp_path):
    from edge.pitfalls import image_size
    _png(tmp_path / "big.png", 5000, 10)
    assert image_size(tmp_path / "big.png") == (5000, 10)
    doc = {"name": "b", "routines": {"t": {"components": [{"id": "p", "type": "image", "image": "big.png", "duration": 0.5}]}},
           "flow": ["t"]}
    assert any("very large picture" in i.message for i in Experiment.from_dict(doc, base_dir=tmp_path).validate())


# ============================================================================ hardware: test devices, measure timing
def test_device_test_reports_rates_and_marker_loopback():
    from edge.devtest import test_device
    r = test_device("sim_eeg", "eeg", seconds=1.2)
    assert r["connected"] and r["streams"]["eeg"]["status"] == "ok" and r["streams"]["eeg"]["marker_back"]["seen"]
    bad = test_device("serial_inputs", "box", {"port": "/dev/does-not-exist"}, seconds=0.5)
    assert not bad["connected"] and bad.get("hint")


def test_timing_test_measures_display_audio_and_triggers(tmp_path):
    import copy
    from edge.report import analyze_session, format_report
    from edge.templates import TEMPLATES
    s = run_experiment(Experiment.from_dict(copy.deepcopy(TEMPLATES["timing_test"]), base_dir=tmp_path), dry_run=True,
                       data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rep = analyze_session(s["data_dir"])
    assert rep["display_latency"]["matched"] == 30 and abs(rep["display_latency"]["mean_ms"] - 8) < 0.5
    assert rep["audio_latency"]["matched"] == 30 and 19 < rep["audio_latency"]["mean_ms"] < 25
    assert rep["streams"]["trig.ttl"]["triggers"]["matched"] == rep["streams"]["trig.ttl"]["triggers"]["expected"]
    text = format_report(rep)
    assert "Audio latency (microphone)" in text and "Display latency (light sensor)" in text


# ============================================================================ closed loop
def test_external_program_drives_the_experiment(tmp_path):
    from edge.devices import messages
    ports = {}
    orig = messages.UDPMessages.connect

    def connect(self):
        orig(self)
        ports["p"] = self.port

    messages.UDPMessages.connect = connect
    try:
        doc = {"name": "cl", "settings": {"window": {"size": [400, 300]}},
               "devices": [{"id": "bci", "type": "udp_messages", "options": {"port": 0, "variables": ["alpha"]}}],
               "variables": {"alpha": 0},
               "routines": {"t": {"duration": 3, "rules": [{"when": "$alpha > 0.5", "do": [{"set": {"high": 1}}, "end_routine"]}],
                                  "components": [{"id": "s", "type": "text", "text": "$f'{devices.bci}'"},
                                                 {"id": "pick", "type": "device_response", "device": "bci", "inputs": ["left", "right"]}]}},
               "flow": ["t"]}
        exp = Experiment.from_dict(doc, base_dir=tmp_path)
        assert not [i for i in exp.validate() if i.level in ("error", "warning")]

        def send():
            while "p" not in ports:
                time.sleep(0.01)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            time.sleep(0.3)
            s.sendto(b'{"event": "left"}', ("127.0.0.1", ports["p"]))
            time.sleep(0.2)
            s.sendto(b'{"alpha": 0.8}', ("127.0.0.1", ports["p"]))
        threading.Thread(target=send, daemon=True).start()
        res = run_experiment(exp, backend="headless", data_dir=str(tmp_path / "d"), log=lambda *a: None, realtime=True)
    finally:
        messages.UDPMessages.connect = orig
    rows = [json.loads(line) for line in (Path(res["data_dir"]) / "trials.jsonl").read_text().splitlines()]
    assert rows[0]["pick.input"] == "left" and rows[0]["high"] == 1 and rows[0]["routine_duration"] < 2.5
    assert (Path(res["data_dir"]) / "streams" / "bci.messages.csv").read_text().count("\n") == 3


def test_live_device_values_in_expressions():
    from edge.devices import create_device
    from edge.devices.messages import parse_message
    dev = create_device("sim_eeg", "eeg")
    dev.connect()
    dev.emit("eeg", 1.0, [float(i) for i in range(9)])
    live = dev.live()
    assert live.Fz == 0.0 and live.eeg.Cz == 1.0 and live.age is not None
    assert parse_message(b'{"a": 1}') == {"a": 1} and parse_message(b"left") == {"event": "left"}
    assert parse_message(b"[1, 2]") == {"event": [1, 2]}
