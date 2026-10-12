"""Regression tests for the usability fixes in the command line and the launcher (group A2)."""

from __future__ import annotations

import builtins
import csv
import json
import shlex
import shutil
from pathlib import Path

import pytest
import yaml

from edge import cli, launcher
from edge.cli import main

ROOT = Path(__file__).resolve().parent.parent
STROOP = ROOT / "examples" / "stroop"


def _copy_stroop(tmp_path: Path) -> Path:
    shutil.copytree(STROOP, tmp_path / "s", ignore=shutil.ignore_patterns("data", "exports", "*.lock.json",
                                                                         "*.preflight.json"))
    return tmp_path / "s" / "stroop.yaml"


def _dry_runs(p: Path, *ids: str) -> list[Path]:
    for pid in ids:
        assert main(["run", str(p), "--dry-run", "-p", pid]) == 0
    return sorted((p.parent / "data" / "dry_runs").iterdir())


def _timed(tmp_path: Path, conditions: bool = False) -> Path:
    """A short experiment that runs by itself (a real session needs no participant to answer)."""
    doc = {"name": "timed", "routines": {"trial": {"duration": 0.1, "components": [
        {"id": "t", "type": "text", "text": "$word" if conditions else "hello"}]}},
        "flow": [{"loop": "trials", "conditions": "words.csv", "children": ["trial"]}] if conditions else ["trial"]}
    if conditions:
        (tmp_path / "words.csv").write_text("word\nalpha\nbeta\n")
    p = tmp_path / "timed.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def _real_run(p: Path, *args: str) -> int:
    return main(["run", str(p), "--backend", "headless-realtime", *args])


def _answer(monkeypatch, reply: str) -> list[str]:
    """Pretend someone is at the terminal and types ``reply`` to every question."""
    asked: list[str] = []
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda q="": asked.append(q) or reply)
    return asked


# ------------------------------------------------------------------ cli#5 / data#6: --layout long and --name
def test_export_long_layout_for_a_data_folder_and_name_for_one_session(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    sessions = _dry_runs(p, "001", "002")
    data = p.parent / "data"
    assert main(["export", str(data), "--include-dry-runs", "--layout", "long", "--formats", "csv",
                 "--name", "study", "--out", str(tmp_path / "long")]) == 0
    assert main(["export", str(data), "--include-dry-runs", "--formats", "csv", "--name", "study",
                 "--out", str(tmp_path / "wide")]) == 0
    with open(tmp_path / "long" / "study_trials.csv", encoding="utf-8-sig") as f:
        long_rows = list(csv.DictReader(f))
    with open(tmp_path / "wide" / "study_trials.csv", encoding="utf-8-sig") as f:
        wide_rows = list(csv.DictReader(f))
    routine_runs = sum(len((s / "trials.jsonl").read_text().splitlines()) for s in sessions)
    assert len(long_rows) == routine_runs > len(wide_rows)               # one row per routine, not per trial
    assert {r["session_folder"] for r in long_rows} == {s.name for s in sessions}
    capsys.readouterr()
    assert main(["export", str(sessions[0]), "--formats", "csv", "--name", "pilot_a", "--out", str(tmp_path / "one")]) == 0
    assert (tmp_path / "one" / "pilot_a_trials.csv").exists()
    assert not list((tmp_path / "one").glob("001_*"))
    # the builder's Data tab exports a whole folder in the layout asked for, too
    from edge.builder.server import BuilderApp
    res = BuilderApp(tmp_path).export("s/data", ["csv"], "long", True)
    trials = next(tmp_path / f for f in res["files"] if f.endswith("_trials.csv"))
    with open(trials, encoding="utf-8-sig") as f:
        assert len(list(csv.DictReader(f))) == routine_runs


# ------------------------------------------------------------------ cli#6: a real run checks the lock
def test_a_real_run_says_when_the_experiment_changed_since_the_lock(tmp_path, capsys, monkeypatch):
    p = _timed(tmp_path, conditions=True)
    assert main(["lock", str(p)]) == 0
    (tmp_path / "words.csv").write_text("word\nALPHA\nbeta\ngamma\n")
    capsys.readouterr()
    # nobody at a terminal (the builder, a script): the warning is printed and kept with the session
    assert _real_run(p, "-p", "1") == 0
    out = capsys.readouterr().out
    assert "words.csv changed since the lock" in out and "edge verify" in out and "edge lock" in out
    meta = json.loads(next((tmp_path / "data").glob("1_1_*/session.json")).read_text())
    assert meta["lock"]["locked"] is True and meta["lock"]["matches"] is False
    assert any("words.csv" in f["what"] for f in meta["lock"]["findings"])
    # someone at the terminal is asked, and Enter (no) runs nothing
    asked = _answer(monkeypatch, "")
    assert _real_run(p, "-p", "2") == 2
    assert asked and "anyway" in asked[0] and not list((tmp_path / "data").glob("2_1_*"))
    assert "Nothing was run" in capsys.readouterr().out
    # once locked again it runs without a question, and the session records that it matched
    asked.clear()
    assert main(["lock", str(p)]) == 0 and _real_run(p, "-p", "3") == 0 and not asked
    meta = json.loads(next((tmp_path / "data").glob("3_1_*/session.json")).read_text())
    assert meta["lock"]["matches"] is True


def test_an_unlocked_experiment_runs_without_questions(tmp_path, monkeypatch):
    p = _timed(tmp_path)
    asked = _answer(monkeypatch, "n")
    assert _real_run(p, "-p", "7") == 0 and not asked
    meta = json.loads(next((tmp_path / "data").glob("7_1_*/session.json")).read_text())
    assert meta["lock"] == {"locked": False}


# ------------------------------------------------------------------ cli#7: participant ids
def test_a_real_run_names_the_participant_and_warns_before_reusing_one(tmp_path, capsys, monkeypatch):
    p = _timed(tmp_path)
    assert _real_run(p) == 0
    out = capsys.readouterr().out
    assert "Participant: 001 (the default" in out and "-p" in out
    assert _real_run(p) == 0                       # nobody to ask: a warning, and both sessions are kept
    out = capsys.readouterr().out
    assert "Participant 001, session 1 already has data" in out and "-s 2" in out and "-p 002" in out
    assert len(list((tmp_path / "data").glob("001_1_*"))) == 2
    asked = _answer(monkeypatch, "n")
    assert _real_run(p, "-p", "001") == 2 and asked
    assert len(list((tmp_path / "data").glob("001_1_*"))) == 2
    asked.clear()
    assert _real_run(p, "-p", "002") == 0 and not asked     # a new participant: no question
    # test runs never count as a participant's data
    assert main(["run", str(p), "--dry-run", "-p", "005"]) == 0
    asked.clear()
    assert _real_run(p, "-p", "005") == 0 and not asked


# ------------------------------------------------------------------ cli#8, docs#5, install#8: one-line messages
def test_common_mistakes_are_one_line_messages(tmp_path, capsys, monkeypatch):
    p = _copy_stroop(tmp_path)
    [session] = _dry_runs(p, "001")
    (tmp_path / "afile.txt").write_text("x")
    capsys.readouterr()

    def said(argv: list[str]) -> str:
        assert main(argv) == 2, argv
        err = capsys.readouterr().err
        assert "Traceback" not in err and err.count("\n") <= 2, err
        return err

    assert "is a file, not a folder" in said(["export", str(session), "--formats", "csv", "--out", str(tmp_path / "afile.txt")])
    assert "is a file, not a folder" in said(["new", "blank", str(tmp_path / "afile.txt")])
    assert "did you mean eyetracker" in said(["test-device", str(p), "eyetraker", "--simulate", "--seconds", "0.1"])
    assert "is a file, not a folder" in said(["start", str(tmp_path / "afile.txt"), "--no-browser"])
    # anything a command reports with a ValueError is shown as its message
    import edge.devtest

    def broken(*a, **k):
        raise ValueError("the device said no")
    monkeypatch.setattr(edge.devtest, "test_experiment_device", broken)
    assert said(["test-device", str(p), "eyetracker"]).strip() == "edge test-device: the device said no"


def test_lock_checks_the_experiment_first(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    (p.parent / "stroop.csv").unlink()
    assert main(["lock", str(p)]) == 2
    out = capsys.readouterr().out
    assert "stroop.csv" in out and "fix them before locking" in out
    assert not p.with_name("stroop.lock.json").exists()


# ------------------------------------------------------------------ cli#11, install#8: builder / start on a file
def test_builder_and_start_open_the_folder_of_an_experiment_file(tmp_path, capsys, monkeypatch):
    import edge.builder.server as server
    calls = []
    monkeypatch.setattr(server, "serve", lambda root, **kw: calls.append((Path(root), kw)))
    p = _copy_stroop(tmp_path)
    assert main(["builder", str(p), "--no-browser"]) == 0
    assert calls[-1][0] == p.parent and calls[-1][1]["path_query"] == "?open=stroop.yaml"
    assert main(["start", str(p), "--no-browser"]) == 0
    assert calls[-1][0] == p.parent and "?open=stroop.yaml" in calls[-1][1]["path_query"]
    assert "opening the folder it is in" in capsys.readouterr().out
    n = len(calls)
    assert main(["builder", str(tmp_path / "no_such_folder"), "--no-browser"]) == 2
    err = capsys.readouterr().err
    assert "there is no folder" in err and "edge start" in err
    assert len(calls) == n and not (tmp_path / "no_such_folder").exists()


# ------------------------------------------------------------------ cli#13: suggested commands can be pasted
def test_suggested_commands_quote_paths_with_spaces(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    folder = tmp_path / "my exp"
    assert main(["new", "blank", str(folder)]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "edge run" in x)
    args = shlex.split(line.split("try:", 1)[1])
    assert args[:2] == ["edge", "run"] and Path(args[2]).parent == folder and args[3] == "--dry-run"
    assert main(["timing-test", str(tmp_path / "my timing")]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "--dry-run" in x)
    assert shlex.split(line.split(":", 1)[1].strip(" )"))[2] == str(tmp_path / "my timing" / "timing_test.yaml")
    monkeypatch.setattr(cli.sys, "platform", "win32")
    assert cli.shlex_quote(r"C:\Users\Ana\EDGE Experiments\a.yaml") == '"C:\\Users\\Ana\\EDGE Experiments\\a.yaml"'


# ------------------------------------------------------------------ cli#19, docs#18: report on what people type
def test_report_accepts_a_data_folder_an_experiment_or_several_folders(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    sessions = _dry_runs(p, "001", "001")
    capsys.readouterr()
    for target in ([str(p.parent / "data")], [str(p)], [str(s) for s in sessions]):
        assert main(["report", *target]) == 0, target
        out = capsys.readouterr().out
        assert "2 sessions match; this is the newest" in out and sessions[-1].name in out
    assert main(["report", str(sessions[0])]) == 0
    assert "sessions match" not in capsys.readouterr().out
    assert main(["report", str(p.parent / "data" / "001_1_study_*")]) == 2
    assert "no folder matches" in capsys.readouterr().err
    assert main(["report", str(p.parent / "data"), "--json"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["session"] == sessions[-1].name and "sessions match" in out.err


def test_align_explains_its_result_and_refuses_several_sessions(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    s1, s2 = _dry_runs(p, "001", "002")
    ev = [json.loads(line) for line in (s1 / "events.jsonl").read_text().splitlines()]
    ext = tmp_path / "ext.csv"
    ext.write_text("time,code\n" + "".join(f"{e['time'] - 100:.5f},{e['code']}\n" for e in ev if e.get("code") is not None))
    capsys.readouterr()
    assert main(["align", str(s1), str(ext)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Matched ") and "alignment.json" in out and "{" not in out
    assert (s1 / "alignment.json").exists()
    assert main(["align", str(s1), str(ext), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] > 2
    assert main(["align", str(s1), str(s2), str(ext)]) == 2
    assert "give the one the external recording belongs to" in capsys.readouterr().err


# ------------------------------------------------------------------ cli#20, docs#23: backups
def test_backups_says_when_there_are_none(tmp_path, capsys):
    p = _copy_stroop(tmp_path)
    assert main(["backups", str(p)]) == 0
    assert "No backups yet" in capsys.readouterr().out
    assert main(["backups", str(tmp_path / "nope.yaml")]) == 2
    assert "file not found" in capsys.readouterr().err


# ------------------------------------------------------------------ cli#22: -f key=value
def test_participant_fields_need_key_value_and_are_trimmed(tmp_path, capsys):
    p = _timed(tmp_path)
    assert main(["run", str(p), "--dry-run", "-p", "F1", "-f", "age30"]) == 2
    assert "-f age30: use key=value, e.g. -f age=30" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()
    assert main(["run", str(p), "--dry-run", "-p", "F1", "-f", "hand = left", "-f", "age=30"]) == 0
    meta = json.loads(next((tmp_path / "data" / "dry_runs").glob("F1_*/session.json")).read_text())
    assert meta["participant"]["hand"] == "left" and meta["participant"]["age"] == "30"


# ------------------------------------------------------------------ cli#24: help and parse errors
def test_a_mistyped_option_is_explained_by_its_command(capsys):
    with pytest.raises(SystemExit) as e:
        main(["run", "x.yaml", "--dryrun"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "usage: edge run" in err and "did you mean --dry-run?" in err and "desktop-shortcut" not in err
    with pytest.raises(SystemExit):
        main(["report", "--jsn", "x"])
    assert "did you mean --json?" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["rnu", "x.yaml"])
    err = capsys.readouterr().err
    assert "there is no command 'rnu'; did you mean run?" in err and "desktop-shortcut" not in err
    with pytest.raises(SystemExit):
        main(["run", "my", "exp/study.yaml"])
    assert "in quotes" in capsys.readouterr().err


def test_every_argument_is_explained():
    from edge.help import build_cli_reference
    ref = build_cli_reference()
    empty = [line for line in ref.splitlines() if line.startswith("| `") and line.rstrip().endswith("|  |")]
    assert not empty, empty
    assert "~/Documents/EDGE Experiments" not in ref and "Documents folder" in ref
    assert "(default: csv,xlsx)" in ref and "pyglet (default)" in ref


def test_docs_alone_points_to_help_and_rebuilds_nothing(capsys, monkeypatch):
    from edge import help as hp
    monkeypatch.setattr(hp, "build_docs", lambda check=False: pytest.fail("edge docs alone must not rebuild"))
    assert main(["docs"]) == 0
    assert "edge help" in capsys.readouterr().out


def test_component_names_line_up(capsys):
    assert main(["components"]) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    starts = {len(x) - len(x[13:].split(" ", 1)[1].lstrip()) for x in lines}
    assert len(starts) == 1, "descriptions start in one column"


# ------------------------------------------------------------------ docs#23: scan and test-device output
def test_scan_prints_device_lines_not_python(capsys, monkeypatch):
    import edge.scan
    monkeypatch.setattr(edge.scan, "scan_all", lambda timeout=2.0: {
        "serial_ports": [{"port": "/dev/ttyUSB0", "description": "n/a", "vid_pid": "",
                          "suggested": {"type": "ttl_serial", "options": {"port": "/dev/ttyUSB0", "protocol": "byte"}}}],
        "tobii": []})
    assert main(["scan", "--timeout", "0"]) == 0
    out = capsys.readouterr().out
    assert "{'" not in out and "n/a" not in out
    assert "{id: triggers, type: ttl_serial, options: {port: /dev/ttyUSB0, protocol: byte}}" in out
    assert "(none)" in out


def test_test_device_asks_for_what_the_device_needs(tmp_path, capsys, monkeypatch):
    import edge.devtest
    p = _copy_stroop(tmp_path)
    monkeypatch.setattr(edge.devtest, "test_experiment_device",
                        lambda exp, did, seconds, simulate: {"connected": True, "messages": ["ok"]})
    assert main(["test-device", str(p), "eyetracker"]) == 0
    out = capsys.readouterr().out
    assert "look at the screen" in out and "speak" not in out and "buttons" not in out
    assert main(["test-device", str(p), "eeg"]) == 0
    assert "(" not in capsys.readouterr().out.splitlines()[0]


# ------------------------------------------------------------------ install#18, wizard#9, wizard#10: terminal wizard
def test_terminal_wizard_checks_each_answer_and_asks_again(tmp_path, capsys):
    replies = iter(["lexdec", "video", "words", "keys", "house, f, word", "", "", "half a second", "0.5", "",
                    "none", "maybe", "y", "until", "80%", "three", "3", "two", "2", "1", "bdi swls", "swls"])
    answers = launcher.ask_wizard(lambda q, d: next(replies))
    out = capsys.readouterr().out
    assert "Please type one of: word, picture, sound, shape" in out
    assert "please type a number of seconds" in out and "please answer y" in out
    assert "please type a whole number" in out and "no questionnaire called bdi" in out
    assert answers["stimulus"]["kind"] == "word" and answers["practice"] == {"mode": "until", "criterion": 0.8,
                                                                             "max_rounds": 3}
    assert answers["blocks"] == {"count": 2, "repeats": 1} and answers["questionnaires"] == ["swls"]
    path, _ = launcher.write_wizard_experiment(answers, tmp_path)
    doc = yaml.safe_load(path.read_text())
    resp = next(c for c in doc["routines"]["trial"]["components"] if c["id"] == "response")
    assert "duration" not in resp, "'none' means wait for the answer"


def test_terminal_wizard_deadline_default_and_cancel(tmp_path, capsys, monkeypatch):
    questions = []
    launcher.ask_wizard(lambda q, d: questions.append((q, d)) or "")
    deadline = next((q, d) for q, d in questions if "deadline" in q.lower())
    assert deadline[1] == "2" and "none = wait for the answer" in deadline[0]
    lines = iter(["test5"])

    def eof(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None
    monkeypatch.setattr(builtins, "input", eof)
    assert main(["wizard", str(tmp_path / "w")]) == 1
    assert "Cancelled: nothing was created" in capsys.readouterr().out
    assert not (tmp_path / "w").exists()


# ------------------------------------------------------------------ install#19, install#22: shortcut and workspace
def test_shortcut_workspace_is_made_absolute(tmp_path, capsys, monkeypatch):
    got = {}
    monkeypatch.setattr(launcher, "desktop_shortcut", lambda workspace=None, **kw: got.setdefault("ws", workspace) and [])
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lab").mkdir()
    main(["desktop-shortcut", "--workspace", "lab"])
    assert got["ws"] == tmp_path / "lab" and got["ws"].is_absolute()
    assert str(tmp_path / "lab") in capsys.readouterr().out


def test_default_workspace_is_in_the_real_documents_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("EDGE_HOME", raising=False)
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / "Dokumente").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Dokumente"\n')
    assert launcher.default_workspace("linux", home) == home / "Dokumente" / "EDGE Experiments"
    assert launcher.default_workspace("darwin", home) == home / "EDGE Experiments"      # no ~/Documents there
    (home / "Documents").mkdir()
    assert launcher.default_workspace("darwin", home) == home / "Documents" / "EDGE Experiments"
    # experiments an earlier EDGE put in ~/EDGE Experiments are not left behind
    (home / "EDGE Experiments").mkdir()
    assert launcher.default_workspace("linux", home) == home / "EDGE Experiments"
    (home / "Dokumente" / "EDGE Experiments").mkdir()
    assert launcher.default_workspace("linux", home) == home / "Dokumente" / "EDGE Experiments"
