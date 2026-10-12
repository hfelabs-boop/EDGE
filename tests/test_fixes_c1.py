"""Regression tests for the C1 fixes: MCP server, editing, help, support bundle, builder messages."""
import asyncio
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

mcp = pytest.importorskip("mcp")

from edge.mcp_server import create_server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def call(server, tool, **args):
    res = asyncio.run(server.call_tool(tool, args))
    if isinstance(res, tuple):
        structured = res[1]
        return structured["result"] if set(structured) == {"result"} else structured
    return json.loads(res[0].text)


@pytest.fixture
def ws(tmp_path):
    for name in ("stroop", "questionnaire"):
        shutil.copytree(EXAMPLES / name, tmp_path / name)
    return tmp_path, create_server(tmp_path)


P = "stroop/stroop.yaml"


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- mcp#0: conditions files in edits
def test_failed_batch_leaves_conditions_file_alone(ws):
    root, s = ws
    before = (root / "stroop" / "stroop.csv").read_bytes()
    r = call(s, "edit_experiment", path=P, operations=[
        {"op": "set_conditions", "lid": "trials", "rows": [{"word": "X"}], "file": "stroop.csv", "write_file": True},
        {"op": "add_routine", "rid": "trial"}])
    assert not r["ok"] and r["applied"] == 0
    assert (root / "stroop" / "stroop.csv").read_bytes() == before


def test_shared_conditions_file_is_not_overwritten_and_undo_restores_it(ws):
    root, s = ws
    csv = root / "stroop" / "stroop.csv"
    before = csv.read_bytes()
    assert call(s, "add_loop", path=P, loop="practice", children=["trial"], position=1)["ok"]
    row = [{"word": "RED", "ink": "red", "congruent": 1, "correct_key": "r"}]
    r = call(s, "set_conditions", path=P, loop="practice", rows=row, file="stroop.csv", write_file=True)
    assert not r["ok"] and "loop trials" in r["error"] and "overwrite=true" in r["error"]
    assert csv.read_bytes() == before
    # the loop's own file: replaced, backed up, and undo puts it back
    r = call(s, "set_conditions", path=P, loop="trials", rows=row, file="stroop.csv", write_file=True)
    assert r["ok"] and "undo puts it back" in r["changes"][0]
    assert csv.read_bytes() != before
    u = call(s, "undo", path=P)
    assert u["ok"] and u["files_restored"] == ["stroop.csv"]
    assert csv.read_bytes() == before
    # overwrite=true changes the shared file
    r = call(s, "set_conditions", path=P, loop="practice", rows=row, file="stroop.csv", write_file=True, overwrite=True)
    assert r["ok"] and csv.read_bytes() != before


# ---------------------------------------------------------------- mcp#1: run_status reads its own run's log
def test_run_status_shows_the_log_of_that_run(ws, monkeypatch):
    root, s = ws
    import edge.mcp_server as ms
    real = ms.subprocess.Popen

    def fake(cmd, **kw):   # no window: each "run" just prints its participant id
        who = cmd[cmd.index("-p") + 1]
        return real([sys.executable, "-c", f"print('log of {who}')"], **kw)
    monkeypatch.setattr(ms.subprocess, "Popen", fake)
    r1 = call(s, "run_experiment", path=P, participant="A1")
    r2 = call(s, "run_experiment", path="questionnaire/questionnaire.yaml", participant="B2")
    r3 = call(s, "run_experiment", path=P, participant="A1")       # same participant again: its own log
    assert len({r1["log"], r2["log"], r3["log"]}) == 3
    for r in (r1, r2, r3):
        s.workspace.runs[str(r["pid"])].wait(30)
    assert "log of A1" in call(s, "run_status", pid=r1["pid"])["output"]
    assert "log of B2" in call(s, "run_status", pid=r2["pid"])["output"]
    assert "no session was started" in call(s, "run_status", pid=1)["error"]


# ---------------------------------------------------------------- mcp#2, mcp#16: measures and trial count
def test_dry_run_and_analyze_session_report_measures_and_loop_trials(ws):
    root, s = ws
    d = call(s, "dry_run", path=P)
    assert d["ok"] and d["trials"] == 18 == call(s, "estimate_duration", path=P)["trials"]
    assert [m["measure"] for m in d["measures"]["values"]] == ["rt", "accuracy"]
    sess = call(s, "list_sessions", directory="stroop", include_dry_runs=True)["sessions"][0]["path"]
    a = call(s, "analyze_session", session=sess)
    assert a["measures"]["values"][0]["label"] == "Reaction time" and "checks" in a["measures"]


# ---------------------------------------------------------------- mcp#4: workflows run loops by name
def test_workflow_states_run_loops_named_as_strings(ws):
    root, s = ws
    assert call(s, "edit_experiment", path=P, operations=[
        {"op": "duplicate_routine", "rid": "trial", "new": "ptrial"},
        {"op": "add_loop", "lid": "practice", "children": ["ptrial"], "conditions": "stroop.csv", "position": 1}])["ok"]
    r = call(s, "add_workflow", path=P, workflow="session", states={
        "practice": {"run": ["practice"], "max_visits": 3,
                     "next": [{"if": "$practice.accuracy >= 0.8", "goto": "main"}, {"goto": "practice"}]},
        "main": {"run": ["trials"], "next": ["end"]}})
    assert r["ok"] and r["valid"], r
    flow = load(root / P)["flow"]
    assert [x if isinstance(x, str) else x.get("statemachine") for x in flow] == ["instructions", "session", "thanks"]
    assert flow[1]["states"]["main"]["run"][0]["loop"] == "trials"
    bad = call(s, "add_workflow", path=P, workflow="w2", states={"a": {"run": ["nope"]}})
    assert not bad["ok"] and "no routine or loop 'nope'" in bad["error"]


# ---------------------------------------------------------------- mcp#5: write_file and experiments
def test_write_file_refuses_experiments_and_backs_up_files(ws):
    root, s = ws
    before = (root / P).read_text()
    r = call(s, "write_file", path=P, content="oops: [")
    assert not r["ok"] and "replace_experiment_source" in r["error"]
    assert (root / P).read_text() == before
    r = call(s, "write_file", path="stroop/stroop.csv", content="a,b\n1,2\n")
    assert r["ok"] and Path(root / r["previous_version"]).read_text().startswith("word,")


# ---------------------------------------------------------------- mcp#7: renames keep references working
def test_renaming_a_component_or_loop_updates_references(ws):
    root, s = ws
    r = call(s, "update_component", path=P, routine="trial", id="resp", rename_to="response")
    assert r["ok"] and r["valid"], r
    assert "renamed component trial.resp to response" in r["changes"][0] and "feedback.fb.text" in r["changes"][0]
    doc = load(root / P)
    assert "response.corr" in doc["routines"]["feedback"]["components"][0]["text"]
    assert doc["measures"][0]["column"] == "response.rt"
    r = call(s, "update_loop", path=P, loop="trials", changes={"id": "main"})
    assert r["ok"] and r["valid"], r
    doc = load(root / P)
    assert "main.total" in doc["routines"]["thanks"]["components"][0]["text"]
    assert doc["measures"][0]["loop"] == "main"
    assert not call(s, "update_loop", path=P, loop="main", changes={"id": "trial"})["ok"]   # a routine's name


# ---------------------------------------------------------------- mcp#8: branches
def test_branches_take_loops_can_be_addressed_and_keep_children(ws):
    root, s = ws
    call(s, "edit_experiment", path=P, operations=[
        {"op": "duplicate_routine", "rid": "trial", "new": "practice_trial"},
        {"op": "add_loop", "lid": "prac", "children": ["practice_trial"], "conditions": "stroop.csv", "position": 1}])
    r = call(s, "add_branch", path=P, condition="$prac.accuracy >= 0.8", then=["trials"], otherwise=["practice_trial"])
    assert r["ok"], r
    out = call(s, "describe_experiment", path=P)["outline"]
    assert "if $prac.accuracy >= 0.8:   [branch if:0]" in out
    assert call(s, "modify_flow", path=P, action="insert", name="feedback",
                parent="if $prac.accuracy >= 0.8", branch="else")["ok"]
    branch = load(root / P)["flow"][2]
    assert branch["then"][0]["loop"] == "trials" and branch["else"] == ["practice_trial", "feedback"]
    r = call(s, "modify_flow", path=P, action="remove", name="if:0")
    assert r["ok"] and "stays in its place" in r["changes"][0] and r["valid"]
    flow = load(root / P)["flow"]
    assert any(isinstance(x, dict) and x.get("loop") == "trials" for x in flow)


# ---------------------------------------------------------------- mcp#9, mcp#11: settings and device options
@pytest.mark.parametrize("patch, words", [
    ({"window": {"units": "inches"}}, "px, norm, height, deg"),
    ({"window": {"background": "notacolor"}}, "not a colour"),
    ({"data": {"exports": ["csv", "spss"]}}, "unknown format spss"),
    ({"windw": {"fullscreen": True}}, "did you mean 'window'"),
])
def test_update_settings_refuses_invalid_settings(ws, patch, words):
    root, s = ws
    before = (root / P).read_text()
    r = call(s, "update_settings", path=P, settings=patch)
    assert not r["ok"] and words in r["error"]
    assert (root / P).read_text() == before


def test_device_options_are_checked_when_updating(ws):
    root, s = ws
    assert call(s, "add_device", path=P, type="sim_eyetracker", id="et")["ok"]
    r = call(s, "update_device", path=P, id="et", options={"bogus_option": 1})
    assert not r["ok"] and "no option bogus_option" in r["error"]
    r = call(s, "add_device", path=P, type="sim_eeg", id="eeg2", options={"srate": "fast"})
    assert not r["ok"] and "srate must be a number" in r["error"]
    assert call(s, "update_device", path=P, id="et", options={"srate": 250})["ok"]


# ---------------------------------------------------------------- mcp#12, wizard#17: add_survey
def test_add_survey_checks_questions_and_position_and_appends(ws):
    root, s = ws
    before = (root / P).read_text()
    r = call(s, "add_survey", path=P, questions=[{"instrument": "PHQ-9"}])
    assert not r["ok"] and "did you mean 'phq9'" in r["error"]
    r = call(s, "add_survey", path=P, questions=[{"id": "age", "type": "numbr", "text": "Age?"}])
    assert not r["ok"] and "unknown question type 'numbr'" in r["error"]
    assert not call(s, "add_survey", path=P, questions=[{"instrument": "phq9"}], position="middle")["ok"]
    r = call(s, "add_survey", path=P, questions=[{"instrument": "phq9"}], position="after:nope")
    assert "Top level: instructions, trials, thanks" in r["error"]
    assert (root / P).read_text() == before
    assert call(s, "add_survey", path=P, questions=[{"instrument": "phq9"}])["ok"]
    assert call(s, "add_survey", path=P, questions=[{"instrument": "gad7"}])["ok"]
    comps = load(root / P)["routines"]["questionnaire"]["components"]
    assert len(comps) == 1 and comps[0]["questions"] == [{"instrument": "phq9"}, {"instrument": "gad7"}]


# ---------------------------------------------------------------- mcp#13, mcp#14: measures
def test_set_measures_refuses_invalid_measures_and_warnings_keep_hints(ws):
    root, s = ws
    Q = "questionnaire/questionnaire.yaml"
    r = call(s, "set_measures", path=Q, measures=[{"id": "bad", "column": "ratng.pleasantness"}])
    assert r["ok"] and any("did you mean rating.pleasantness" in w for w in r["warnings"])
    before = (root / Q).read_text()
    for m, words in (({"id": "x", "column": "rating.pleasantness", "summary": "avg"}, "unknown summary 'avg'"),
                     ({"id": "y", "role": "dv", "column": "rating.pleasantness"}, "unknown role 'dv'")):
        r = call(s, "set_measures", path=Q, measures=[m], replace=False)
        assert not r["ok"] and words in r["error"]
    assert (root / Q).read_text() == before
    for label in ("first", "second"):     # no id: the column names it, so replace=False replaces it
        assert call(s, "set_measures", path=Q, measures=[{"label": label, "column": "rating.pleasantness"}],
                    replace=False)["ok"]
    ms = load(root / Q)["measures"]
    assert [m["id"] for m in ms] == ["bad", "rating_pleasantness"] and ms[1]["label"] == "second"


# ---------------------------------------------------------------- mcp#17: estimate with duration caps
def test_estimate_uses_when_components_stop_not_the_cap():
    from edge.model import Experiment
    from edge.wizard import estimate_experiment
    exp = Experiment.from_dict({"name": "t", "routines": {
        "flash": {"duration": 0.5, "components": [{"id": "p", "type": "shape", "duration_frames": 6}]},
        "hold": {"duration": 0.5, "components": [{"id": "w", "type": "wait"}]}},
        "flow": [{"loop": "r", "repeats": 10, "children": ["flash", "hold"]}]})
    est = estimate_experiment(exp)
    assert est["trials"] == 10 and 5.5 <= est["seconds"] <= 7.0     # 10 x (0.1 + 2 frames + 0.5)


# ---------------------------------------------------------------- mcp#19, mcp#22: bundles and versions
def test_bundle_out_folder_and_versions_say_what_they_contain(ws):
    root, s = ws
    assert call(s, "bundle_experiment", path=P, out="bundles/")["bundle"] == "bundles/stroop.edgez"
    assert call(s, "bundle_experiment", path=P, out="new/dir/mine")["bundle"] == "new/dir/mine.edgez"
    assert call(s, "import_experiment_bundle", bundle="bundles/stroop.edgez", directory="unbundled")["ok"]
    call(s, "update_settings", path=P, settings={"window": {"background": "#222222"}})
    v = call(s, "list_versions", path=P)["versions"][0]
    assert v["before_change"] == "settings" and "#222222" not in (root / "stroop" / ".edge" / "backups" /
                                                                    "stroop.yaml" / v["id"]).read_text()


# ---------------------------------------------------------------- mcp#25, docs#8: argument names
def test_batch_takes_tool_argument_names_and_reports_accepted_ones(ws):
    root, s = ws
    r = call(s, "edit_experiment", path=P, operations=[
        {"op": "add_component", "routine": "trial", "type": "text", "properties": {"text": "x"}},
        {"op": "update_component", "routine": "trial", "id": "fix", "properties": {"duration": 0.3}},
        {"op": "add_device", "type": "sim_eeg", "id": "eeg2"},
        {"op": "add_loop", "loop": "x", "children": ["trial"]}])
    assert r["ok"], r
    r = call(s, "edit_experiment", path=P, operations=[{"op": "add_routine", "rid": "z", "colour": 1}])
    assert not r["ok"] and "unknown argument colour" in r["error"] and "add_routine takes rid" in r["error"]


def test_misspelled_tool_arguments_are_refused_without_a_backup(ws):
    root, s = ws
    before = (root / P).read_text()
    r = call(s, "update_component", path=P, routine="trial", id="fix", props={"duration": 0.25})
    assert not r["ok"] and "did you mean 'properties'" in r["error"]
    r = call(s, "update_component", path=P, routine="trial", id="fix", properties={})
    assert r["ok"] and r["changes"] == []
    assert (root / P).read_text() == before and call(s, "list_versions", path=P)["versions"] == []


# ---------------------------------------------------------------- mcp#26: plain errors
def test_common_mistakes_get_plain_messages(ws):
    root, s = ws
    r = call(s, "analyze_session", session=P)
    assert "is an experiment file, not a session folder" in r["error"] and "trace" not in r
    r = call(s, "analyze_session", session="stroop")
    assert "is an experiment folder, not a session folder" in r["error"]
    r = call(s, "import_experiment_bundle", bundle=P, directory="x")
    assert "not an EDGE bundle" in r["error"] and "trace" not in r


def test_stdio_failures_are_errors_and_server_reports_edge_version(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from edge import __version__

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "edge", "mcp", str(tmp_path)], cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as cs:
                init = await cs.initialize()
                assert init.serverInfo.version == __version__
                res = await cs.call_tool("add_component", {"path": "nope.yaml", "routine": "x", "type": "text"})
                assert res.isError and res.structuredContent["ok"] is False
                res = await cs.call_tool("create_experiment", {"path": "x.yaml"})
                assert not res.isError and res.structuredContent["ok"]
    asyncio.run(go())


# ---------------------------------------------------------------- mcp#27: listing and creating experiments
def test_experiments_in_folders_called_data_are_listed(ws):
    root, s = ws
    assert call(s, "create_experiment", path="data/study1/study1.yaml", template="blank")["ok"]
    assert call(s, "create_experiment", path="lab/data/study2.yaml", template="blank")["ok"]
    r = call(s, "create_experiment", path="new/a.txt")
    assert not r["ok"] and "new/a.yaml" in r["error"]
    call(s, "dry_run", path=P)      # its session copy (data/dry_runs/…/experiment.yaml) is not an experiment
    paths = [e["path"] for e in call(s, "list_experiments")["experiments"]]
    assert {"data/study1/study1.yaml", "lab/data/study2.yaml", P} <= set(paths)
    assert not any("dry_runs" in p for p in paths)
    assert [e["path"] for e in call(s, "list_experiments", directory="data")["experiments"]] == ["data/study1/study1.yaml"]


# ---------------------------------------------------------------- mcp#28: help
def test_every_search_hit_can_be_read(ws):
    root, s = ws
    hits = call(s, "search_help", query="practice until accuracy")["results"]
    assert any(h["topic"] == "tutorial" for h in hits)
    for h in hits:
        r = call(s, "read_help", topic=h["topic"], section=h["anchor"])
        assert "markdown" in r, (h, r)
    r = call(s, "read_help", topic="nonsense")
    assert "topics: README" in r["error"]


# ---------------------------------------------------------------- mcp#30, wizard#16, mcp#34: wizard and descriptions
@pytest.mark.parametrize("answers, words", [
    ({"stimuli": ["a"]}, "did you mean 'stimulus'"),
    ({"stimulus": {"kind": "word", "stimuli": []}}, "'stimulus' takes items, kind"),
    ({"devices": ["tobi"]}, "did you mean 'tobii'"),
    ({"blocks": {"count": -2}}, "at least 1"),
])
def test_wizard_answers_are_checked_before_anything_is_written(ws, answers, words):
    root, s = ws
    r = call(s, "create_from_wizard", path="wiz/x.yaml", answers=answers)
    assert not r["ok"] and words in r["error"]
    assert not (root / "wiz" / "x.yaml").exists()


def test_tool_descriptions_and_docs_are_complete(ws):
    root, s = ws
    from edge.templates import public_templates
    tools = {t.name: t for t in asyncio.run(s.list_tools())}
    for name in public_templates():
        assert name in tools["create_experiment"].description
    assert "questionnaires" in tools["create_from_wizard"].description    # (MCP.md: tests/test_fixes_e.py)
    d = call(s, "describe_experiment", path="questionnaire/questionnaire.yaml")
    assert isinstance(d["measures"], list)


def test_edge_mcp_takes_the_folder_like_edge_builder(monkeypatch, tmp_path):
    import edge.mcp_server as ms
    from edge import cli
    seen = {}
    monkeypatch.setattr(ms, "main", lambda root, transport: seen.update(root=root))
    assert cli.main(["mcp", str(tmp_path)]) == 0 and seen["root"] == str(tmp_path)


# ---------------------------------------------------------------- cli#10: support bundle from a session
def test_support_bundle_of_a_session_checks_the_experiment_folder(tmp_path):
    from edge.support import make_bundle
    shutil.copytree(EXAMPLES / "stroop", tmp_path / "stroop")
    s = create_server(tmp_path)
    assert call(s, "dry_run", path=P)["ok"]
    session = next((tmp_path / "stroop" / "data" / "dry_runs").iterdir())
    res = make_bundle(session, tmp_path / "sb.zip")
    with zipfile.ZipFile(res["bundle"]) as z:
        text = z.read("validation.txt").decode()
    assert "not found" not in text and "isn't defined" not in text and "no issues" in text


# ---------------------------------------------------------------- install#20: builder help messages
def test_builder_help_lookups_say_what_exists(tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from edge.builder.server import BuilderApp, make_handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        code, body = get("/api/help/tutorial?id=bogus")
        assert code == 404 and body["error"].startswith("no tutorial 'bogus'; available: ")
        code, body = get("/api/help/topic?id=NOPE_TOPIC")
        assert code == 404 and body["error"].startswith("no help topic 'NOPE_TOPIC'")
        code, body = get("/api/help/topic")
        assert code == 400 and body["error"] == "the request needs ?id=…"
    finally:
        httpd.shutdown()


# ---------------------------------------------------------------- install#21: docs build only in a checkout
def test_docs_build_refuses_outside_a_source_checkout(monkeypatch, tmp_path, capsys):
    from edge import cli
    from edge import help as hp
    (tmp_path / "edge").mkdir()
    monkeypatch.setattr(hp, "PACKAGE_DIR", tmp_path / "edge")      # like site-packages/edge
    assert not hp.is_source_checkout()
    assert cli.main(["docs", "build"]) == 2
    assert "source checkout" in capsys.readouterr().err
    assert not (tmp_path / "docs").exists()
