"""Assistant / MCP edits that put an item's settings beside the operation, and the triangle shape."""
from __future__ import annotations

import pytest

from edge.editing import ExperimentDoc, apply_operations
from edge.engine import run_experiment
from edge.model import Experiment


@pytest.fixture
def doc(tmp_path):
    return ExperimentDoc.new(tmp_path / "e" / "e.yaml", name="e")


def test_settings_beside_the_operation_go_into_properties(doc):
    # exactly what a local model sent: start, duration, shape, units at the top level
    res = apply_operations(doc, [
        {"op": "add_routine", "rid": "tri", "add_to_flow": True},
        {"op": "add_component", "rid": "tri", "ctype": "shape", "start": 0, "duration": 2,
         "shape": "triangle", "units": "px"}])
    assert res["ok"], res
    comp = doc.routine("tri")["components"][0]
    assert comp["type"] == "shape" and comp["shape"] == "triangle" and comp["duration"] == 2 and comp["units"] == "px"


def test_explicit_properties_win_and_are_merged(doc):
    res = apply_operations(doc, [
        {"op": "add_routine", "rid": "a"},
        {"op": "add_component", "rid": "a", "ctype": "text", "cid": "msg", "height": 40,
         "properties": {"text": "hi", "height": 60}}])
    assert res["ok"], res
    c = doc.component("a", "msg")
    assert c["text"] == "hi" and c["height"] == 60


def test_update_component_settings_beside_the_operation(doc):
    apply_operations(doc, [{"op": "add_routine", "rid": "a"},
                           {"op": "add_component", "rid": "a", "ctype": "shape", "cid": "s"}])
    res = apply_operations(doc, [{"op": "update_component", "rid": "a", "cid": "s", "shape": "triangle", "fill": "red"}])
    assert res["ok"], res
    assert doc.component("a", "s")["shape"] == "triangle" and doc.component("a", "s")["fill"] == "red"


def test_a_setting_the_item_does_not_have_is_still_refused_clearly(doc):
    res = apply_operations(doc, [{"op": "add_routine", "rid": "a"},
                                 {"op": "add_component", "rid": "a", "ctype": "shape", "colour": "red"}])
    assert not res["ok"]
    assert "shape has no property colour" in res["error"] and "fill" in res["error"]
    assert "a" not in doc.routines            # all or nothing


def test_triangle_validates_and_runs(tmp_path):
    exp = Experiment.from_dict({
        "name": "tri",
        "routines": {"tri": {"components": [
            {"id": "t", "type": "shape", "shape": "triangle", "size": [200, 150], "fill": "orange", "duration": 0.2}]}},
        "flow": ["tri"]}, base_dir=tmp_path)
    assert not [i for i in exp.validate() if i.level == "error"]
    summary = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    assert not summary.get("errors")
