"""``edge assistant``: settings from the command line (keys from standard input only), models, connection test
and ``ask`` against a fake Claude, saving with a backup."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from assistant_fakes import FINAL_TEXT, GOLDEN_OPS, FakeAnthropic, FakeOllama, closed_port
from edge.assistant import http as H
from edge.assistant.providers import anthropic as A
from edge.cli import main

FIX = Path(__file__).parent / "fixtures" / "assistant"
KEY = "sk-ant-cli-test-key-0000000000000000-CL1K"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(H, "RETRY_BASE", 0.01)
    monkeypatch.setattr(A, "DISABLED_FEATURES", set())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def stdin(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_config_and_key_from_stdin(tmp_path, monkeypatch, capsys):
    fake = FakeOllama([])
    assert main(["assistant", "config", "--provider", "ollama", "--base-url", fake.url, "--model", "qwen2.5:14b"]) == 0
    out = capsys.readouterr().out
    assert "Saved" in out and fake.url in out
    stdin(monkeypatch, KEY + "\n")
    assert main(["assistant", "config", "--provider", "anthropic", "--set-key"]) == 0
    out = capsys.readouterr().out
    assert KEY not in out and "…CL1K" in out
    p = tmp_path / "cfg" / "assistant.json"
    assert json.loads(p.read_text())["anthropic"]["api_key"] == KEY
    if os.name == "posix":
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert main(["assistant", "config", "--provider", "anthropic", "--clear-key"]) == 0
    assert json.loads(p.read_text())["anthropic"]["api_key"] is None
    assert main(["assistant", "config", "--provider", "ollama", "--set-key"]) == 2              # no keys for local
    assert main(["assistant", "config", "--provider", "ollama", "--num-ctx", "5"]) == 2         # validated
    assert "context size" in capsys.readouterr().err
    fake.close()


def test_models_and_test_exit_codes(capsys):
    fake = FakeOllama([])
    main(["assistant", "config", "--provider", "ollama", "--base-url", fake.url, "--model", "qwen2.5:14b"])
    capsys.readouterr()
    assert main(["assistant", "models"]) == 0
    out = capsys.readouterr().out
    assert "qwen2.5:14b" in out and "recommended" in out
    assert main(["assistant", "models", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "qwen2.5:14b"
    assert main(["assistant", "test"]) == 0
    assert "Connected to Ollama 0.12.3" in capsys.readouterr().out
    main(["assistant", "config", "--base-url", f"http://127.0.0.1:{closed_port()}"])
    capsys.readouterr()
    assert main(["assistant", "test"]) == 2
    assert "ollama serve" in capsys.readouterr().err
    fake.close()


def claude_script():
    return [FakeAnthropic.turn(FakeAnthropic.text("I'll build it."), FakeAnthropic.tool("read_attachment", {
        "file": "conditions/words.csv"}, id="1")),
        FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": GOLDEN_OPS}, id="2")),
        FakeAnthropic.turn(FakeAnthropic.tool("validate", {}, id="3")),
        FakeAnthropic.turn(FakeAnthropic.text(FINAL_TEXT))]


def setup_claude(monkeypatch, fake):
    main(["assistant", "config", "--provider", "anthropic", "--base-url", fake.url, "--model", "claude-opus-5-5"])
    stdin(monkeypatch, KEY)
    main(["assistant", "config", "--set-key"])


def test_ask_saves_with_a_backup(tmp_path, monkeypatch, capsys):
    fake = FakeAnthropic(claude_script())
    setup_claude(monkeypatch, fake)
    exp = tmp_path / "stroop_ai" / "stroop_ai.yaml"
    stdin(monkeypatch, "")
    assert main(["assistant", "ask", str(exp), "Build a Stroop task from this list, 2 repeats", "--new",
                 "--attach", str(FIX / "words.csv")]) == 2                    # no consent yet, not interactive
    assert "--yes" in capsys.readouterr().err
    assert not exp.exists() and not exp.parent.exists()      # refused before --new made anything
    code = main(["assistant", "ask", str(exp), "Build a Stroop task from this list, 2 repeats", "--new",
                 "--attach", str(FIX / "words.csv"), "--yes"])                 # the same command, agreeing
    cap = capsys.readouterr()
    assert code == 0, cap.err
    assert FINAL_TEXT in cap.out and "Added screen “trial”" in cap.out and "Test run: 18 trials" in cap.out
    assert "Reading words.csv" in cap.err and KEY not in cap.out + cap.err
    from edge.storage import list_backups, load_document
    doc = load_document(exp).doc
    assert set(doc["routines"]) == {"instructions", "trial", "thanks"}
    assert (exp.parent / "conditions/words.csv").exists()
    assert any(b["label"].startswith("assistant") for b in list_backups(exp))
    assert main(["backups", str(exp)]) == 0 and "assistant" in capsys.readouterr().out
    hist = (exp.parent / ".edge/assistant/history.jsonl").read_text()
    assert "Build a Stroop task" in hist
    fake.close()


def test_ask_no_save_json_and_exit_3_when_errors_remain(tmp_path, monkeypatch, capsys):
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
        {"op": "add_routine", "rid": "x", "add_to_flow": True, "duration": 1},
        {"op": "add_component", "rid": "x", "ctype": "text", "properties": {"text": "$nothing"}}]}, id="1")),
        FakeAnthropic.turn(FakeAnthropic.text("Added x.")),
        FakeAnthropic.turn(FakeAnthropic.text("I couldn't fix it.")),
        FakeAnthropic.turn(FakeAnthropic.text("Still not."))])
    setup_claude(monkeypatch, fake)
    exp = tmp_path / "e" / "e.yaml"
    main(["new", "blank", str(tmp_path / "e")])
    created = next((tmp_path / "e").glob("*.yaml"))
    capsys.readouterr()
    before = created.read_text()
    code = main(["assistant", "ask", str(created), "add x", "--no-save", "--json", "--yes"])
    out = capsys.readouterr().out
    res = json.loads(out)
    assert code == 3 and res["valid"] is False and res["changed"] and created.read_text() == before
    fake.close()


def test_ask_without_setup_says_how(tmp_path, capsys):
    exp = tmp_path / "x.yaml"
    main(["new", "blank", str(tmp_path)])
    created = next(tmp_path.glob("*.yaml"))
    assert main(["assistant", "ask", str(created), "hello"]) == 2
    assert "isn't set up" in capsys.readouterr().err


def test_ask_new_refused_leaves_nothing_and_code_needs_code_read(tmp_path, monkeypatch, capsys):
    """--new refused before consent leaves no half-made file; assistant code isn't test-run in a later `ask` until
    --code-read says a person has read it."""
    code_ops = [{"op": "add_routine", "rid": "scoring", "add_to_flow": True, "duration": 0.5},
                {"op": "add_component", "rid": "scoring", "ctype": "code", "cid": "c",
                 "properties": {"on_begin": "score = 0"}}]
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": code_ops}, id="a")),
                          FakeAnthropic.turn(FakeAnthropic.text("Added code.")),
                          FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
                              {"op": "update_routine", "rid": "scoring", "duration": 1}]}, id="b")),
                          FakeAnthropic.turn(FakeAnthropic.text("Longer.")),
                          FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
                              {"op": "update_routine", "rid": "scoring", "duration": 2}]}, id="c")),
                          FakeAnthropic.turn(FakeAnthropic.text("Longer still."))])
    setup_claude(monkeypatch, fake)
    exp = tmp_path / "code_ai" / "code_ai.yaml"
    stdin(monkeypatch, "")
    assert main(["assistant", "ask", str(exp), "score it", "--new"]) == 2 and not exp.exists()
    capsys.readouterr()
    assert main(["assistant", "ask", str(exp), "score it", "--new", "--yes", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["dry_run"]["ran"] is False and first["review"][0]["kind"] == "code"
    assert main(["assistant", "ask", str(exp), "longer", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["dry_run"]["ran"] is False                      # remembered through history.jsonl
    assert main(["assistant", "ask", str(exp), "longer still", "--json", "--code-read"]) == 0
    third = json.loads(capsys.readouterr().out)
    assert third["dry_run"]["ran"] is True and third["review"] == []
    fake.close()
