"""`if:` on a trial list, and trial lists whose file comes from an outer list's column."""
from __future__ import annotations

import json

from edge.engine import run_experiment
from edge.model import Experiment


def _exp(tmp_path, practice_if):
    (tmp_path / "practice.csv").write_text("word\nA\nB\n")
    return Experiment.from_dict({
        "name": "e", "variables": {"want_practice": False},
        "routines": {"t": {"components": [{"id": "w", "type": "text", "text": "$word", "duration": 0.05}]}},
        "flow": [{"loop": "practice", "if": practice_if, "conditions": "practice.csv", "children": ["t"]}],
    }, base_dir=tmp_path)


def test_if_false_skips_the_trial_list(tmp_path):
    exp = _exp(tmp_path, "$want_practice")
    assert not [i for i in exp.validate() if i.level == "error"]
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rows = [json.loads(x) for x in open(f"{s['data_dir']}/trials.jsonl")]
    assert not any(r.get("routine") == "t" for r in rows)


def test_if_true_runs_it_and_round_trips(tmp_path):
    exp = _exp(tmp_path, "$not want_practice")
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rows = [json.loads(x) for x in open(f"{s['data_dir']}/trials.jsonl")]
    assert sum(r.get("routine") == "t" for r in rows) == 2
    assert exp.to_dict()["flow"][0]["if"] == "$not want_practice"


def test_bad_if_on_a_trial_list_is_reported(tmp_path):
    issues = _exp(tmp_path, "$want_practice ==").validate()
    assert any(i.where.endswith(".if") and i.level == "error" for i in issues)
    issues = _exp(tmp_path, "$wnat_practice").validate()
    assert any(i.where.endswith(".if") and "wnat_practice" in i.message for i in issues)


def test_estimate_counts_trial_list_files_named_by_a_column(tmp_path):
    from edge.wizard import estimate_experiment
    (tmp_path / "blocks.csv").write_text("block_file\nblock_a.csv\nblock_b.csv\n")
    (tmp_path / "block_a.csv").write_text("word\nRED\nBLUE\nGREEN\n")
    (tmp_path / "block_b.csv").write_text("word\nONE\nTWO\nTHREE\n")
    exp = Experiment.from_dict({
        "name": "cb", "routines": {"t": {"components": [{"id": "w", "type": "text", "text": "$word", "duration": 0.5}]}},
        "flow": [{"loop": "blocks", "conditions": "blocks.csv",
                  "children": [{"loop": "trials", "conditions": "$block_file", "children": ["t"]}]}]}, base_dir=tmp_path)
    est = estimate_experiment(exp)
    assert est["trials"] == 6 and est["seconds"] == 3.0
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rows = [json.loads(x) for x in open(f"{s['data_dir']}/trials.jsonl")]
    assert sum(r.get("routine") == "t" for r in rows) == 6


def test_a_trial_list_that_runs_again_counts_from_zero(tmp_path):
    exp = Experiment.from_dict({
        "name": "e",
        "routines": {"t": {"components": [{"id": "w", "type": "text", "text": "$f'{show.n}'", "duration": 0.05},
                                          {"id": "v", "type": "variable", "set": {"seen": "$show.n"}}]}},
        "flow": [{"loop": "outer", "repeats": 2, "children": [
            {"loop": "show", "conditions": [{"x": 1}, {"x": 2}, {"x": 3}], "children": ["t"]}]}]}, base_dir=tmp_path)
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rows = [json.loads(x) for x in open(f"{s['data_dir']}/trials.jsonl")]
    seen = [r.get("v.seen", r.get("seen")) for r in rows if r.get("routine") == "t"]
    assert seen == [0, 1, 2, 0, 1, 2], seen
