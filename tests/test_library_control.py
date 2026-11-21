"""Task library, group "control": Stroop family, numerical Stroop, Simon, negative priming, Navon, task
switching, multitasking, PRP, DCCS and the WCST-inspired card sort.

For every task: the experiment validates with no errors or warnings, a test run (dry run) finishes without
errors, every declared outcome measure appears in measures.csv with data, and meta.yaml is complete.
A few paradigm-specific checks make sure the logic that defines the conditions does what it says.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

from edge.cli import main
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "edge" / "library" / "tasks"
GROUP = ["stroop", "stroop_de", "stroop_en", "stroop_phone", "numerical_stroop", "numerical_stroop_touch",
         "simon", "touch_simon", "negative_priming", "navon", "taskswitching", "taskswitching_cued",
         "multitasking", "prp", "dccs", "wcst"]
CATEGORIES = {"Attention", "Inhibition and conflict", "Cognitive control", "Working memory", "Vigilance",
              "Decision making", "Language", "Social and implicit", "Perception and motor", "Problem solving"}
INPUTS = {"keyboard", "mouse", "touch", "keyboard+mouse"}
REQUIRED = ["id", "title", "category", "summary", "description", "measures", "duration_min", "input",
            "languages", "references", "see_also"]


def _run(task: str, tmp: Path, participant: str = "1") -> Path:
    """Copy the task to tmp, dry-run it, return the session folder."""
    dst = tmp / task
    if not dst.exists():
        shutil.copytree(TASKS / task, dst)
    assert main(["run", str(dst / f"{task}.yaml"), "--dry-run", "-p", participant]) == 0
    sessions = sorted(p.parent for p in (dst / "data").rglob("session.json"))
    assert sessions, "the test run made a session folder"
    return sessions[-1]


def _wide(session: Path) -> list[dict]:
    return list(csv.DictReader((session / "trials_wide.csv").open(encoding="utf-8-sig")))


@pytest.mark.parametrize("task", GROUP)
def test_meta_complete(task):
    meta = yaml.safe_load((TASKS / task / "meta.yaml").read_text(encoding="utf-8"))
    for key in REQUIRED:
        assert meta.get(key), f"{task}/meta.yaml: '{key}' is missing or empty"
    assert meta["id"] == task
    assert meta["category"] in CATEGORIES
    assert meta["input"] in INPUTS
    assert isinstance(meta["measures"], list) and all(isinstance(m, str) for m in meta["measures"])
    assert isinstance(meta["languages"], list) and isinstance(meta["references"], list)
    assert 1 <= float(meta["duration_min"]) <= 15
    url = meta["see_also"]["psytoolkit"]
    assert url == f"https://www.psytoolkit.org/experiment-library/{task}.html"
    if meta.get("variant_of"):
        assert (TASKS / meta["variant_of"] / "meta.yaml").exists(), "variant_of names another library task"


@pytest.mark.parametrize("task", GROUP)
def test_validates_cleanly(task):
    exp = Experiment.load(TASKS / task / f"{task}.yaml")
    issues = [i for i in exp.validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))
    assert exp.name == task
    assert any(m.get("role", "outcome") == "outcome" for m in (exp.measures or [])), "declares outcome measures"


@pytest.mark.parametrize("task", GROUP)
def test_dry_run_and_measures(task, tmp_path):
    session = _run(task, tmp_path)
    info = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors"), info.get("errors")
    exp = Experiment.load(TASKS / task / f"{task}.yaml")
    rows = list(csv.DictReader((session / "measures.csv").open(encoding="utf-8-sig")))
    overall = {r["measure"]: r for r in rows if all(r.get(k) == "(all)" for k in r if k not in (
        "participant", "session", "measure", "label", "role", "column", "summary", "n", "missing", "value", "units"))}
    for m in exp.measures:
        if m.get("role", "outcome") not in ("outcome", "check"):
            continue
        assert m["id"] in overall, f"measure {m['id']} is in measures.csv"
        r = overall[m["id"]]
        assert int(r["n"]) > 0 and r["value"] not in ("", None), f"measure {m['id']} has data: {r}"
    assert (session / "summary.csv").exists()


def test_taskswitching_alternating_runs(tmp_path):
    rows = [r for r in _wide(_run("taskswitching", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 96
    for i, r in enumerate(rows):
        q = i % 4
        assert int(r["cond.quadrant"]) == q
        assert r["cond.task"] == ("letter" if q < 2 else "digit")
        assert r["cond.transition"] == ("first" if i == 0 else ("switch" if q in (0, 2) else "repeat"))
        if r["resp.keys"]:
            want = r["letter_key"] if r["cond.task"] == "letter" else r["digit_key"]
            assert int(r["resp.corr"]) == int(r["resp.keys"] == want)


def test_cued_switching_transitions(tmp_path):
    rows = [r for r in _wide(_run("taskswitching_cued", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 128
    assert rows[0]["cond.transition"] == "first"
    for prev, cur in zip(rows, rows[1:]):
        assert cur["cond.transition"] == ("repeat" if cur["task"] == prev["task"] else "switch")
    assert abs(float(rows[1]["stimulus.onset"]) - float(rows[1]["cue_word.onset"]) - float(rows[1]["cti"])) < 0.02


def test_wcst_rule_changes_and_scoring(tmp_path):
    rows = [r for r in _wide(_run("wcst", tmp_path)) if r.get("loop") == "trials"]
    rules = ["colour", "shape", "number"]
    categories, streak, prev_rule = 0, 0, ""
    for r in rows:
        if streak >= 10:
            streak = 0
        rule = rules[categories % 3]
        assert r["rule_now.rule"] == rule
        key = {"colour": r["key_colour"], "shape": r["key_shape"], "number": r["key_number"]}
        assert r["rule_now.target"] == f"key{key[rule]}"
        corr = int(r["resp.corr"])
        chosen = int(r["resp.clicked"][-1])
        assert corr == int(chosen == int(key[rule]))
        persev = int(not corr and prev_rule != "" and int(key[prev_rule]) == chosen)
        assert int(r["score.persev_error"]) == persev
        streak = streak + 1 if corr else 0
        if streak >= 10:
            prev_rule, categories = rule, categories + 1
        assert int(r["score.categories"]) == categories
    assert categories >= 6 or len(rows) == 128, "stops after 6 categories or 128 cards"


def test_prp_soas_and_order(tmp_path):
    rows = [r for r in _wide(_run("prp", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 80
    assert sorted({r["soa_ms"] for r in rows}, key=int) == ["50", "150", "300", "600", "1000"]
    for r in rows:
        lag = float(r["letter_stim.onset"]) - float(r["tone_stim.onset"])
        assert abs(lag - float(r["soa"])) < 0.02, "the letter appears SOA seconds after the tone"


def test_negative_priming_design():
    rows = list(csv.DictReader((TASKS / "negative_priming" / "trials.csv").open(encoding="utf-8")))
    assert len(rows) == 48
    for r in rows:
        assert r["prime_target"] != r["prime_distractor"] and r["probe_target"] != r["probe_distractor"]
        if r["condition"] == "ignored_repetition":
            assert r["probe_target"] == r["prime_distractor"]
        else:
            assert {r["probe_target"], r["probe_distractor"]}.isdisjoint({r["prime_target"], r["prime_distractor"]})


def test_navon_grid_and_counterbalancing(tmp_path):
    stim = list(csv.DictReader((TASKS / "navon" / "stimuli.csv").open(encoding="utf-8")))
    assert {(r["global_letter"], r["local_letter"]) for r in stim} == {("H", "H"), ("H", "S"), ("S", "H"), ("S", "S")}
    assert all(len(r["cells"]) == 25 and set(r["cells"]) <= {"x", "."} for r in stim)
    first = {}
    for pid in ("1", "2"):
        rows = [r for r in _wide(_run("navon", tmp_path, pid)) if r.get("loop") == "trials"]
        assert len(rows) == 96
        first[pid] = rows[0]["level"]
    assert first["1"] != first["2"], "block order is counterbalanced across participants"


def test_multitasking_trial_types(tmp_path):
    rows = [r for r in _wide(_run("multitasking", tmp_path)) if r.get("stage") == "test"]
    assert len(rows) == 24 + 24 + 64
    single = [r for r in rows if r["block_type"] == "single"]
    assert single and all(r["cond.trial_type"] == "single" for r in single)
    mixed = [r for r in rows if r["block_type"] == "mixed"]
    assert mixed[0]["cond.trial_type"] == "first"
    for prev, cur in zip(mixed, mixed[1:]):
        assert cur["cond.trial_type"] == ("repeat" if cur["task"] == prev["task"] else "switch")


def test_dccs_answers():
    want = {("red_triangle", "colour"): "card_right", ("blue_circle", "colour"): "card_left",
            ("red_triangle", "shape"): "card_left", ("blue_circle", "shape"): "card_right"}
    for name, rule in (("pre_switch.csv", {"colour"}), ("post_switch.csv", {"shape"}), ("border.csv", {"colour", "shape"})):
        rows = list(csv.DictReader((TASKS / "dccs" / name).open(encoding="utf-8")))
        assert {r["rule"] for r in rows} == rule
        for r in rows:
            assert r["correct_card"] == want[(r["card"], r["rule"])]
            if name == "border.csv":
                assert (r["border"] == "1") == (r["rule"] == "colour")
