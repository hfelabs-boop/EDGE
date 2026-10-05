"""Features for people new to experiment building: plain-language errors, the "is this name defined
here?" check, the design wizard, Try it (play in the builder), the run dialog helpers and the launcher."""

import itertools
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import expressions
from edge.builder.server import BuilderApp, make_handler
from edge.cli import main
from edge.engine import run_experiment
from edge.model import Experiment
from edge.wizard import WizardError, build_experiment, estimate


# ------------------------------------------------------------------ plain-language errors
def test_unknown_name_says_what_exists_and_suggests():
    with pytest.raises(expressions.ExpressionError) as e:
        expressions.evaluate("wrod.upper()", {"word": "RED", "ink": "red"})
    msg = str(e.value)
    assert "'wrod' isn't defined" in msg and "Did you mean 'word'" in msg and "ink, word" in msg


@pytest.mark.parametrize("src, hint", [
    ("resp.keys = 'f'", "=="),
    ("hello there friend", "remove the leading '$'"),
    ("(1 + 2", "matching ')'"),
    ("'red", "quote"),
])
def test_syntax_errors_come_with_a_hint(src, hint):
    with pytest.raises(expressions.ExpressionError) as e:
        expressions.compile_expr(src)
    assert "syntax error" in str(e.value) and hint in str(e.value)


def test_none_errors_explain_missing_responses():
    with pytest.raises(expressions.ExpressionError) as e:
        expressions.evaluate("rt * 1000", {"rt": None})
    assert "no response yet" in str(e.value)


# ------------------------------------------------------------------ static scope check
def _exp(routines, flow, **kw):
    return Experiment.from_dict({"name": "x", "routines": routines, "flow": flow, **kw})


def test_scope_check_finds_misspelled_and_missing_columns():
    exp = _exp({"trial": {"components": [
        {"id": "w", "type": "text", "text": "$word", "color": "$ink", "duration": 1},
        {"id": "k", "type": "keyboard", "keys": ["f"], "correct": "$corect", "end_routine": True}]}},
        [{"loop": "trials", "conditions": [{"word": "RED", "colour": "red", "correct": "f"}], "children": ["trial"]}])
    errors = {i.where: i for i in exp.validate() if i.level == "error"}
    assert "no column called 'ink'" in errors["routines.trial.w.color"].message
    assert "colour, correct, word" in errors["routines.trial.w.color"].hint
    assert "Did you mean 'correct'" in errors["routines.trial.k.correct"].message


def test_scope_check_warns_when_a_screen_runs_outside_its_loop():
    exp = _exp({"t": {"components": [{"id": "x", "type": "text", "text": "$word", "duration": 1}]}},
               ["t", {"loop": "L", "conditions": [{"word": "a"}], "children": ["t"]}])
    warn = [i for i in exp.validate() if i.level == "warning"]
    assert any("runs outside that loop" in i.message for i in warn)


def test_scope_check_knows_variables_components_loops_and_code():
    exp = _exp({
        "setup": {"components": [{"id": "v", "type": "variable", "set": {"score": 0}},
                                 {"id": "c", "type": "code", "on_begin": "bonus = 2\nvars['streak'] = 0"},
                                 {"id": "resp", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
        "show": {"duration": 1, "components": [
            {"id": "t", "type": "text", "text": "$f'{score} {bonus} {streak} {participant} {trials.total} {resp.rt}'"},
            {"id": "u", "type": "text", "text": "$str(len([x for x in range(3)])) + str(t)"}]}},
        ["setup", {"loop": "trials", "repeats": 2, "children": ["show"]}, "show"])
    assert [i for i in exp.validate() if i.level in ("error", "warning")] == []


def test_scope_check_reads_conditions_files(tmp_path):
    (tmp_path / "c.csv").write_text("word,key\nRED,r\n")
    exp = Experiment.from_dict({"name": "x", "routines": {"t": {"components": [
        {"id": "x", "type": "text", "text": "$wordd", "duration": 1}]}},
        "flow": [{"loop": "L", "conditions": "c.csv", "children": ["t"]}]}, base_dir=tmp_path)
    err = [i for i in exp.validate() if i.level == "error"]
    assert err and "Did you mean 'word'" in err[0].message


def test_trial_list_value_wins_over_component_with_same_name(tmp_path):
    """A text component called 'word' showing $word must show the word (regression: it showed '{}')."""
    from edge.backends import HeadlessBackend
    from edge.engine import Runner
    from edge.participant import VirtualParticipant
    from edge.runtime import Session
    exp = _exp({"t": {"components": [{"id": "word", "type": "text", "text": "$word", "duration": 0.1}]}},
               [{"loop": "L", "conditions": [{"word": "RED"}, {"word": "BLUE"}], "children": ["t"]}])
    assert not [i for i in exp.validate() if i.level == "error"]
    be = HeadlessBackend()
    s = Session(exp, be, data_dir=str(tmp_path), virtual_participant=VirtualParticipant(), simulate_devices=True,
                log=lambda *a: None)
    Runner(s).run()
    shown = {p["text"] for f in be.frame_log for k, p in f["drawn"] if k == "text"}
    assert shown == {"RED", "BLUE"}


# ------------------------------------------------------------------ wizard
@pytest.mark.parametrize("kind, resp, practice, blocks", [
    (k, r, p, b) for k, r, p, b in itertools.product(["word", "shape", "sound"], ["keys", "mouse", "rating", "none"],
                                                      ["none", "once", "until"], [1, 3])
    if not (r != "keys" and p == "until" and b == 3)])
def test_wizard_experiments_validate_and_run(kind, resp, practice, blocks, tmp_path):
    doc = build_experiment({"stimulus": {"kind": kind}, "response": {"kind": resp}, "practice": {"mode": practice},
                            "blocks": {"count": blocks}, "feedback": True})
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    assert [str(i) for i in exp.validate() if i.level in ("error", "warning")] == []
    summary = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    assert not summary["errors"]


def test_wizard_practice_until_criterion_uses_a_workflow(tmp_path):
    doc = build_experiment({"practice": {"mode": "until", "criterion": 0.9, "max_rounds": 2}, "blocks": {"count": 2, "repeats": 3},
                            "stimulus": {"kind": "word", "items": [{"stimulus": "A", "correct": "f", "condition": "a"},
                                                                   {"stimulus": "B", "correct": "j", "condition": "b"}]}})
    sm = next(n for n in doc["flow"] if isinstance(n, dict) and "statemachine" in n)
    assert sm["states"]["practice"]["max_visits"] == 2 and "0.9" in sm["states"]["practice"]["next"][0]["if"]
    est = estimate(doc, tmp_path)
    assert est["trials"] == 2 + 2 * 3 * 2 and "trials" in est["text"]


def test_wizard_rejects_bad_answers():
    with pytest.raises(WizardError, match="not among the response keys"):
        build_experiment({"stimulus": {"items": [{"stimulus": "A", "correct": "x"}]}, "response": {"kind": "keys", "keys": ["f"]}})
    with pytest.raises(WizardError, match="at least one stimulus"):
        build_experiment({"stimulus": {"items": [{"stimulus": ""}]}})
    with pytest.raises(WizardError, match="number of seconds"):
        build_experiment({"timing": {"fixation": "soon"}})


def test_wizard_cli_with_answers_file(tmp_path, capsys):
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps({"name": "Flanker Task!", "blocks": {"count": 2}}))
    assert main(["wizard", str(tmp_path), "--answers", str(answers)]) == 0
    out = capsys.readouterr().out
    assert "flanker_task.yaml" in out and "trials" in out
    assert main(["run", str(tmp_path / "flanker_task.yaml"), "--dry-run"]) == 0


# ------------------------------------------------------------------ Try it
def test_single_screen_experiment_keeps_the_enclosing_loops():
    from edge.play import single_screen_experiment
    doc = build_experiment({"blocks": {"count": 3}})
    one = single_screen_experiment(doc, "trial", max_trials=3)
    outer = one["flow"][0]
    assert outer["loop"] == "blocks" and outer["stop_if"] == "$True"
    inner = outer["children"][0]
    assert inner["loop"] == "trials" and inner["children"] == ["trial"] and inner["stop_if"] == "$trials.n >= 2"
    assert single_screen_experiment(doc, "instructions")["flow"] == ["instructions"]


def test_play_manager_runs_with_browser_input(tmp_path):
    from edge.play import PlayManager
    doc = build_experiment({"timing": {"fixation": 0.1, "iti": 0}})
    pm = PlayManager(tmp_path)
    assert pm.start(doc, tmp_path)["ok"]
    seen = set()
    deadline = time.time() + 20
    while time.time() < deadline:
        f = pm.frame()
        if not f["running"]:
            break
        texts = [p.get("text", "") for k, p in f["drawn"] if k == "text"]
        seen.update(texts)
        if any("Press SPACE" in t for t in texts):
            pm.input({"kind": "key", "name": "space"})
            pm.input({"kind": "key", "name": "space", "down": False})
        elif "LEFT" in texts or "RIGHT" in texts:
            pm.input({"kind": "key", "name": "f"})
        time.sleep(0.05)
    f = pm.frame()
    assert not f["running"] and f["error"] is None, f
    assert f["result"]["trials"] == 2 and f["result"]["responses"] == 2
    assert {"LEFT", "RIGHT"} & seen


def test_play_escape_stops_and_html_pages_are_shown_in_place(tmp_path):
    from edge.play import PlayManager
    doc = {"name": "p", "routines": {"page": {"components": [
        {"id": "form", "type": "html", "html": "<form><input name='age'></form>", "end_routine": True}]}},
        "flow": ["page"]}
    pm = PlayManager(tmp_path)
    pm.start(doc, tmp_path)
    url = None
    for _ in range(100):
        url = pm.frame().get("page")
        if url:
            break
        time.sleep(0.05)
    assert url and url.startswith("http://127.0.0.1:")
    with urllib.request.urlopen(url) as r:
        assert b"age" in r.read()
    pm.input({"kind": "key", "name": "escape"})
    st = pm.stop()
    assert not st["running"] and st["result"]["aborted"]


def test_play_refuses_experiments_with_errors(tmp_path):
    from edge.play import PlayManager
    with pytest.raises(ValueError, match="no column called"):
        PlayManager(tmp_path).start({"name": "x", "routines": {"t": {"components": [
            {"id": "a", "type": "text", "text": "$nope", "duration": 1}]}},
            "flow": [{"loop": "L", "conditions": [{"word": 1}], "children": ["t"]}]}, tmp_path)


# ------------------------------------------------------------------ builder endpoints
@pytest.fixture
def server(tmp_path):
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_builder_wizard_estimate_play_and_participants(server):
    url, root = server
    pre = _post(url + "/api/wizard", {"answers": {"blocks": {"count": 2}}})
    assert pre["ok"] and "path" not in pre and pre["estimate"]["trials"] == 4
    bad = _post(url + "/api/wizard", {"answers": {"stimulus": {"items": []}, "response": {"kind": "keys", "keys": ["q"]}}})
    assert bad["ok"] is False and "not among the response keys" in bad["error"]
    made = _post(url + "/api/wizard", {"answers": {"name": "demo", "stimulus": {"kind": "picture"}}, "save_as": "demo/demo.yaml"})
    assert made["path"] == "demo/demo.yaml" and (root / "demo" / "images").is_dir()
    assert _post(url + "/api/wizard", {"answers": {}, "save_as": "demo/demo.yaml"})["ok"] is False   # never overwrites
    est = _post(url + "/api/estimate", {"experiment": made["experiment"], "path": "demo/demo.yaml"})
    assert est["trials"] == 2
    # next participant id comes from existing (non-test) sessions
    assert _get(url + "/api/next_participant?path=demo/demo.yaml")["suggestion"] == "001"
    exp = Experiment.load(root / "demo" / "demo.yaml")
    run_experiment(exp, backend="headless", participant={"participant": "007"}, simulate_devices=True,
                   virtual_participant=__import__("edge.participant", fromlist=["x"]).VirtualParticipant(), log=lambda *a: None)
    nxt = _get(url + "/api/next_participant?path=demo/demo.yaml")
    assert nxt["suggestion"] == "008" and "007" in nxt["used"]
    # Try it over HTTP
    doc = build_experiment({})
    assert _post(url + "/api/play/start", {"experiment": doc, "routine": "trial", "max_trials": 1})["ok"]
    f = _get(url + "/api/play/frame")
    assert "drawn" in f and f["size"] == [1280, 720]
    assert _post(url + "/api/play/input", {"kind": "key", "name": "f"})["ok"] in (True, False)
    assert _post(url + "/api/play/stop", {})["running"] is False
    err = _post(url + "/api/play/start", {"experiment": doc, "routine": "nope"})
    assert err["ok"] is False and "nope" in err["error"]


# ------------------------------------------------------------------ launcher
def test_launcher_workspace_and_shortcuts(tmp_path, monkeypatch):
    from edge import launcher
    monkeypatch.setenv("EDGE_HOME", str(tmp_path / "EDGE Experiments"))
    ws = launcher.ensure_workspace()
    assert ws == tmp_path / "EDGE Experiments" and (ws / "README.md").exists()
    linux = launcher.desktop_shortcut("linux", desktop=tmp_path / "Desktop")
    text = linux[0].read_text()
    assert "Exec=" in text and "start" in text and '"' in text and "EDGE Experiments" in text
    mac = launcher.desktop_shortcut("darwin", desktop=tmp_path / "mac")
    assert mac[0].name == "EDGE.command" and mac[0].read_text().startswith("#!/bin/sh")
    win = launcher.desktop_shortcut("win32", desktop=tmp_path / "win")
    assert win[0].name == "EDGE.bat" and "-m edge start" in win[0].read_text()


def test_terminal_wizard_questions(tmp_path):
    from edge import launcher
    replies = iter(["stroopish", "word", "keys", "RED, r, congruent", "GREEN, g, incongruent", "", "", "0.5", "", "2",
                    "y", "once", "2", "1"])
    answers = launcher.ask_wizard(lambda q, d: next(replies))
    path, est = launcher.write_wizard_experiment(answers, tmp_path)
    assert path.name == "stroopish.yaml" and est["trials"] == 2 + 2 * 2
    doc = Experiment.load(path)
    assert not [i for i in doc.validate() if i.level == "error"]


def test_run_reports_a_missing_screen_in_plain_words(tmp_path, capsys, monkeypatch):
    import edge.engine
    doc = build_experiment({})
    p = tmp_path / "x.yaml"
    from edge.storage import save_document
    save_document(p, doc)

    def boom(*a, **k):
        raise RuntimeError("Cannot connect to display ':0' (pyglet.canvas.xlib.NoSuchDisplayException)")
    monkeypatch.setattr(edge.engine, "run_experiment", boom)
    assert main(["run", str(p)]) == 3
    assert "no screen is available" in capsys.readouterr().out


def test_builder_static_files_reference_existing_functions():
    static = Path(__file__).resolve().parent.parent / "edge" / "builder" / "static"
    html = (static / "index.html").read_text()
    assert "simple.js" in html and 'id="btn-try"' in html and 'id="btn-mode"' in html
    js = (static / "app.js").read_text() + (static / "simple.js").read_text()
    for fn in ("function renderStoryboard", "function openWizard", "function tryIt", "function runDialog",
               "function addTrialColumn", "function drawScreen", "function setMode"):
        assert fn in js


def test_simple_mode_tutorials_only_use_visible_controls():
    import re
    from edge import help as hp
    html = (Path(hp.__file__).parent / "builder" / "static" / "index.html").read_text()
    hidden = set(re.findall(r'id="([\w-]+)"[^>]*class="[^"]*expert-only', html)) | \
        set(re.findall(r'class="[^"]*expert-only[^"]*"[^>]*id="([\w-]+)"', html)) | \
        {f"data-tab={t}" for t in re.findall(r'data-tab="(\w+)" class="expert-only"', html)}
    assert "btn-import" in hidden and "data-tab=source" in hidden
    for tut in hp.tutorials():
        if tut.get("mode", "simple") != "simple":
            continue
        for st in tut["steps"]:
            target = st.get("target") or ""
            assert not any(h in target for h in hidden), f"{tut['id']}: '{target}' is hidden in Simple mode"


def test_second_launch_reuses_the_running_builder(server, capsys):
    from edge.builder.server import serve
    url, root = server
    port = int(url.rsplit(":", 1)[1])
    serve(root, port=port, open_browser=False)          # returns at once instead of failing or serving twice
    assert "already running" in capsys.readouterr().out
