import json
from pathlib import Path

import pytest

from edge.importers import ImportError_, detect, import_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant
from tests.conftest import run_headless

FIX = Path(__file__).parent / "fixtures"


def load(path):
    return Experiment.load(path)


def dry(path, tmp_path):
    exp = load(path)
    summary, session, _ = run_headless(exp.source, path.parent, vp=VirtualParticipant(seed=1))
    return summary, session


def test_detect():
    assert detect(FIX / "psychopy/stroop.psyexp") == "psychopy"
    assert detect(FIX / "eprime/Stroop.ebs3") == "eprime"
    assert detect(FIX / "opensesame/flanker.opensesame") == "opensesame"
    assert detect(FIX / "jspsych/experiment.html") == "jspsych"
    with pytest.raises(ImportError_, match="Generate"):
        detect(Path("thing.es3"))


def test_psychopy(tmp_path):
    path, res = import_experiment(FIX / "psychopy/stroop.psyexp", tmp_path)
    d = load(path).to_dict()
    assert d["settings"]["window"]["units"] == "height" and d["settings"]["window"]["background"] == "#000000"
    trial = {c["id"]: c for c in d["routines"]["trial"]["components"]}
    assert trial["word"]["text"] == "$text" and trial["word"]["start"] == 0.5 and trial["word"]["height"] == 0.15
    assert trial["fixation"]["shape"] == "cross" and trial["fixation"]["duration"] == 0.5
    assert trial["resp"]["keys"] == ["left", "down", "right"] and trial["resp"]["correct"] == "$corrAns"
    assert trial["resp"]["duration"] == 2 and trial["resp"]["end_routine"] is True
    assert trial["trigger"]["type"] == "marker" and trial["trigger"]["code"] == 1
    loop = next(n for n in d["flow"] if isinstance(n, dict) and "loop" in n)
    assert loop["conditions"] == "trialTypes.csv" and loop["repeats"] == 2 and loop["order"] == "random"
    assert loop["children"] == ["trial", "feedback"]
    assert d["flow"][0] == "setup_code"                      # Begin Experiment code runs first
    fb = {c["id"]: c for c in d["routines"]["feedback"]["components"]}
    assert "if resp.corr" in fb["fbCode"]["on_begin"] and "clip" not in fb
    assert (tmp_path / "trialTypes.csv").exists()
    assert any(n["level"] == "unsupported" and "Movie" in n["message"] for n in res.notes)
    assert (tmp_path / "IMPORT_REPORT.md").read_text().startswith("# Import report")
    summary, session = dry(path, tmp_path)
    rows = session.data.trial_rows
    assert sum(r["routine"] == "trial" for r in rows) == 12
    fb_texts = [r for r in rows if r["routine"] == "feedback"]
    assert len(fb_texts) == 12


def test_eprime(tmp_path):
    path, res = import_experiment(FIX / "eprime/Stroop.ebs3", tmp_path)
    d = load(path).to_dict()
    assert list(d["routines"]) == ["Instructions", "Fixation", "Stimulus", "Feedback", "Goodbye"]
    stim = {c["id"]: c for c in d["routines"]["Stimulus"]["components"]}
    assert stim["text"]["text"] == "$Word" and stim["text"]["color"] == "$InkColor"
    assert stim["resp"]["keys"] == ["r", "g", "b"] and stim["resp"]["correct"] == "$CorrectAnswer"
    assert stim["resp"]["duration"] == 2.0 and stim["resp"]["end_routine"]
    assert d["routines"]["Fixation"]["duration"] == 0.5
    instr = {c["id"]: c for c in d["routines"]["Instructions"]["components"]}
    assert instr["resp"]["keys"] == ["space"] and "duration" not in instr["resp"]
    loop = d["flow"][1]
    assert loop["order"] == "random" and loop["repeats"] == 2
    assert len(loop["conditions"]) == 6                     # weights 2+1+1+2 expanded
    assert loop["children"] == ["Fixation", "Stimulus", "Feedback"]
    good = d["routines"]["Goodbye"]["components"][0]
    assert good["text"] == "$f'Thank you, {participant}!'" and good["pos"][1] == pytest.approx(-192)
    assert any("InLine" in n["message"] for n in res.notes)
    summary, session = dry(path, tmp_path)
    assert sum(r["routine"] == "Stimulus" for r in session.data.trial_rows) == 12


def test_eprime_without_list_export(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Stroop.ebs3").write_text((FIX / "eprime/Stroop.ebs3").read_text())
    _, res = import_experiment(src / "Stroop.ebs3", tmp_path / "out")
    assert any(n["level"] == "unsupported" and "TrialList.txt" in n["message"] for n in res.notes)


def test_opensesame(tmp_path):
    path, res = import_experiment(FIX / "opensesame/flanker.opensesame", tmp_path)
    d = load(path).to_dict()
    assert d["settings"]["window"]["size"] == [1024, 768]
    loop = next(n for n in d["flow"] if isinstance(n, dict) and "loop" in n)
    assert loop["repeats"] == 2 and len(loop["conditions"]) == 3 and loop["conditions"][1]["stim"] == "<<><<"
    kids = loop["children"]
    assert kids[0] == "fixation" and kids[1] == "target"     # target sketchpad merged with the keyboard
    assert kids[2] == {"routine": "feedback_correct", "if": "$correct == 1"}
    target = {c["id"]: c for c in d["routines"]["target"]["components"]}
    assert target["resp"]["keys"] == ["left", "right"] and target["resp"]["correct"] == "$correct_response"
    assert target["resp"]["duration"] == 2.0
    rect = next(c for c in target.values() if c["type"] == "shape")
    assert rect["pos"] == [0, 0] and rect["size"] == [400, 100]  # OpenSesame top-left rect -> centre
    assert d["routines"]["fixation"]["duration"] == 0.5
    summary, session = dry(path, tmp_path)
    assert sum(r["routine"] == "target" for r in session.data.trial_rows) == 6


def test_jspsych(tmp_path):
    path, res = import_experiment(FIX / "jspsych/experiment.html", tmp_path)
    d = load(path).to_dict()
    flow = d["flow"]
    assert flow[0] == "html_keyboard_response"
    assert d["routines"]["html_keyboard_response"]["components"][0]["text"] == "Welcome! Press any key."
    assert flow[1:3] == ["instructions_p1", "instructions_p2"]
    loop = flow[3]
    assert loop["order"] == "random" and loop["repeats"] == 5 and len(loop["conditions"]) == 2
    test_r = d["routines"][loop["children"][1]]
    stim = test_r["components"][0]
    assert stim["type"] == "image" and stim["image"] == "$stimulus"
    resp = test_r["components"][1]
    assert resp["keys"] == ["f", "j"] and resp["correct"] == "$correct_response" and test_r["duration"] == 1.5
    survey = d["routines"][flow[4]]["components"][0]
    assert survey["type"] == "html" and (tmp_path / survey["file"]).exists()
    page = (tmp_path / survey["file"]).read_text()
    assert "name='focus'" in page and "required" in page
    assert (tmp_path / "img/blue.png").exists()
    assert any("function" in n["message"] for n in res.notes)
    summary, session = dry(path, tmp_path)
    rows = session.data.trial_rows
    focus = [r for r in rows if "survey.focus" in r]
    assert focus and focus[0]["survey.focus"] in (0, 1, 2)
