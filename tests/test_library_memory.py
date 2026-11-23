"""Task library, group 'memory': working-memory span tasks, n-back, AOSPAN, retro-cue, Mackworth clock, PVT-B.

Every task: meta.yaml complete, validates without errors or warnings, a test run (virtual participant) finishes
and its declared measures come out in measures.csv. Plus checks of the task-specific logic (stopping rules,
reversed recall, trial lists, scoring)."""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from edge.engine import run_experiment
from edge.model import Experiment

TASKS_DIR = Path(__file__).resolve().parents[1] / "edge" / "library" / "tasks"
TASKS = ["nback2", "nback2_phone", "touch_nback2", "digitspan", "rdigitspan", "corsi", "corsi2", "backward_corsi",
         "aospan", "retrocue", "mackworth", "mackworth2", "pvtb", "pvtb_touch"]
CATEGORIES = {"Attention", "Inhibition and conflict", "Cognitive control", "Working memory", "Vigilance",
              "Decision making", "Language", "Social and implicit", "Perception and motor", "Problem solving"}
INPUTS = {"keyboard", "mouse", "touch", "keyboard+mouse"}

_RUNS: dict[str, Path] = {}


def _run(task: str, tmp_root: Path) -> Path:
    """One test run per task, shared by the tests of this module (a copy of the task folder, data in tmp)."""
    if task not in _RUNS:
        work = tmp_root / task
        shutil.copytree(TASKS_DIR / task, work)
        exp = Experiment.load(work / f"{task}.yaml")
        from edge.participant import VirtualParticipant
        summary = run_experiment(exp, dry_run=True, data_dir=str(work / "data"), log=lambda *a: None,
                                 virtual_participant=VirtualParticipant(seed=3))      # same answers every run
        assert not summary.get("errors"), summary.get("errors")
        _RUNS[task] = Path(summary["data_dir"])
    return _RUNS[task]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("library_memory")
    return lambda task: _run(task, root)


def _rows(folder: Path, name: str = "trials.csv") -> list[dict]:
    with (folder / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _measure(folder: Path, mid: str) -> dict:
    return next(r for r in _rows(folder, "measures.csv") if r["measure"] == mid
                and all(v == "(all)" for k, v in r.items() if k not in ("participant", "session", "measure", "label",
                                                                        "role", "column", "summary", "n", "missing",
                                                                        "value", "units")))


# ============================================================================ every task
def test_task_list_matches_the_folders():
    for t in TASKS:
        assert (TASKS_DIR / t / f"{t}.yaml").is_file(), t
        assert (TASKS_DIR / t / "meta.yaml").is_file(), t


@pytest.mark.parametrize("task", TASKS)
def test_meta_is_complete(task):
    m = yaml.safe_load((TASKS_DIR / task / "meta.yaml").read_text(encoding="utf-8"))
    for key in ("id", "title", "category", "summary", "description", "measures", "duration_min", "input",
                "languages", "references", "see_also"):
        assert m.get(key) not in (None, "", [], {}), (task, key)
    assert m["id"] == task
    assert m["category"] in CATEGORIES
    assert m["input"] in INPUTS
    assert isinstance(m["measures"], list) and all(isinstance(x, str) for x in m["measures"])
    assert 1 <= m["duration_min"] <= 20
    assert m["languages"] == ["en"]
    assert all(re.search(r"\(\d{4}\)", r) for r in m["references"]), "every reference has a year"
    assert m["see_also"]["psytoolkit"] == f"https://www.psytoolkit.org/experiment-library/{task}.html"
    if "variant_of" in m:
        assert (TASKS_DIR / m["variant_of"] / "meta.yaml").is_file()


@pytest.mark.parametrize("task", TASKS)
def test_validates_cleanly(task):
    exp = Experiment.load(TASKS_DIR / task / f"{task}.yaml")
    issues = exp.validate()
    assert [str(i) for i in issues if i.level in ("error", "warning")] == []
    assert exp.name == task
    assert exp.measures, "the task declares what it measures"


@pytest.mark.parametrize("task", TASKS)
def test_test_run_records_every_measure(task, runs):
    folder = runs(task)
    exp = Experiment.load(TASKS_DIR / task / f"{task}.yaml")
    rows = _rows(folder, "measures.csv")
    got = {r["measure"]: r for r in rows if r["value"] not in ("", None)}
    for m in exp.measures:
        if m.get("role") == "factor":
            continue
        assert m["id"] in got, f"{task}: measure {m['id']} has no value after a test run"
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    assert not session.get("errors")


# ============================================================================ span tasks
def _span_rows(folder: Path) -> list[dict]:
    return [r for r in _rows(folder) if r["routine"] == "result" and r["phase"] == "main"]


@pytest.mark.parametrize("task,first,longest", [("digit" + "span", 3, 9), ("rdigit" + "span", 2, 8),
                                                ("corsi", 2, 9), ("backward_corsi", 2, 9)])
def test_span_tasks_follow_the_two_tries_rule(task, first, longest, runs):
    res = _span_rows(runs(task))
    spans = [int(float(r["span"])) for r in res]
    assert spans[0] == first and spans[1] == first
    ok = {}
    for r in res:
        ok.setdefault(int(float(r["span"])), []).append(int(r["score.list_ok"] if "score.list_ok" in r and r["score.list_ok"] != ""
                                                            else r["score.seq_ok"]))
    for n, outcomes in ok.items():
        assert len(outcomes) == 2, f"two tries at length {n}"
    lengths = sorted(ok)
    assert lengths == list(range(first, lengths[-1] + 1)), "lengths grow one at a time"
    for n in lengths[:-1]:
        assert any(ok[n]), "the test only goes on after at least one correct try"
    assert not any(ok[lengths[-1]]) or lengths[-1] == longest, "it stops after two failures or at the longest list"
    best = max([n for n, o in ok.items() if any(o)], default=0)
    assert int(res[-1]["score.best"]) == best


@pytest.mark.parametrize("task,backward", [("digit" + "span", False), ("rdigit" + "span", True),
                                           ("corsi", False), ("backward_corsi", True)])
def test_recall_order(task, backward, runs):
    rows = _rows(runs(task))
    makes = [r for r in rows if r.get("make.seq")]
    assert makes
    for r in makes:
        seq, target = json.loads(r["make.seq"]), json.loads(r["order.target"])
        assert len(set(seq)) == len(seq) and all(1 <= d <= 9 for d in seq)
        assert target == (seq[::-1] if backward else seq)
    # each recall screen's correct answer is the next element of the target (the counters, not stale loop states)
    pad = "pad"
    taps = [r for r in rows if r.get(f"{pad}.clicked")]
    assert taps and sum(int(r[f"{pad}.corr"]) for r in taps) / len(taps) > 0.6


def test_corsi2_uses_a_staircase_for_the_length(runs):
    folder = runs("corsi2")
    session = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    loops = session.get("loops") or session.get("loop_summaries") or {}
    text = json.dumps(loops)
    assert "staircase" in text
    res = [r for r in _rows(folder) if r["routine"] == "result" and r["phase"] == "main"]
    assert len(res) == 14
    spans = [int(float(r["span"])) for r in res]
    assert spans[0] == 3
    for (a, b), r in zip(zip(spans, spans[1:]), res):
        ok = int(r["score.seq_ok"])
        assert b == (min(a + 1, 9) if ok else max(a - 1, 2)), "one up after a correct sequence, one down after an error"
    assert 2 <= float(_measure(folder, "span_estimate")["value"]) <= 9


# ============================================================================ n-back
@pytest.mark.parametrize("task", ["nback2", "nback2_phone", "touch_nback2"])
def test_nback_lists(task):
    for name, n_blocks in (("practice.csv", 1), ("main.csv", 3)):
        rows = list(csv.DictReader((TASKS_DIR / task / name).open(encoding="utf-8")))
        blocks: dict[str, list[dict]] = {}
        for r in rows:
            blocks.setdefault(r["block"], []).append(r)
        assert len(blocks) == n_blocks
        for b in blocks.values():
            letters = [r["letter"] for r in b]
            assert [r["cond"] for r in b[:2]] == ["filler", "filler"]
            for i, r in enumerate(b):
                match = i >= 2 and letters[i] == letters[i - 2]
                assert int(r["target"]) == int(match)
                assert r["cond"] == ("target" if match else ("filler" if i < 2 else "nontarget"))
                assert r["corr_key"] == ("space" if match else "none")
                assert r["corr_button"] == ("b_match" if match else "b_nomatch")
            scored = b[2:]
            assert sum(int(r["target"]) for r in scored) * 3 in (len(scored) - 1, len(scored), len(scored) + 1)
            assert int(b[-1]["last_in_block"]) == 1 and sum(int(r["last_in_block"]) for r in b) == 1


def test_nback_breaks_between_blocks(runs):
    rows = _rows(runs("nback2"))
    assert sum(r["routine"] == "rest" for r in rows) == 2
    trials = [r for r in rows if r["routine"] == "trial" and r["loop"] == "trials"]
    assert len(trials) == 96


# ============================================================================ AOSPAN
def test_aospan_time_limit_and_scores(runs):
    folder = runs("aospan")
    rows = _rows(folder)
    limit = [r for r in rows if r["routine"] == "set_limit"]
    assert len(limit) == 1 and float(limit[0]["limit.math_limit"]) >= 2.0
    main_sets = [r for r in rows if r["routine"] == "set_feedback" and r["phase"] == "main"]
    assert sorted(int(r["set_size"]) for r in main_sets) == [3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
    letters = [r for r in rows if r["routine"] == "letter" and r["phase"] == "main"]
    assert len(letters) == 50
    absolute = sum(int(r["set_size"]) for r in main_sets if int(r["setscore.set_ok"]) == 1)
    assert int(float(_measure(folder, "ospan_absolute")["value"])) == absolute
    partial = sum(int(r["pick.corr"]) for r in rows if r["routine"] == "recall" and r["phase"] == "main")
    assert int(float(_measure(folder, "ospan_partial")["value"])) == partial


# ============================================================================ retro-cue
def test_retrocue_design(runs):
    rows = [r for r in _rows(runs("retrocue")) if r["routine"] == "trial" and r["loop"] == "trials"]
    assert len(rows) == 48
    cells = {}
    for r in rows:
        cells[(r["cue"], r["change"])] = cells.get((r["cue"], r["change"]), 0) + 1
        cols = json.loads(r["draw.cols"])
        probe = r["pick.probe_col"]
        if r["change"] == "same":
            assert probe == cols[int(r["draw.probe_i"])]
        else:
            assert probe not in cols
        assert (r["cue_one.onset"] != "") == (r["cue"] == "retro")
    assert set(cells.values()) == {12}


# ============================================================================ vigilance
@pytest.mark.parametrize("task,n_steps,n_signals", [("mackworth", 300, 15), ("mackworth2", 480, 24)])
def test_mackworth_lists_and_scoring(task, n_steps, n_signals, runs):
    ticks = list(csv.DictReader((TASKS_DIR / task / "ticks.csv").open(encoding="utf-8")))
    assert len(ticks) == n_steps and sum(int(t["double"]) for t in ticks) == n_signals
    for prev, cur in zip(ticks, ticks[1:]):
        assert int(cur["after"]) == int(prev["double"])
    assert (TASKS_DIR / task / "stimuli").is_dir() and any((TASKS_DIR / task / "stimuli").glob("*.png"))
    folder = runs(task)
    rows = [r for r in _rows(folder) if r["routine"] == "tick" and r["loop"] == "ticks"]
    assert len(rows) == n_steps
    hits = sum(int(r["score.hit_now"]) for r in rows)
    misses = sum(int(r["score.miss_now"]) for r in rows)
    assert hits + misses == n_signals, "every signal is either detected or missed"
    # the pointer moved 1 step per second, 2 on signals
    pointer = 0
    for r in rows:
        pointer = (pointer + 1 + int(r["double"])) % 60
        assert int(r["move.pointer"]) == pointer


@pytest.mark.parametrize("task", ["pvtb", "pvtb_touch"])
def test_pvt_runs_three_minutes_and_scores_lapses(task, runs):
    folder = runs(task)
    rows = [r for r in _rows(folder) if r["loop"] == "trials"]
    trials = [r for r in rows if r["routine"] == "trial"]
    total = sum(float(r["routine_duration"]) for r in rows)
    assert 180 <= total < 180 + 40          # the last trial may run up to a 30-s timeout
    assert len(trials) > 20
    for r in trials:
        rt = r["resp.rt"]
        fs, lapse = int(r["score.false_start"]), int(r["score.lapse"])
        if rt == "":
            assert fs == 1 or lapse == 1
        else:
            assert lapse == int(fs == 0 and float(rt) > 0.355)
        assert 1.0 - 1e-6 <= float(r["wait.isi"]) <= 4.0 + 1e-6
