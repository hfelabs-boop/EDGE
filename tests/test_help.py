"""Documentation, help search, tutorials and cookbook recipes."""
import re
from pathlib import Path

import pytest

from edge import help as hp
from edge.cli import main
from edge.model import Experiment
from edge.participant import VirtualParticipant
from edge.templates import TEMPLATES

DOCS = hp.docs_dir()


def test_generated_docs_are_up_to_date():
    assert hp.build_docs(check=True) == [], "run 'edge docs build' and commit the result"


def test_every_doc_link_and_anchor_resolves():
    """Broken links in the docs fail the build."""
    files = list(DOCS.glob("*.md")) + list((DOCS / "reference").glob("*.md")) + [DOCS.parent / "README.md"]
    anchors = {}
    for f in files:
        text = re.sub(r"```.*?```", "", f.read_text(encoding="utf-8"), flags=re.S)
        anchors[f.resolve()] = {hp.slug(m) for m in re.findall(r"^#{1,4}\s+(.*)$", text, flags=re.M)}
    problems = []
    for f in files:
        text = re.sub(r"```.*?```", "", f.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://")):
                continue
            path, _, anchor = target.partition("#")
            dest = (f.parent / path).resolve() if path else f.resolve()
            if not dest.exists():
                problems.append(f"{f.name}: missing file {target}")
            elif anchor and dest.suffix == ".md" and anchor not in anchors.get(dest, set()):
                problems.append(f"{f.name}: missing anchor {target}")
    assert not problems, "\n".join(problems)


def test_builder_help_links_point_to_real_sections():
    js = (Path(hp.__file__).parent / "builder" / "static" / "app.js").read_text()
    for topic, anchor in re.findall(r'helpLink\("([^"]+)", "([^"]+)"\)', js):
        if topic == "reference/components" or topic == "reference/devices":
            continue   # anchors are component/device names, checked below
        assert anchor in {s.anchor for s in hp.sections() if s.topic == topic}, (topic, anchor)
    comp_ref = hp.read_topic("reference/components")
    from edge.components import component_registry
    for name in component_registry():
        assert f"### {name}" in comp_ref


def test_topics_search_and_sections():
    ids = {t["id"] for t in hp.topics()}
    for must in ("README", "GETTING_STARTED", "TUTORIALS", "BUILDER_GUIDE", "COOKBOOK", "FAQ",
                 "EXPERIMENT_FORMAT", "reference/components", "reference/devices", "reference/cli"):
        assert must in ids
    top = hp.search("jitter isi")[0]
    assert top["topic"] == "COOKBOOK" and "Jitter" in top["section"]
    assert hp.search("practice criterion accuracy")[0]["section"].lower().startswith(("practice", "workflow"))
    assert any(r["topic"] == "tutorial" for r in hp.search("tutorial workflow practice", limit=20))
    assert "random.uniform" in hp.section_text("COOKBOOK", "jittered-inter-stimulus-interval")
    with pytest.raises(KeyError):
        hp.read_topic("no_such_topic")
    assert hp.read_topic("cookbook").startswith("# Cookbook")       # case-insensitive partial match


@pytest.mark.parametrize("tut", hp.tutorials(), ids=lambda t: t["id"])
def test_tutorials_are_valid(tut):
    assert hp.validate_tutorial(tut) == []
    start = tut.get("start")
    if start and start != "keep":
        exp = Experiment.from_dict(TEMPLATES[start])
        errors = [i for i in exp.validate() if i.level == "error" and "flow is empty" not in i.message]
        assert errors == []
    # every UI element a tutorial points at exists in the builder
    html = (Path(hp.__file__).parent / "builder" / "static" / "index.html").read_text()
    js = (Path(hp.__file__).parent / "builder" / "static" / "app.js").read_text()
    for st in tut["steps"]:
        target = st.get("target")
        if not target:
            continue
        for token in re.findall(r"[#.][\w-]+|\[data-[\w-]+", target):
            name = token[1:]
            assert name in html or name in js, f"{tut['id']}: selector part {token} not found in the builder"


def test_tutorial_start_templates_run(tmp_path):
    from tests.conftest import run_headless
    for name in ("tutorial_loops", "tutorial_practice", "tutorial_gaze", "tutorial_stroop"):
        summary, session, _ = run_headless(TEMPLATES[name], tmp_path, vp=VirtualParticipant(seed=1))
        assert not summary["errors"], name


def test_cli_help_and_tutorial(capsys):
    assert main(["help"]) == 0
    assert "COOKBOOK" in capsys.readouterr().out
    assert main(["help", "faq"]) == 0
    assert "TROUBLESHOOTING" in capsys.readouterr().out.upper()
    assert main(["help", "--first", "jitter"]) == 0
    assert "random.uniform" in capsys.readouterr().out
    assert main(["tutorial"]) == 0
    assert "first_experiment" in capsys.readouterr().out
    assert main(["tutorial", "workflow_practice", "--print"]) == 0
    assert "max_visits" in capsys.readouterr().out
    assert main(["docs", "build", "--check"]) == 0


def test_mcp_help_tools(tmp_path):
    pytest.importorskip("mcp")
    from tests.test_mcp import call
    from edge.mcp_server import create_server
    s = create_server(tmp_path)
    res = call(s, "search_help", query="EEG trigger codes")["results"]
    assert res and res[0]["topic"] in ("COOKBOOK", "DEVICES", "EXPERIMENT_FORMAT")
    page = call(s, "read_help", topic="COOKBOOK", section="a-break-every-40-trials")
    assert "trials.n % 40" in page["markdown"]
    assert len(call(s, "list_tutorials")["tutorials"]) >= 8


# ------------------------------------------------------------------ cookbook recipes really run
TRIAL_LIST = [{"word": "a", "answer": "f", "isi": 0.4, "is_practice": True, "target": "left",
               "left_img": "x.png", "right_img": "y.png"},
              {"word": "b", "answer": "j", "isi": 0.6, "is_practice": False, "target": "right",
               "left_img": "x.png", "right_img": "y.png"}]
RECIPES = {
    "jitter": {"routines": {"r": {"components": [
        {"id": "fix", "type": "fixation", "duration": "$random.uniform(0.4, 0.8)"},
        {"id": "w", "type": "text", "text": "$word", "start_after": "fix", "duration": "$isi"}]}}},
    "too_slow": {"routines": {"r": {"components": [
        {"id": "stim", "type": "text", "text": "$word"},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$answer", "duration": 1.5, "end_routine": True}]},
        "feedback": {"duration": 0.8, "components": [
            {"id": "fb", "type": "text", "text": "$'Too slow' if resp.keys is None else ('Correct' if resp.corr else 'Wrong')"}]}},
        "children": ["r", "feedback"]},
    "frames_and_start_after": {"routines": {"r": {"duration": 1, "components": [
        {"id": "stim", "type": "shape", "duration": 0.2},
        {"id": "mask", "type": "shape", "start_frame": 3, "duration_frames": 2},
        {"id": "tone", "type": "sound", "sound": 1000, "start_after": "stim"}]}}},
    "random_side_once": {"routines": {"r": {"duration": 0.2, "components": [
        {"id": "pick", "type": "variable", "set": {"side": "$random.choice([-1, 1])"}},
        {"id": "target", "type": "shape", "pos": "$[side * 300, 0]"}]}}},
    "breaks": {"routines": {"rest_break": {"duration": 0.1, "components": [{"id": "b", "type": "text", "text": "rest"}]},
                            "r": {"duration": 0.05, "components": [{"id": "t", "type": "text", "text": "$word"}]}},
               "children": [{"routine": "rest_break", "if": "$trials.n > 0 and trials.n % 3 == 0"}, "r"], "repeats": 4},
    "feedback_if_and_hint": {"routines": {"r": {
        "rules": [{"when": "$t > 3 and resp.keys is None", "do": [{"start": "hint"}]}],
        "components": [
            {"id": "hint", "type": "text", "text": "Press F or J", "pos": [0, -200], "start_if": "$False"},
            {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$answer", "end_routine": True},
            {"id": "fb", "type": "text", "text": "$'Correct' if resp.corr else 'Wrong'", "if": "$is_practice", "duration": 0.1}]}}},
    "score": {"variables": {"score": 0}, "routines": {"r": {"components": [
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$answer", "end_routine": True},
        {"id": "add", "type": "variable", "when": "end", "set": {"score": "$score + (resp.corr or 0)"}}]},
        "feedback": {"duration": 0.2, "components": [{"id": "s", "type": "text", "text": "$f'Score: {score}'"}]}},
        "children": ["r", "feedback"]},
    "click_images": {"routines": {"r": {"components": [
        {"id": "left", "type": "shape", "pos": [-300, 0], "size": [200, 200]},
        {"id": "right", "type": "shape", "pos": [300, 0], "size": [200, 200]},
        {"id": "click", "type": "mouse", "clickable": ["left", "right"], "correct": "$target", "end_routine": True}]}}},
    "slider": {"routines": {"r": {"components": [
        {"id": "rating", "type": "slider", "ticks": [1, 2, 3, 4, 5, 6, 7], "labels": ["not at all", "very much"],
         "end_routine": True}]}}},
    "fixcheck_and_aoi": {"devices": [{"id": "g", "type": "sim_eyetracker"}], "routines": {
        "fixcheck": {"duration": 5, "components": [
            {"id": "dot", "type": "shape", "shape": "circle", "radius": 8, "fill": "white"},
            {"id": "roi", "type": "gaze_roi", "radius": 60, "dwell": 0.3, "end_routine": True}]},
        "r": {"duration": 0.5, "components": [
            {"id": "left_img", "type": "shape", "pos": [-300, 0], "size": [400, 300]},
            {"id": "aoi_left", "type": "gaze_roi", "target": "left_img"},
            {"id": "window", "type": "shape", "shape": "circle", "radius": 120, "fill": "#ffffff30"},
            {"id": "follow", "type": "gaze_follow", "target": "window", "smoothing": 0.3}]}},
        "children": ["fixcheck", "r"]},
    "eeg_triggers": {"settings": {"markers": {"codes": {"standard": 1, "deviant": 2, "response": 10}}},
                     "devices": [{"id": "ttl", "type": "ttl_loopback"}],
                     "routines": {"tone": {"duration": 1, "components": [
                         {"id": "beep", "type": "sound", "sound": 1000, "marker": "standard"},
                         {"id": "resp", "type": "keyboard", "keys": ["space"], "response_marker": "response"}]}},
                     "children": ["tone"]},
}


@pytest.mark.parametrize("name", list(RECIPES))
def test_cookbook_recipe_runs(name, tmp_path):
    from tests.conftest import run_headless
    r = RECIPES[name]
    children = r.get("children") or ["r"]
    d = {"variables": r.get("variables", {}), "settings": r.get("settings", {}), "devices": r.get("devices", []),
         "routines": r["routines"],
         "flow": [{"loop": "trials", "conditions": TRIAL_LIST, "repeats": r.get("repeats", 1), "children": children}]}
    errors = [i for i in Experiment.from_dict(d, base_dir=tmp_path).validate() if i.level == "error"]
    assert errors == [], errors
    summary, session, _ = run_headless(d, tmp_path, vp=VirtualParticipant(seed=5))
    assert summary["errors"] == [] and session.data.trial_rows


def test_cookbook_workflow_and_counterbalance_recipes(tmp_path):
    from tests.conftest import run_headless
    (tmp_path / "easy.csv").write_text("word\neasy1\neasy2\n")
    (tmp_path / "hard.csv").write_text("word\nhard1\n")
    trial = {"components": [{"id": "resp", "type": "keyboard", "keys": ["f"], "correct": "f", "end_routine": True}]}
    d = {"routines": {"trial": trial, "main_trial": trial},
         "flow": [
             {"statemachine": "session", "start": "practice", "states": {
                 "practice": {"run": [{"loop": "practice_loop", "repeats": 3, "children": ["trial"]}], "max_visits": 3,
                              "next": [{"if": "$practice_loop.accuracy >= 0.8", "goto": "main"}, {"goto": "practice"}]},
                 "main": {"run": [{"loop": "blocks", "conditions": [{"block_file": "easy.csv"}, {"block_file": "hard.csv"}],
                                   "order": "latin_square", "children": [
                                       {"loop": "main_loop", "conditions": "$block_file", "order": "random",
                                        "stop_if": "$main_loop.n_correct >= 10", "children": ["main_trial"]}]}]}}},
             {"if": "$int(participant) % 2 == 0", "then": ["trial"], "else": ["main_trial"]}]}
    summary, session, _ = run_headless(d, tmp_path, vp=VirtualParticipant(seed=2, accuracy=1.0, respond_prob=1))
    assert summary["loops"]["session"]["path"] == ["practice", "main"]
    words = [r.get("word") for r in session.data.trial_rows if r["routine"] == "main_trial" and r.get("word")]
    assert sorted(words) == ["easy1", "easy2", "hard1"]
