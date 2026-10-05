"""What is measured and recorded: declared outputs, the recording plan, measures, the live monitor."""

import copy
import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

from edge.components import component_registry
from edge.devices import device_registry
from edge.engine import run_experiment
from edge.measures import (describe, measure_checks, measure_table, recording_plan, suggest_measures,
                           validate_measures)
from edge.model import Experiment
from edge.templates import TEMPLATES

ROOT = Path(__file__).resolve().parent.parent
STROOP = ROOT / "examples" / "stroop"


def _stroop(tmp_path, measures=None, edit=None):
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data"))
    d = yaml.safe_load((tmp_path / "s" / "stroop.yaml").read_text())
    if measures is not None:
        d["measures"] = measures
    if edit:
        edit(d)
    return Experiment.from_dict(d, base_dir=tmp_path / "s")


def _dry(exp, tmp_path, **kw):
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None, **kw)
    return Path(s["data_dir"])


# ============================================================================ declared outputs
def test_every_component_and_streaming_device_declares_what_it_records():
    for name, cls in component_registry().items():
        assert isinstance(cls.outputs, dict), name
        for key, meta in cls.outputs.items():
            assert meta.get("desc") and "{who}" in meta["desc"], (name, key)
            assert meta.get("kind") in ("rt", "accuracy", "response", "answer", "score", "gaze", "timing", "other"), (name, key)
        assert "outputs" in cls.describe()
    for name, cls in device_registry().items():
        streams = cls.planned_streams({})
        if "stream" in cls.capabilities and name != "mindware":
            assert streams and all(s["name"] and s["what"] for s in streams), name
        if "stream" not in cls.capabilities:
            assert streams == [] and cls.records_note({}), name


@pytest.mark.parametrize("name", ["freeview_eyetracking", "eeg_oddball", "staircase", "online_questionnaire",
                                  "tutorial_practice", "tutorial_gaze", "tutorial_survey", "tutorial_stroop"])
def test_recorded_columns_are_all_declared(name, tmp_path):
    """Nothing a component writes into the data is missing from its declaration (and the dictionary)."""
    exp = Experiment.from_dict(copy.deepcopy(TEMPLATES[name]), base_dir=tmp_path)
    plan = recording_plan(exp)
    declared = {o["column"] for c in plan["components"] for o in c["outputs"]}
    comp_ids = {c["id"] for c in plan["components"]}
    root = _dry(exp, tmp_path)
    rows = [json.loads(line) for line in (root / "trials.jsonl").read_text().splitlines() if line.strip()]
    written = {k for r in rows for k, v in r.items() if k.split(".")[0] in comp_ids and "." in k and v is not None}
    assert written - declared == set(), f"{name}: undeclared columns {sorted(written - declared)}"
    with (root / "data_dictionary.csv").open(encoding="utf-8-sig") as f:
        dd = {r["column"]: r for r in csv.DictReader(f)}
    for col in written & set(dd):
        assert not dd[col]["description"].startswith(col.rpartition(".")[2] + " of"), col   # a real description


def test_planned_outputs_follow_the_settings(tmp_path):
    reg = component_registry()
    assert "corr" not in reg["keyboard"].planned_outputs({})
    assert "corr" in reg["keyboard"].planned_outputs({"correct": "$key"})
    assert "path" in reg["mouse"].planned_outputs({"track": True})
    assert set(reg["variable"].planned_outputs({"set": {"score": 1}})) == {"score"}
    page = '<form><input name="age" type="number"><select name="hand"><option>left</option></select></form>'
    assert {"age", "hand", "submitted"} <= set(reg["html"].planned_outputs({"html": page}))
    (tmp_path / "p.html").write_text(page)
    assert "age" in reg["html"].planned_outputs({"file": "p.html"}, tmp_path)
    sv = reg["survey"].planned_outputs({"questions": [{"instrument": "gad7"}]})
    assert sv["gad7_total"]["kind"] == "score" and sv["gad7_1"]["kind"] == "answer"


# ============================================================================ the recording plan
def test_recording_plan_lists_everything(tmp_path):
    plan = recording_plan(_stroop(tmp_path))
    assert plan["participant"] == ["participant", "session"]
    assert plan["loops"][0]["loop"] == "trials" and "congruent" in plan["loops"][0]["columns"]
    resp = next(c for c in plan["components"] if c["id"] == "resp")
    assert {o["key"] for o in resp["outputs"]} == {"keys", "rt", "corr", "time"}
    assert plan["columns"]["resp.rt"]["units"] == "s" and plan["columns"]["resp.rt"]["kind"] == "rt"
    eye = next(d for d in plan["devices"] if d["id"] == "eyetracker")
    assert eye["streams"][0]["srate"] == 150.0 and eye["files"] == ["streams/eyetracker.gaze.csv"]
    assert "TTL" in next(d for d in plan["devices"] if d["id"] == "physio")["note"]
    assert any(f["file"] == "measures.csv" for f in plan["always"])
    plan = recording_plan(_stroop(tmp_path / "b", edit=lambda d: d["routines"]["trial"]["components"][0].update(save=False)))
    assert plan["columns"]["fix.onset"]["saved"] is False


def test_suggested_measures(tmp_path):
    ms = suggest_measures(_stroop(tmp_path, measures=None, edit=lambda d: d.pop("measures", None)))
    by = {m["id"]: m for m in ms}
    assert by["rt"]["column"] == "resp.rt" and by["rt"]["trials"] == "$resp.corr == 1" and by["rt"]["loop"] == "trials"
    assert by["accuracy"]["summary"] == "proportion"
    assert [m["column"] for m in ms if m["role"] == "factor"] == ["congruent"]
    assert not any(m["column"].startswith("go.") for m in ms)        # "press space" is not a measure


def test_wizard_declares_measures_and_skips_practice():
    from edge.wizard import build_experiment
    doc = build_experiment({"practice": {"enabled": True, "until": 0.8}})
    ms = {m["id"]: m for m in doc["measures"]}
    assert ms["rt"]["loop"] == "trials" and ms["accuracy"]["column"].endswith(".corr")
    assert validate_measures(Experiment.from_dict(doc)) == []


# ============================================================================ validation
def test_measure_mistakes_are_explained(tmp_path):
    exp = _stroop(tmp_path, measures=[
        {"id": "rt", "column": "resp.rtt"},
        {"id": "rt", "column": "resp.rt", "role": "dv", "summary": "avg"},
        {"column": "inkk", "role": "factor"},
        {"id": "x", "column": "resp.rt", "loop": "blocks", "trials": "$resp.corr ==", "expect": [3, 1], "colour": 1},
        {"id": "f", "column": "fix.onset"},
        {"label": "no column"},
    ], edit=lambda d: d["routines"]["trial"]["components"][0].update(save=False))
    msgs = [str(i) for i in validate_measures(exp)]
    text = "\n".join(msgs)
    assert "records keys, rt, corr, time, not 'rtt'" in text and "did you mean resp.rt" in text
    assert "two measures have the same id" in text and "unknown role 'dv'" in text and "unknown summary 'avg'" in text
    assert "no column called 'inkk'" in text and "did you mean ink" in text
    assert "no loop called 'blocks'" in text and "expect must be" in text and "isn't a valid expression" in text
    assert "unknown measure setting 'colour'" in text
    assert "'fix' is not saved" in text and "needs a 'column'" in text
    assert any("measures" in i.where for i in exp.validate())


def test_measures_survive_saving_and_describe(tmp_path):
    exp = _stroop(tmp_path)
    assert exp.to_dict()["measures"] == exp.measures
    lines = describe(exp)
    assert lines[0].startswith("Reaction time: outcome (dependent variable) from resp.rt, median")
    assert validate_measures(exp) == []


# ============================================================================ after a session
def test_session_writes_measures_and_checks_them(tmp_path):
    from edge.report import analyze_session, format_report
    exp = _stroop(tmp_path, measures=[
        {"id": "rt", "label": "RT", "column": "resp.rt", "trials": "$resp.corr == 1", "loop": "trials",
         "summary": "median", "units": "s", "expect": [0.15, 0.3]},
        {"id": "acc", "column": "resp.corr", "loop": "trials", "summary": "proportion"},
        {"id": "ghost", "column": "nothing_here"},
        {"id": "congruent", "role": "factor", "column": "congruent"},
    ])
    root = _dry(exp, tmp_path)
    with (root / "measures.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rt = [r for r in rows if r["measure"] == "rt"]
    assert [r["congruent"] for r in rt] == ["(all)", "0", "1"]
    assert 0.1 < float(rt[0]["value"]) < 3 and rt[0]["units"] == "s"
    acc = next(r for r in rows if r["measure"] == "acc" and r["congruent"] == "(all)")
    assert 0 <= float(acc["value"]) <= 1 and int(acc["n"]) == 18
    rep = analyze_session(root)
    assert {v["measure"] for v in rep["measures"]["values"]} == {"rt", "acc", "ghost"}
    verdict = "\n".join(rep["verdict"])
    assert "ghost: column nothing_here was never recorded" in verdict
    assert "outside the expected 0.15–0.3" in verdict
    assert "Measures" in format_report(rep) and "RT:" in format_report(rep)


def test_measure_table_and_checks_without_a_session():
    src = {"measures": [{"id": "rt", "column": "r.rt", "summary": "mean", "expect": [0.2, 1]},
                        {"id": "cond", "role": "factor", "column": "cond"}]}
    rows = [{"cond": "a", "r.rt": 0.5, "loop": "t"}, {"cond": "a", "r.rt": None, "loop": "t"},
            {"cond": "b", "r.rt": 2.0, "loop": "t"}, {"cond": "b", "r.rt": None, "loop": "t"}]
    cols, out = measure_table(src, rows)
    assert cols[-4:] == ["n", "missing", "value", "units"]
    assert [(r["cond"], r["value"], r["missing"]) for r in out] == [("(all)", 1.25, 2), ("a", 0.5, 1), ("b", 2.0, 1)]
    notes = " ".join(n["message"] for n in measure_checks(src, rows))
    assert "missing on 2 of 4 trials" in notes and "outside the expected" in notes


# ============================================================================ the live monitor
def test_monitor_reports_progress_measures_and_devices(tmp_path, monkeypatch, capsys):
    from edge.monitor import parse
    monkeypatch.setenv("EDGE_MONITOR", "1")
    _dry(_stroop(tmp_path), tmp_path, simulate_devices=True)
    events = [e for e in (parse(line) for line in capsys.readouterr().out.splitlines()) if e]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "end"
    start, end = events[0], events[-1]
    assert start["expected_trials"] == 18 and [m["id"] for m in start["measures"]] == ["rt", "accuracy", "congruent"]
    assert set(start["devices"]) >= {"eyetracker", "eeg", "physio"}
    trials = [e for e in events if e["type"] == "trial"]
    assert max(t["n"] for t in trials) == 18 == end["trials"]
    assert any("rt" in t["values"] for t in trials) and any(t["factors"].get("congruent") is not None for t in trials)
    assert end["running"]["accuracy"]["n"] == 18 and not end["aborted"]


def test_monitor_device_health_flags_silent_streams(tmp_path):
    from edge.monitor import Monitor

    class Dev:
        type_name, errors = "x", []
        def __init__(self, srate):
            from edge.devices.base import StreamInfo
            self.streams = {"s": StreamInfo("s", ["a"], srate)}
            self.n_samples = {"s": 0}

    class Sess:
        devices = {"amp": Dev(100.0)}
        exp = type("E", (), {"measures": None})()

    m = Monitor(Sess(), emit=lambda e: None)
    m.t0 -= 5                                  # pretend the session has been running a while
    assert m.device_health()["amp"]["streams"]["s"]["status"] == "silent"
    Sess.devices["amp"].n_samples["s"] = 500
    h = m.device_health()["amp"]["streams"]["s"]
    assert h["samples"] == 500 and h["status"] in ("ok", "low")


def test_stop_file_ends_the_session_and_keeps_the_data(tmp_path, monkeypatch):
    stop = tmp_path / "stop"
    stop.touch()
    monkeypatch.setenv("EDGE_MONITOR", "1")
    monkeypatch.setenv("EDGE_STOP_FILE", str(stop))
    root = _dry(_stroop(tmp_path), tmp_path)
    meta = json.loads((root / "session.json").read_text())
    assert meta["aborted"] is True and (root / "trials.jsonl").exists()


# ============================================================================ builder and MCP
def test_builder_recording_endpoint_and_stop(tmp_path):
    from edge.builder.server import BuilderApp
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data"))
    app = BuilderApp(tmp_path)
    doc = yaml.safe_load((tmp_path / "s" / "stroop.yaml").read_text())
    r = app.recording(doc, "s/stroop.yaml")
    assert r["lines"] and r["issues"] == [] and r["suggestions"] == [] and "outcome" in r["roles"]
    doc.pop("measures")
    r = app.recording(doc, "s/stroop.yaml")
    assert {m["id"] for m in r["suggestions"]} == {"rt", "accuracy", "congruent"}
    assert app.run_stop("nope") == {"error": "unknown run"}


def test_mcp_describe_recording_and_set_measures(tmp_path):
    import asyncio
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data"))
    mcp = create_server(tmp_path)

    def call(name, **kw):
        r = asyncio.run(mcp.call_tool(name, kw))
        content = r[0] if isinstance(r, tuple) else r
        return json.loads(content[0].text)

    d = call("describe_recording", path="s/stroop.yaml")
    assert len(d["measures"]) == 3 and any(c["id"] == "resp" for c in d["components"])
    r = call("set_measures", path="s/stroop.yaml", measures=[{"id": "acc", "column": "resp.corr", "summary": "proportion"}])
    assert r["ok"] and r["result"] == ["acc: outcome (dependent variable) from resp.corr, proportion"]
    assert yaml.safe_load((tmp_path / "s" / "stroop.yaml").read_text())["measures"][0]["id"] == "acc"
    assert "acc" in call("describe_experiment", path="s/stroop.yaml")["measures"][0]
