"""Regression tests for the C2 fixes: the design wizard, the templates and safe storage."""
import copy
import csv
import json
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from edge.cli import main
from edge.engine import run_experiment
from edge.model import Experiment
from edge.storage import (DocumentError, carry_comments, dumps, export_bundle, import_bundle, load_document, loads,
                          save_document)
from edge.templates import TEMPLATES, write_template
from edge.wizard import WizardError, build_experiment, estimate, read_answers

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def dry_run(doc, tmp_path):
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    assert [str(i) for i in exp.validate() if i.level == "error"] == []
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    assert not s["errors"]
    data = Path(s["data_dir"])
    rows = list(csv.DictReader((data / "trials.csv").open(encoding="utf-8")))
    events = [json.loads(line) for line in (data / "events.jsonl").read_text().splitlines() if line.strip()]
    return rows, events


def build(answers):
    notes = []
    return build_experiment(answers, notes), notes


def evaluate(expr, **names):
    return eval(expr.lstrip("$"), {}, {k: SimpleNamespace(**v) for k, v in names.items()})


# ---------------------------------------------------------------- wizard#0, wizard#1: sounds
def test_listen_only_sound_trials_last_as_long_as_written(tmp_path):
    doc, _ = build({"stimulus": {"kind": "sound"}, "response": {"kind": "none"}})
    assert doc["routines"]["trial"]["duration"] == 2.5
    rows, _ = dry_run(doc, tmp_path)
    lengths = [float(r["routine_duration"]) for r in rows if r["routine"] == "trial"]
    assert len(lengths) == 2 and all(abs(x - 2.5) < 0.05 for x in lengths)      # not 0.85 s (tone + fixation)


@pytest.mark.parametrize("kind", ["word", "picture", "sound", "shape"])
def test_every_stimulus_kind_sends_a_marker(kind):
    doc, _ = build({"stimulus": {"kind": kind}})
    stim = next(c for c in doc["routines"]["trial"]["components"] if c["id"] == kind)
    assert stim["marker"] == "$f'stim_{condition}'"


def test_sound_onsets_reach_the_eeg(tmp_path):
    doc, _ = build({"stimulus": {"kind": "sound"}, "response": {"kind": "none"}, "devices": ["sim_eeg"]})
    _, events = dry_run(doc, tmp_path)
    assert sorted(e["label"] for e in events if e["label"].startswith("stim_")) == ["stim_high", "stim_low"]


# ---------------------------------------------------------------- wizard#2, wizard#14: key names
def test_key_names_are_what_the_keyboard_sends():
    doc, _ = build({"stimulus": {"kind": "word", "items": [{"stimulus": "LEFT", "correct": "F", "condition": "l"},
                                                           {"stimulus": "RIGHT", "correct": " J", "condition": "r"}]},
                    "response": {"kind": "keys", "keys": ["F", "J"]}})
    resp = doc["routines"]["trial"]["components"][-1]
    assert resp["keys"] == ["f", "j"]
    assert [r["correct"] for r in doc["flow"][1]["conditions"]] == ["f", "j"]
    doc, _ = build({"stimulus": {"items": [{"stimulus": "GO", "correct": "Space"}]}})
    assert doc["routines"]["trial"]["components"][-1]["keys"] == ["space"]
    with pytest.raises(WizardError, match=r"row 1 \(stimulus\): 'correct key' is not a key name.*header"):
        build({"stimulus": {"items": [{"stimulus": "stimulus", "correct": "correct key", "condition": "condition"},
                                      {"stimulus": "A", "correct": "f"}]}})


def test_a_row_without_a_correct_key_is_a_no_go_row():
    doc, notes = build({"stimulus": {"kind": "word", "items": [{"stimulus": "GO", "correct": "space", "condition": "go"},
                                                               {"stimulus": "STOP", "condition": "nogo"}]}})
    assert [r["correct"] for r in doc["flow"][1]["conditions"]] == ["space", ""]
    assert any("No correct key for STOP" in n for n in notes)


# ---------------------------------------------------------------- wizard#3: consent
def _declining(doc):
    from edge.survey_library import instrument
    doc = copy.deepcopy(doc)
    qs = instrument("consent")["questions"]
    for q in qs:
        if q["id"] == "consent":
            q["test_answer"] = "no"
    doc["routines"]["consent"]["components"][0]["questions"] = qs
    return doc


def test_declining_consent_ends_the_study(tmp_path):
    doc, _ = build({"questionnaires": ["consent", "demographics"]})
    assert doc["flow"][0] == "consent" and doc["flow"][1]["if"] == "$consent_form.consent == 'yes'"
    rows, _ = dry_run(_declining(doc), tmp_path / "no")
    assert [r["routine"] for r in rows] == ["consent", "declined"]
    rows, _ = dry_run(doc, tmp_path / "yes")        # agreeing runs everything
    assert [r["routine"] for r in rows][:3] == ["consent", "about_you", "instructions"]
    assert sum(r["routine"] == "trial" for r in rows) == 2


# ---------------------------------------------------------------- wizard#4, wizard#5: instructions and feedback
def test_go_no_go_instructions_and_feedback():
    doc, _ = build({"stimulus": {"kind": "word", "items": [{"stimulus": "GO", "correct": "space", "condition": "go"},
                                                           {"stimulus": "NOGO", "correct": "", "condition": "nogo"}]},
                    "feedback": True})
    text = doc["routines"]["instructions"]["components"][0]["text"]
    assert "Press SPACE for go" in text and "Do not press anything for nogo" in text and "Press  for" not in text
    fb = doc["routines"]["feedback"]["components"][0]["text"]
    assert evaluate(fb, response={"corr": 1, "keys": None}) == "Correct!"        # a correct withhold
    assert evaluate(fb, response={"corr": 0, "keys": None}) == "Too slow"
    assert evaluate(fb, response={"corr": 0, "keys": "space"}) == "Wrong"


def test_instructions_only_pair_keys_with_conditions_that_have_one_key():
    flanker = [{"stimulus": "<<<<<", "correct": "f", "condition": "congruent"},
               {"stimulus": ">>>>>", "correct": "j", "condition": "congruent"},
               {"stimulus": "<<><<", "correct": "j", "condition": "incongruent"},
               {"stimulus": ">><>>", "correct": "f", "condition": "incongruent"}]
    doc, notes = build({"stimulus": {"kind": "word", "items": flanker}})
    text = doc["routines"]["instructions"]["components"][0]["text"]
    assert "congruent" not in text and "Respond with F or J" in text
    assert any("write that into the instructions" in n for n in notes)
    doc, notes = build({"stimulus": {"kind": "word", "items": [
        {"stimulus": "cat", "correct": "f", "condition": "animal"}, {"stimulus": "dog", "correct": "f", "condition": "animal"},
        {"stimulus": "car", "correct": "j", "condition": "object"}]}})
    text = doc["routines"]["instructions"]["components"][0]["text"]
    assert "Press F for animal" in text and "Press J for object" in text and not notes


# ---------------------------------------------------------------- wizard#7, wizard#8, wizard#12: answers that can't work
@pytest.mark.parametrize("answers, words", [
    ({"timing": {"response_deadline": 0}}, "Time limit to respond must be more than 0 seconds"),
    ({"timing": {"fixation": -1}}, "Fixation time can't be negative"),
    ({"timing": {"iti": -0.5}}, "Pause between trials can't be negative"),
    ({"timing": {"stimulus_duration": 0}}, "leave it empty to show the stimulus until the response"),
    ({"practice": {"mode": "until", "criterion": 80}}, "proportion between 0 and 1, e.g. 0.8"),
    ({"practice": {"mode": "until", "criterion": 0}}, "proportion between 0 and 1"),
    ({"practice": {"mode": "until", "max_rounds": 0}}, "practice rounds must be at least 1"),
    ({"blocks": {"count": "two"}}, 'Number of blocks must be a whole number (you gave "two")'),
    ({"response": {"kind": "rating", "ticks": "seven"}}, "Points on the rating scale must be a whole number"),
    ({"practice": {"mode": "until", "max_rounds": "three"}}, "must be a whole number"),
    ({"response": {"kind": "rating", "ticks": 1}}, "at least 2"),
    ({"devices": ["eyetracker"]}, "unknown device type 'eyetracker' (did you mean sim_eyetracker?)"),
    ({"blocks": {"order": "shuffled"}}, "unknown order 'shuffled'"),
    ({"stimulus": {"kind": "word", "items": []}}, "add at least one stimulus"),
    ({"stimulus": "word"}, "the 'stimulus' answer must be a set of named answers"),
])
def test_answers_that_cannot_work_are_refused_in_plain_words(answers, words):
    with pytest.raises(WizardError) as e:
        build_experiment(answers)
    assert words in str(e.value)


def test_answers_must_be_named_answers():
    with pytest.raises(WizardError, match="set of named answers"):
        build_experiment("word")


def test_answers_files_json_or_yaml_with_located_errors(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"stimulus": {"kind": "word",}}')
    with pytest.raises(WizardError, match=r"bad.json is not valid JSON \(line 1, column 30\)"):
        read_answers(bad)
    assert main(["wizard", str(tmp_path / "x"), "--answers", str(bad)]) == 2
    out = capsys.readouterr()
    assert "not valid JSON" in out.out and "Traceback" not in out.out + out.err
    good = tmp_path / "answers.yaml"
    good.write_text("name: from yaml\nstimulus:\n  kind: shape\n")
    assert main(["wizard", str(tmp_path / "y"), "--answers", str(good)]) == 0
    assert (tmp_path / "y" / "from_yaml.yaml").exists()
    nums = tmp_path / "n.json"
    nums.write_text('{"blocks": {"count": "two"}}')
    assert main(["wizard", str(tmp_path / "z"), "--answers", str(nums)]) == 2
    assert "Number of blocks must be a whole number" in capsys.readouterr().out


# ---------------------------------------------------------------- wizard#13: devices, orders, questionnaires
def test_questionnaires_chosen_twice_are_asked_once(tmp_path):
    doc, notes = build({"questionnaires": ["tipi", "tipi"]})
    assert doc["routines"]["questionnaires"]["components"][0]["questions"] == [{"instrument": "tipi"}]
    assert any("tipi was chosen twice" in n for n in notes)
    assert not [i for i in Experiment.from_dict(doc, base_dir=tmp_path).validate() if i.level == "error"]


# ---------------------------------------------------------------- wizard#19, wizard#20: response boxes, eye trackers
def test_buttons_answer_with_a_response_box(tmp_path):
    doc, notes = build({"response": {"kind": "buttons"}, "feedback": True})
    box = doc["devices"][0]
    assert box["type"] == "sim_inputs" and box["options"]["inputs"] == {"1": "left", "2": "right"}
    resp = doc["routines"]["trial"]["components"][-1]
    assert resp["type"] == "device_response" and resp["device"] == box["id"] and resp["inputs"] == ["left", "right"]
    assert any("simulated response box" in n for n in notes)
    rows, _ = dry_run(doc, tmp_path)
    trials = [r for r in rows if r["routine"] == "trial"]
    assert trials and all(r["response.input"] in ("left", "right") and r["response.device"] == box["id"]
                          and r["response.corr"] in ("0", "1") for r in trials)
    doc, notes = build({"devices": ["serial_inputs"]})          # a box, but key presses: say so
    assert doc["routines"]["trial"]["components"][-1]["type"] == "keyboard"
    assert any("choose the response 'buttons'" in n for n in notes)


def test_eye_trackers_from_the_wizard_calibrate():
    doc, _ = build({"devices": ["tobii", "sim_eeg"]})
    assert doc["devices"] == [{"id": "eyetracker", "type": "tobii", "calibrate": True}, {"id": "eeg", "type": "sim_eeg"}]


# ---------------------------------------------------------------- wizard#22: practice-until estimates
def test_estimate_gives_the_range_when_practice_can_repeat(tmp_path):
    doc, _ = build({"practice": {"mode": "until", "criterion": 0.9, "max_rounds": 3}})
    est = estimate(doc, tmp_path)
    assert est["trials"] == 4 and est["trials_max"] == 8
    assert est["text"].startswith("4 to 8 trials") and "practice may run up to 3×" in est["text"]
    assert "trials_max" not in estimate(build({"practice": {"mode": "once"}})[0], tmp_path)


# ---------------------------------------------------------------- wizard#23, mcp#31: pictures and sounds
def test_cli_wizard_says_what_it_made_and_what_is_missing(tmp_path, capsys):
    a = tmp_path / "pic.json"
    a.write_text(json.dumps({"stimulus": {"kind": "picture", "items": [{"stimulus": "faces/happy.jpg", "correct": "f"},
                                                                       {"stimulus": "sad.png", "correct": "j"}]}}))
    assert main(["wizard", str(tmp_path / "pic"), "--answers", str(a)]) == 0
    out = capsys.readouterr().out
    assert "Made 2 stand-in pictures (faces/happy.jpg, images/sad.png)" in out
    assert (tmp_path / "pic" / "faces" / "happy.jpg").read_bytes()[:3] == b"\xff\xd8\xff"     # a real JPEG
    assert (tmp_path / "pic" / "images" / "sad.png").read_bytes()[:4] == b"\x89PNG"
    a.write_text(json.dumps({"stimulus": {"kind": "sound", "items": [{"stimulus": "beep.wav", "correct": "f"},
                                                                     {"stimulus": "boop.wav", "correct": "j"}]}}))
    assert main(["wizard", str(tmp_path / "wav"), "--answers", str(a)]) == 0
    assert "Put the sound files beep.wav, boop.wav in" in capsys.readouterr().out


def test_bare_picture_names_go_in_images_as_the_description_says(tmp_path):
    from edge.wizard import prepare_files
    doc, _ = build({"stimulus": {"kind": "picture", "items": [{"stimulus": "cat.png", "correct": "f"}]}})
    assert doc["flow"][1]["conditions"][0]["stimulus"] == "images/cat.png"
    assert "images/ folder" in doc["description"]
    save_document(tmp_path / "f.yaml", doc)
    assert prepare_files(doc, tmp_path) and (tmp_path / "images" / "cat.png").exists()
    assert not [i for i in Experiment.load(tmp_path / "f.yaml").validate() if i.level == "error"]


def test_mcp_and_builder_return_the_notes(tmp_path):
    from edge.builder.server import BuilderApp
    out = BuilderApp(tmp_path).wizard({"stimulus": {"kind": "picture"}, "feedback": True,
                                       "response": {"kind": "rating"}}, "b/b.yaml")
    assert out["ok"] and any("No feedback" in n for n in out["notes"]) and any("stand-in" in n for n in out["notes"])
    pytest.importorskip("mcp")
    import asyncio
    from edge.mcp_server import create_server
    res = asyncio.run(create_server(tmp_path).call_tool("create_from_wizard", {
        "path": "w/w.yaml", "answers": {"stimulus": {"kind": "sound", "items": [{"stimulus": "a.wav", "correct": "f"}]}}}))
    r = res[1] if isinstance(res, tuple) else json.loads(res[0].text)
    r = r.get("result", r)
    assert r["ok"] and any("a.wav" in n for n in r["notes"])


# ---------------------------------------------------------------- wizard#24, wizard#27: quiet changes are said
def test_example_stimuli_are_announced():
    _, notes = build({"stimulus": {"kind": "word"}})
    assert any("examples LEFT and RIGHT were used" in n for n in notes)
    _, notes = build({"stimulus": {"kind": "word", "items": [{"stimulus": "A", "correct": "f"}]}})
    assert not any("examples" in n for n in notes)


def test_adjusted_answers_are_explained_and_names_stay_readable():
    _, notes = build({"feedback": True, "response": {"kind": "rating"}})
    assert any(n.startswith("No feedback") for n in notes)
    doc, notes = build({"practice": {"mode": "until"}, "response": {"kind": "mouse"}})
    assert any("Practice runs once" in n for n in notes)
    _, notes = build({"blocks": {"count": 100, "repeats": 100}})
    assert any("hours: check the numbers of blocks and repeats" in n for n in notes)
    doc, _ = build({"name": "Stroop-Aufgabe für Ältere"})
    assert doc["name"] == "stroop_aufgabe_fuer_aeltere"
    doc, _ = build({"stimulus": {"kind": "sound"}, "response": {"kind": "none"}})
    assert "none responses" not in doc["description"] and "sounds" in doc["description"]


# ---------------------------------------------------------------- wizard#25, docs#16: templates
def test_every_template_says_what_it_is_in_plain_words():
    from edge.templates import public_templates
    for name, t in public_templates().items():
        assert len(t.get("description", "")) > 40, name
    assert "rectangle" in TEMPLATES["freeview_eyetracking"]["description"]


def test_templates_and_files_have_no_shared_parts(tmp_path):
    p = write_template("tutorial_practice", tmp_path)
    assert "&id" not in p.read_text() and "*id" not in p.read_text()
    doc = load_document(p).doc
    doc["routines"]["main_trial"]["components"][0]["duration"] = 0.25
    assert doc["routines"]["trial"]["components"][0]["duration"] == 0.5
    shared = loads("a: &x {components: [{id: f, duration: 0.5}]}\nb: *x\n")
    shared["a"]["components"][0]["duration"] = 1
    assert shared["b"]["components"][0]["duration"] == 0.5          # an alias in the file is a copy, not a link
    d = {"x": 1}
    assert "&id" not in dumps({"a": d, "b": d})


# ---------------------------------------------------------------- cli#12, install#12: never over an existing file
def test_new_never_replaces_an_existing_experiment(tmp_path, capsys):
    assert main(["new", "blank", str(tmp_path)]) == 0
    first = tmp_path / "my_experiment.yaml"
    first.write_text(first.read_text() + "# my edits\n")
    assert main(["new", "blank", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert first.read_text().endswith("# my edits\n")
    assert (tmp_path / "my_experiment_2.yaml").exists() and "already exists there" in out


# ---------------------------------------------------------------- docs#15: keys given twice
def test_a_key_given_twice_is_an_error_with_both_lines(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text("name: dup\nroutines:\n  r:\n    duration: 1\n    components: []\nflow:\n"
                 "  - loop: trials\n    max_repeat: {answer: 2}\n    max_repeat: {kind: {deviant: 1}}\n    children: [r]\n")
    with pytest.raises(DocumentError, match=r"'max_repeat' is given twice \(lines 8 and 9\)"):
        load_document(p)
    assert main(["validate", str(p)]) != 0


# ---------------------------------------------------------------- mcp#23: comments survive saves
def test_saving_keeps_the_researchers_comments(tmp_path):
    p = tmp_path / "stroop.yaml"
    shutil.copy(EXAMPLES / "stroop" / "stroop.yaml", p)
    doc = load_document(p).doc
    doc["settings"]["window"]["background"] = "#222222"
    save_document(p, doc)
    text = p.read_text()
    assert "# What this experiment measures. Summarised per participant" in text
    assert text.index("# What this experiment measures") < text.index("\nmeasures:")
    assert load_document(p).doc["settings"]["window"]["background"] == "#222222"


def test_comments_follow_their_item_and_never_change_the_content():
    old = ("# header\n\nname: x   # the name\nroutines:\n  a:\n    components:\n      # the cross\n"
           "      - {id: fix, type: fixation}   # cross\n      - id: code\n        type: code\n"
           "        on_begin: |\n          # python, not a YAML comment\n          x = 1\n  b:  # gone\n"
           "    components: []\nflow: [a]\n")
    d = loads(old)
    d["routines"]["a"]["components"].insert(0, {"id": "new", "type": "text", "text": "hi # not a comment"})
    del d["routines"]["b"]
    new = dumps(d)
    text = carry_comments(old, new)
    assert yaml.safe_load(text) == yaml.safe_load(new)
    assert text.startswith("# header\n\nname: x  # the name\n") and "# gone" not in text
    lines = text.splitlines()
    assert lines[lines.index("    # the cross") + 1].strip() == "- id: fix  # cross"
    assert carry_comments("a: 1  # c\n", "a: |\n  two\n  lines\n") .count("# c") <= 1


# ---------------------------------------------------------------- mcp#24, cli#16, install#13: permissions
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_saved_files_keep_their_permissions_and_new_ones_follow_the_umask(tmp_path):
    old = os.umask(0o022)
    try:
        p = tmp_path / "e.yaml"
        save_document(p, {"name": "e", "routines": {}, "flow": []})
        assert stat.S_IMODE(p.stat().st_mode) == 0o644
        p.chmod(0o640)
        save_document(p, {"name": "e2", "routines": {}, "flow": []})
        assert stat.S_IMODE(p.stat().st_mode) == 0o640
        assert stat.S_IMODE(write_template("blank", tmp_path / "t").stat().st_mode) == 0o644
    finally:
        os.umask(old)


# ---------------------------------------------------------------- mcp#20, cli#12, cli#17, cli#23: bundles
def _stroop_bundle(tmp_path):
    shutil.copytree(EXAMPLES / "stroop", tmp_path / "src")
    return Path(export_bundle(tmp_path / "src" / "stroop.yaml", tmp_path / "stroop.edgez")["bundle"])


def test_bundles_carry_the_file_as_written(tmp_path):
    b = _stroop_bundle(tmp_path)
    out = import_bundle(b, tmp_path / "there")
    assert out.read_text() == (EXAMPLES / "stroop" / "stroop.yaml").read_text()       # comments and all


def test_unbundling_never_replaces_changed_files_silently(tmp_path):
    b = _stroop_bundle(tmp_path)
    dest = tmp_path / "there"
    import_bundle(b, dest)
    import_bundle(b, dest)                      # the same files again: fine
    (dest / "stroop.csv").write_text((dest / "stroop.csv").read_text() + "MY,EDITED,ROW,x\n")
    with pytest.raises(DocumentError, match="already has stroop.csv.*Nothing was unpacked"):
        import_bundle(b, dest)
    assert "MY,EDITED,ROW" in (dest / "stroop.csv").read_text()
    assert main(["unbundle", str(b), str(dest)]) == 2
    import_bundle(b, dest, overwrite=True)      # on request: replaced, the edited one kept as a backup
    assert "MY,EDITED" not in (dest / "stroop.csv").read_text()
    assert any("MY,EDITED" in f.read_text() for f in (dest / ".edge" / "backups" / "stroop.csv").iterdir())


def test_an_unsafe_bundle_writes_nothing(tmp_path):
    b = _stroop_bundle(tmp_path)
    evil = tmp_path / "evil.edgez"
    with zipfile.ZipFile(b) as z, zipfile.ZipFile(evil, "w") as out:
        for info in z.infolist():
            out.writestr(info, z.read(info))
        out.writestr("files/../escaped.txt", "x")
    with pytest.raises(DocumentError, match="not a safe bundle.*Nothing was unpacked"):
        import_bundle(evil, tmp_path / "dest")
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "dest").exists() or not any((tmp_path / "dest").iterdir())
