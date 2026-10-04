import json
import zipfile

import pytest

from edge.editing import EditError, ExperimentDoc
from edge.model import Experiment
from edge.storage import (FORMAT_VERSION, ConflictError, DocumentError, export_bundle, import_bundle,
                          list_backups, load_document, referenced_files, restore_backup, save_document)


def test_atomic_save_backups_and_restore(tmp_path):
    p = tmp_path / "exp.yaml"
    fp1 = save_document(p, {"name": "v1", "routines": {}, "flow": []})
    assert list_backups(p) == []                       # first save: nothing to back up
    fp2 = save_document(p, {"name": "v2", "routines": {}, "flow": []}, expected_fingerprint=fp1)
    save_document(p, {"name": "v3", "routines": {}, "flow": []}, expected_fingerprint=fp2)
    assert [load_document(b["path"]).doc["name"] for b in list_backups(p)] == ["v2", "v1"]
    assert not list(tmp_path.glob(".exp.yaml.*.tmp"))   # no temp files left behind
    restore_backup(p)
    assert load_document(p).doc["name"] == "v2"
    restore_backup(p)
    assert load_document(p).doc["name"] == "v1"


def test_identical_save_makes_no_backup(tmp_path):
    p = tmp_path / "e.yaml"
    d = {"name": "x", "routines": {}, "flow": []}
    save_document(p, d)
    save_document(p, d)
    assert list_backups(p) == []


def test_conflict_detection(tmp_path):
    p = tmp_path / "exp.yaml"
    save_document(p, {"name": "a", "routines": {}, "flow": []})
    exp = Experiment.load(p)
    save_document(p, {"name": "changed elsewhere", "routines": {}, "flow": []})
    exp.name = "mine"
    with pytest.raises(ConflictError):
        exp.save()
    exp.save(check_conflicts=False)
    assert load_document(p).doc["name"] == "mine"


def test_friendly_syntax_errors(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("name: x\nroutines:\n  trial: [unclosed\nflow: []\n")
    with pytest.raises(DocumentError, match=r"line \d+, column \d+"):
        load_document(p)
    j = tmp_path / "bad.json"
    j.write_text('{"name": "x",\n "flow": [}')
    with pytest.raises(DocumentError, match="line 2"):
        load_document(j)
    n = tmp_path / "notexp.yaml"
    n.write_text("foo: 1\n")
    with pytest.raises(DocumentError, match="doesn't look like"):
        load_document(n)


def test_migration_of_old_code_component(tmp_path):
    p = tmp_path / "old.yaml"
    p.write_text("name: old\nroutines:\n  r:\n    components:\n"
                 "      - {id: c, type: code, begin_routine: 'x = 1', end_routine: 'y = 2'}\nflow: [r]\n")
    loaded = load_document(p)
    c = loaded.doc["routines"]["r"]["components"][0]
    assert c["on_begin"] == "x = 1" and c["on_end"] == "y = 2" and "end_routine" not in c
    assert loaded.doc["edge_format"] == FORMAT_VERSION and loaded.migrations


def test_newer_format_is_refused(tmp_path):
    p = tmp_path / "future.yaml"
    p.write_text(f"edge_format: {FORMAT_VERSION + 5}\nname: f\nroutines: {{}}\nflow: []\n")
    with pytest.raises(DocumentError, match="newer EDGE"):
        load_document(p)


def test_multiline_strings_are_readable(tmp_path):
    p = tmp_path / "e.yaml"
    save_document(p, {"name": "x", "routines": {"r": {"components": [
        {"id": "t", "type": "text", "text": "line one\nline two"}]}}, "flow": ["r"]})
    assert "text: |" in p.read_text()


def test_json_round_trip(tmp_path):
    p = tmp_path / "e.json"
    save_document(p, {"name": "j", "routines": {}, "flow": []})
    assert json.loads(p.read_text())["name"] == "j"


def test_bundle_round_trip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "stim").mkdir()
    (src / "stim" / "face.png").write_bytes(b"\x89PNG fake")
    (src / "conds.csv").write_text("img\nstim/face.png\n")
    save_document(src / "exp.yaml", {"name": "b", "routines": {"r": {"components": [
        {"id": "i", "type": "image", "image": "stim/face.png"},
        {"id": "s", "type": "sound", "sound": 440},
        {"id": "dyn", "type": "image", "image": "$img"}]}},
        "flow": [{"loop": "L", "conditions": "conds.csv", "children": ["r"]}]})
    assert referenced_files(load_document(src / "exp.yaml").doc) == {"stim/face.png", "conds.csv"}
    res = export_bundle(src / "exp.yaml", tmp_path / "b.edgez")
    assert sorted(res["files"]) == ["conds.csv", "stim/face.png"] and not res["missing"]
    with zipfile.ZipFile(tmp_path / "b.edgez") as z:
        assert "manifest.json" in z.namelist()
    out = import_bundle(tmp_path / "b.edgez", tmp_path / "dest")
    assert (tmp_path / "dest" / "stim" / "face.png").read_bytes() == b"\x89PNG fake"
    assert load_document(out).doc["name"] == "b"


# ------------------------------------------------------------------ editing API
def test_editing_api_builds_a_valid_experiment(tmp_path):
    doc = ExperimentDoc.new(tmp_path / "e.yaml", name="demo")
    doc.add_routine("trial")
    doc.add_component("trial", "text", {"text": "$word", "duration": 1})
    doc.add_component("trial", "keyboard", {"keys": ["f", "j"], "end_routine": True, "correct": "$ans"})
    doc.add_loop("trials", children=["trial"], order="random", repeats=2)
    doc.set_conditions("trials", rows=[{"word": "a", "ans": "f"}, {"word": "b", "ans": "j"}],
                       file="c.csv", write_file=True)
    doc.add_routine("bye", duration=1, add_to_flow=True)
    doc.add_component("bye", "text", {"text": "thanks"})
    doc.add_device("sim_eyetracker", "et")
    doc.update_settings({"window": {"background": "#333333"}, "data": {"exports": ["csv", "xlsx"]}})
    doc.save()
    assert [i for i in doc.validate() if i["level"] == "error"] == []
    assert (tmp_path / "c.csv").read_text().startswith("word,ans")
    out = doc.outline()
    assert "loop trials [c.csv, random, repeats 2]" in out and "resp (keyboard" in out
    exp = Experiment.load(tmp_path / "e.yaml")
    assert exp.settings["window"]["background"] == "#333333"


def test_editing_errors_are_helpful(tmp_path):
    doc = ExperimentDoc.new(tmp_path / "e.yaml")
    doc.add_routine("trial")
    with pytest.raises(EditError, match="Valid:.*color"):
        doc.add_component("trial", "text", {"colour": "red"})
    with pytest.raises(EditError, match="Available:"):
        doc.add_component("trial", "txt")
    with pytest.raises(EditError, match="Existing routines: trial"):
        doc.add_component("trail", "text")
    with pytest.raises(EditError, match="identifier"):
        doc.add_routine("my trial")


def test_rename_and_wrap(tmp_path):
    doc = ExperimentDoc.new(tmp_path / "e.yaml")
    for r in ("intro", "trial", "feedback", "end"):
        doc.add_routine(r, add_to_flow=True)
    doc.add_loop("trials", children=["trial", "feedback"], wrap=True, repeats=3)
    assert doc.doc["flow"][0] == "intro" and doc.doc["flow"][1]["loop"] == "trials" and doc.doc["flow"][2] == "end"
    assert doc.doc["flow"][1]["children"] == ["trial", "feedback"]
    doc.rename_routine("trial", "main")
    assert doc.doc["flow"][1]["children"][0] == "main" and "main" in doc.doc["routines"]
    doc.add_component("main", "shape", cid="box")
    doc.add_component("main", "gaze_roi", {"target": "box"}, cid="roi")
    doc.update_component("main", "box", new_id="square")
    assert doc.component("main", "roi")["target"] == "square"
    doc.remove_from_flow("trials")
    assert doc.doc["flow"] == ["intro", "main", "feedback", "end"]
