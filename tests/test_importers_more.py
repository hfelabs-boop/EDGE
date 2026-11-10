"""Importers for Inquisit, Presentation, Gorilla and Psychtoolbox: structure, timing, keys, dry runs, damaged files."""
import shutil
from pathlib import Path

import pytest

from edge.builder.server import BuilderApp, import_candidates
from edge.cli import main
from edge.importers import ImportError_, detect, import_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant
from tests.conftest import run_headless

FIX = Path(__file__).parent / "fixtures"


def imported(src, tmp_path, **kw):
    path, res = import_experiment(src, tmp_path / "out", **kw)
    exp = Experiment.load(path)
    assert [i.message for i in exp.validate() if i.level == "error"] == []
    return path, res, exp.to_dict()


def dry_rows(path):
    exp = Experiment.load(path)
    summary, session, _ = run_headless(exp.source, path.parent, vp=VirtualParticipant(seed=3))
    return session.data.trial_rows


def comps(routine):
    return {c["id"]: c for c in routine["components"]}


def loops(nodes):
    for n in nodes:
        if isinstance(n, dict):
            if "loop" in n:
                yield n
                yield from loops(n.get("children", []))
            yield from loops(n.get("then", []) + n.get("else", []))


def levels(res, level):
    return [n for n in res.notes if n["level"] == level]


def test_detect_new_platforms():
    assert detect(FIX / "inquisit/stroop.iqx") == "inquisit"
    assert detect(FIX / "presentation/stroop.sce") == "presentation"
    assert detect(FIX / "presentation/stroop.pcl") == "presentation"
    assert detect(FIX / "presentation/flanker.sce") == "presentation"
    assert detect(FIX / "gorilla/task.json") == "gorilla"
    assert detect(FIX / "gorilla/flanker_spreadsheet.csv") == "gorilla"
    assert detect(FIX / "psychtoolbox/stroop.m") == "psychtoolbox"
    assert detect(FIX / "psychtoolbox/flanker.m") == "psychtoolbox"
    for plain in ("psychopy/trialTypes.csv", "psychtoolbox/conditions.csv"):   # ordinary trial lists are not Gorilla tasks
        with pytest.raises(ImportError_, match="unrecognized"):
            detect(FIX / plain)


# ------------------------------------------------------------------ Inquisit
def test_inquisit_stroop(tmp_path):
    path, res, d = imported(FIX / "inquisit/stroop.iqx", tmp_path)
    assert d["settings"]["window"]["background"] == "black"
    assert d["variables"] == {"ncorrect": 0, "blockcount": 0}
    flow = d["flow"]
    assert flow[:3] == ["about", "intro", "practice_begin"] and flow[-1] == "goodbye"
    survey = comps(d["routines"]["about"])["about"]
    assert [q["type"] for q in survey["questions"]] == ["number", "single", "dropdown"]
    assert survey["questions"][0]["min"] == 16 and survey["questions"][1]["options"] == ["left", "right", "both"]
    stroop = next(lp for lp in loops(flow) if lp["loop"] == "stroop")
    assert stroop["order"] == "random" and stroop["repeats"] == 2 and len(stroop["conditions"]) == 6
    row = next(r for r in stroop["conditions"] if r["trial"] == "redincongruent")
    assert row == {"trial": "redincongruent", "stim_text": "GREEN", "stim_color": "red", "correct_response": "d"}
    assert next(r for r in stroop["conditions"] if r["trial"] == "greencongruent")["stim_color"] == "#00ff00"
    assert stroop["children"] == ["stroop_trial", {"routine": "stroop_trial_errormessage", "if": "$not resp.corr"},
                                  "stroop_trial_posttrialpause"]
    trial = comps(d["routines"]["stroop_trial"])
    assert trial["fixation"]["text"] == "+" and trial["fixation"]["duration"] == 0.5   # the word replaces the cross
    assert trial["stim"]["text"] == "$stim_text" and trial["stim"]["start"] == 0.5
    assert trial["resp"]["keys"] == ["d", "f", "j"] and trial["resp"]["correct"] == "$correct_response"
    assert trial["resp"]["start"] == 0.5 and trial["resp"]["duration"] == 2.0 and trial["resp"]["end_routine"]
    assert trial["reminder"]["pos"] == [0.0, -307.2]                                   # (50%, 90%) of 768 px
    assert trial["on_end"]["set"]["ncorrect"] == "$(ncorrect + 1) if (resp.corr) else ncorrect"
    assert d["routines"]["stroop_trial_posttrialpause"]["duration"] == 0.25
    assert d["routines"]["stroop_trial_errormessage"]["duration"] == 0.4
    practice = next(lp for lp in loops(flow) if lp["loop"] == "practice_trials")
    assert practice["repeats"] == 4 and practice["children"][1] == {"routine": "practicefeedback", "if": "$not resp.corr"}
    assert comps(d["routines"]["showkeys"])["keyboard"]["image"] == "stimuli/keyboard.png"
    assert (path.parent / "stimuli/keyboard.png").exists()
    unsupported = " ".join(n["message"] for n in levels(res, "unsupported"))
    assert "<list inkcolors>" in unsupported and "<counter oldstyle>" in unsupported and "onexptend" in unsupported
    assert any("noreplace" in n["message"] for n in levels(res, "approx"))
    rows = dry_rows(path)
    assert sum(r["routine"] == "stroop_trial" for r in rows) == 12
    assert sum(r["routine"] == "practice" for r in rows) == 4
    assert {r["trial"] for r in rows if r["routine"] == "stroop_trial"} == {r["trial"] for r in stroop["conditions"]}


def test_inquisit_trial_list_forms(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "task.iqx").write_text("""
<text a>
/ items = ("A")
</text>
<text b>
/ items = ("B")
</text>
<trial ta>
/ stimulustimes = [0 = a]
/ validresponse = (18, 23)
/ correctresponse = (18)
</trial>
<trial tb>
/ stimulusframes = [1 = b]
/ trialduration = 300
/ validresponse = (0)
/ ontrialbegin = [values.x = list.foo.nextvalue]
</trial>
<block one>
/ trials = [1-5 = sequence(ta, tb); 6-7 = replace(ta, tb)]
</block>
""")
    path, res, d = imported(src / "task.iqx", tmp_path)
    ta = comps(d["routines"]["ta"])
    assert ta["resp"]["keys"] == ["e", "i"] and ta["resp"]["correct"] == "e"         # scan codes
    assert d["routines"]["tb"]["duration"] == 0.3
    first, second = list(loops(d["flow"]))
    assert first.get("order", "sequential") == "sequential" and len(first["conditions"]) == 5 and "repeats" not in first
    assert [r["trial"] for r in first["conditions"]] == ["ta", "tb", "ta", "tb", "ta"]
    assert second["order"] == "random" and len(second["conditions"]) == 2
    assert any("no <expt>" in n["message"] for n in res.notes)
    assert any("list.foo.nextvalue" in n["message"] for n in levels(res, "unsupported"))
    rows = dry_rows(path)
    assert sum(r["routine"] in ("ta", "tb") for r in rows) == 7


# ------------------------------------------------------------------ Presentation
def test_presentation_stroop_with_pcl(tmp_path):
    path, res, d = imported(FIX / "presentation/stroop.sce", tmp_path)
    assert d["settings"]["window"]["background"] == "#000000"
    assert d["settings"]["markers"]["codes"]["words_21"] == 21
    flow = d["flow"]
    assert flow[0] == "instr_trial" and flow[-1] == "end_trial"
    loop = flow[1]
    assert loop["order"] == "random" and loop["repeats"] == 2 and len(loop["conditions"]) == 6
    assert loop["conditions"][3] == {"words": "RED", "inks": "#00ff00", "ink_of": 2, "codes": 21}
    assert loop["children"] == ["fix_trial", "stroop_trial", {"routine": "correct_trial", "if": "$resp.corr == 1"},
                                {"routine": "wrong_trial", "if": "$not (resp.corr == 1)"}, "iti_trial"]
    word = comps(d["routines"]["stroop_trial"])
    assert word["word_text"]["text"] == "$words" and word["word_text"]["color"] == "$inks"
    assert word["word_text"]["height"] == 72 and word["word_text"]["marker"] == {"onset": "$f'words_{codes}'"}
    assert word["resp"]["keys"] == ["1", "2", "3"] and word["resp"]["correct"] == "$ink_of" and word["resp"]["end_routine"]
    assert d["routines"]["stroop_trial"]["duration"] == 2.0
    assert d["routines"]["fix_trial"]["duration"] == 0.5
    assert d["routines"]["iti_trial"]["duration"] == "$(random.randint(800, 1200)) / 1000"
    instr = comps(d["routines"]["instr_trial"])
    assert instr["keys_bmp"]["pos"] == [0, -200] and instr["instr_text"]["pos"] == [0, 100]
    assert comps(d["routines"]["wrong_trial"])["sound"]["sound"] == "wrong.wav"
    assert (path.parent / "wrong.wav").exists() and (path.parent / "keys.png").exists()
    pcl = next(n for n in levels(res, "unsupported") if n["where"] == "PCL")["message"]
    assert "line 35: n_correct = n_correct + 1" in pcl
    assert any("button 1 became the key '1'" in n["message"] for n in levels(res, "approx"))
    assert any("lines 13, 14, 15" in n["message"] for n in levels(res, "info"))
    rows = dry_rows(path)
    assert sum(r["routine"] == "stroop_trial" for r in rows) == 12
    assert sum(r["routine"] in ("correct_trial", "wrong_trial") for r in rows) == 12


def test_presentation_template_without_pcl(tmp_path):
    path, res, d = imported(FIX / "presentation/flanker.sce", tmp_path)
    assert d["settings"]["window"]["background"] == "#808080"
    loop = d["flow"][1]
    assert loop.get("order", "sequential") == "sequential" and loop["repeats"] == 2
    assert loop["conditions"][1] == {"arrows": ">><>>", "target": 1, "code": "incongruent_left"}
    trial = comps(d["routines"][loop["children"][0]])
    assert trial["plus"]["duration"] == 0.4
    assert trial["text"]["text"] == "$arrows" and trial["text"]["start"] == 0.5 and trial["text"]["duration"] == 0.2
    assert trial["text"]["marker"] == {"onset": "$code", "code": 1}
    assert trial["resp"]["correct"] == "$target" and trial["resp"]["start"] == 0.5
    rows = dry_rows(path)
    assert sum(r["routine"] == loop["children"][0] for r in rows) == 8


def test_presentation_pcl_file_imports_its_scenario(tmp_path):
    path, res = import_experiment(FIX / "presentation/stroop.pcl", tmp_path / "out")
    assert path.name == "stroop.yaml" and any("stroop.sce" in n["message"] for n in res.notes)
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(FIX / "presentation/stroop.pcl", lone)
    with pytest.raises(ImportError_, match="import the scenario"):
        import_experiment(lone / "stroop.pcl")


# ------------------------------------------------------------------ Gorilla
def test_gorilla_structure_and_spreadsheet(tmp_path):
    path, res, d = imported(FIX / "gorilla/task.json", tmp_path)
    flow = d["flow"]
    assert flow[0] == "instructions_Welcome" and flow[-2:] == ["end_Rating", "end_Debrief"]
    practice = flow[1]
    assert practice["order"] == "random" and len(practice["conditions"]) == 4
    assert practice["children"] == ["practice_Fixation", "practice_Stimulus", "practice_Feedback"]
    assert practice["conditions"][0]["Stimulus"] == "stimuli/congruent_left.png"
    blocks = flow[3]
    assert blocks["loop"] == "blocks" and blocks["order"] == "random"
    assert blocks["conditions"] == [{"randomise_blocks": 1}, {"randomise_blocks": 2}]
    inner = blocks["children"][1]["then"][0]
    assert inner["order"] == "random" and [r["ITI"] for r in inner["conditions"]] == [600, 400, 600, 400]
    stim = comps(d["routines"]["trial_Stimulus"])
    assert stim["arrows"]["image"] == "$Stimulus"
    assert stim["resp"]["keys"] == ["f", "j"] and stim["resp"]["correct"] == "$ANSWER" and stim["resp"]["duration"] == 2.0
    assert d["routines"]["trial_Fixation"]["duration"] == 0.5
    assert d["routines"]["trial_ITI"]["duration"] == "$(ITI) / 1000"
    welcome = comps(d["routines"]["instructions_Welcome"])
    assert welcome["welcome_text"]["text"].startswith("Arrow task\nLook at the middle arrow.")
    assert welcome["click"]["clickable"] == ["start_button"]
    rating = comps(d["routines"]["end_Rating"])
    assert rating["click"]["clickable"] == ["difficulty_Easy_button", "difficulty_OK_button", "difficulty_Hard_button"]
    assert "resp.corr" in comps(d["routines"]["practice_Feedback"])["fb"]["text"]
    assert any("Video" in n["message"] for n in levels(res, "unsupported"))
    assert (path.parent / "stimuli/congruent_left.png").exists() and (path.parent / "stimuli/beep.wav").exists()
    rows = dry_rows(path)
    assert sum(r["routine"] == "practice_Stimulus" for r in rows) == 4
    assert sum(r["routine"] == "trial_Stimulus" for r in rows) == 8
    assert {r["Block"] for r in rows if r["routine"] == "trial_Stimulus"} == {"A", "B"}


def test_gorilla_spreadsheet_alone_and_xlsx(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(FIX / "gorilla/flanker_spreadsheet.csv", src)
    shutil.copytree(FIX / "gorilla/stimuli", src / "stimuli")
    path, res, d = imported(src / "flanker_spreadsheet.csv", tmp_path)
    assert any("no task structure" in n["message"] for n in levels(res, "approx"))
    trial = comps(d["routines"]["trial"])
    assert trial["Stimulus_item"]["image"] == "$Stimulus"         # renamed: the column keeps the name
    assert trial["resp"]["keys"] == ["f", "j"] and trial["resp"]["correct"] == "$ANSWER"
    assert sum(r["routine"] == "trial" for r in dry_rows(path)) == 8
    openpyxl = pytest.importorskip("openpyxl")
    import csv
    wb = openpyxl.Workbook()
    for r in csv.reader((FIX / "gorilla/flanker_spreadsheet.csv").read_text().splitlines()):
        wb.active.append(r)
    xdir = tmp_path / "xlsx"
    xdir.mkdir()
    wb.save(xdir / "flanker.xlsx")
    shutil.copy(FIX / "gorilla/task.json", xdir)
    shutil.copytree(FIX / "gorilla/stimuli", xdir / "stimuli")
    assert detect(xdir / "flanker.xlsx") == "gorilla"
    path, res, d = imported(xdir / "task.json", tmp_path / "x")
    assert sum(len(lp["conditions"]) for lp in loops(d["flow"]) if lp["loop"].startswith("trial")) == 8


# ------------------------------------------------------------------ Psychtoolbox
def test_psychtoolbox_condition_matrix(tmp_path):
    path, res, d = imported(FIX / "psychtoolbox/stroop.m", tmp_path)
    assert d["settings"]["window"]["background"] == "#000000"
    assert any("Code translation is partial" in n["message"] for n in levels(res, "approx"))
    assert d["flow"][0] == "instructions" and d["flow"][-1] == "thank_you"
    loop = d["flow"][1]
    assert loop["order"] == "random" and loop["repeats"] == 2 and len(loop["conditions"]) == 6
    assert loop["conditions"][3] == {"wordNum": 1, "colorNum": 2, "theWord": "RED", "theColor": "#00ff00",
                                     "correct_key": "f"}
    assert loop["children"] == ["fixation", "stimulus", "blank"]
    stim = comps(d["routines"]["stimulus"])
    assert stim["text"]["text"] == "$theWord" and stim["text"]["color"] == "$theColor" and stim["text"]["height"] == 60
    assert stim["resp"]["keys"] == ["d", "f", "j"] and stim["resp"]["correct"] == "$correct_key"
    assert stim["resp"]["duration"] == 2 and stim["resp"]["end_routine"]
    assert d["routines"]["fixation"]["duration"] == 0.5 and d["routines"]["blank"]["duration"] == 0.8
    assert comps(d["routines"]["instructions"])["text"]["color"] == "#ffffff"
    rows = dry_rows(path)
    assert sum(r["routine"] == "stimulus" for r in rows) == 12


def test_psychtoolbox_table_textures_queue_and_sound(tmp_path):
    path, res, d = imported(FIX / "psychtoolbox/flanker.m", tmp_path)
    assert d["settings"]["window"]["background"] == "#808080"
    loop = d["flow"][1]
    assert loop["order"] == "random" and len(loop["conditions"]) == 8 and "repeats" not in loop
    assert loop["conditions"][0] == {"image": "stimuli/congruent_left.png", "congruency": "congruent",
                                     "correct_key": "left", "fixdur": 400}
    assert d["routines"]["fixation"]["duration"] == "$fixdur / 1000"
    stim = d["routines"]["stimulus"]
    assert stim["duration"] == 1.5
    resp = comps(stim)["resp"]
    assert resp["keys"] == ["left", "right"] and resp["correct"] == "$correct_key" and not resp.get("end_routine")
    beep = comps(d["routines"]["blank"])["sound"]
    assert beep["sound"] == "stimuli/beep.wav" and beep["if"] == "$not resp.corr"
    assert (path.parent / "stimuli/incongruent_right.png").exists() and (path.parent / "stimuli/beep.wav").exists()
    rows = dry_rows(path)
    assert sum(r["routine"] == "stimulus" for r in rows) == 8


def test_psychtoolbox_lists_what_it_does_not_translate(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "task.m").write_text("""% a script with a custom staircase
win = Screen('OpenWindow', 0, 128);
contrast = 0.5;
for t = 1:10
    DrawFormattedText(win, 'X', 'center', 'center', 0);
    Screen('Flip', win);
    contrast = updateStaircase(contrast, t);   % our own function
    WaitSecs(0.2);
end
sca;
""")
    path, res, d = imported(src / "task.m", tmp_path)
    code = next(n for n in levels(res, "unsupported") if n["where"] == "MATLAB code")["message"]
    assert "line 7: contrast = updateStaircase(contrast, t)" in code
    assert d["settings"]["window"]["background"] == "#808080"
    assert d["flow"][0]["loop"] == "trials" and len(d["flow"][0]["conditions"]) == 10


# ------------------------------------------------------------------ damaged files, CLI, builder
@pytest.mark.parametrize("rel,cut,message", [
    ("inquisit/stroop.iqx", 0.05, "nothing could be converted from stroop.iqx.*no <expt> or <block>"),
    ("presentation/stroop.sce", 0.1, "no 'begin;' line"),
    ("presentation/stroop.sce", 0.5, "nothing could be converted from stroop.sce.*cut short"),
    ("presentation/stroop.pcl", 0.4, "PCL program presents no trial"),
    ("gorilla/task.json", 0.5, "not a Gorilla task structure.*damaged or cut short"),
    ("psychtoolbox/stroop.m", 0.3, "nothing could be converted from stroop.m.*no screen"),
])
def test_truncated_files_are_refused_clearly(tmp_path, rel, cut, message):
    src = FIX / rel
    d = tmp_path / "src"
    shutil.copytree(src.parent, d)
    data = src.read_bytes()
    (d / src.name).write_bytes(data[:int(len(data) * cut)])
    with pytest.raises(ImportError_, match=message):
        import_experiment(d / src.name, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_damaged_files(tmp_path):
    (tmp_path / "noise.iqx").write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ImportError_, match="nothing could be converted from noise.iqx"):
        import_experiment(tmp_path / "noise.iqx")
    (tmp_path / "broken.xlsx").write_bytes(b"PK\x03\x04 not really a workbook")
    with pytest.raises(ImportError_, match="(could not be read as an Excel workbook|needs 'openpyxl')"):
        import_experiment(tmp_path / "broken.xlsx")
    (tmp_path / "analysis.m").write_text("x = mean([1 2 3]);\n")
    with pytest.raises(ImportError_, match="unrecognized"):
        import_experiment(tmp_path / "analysis.m")
    with pytest.raises(ImportError_, match="does not look like a Psychtoolbox experiment"):
        import_experiment(tmp_path / "analysis.m", platform="psychtoolbox")


def test_cli_and_builder_detect_new_platforms(tmp_path, capsys):
    assert main(["import", str(FIX / "inquisit/stroop.iqx"), "--out", str(tmp_path / "cli")]) == 0
    assert "imported Inquisit experiment" in capsys.readouterr().out
    assert main(["import", str(FIX / "psychtoolbox/stroop.m"), "--platform", "psychtoolbox",
                 "--out", str(tmp_path / "cli2")]) == 0
    # the builder's Import: a whole Gorilla download (structure + spreadsheet + stimuli folder)
    root = tmp_path / "ws"
    up = root / "imports/flanker/source"
    shutil.copytree(FIX / "gorilla", up)
    found = import_candidates(up)
    assert {f.name for f in found} == {"task.json", "flanker_spreadsheet.csv"}
    app = BuilderApp(root)
    r = app.import_source("imports/flanker/source", "imports/flanker")
    assert r["platform"] == "Gorilla" and r["path"].startswith("imports/flanker/")
    # a Presentation folder: the scenario is imported (also when the PCL file is found first)
    pres = root / "imports/pres/source"
    shutil.copytree(FIX / "presentation", pres)
    r = app.import_source("imports/pres/source", "imports/pres")
    assert r["platform"] == "Presentation"
    # an earlier upload of another 'stroop' left its file in the folder: the file the researcher chose wins
    shutil.copy(FIX / "inquisit/stroop.iqx", pres)
    assert app.import_source("imports/pres/source", "imports/pres_b")["platform"] == "Inquisit"
    r = app.import_source("imports/pres/source", "imports/pres_c", main="stroop.sce")
    assert r["platform"] == "Presentation" and r["source"] == "stroop.sce"


def test_builder_schema_lists_new_extensions():
    from edge.builder import server
    exts = server.schema()["import_extensions"]
    for ext in (".iqx", ".exp", ".sce", ".pcl", ".m", ".json", ".csv", ".xlsx"):
        assert ext in exts
    app_js = (Path(server.__file__).parent / "static/app.js").read_text()
    assert '".iqx", ".exp", ".sce", ".pcl", ".m"' in app_js


def test_mcp_import(tmp_path):
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    from tests.test_mcp import call
    shutil.copytree(FIX / "presentation", tmp_path / "pres")
    server = create_server(tmp_path)
    r = call(server, "import_experiment", source="pres/flanker.sce", out_dir="pres_edge")
    assert r["ok"] and r["platform"] == "Presentation" and r["path"] == "pres_edge/flanker.yaml"
    assert any("button" in a for a in r["approximate"])
