"""PsyToolkit importer: scripts and account zips, screens and timing, tables, responses, if/fi, feedback, notes with
line numbers, and its place in the CLI, the builder and MCP. Fixtures are original scripts written for these tests
(tests/fixtures/psytoolkit; pictures drawn by tests/fixtures/draw_fixture_pictures.py)."""
import shutil
import statistics
import zipfile
from pathlib import Path

import pytest

from edge.builder.server import BuilderApp, import_candidates
from edge.cli import main
from edge.importers import ImportError_, detect, import_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant
from tests.conftest import run_headless

FIX = Path(__file__).parent / "fixtures" / "psytoolkit"


def imported(src, tmp_path, errors=(), **kw):
    path, res = import_experiment(src, tmp_path / "out", **kw)
    exp = Experiment.load(path)
    issues = exp.validate()
    assert [i.message for i in issues if i.level == "error"] == list(errors)
    return path, res, exp.to_dict()


def run(path, seed=3):
    exp = Experiment.load(path)
    _, session, _ = run_headless(exp.source, path.parent, vp=VirtualParticipant(seed=seed))
    return session


def notes(res, level):
    return {n["where"]: n["message"] for n in res.notes if n["level"] == level}


def test_detect(tmp_path):
    assert detect(FIX / "stroop.psy") == "psytoolkit"
    assert detect(FIX / "simon_task.zip") == "psytoolkit"
    txt = tmp_path / "experiment.txt"
    txt.write_text((FIX / "stroop.psy").read_text())
    assert detect(txt) == "psytoolkit"
    (tmp_path / "notes.txt").write_text("task list for tomorrow\nblock the afternoon\n")
    with pytest.raises(ImportError_, match="unrecognized"):
        detect(tmp_path / "notes.txt")
    with zipfile.ZipFile(tmp_path / "photos.zip", "w") as z:
        z.writestr("a.png", b"not really")
    with pytest.raises(ImportError_, match="unrecognized"):
        detect(tmp_path / "photos.zip")


def test_stroop_script(tmp_path):
    path, res, doc = imported(FIX / "stroop.psy", tmp_path)
    assert res.platform == "PsyToolkit" and doc["name"] == "stroop"
    win = doc["settings"]["window"]
    assert (win["size"], win["background"], win["units"], win["fullscreen"]) == ([1024, 768], "#000000", "px", True)
    for f in ("fixpoint", "right", "wrong", "instruction"):
        assert (path.parent / "stroop_pictures" / f"{f}.png").is_file()
    trial = {c["id"]: c for c in doc["routines"]["colourword"]["components"]}
    assert trial["fixpoint"]["duration"] == 0.4 and "start" not in trial["fixpoint"]
    assert trial["text"]["start"] == 0.5 and trial["text"]["text"] == "$col2"
    assert trial["text"]["color"] == "$[col3, col4, col5]" and trial["text"]["height"] == 32
    assert trial["resp"]["keys"] == ["r", "g"] and trial["resp"]["correct"] == "$['r', 'g'][int(col6) - 1]"
    assert trial["resp"]["start"] == 0.5 and trial["resp"]["duration"] == 2.0 and trial["resp"]["end_routine"]
    assert "duration" not in doc["routines"]["colourword"]            # the answer ends the screen
    after = doc["routines"]["colourword_2"]
    fb = {c["id"]: c for c in after["components"]}
    assert after["duration"] == 0.6                                   # delay 600 after fi keeps the feedback up
    assert fb["right"]["if"] == "$STATUS == 1" and fb["wrong"]["if"] == "$STATUS != 1"
    assert fb["wrong"]["pos"] == [0, 100]                             # PsyToolkit's y grows downwards
    assert fb["set_hits"]["set"] == {"hits": "$(hits + 1) if (STATUS == 1) else hits"}
    loops = [n for n in doc["flow"] if isinstance(n, dict)]
    assert [n["loop"] for n in loops] == ["practice_colourword", "test_colourword"]
    assert loops[0]["children"] == ["colourword", "colourword_2"] and len(loops[0]["conditions"]) == 4
    assert loops[0]["conditions"][1] == {"col1": "red in green", "col2": "RED", "col3": 0, "col4": 200, "col5": 0,
                                         "col6": 2, "col7": 0}
    assert loops[0]["repeats"] == 2 and loops[0]["stop_if"] == "$practice_colourword.n >= 5"     # 6 trials
    assert loops[1]["repeats"] == 2 and "stop_if" not in loops[1]                               # 8 trials
    assert doc["flow"][0] == "practice_message" and doc["flow"][-1] == "test_feedback"
    assert {m["column"] for m in doc["measures"]} == {"resp.rt", "resp.corr"}
    assert "line 51" in notes(res, "approx") and "at random" in notes(res, "approx")["line 51"]


def test_stroop_runs_and_feedback_is_computed(tmp_path):
    path, res, doc = imported(FIX / "stroop.psy", tmp_path)
    session = run(path)
    rows = [r for r in session.data.trial_rows if r.get("loop") in ("practice_colourword", "test_colourword")
            and r.get("resp.rt") is not None or r.get("STATUS") == 3 and r.get("col1")]
    practice = [r for r in session.data.trial_rows if r.get("loop") == "practice_colourword" and "resp.corr" in r]
    test = [r for r in session.data.trial_rows if r.get("loop") == "test_colourword" and "resp.corr" in r]
    assert len(practice) == 6 and len(test) == 8 and rows
    for r in practice + test:
        key = ["r", "g"][r["col6"] - 1]
        assert r["resp.corr"] == (1 if r["resp.keys"] == key else 0)
        assert r["STATUS"] == (1 if r["resp.corr"] else (3 if not r["resp.keys"] else 2))
    ok = [r["RT"] for r in practice if r["STATUS"] == 1]
    assert session.vars["meanrt"] == (round(statistics.mean(ok)) if ok else 0)
    assert session.vars["errs"] == sum(1 for r in practice if r["STATUS"] != 1)
    mixed = [r["RT"] for r in test if r["STATUS"] == 1 and r["col7"] == 0]
    assert session.vars["med"] == (round(statistics.median(mixed)) if mixed else 0)
    assert session.vars["hits"] == sum(1 for r in practice + test if r["STATUS"] == 1)


def test_simon_zip(tmp_path):
    path, res, doc = imported(FIX / "simon_task.zip", tmp_path)
    assert path.name == "simon_task.yaml"
    for f in ("fix.png", "red_square.png", "green_square.png", "oops.png"):
        assert (path.parent / f).is_file()                            # copied out of the zip
    assert doc["settings"]["window"]["background"] == "#282828"
    first = {c["id"]: c for c in doc["routines"]["simon"]["components"]}
    assert first["fix"]["duration"] == 0.3                            # from part fixation
    assert first["set_wait"]["set"] == {"wait": "$random.randint(200, 400)"}
    assert first["picture"]["start"] == "$((wait) + 300) / 1000"      # delay $wait after the fixation
    assert first["picture"]["pos"] == "$[col3, 0]" and "red_square.png" in first["picture"]["image"]
    assert first["resp"]["correct"] == "$['a', 'l'][int(col4) - 1]" and first["resp"]["duration"] == 1.5
    assert first["trial_count"]["set"] == {"TRIALCOUNT": "$TRIALCOUNT + 1"}
    loop = next(n for n in doc["flow"] if isinstance(n, dict))
    kids = loop["children"]
    assert kids[0] == "simon" and kids[1] == {"if": "$STATUS == 2", "then": ["simon_wrong"]}
    assert kids[2] == {"if": "$STATUS == 3", "then": ["simon_timeout"]}
    wrong = {c["id"]: c for c in doc["routines"]["simon_wrong"]["components"]}
    assert doc["routines"]["simon_wrong"]["duration"] == 0.5 and wrong["oops"]["duration"] == 0.5
    click = {c["id"]: c for c in doc["routines"][kids[3]]["components"]}["click"]
    assert click["correct"] == "circle" and click["clickable"] == ["circle"] and click["start"] == 0.2
    assert loop["repeats"] == 3 and "stop_if" not in loop            # 12 trials of 4 rows
    assert doc["flow"][0] == "message" and doc["flow"][1] == "main_start"
    assert "while" in notes(res, "unsupported")["line 49"]           # with its line number
    session = run(path, seed=5)
    assert sum(1 for r in session.data.trial_rows if r.get("loop") == loop["loop"] and "resp.corr" in r) == 12
    assert session.vars["TRIALCOUNT"] == 12


def test_script_with_its_pictures_folder_and_include(tmp_path):
    src = tmp_path / "src"
    (src / "pics").mkdir(parents=True)
    shutil.copy(FIX / "stroop_pictures" / "fixpoint.png", src / "pics" / "Dot.PNG")
    (src / "extra.txt").write_text("table words\n  \"cat\" 1\n  \"dog\" 2\n")
    (src / "code.psy").write_text(
        "options\n  bitmapdir pics\n  sounddir snd\n  window spooky\n\n"
        "bitmaps\n  dot\n\nsounds\n  ping ping.wav\n\ninclude extra.txt\n\n"
        "task t\n  table words\n  keys space\n  show bitmap dot -100 50\n  sound ping\n  delay &gap\n  clear 1\n"
        "  show text @1\n  readkey 1 &limit\n  readkeys \"x\" 5000\n  frobnicate now\n  if &x > 1\n  delay 10\n  else\n"
        "  show rectangle 0 0 20 30 255 0 0\n  delay 20\n  fi\n\n"
        "block b\n  tasks t 3\n  maxtrials 2\n  feedback\n    xyplot c1 c2\n    set &q mean c9\n  end\n")
    path, res, doc = imported(src / "code.psy", tmp_path, errors=["sound file not found: snd/ping.wav"])
    assert path.name == "src.yaml"                                    # code.psy is named after its folder
    assert (path.parent / "pics" / "Dot.PNG").is_file()               # found whatever the case of its name
    t = {c["id"]: c for c in doc["routines"]["t"]["components"]}
    assert t["dot"]["pos"] == [-100, -50] and t["dot"]["duration"] == "$((gap)) / 1000"
    assert t["text"]["start"] == "$((gap)) / 1000" and t["resp"]["keys"] == ["space"]
    assert t["resp"]["duration"] == "$(limit) / 1000" and t["resp"]["correct"] == "space"
    assert doc["variables"]["gap"] == 0 and doc["variables"]["limit"] == 0
    loop = next(n for n in doc["flow"] if isinstance(n, dict))
    assert [r["col1"] for r in loop["conditions"]] == ["cat", "dog"]       # the included table
    assert loop["stop_if"].endswith(".n >= 1")                              # maxtrials 2
    branch = next(n for n in loop["children"] if isinstance(n, dict))
    assert branch["if"] == "$x > 1" and branch["then"] and branch["else"]
    unsupported = notes(res, "unsupported")
    assert "window spooky" in unsupported["line 4"]
    assert "readkeys" in unsupported["line 23"] and "frobnicate" in unsupported["line 24"]
    assert any("xyplot" in m for m in unsupported.values())
    assert any("c9 is not one of the" in m or "saves nothing" in m for m in unsupported.values())
    assert any("ping.wav" in m for m in notes(res, "approx").values())    # a sound that is not there


def test_damaged_and_empty_sources(tmp_path):
    bad = tmp_path / "broken.zip"
    bad.write_bytes((FIX / "simon_task.zip").read_bytes()[:300])
    with pytest.raises(ImportError_):
        import_experiment(bad, tmp_path / "o1", platform="psytoolkit")
    with zipfile.ZipFile(tmp_path / "noscript.zip", "w") as z:
        z.writestr("readme.md", "hello")
    with pytest.raises(ImportError_, match="holds no PsyToolkit script"):
        import_experiment(tmp_path / "noscript.zip", tmp_path / "o2", platform="psytoolkit")
    (tmp_path / "only_options.psy").write_text("options\n  fullscreen\n")
    with pytest.raises(ImportError_, match="nothing could be converted from only_options.psy"):
        import_experiment(tmp_path / "only_options.psy", tmp_path / "o3")
    assert not (tmp_path / "o3").exists()
    # a zip whose files try to leave the folder: they are skipped
    with zipfile.ZipFile(tmp_path / "evil.zip", "w") as z:
        z.writestr("exp/code.psy", (FIX / "stroop.psy").read_text().replace("bitmapdir stroop_pictures", ""))
        z.writestr("../../escape.png", b"x")
        for f in ("fixpoint", "right", "wrong", "instruction"):
            z.write(FIX / "stroop_pictures" / f"{f}.png", f"exp/{f}.png")
    path, res, doc = imported(tmp_path / "evil.zip", tmp_path)
    assert not (tmp_path / "escape.png").exists() and not list(tmp_path.parent.glob("escape.png"))
    assert (path.parent / "fixpoint.png").is_file()


def test_cli_builder_and_mcp(tmp_path, capsys):
    assert main(["import", str(FIX / "simon_task.zip"), "--out", str(tmp_path / "cli")]) == 0
    assert "imported PsyToolkit experiment" in capsys.readouterr().out
    assert main(["import", str(FIX / "stroop.psy"), "--platform", "psytoolkit", "--out", str(tmp_path / "cli2")]) == 0
    # the builder's Import: the zip uploaded as it is, or the script with its pictures folder
    root = tmp_path / "ws"
    up = root / "imports/simon_task/source"
    up.mkdir(parents=True)
    shutil.copy(FIX / "simon_task.zip", up)
    assert [f.name for f in import_candidates(up)] == ["simon_task.zip"]
    app = BuilderApp(root)
    r = app.import_source("imports/simon_task/source", "imports/simon_task", main="simon_task.zip")
    assert r["platform"] == "PsyToolkit" and r["path"] == "imports/simon_task/simon_task.yaml"
    up2 = root / "imports/stroop/source"
    shutil.copytree(FIX, up2, ignore=shutil.ignore_patterns("*.zip", "simon_code.psy"))
    r = app.import_source("imports/stroop/source", "imports/stroop", main="stroop.psy")
    assert r["platform"] == "PsyToolkit" and (root / "imports/stroop/stroop_pictures/right.png").is_file()
    from edge.builder import server
    exts = server.schema()["import_extensions"]
    assert ".psy" in exts and ".zip" in exts
    app_js = (Path(server.__file__).parent / "static/app.js").read_text()
    assert '".psy", ".zip"' in app_js and "PsyToolkit (the .zip from your PsyToolkit account" in app_js
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    from tests.test_mcp import call
    shutil.copy(FIX / "simon_task.zip", tmp_path / "simon_task.zip")
    r = call(create_server(tmp_path), "import_experiment", source="simon_task.zip", out_dir="simon_edge")
    assert r["ok"] and r["platform"] == "PsyToolkit" and r["path"] == "simon_edge/simon_task.yaml"
    assert any("while" in m for m in r["needs_manual_work"])


def test_docs_describe_the_importer_and_its_limits():
    docs = (Path(__file__).parent.parent / "docs" / "IMPORT.md").read_text()
    section = docs.split("## PsyToolkit")[1]
    assert "free PsyToolkit account" in section and "non-commercial" in section and "readmouse" in section
