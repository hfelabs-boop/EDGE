"""Regression tests for the usability/integration fixes in sessions, reports, preflight and devices (group A1)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from edge.backends.headless import HeadlessBackend
from edge.cli import main
from edge.engine import Runner, run_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant
from edge.report import analyze_session, format_report
from edge.runtime import MarkerCodebook, Session, planned_marker_labels
from edge.templates import TEMPLATES, write_template

ROOT = Path(__file__).resolve().parent.parent
STROOP = ROOT / "examples" / "stroop"
QUIET = lambda *a: None  # noqa: E731


def _copy_stroop(tmp_path: Path) -> Path:
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data", "exports", "*.lock.json",
                                                                         "*.preflight.json"))
    return tmp_path / "s" / "stroop.yaml"


TIMED = {"name": "timed", "routines": {"trial": {"duration": 0.5, "components": [
    {"id": "t", "type": "text", "text": "$word"}]}},
    "flow": [{"loop": "trials", "conditions": [{"word": "a"}, {"word": "b"}], "repeats": 10, "children": ["trial"]}]}


# ------------------------------------------------------------------ cli#0 / data#2 / docs#2: where test runs go
def test_cli_dry_run_goes_to_dry_runs_and_stays_out_of_exports(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    assert main(["run", str(p), "--dry-run", "-p", "900"]) == 0
    assert "dry_runs" in capsys.readouterr().out
    data = p.parent / "data"
    assert [d.name.split("_")[0] for d in (data / "dry_runs").iterdir()] == ["900"]
    assert not [d for d in data.iterdir() if d.name != "dry_runs"], "nothing next to the real sessions"
    from edge.export import find_sessions
    assert find_sessions(data) == [] and len(find_sessions(data, include_dry_runs=True)) == 1
    # the Python API behaves the same as the CLI, MCP and the builder
    s = run_experiment(Experiment.load(p), dry_run=True, log=QUIET)
    assert Path(s["data_dir"]).parent == data / "dry_runs"


# ------------------------------------------------------------------ cli#1: plain headless backend
def test_headless_backend_without_participant_stops_with_an_explanation(tmp_path):
    p = write_template("blank", tmp_path / "b")
    t0 = time.monotonic()
    with pytest.raises(RuntimeError) as e:
        run_experiment(Experiment.load(p), backend="headless", log=QUIET)
    assert time.monotonic() - t0 < 60
    assert "--dry-run" in str(e.value) and "headless-realtime" in str(e.value)
    # an experiment that runs by itself (only timed screens) still works on the plain headless backend
    s = run_experiment(Experiment.from_dict(copy.deepcopy(TIMED), base_dir=tmp_path), backend="headless",
                       data_dir=str(tmp_path / "d"), log=QUIET)
    assert not s["aborted"] and s["timing"]["frames"] > 500


# ------------------------------------------------------------------ cli#2: SIGTERM / SIGHUP finish the session
@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX signals")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_closing_edge_finishes_the_session(tmp_path, sig):
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(TIMED))
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, "-m", "edge", "run", "t.yaml", "--backend", "headless-realtime", "-p", "K1"],
                            cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not list(tmp_path.glob("data/K1_*/trials.jsonl")):
        time.sleep(0.1)
    time.sleep(1.2)
    proc.send_signal(getattr(signal, sig))
    out, _ = proc.communicate(timeout=30)
    folder = next(tmp_path.glob("data/K1_*"))
    meta = json.loads((folder / "session.json").read_text())
    assert meta["aborted"] and meta["stop_reason"].startswith("EDGE was") and meta["errors"] == []
    assert "stopped early" in out and str(folder.name) in out
    rep = analyze_session(folder)
    assert rep["verdict"][0].startswith("STOPPED EARLY (EDGE was") and "of 20 trials" in rep["verdict"][0]


# ------------------------------------------------------------------ cli#3 / data#14: Ctrl+C and the report
class _CtrlC(HeadlessBackend):
    def flip(self):
        if self.n_flips == 100:
            raise KeyboardInterrupt
        return super().flip()


def test_ctrl_c_in_a_real_session_saves_and_the_report_says_stopped_early(tmp_path):
    exp = Experiment.from_dict(copy.deepcopy(TIMED), base_dir=tmp_path)
    logs = []
    s = Runner(Session(exp, _CtrlC(), data_dir=tmp_path / "data", log=logs.append)).run()   # returns, no exception
    assert s["aborted"] and s["stop_reason"] == "Ctrl+C was pressed" and s["errors"] == []
    assert any("stopped early (Ctrl+C was pressed) after 3 trials" in m and s["data_dir"] in m for m in logs)
    rep = analyze_session(s["data_dir"])
    assert rep["verdict"][0].startswith("STOPPED EARLY (Ctrl+C was pressed) after 3 of 20 trials")
    assert "runtime error" not in format_report(rep)
    # a session saved by an older EDGE (Ctrl+C logged as an error) reads the same way
    sj = Path(s["data_dir"]) / "session.json"
    meta = json.loads(sj.read_text())
    meta.pop("stop_reason")
    meta["errors"] = ["KeyboardInterrupt: "]
    sj.write_text(json.dumps(meta))
    old = analyze_session(s["data_dir"])
    assert "Ctrl+C" in old["verdict"][0] and not any(v.startswith("ERROR") for v in old["verdict"])


def test_report_names_errors_and_marks_test_runs(tmp_path):
    s = run_experiment(Experiment.from_dict(copy.deepcopy(TEMPLATES["timing_test"]), base_dir=tmp_path), dry_run=True,
                       data_dir=str(tmp_path / "d"), log=QUIET)
    text = format_report(analyze_session(s["data_dir"]))
    assert "TEST RUN" in text and "Display latency (light sensor) (simulated)" in text
    sj = Path(s["data_dir"]) / "session.json"
    meta = json.loads(sj.read_text())
    meta["errors"] = ["marker 'x' to ttl failed: port closed"]
    sj.write_text(json.dumps(meta))
    assert "ERROR: marker 'x' to ttl failed: port closed" in analyze_session(s["data_dir"])["verdict"]


def test_report_reads_a_session_edge_could_not_finish(tmp_path):
    s = run_experiment(Experiment.from_dict(copy.deepcopy(TIMED), base_dir=tmp_path), backend="headless",
                       data_dir=str(tmp_path / "d"), log=QUIET)
    root = Path(s["data_dir"])
    (root / "session.json").unlink()          # killed before it could be written (power cut, kill -9)
    with (root / "trials.jsonl").open("a") as f:
        f.write('{"routine": "tri')
    rep = analyze_session(root)
    assert rep["verdict"][0].startswith("INCOMPLETE") and rep["trials"] == 20
    with pytest.raises(FileNotFoundError, match="not an EDGE session folder"):
        analyze_session(tmp_path)


# ------------------------------------------------------------------ cli#14, data#10, mcp#6, mcp#33, docs#19, wizard#21
def test_oddball_template_test_run_is_plausible_and_ok(tmp_path):
    p = write_template("eeg_oddball", tmp_path / "o")
    s = run_experiment(Experiment.load(p), dry_run=True, participant={"participant": "1"}, log=QUIET)
    rep = analyze_session(s["data_dir"])
    assert rep["verdict"][0].startswith("OK"), rep["verdict"]
    rows = [json.loads(line) for line in (Path(s["data_dir"]) / "trials.jsonl").read_text().splitlines()]
    std = [r for r in rows if r.get("kind") == "standard"]
    assert sum(r["resp.corr"] for r in std) / len(std) >= 0.75, "withholds on most standards"
    assert "response" in rep["markers"]["sent_after_event_ms"]
    assert "sent after the response itself" in format_report(rep)


def test_marker_alignment_judges_flip_and_response_markers_fairly():
    from edge.report import _marker_error
    flip = {"time": 10.0, "on_flip": True, "delivered": {"ttl": 10.0}}
    resp = {"time": 10.0, "on_flip": False, "delivered": {"ttl": 10.016}}
    assert _marker_error(flip, 10.016, "ttl") == pytest.approx(0.016)
    assert _marker_error(resp, 10.016, "ttl") == 0.0 and _marker_error(resp, 10.0, "ttl") == 0.0
    assert _marker_error(resp, 10.03, "ttl") == pytest.approx(0.014)
    from edge.report import _verdict
    rep = {"streams": {"eeg.eeg": {"sample_period_ms": 4.0, "triggers": {
        "found": 3, "expected": 3, "matched": 3, "latency_max_abs_ms": 20.0,
        "max_abs_ms_by_label": {"target": 20.0, "fix": 1.0}}}}}
    v = _verdict(rep)
    assert "target 20 ms" in v[0] and "fix" not in v[0]


def test_virtual_participant_withholds_when_no_response_is_correct():
    class Spec:
        duration = 1.0
        duration_frames = None

    class Comp:
        spec, type_name, t_start = Spec(), "keyboard", 0.0

    class Be:
        def __init__(self):
            self.pressed = 0

        def press(self, key, at):
            self.pressed += 1

        def clock(self):
            return 0.0
    be = Be()
    vp = VirtualParticipant(seed=1, accuracy=0.9, respond_prob=1.0)
    for _ in range(200):
        vp.respond(Comp(), ["space"], "none", be)
    assert 5 <= be.pressed <= 40          # ~10% false alarms


# ------------------------------------------------------------------ cli#15: the measures hint works without the builder
def test_preflight_measures_hint_has_a_yaml_example(tmp_path):
    from edge.preflight import run_preflight
    p = write_template("blank", tmp_path / "b")
    res = run_preflight(p, computer=False, save=False)
    item = next(s for s in res["sections"] if s["id"] == "measures")["items"][0]
    assert "measures: [{id: rt, column: go.rt" in item["hint"] and "edge help" in item["hint"]


# ------------------------------------------------------------------ cli#18: one definition of a trial
def test_lock_preflight_and_report_count_the_same_trials(tmp_path):
    from edge.preflight import run_preflight
    from edge.reproduce import lock, lock_path, verify
    p = _copy_stroop(tmp_path)
    assert lock(p)["trials"] == 18
    v = verify(p)
    assert any("same 18 trials" in f["what"] for f in v["findings"])
    tr = next(s for s in run_preflight(p, computer=False, save=False)["sections"] if s["id"] == "test_run")
    assert "(18 trials)" in tr["items"][0]["text"]
    # a lock written before this change (n_trials = all rows) still verifies without a false alarm
    lk = json.loads(lock_path(p).read_text())
    lk["golden"]["n_trials"] = lk["golden"].pop("n_steps")
    lock_path(p).write_text(json.dumps(lk))
    assert not [f for f in verify(p)["findings"] if f["level"] in ("warning", "error")]


# ------------------------------------------------------------------ cli#21: simulated device tests say so; liblsl quiet
def test_device_test_says_when_it_simulates(tmp_path):
    from edge.devtest import test_experiment_device
    exp = Experiment.load(_copy_stroop(tmp_path))
    r = test_experiment_device(exp, "eeg", seconds=0.3, simulate=True)
    assert r["connected"] and r["simulated"] == "sim_eeg" and r["messages"][0].startswith("SIMULATED")


def test_liblsl_logs_are_kept_off_the_terminal_unless_the_lab_has_its_own_config(tmp_path, monkeypatch):
    from edge import clock
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    clock._quiet_liblsl()
    assert os.environ["LSLAPICFG"].endswith("lsl_api.cfg") and "level = -2" in Path(os.environ["LSLAPICFG"]).read_text()
    monkeypatch.delenv("LSLAPICFG")
    (tmp_path / "lsl_api").mkdir()
    (tmp_path / "lsl_api" / "lsl_api.cfg").write_text("[ports]\nIPv6 = disable\n")
    clock._quiet_liblsl()
    assert "LSLAPICFG" not in os.environ


# ------------------------------------------------------------------ cli#25: report formatting
def test_report_has_no_python_none_or_empty_headings(tmp_path):
    p = write_template("blank", tmp_path / "b")
    s = run_experiment(Experiment.load(p), dry_run=True, log=QUIET)
    text = format_report(analyze_session(s["data_dir"]))
    assert "Streams: none" in text and "None" not in text
    from edge.report import _pm
    assert _pm(0.041, None) == "0.041" and _pm(1.0, 0.5) == "1.0 ± 0.5"


def test_questionnaire_example_passes_its_own_checks():
    exp = Experiment.load(ROOT / "examples" / "questionnaire" / "questionnaire.yaml")
    assert not [i for i in exp.validate() if "same name as the trial-list column" in i.message]
    for ex in ("questionnaire/questionnaire.yaml", "stroop/stroop.yaml"):
        assert "examples/" not in yaml.safe_load((ROOT / "examples" / ex).read_text())["description"]


# ------------------------------------------------------------------ data#0: stable trigger codes
def test_trigger_codes_do_not_depend_on_trial_order(tmp_path):
    p = _copy_stroop(tmp_path)
    books = []
    for seed in (1, 2, 3, 4):
        doc = yaml.safe_load(p.read_text())
        doc["settings"]["seed"] = seed
        s = run_experiment(Experiment.from_dict(doc, base_dir=p.parent), dry_run=True, data_dir=str(tmp_path / "d"),
                           log=QUIET)
        books.append(s["marker_codebook"])
    assert all(b == books[0] for b in books)
    assert books[0]["session_start"] == 1 and books[0]["word_congruent"] < books[0]["word_incongruent"]
    plan = planned_marker_labels(Experiment.load(p))
    assert {"word_congruent", "word_incongruent", "session_start", "session_end"} <= set(plan)
    cb = MarkerCodebook({"word_congruent": 9}, plan)
    assert cb.codes["word_congruent"] == 9 and len(set(cb.codes.values())) == len(cb.codes)


def test_preflight_warns_when_trigger_codes_depend_on_responses(tmp_path):
    from edge.preflight import run_preflight
    doc = {"name": "resp_codes", "devices": [{"id": "ttl", "type": "ttl_loopback"}],
           "routines": {"t": {"components": [{"id": "resp", "type": "keyboard", "keys": ["f", "j"], "duration": 1.0,
                                              "end_routine": True, "response_marker": "$f'resp_{resp.keys}'"}]}},
           "flow": [{"loop": "trials", "repeats": 6, "children": ["t"]}]}
    (tmp_path / "r.yaml").write_text(yaml.safe_dump(doc))
    tr = next(s for s in run_preflight(tmp_path / "r.yaml", computer=False, save=False)["sections"] if s["id"] == "test_run")
    warn = [i for i in tr["items"] if "trigger codes" in i["text"]]
    assert warn and "resp_" in warn[0]["text"] and "markers: {codes:" in warn[0]["hint"]


# ------------------------------------------------------------------ data#7: staircase threshold in the report
def test_report_shows_the_staircase_threshold(tmp_path):
    p = write_template("staircase", tmp_path / "st")
    s = run_experiment(Experiment.load(p), dry_run=True, log=QUIET)
    text = format_report(analyze_session(s["data_dir"]))
    assert "Staircase stairs: threshold" in text and "stairs_threshold" in text


# ------------------------------------------------------------------ data#12: edge align and common file formats
def _session_with_codes(tmp_path) -> Path:
    s = run_experiment(Experiment.load(_copy_stroop(tmp_path)), dry_run=True, log=QUIET)
    return Path(s["data_dir"])


def test_align_reads_common_event_exports(tmp_path):
    from edge.align import AlignError, align
    sess = _session_with_codes(tmp_path)
    ev = [json.loads(line) for line in (sess / "events.jsonl").read_text().splitlines()]
    ev = [e for e in ev if e.get("code") is not None]
    files = {"ms.csv": ("time,code", lambda e: f"{(e['time'] - 990.5) * 1000:.1f},{e['code']}"),
             "biolab.csv": ("Time (s),Event", lambda e: f"{e['time'] - 990.5:.4f},{e['code']}"),
             "semi.csv": ("time;code", lambda e: f"{e['time'] - 990.5:.4f};{e['code']}".replace(".", ",")),
             "bv.csv": ("Latency [ms],Description", lambda e: f"{(e['time'] - 990.5) * 1000:.1f},S {e['code']:>2}")}
    for name, (head, fmt) in files.items():
        (tmp_path / name).write_text(head + "\n" + "\n".join(fmt(e) for e in ev) + "\n")
        r = align(sess, tmp_path / name)
        assert r["matched"] == len(ev), name
        assert ("/ 1000" in r["usage"]) == (name in ("ms.csv", "bv.csv")), name
    (tmp_path / "bad.csv").write_text("foo,bar\n1,2\n")
    with pytest.raises(AlignError, match="its columns are: foo, bar"):
        align(sess, tmp_path / "bad.csv")
    with pytest.raises(AlignError, match="not an EDGE session folder"):
        align(tmp_path, tmp_path / "bad.csv")


# ------------------------------------------------------------------ data#17, docs#11, wizard#18: different participants
def test_each_test_run_is_a_different_but_reproducible_participant(tmp_path):
    p = _copy_stroop(tmp_path)

    def rts(seed: int | None) -> list:
        doc = yaml.safe_load(p.read_text())
        doc["settings"]["seed"] = seed
        s = run_experiment(Experiment.from_dict(doc, base_dir=p.parent), dry_run=True, data_dir=str(tmp_path / "d"),
                           log=QUIET)
        assert s["virtual_participant"]["seed"] == s["seed"]
        rows = [json.loads(line) for line in (Path(s["data_dir"]) / "trials.jsonl").read_text().splitlines()]
        return sorted(r["resp.rt"] for r in rows if r.get("resp.rt"))
    assert rts(11) != rts(12)
    assert rts(11) == rts(11), "the same session seed gives the same participant"
    a, b = VirtualParticipant(seed=0), VirtualParticipant(seed=0)     # the lock's golden participant stays fixed
    assert [a.rt() for _ in range(5)] == [b.rt() for _ in range(5)]


# ------------------------------------------------------------------ mcp#29, docs#17: a session that can't start
class _NoScreen(HeadlessBackend):
    def open(self, window):
        raise RuntimeError("NoSuchDisplayException: Cannot connect to None")


def test_a_session_that_cannot_start_leaves_no_folder(tmp_path):
    exp = Experiment.from_dict(copy.deepcopy(TIMED), base_dir=tmp_path)
    with pytest.raises(Exception):
        Runner(Session(exp, _NoScreen(), data_dir=tmp_path / "data", log=QUIET)).run()
    assert not (tmp_path / "data").exists() or not list((tmp_path / "data").iterdir())
    doc = copy.deepcopy(TIMED)
    doc["devices"] = [{"id": "box", "type": "serial_inputs", "options": {"port": "/dev/does-not-exist"}, "required": True}]
    with pytest.raises(Exception):
        run_experiment(Experiment.from_dict(doc, base_dir=tmp_path), backend="headless", data_dir=str(tmp_path / "data"),
                       log=QUIET)
    assert not (tmp_path / "data").exists() or not list((tmp_path / "data").iterdir())


# ------------------------------------------------------------------ docs#6, install#14: doctor and preflight see what's missing
def test_no_screen_and_missing_window_library_are_reported(monkeypatch):
    from edge import syscheck
    monkeypatch.setattr(syscheck, "screens", lambda: [])
    monkeypatch.setattr(syscheck, "no_display_reason", lambda: "NoSuchDisplayException: Cannot connect")
    assert any(c.id == "no_display" and c.level == "error" for c in syscheck.check_screens({}))
    import importlib.util
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pyglet" else real(name, *a))
    checks = syscheck.run_checks()
    assert any(c.id == "software:pyglet" and c.level == "error" for c in checks)
    assert "No problems found" not in syscheck.format_checks(checks)


def test_preflight_tries_the_devices(tmp_path):
    from edge.model import DeviceSpec
    from edge.preflight import device_items

    class E:
        devices = [DeviceSpec.from_dict({"id": "box", "type": "serial_inputs", "options": {"port": "/dev/does-not-exist"},
                                         "required": True}),
                   DeviceSpec.from_dict({"id": "pedal", "type": "serial_inputs", "options": {"port": "/dev/nope"},
                                         "required": False}),
                   DeviceSpec.from_dict({"id": "eeg", "type": "sim_eeg"})]
    items = {i["text"].split("'")[1]: i for i in device_items(E(), timeout=3)}
    assert items["box"]["level"] == "error" and "not reachable" in items["box"]["text"]
    assert items["pedal"]["level"] == "warning" and "but would not record it" in items["pedal"]["hint"]
    assert items["eeg"]["level"] == "warning" and "simulator" in items["eeg"]["text"]
