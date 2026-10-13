"""Regression tests for the importer fixes (audit group D): readable jsPsych text, scripts next to the page,
refused empty/damaged/mis-labelled imports, inline HTML styling, OpenSesame line breaks and font sizes, E-Prime
"too slow" feedback, re-imports that keep earlier work, UTF-16 files, Windows paths, jsPsych data fields,
missing list exports, safe names, routine names from variables, and small message fixes."""
from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge.backends.headless import HeadlessBackend
from edge.builder.server import BuilderApp, make_handler
from edge.cli import main
from edge.engine import Runner
from edge.importers import ImportError_, import_experiment, platform_name
from edge.importers.base import html_to_text
from edge.model import Experiment
from edge.participant import VirtualParticipant
from edge.runtime import Session
from tests.conftest import run_headless

FIX = Path(__file__).parent / "fixtures"


def copy_fixture(name: str, tmp_path: Path) -> Path:
    dest = tmp_path / name
    shutil.copytree(FIX / name, dest)
    return dest


def jspsych_page(folder: Path, script: str, name: str = "exp.html") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("<html><head><script src='https://unpkg.com/jspsych@7.3.4'></script></head>"
                               f"<body></body><script>\n{script}\n</script></html>")
    return folder / name


def text_comps(doc: dict) -> list[dict]:
    return [c for r in doc["routines"].values() for c in r["components"] if c["type"] == "text"]


# ------------------------------------------------------------------ importers#0: white text on white
def test_jspsych_text_is_dark_on_the_white_page(tmp_path):
    path, _ = import_experiment(FIX / "jspsych/experiment.html", tmp_path / "out")
    d = Experiment.load(path).to_dict()
    assert d["settings"]["window"]["background"] == "#ffffff"
    texts = text_comps(d)
    assert texts and all(c.get("color") == "black" for c in texts)


# ------------------------------------------------------------------ importers#4: timeline in experiment.js
def test_jspsych_page_reads_its_own_script_files(tmp_path):
    src = (FIX / "jspsych/experiment.html").read_text()
    m = re.search(r"<script>(.*?)</script>", src, re.S)
    d = tmp_path / "split"
    shutil.copytree(FIX / "jspsych/img", d / "img")
    (d / "experiment.js").write_text(m.group(1))
    (d / "index.html").write_text(src.replace(m.group(0), '<script src="experiment.js?v=2"></script>'))
    path, res = import_experiment(d / "index.html", tmp_path / "out")
    doc = Experiment.load(path).to_dict()
    assert doc["flow"][0] == "welcome" and len(doc["routines"]) == 6
    assert any("experiment.js" in n["message"] for n in res.notes if n["level"] == "info")
    # a script that isn't there: refused, with the reason
    (d / "index.html").write_text(src.replace(m.group(0), '<script src="missing.js"></script>'))
    with pytest.raises(ImportError_, match="missing.js"):
        import_experiment(d / "index.html", tmp_path / "out2")
    assert not (tmp_path / "out2").exists()
    # the experiment's code in a file named like a jsPsych library: the refusal says which file to import
    (d / "jspsych_stroop.js").write_text(m.group(1))
    (d / "index.html").write_text(src.replace(m.group(0), '<script src="jspsych_stroop.js"></script>'))
    with pytest.raises(ImportError_, match="if the experiment's code is in jspsych_stroop.js .*import that file"):
        import_experiment(d / "index.html", tmp_path / "out3")


def test_utf16_pages_and_psyexp_files_are_recognized(tmp_path):
    from edge.importers import detect
    for src, enc in ((FIX / "jspsych/experiment.html", "utf-16"), (FIX / "psychopy/stroop.psyexp", "utf-16")):
        text = src.read_text().replace('encoding="utf-8"', 'encoding="utf-16"')
        (tmp_path / src.name).write_bytes(text.encode(enc))
    assert detect(tmp_path / "experiment.html") == "jspsych" and detect(tmp_path / "stroop.psyexp") == "psychopy"
    shutil.copy(FIX / "psychopy/trialTypes.csv", tmp_path)
    path, _ = import_experiment(tmp_path / "stroop.psyexp")
    plain, _ = import_experiment(FIX / "psychopy/stroop.psyexp", tmp_path / "plain")
    assert Experiment.load(path).to_dict()["routines"] == Experiment.load(plain).to_dict()["routines"]


# ------------------------------------------------------------------ importers#5 / mcp#21: empty or mis-labelled
def test_imports_that_convert_nothing_are_refused_and_write_nothing(tmp_path):
    (tmp_path / "trunc.ebs3").write_bytes((FIX / "eprime/Stroop.ebs3").read_bytes()[:1000])
    with pytest.raises(ImportError_, match="nothing could be converted from trunc.ebs3.*no runnable procedure"):
        import_experiment(tmp_path / "trunc.ebs3")
    (tmp_path / "random.osexp").write_bytes(bytes(range(256)) * 2)
    with pytest.raises(ImportError_, match="incomplete or damaged"):
        import_experiment(tmp_path / "random.osexp")
    assert not list(tmp_path.glob("*_edge"))


def test_a_wrong_platform_is_refused_and_keeps_the_earlier_import(tmp_path):
    pp = copy_fixture("psychopy", tmp_path)
    good, _ = import_experiment(pp / "stroop.psyexp")
    before = good.read_text()
    with pytest.raises(ImportError_, match="is a PsychoPy experiment, not E-Prime"):
        import_experiment(pp / "stroop.psyexp", platform="eprime")
    assert good.read_text() == before
    assert platform_name("PsychoPy") == "psychopy" and platform_name("E-Prime") == "eprime"
    assert platform_name("PsychoPy 2023.2.3") == "psychopy"
    with pytest.raises(ImportError_, match="choose psychopy, eprime, opensesame, jspsych"):
        platform_name("presentation")


def test_validation_errors_are_listed_as_wont_run_and_the_cli_says_so(tmp_path, capsys):
    ep = tmp_path / "ep"
    ep.mkdir()
    shutil.copy(FIX / "eprime/Stroop.ebs3", ep)                     # no TrialList.txt export
    _, res = import_experiment(ep / "Stroop.ebs3", tmp_path / "a")
    assert any(n["level"] == "error" and "TrialList.txt" in n["message"] for n in res.notes)
    assert not any(n["level"] == "approx" and "not found" in n["message"] for n in res.notes)
    report = (tmp_path / "a/IMPORT_REPORT.md").read_text()
    assert "## Won't run until fixed" in report
    assert report.index("Won't run until fixed") < report.index("Not converted")
    assert main(["import", str(ep / "Stroop.ebs3"), "--out", str(tmp_path / "b")]) == 1
    out = capsys.readouterr().out
    assert "won't run until 1 problem(s) are fixed" in out and "TrialList.txt" in out


# ------------------------------------------------------------------ importers#6: damaged files
def test_damaged_files_get_a_plain_message_not_a_traceback(tmp_path, capsys):
    (tmp_path / "trunc.psyexp").write_bytes((FIX / "psychopy/stroop.psyexp").read_bytes()[:3000])
    with pytest.raises(ImportError_, match=r"incomplete or damaged \(the problem is on line \d+\).*PsychoPy"):
        import_experiment(tmp_path / "trunc.psyexp")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = (FIX / "opensesame/flanker.opensesame").read_bytes()
        info = tarfile.TarInfo("exp/script.opensesame")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (tmp_path / "trunc.osexp").write_bytes(buf.getvalue()[:300])
    with pytest.raises(ImportError_, match="archive is incomplete or damaged"):
        import_experiment(tmp_path / "trunc.osexp")
    assert main(["import", str(tmp_path / "trunc.psyexp")]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "ParseError" not in err and "incomplete or damaged" in err


def test_files_cut_short_never_crash_the_importers(tmp_path):
    for src in (FIX / "psychopy/stroop.psyexp", FIX / "eprime/Stroop.ebs3", FIX / "opensesame/flanker.opensesame",
                FIX / "jspsych/experiment.html"):
        data = src.read_bytes()
        for n in range(0, len(data), max(1, len(data) // 25)):
            d = tmp_path / f"{src.stem}_{n}"
            d.mkdir()
            (d / src.name).write_bytes(data[:n])
            try:
                import_experiment(d / src.name, d / "out")
            except ImportError_ as e:
                assert "importer did not understand" not in str(e), (src.name, n, e)


# ------------------------------------------------------------------ importers#8: inline HTML styling
def test_jspsych_inline_style_becomes_text_properties(tmp_path):
    page = jspsych_page(tmp_path / "js", "const jsPsych = initJsPsych();\n"
                        "const t1 = { type: jsPsychHtmlKeyboardResponse, stimulus: "
                        "'<p style=\"color:red; font-size:48px; text-decoration: underline\"><b>GREEN</b></p>', "
                        "choices: ['r','g'] };\njsPsych.run([t1]);")
    path, res = import_experiment(page, tmp_path / "out")
    stim = Experiment.load(path).to_dict()["routines"]["t1"]["components"][0]
    assert stim["text"] == "GREEN" and stim["color"] == "red" and stim["height"] == 48 and stim["bold"] is True
    assert any("text-decoration" in n["message"] for n in res.notes if n["level"] == "approx")


def test_jspsych_html_timeline_variables_become_text_and_colour_columns(tmp_path):
    page = jspsych_page(tmp_path / "js", """
      var timeline = [];
      var stimuli = [
        { stimulus: "<p style='color:blue;font-size:48px'>BLUE</p>", correct_response: 'f' },
        { stimulus: "<p style='color:orange;font-size:48px'>ORANGE &amp; co</p>", correct_response: 'j' }];
      var test = { type: 'html-keyboard-response', stimulus: jsPsych.timelineVariable('stimulus'), choices: ['f','j'],
                   data: { correct_response: jsPsych.timelineVariable('correct_response') } };
      var debrief = { type: 'html-keyboard-response', stimulus: function(){ return '<p>Done</p>'; } };
      timeline.push({ timeline: [test], timeline_variables: stimuli }, debrief);
      jsPsych.init({ timeline: timeline });""")
    path, res = import_experiment(page, tmp_path / "out")
    d = Experiment.load(path).to_dict()
    stim = d["routines"]["test"]["components"][0]
    assert stim["text"] == "$stimulus_text" and stim["color"] == "$stimulus_color" and stim["height"] == 48
    assert "x_note" not in json.dumps(d)
    rows = d["flow"][0]["conditions"]
    assert [r["stimulus_text"] for r in rows] == ["BLUE", "ORANGE & co"]
    assert [r["stimulus_color"] for r in rows] == ["blue", "orange"]
    assert rows[0]["stimulus"].startswith("<p")                   # the original column is kept for HTML pages
    debrief_notes = [n["message"] for n in res.notes if n["where"].endswith("debrief")]
    assert debrief_notes and not any("timeline variable" in m for m in debrief_notes)
    _, session, be = run_headless(d, path.parent, vp=VirtualParticipant(seed=3))
    shown = {p.get("text") for f in be.frame_log for k, p in f["drawn"] if k == "text"}
    assert "BLUE" in shown and not any(str(t).startswith("<p") for t in shown)


def test_html_to_text_handles_breaks_entities_and_partial_styling():
    text, style, dropped = html_to_text("Press <b>F</b> for blue,<br>J&nbsp;for orange")
    assert text == "Press F for blue,\nJ\xa0for orange" and "bold" not in style
    assert "bold on part of the text" in dropped
    assert html_to_text("<<><<") == ("<<><<", {}, [])           # flanker arrows are not HTML
    assert html_to_text("<span style='color: rgb(255, 0, 0)'>x</span>")[1] == {"color": "#ff0000"}


# ------------------------------------------------------------------ importers#9 / #20: OpenSesame text
def test_opensesame_line_breaks_and_pixel_font_sizes(tmp_path):
    path, _ = import_experiment(FIX / "opensesame/flanker.opensesame", tmp_path / "out")
    d = Experiment.load(path).to_dict()
    instr = d["routines"]["instructions"]["components"][0]
    assert instr["text"] == "Respond to the middle arrow\nPress any key" and instr["height"] == 24
    target = d["routines"]["target"]["components"][0]
    assert target["text"] == "$stim" and target["height"] == 48
    assert d["routines"]["goodbye"]["components"][0]["height"] == 18     # OpenSesame's default font size


def test_opensesame_span_colour_and_bold(tmp_path):
    script = ("set start experiment\ndefine sequence experiment\n\trun s always\n"
              "define sketchpad s\n\tset duration 500\n"
              "\tdraw textline text=\"<span color='red'><b>Stop</b></span>\" x=0 y=0 color=white font_size=30\n"
              "\tdraw textline text=\"<span color=[ink]>Go</span>\" x=0 y=50 color=white\n")
    (tmp_path / "t.opensesame").write_text(script)
    path, res = import_experiment(tmp_path / "t.opensesame", tmp_path / "out")
    c, v = Experiment.load(path).to_dict()["routines"]["s"]["components"][:2]
    assert c["text"] == "Stop" and c["color"] == "red" and c["bold"] is True and c["height"] == 30
    assert v["text"] == "Go" and v["color"] == "$ink"           # a colour from a variable stays a variable
    assert not any("styling not kept" in n["message"] for n in res.notes)


# ------------------------------------------------------------------ importers#10: E-Prime "Too slow"
@pytest.mark.parametrize("respond, expected", [(0.0, {"Too slow"}), (1.0, {"Correct", "Incorrect"})])
def test_eprime_feedback_says_too_slow_after_a_missed_response(tmp_path, respond, expected):
    path, _ = import_experiment(FIX / "eprime/Stroop.ebs3", tmp_path / "out")
    exp = Experiment.load(path)
    be = HeadlessBackend(size=tuple(exp.settings["window"]["size"]))
    session = Session(exp, be, data_dir=tmp_path / "data", log=lambda *a: None,
                      virtual_participant=VirtualParticipant(respond_prob=respond, seed=1))
    Runner(session).run()
    shown = {p.get("text") for f in be.frame_log for k, p in f["drawn"] if k == "text"}
    assert shown & {"Correct", "Incorrect", "Too slow"} <= expected and shown & expected


# ------------------------------------------------------------------ importers#11: re-imports keep earlier work
def test_reimport_never_overwrites_earlier_work(tmp_path):
    pp = copy_fixture("psychopy", tmp_path)
    first, _ = import_experiment(pp / "stroop.psyexp")
    first.write_text(first.read_text().replace("repeats: 2", "repeats: 10"))
    with (first.parent / "trialTypes.csv").open("a") as f:
        f.write("blue,red,left,0\n")
    second, res = import_experiment(pp / "stroop.psyexp")
    assert second.parent.name == "stroop_edge_2" and "repeats: 2" in second.read_text()
    assert "repeats: 10" in first.read_text() and "blue,red,left,0" in (first.parent / "trialTypes.csv").read_text()
    assert any(n["where"] == "output" and "stroop_edge_2" in n["message"] for n in res.notes)
    # two different experiments into one folder: the second gets its own folder and report
    import_experiment(pp / "stroop.psyexp", tmp_path / "shared")
    other, _ = import_experiment(FIX / "opensesame/flanker.opensesame", tmp_path / "shared")
    assert other.parent.name == "shared_2"
    assert (tmp_path / "shared/IMPORT_REPORT.md").read_text().startswith("# Import report: stroop.psyexp")


def test_reimport_updates_an_import_nobody_changed(tmp_path):
    from edge.storage import list_backups
    ep = tmp_path / "ep"
    ep.mkdir()
    shutil.copy(FIX / "eprime/Stroop.ebs3", ep)                     # the list export is missing at first
    first, _ = import_experiment(ep / "Stroop.ebs3")
    assert "conditions: TrialList.txt" in first.read_text()
    shutil.copy(FIX / "eprime/TrialList.txt", ep)                   # as the report asks: export it, import again
    again, res = import_experiment(ep / "Stroop.ebs3")
    assert again == first and "Word: RED" in again.read_text()
    assert any(n["where"] == "output" and "previous version is kept as a backup" in n["message"] for n in res.notes)
    assert [b["label"] for b in list_backups(again)] == ["before importing again"]
    same, res = import_experiment(ep / "Stroop.ebs3")              # nothing changed: nothing new
    assert same == first and len(list_backups(same)) == 1
    # recorded sessions belong to the import they were recorded with
    (first.parent / "data/P01_session1").mkdir(parents=True)
    assert import_experiment(ep / "Stroop.ebs3")[0].parent.name == "Stroop_edge_2"
    # another file of the same name (trunc.ebs3 / trunc.html) never replaces it
    shutil.copy(FIX / "jspsych/experiment.html", ep / "Stroop.html")
    assert import_experiment(ep / "Stroop.html")[0].parent.name == "Stroop_edge_3"


def test_builder_reimport_goes_next_to_an_edited_import(tmp_path):
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        src = tmp_path / "imports/flanker/source"
        src.mkdir(parents=True)
        shutil.copy(FIX / "opensesame/flanker.opensesame", src)
        paths = []
        for i in range(3):
            if i == 2:                                              # the researcher edits the import
                f = tmp_path / paths[0]
                f.write_text(f.read_text().replace("Thanks!", "Thank you!"))
            req = urllib.request.Request(base + "/api/import", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"source": "imports/flanker/source/flanker.opensesame",
                                                          "out": "imports/flanker"}).encode())
            with urllib.request.urlopen(req) as r:
                paths.append(json.loads(r.read())["path"])
        assert paths == ["imports/flanker/Flanker_task.yaml"] * 2 + ["imports/flanker_2/Flanker_task.yaml"]
        assert "Thank you!" in (tmp_path / paths[0]).read_text()
    finally:
        httpd.shutdown()


# ------------------------------------------------------------------ importers#12: UTF-16 ("Unicode") files
@pytest.mark.parametrize("which", ["list", "script"])
def test_eprime_utf16_files(tmp_path, which):
    d = tmp_path / "ep"
    d.mkdir()
    for name in ("Stroop.ebs3", "TrialList.txt"):
        text = (FIX / "eprime" / name).read_text().replace("\n", "\r\n")
        enc = "utf-16" if (name == "TrialList.txt") == (which == "list") else "utf-8"
        (d / name).write_bytes(text.encode(enc))
    path, _ = import_experiment(d / "Stroop.ebs3", tmp_path / "out")
    loop = Experiment.load(path).to_dict()["flow"][1]
    assert set(loop["conditions"][0]) == {"Word", "InkColor", "CorrectAnswer"} and len(loop["conditions"]) == 6


# ------------------------------------------------------------------ importers#15: Windows paths
def test_psychopy_windows_paths_are_made_portable(tmp_path):
    d = tmp_path / "pp"
    (d / "conditions").mkdir(parents=True)
    shutil.copy(FIX / "psychopy/trialTypes.csv", d / "conditions")
    src = (FIX / "psychopy/stroop.psyexp").read_text()
    src = src.replace('val="trialTypes.csv"', 'val="conditions\\trialTypes.csv"')
    (d / "stroop.psyexp").write_text(src)
    path, res = import_experiment(d / "stroop.psyexp", tmp_path / "out")
    loop = next(n for n in Experiment.load(path).to_dict()["flow"] if isinstance(n, dict))
    assert loop["conditions"] == "conditions/trialTypes.csv" and (tmp_path / "out/conditions/trialTypes.csv").exists()
    assert not [n for n in res.notes if n["level"] == "error"]


# ------------------------------------------------------------------ importers#16: jsPsych data fields
def test_jspsych_data_fields_are_saved_with_each_trial(tmp_path):
    path, _ = import_experiment(FIX / "jspsych/experiment.html", tmp_path / "out")
    d = Experiment.load(path).to_dict()
    _, session, _ = run_headless(d, path.parent, vp=VirtualParticipant(seed=1))
    rows = session.data.trial_rows
    tasks = {r["routine"]: r.get("task") for r in rows}
    assert tasks["fixation"] == "fixation" and tasks["test"] == "response"
    assert tasks["survey"] is None                                  # no stale value from the trial before


# ------------------------------------------------------------------ importers#17: E-Prime list not exported
def test_eprime_without_list_export_does_not_pass_as_ok(tmp_path, capsys):
    d = tmp_path / "ep"
    d.mkdir()
    shutil.copy(FIX / "eprime/Stroop.ebs3", d)
    path, res = import_experiment(d / "Stroop.ebs3", tmp_path / "out")
    loop = Experiment.load(path).to_dict()["flow"][1]
    assert loop["conditions"] == "TrialList.txt"
    assert any("Word, InkColor, CorrectAnswer" in n["message"] for n in res.notes)
    assert main(["validate", str(path)]) != 0
    assert "TrialList.txt" in capsys.readouterr().out


# ------------------------------------------------------------------ importers#19: --name with a slash
def test_name_with_a_slash_makes_a_safe_file_name(tmp_path, capsys):
    pp = copy_fixture("psychopy", tmp_path)
    assert main(["import", str(pp / "stroop.psyexp"), "--name", "Stroop 1/2", "--out", str(tmp_path / "named")]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "named/Stroop_1_2.yaml").exists() and (tmp_path / "named/trialTypes.csv").exists()
    assert str(tmp_path / "named" / "IMPORT_REPORT.md") in out
    assert Experiment.load(tmp_path / "named/Stroop_1_2.yaml").name == "Stroop 1/2"


# ------------------------------------------------------------------ importers#21: names and notes
def test_jspsych_routines_are_named_after_variables_with_one_note_each(tmp_path):
    path, res = import_experiment(FIX / "jspsych/experiment.html", tmp_path / "out")
    d = Experiment.load(path).to_dict()
    assert set(d["routines"]) == {"welcome", "instructions_p1", "instructions_p2", "fixation", "test", "survey"}
    assert d["flow"][3]["loop"] == "test_procedure"
    fix_notes = [n for n in res.notes if n["where"] == "routines.fixation" and "trial_duration" in n["message"]]
    assert len(fix_notes) == 1 and fix_notes[0]["level"] == "approx"
    for n in res.notes:                                 # every note points at something that exists
        m = re.match(r"routines\.(\w+)", n["where"])
        assert not m or m.group(1) in d["routines"], n


# ------------------------------------------------------------------ importers#22: small message issues
def test_a_folder_names_the_experiment_file_inside(tmp_path):
    d = tmp_path / "ep_nolist"
    d.mkdir()
    shutil.copy(FIX / "eprime/Stroop.ebs3", d)
    with pytest.raises(ImportError_, match=r"'ep_nolist' is a folder: import the experiment file inside it "
                                           r"\(Stroop.ebs3\)"):
        import_experiment(d)
    with pytest.raises(ImportError_, match="'Stroop.ebs3' is a file, not a folder"):     # --out naming a file
        import_experiment(FIX / "psychopy/stroop.psyexp", d / "Stroop.ebs3")


def test_mcp_import_platform_and_name(tmp_path):
    pytest.importorskip("mcp")
    from tests.test_mcp import call
    from edge.mcp_server import create_server
    server = create_server(tmp_path)
    shutil.copytree(FIX / "psychopy", tmp_path / "pp")
    ok = call(server, "import_experiment", source="pp/stroop.psyexp", platform="PsychoPy", name="My Stroop")
    assert ok["ok"] and ok["path"] == "pp/stroop_edge/My_Stroop.yaml"
    before = (tmp_path / ok["path"]).read_text()
    bad = call(server, "import_experiment", source="pp/stroop.psyexp", platform="eprime")
    assert not bad["ok"] and "not E-Prime" in bad["error"]
    assert (tmp_path / ok["path"]).read_text() == before
    unknown = call(server, "import_experiment", source="pp/stroop.psyexp", platform="Presentation")
    assert not unknown["ok"] and "choose psychopy, eprime, opensesame, jspsych" in unknown["error"]


def test_try_it_error_keeps_its_quotes(tmp_path):
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        doc = {"name": "x", "routines": {"r": {"components": [{"id": "stim", "type": "text"}]}}, "flow": ["r"]}
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/play/start",
                                     headers={"Content-Type": "application/json"},
                                     data=json.dumps({"experiment": doc, "routine": "r"}).encode())
        with urllib.request.urlopen(req) as r:
            err = json.loads(r.read())["error"]
        assert err.count("'") % 2 == 0 and err.endswith("'text'"), err
    finally:
        httpd.shutdown()

