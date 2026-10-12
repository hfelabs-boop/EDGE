"""The assistant's loop against scripted models: build a Stroop task from a CSV end to end (three services),
all-or-nothing edits, trial lists from files, the code gate, the JSON protocol for models without tools,
limits, follow-ups and the system prompt."""

from __future__ import annotations

import copy
import io
import json
import threading
from pathlib import Path

import pytest

from assistant_fakes import (FINAL_TEXT, GOLDEN_OPS, FakeAnthropic, FakeLMStudio, FakeOllama, FakeOpenAI,
                             assert_append_only, png_bytes, xlsx_bytes)
from edge.assistant import http as H
from edge.assistant.agent import AssistantRequest, EventSink
from edge.assistant.attachments import store_attachment
from edge.assistant.config import load_config, update_config
from edge.assistant.errors import AssistantError
from edge.assistant.fallback import extract_envelope, recover_text_tool_calls
from edge.assistant.http import CancelEvent
from edge.assistant.jobs import Conversation, execute, normalized_base
from edge.assistant.ops import EXTRA_OPS, OP_DOCS, FileLedger
from edge.assistant.providers import anthropic as A
from edge.assistant.providers.anthropic import AnthropicProvider
from edge.assistant.providers.lmstudio import LMStudioProvider
from edge.assistant.providers.ollama import _SHOW_CACHE, OllamaProvider
from edge.assistant.providers.openai_compat import OpenAICompatProvider
from edge.editing import ALLOWED_OPS, ExperimentDoc, apply_operations

FIX = Path(__file__).parent / "fixtures" / "assistant"
KEY = "sk-ant-agent-test-0000000000000000-AAAA"
EXP = "stroop_ai/stroop_ai.yaml"
BLANK = {"name": "stroop_ai", "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
         "devices": [], "variables": {}, "routines": {}, "flow": []}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(H, "RETRY_BASE", 0.01)
    monkeypatch.setattr(A, "DISABLED_FEATURES", set())
    _SHOW_CACHE.clear()


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    (root / "stroop_ai").mkdir(parents=True)
    from edge.storage import save_document
    save_document(root / EXP, BLANK)
    return root


def provider_for(kind, fake):
    if kind == "anthropic":
        return AnthropicProvider({"base_url": fake.url, "model": "claude-opus-5-5"}, key=KEY)
    if kind == "openai":
        return OpenAICompatProvider({"preset": "custom", "base_url": fake.url + "/v1", "model": "gpt-5.1"},
                                    key="sk-test-1234567890123456789")
    if kind == "lmstudio":
        return LMStudioProvider({"base_url": fake.url + "/v1", "model": "qwen2.5-14b-instruct"})
    return OllamaProvider({"base_url": fake.url, "model": fake.model_name if hasattr(fake, "model_name") else "qwen2.5:14b"})


def ask(root, prov, message, doc=None, attachments=(), conv=None, path=EXP, recap=None, dry=True, cancel=None,
        limits=None):
    cfg = load_config()
    conv = conv or Conversation(id="c", provider=prov.name, model=prov.model or "", base_url=prov.base_url,
                                experiment_path=path)
    doc = copy.deepcopy(doc if doc is not None else BLANK)
    req = AssistantRequest(experiment=doc, path=path, message=message, attachments=list(attachments),
                           auto_dry_run=dry, recap=recap)
    sink = EventSink()
    ledger = FileLedger((root / path).parent if path else None)
    if limits:
        from edge.assistant import agent as AG
        orig = AG.Limits.for_provider
        AG.Limits.for_provider = classmethod(lambda cls, local, o=None: limits)
    try:
        res = execute(req, conv, prov, cfg, root, sink, cancel or CancelEvent(), ledger,
                      normalized_base(doc, (root / path) if path else None))
    finally:
        if limits:
            AG.Limits.for_provider = orig
    return res, sink, conv, ledger


def stroop_script(kind):
    steps = [("read_attachment", {"file": "conditions/words.csv"}, "I'll read your list and build the task."),
             ("apply_operations", {"operations": GOLDEN_OPS}, ""), ("validate", {}, ""), ("dry_run", {}, "")]
    if kind == "anthropic":
        turns = [FakeAnthropic.turn(*([FakeAnthropic.thinking(f"sig-{i}", "")] + ([FakeAnthropic.text(say)] if say else [])
                                      + [FakeAnthropic.tool(name, inp, id=f"t{i}")]))
                 for i, (name, inp, say) in enumerate(steps)]
        return turns + [FakeAnthropic.turn(FakeAnthropic.text(FINAL_TEXT))]
    if kind == "openai":
        return [FakeOpenAI.turn(*([FakeOpenAI.text(say)] if say else []), FakeOpenAI.tool(name, inp, id=f"c{i}"))
                for i, (name, inp, say) in enumerate(steps)] + [FakeOpenAI.turn(FakeOpenAI.text(FINAL_TEXT))]
    return [FakeOllama.turn(*([FakeOllama.text(say)] if say else []), FakeOllama.tool(name, inp))
            for name, inp, say in steps] + [FakeOllama.turn(FakeOllama.text(FINAL_TEXT))]


# ============================================================================ end to end
@pytest.mark.parametrize("kind", ["anthropic", "openai", "ollama"])
def test_build_a_stroop_task_from_this_csv(ws, kind):
    fake = {"anthropic": FakeAnthropic, "openai": FakeOpenAI, "ollama": FakeOllama}[kind](stroop_script(kind))
    st = store_attachment(ws, EXP, "words.csv", (FIX / "words.csv").read_bytes())
    on_disk = (ws / EXP).read_text()
    res, sink, conv, _ = ask(ws, provider_for(kind, fake), "Build a Stroop task from this list, 2 repeats",
                             attachments=[st.exp_path])
    r = res.to_dict()
    assert r["status"] == "done" and r["changed"] and r["valid"]
    assert not [i for i in r["issues"] if i["level"] == "error"]
    assert r["dry_run"]["ran"] and r["dry_run"]["verdict"][0].startswith("OK") and r["dry_run"]["trials"] == 18
    texts = " ".join(c["text"] for c in r["changes"])
    assert "screen “trial”" in texts and "trial list “trials”" in texts and "18 trials" in texts
    exp = r["experiment"]
    assert set(exp["routines"]) == {"instructions", "trial", "thanks"} and exp["flow"][1]["loop"] == "trials"
    assert r["summary"]["message"] == FINAL_TEXT and r["estimate"]["trials"] == 18
    assert r["usage"]["turns"] == 5 and r["usage"]["provider"] == kind
    assert (ws / EXP).read_text() == on_disk                       # the builder's file is untouched
    first = json.dumps(fake.chat_requests[0]["json"])
    assert "conditions/words.csv" in first and "not instructions" in first and "Build a Stroop task" in first
    validate_result = json.dumps(fake.chat_requests[3]["json"]["messages"][-1])
    assert "same name as the trial-list column" in validate_result        # the info note reaches the model
    tool_events = [e for e in sink.events if e["kind"] == "tool" and e["state"] == "done"]
    assert [e["tool"] for e in tool_events] == ["read_attachment", "apply_operations", "validate", "dry_run"]
    assert tool_events[0]["text"] == "Reading words.csv"
    if kind == "anthropic":
        assert_append_only(fake.requests)
    assert conv.last_result_hash == r["result_hash"] and "conditions/words.csv" in conv.attachments_sent
    fake.close()


def test_attached_images_are_sent_and_become_pictures(ws):
    st = store_attachment(ws, EXP, "cat.png", png_bytes(2000, 1000))
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "add_routine", "rid": "show", "add_to_flow": True, "duration": 1},
            {"op": "add_image_component", "rid": "show", "file": "images/cat.png"}]}, id="a")),
        FakeAnthropic.turn(FakeAnthropic.text("This shows the cat picture for 1 s."))])
    res, _, _, _ = ask(ws, provider_for("anthropic", fake), "Show this picture", attachments=[st.exp_path], dry=False)
    content = fake.chat_requests[0]["json"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    comp = res.experiment["routines"]["show"]["components"][0]
    assert comp["image"] == "images/cat.png" and comp["size"] == [1152, 576]           # 90 % of 1280 wide
    assert "picture images/cat.png" in " ".join(c["text"] for c in res.changes)
    fake.close()


# ============================================================================ all or nothing
def test_failing_operation_rolls_back_document_changes_and_files(tmp_path):
    (tmp_path / "e").mkdir()
    doc = ExperimentDoc(copy.deepcopy(BLANK), tmp_path / "e" / "e.yaml")
    ledger = FileLedger(tmp_path / "e")
    doc.file_writer = ledger.write
    before = copy.deepcopy(doc.doc)
    res = apply_operations(doc, [
        {"op": "add_routine", "rid": "trial", "add_to_flow": True},
        {"op": "add_loop", "lid": "trials", "children": ["trial"]},
        {"op": "set_conditions", "lid": "trials", "rows": [{"a": 1}], "file": "conditions/x.csv", "write_file": True},
        {"op": "add_component", "rid": "trail", "ctype": "text"}], ledger=ledger)
    assert not res["ok"] and res["failed_index"] == 3 and res["op"] == "add_component"
    assert "operation 3 (add_component): no routine 'trail'" in res["error"]
    assert doc.doc == before and doc.changes == [] and not (tmp_path / "e/conditions/x.csv").exists()
    res = apply_operations(doc, [{"op": "add_routine", "rid": "a"}, {"op": "add_component", "rid": "a", "ctype": "text",
                                                                      "properties": "not a dict"}])
    assert not res["ok"] and res["failed_index"] == 1 and doc.doc == before
    res = apply_operations(doc, [{"op": "add_routine", "rid": "a", "colour": 1}])
    assert "bad arguments" in res["error"] and "add_routine(rid" in res["error"]
    res = apply_operations(doc, [{"op": "os.system"}])
    assert "unknown op" in res["error"]


def test_ledger_never_overwrites_files_it_did_not_write(tmp_path):
    (tmp_path / "e/conditions").mkdir(parents=True)
    (tmp_path / "e/conditions/x.csv").write_text("mine\n")
    ledger = FileLedger(tmp_path / "e")
    from edge.editing import EditError
    with pytest.raises(EditError, match="never overwrites"):
        ledger.write(tmp_path / "e/conditions/x.csv", "a\n")
    with pytest.raises(EditError, match="trial lists"):
        ledger.write(tmp_path / "e/run.py", "print(1)")
    with pytest.raises(EditError, match="data/"):
        ledger.write(tmp_path / "e/data/x.csv", "a\n")
    with pytest.raises(EditError, match="inside"):
        ledger.write(tmp_path / "other.csv", "a\n")
    ledger.write(tmp_path / "e/conditions/y.csv", "a\n1\n")
    ledger.write(tmp_path / "e/conditions/y.csv", "a\n2\n")          # its own file: fine
    (tmp_path / "e/conditions/z.csv").write_text("z\n")
    ledger.write(tmp_path / "e/new.csv", "n\n")
    (tmp_path / "e/new.csv").write_text("changed by a person\n")       # changed since: kept
    assert ledger.rollback_all() == ["conditions/y.csv"]
    assert (tmp_path / "e/new.csv").exists() and (tmp_path / "e/conditions/x.csv").read_text() == "mine\n"


# ============================================================================ trial lists from files
def _doc_with_trial(root, cols="$word"):
    d = copy.deepcopy(BLANK)
    d["routines"]["trial"] = {"components": [
        {"id": "stim", "type": "text", "text": cols, "color": "$colour"},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "end_routine": True}]}
    d["flow"] = ["trial"]
    return d


def run_tool(root, doc, call_name, inp, kind="anthropic"):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool(call_name, inp, id="x")),
                          FakeAnthropic.turn(FakeAnthropic.text("Done."))])
    res, sink, _, ledger = ask(root, provider_for(kind, fake), "use it", doc=doc, dry=False)
    result = json.loads(fake.chat_requests[1]["json"]["messages"][-1]["content"][0]["content"][0]["text"])
    fake.close()
    return res, result, ledger


def test_set_conditions_from_a_non_active_excel_sheet(ws):
    data = xlsx_bytes({"info": [["note"], ["x"]], "trials": [["word", "color"], ["RED", "red"], ["BLUE", "blue"]]},
                      active=0)
    st = store_attachment(ws, EXP, "words.xlsx", data)
    res, out, _ = run_tool(ws, _doc_with_trial(ws), "set_conditions_from_file",
                           {"loop": "trials", "file": st.exp_path, "sheet": "trials",
                            "create_loop": {"children": ["trial"], "order": "random"}})
    assert out["ok"] and out["conditions"] == "conditions/words-trials.csv" and out["converted_from"] == "conditions/words.xlsx"
    assert out["rows"] == 2 and out["names_missing"] == ["colour"] and out["unused_columns"] == ["color"]
    assert (ws / "stroop_ai/conditions/words-trials.csv").read_text() == "word,color\nRED,red\nBLUE,blue\n"
    assert res.files_created == ["conditions/words-trials.csv"]
    loop = res.experiment["flow"][0]
    assert loop["loop"] == "trials" and loop["children"] == ["trial"] and loop["order"] == "random"   # wrapped
    assert any(c["kind"] == "file" for c in res.changes)


def test_bad_headers_are_renamed_into_a_csv_copy_never_over_a_file(ws):
    st = store_attachment(ws, EXP, "bad_headers.csv", (FIX / "bad_headers.csv").read_bytes())
    (ws / "stroop_ai/conditions/bad_headers_2.csv").parent.mkdir(exist_ok=True)
    d = _doc_with_trial(ws, "$word")
    d["flow"] = [{"loop": "trials", "children": ["trial"]}]
    res, out, _ = run_tool(ws, d, "set_conditions_from_file", {"loop": "trials", "file": st.exp_path})
    assert out["ok"] and out["renamed"] == {"Ink Colour": "ink_colour", "Correct Key": "correct_key",
                                            "2nd cue": "_2nd_cue"}
    assert out["conditions"] == "conditions/bad_headers_2.csv"        # never over the attached original
    assert (ws / "stroop_ai/conditions/bad_headers_2.csv").read_text().splitlines()[0] == \
        "Word,ink_colour,correct_key,_2nd_cue"
    assert (ws / "stroop_ai" / st.exp_path).read_text() == (FIX / "bad_headers.csv").read_text()     # original kept
    assert res.experiment["flow"][0]["conditions"] == out["conditions"]


def test_a_plain_csv_is_used_as_it_is(ws):
    st = store_attachment(ws, EXP, "words.csv", (FIX / "words.csv").read_bytes())
    d = _doc_with_trial(ws)
    d["flow"] = [{"loop": "trials", "children": ["trial"]}]
    res, out, _ = run_tool(ws, d, "set_conditions_from_file", {"loop": "trials", "file": st.exp_path})
    assert out["conditions"] == "conditions/words.csv" and out["converted_from"] is None and res.files_created == []
    assert "colour" in out["names_missing"]


def test_reading_outside_the_folder_or_data_is_refused(ws):
    (ws / "stroop_ai/data/001").mkdir(parents=True)
    (ws / "stroop_ai/data/001/trials.csv").write_text("participant,rt\n001,0.5\n")
    (ws / "secret.csv").write_text("a\n1\n")
    for f in ("data/001/trials.csv", "../secret.csv", ".edge/x.csv"):
        _, out, _ = run_tool(ws, BLANK, "read_attachment", {"file": f})
        assert out["ok"] is False and ("data or hidden" in out["error"] or "outside" in out["error"])


# ============================================================================ replace, code gate, confirm
def test_replace_experiment_and_confirm(ws):
    d = _doc_with_trial(ws)
    d["routines"]["other"] = {"components": [{"id": "t", "type": "text", "text": "x", "duration": 1}]}
    d["flow"] = ["trial", "other"]
    new = "name: fresh\nroutines:\n  only:\n    components:\n      - {id: t, type: text, text: hi, duration: 1}\nflow: [only]\n"
    res, out, _ = run_tool(ws, d, "replace_experiment", {"yaml": new, "reason": "rewrite"})
    assert out["ok"] and res.experiment["name"] == "fresh" and res.confirm["text"] == "This replaces most of your experiment."
    _, out, _ = run_tool(ws, d, "replace_experiment", {"yaml": "just text"})
    assert out["ok"] is False


def test_replace_is_refused_after_a_shortened_view(ws):
    d = _doc_with_trial(ws)
    d["flow"] = [{"loop": "trials", "conditions": [{"word": str(i)} for i in range(80)], "children": ["trial"]}]
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("get_experiment", {"view": "yaml"}, id="g")),
        FakeAnthropic.turn(FakeAnthropic.tool("replace_experiment", {"yaml": "name: x\nroutines: {}\nflow: []\n"}, id="r")),
        FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    res, _, _, _ = ask(ws, provider_for("anthropic", fake), "rewrite", doc=d, dry=False)
    got = json.loads(fake.chat_requests[1]["json"]["messages"][-1]["content"][0]["content"][0]["text"])
    assert "80 inline rows" in got["shortened"][0]
    refused = json.loads(fake.chat_requests[2]["json"]["messages"][-1]["content"][0]["content"][0]["text"])
    assert refused["ok"] is False and "apply_operations" in refused["error"] and not res.changed
    fake.close()


def test_code_written_by_the_assistant_is_never_test_run(ws):
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "add_routine", "rid": "s", "add_to_flow": True, "duration": 0.5},
            {"op": "add_component", "rid": "s", "ctype": "code", "cid": "score_code",
             "properties": {"on_begin": "score = 0"}}]}, id="a")),
        FakeAnthropic.turn(FakeAnthropic.tool("dry_run", {}, id="d")),
        FakeAnthropic.turn(FakeAnthropic.text("Added code."))])
    res, sink, _, _ = ask(ws, provider_for("anthropic", fake), "score it")
    skipped = json.loads(fake.chat_requests[2]["json"]["messages"][-1]["content"][0]["content"][0]["text"])
    assert skipped["skipped"] and "read it" in skipped["skipped"]
    assert res.dry_run == {"ran": False, "skipped": "it contains code you need to read first", "verdict": [], "trials": None}
    assert res.review[0]["kind"] == "code" and res.review[0]["routine"] == "s" and res.review[0]["id"] == "score_code"
    assert "read it before running participants" in res.review[0]["text"]
    fake.close()


def test_review_flags_devices_scripts_and_data_folder(ws):
    from edge.assistant.diffsum import review_items
    before = copy.deepcopy(BLANK)
    after = copy.deepcopy(BLANK)
    after["devices"] = [{"id": "udp", "type": "udp_messages", "options": {"host": "0.0.0.0"}}]
    after["routines"]["p"] = {"components": [{"id": "page", "type": "html", "html": "<script>alert(1)</script>"}]}
    after["settings"]["data"] = {"dir": "../elsewhere"}
    kinds = [r["kind"] for r in review_items(before, after)]
    assert kinds == ["script", "device", "network", "data_dir"]


# ============================================================================ refusals, cut-off tool calls, history
def test_refusal_ends_the_job_and_rolls_back(ws):
    fake = FakeAnthropic([FakeAnthropic.turn(stop="refusal", stop_details={"type": "refusal", "category": "bio",
                                                                          "explanation": "x"})])
    prov = provider_for("anthropic", fake)
    conv = Conversation(id="c", provider="anthropic", model="claude-opus-5-5", base_url=fake.url, experiment_path=EXP)
    with pytest.raises(AssistantError) as e:
        ask(ws, prov, "something", conv=conv)
    assert e.value.code == "refused" and "(bio)" in e.value.message
    assert conv.transcript.native == []                                  # the failed job's tail is rolled back
    fake.close()


def test_cut_off_tool_calls_are_not_run(ws):
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [{"op": "add_routine", "rid": "x"}]},
                                              id="cut"), stop="max_tokens"),
        FakeAnthropic.turn(FakeAnthropic.text("Sorry."))])
    res, _, _, _ = ask(ws, provider_for("anthropic", fake), "x")
    msg = fake.chat_requests[1]["json"]["messages"][-1]["content"][0]
    assert msg["is_error"] and "cut off" in msg["content"][0]["text"] and not res.changed
    fake.close()


def test_follow_up_turns_describe_what_changed(ws):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
        {"op": "add_routine", "rid": "a", "add_to_flow": True, "duration": 1}]}, id="1")),
        FakeAnthropic.turn(FakeAnthropic.text("Added a."))] + [FakeAnthropic.turn(FakeAnthropic.text("ok"))] * 3)
    prov = provider_for("anthropic", fake)
    res, _, conv, _ = ask(ws, prov, "first", dry=False)
    assert res.changed
    applied = res.experiment
    ask(ws, prov, "second", doc=applied, conv=conv)
    text2 = fake.chat_requests[2]["json"]["messages"][-1]["content"][-1]["text"]
    assert "Changes since your last turn: none" in text2 and "Outline" not in text2
    edited = copy.deepcopy(applied)
    edited["routines"]["a"]["duration"] = 2
    ask(ws, prov, "third", doc=edited, conv=conv)
    assert "the researcher edited the experiment" in fake.chat_requests[3]["json"]["messages"][-1]["content"][-1]["text"]
    ask(ws, prov, "fourth", doc=BLANK, conv=Conversation(id="c2", provider="anthropic", model="claude-opus-5-5",
                                                          base_url=fake.url, experiment_path=EXP), recap=[
        {"role": "user", "text": "make a stroop"}, {"role": "assistant", "text": "I built it."}])
    text4 = fake.chat_requests[4]["json"]["messages"][0]["content"][-1]["text"]
    assert "<earlier_conversation>" in text4 and "make a stroop" in text4
    assert_append_only(fake.requests[:4])
    fake.close()


def test_undo_is_noticed(ws):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
        {"op": "add_routine", "rid": "a", "add_to_flow": True, "duration": 1}]}, id="1")),
        FakeAnthropic.turn(FakeAnthropic.text("Added a.")), FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    prov = provider_for("anthropic", fake)
    _, _, conv, _ = ask(ws, prov, "first", dry=False)
    ask(ws, prov, "again", doc=BLANK, conv=conv)
    assert "undid or discarded" in fake.chat_requests[2]["json"]["messages"][-1]["content"][-1]["text"]
    fake.close()


def test_focus_is_described(ws):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    prov = provider_for("anthropic", fake)
    cfg = load_config()
    conv = Conversation(id="c", provider="anthropic", model="claude-opus-5-5", base_url=fake.url, experiment_path=EXP)
    d = _doc_with_trial(ws)
    req = AssistantRequest(experiment=d, path=EXP, message="make this bigger",
                           focus={"kind": "component", "routine": "trial", "id": "stim"})
    execute(req, conv, prov, cfg, ws, EventSink(), CancelEvent(), FileLedger(ws / "stroop_ai"),
            normalized_base(d, ws / EXP))
    text = fake.chat_requests[0]["json"]["messages"][0]["content"][-1]["text"]
    assert '<selected>The researcher has selected component "stim" (text) in screen "trial".</selected>' in text
    fake.close()


# ============================================================================ models without tools
def test_json_protocol_for_ollama_models_without_tools(ws):
    env = lambda **k: FakeOllama.turn(FakeOllama.text(json.dumps(k)))
    fake = FakeOllama([
        env(say="I'll add a screen.", tool={"name": "apply_operations", "input": {"operations": [
            {"op": "add_routine", "rid": "hello", "add_to_flow": True, "duration": 1},
            {"op": "add_component", "rid": "hello", "ctype": "text", "properties": {"text": "$greeting"}}]}}),
        env(say="Done: added a screen.", done=True),            # leaves an error: $greeting is not defined
        FakeOllama.turn(FakeOllama.text('Sure.\n```json\n{"say": "fixing", "tool": {"name": "apply_operations", '
                                        '"input": {"operations": [{"op": "update_component", "rid": "hello", '
                                        '"cid": "text", "set_props": {"text": "Hello"}}]}}}\n```')),
        env(say="Fixed: the screen says Hello.", done=True)],
        models={"gemma2:9b": {"tools": False, "context": 32768, "size": "9B"}})
    fake.model_name = "gemma2:9b"
    res, sink, conv, _ = ask(ws, provider_for("ollama", fake), "add a hello screen", dry=False)
    assert conv.tool_mode == "json" and "tools" not in fake.chat_requests[0]["json"]
    assert fake.chat_requests[0]["json"]["format"]["required"] == ["say"]
    assert "exactly ONE JSON object" in fake.chat_requests[0]["json"]["messages"][0]["content"]
    assert "Your changes left these problems" in fake.chat_requests[2]["json"]["messages"][-1]["content"]
    assert '"tool_result"' in fake.chat_requests[1]["json"]["messages"][-1]["content"]
    assert res.valid and res.experiment["routines"]["hello"]["components"][0]["text"] == "Hello"
    assert res.summary["message"] == "Fixed: the screen says Hello."
    fake.close()


def test_three_unreadable_answers_fail_and_change_nothing(ws):
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("I think we should")) for _ in range(3)],
                      models={"gemma2:9b": {"tools": False, "context": 32768, "size": "9B"}})
    fake.model_name = "gemma2:9b"
    with pytest.raises(AssistantError) as e:
        ask(ws, provider_for("ollama", fake), "x")
    assert e.value.code == "bad_response"
    assert "not one JSON object" in fake.chat_requests[1]["json"]["messages"][-1]["content"]
    fake.close()


def test_tools_refused_mid_way_switches_to_json(ws):
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text('{"say": "Hi, nothing to change.", "done": true}'))],
                      models={"odd:14b": {"tools": True, "context": 32768, "size": "14B"}})
    fake.model_name = "odd:14b"
    prov = provider_for("ollama", fake)
    prov.capabilities("odd:14b")                       # /api/show answered before the failure is queued
    fake.fail_next(400, {"error": "registry.ollama.ai/library/odd does not support tools"})
    res, sink, conv, _ = ask(ws, prov, "hello")
    assert conv.tool_mode == "json" and res.summary["message"] == "Hi, nothing to change." and not res.changed
    assert any("JSON mode" in e["text"] for e in sink.events)
    fake.close()


@pytest.mark.parametrize("text, name", [
    ('{"say": "x", "tool": {"name": "validate", "input": {}}}', "validate"),
    ('Sure!\n```json\n{"say": "x", "tool": {"name": "dry_run", "input": {}}}\n```', "dry_run"),
    ('Here you go: {"say": "brace } in a string", "tool": {"name": "validate", "input": {}}} thanks', "validate"),
    ('[{"op": "add_routine", "rid": "a"}]', "apply_operations"),
    ('```yaml\nname: x\nroutines: {}\nflow: []\n```', "replace_experiment"),
    ('{"name": "validate", "arguments": {}}', "validate"),
])
def test_envelope_extraction(text, name):
    assert extract_envelope(text)["tool"]["name"] == name


def test_envelope_extraction_fails_on_prose():
    assert extract_envelope("I would add a screen.") is None and extract_envelope("") is None
    assert extract_envelope('{"say": "all done", "done": true}') == {"say": "all done", "done": True}


def test_text_tool_calls_are_recovered_for_local_models(ws):
    fake = FakeLMStudio([
        FakeLMStudio.turn(FakeLMStudio.text('Let me check.\n<tool_call>{"name": "apply_operations", "arguments": '
                                            '{"operations": [{"op": "add_routine", "rid": "r", "add_to_flow": true, '
                                            '"duration": 1}]}}</tool_call>')),
        FakeLMStudio.turn(FakeLMStudio.text("Added screen r."))])
    res, _, _, _ = ask(ws, provider_for("lmstudio", fake), "add r", dry=False)
    assert "r" in res.experiment["routines"]
    assert fake.chat_requests[1]["json"]["messages"][-1]["content"].startswith("Result of apply_operations:")
    assert recover_text_tool_calls('{"name": "nope", "arguments": {}}', {"validate"}) == []
    fake.close()


# ============================================================================ limits and context
def test_step_limit_gives_an_incomplete_result(ws):
    from edge.assistant.agent import Limits
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("validate", {}, id=f"v{i}")) for i in range(5)])
    res, sink, _, _ = ask(ws, provider_for("anthropic", fake), "loop", limits=Limits(max_turns=3))
    assert res.status == "incomplete" and len(fake.chat_requests) == 3
    fake.close()


def test_tool_call_limit_tells_the_model_to_finish(ws):
    from edge.assistant.agent import Limits
    fake = FakeAnthropic([FakeAnthropic.turn(*[FakeAnthropic.tool("validate", {}, id=f"v{i}") for i in range(3)]),
                          FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    ask(ws, provider_for("anthropic", fake), "x", limits=Limits(max_tool_calls=2))
    results = fake.chat_requests[1]["json"]["messages"][-1]["content"]
    assert results[2]["is_error"] and "limit" in results[2]["content"][0]["text"]
    fake.close()


def test_wall_clock_limit(ws):
    from edge.assistant.agent import Limits
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("validate", {}, id="v")),
                          FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    fake.delay(0.05)
    with pytest.raises(AssistantError) as e:
        ask(ws, provider_for("anthropic", fake), "x", limits=Limits(wall_clock_s=0.2))
    assert e.value.code == "step_limit"
    fake.close()


def test_cancel_rolls_back_files(ws):
    st = store_attachment(ws, EXP, "words.xlsx", xlsx_bytes({"a": [["x"], [1]], "b": [["y"], [2]]}))
    cancel = CancelEvent()

    def second(req):
        cancel.set()
        return FakeAnthropic.turn(FakeAnthropic.text("late"))
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("set_conditions_from_file", {
        "loop": "l", "file": st.exp_path, "sheet": "b", "create_loop": {"children": ["t"]}}, id="s")), second])
    d = copy.deepcopy(BLANK)
    d["routines"]["t"] = {"components": [{"id": "x", "type": "text", "text": "$y", "duration": 1}]}
    d["flow"] = ["t"]
    with pytest.raises(H.Cancelled):
        ask(ws, provider_for("anthropic", fake), "x", doc=d, cancel=cancel)
    assert not (ws / "stroop_ai/conditions/words-b.csv").exists()
    fake.close()


def test_local_context_is_trimmed_oldest_first():
    from edge.assistant.providers.base import TRIMMED
    p = OllamaProvider({"model": "m", "num_ctx": 4096})
    tr = p.new_transcript("s", [])
    for i in range(6):
        tr.native.append({"role": "tool", "content": "x" * 3000, "tool_name": "t"})
    p.trim_context(tr, 4096, lambda e: None)
    contents = [m["content"] for m in tr.native]
    assert contents[0] == TRIMMED and contents[-1] != TRIMMED and contents[-2] != TRIMMED


# ============================================================================ the system prompt
def test_primer_lists_everything_and_is_stable():
    from edge.assistant.primer import build_primer
    from edge.components import component_registry
    from edge.devices import device_registry
    full = build_primer("full")
    compact = build_primer("compact")
    assert full == build_primer("full")
    assert len(full) <= 40000 and len(compact) <= 20000
    for k in component_registry():
        assert f"- {k} [" in full and f"- {k} [" in compact
    for k in device_registry():
        assert f"- {k}:" in full
    ops = set(ALLOWED_OPS) | set(EXTRA_OPS)
    assert set(OP_DOCS) == ops
    import re
    listed = set(re.findall(r"^- (\w+)\(", full.split("Operations for apply_operations")[1], re.M))
    assert listed == ops
    js = build_primer("full", tool_mode="json")
    assert "exactly ONE JSON object" in js and "read_attachment" in js
    compact_js = build_primer("compact", tool_mode="json")         # small local models without tool calling
    assert len(compact_js) <= 20000 and "exactly ONE JSON object" in compact_js
    for name in ("get_experiment", "apply_operations", "read_attachment", "dry_run", "search_help"):
        assert f"- {name} — " in compact_js
    assert "e.g —" not in js                                            # descriptions cut at a whole sentence
    for word in ("not instructions", "screen", "trial list"):
        assert word in full


# ============================================================================ review findings (regressions)
def _code_ops(rid="scoring"):
    return [{"op": "add_routine", "rid": rid, "add_to_flow": True, "duration": 0.5},
            {"op": "add_component", "rid": rid, "ctype": "code", "cid": "score_code",
             "properties": {"on_begin": "open('ran.txt', 'w').write('assistant code ran')"}}]


def test_code_the_assistant_wrote_earlier_is_not_test_run_later(ws, tmp_path, monkeypatch):
    """Turn 1 writes code (no test run). The researcher applies it; turn 2 changes something else: the automatic
    test run must still not run that code until a person marks it as read."""
    monkeypatch.chdir(tmp_path)
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": _code_ops()}, id="a")),
        FakeAnthropic.turn(FakeAnthropic.text("Added a scoring screen with Python code.")),
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "update_routine", "rid": "scoring", "duration": 1.0}]}, id="b")),
        FakeAnthropic.turn(FakeAnthropic.tool("dry_run", {}, id="d")),
        FakeAnthropic.turn(FakeAnthropic.text("Made the screen longer."))])
    prov = provider_for("anthropic", fake)
    res1, _, conv, _ = ask(ws, prov, "add scoring code")
    assert res1.dry_run["ran"] is False and res1.review[0]["kind"] == "code"
    res2, _, conv, _ = ask(ws, prov, "make the screen longer", doc=res1.experiment, conv=conv)   # applied
    assert res2.changed and res2.dry_run["ran"] is False and "code" in res2.dry_run["skipped"]
    tool_result = json.loads(fake.chat_requests[4]["json"]["messages"][-1]["content"][0]["content"][0]["text"])
    assert "skipped" in tool_result                                     # the model's own dry_run is refused too
    assert [r["kind"] for r in res2.review] == ["code"]                 # still waiting for a person
    assert not (tmp_path / "ran.txt").exists() and not (ws / "stroop_ai/ran.txt").exists()
    fake.close()


def test_code_from_an_applied_earlier_result_is_remembered_in_the_history(ws):
    from edge.assistant.jobs import append_history
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": _code_ops()}, id="a")),
        FakeAnthropic.turn(FakeAnthropic.text("Added code.")),
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "update_routine", "rid": "scoring", "duration": 1.0}]}, id="b")),
        FakeAnthropic.turn(FakeAnthropic.text("Longer.")),
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "update_routine", "rid": "scoring", "duration": 1.5}]}, id="c")),
        FakeAnthropic.turn(FakeAnthropic.text("Longer still."))])
    prov = provider_for("anthropic", fake)
    res1, *_ = ask(ws, prov, "add scoring code")
    append_history(ws / "stroop_ai", "anthropic", "claude-opus-5-5", "add scoring code", res1.to_dict())
    res2, *_ = ask(ws, prov, "longer", doc=res1.experiment)          # a new conversation (e.g. the terminal)
    assert res2.dry_run["ran"] is False
    h = res1.review[0]["hash"]
    from edge.assistant.jobs import Conversation
    conv = Conversation(id="c2", provider="anthropic", model="claude-opus-5-5", base_url=prov.base_url,
                        experiment_path=EXP)
    req = AssistantRequest(experiment=copy.deepcopy(res2.experiment), path=EXP, message="longer still",
                           reviewed_code=[h])                       # a person has read it now
    res3 = execute(req, conv, prov, load_config(), ws, EventSink(), CancelEvent(), FileLedger(ws / "stroop_ai"),
                   normalized_base(res2.experiment, ws / EXP))
    assert res3.dry_run["ran"] is True and res3.review == []
    fake.close()


def test_the_test_run_never_reaches_the_network(ws):
    """A udp_messages device the model adds can't make the automatic test run send markers anywhere."""
    import socket
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    ops = json.loads(json.dumps(GOLDEN_OPS))
    ops[8]["conditions"] = [{"word": "RED", "ink": "red", "congruent": 1, "correct_key": "r"}]
    ops.append({"op": "add_device", "dtype": "udp_messages", "did": "sync",
                "options": {"send_markers_to": f"127.0.0.1:{port}", "port": 0}})
    ops.append({"op": "update_component", "rid": "trial", "cid": "word", "set_props": {"marker": "$f'{word}|{ink}'"}})
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": ops}, id="a")),
                          FakeAnthropic.turn(FakeAnthropic.text("Added a sync device."))])
    res, *_ = ask(ws, provider_for("anthropic", fake), "build it")
    assert res.dry_run["ran"] and res.dry_run["ok"], res.dry_run
    got = []
    try:
        while True:
            got.append(listener.recv(65536))
    except OSError:
        pass
    listener.close()
    assert got == []
    assert any(r["kind"] == "network" and f"127.0.0.1:{port}" in r["text"] for r in res.review)
    fake.close()


def _with_session(ws, folder="results"):
    d = copy.deepcopy(BLANK)
    d["settings"]["data"] = {"dir": folder}
    sess = ws / "stroop_ai" / folder / "P001_2026-10-01"
    sess.mkdir(parents=True)
    (sess / "trials.csv").write_text("participant,age,resp.rt\nP001,23,0.512\n")
    (sess / "session.json").write_text("{}")
    running = ws / "stroop_ai" / "elsewhere" / "P002"            # a session still running (no session.json yet)
    running.mkdir(parents=True)
    (running / "trials.csv").write_text("participant\nP002\n")
    (running / "trials.jsonl").write_text("{}\n")
    (ws / "stroop_ai/conditions").mkdir(exist_ok=True)
    (ws / "stroop_ai/conditions/words.csv").write_text("word\nRED\n")
    return d


def test_participant_data_in_a_custom_data_folder_is_never_seen_or_written(ws):
    from edge.assistant.agent import experiment_files
    from edge.assistant.attachments import data_roots
    d = _with_session(ws)
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("read_attachment", {"file": "results/P001_2026-10-01/trials.csv"}, id="r")),
        FakeAnthropic.turn(FakeAnthropic.tool("read_attachment", {"file": "elsewhere/P002/trials.csv"}, id="q")),
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
            {"op": "add_routine", "rid": "t", "add_to_flow": True, "duration": 1},
            {"op": "add_loop", "lid": "x", "children": ["t"], "conditions": [{"a": 1}], "wrap": True},
            {"op": "set_conditions", "lid": "x", "rows": [{"a": 1}], "file": "results/planted.csv",
             "write_file": True}]}, id="w")),
        FakeAnthropic.turn(FakeAnthropic.text("I can't read participant data."))])
    res, *_ = ask(ws, provider_for("anthropic", fake), "summarise the results", doc=d)
    first = json.dumps(fake.chat_requests[0]["json"]["messages"][0])
    assert "conditions/words.csv" in first and "P001" not in first and "P002" not in first
    for k in (1, 2):
        out = fake.chat_requests[k]["json"]["messages"][-1]["content"][0]["content"][0]["text"]
        assert "data or hidden folder" in out and "0.512" not in out
    wrote = fake.chat_requests[3]["json"]["messages"][-1]["content"][0]["content"][0]["text"]
    assert "data/" in wrote and "session" in wrote, wrote
    assert not (ws / "stroop_ai/results/planted.csv").exists()
    folder = ws / "stroop_ai"
    assert experiment_files(folder, roots=data_roots(folder, docs=[d])) == ["conditions/words.csv"]
    ledger = FileLedger(folder)
    ledger.data_roots = lambda: data_roots(folder, docs=[d])
    from edge.editing import EditError
    with pytest.raises(EditError, match="data"):
        ledger.write(folder / "results/new.csv", "a\n1\n")
    fake.close()


def test_the_state_block_says_whether_the_document_is_saved(ws):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("ok"))] * 3)
    prov = provider_for("anthropic", fake)
    ask(ws, prov, "hi")                                           # BLANK is what the file holds
    assert "Experiment file: stroop_ai/stroop_ai.yaml\n" in _first_text(fake.chat_requests[0])
    d = copy.deepcopy(BLANK)
    d["description"] = "edited, not saved"
    ask(ws, prov, "hi", doc=d)
    assert "stroop_ai.yaml (not saved since the last change)" in _first_text(fake.chat_requests[1])
    ask(ws, prov, "hi", path="new_one/new_one.yaml")
    assert "new_one/new_one.yaml (not saved yet)" in _first_text(fake.chat_requests[2])
    fake.close()


def _first_text(req):
    return req["json"]["messages"][0]["content"][-1]["text"]


def test_an_empty_claude_answer_is_not_kept_and_the_model_is_asked_to_continue(ws):
    """Claude sometimes ends with no content right after tool results. An empty assistant message in the history
    makes every later request a 400 (the strict fake enforces it): it is never stored."""
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.tool("validate", {}, id="v")),
        FakeAnthropic.turn(),                                              # empty end_turn
        FakeAnthropic.turn(FakeAnthropic.text("Checked: no problems.")),
        FakeAnthropic.turn(FakeAnthropic.text("Still fine."))])
    prov = provider_for("anthropic", fake)
    res, sink, conv, _ = ask(ws, prov, "check it")
    assert res.summary["message"] == "Checked: no problems." and res.status == "done"
    assert all(m["content"] for m in conv.transcript.native)
    nudge = fake.chat_requests[2]["json"]["messages"][-1]["content"][0]["text"]
    assert "Your last answer was empty" in nudge
    res2, *_ = ask(ws, prov, "and now?", conv=conv)                       # the conversation still works
    assert res2.summary["message"] == "Still fine." and not fake.rejected
    fake.close()


@pytest.mark.parametrize("kind", ["anthropic", "openai"])
def test_an_answer_cut_off_by_the_output_limit_is_incomplete(ws, kind):
    if kind == "anthropic":
        fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("This experiment measures"), stop="max_tokens")])
    else:
        fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("This experiment measures"), finish="length")])
    res, sink, _, _ = ask(ws, provider_for(kind, fake), "explain it")
    assert res.status == "incomplete"
    assert any("cut off by the model's output limit" in e["text"] for e in sink.events if e["kind"] == "warning")
    fake.close()


def test_json_mode_tool_results_are_trimmed_like_native_ones():
    from edge.assistant.providers.base import TRIMMED
    p = OllamaProvider({"model": "m", "num_ctx": 4096})
    tr = p.new_transcript("s", [])
    for i in range(6):
        p.add_user(tr, json.dumps({"tool_result": {"name": "read_attachment", "rows": "x" * 3000}}), [])
        tr.mark_tool_result()
        tr.native.append({"role": "assistant", "content": '{"say": "", "tool": {}}'})
    fork = tr.fork()
    p.trim_context(fork, 4096, lambda e: None)
    contents = [m["content"] for m in fork.native if m["role"] == "user"]
    assert contents[0] == TRIMMED and contents[-1] != TRIMMED and contents[-2] != TRIMMED
    assert all(m["content"] != TRIMMED for m in tr.native)              # the conversation's copy is untouched


def test_json_mode_keeps_working_in_a_small_context(ws):
    """Eight reads in JSON mode with a 16k context: older results are trimmed instead of failing."""
    big = "word,ink\n" + "\n".join(f"W{i}{'x' * 60},red" for i in range(400)) + "\n"
    (ws / "stroop_ai/conditions").mkdir()
    (ws / "stroop_ai/conditions/big.csv").write_text(big)
    env = lambda **k: FakeOllama.turn(FakeOllama.text(json.dumps(k)))
    turns = [env(say="", tool={"name": "read_attachment", "input": {"file": "conditions/big.csv", "start_row": i * 50,
                                                                     "rows": 50}}) for i in range(8)]
    fake = FakeOllama(turns + [env(say="Read it all.", done=True)],
                      models={"gemma2:9b": {"tools": False, "context": 16384, "size": "9B"}})
    fake.model_name = "gemma2:9b"
    res, sink, conv, _ = ask(ws, provider_for("ollama", fake), "read the list", dry=False)
    assert res.status == "done" and conv.tool_mode == "json"
    assert any("older tool result" in e["text"] for e in sink.events if e["kind"] == "warning")
    fake.close()
