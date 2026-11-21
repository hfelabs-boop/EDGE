"""Operational (defence human-factors) adaptations of the "control" group of the task library: the Stroop family,
numerical Stroop, Simon, negative priming, Navon, task switching, multitasking, PRP, DCCS and the card sort
(edge/library/tasks/<id>_ops/, docs/library/DEFENSE.md).

For every adaptation: meta.yaml is complete and valid (domain, themes with the default first, adaptation,
variant_of the base task, the base task's category); the experiment keeps the base task's measures; and in EVERY
theme a copy validates with no errors or warnings, a test run (dry run) finishes without errors, records the
theme, and every declared outcome / check measure appears in measures.csv with data. A few checks make sure the
paradigm logic still does what the base task's does.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from edge import library
from edge.cli import main
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "edge" / "library" / "tasks"
KIT = ROOT / "edge" / "library" / "defense_kit"
BASES = ["stroop", "stroop_de", "stroop_en", "stroop_phone", "numerical_stroop", "numerical_stroop_touch",
         "simon", "touch_simon", "negative_priming", "navon", "taskswitching", "taskswitching_cued",
         "multitasking", "prp", "dccs", "wcst"]
GROUP = [f"{b}_ops" for b in BASES]


def _meta(task: str) -> dict:
    return yaml.safe_load((TASKS / task / "meta.yaml").read_text(encoding="utf-8"))


THEMED = [(t, th) for t in GROUP for th in _meta(t)["themes"]]


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _run(task: str, theme: str, tmp: Path, participant: str = "5") -> Path:
    """Copy the task in a theme, check it validates cleanly, dry-run it; returns the session folder."""
    exp_file = library.copy_task(task, tmp, theme=theme)
    exp = Experiment.load(exp_file)
    issues = [i for i in exp.validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))
    assert exp.variables["theme"] == theme
    assert main(["run", str(exp_file), "--dry-run", "-p", participant]) == 0
    sessions = sorted(p.parent for p in (exp_file.parent / "data").rglob("session.json"))
    assert len(sessions) == 1
    return sessions[0]


# ================================================================ meta.yaml and files
@pytest.mark.parametrize("task", GROUP)
def test_meta(task):
    meta = _meta(task)
    assert library.validate_meta(meta, TASKS / task) == []
    base = _meta(meta["variant_of"])
    assert meta["variant_of"] == task[:-4] and meta["id"] == task
    assert meta["domain"] == "defense" and len(meta["themes"]) >= 2
    assert set(meta["themes"]) <= set(library.THEMES) and len(meta["adaptation"]) > 200
    assert meta["category"] == base["category"] and meta["input"] == base["input"]
    assert meta["languages"] == base["languages"]
    assert meta["see_also"] == base["see_also"]
    assert set(meta["references"]) & set(base["references"]), "cites the base paradigm's papers"
    t = library.get_task(task)
    assert t.themes == meta["themes"] and t.domain == "defense"
    assert task in [a["id"] for a in library.get_task(meta["variant_of"]).adaptations]
    # the experiment's theme is the default (first) theme, as the first variable
    exp = Experiment.load(TASKS / task / f"{task}.yaml")
    assert list(exp.variables)[0] == "theme" and exp.variables["theme"] == meta["themes"][0]


@pytest.mark.parametrize("task", GROUP)
def test_same_measures_as_the_base_task(task):
    ops = Experiment.load(TASKS / task / f"{task}.yaml")
    base = Experiment.load(TASKS / task[:-4] / f"{task[:-4]}.yaml")
    key = lambda m: (m["id"], m["column"], m.get("role", "outcome"), m.get("summary"), m.get("loop"))  # noqa: E731
    assert [key(m) for m in ops.measures] == [key(m) for m in base.measures]


@pytest.mark.parametrize("task", GROUP)
def test_files_are_small_and_from_the_kit_or_a_generator(task):
    folder = TASKS / task
    assert sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) < 2_000_000
    assert not (folder / "data").exists()
    stimuli = [p for p in (folder / "stimuli").rglob("*") if p.is_file()]
    assert stimuli, "the task carries its own pictures"
    for p in stimuli:
        kit = list(KIT.rglob(p.name))
        if kit:                                           # a copy of a kit file: unchanged
            assert kit[0].read_bytes() == p.read_bytes(), p.name
        else:                                             # the task's own pictures (wcst_ops cards)
            assert task == "wcst_ops", p
    gen = ROOT / "tools" / "library"
    assert any(task in f.read_text(encoding="utf-8") for f in gen.glob("make_*_ops.py")), "a generator makes it"


@pytest.mark.parametrize("task", ["simon_ops", "touch_simon_ops", "numerical_stroop_ops", "numerical_stroop_touch_ops",
                                  "negative_priming_ops", "multitasking_ops", "prp_ops"])
def test_trial_lists_are_the_base_task_lists(task):
    base = task[:-4]
    for f in (TASKS / base).glob("*.csv"):
        assert (TASKS / task / f.name).read_text(encoding="utf-8") == f.read_text(encoding="utf-8"), f.name


# ================================================================ every task in every theme
@pytest.mark.parametrize("task,theme", THEMED)
def test_runs_in_every_theme(task, theme, tmp_path):
    session = _run(task, theme, tmp_path)
    info = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors"), info.get("errors")
    assert info["variables"]["theme"] == theme
    exp = Experiment.load(TASKS / task / f"{task}.yaml")
    rows = _rows(session / "measures.csv")
    fixed = ("participant", "session", "measure", "label", "role", "column", "summary", "n", "missing", "value", "units")
    overall = {r["measure"]: r for r in rows if all(r.get(k) == "(all)" for k in r if k not in fixed)}
    for m in exp.measures:
        if m.get("role", "outcome") in ("outcome", "check"):
            assert m["id"] in overall, f"measure {m['id']} is in measures.csv"
            r = overall[m["id"]]
            assert int(r["n"]) > 0 and r["value"] not in ("", "None"), f"measure {m['id']} has data: {r}"
    assert (session / "summary.csv").exists()
    trials = _rows(session / "trials.csv")
    shown = {r[c] for r in trials for c in r if c.endswith(".shown_theme") and r[c]}
    assert shown == {theme}, "every trial records the theme it was shown in"


# ================================================================ the paradigm logic is the base task's
def _wide(session: Path) -> list[dict]:
    return _rows(session / "trials_wide.csv")


def test_stroop_family_lists():
    for task, keys in (("stroop_ops", "rgby"), ("stroop_de_ops", "dfjk"), ("stroop_en_ops", "dfjk")):
        rows = _rows(TASKS / task / "stroop.csv")
        assert len(rows) == 24 and sum(r["condition"] == "congruent" for r in rows) == 12
        ink_key = {r["ink"]: r["correct_key"] for r in rows}
        assert sorted(ink_key.values()) == sorted(keys) and len(ink_key) == 4
        assert len(_rows(TASKS / task / "practice.csv")) == 8
    words = {r["word"] for r in _rows(TASKS / "stroop_de_ops" / "stroop.csv")}
    assert words == {"FEIND", "FREUND", "NEUTRAL", "UNBEKANNT"}
    phone = _rows(TASKS / "stroop_phone_ops" / "stroop.csv")
    assert all(r["correct_button"] == f"btn_{r['ink']}" for r in phone)
    # the label's colour is the affiliation colour of the kit's palette
    palette = yaml.safe_load((KIT / "kit.yaml").read_text(encoding="utf-8"))["palette"]["affiliation"]
    assert all(r["ink_rgb"] == palette[r["ink"]] for r in phone)


def test_taskswitching_alternating_runs(tmp_path):
    rows = [r for r in _wide(_run("taskswitching_ops", "ew", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 96
    for i, r in enumerate(rows):
        q = i % 4
        assert int(r["cond.quadrant"]) == q
        assert r["cond.task"] == ("identity" if q < 2 else "kind")
        assert r["cond.transition"] == ("first" if i == 0 else ("switch" if q in (0, 2) else "repeat"))
        if r["resp.keys"]:
            want = r["identity_key"] if r["cond.task"] == "identity" else r["kind_key"]
            assert int(r["resp.corr"]) == int(r["resp.keys"] == want)


def test_cued_switching_transitions(tmp_path):
    rows = [r for r in _wide(_run("taskswitching_cued_ops", "c2", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 128
    assert rows[0]["cond.transition"] == "first"
    for prev, cur in zip(rows, rows[1:]):
        assert cur["cond.transition"] == ("repeat" if cur["task"] == prev["task"] else "switch")
    assert abs(float(rows[1]["stimulus.onset"]) - float(rows[1]["cue_word.onset"]) - float(rows[1]["cti"])) < 0.02
    lists = _rows(TASKS / "taskswitching_cued_ops" / "trials.csv")
    for r in lists:
        assert r["correct_key"] == ("a" if r[r["task"]] in ("hostile", "air") else "l")


def test_wcst_rule_changes_and_scoring(tmp_path):
    rows = [r for r in _wide(_run("wcst_ops", "ew", tmp_path)) if r.get("loop") == "trials"]
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
        assert int(r["score.persev_error"]) == int(not corr and prev_rule != "" and int(key[prev_rule]) == chosen)
        streak = streak + 1 if corr else 0
        if streak >= 10:
            prev_rule, categories = rule, categories + 1
        assert int(r["score.categories"]) == categories
    assert categories >= 6 or len(rows) == 128
    # every card exists in both themes, named by the classic codes
    cards = _rows(TASKS / "wcst_ops" / "cards.csv")
    assert len(cards) == 64
    for theme in ("c2", "ew"):
        assert sorted(p.stem for p in (TASKS / "wcst_ops" / "stimuli" / theme).glob("*.png")) == sorted(c["card"] for c in cards)


def test_prp_soas(tmp_path):
    rows = [r for r in _wide(_run("prp_ops", "uav", tmp_path)) if r.get("loop") == "trials"]
    assert len(rows) == 80
    assert sorted({r["soa_ms"] for r in rows}, key=int) == ["50", "150", "300", "600", "1000"]
    for r in rows:
        assert abs(float(r["alert_stim.onset"]) - float(r["tone_stim.onset"]) - float(r["soa"])) < 0.02


def test_navon_formations_and_counterbalancing(tmp_path):
    stim = _rows(TASKS / "navon_ops" / "stimuli.csv")
    assert {(r["global_shape"], r["local_shape"]) for r in stim} == {("diamond", "diamond"), ("diamond", "square"),
                                                                    ("square", "diamond"), ("square", "square")}
    assert all(len(r["cells"]) == 49 and set(r["cells"]) <= {"x", "."} for r in stim)
    first = {}
    for pid in ("1", "2"):
        rows = [r for r in _wide(_run("navon_ops", "uav", tmp_path / pid, pid)) if r.get("loop") == "trials"]
        assert len(rows) == 96
        first[pid] = rows[0]["level"]
        for r in rows:
            assert r["resp.corr"] in ("0", "1", "")
            if r["resp.keys"]:
                want = r["global_key"] if r["level"] == "global" else r["local_key"]
                assert int(r["resp.corr"]) == int(r["resp.keys"] == want)
    assert first["1"] != first["2"], "block order is counterbalanced across participants"
    # the 20 cell items are exactly the places either outline uses, each drawn only where `cells` has an x
    doc = yaml.safe_load((TASKS / "navon_ops" / "navon_ops.yaml").read_text(encoding="utf-8"))
    cells = [c for c in doc["routines"]["trial"]["components"] if c["id"][1:].isdigit()]
    used = {i for r in stim for i, ch in enumerate(r["cells"]) if ch == "x"}
    assert {int(c["id"][1:]) for c in cells} == used
    assert all(c["if"] == f"$cells[{int(c['id'][1:])}] == 'x'" for c in cells)


def test_multitasking_trial_types(tmp_path):
    rows = [r for r in _wide(_run("multitasking_ops", "uav", tmp_path)) if r.get("stage") == "test"]
    assert len(rows) == 24 + 24 + 64
    assert all(r["cond.trial_type"] == "single" for r in rows if r["block_type"] == "single")
    mixed = [r for r in rows if r["block_type"] == "mixed"]
    assert mixed[0]["cond.trial_type"] == "first"
    for prev, cur in zip(mixed, mixed[1:]):
        assert cur["cond.trial_type"] == ("repeat" if cur["task"] == prev["task"] else "switch")
    for r in rows:                # a group of 2 or 3: the third member only for 3
        assert (r.get("member3.onset", "") != "") == (r["dots"] == "3")


def test_dccs_answers():
    want = {("red_triangle", "colour"): "card_right", ("blue_circle", "colour"): "card_left",
            ("red_triangle", "shape"): "card_left", ("blue_circle", "shape"): "card_right"}
    for name, rule in (("pre_switch.csv", {"colour"}), ("post_switch.csv", {"shape"}), ("border.csv", {"colour", "shape"})):
        rows = _rows(TASKS / "dccs_ops" / name)
        assert {r["rule"] for r in rows} == rule
        for r in rows:
            assert r["correct_card"] == want[(r["card"], r["rule"])]
            if name == "border.csv":
                assert (r["border"] == "1") == (r["rule"] == "colour")
    # the pictures match the rules in each theme: the test reports share one dimension with each reference
    looks = Experiment.load(TASKS / "dccs_ops" / "dccs_ops.yaml").variables["looks"]
    assert Path(looks["c2"]["red_triangle"]).name.split("_")[0] == Path(looks["c2"]["right"]).name.split("_")[0]  # hostile
    assert Path(looks["c2"]["red_triangle"]).name.split("_")[1] == Path(looks["c2"]["left"]).name.split("_")[1]   # air


def test_negative_priming_design():
    rows = _rows(TASKS / "negative_priming_ops" / "trials.csv")
    assert len(rows) == 48
    for r in rows:
        if r["condition"] == "ignored_repetition":
            assert r["probe_target"] == r["prime_distractor"]
        else:
            assert {r["probe_target"], r["probe_distractor"]}.isdisjoint({r["prime_target"], r["prime_distractor"]})
