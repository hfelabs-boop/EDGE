"""Regression tests for the problems QA round 2 found in the redesigned builder and the assistant.

Server behaviour is tested through the builder's HTTP API and the Python functions behind it; the browser code is
checked as text in tests/test_ui_contract.py.
"""
from __future__ import annotations

import copy
import json
import shutil
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from edge.builder.server import BuilderApp, make_handler

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(tmp_path):
    shutil.copytree(ROOT / "examples/stroop", tmp_path / "stroop", ignore=shutil.ignore_patterns("data"))
    shutil.copytree(ROOT / "examples/questionnaire", tmp_path / "questionnaire", ignore=shutil.ignore_patterns("data"))
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, app
    httpd.shutdown()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _stroop(root: Path) -> dict:
    return yaml.safe_load((root / "stroop/stroop.yaml").read_text())


def _stop(app):
    if app.play.player is not None:
        app.play.stop()


# ---------------------------------------------------------------- Try only one screen
def test_one_screen_outside_the_trial_list_starts_with_loop_measures(server):
    """measures.accuracy names the loop 'trials': cutting the flow down to 'instructions' must not make it invalid."""
    from edge.model import Experiment
    from edge.play import single_screen_experiment
    url, root, app = server
    doc = _stroop(root)
    assert any(m.get("loop") == "trials" for m in doc["measures"])
    one = single_screen_experiment(doc, "instructions")
    assert one["flow"] == ["instructions"] and "measures" not in one
    assert not [i for i in Experiment.from_dict(one, base_dir=root / "stroop").validate() if i.level == "error"]
    r = _post(url + "/api/play/start", {"experiment": doc, "path": "stroop/stroop.yaml", "routine": "instructions"})
    _stop(app)
    assert r["ok"] is True, r


def test_feedback_is_tried_together_with_the_screen_whose_answer_it_reads(server):
    from edge.play import single_screen_experiment, single_screen_plan
    url, root, app = server
    doc = _stroop(root)
    assert single_screen_plan(doc, "feedback") == ["trial", "feedback"]
    assert single_screen_plan(doc, "trial") == ["trial"] and single_screen_plan(doc, "instructions") == ["instructions"]
    loop = single_screen_experiment(doc, "feedback", 3)["flow"][0]
    assert loop["loop"] == "trials" and loop["children"] == ["trial", "feedback"] and loop["stop_if"] == "$trials.n >= 2"
    r = _post(url + "/api/play/start", {"experiment": doc, "path": "stroop/stroop.yaml", "routine": "feedback"})
    assert r["ok"] is True and r["screens"] == ["trial", "feedback"]
    for _ in range(3):              # it really runs: answer three trials, no "resp doesn't exist" stop
        time.sleep(0.9)
        for down in (True, False):
            _post(url + "/api/play/input", {"kind": "key", "name": "r", "down": down})
    deadline = time.time() + 20
    f = {}
    while time.time() < deadline:
        f = _get(url + "/api/play/frame")
        if not f.get("running"):
            break
        time.sleep(0.3)
    _stop(app)
    assert not f.get("error"), f.get("error")


def test_a_screen_that_needs_the_rest_says_so_without_validator_paths(server):
    url, root, app = server
    r = _post(url + "/api/play/start", {"experiment": _stroop(root), "path": "stroop/stroop.yaml", "routine": "thanks"})
    assert r["ok"] is False
    assert "“thanks” uses “trials” from earlier in the experiment" in r["error"]
    assert "routines." not in r["error"] and "measures." not in r["error"]


# ---------------------------------------------------------------- the checker: resp.cor is an error
def test_unknown_result_of_a_known_component_is_an_error(server):
    url, root, _ = server
    doc = _stroop(root)
    doc["routines"]["feedback"]["components"][0]["text"] = "$'Correct!' if resp.cor else 'Wrong!'"
    issues = _post(url + "/api/validate", {"experiment": doc, "path": "stroop/stroop.yaml"})["issues"]
    hit = [i for i in issues if "resp.cor" in i["message"]]
    assert hit and hit[0]["level"] == "error" and "Did you mean resp.corr?" in hit[0]["message"]
    # reading the results as a dict is fine: resp.get('rt')
    doc["routines"]["feedback"]["components"][0]["text"] = "$str(resp.get('rt'))"
    issues = _post(url + "/api/validate", {"experiment": doc, "path": "stroop/stroop.yaml"})["issues"]
    assert not [i for i in issues if "resp.get" in i["message"]]
    schema = _get(url + "/api/schema")
    assert schema["components"]["keyboard"]["known_outputs"] == ["corr", "duration", "keys", "rt", "time"]
    assert schema["components"]["survey"]["known_outputs"] == []      # depends on its questions


# ---------------------------------------------------------------- unread assistant code: enforced by the server
def _with_assistant_code(root: Path) -> tuple[dict, str]:
    from edge.assistant.jobs import append_history
    from edge.assistant.tools import code_hashes
    doc = _stroop(root)
    doc["routines"]["scoring"] = {"duration": 0.1, "components": [
        {"id": "score_code", "type": "code", "on_begin": "score = score + 0"}]}
    doc["flow"].insert(1, "scoring")
    h = code_hashes(doc)[("scoring", "score_code")]
    append_history(root / "stroop", "anthropic", "m", "Keep a running score",
                   {"review": [{"kind": "code", "hash": h, "routine": "scoring", "id": "score_code"}]})
    return doc, h


def test_try_it_and_test_runs_refuse_unread_assistant_code_in_any_browser(server):
    url, root, app = server
    doc, h = _with_assistant_code(root)
    body = {"experiment": doc, "path": "stroop/stroop.yaml"}
    for route in ("/api/play/start", "/api/dryrun"):
        r = _post(url + route, body)
        assert r["ok"] is False and r["unread_code"] == [{"routine": "scoring", "id": "score_code", "hash": h}], route
        assert "I've read it" in r["error"]
    assert not (root / "stroop/data/dry_runs").exists() or not list((root / "stroop/data/dry_runs").rglob("trials.csv"))
    # what the panel of a fresh browser learns from the server
    assert _get(url + "/api/assistant/code?exp=stroop/stroop.yaml") == {"written": [h], "reviewed": []}
    # I've read it, in one browser: kept next to the experiment, counted everywhere
    assert _post(url + "/api/assistant/reviewed", {"exp": "stroop/stroop.yaml", "hashes": [h]})["reviewed"] == [h]
    assert json.loads((root / "stroop/.edge/assistant/reviewed.json").read_text()) == [h]
    assert _get(url + "/api/assistant/code?exp=stroop/stroop.yaml")["reviewed"] == [h]
    r = _post(url + "/api/play/start", body)
    _stop(app)
    assert r["ok"] is True
    from edge.preflight import unread_assistant_code
    (root / "stroop/stroop.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    assert unread_assistant_code(root / "stroop/stroop.yaml") == []


def test_reviewed_hashes_from_the_page_still_count(server):
    url, root, app = server
    doc, h = _with_assistant_code(root)
    r = _post(url + "/api/dryrun", {"experiment": doc, "path": "stroop/stroop.yaml", "reviewed_code": [h]})
    assert r.get("ok") is True, r
    bad = urllib.request.Request(url + "/api/assistant/reviewed", data=json.dumps({"exp": "stroop/stroop.yaml", "hashes": "x"}).encode(),
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(bad)
    assert e.value.code == 400


# ---------------------------------------------------------------- "Tested" survives a reload
def test_last_test_ignores_empty_defaults_and_reports_the_last_try(server):
    url, root, app = server
    doc = app.load("stroop/stroop.yaml")["experiment"]
    assert _post(url + "/api/dryrun", {"experiment": copy.deepcopy(doc), "path": "stroop/stroop.yaml"})["ok"]
    seen = copy.deepcopy(doc)
    seen["devices"][0]["options"] = {}            # what drawing the device panel used to add
    r = _post(url + "/api/last_test", {"experiment": seen, "path": "stroop/stroop.yaml"})
    assert r["found"] is True and r["ok"] is True and r["tried"] is None
    assert _post(url + "/api/play/start", {"experiment": doc, "path": "stroop/stroop.yaml"})["ok"]
    _stop(app)
    time.sleep(0.5)
    r = _post(url + "/api/last_test", {"experiment": doc, "path": "stroop/stroop.yaml"})
    assert r["tried"] and r["tried"]["path"].startswith("stroop/data/dry_runs/try/")
    changed = copy.deepcopy(doc)
    changed["routines"]["thanks"]["duration"] = 3
    r = _post(url + "/api/last_test", {"experiment": changed, "path": "stroop/stroop.yaml"})
    assert r["found"] is False and r["tried"] is None


# ---------------------------------------------------------------- Save a copy takes its files along
@pytest.mark.parametrize("src, files", [("stroop/stroop.yaml", ["stroop.csv"]),
                                        ("questionnaire/questionnaire.yaml", ["pages/consent.html", "pages/rating.html"])])
def test_save_a_copy_copies_the_files_it_uses(server, src, files):
    url, root, app = server
    doc = app.load(src)["experiment"]
    doc["name"] = "the_copy"
    r = _post(f"{url}/api/experiment?path=the_copy/the_copy.yaml&fingerprint=&new=1&copy_from={src}", doc)
    for f in files:
        assert (root / "the_copy" / f).is_file(), f
        assert f in r["copied"]
    assert r["missing"] == []
    issues = _post(url + "/api/validate", {"experiment": doc, "path": "the_copy/the_copy.yaml"})["issues"]
    assert not [i for i in issues if i["level"] == "error"], issues
    assert not (root / "the_copy" / "data").exists()           # participant data stays with the original


# ---------------------------------------------------------------- the computer, before and after a session
def test_test_and_try_sessions_never_report_computer_checks(tmp_path):
    from edge.report import analyze_session
    s = tmp_path / "data" / "dry_runs" / "try" / "try_1"
    s.mkdir(parents=True)
    (s / "session.json").write_text(json.dumps({"experiment": "x", "backend": "browser", "system_checks": [
        {"id": "no_display", "level": "error", "title": "No screen found", "fix": "Run participants … 'edge run --dry-run' …"}]}))
    (s / "events.jsonl").write_text("")
    rep = analyze_session(s)
    assert rep["computer"] == []
    assert not any("COMPUTER" in v for v in rep.get("verdict", []))


def test_preflight_computer_row_sees_software_rendering_and_no_sound():
    from edge.syscheck import check_graphics_and_sound
    out = {c.id: c for c in check_graphics_and_sound(True, {"renderer": "llvmpipe (LLVM 20.1.2, 256 bits)", "audio": "SilentDriver"})}
    assert out["display_driver"].level == "error" and "llvmpipe" in out["display_driver"].title
    assert out["sound_device"].level == "warning" and "sounds will not play" in out["sound_device"].detail
    assert check_graphics_and_sound(False, {"renderer": "NVIDIA GeForce RTX 4070/PCIe/SSE2", "audio": "SilentDriver"})[1].level == "info"
    assert [c.level for c in check_graphics_and_sound(True, {"renderer": "NVIDIA GeForce", "audio": "XAudio2Driver"})] == ["ok"]


def test_vsync_error_says_what_to_do():
    src = (ROOT / "edge/runtime.py").read_text()
    assert "vsync appears disabled: the screen isn't synchronised, so stimulus times can be off by a" in src
    assert "Check this computer" in src


def test_preflight_device_rows_carry_what_the_builder_words_them_from(tmp_path):
    from edge.model import Experiment
    from edge.preflight import device_items
    exp = Experiment.from_dict({"name": "x", "devices": [{"id": "eeg", "type": "lsl_inlet", "options": {"stream_type": "EEG"},
                                                            "required": False}],
                                "routines": {"a": {"duration": 0.1, "components": []}}, "flow": ["a"]}, base_dir=tmp_path)
    [it] = device_items(exp, timeout=0.5)
    assert it["device_id"] == "eeg" and it["device_type"] == "lsl_inlet" and it["required"] is False
    assert it["hint"].startswith("Optional: the session can run without it")
