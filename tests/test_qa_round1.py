"""Regression tests for the problems QA round 1 found in the redesigned builder and the assistant.

Server behaviour is tested through the builder's HTTP API; the browser code is checked as text (and, where a pure
function says it best, run with node when it is installed).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from edge.builder.server import BuilderApp, make_handler

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "edge" / "builder" / "static"


def js(name: str) -> str:
    return (STATIC / name).read_text()


def function_body(src: str, name: str) -> str:
    """The text of `function name(` up to the next top-level function."""
    i = src.index(f"function {name}(")
    m = re.search(r"\n(?:async )?function \w+\(|\n/\* =+", src[i + 10:])
    return src[i: i + 10 + (m.start() if m else len(src))]


@pytest.fixture
def server(tmp_path):
    shutil.copytree(ROOT / "examples/stroop", tmp_path / "stroop", ignore=shutil.ignore_patterns("data"))
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path, app
    httpd.shutdown()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _typo_doc(root: Path) -> dict:
    doc = yaml.safe_load((root / "stroop/stroop.yaml").read_text())
    fb = doc["routines"]["feedback"]["components"][0]
    fb["text"] = fb["text"].replace("resp.corr", "resp.cor", 1)
    return doc


def _runtime_typo_doc(root: Path) -> dict:
    """The same typo, but past the checker: since QA round 2 resp.cor is an error before running, unless a code item
    could add results the check can't see (then it is a warning and the experiment stops while it runs)."""
    doc = _typo_doc(root)
    doc["routines"]["instructions"]["components"].append({"id": "noop", "type": "code", "on_begin": "pass"})
    return doc


# ---------------------------------------------------------------- runtime errors, in words
def test_checker_catches_a_misspelt_result_name(server):
    url, root, _ = server
    issues = _post(url + "/api/validate", {"experiment": _typo_doc(root), "path": "stroop/stroop.yaml"})[1]["issues"]
    hit = [i for i in issues if "resp.cor" in i["message"]]
    # an error since QA round 2: it always stops the experiment at that line
    assert hit and hit[0]["level"] == "error" and "Did you mean resp.corr?" in hit[0]["message"]
    assert hit[0]["where"] == "routines.feedback.fb.text"


def test_test_run_that_stops_answers_200_in_plain_words(server):
    url, root, _ = server
    status, r = _post(url + "/api/dryrun", {"experiment": _runtime_typo_doc(root), "path": "stroop/stroop.yaml"})
    assert status == 200 and r["ok"] is False and r["stopped"] is True
    assert "error" not in r          # api() in the page would throw on an "error" key: the problem is under "problem"
    p = r["problem"]
    assert p["routine"] == "feedback" and p["component"] == "fb" and p["prop"] == "text"
    assert p["text"] == ("On screen “feedback”, the text formula of “fb” uses resp.cor, but a key press has no “cor”. "
                         "Did you mean resp.corr?")
    assert "ExpressionError" in r["raw"]       # the raw report stays, for Expert mode


def test_try_it_ends_with_the_problem_and_saves_next_to_the_experiment(server):
    url, root, _ = server
    doc = _runtime_typo_doc(root)
    assert _post(url + "/api/play/start", {"experiment": doc, "path": "stroop/stroop.yaml"})[1]["ok"]
    for key in ("space", "r"):
        time.sleep(0.6)
        _post(url + "/api/play/input", {"kind": "key", "name": key, "down": True})
        _post(url + "/api/play/input", {"kind": "key", "name": key, "down": False})
    deadline, f = time.time() + 15, {}
    while time.time() < deadline:
        try:
            f = _get(url + "/api/play/frame?sound=0")
        except urllib.error.HTTPError as e:       # an "error" key: the page now reads it as the end of the try
            f = json.loads(e.read())
        if not f.get("running", True):
            break
        time.sleep(0.2)
    assert f.get("running") is False and f.get("error")
    assert f["problem"]["text"].startswith("On screen “feedback”")
    # Try-it sessions live in <experiment>/data/dry_runs/try, so Data › Tests & tries lists them
    assert list((root / "stroop/data/dry_runs/try").glob("try_*")) and not (root / "data").exists()
    sessions = _get(url + "/api/sessions?dry_runs=1")["sessions"]
    mine = [s for s in sessions if s["path"].startswith("stroop/data/dry_runs/try/")]
    assert mine and mine[0]["dry_run"] and mine[0]["kind"] == "try"


def test_last_test_restores_tested_after_a_reload(server):
    url, root, _ = server
    doc = yaml.safe_load((root / "stroop/stroop.yaml").read_text())
    assert _post(url + "/api/last_test", {"experiment": doc, "path": "stroop/stroop.yaml"})[1]["found"] is False
    r = _post(url + "/api/dryrun", {"experiment": doc, "path": "stroop/stroop.yaml"})[1]
    assert r["ok"]
    t = _post(url + "/api/last_test", {"experiment": doc, "path": "stroop/stroop.yaml"})[1]
    assert t["found"] and t["trials"] == r["n_trials"] and t["path"].startswith("stroop/data/dry_runs/")
    doc["routines"]["thanks"]["duration"] = 3          # another document: not tested
    assert _post(url + "/api/last_test", {"experiment": doc, "path": "stroop/stroop.yaml"})[1]["found"] is False


# ---------------------------------------------------------------- an empty trial list
def test_empty_conditions_warn_and_estimate_zero(tmp_path):
    from edge.model import Experiment
    from edge.wizard import estimate_experiment
    doc = {"name": "t", "routines": {"flash": {"duration": 0.1}},
           "flow": [{"loop": "repeats", "repeats": 30, "conditions": [], "children": ["flash"]}]}
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    assert any("has no rows, so its screens never run" in i.message for i in exp.validate())
    assert estimate_experiment(exp)["trials"] == 0
    del doc["flow"][0]["conditions"]               # no trial list at all: the screens just repeat
    assert estimate_experiment(Experiment.from_dict(doc, base_dir=tmp_path))["trials"] == 30


def test_drawing_a_trial_list_never_changes_the_document():
    body = function_body(js("build.js"), "tableEditor")
    assert "(n.conditions = [])" not in body and "n.conditions =" not in body


# ---------------------------------------------------------------- save, Try it, Data
def test_save_commits_the_field_being_typed_and_tracks_late_edits():
    save = function_body(js("app.js"), "save")
    assert "await flushPendingEdits()" in save.split("\n")[1]
    assert "rev0 = S.rev" in save and "setDirty(later)" in save and 'clearAlert("draft")' in save
    assert "a.blur()" in function_body(js("app.js"), "flushPendingEdits")


def test_try_it_loop_ends_on_an_error_frame_and_main_button_tries_everything():
    loop = function_body(js("simple.js"), "playLoop")
    assert "e.data.running === false" in loop
    assert '$("#btn-try").onclick = () => tryNow("all")' in js("app.js")


def test_sessions_belong_by_folder_not_by_name():
    body = function_body(js("app.js"), "sessionBelongs")
    assert "startsWith(dir)" in body and "s.experiment === S.exp.name" in body   # by folder, and not a sibling's (round 2)


# ---------------------------------------------------------------- words
def _node(script: str) -> str:
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout


def test_code_in_tutorials_and_help_is_escaped_once():
    src = js("app.js")
    fn = function_body(src, "mdInline")
    out = _node(fn + "\nconsole.log(mdInline('set `$practice.accuracy >= 0.8` and `$n < 6`'));")
    assert "<code>$practice.accuracy &gt;= 0.8</code>" in out and "<code>$n &lt; 6</code>" in out and "&amp;gt;" not in out


def test_in_words_reads_if_else_formulas():
    src = js("build.js")
    a, b = src.index("const FIELD_WORDS"), src.index("/* ================================================================== the Build workspace")
    script = ("global.S={exp:{routines:{t:{components:[{id:'resp',type:'keyboard'},{id:'consent_form',type:'survey'}]}}}};"
              "global.isExpr=(v)=>typeof v==='string'&&v.startsWith('$')&&!v.startsWith('$$');"
              + src[a:b] +
              ";for (const [v,k] of [[`$\"Correct!\" if resp.corr else \"Wrong!\"`,'value'],[`$'#55dd55' if resp.corr else '#ff5555'`,'value'],"
              "[`$practice.accuracy is not None and practice.accuracy >= 0.8`,'condition'],[`$consent_form.consent == 'yes'`,'condition']])"
              " console.log(exprInWords(v,k));")
    lines = _node(script).splitlines()
    assert lines[0] == "“Correct!” when the response was correct, otherwise “Wrong!”"
    assert lines[1] == "“#55dd55” when the response was correct, otherwise “#ff5555”"
    assert lines[2] == "“practice” accuracy is at least 80 %"
    assert lines[3] == "the answer to “consent” is “yes”"


def test_formula_in_words_reads_the_real_input():
    src = js("inspector.js")
    i = src.index('const say = h("div", {class: "say"});')
    block = src[i: i + 900]
    assert "const field = input;" in block and "field.value" in block and "input.value" not in block


# ---------------------------------------------------------------- tutorials
def test_tutorials_validate_and_trial_lists_never_advise_removing_key():
    from edge import help as hp
    for t in hp.tutorials():
        assert hp.validate_tutorial(t) == [], t["id"]
    tl = hp.tutorial("trial_lists")
    text = " ".join(st["body"] for st in tl["steps"])
    assert "bin button" not in text
    back = [st for st in tl["steps"] if st["title"] == "Back to your typed rows"][0]
    assert back["check"]["loop"]["conditions_kind"] == "list"
    wf = hp.tutorial("workflow_practice")
    add = [st for st in wf["steps"] if st["title"] == "Add a workflow"][0]
    assert add["check"] == {"statemachine": {"top": True}} and "flow-start" in add["target"]


def test_tutorial_lookup_accepts_a_unique_prefix():
    from edge import help as hp
    assert hp.tutorial("import")["id"] == "import_existing"
    assert hp.tutorial("Trial lists")["id"] == "trial_lists"
    with pytest.raises(Exception):
        hp.tutorial("zzz")


def test_coach_steps_without_target_drop_the_previous_hint():
    body = function_body(js("app.js"), "renderCoach")
    assert "else { T.need = null; T.target = null; }" in body
    assert 'st.advance === "manual"' in function_body(js("app.js"), "checkTutorial")


# ---------------------------------------------------------------- keyboard and focus
def test_grid_tab_leaves_the_grid_and_dialogs_find_a_rerendered_opener():
    assert '"Tab"' not in function_body(js("build.js"), "gridKeys")
    ui = js("ui.js")
    assert "opts.returnFocus" in ui and "openerKey" in ui


def test_position_grid_targets_are_24px():
    css = js("pages.css")
    assert re.search(r"\.placegrid \{[^}]*repeat\(3, 24px\)", css) and re.search(r"\.pg-cell \{[^}]*width: 24px; height: 24px", css)


# ---------------------------------------------------------------- assistant
def test_participant_data_guard_flags_small_exports():
    from edge.assistant.attachments import looks_like_participant_data as f
    assert f(["participant", "trial", "word", "rt", "response", "correct"], 2)
    assert not f(["word", "ink", "key"], 30)


def test_custom_claude_address_is_named_and_needs_its_own_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "cfg"))
    from edge.assistant import config as c
    cfg = c.load_config()
    assert c.service_name(cfg, "anthropic") == "Anthropic" and c.consent_key(cfg, "anthropic") == "anthropic"
    cfg.data.setdefault("anthropic", {})["base_url"] = "http://127.0.0.1:9740"
    assert c.service_name(cfg, "anthropic") == "Claude at 127.0.0.1"
    assert c.consent_key(cfg, "anthropic") == "anthropic:custom:127.0.0.1"


def test_preflight_skips_the_test_run_while_assistant_code_is_unread(tmp_path):
    from edge.assistant.tools import code_hashes
    from edge.preflight import run_preflight, unread_assistant_code
    exp = tmp_path / "e"
    exp.mkdir()
    doc = {"name": "e", "routines": {"s": {"duration": 0.2, "components": [
        {"id": "score", "type": "code", "on_begin": "x = 1"}]}}, "flow": ["s"]}
    (exp / "e.yaml").write_text(yaml.safe_dump(doc))
    h = list(code_hashes(doc).values())[0]
    (exp / ".edge/assistant").mkdir(parents=True)
    (exp / ".edge/assistant/history.jsonl").write_text(json.dumps({"code": [h]}) + "\n")
    unread = unread_assistant_code(exp / "e.yaml")
    assert unread == ["s.score"] and unread_assistant_code(exp / "e.yaml", [h]) == []
    r = run_preflight(exp / "e.yaml", golden=False, computer=False, save=False, skip_code=unread)
    tr = [s for s in r["sections"] if s["id"] == "test_run"][0]
    assert "hasn't been read yet" in tr["items"][0]["text"]


def test_conflicting_proposal_never_applies_without_force():
    app = js("app.js")
    i = app.index("apply({force = false} = {}) {")
    assert "if (S.proposal.conflict && !force)" in app[i: i + 400]
    assert "Ask again with my changes" in function_body(app, "renderProposalBar")


def test_home_describe_starts_from_an_empty_document_and_keeps_its_draft():
    a = js("assistant.js")
    assert 'doc: {name, description: "", routines: {}, flow: []}' in a
    assert "assistant.homeDraft" in a and "restoreHomeDraft()" in a


def test_list_models_uses_the_typed_settings(server):
    url, _, _ = server
    status, r = _post(url + "/api/assistant/list_models", {"provider": "ollama", "settings": {"base_url": "http://127.0.0.1:9"}})
    assert status == 200 and r["models"] == [] and r["error"]
    assert "127.0.0.1:9" in json.dumps(r["error"]) or r["error"]["code"]


def test_stroop_is_in_the_examples_gallery():
    from edge.templates import public_templates
    names = list(public_templates())
    assert names[:2] == ["blank", "stroop"]
    for t in public_templates().values():
        assert "(routines)" not in t.get("description", "") and "sim_eyetracker" not in t.get("description", "")


# ---------------------------------------------------------------- QA round 1, second pass (rechecked in a browser)
def test_measure_filter_with_a_misspelt_result_is_caught(tmp_path):
    from edge.model import Experiment
    from edge.scope import scope_issues
    doc = yaml.safe_load((ROOT / "examples/stroop/stroop.yaml").read_text())
    doc["measures"][0]["trials"] = "$resp.cor == 1"
    issues = scope_issues(Experiment.from_dict(doc))
    hit = [i for i in issues if i.where.startswith("measures.")]
    assert hit and "Did you mean resp.corr?" in hit[0].message


def test_go_there_puts_the_keyboard_in_the_field_with_the_problem():
    body = function_body(js("app.js"), "gotoIssue")
    assert 'data-prop="${prop}"' in body and ".focus(" in body


def test_storyboard_is_one_tab_stop_with_arrow_keys_and_insert_items_in_the_menu():
    src = js("build.js")
    rov = function_body(src, "storyRoving")
    assert "x.tabIndex = x === active ? 0 : -1" in rov and '"Home"' in rov
    assert "storyRoving(el)" in function_body(src, "renderStoryboard")
    menu = function_body(src, "nodeMenu")
    assert "Add a step before…" in menu and "Add a step after…" in menu


def test_delete_and_undo_keep_the_keyboard_on_the_storyboard():
    src = js("build.js")
    assert "BUILD.focusKey = flowNodeKey(" in function_body(src, "removeFromFlow")
    for fn in ("undo", "redo"):
        assert "focusChangedStep(steps)" in function_body(js("app.js"), fn)


def test_crumbs_that_had_to_shrink_make_the_toolbar_tight():
    body = function_body(js("build.js"), "fitToolbar")
    assert "#crumbs .crumb-t, #crumbs .crumb.here" in body and "scrollWidth > e.clientWidth" in body
    assert "max-width: 60%" not in js("build.css")


def test_workflow_diagram_wraps_to_the_canvas_instead_of_shrinking():
    src = js("build.js")
    fn = function_body(src, "layoutMachine")
    m = ("{start:'a', states:{a:{next:[{goto:'b'}]}, b:{next:[{goto:'c'}]}, c:{next:[{goto:'d'}]}, d:{next:[{goto:'end'}]}}}")
    out = _node(fn + f"\nconst p = layoutMachine({m}, 700); delete p._rows;"
                     "console.log(JSON.stringify(Object.values(p).map((q) => [q.x + q.w, q.row])));")
    boxes = json.loads(out)
    assert max(r for _, r in boxes) >= 1 and all(right <= 700 for right, _ in boxes)
    assert "BUILD.zoom = Math.max(all ? 0.3 : 0.85" in src


def test_reload_during_an_assistant_job_follows_it_again():
    src = js("assistant.js")
    assert "inflight: true" in src
    load = function_body(src, "loadTranscript")
    assert "m.inflight || m.live" in load and "resumeJob(m, path)" in load
    assert "delete job.msg.inflight" in function_body(src, "finishJob")


def test_a_change_that_could_not_be_made_puts_the_request_back():
    body = function_body(js("assistant.js"), "finishJob")
    assert 'x.state === "failed"' in body and "st.els.input.value = job.message" in body.split('job.phase = "answer"')[1]


def test_wizard_keys_keep_focus_and_the_preview_never_goes_stale():
    src = js("simple.js")
    assert 'old.replaceWith(nu); nu.querySelector("#wiz-keys")?.focus' in src
    prev = function_body(src, "wizPreview")
    assert prev.count("wizEstError(") == 2 and "wizPlainThumb()" in prev
    assert "Go to step" in function_body(src, "wizEstError")
    assert "r = e.data;" in function_body(src, "createFromWizard")


def test_run_page_words_and_footer():
    src = js("app.js")
    fn = function_body(src, "builderWords") + function_body(src, "relPath")
    out = _node("global.S={root:''};" + fn + "\nconsole.log(builderWords(\"it would run WITHOUT recording it (edge test-device shows the details)\"));")
    assert "edge" not in out and "WITHOUT" not in out and "Test this device" in out
    assert "pfItemText(bad[0] || s.items[0], bw)" in js("measures.js") and "return bw(it.text)" in js("measures.js")
    assert re.search(r"\.run-foot \{ position: sticky; bottom: calc\(-1 \* var\(--sp-8\)\)", js("pages.css"))


def test_value_source_beside_a_control_is_compact_and_survey_editor_starts_at_a_question():
    css = js("pages.css")
    assert ".field.nolabel > .ctl-row > .srcbtn.fixed .src-words { display: none; }" in css
    assert 'setTimeout(() => SV.dlg?.querySelector(".sv-pick' in js("survey.js")


def test_survey_tutorial_opens_the_task_screen_before_the_add_palette():
    tut = yaml.safe_load((ROOT / "edge/tutorials/09_survey.yaml").read_text())
    titles = [s["title"] for s in tut["steps"]]
    i = titles.index("Open the task screen")
    assert titles[i + 1] == "Add a survey" and tut["steps"][i]["check"] == {"view": "screen"}
    runner = (ROOT / "tools/ui_check/tutorials.js").read_text()
    assert "s.manual && s.check" in runner      # advance: manual steps are played: the check, then Next
