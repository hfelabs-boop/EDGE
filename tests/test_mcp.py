"""MCP server tests: tool functions in-process, plus one real stdio session with the official client."""
import asyncio
import json
import sys

import pytest

mcp = pytest.importorskip("mcp")

from edge.mcp_server import create_server  # noqa: E402


def call(server, tool, **args):
    res = asyncio.run(server.call_tool(tool, args))
    # FastMCP returns (content, structured) for tools with a return annotation
    if isinstance(res, tuple):
        structured = res[1]
        # FastMCP wraps non-dict return values as {"result": value}
        return structured["result"] if set(structured) == {"result"} else structured
    return json.loads(res[0].text)


@pytest.fixture
def server(tmp_path):
    return create_server(tmp_path)


def test_tools_are_listed(server):
    names = {t.name for t in asyncio.run(server.list_tools())}
    for n in ("create_experiment", "edit_experiment", "add_component", "dry_run", "export_data", "undo",
              "describe_experiment", "scan_hardware", "analyze_session"):
        assert n in names


def test_build_validate_dry_run_export_undo(server, tmp_path):
    assert call(server, "create_experiment", path="s/stroop.yaml", name="stroop")["ok"]
    r = call(server, "edit_experiment", path="s/stroop.yaml", operations=[
        {"op": "add_device", "dtype": "gazepoint", "did": "et"},
        {"op": "add_routine", "rid": "trial"},
        {"op": "add_component", "rid": "trial", "ctype": "fixation", "properties": {"duration": 0.3}},
        {"op": "add_component", "rid": "trial", "ctype": "text", "cid": "word",
         "properties": {"text": "$word", "color": "$ink", "start": 0.3, "marker": "word_on"}},
        {"op": "add_component", "rid": "trial", "ctype": "keyboard",
         "properties": {"keys": ["r", "g"], "start": 0.3, "duration": 2, "correct": "$key", "end_routine": True}},
        {"op": "add_loop", "lid": "trials", "children": ["trial"], "order": "random", "repeats": 3},
        {"op": "set_conditions", "lid": "trials", "file": "stroop.csv", "write_file": True,
         "rows": [{"word": "RED", "ink": "red", "key": "r"}, {"word": "RED", "ink": "green", "key": "g"}]},
    ])
    assert r["ok"] and r["valid"], r
    assert (tmp_path / "s" / "stroop.csv").exists()
    out = call(server, "describe_experiment", path="s/stroop.yaml")["outline"]
    assert "loop trials [stroop.csv, random, repeats 3]" in out
    dr = call(server, "dry_run", path="s/stroop.yaml", participant="p9")
    assert dr["ok"] and dr["trials"] == 6 and dr["summary_detected"]["rt_column"] == "resp.rt"
    assert dr["streams"]["et.gaze"]["triggers"]["matched"] > 0
    ex = call(server, "export_data", path="s/data", formats=["csv", "xlsx"], include_dry_runs=True)
    assert ex["ok"] and any(f.endswith(".xlsx") for f in ex["files"])
    sess = call(server, "list_sessions", directory="s", include_dry_runs=True)["sessions"]
    an = call(server, "analyze_session", session=sess[0]["path"])
    assert an["summary"][0]["factor"] == "(all)"
    # undo the last edit: the conditions (set_conditions was part of the batch -> whole batch undone)
    call(server, "update_settings", path="s/stroop.yaml", settings={"window": {"background": "#123456"}})
    assert "#123456" in (tmp_path / "s" / "stroop.yaml").read_text()
    assert call(server, "undo", path="s/stroop.yaml")["ok"]
    assert "#123456" not in (tmp_path / "s" / "stroop.yaml").read_text()


def test_batch_is_all_or_nothing(server, tmp_path):
    call(server, "create_experiment", path="e.yaml")
    before = (tmp_path / "e.yaml").read_text()
    r = call(server, "edit_experiment", path="e.yaml", operations=[
        {"op": "add_routine", "rid": "ok"},
        {"op": "add_component", "rid": "ok", "ctype": "text", "properties": {"colour": "red"}}])
    assert not r["ok"] and "colour" in r["error"] and "operation 1" in r["error"]
    assert (tmp_path / "e.yaml").read_text() == before


def test_paths_cannot_escape_workspace(server):
    r = call(server, "describe_experiment", path="../../etc/passwd")
    assert not r["ok"] and "outside the workspace" in r["error"]
    r = call(server, "write_file", path="evil.py", content="print(1)")
    assert not r["ok"]


def test_errors_are_returned_not_raised(server):
    call(server, "create_experiment", path="e.yaml")
    r = call(server, "add_component", path="e.yaml", routine="nope", type="text")
    assert r["ok"] is False and "no routine 'nope'" in r["error"]


def test_help_tools(server):
    assert "keys" in call(server, "list_component_types", type="keyboard")["props"]
    assert any(d["type"] == "tobii" for d in call(server, "list_device_types")["devices"])
    assert "staircase" in call(server, "list_templates")


def test_real_stdio_session(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "edge", "mcp", "--root", str(tmp_path)])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                assert init.serverInfo.name == "edge" and "EDGE" in init.instructions
                res = await s.call_tool("create_experiment", {"path": "x.yaml", "template": "eeg_oddball"})
                assert res.structuredContent["ok"]
                res = await s.call_tool("validate_experiment", {"path": "x.yaml"})
                assert res.structuredContent["valid"]
                prompts = await s.list_prompts()
                assert "design_experiment" in [p.name for p in prompts.prompts]
                doc = await s.read_resource("edge://docs/experiment-format")
                assert "Expressions" in doc.contents[0].text

    asyncio.run(go())


def test_workflow_rules_and_import_tools(server, tmp_path):
    import shutil
    from pathlib import Path
    call(server, "create_experiment", path="w.yaml")
    r = call(server, "edit_experiment", path="w.yaml", operations=[
        {"op": "add_routine", "rid": "trial", "add_to_flow": False},
        {"op": "add_component", "rid": "trial", "ctype": "keyboard", "properties": {"keys": ["f", "j"],
                                                                                     "correct": "f", "end_routine": True}},
        {"op": "add_routine", "rid": "main_trial"},
        {"op": "add_component", "rid": "main_trial", "ctype": "keyboard", "properties": {"end_routine": True}},
        {"op": "add_loop", "lid": "practice", "children": ["trial"], "repeats": 4},
        {"op": "add_loop", "lid": "main", "children": ["main_trial"], "repeats": 2}])
    assert r["ok"], r
    r = call(server, "add_workflow", path="w.yaml", workflow="session", states={
        "train": {"run": [{"loop": "practice"}], "max_visits": 3,
                  "next": [{"if": "$practice.accuracy >= 0.75", "goto": "test"}, {"goto": "train"}]},
        "test": {"run": [{"loop": "main"}], "next": ["end"]}})
    assert r["ok"] and r["valid"], r
    doc = json.loads(json.dumps(__import__("yaml").safe_load((tmp_path / "w.yaml").read_text())))
    assert doc["flow"] == [doc["flow"][0]] and doc["flow"][0]["statemachine"] == "session"   # loops moved inside
    assert doc["flow"][0]["states"]["train"]["run"][0]["loop"] == "practice"
    r = call(server, "add_routine_rule", path="w.yaml", routine="trial", when="$t > 5", do=[{"goto": "test"}])
    assert r["ok"]
    bad = call(server, "add_routine_rule", path="w.yaml", routine="trial", when="$t > 5", do=[{"start": "ghost"}])
    assert not bad["ok"] and "ghost" in bad["error"]
    out = call(server, "describe_experiment", path="w.yaml")["outline"]
    assert "workflow session" in out and "state train, max 3 visits -> test if $practice.accuracy >= 0.75 | train" in out
    dr = call(server, "dry_run", path="w.yaml")
    assert dr["ok"], dr
    # import a PsychoPy experiment through MCP
    src = Path(__file__).parent / "fixtures" / "psychopy"
    shutil.copytree(src, tmp_path / "pp")
    imp = call(server, "import_experiment", source="pp/stroop.psyexp", out_dir="pp_edge")
    assert imp["ok"] and imp["path"] == "pp_edge/stroop.yaml" and imp["valid"]
    assert any("Movie" in x for x in imp["needs_manual_work"])
