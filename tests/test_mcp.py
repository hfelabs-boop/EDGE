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
        return structured.get("result", structured)
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
