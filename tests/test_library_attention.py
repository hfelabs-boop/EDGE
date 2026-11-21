"""Task library, attention group: every task validates cleanly, runs a whole test run with the virtual
participant, records its declared measures (measures.csv) and has complete metadata.

Tasks: ab, abba, ant, ax_cpt, cueing, endo_exo_cueing, ior, dotprobe, go_no_go, sart, sart2, stopsignal,
flanker, flanker_arrows, maabrams, search.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from edge.cli import main
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "edge" / "library" / "tasks"
GROUP = ["ab", "abba", "ant", "ax_cpt", "cueing", "endo_exo_cueing", "ior", "dotprobe", "go_no_go", "sart",
         "sart2", "stopsignal", "flanker", "flanker_arrows", "maabrams", "search"]
CATEGORIES = {"Attention", "Inhibition and conflict", "Cognitive control", "Working memory", "Vigilance",
              "Decision making", "Language", "Social and implicit", "Perception and motor", "Problem solving"}
INPUTS = {"keyboard", "mouse", "touch", "keyboard+mouse"}
REQUIRED = ("id", "title", "category", "summary", "description", "measures", "duration_min", "input",
            "languages", "references", "see_also")


def _copy(task: str, tmp: Path) -> Path:
    dst = tmp / task
    shutil.copytree(TASKS / task, dst, ignore=shutil.ignore_patterns("data", "exports", "*.edgez", "*.lock*"))
    return dst / f"{task}.yaml"


def _session(exp: Path) -> Path:
    found = sorted(p.parent for p in (exp.parent / "data").rglob("session.json"))
    assert len(found) == 1, found
    return found[0]


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("task", GROUP)
def test_meta_complete(task):
    folder = TASKS / task
    assert (folder / f"{task}.yaml").is_file()
    meta = yaml.safe_load((folder / "meta.yaml").read_text(encoding="utf-8"))
    for key in REQUIRED:
        assert meta.get(key) not in (None, "", [], {}), f"meta.yaml: {key} is missing"
    assert meta["id"] == task
    assert meta["category"] in CATEGORIES
    assert meta["input"] in INPUTS
    assert isinstance(meta["duration_min"], (int, float)) and 2 <= meta["duration_min"] <= 12
    assert isinstance(meta["measures"], list) and all(isinstance(m, str) for m in meta["measures"])
    assert isinstance(meta["references"], list) and all(re.search(r"\(\d{4}\)", r) for r in meta["references"])
    assert meta["languages"] == ["en"]
    psy_id = {"ax_cpt": "ax-cpt", "go_no_go": "go-no-go"}.get(task, task)
    assert meta["see_also"]["psytoolkit"] == f"https://www.psytoolkit.org/experiment-library/{psy_id}.html"
    if meta.get("variant_of"):
        assert (TASKS / meta["variant_of"] / "meta.yaml").is_file()
    exp = Experiment.load(folder / f"{task}.yaml")
    assert exp.name == task
    assert exp.description and exp.measures, "the experiment says what it is and what it measures"


@pytest.mark.parametrize("task", GROUP)
def test_validates_without_warnings(task):
    exp = Experiment.load(TASKS / task / f"{task}.yaml")
    issues = [i for i in exp.validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))


@pytest.mark.parametrize("task", GROUP)
def test_test_run_records_measures(task, tmp_path):
    exp_file = _copy(task, tmp_path)
    assert main(["validate", str(exp_file)]) == 0
    assert main(["run", str(exp_file), "--dry-run", "-p", "7"]) == 0
    s = _session(exp_file)
    info = json.loads((s / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors"), info.get("errors")

    trials = _rows(s / "trials.csv")
    main_rows = [r for r in trials if r.get("loop") == "main"]
    assert main_rows, "the main block ran"
    declared = Experiment.load(exp_file).measures
    measured = _rows(s / "measures.csv")
    ids = {r["measure"] for r in measured}
    for m in declared:
        if m.get("role") == "factor":
            # every factor has its levels in the data
            assert any(r.get(m["column"]) not in (None, "") for r in main_rows), m["id"]
            continue
        assert m["id"] in ids, f"measure {m['id']} missing from measures.csv"
        overall = [r for r in measured if r["measure"] == m["id"] and int(r["n"] or 0) > 0]
        assert overall and overall[0]["value"] not in ("", "None"), f"measure {m['id']} has no value"
    # correct answers are in the data: every response item with a correct answer scored the main trials
    assert any(k.endswith(".corr") and r.get(k) in ("0", "1") for r in main_rows for k in r)


def test_preflight_go(tmp_path, capsys):
    """One full preflight (without the computer check, which needs a screen) on a representative task."""
    exp_file = _copy("stopsignal", tmp_path)
    capsys.readouterr()
    main(["preflight", str(exp_file), "--no-computer", "--json"])
    rep = json.loads(capsys.readouterr().out)
    sections = {s["id"]: s["status"] for s in rep["sections"]}
    assert sections["experiment"] == "ok" and sections["test_run"] == "ok" and sections["measures"] == "ok", sections


# ------------------------------------------------------------------ paradigm-specific checks
def _run(task: str, tmp_path: Path, participant: str = "3") -> list[dict[str, str]]:
    exp_file = _copy(task, tmp_path)
    assert main(["run", str(exp_file), "--dry-run", "-p", participant]) == 0
    return _rows(_session(exp_file) / "trials.csv")


def test_stopsignal_staircase_moves_only_on_stop_trials(tmp_path):
    rows = [r for r in _run("stopsignal", tmp_path) if r.get("loop") == "main" and r.get("routine") == "trial"]
    assert len(rows) == 120 and sum(r["trial_type"] == "stop" for r in rows) == 30
    for a, b in zip(rows, rows[1:]):
        before, after = float(a["delay.trial_ssd"]), float(a["track.ssd"])
        if a["trial_type"] == "go":
            assert after == pytest.approx(before)
        else:
            step = 0.05 if not a.get("resp.keys") else -0.05
            assert after == pytest.approx(min(max(before + step, 0.05), 0.9))
        assert float(b["delay.trial_ssd"]) == pytest.approx(after)


def test_ab_stream_holds_both_digits_at_the_lag(tmp_path):
    rows = [r for r in _run("ab", tmp_path) if r.get("routine") == "stream" and r.get("loop") == "main"]
    assert len(rows) == 40
    for r in rows:
        items = json.loads(r["place.items"])
        t1 = int(r["pick.t1_pos"])
        lag = int(r["lag"])
        assert len(items) == 20 and 4 <= t1 <= 8
        assert items[t1] == r["pick.t1_digit"] and items[t1 + lag] == r["build.t2_digit"]
        assert items[t1] != items[t1 + lag]
        assert sum(x.isdigit() for x in items) == 2


def test_search_display_matches_condition(tmp_path):
    rows = [r for r in _run("search", tmp_path) if r.get("routine") == "trial" and r.get("loop") == "main"]
    assert len(rows) == 72
    for r in rows:
        n = int(r["set_size"])
        shown = list(zip(json.loads(r["layout.letters"])[:n], json.loads(r["layout.colors"])[:n]))
        targets = sum(1 for letter, colour in shown if letter == "T" and colour == "#ff4040")
        assert targets == (1 if r["target"] == "present" else 0)
        assert f"item{n - 1}.onset" in r and r[f"item{n - 1}.onset"] != ""
        if n < 16:
            assert r.get(f"item{n}.onset", "") == "", "only set_size items are shown"


def test_maabrams_layout(tmp_path):
    rows = [r for r in _run("maabrams", tmp_path) if r.get("routine") == "prep" and r.get("loop") == "main"]
    assert len(rows) == 72
    for r in rows:
        tp, side, dp = int(r["pick.tp"]), int(r["pick.side"]), int(r["place.dp"])
        assert dp == (tp + side) % 6
        edge_ = int(r["place.bar_edge"])
        joined = {edge_, (edge_ + 1) % 6}
        assert joined == ({tp, dp} if r["distractor"] == "grouped" else {dp, (dp + side) % 6})
        kinds = json.loads(r["place.line_kinds"])
        assert kinds[tp] == r["target_line"] and all(k.startswith("tilt") for i, k in enumerate(kinds) if i != tp)


def test_endo_exo_block_order_is_counterbalanced(tmp_path):
    orders = []
    for pid in ("1", "2"):
        sub = tmp_path / pid
        sub.mkdir()
        rows = _run("endo_exo_cueing", sub, participant=pid)
        seen = []
        for r in rows:
            if r.get("loop") == "main" and r.get("cue_type") and (not seen or seen[-1] != r["cue_type"]):
                seen.append(r["cue_type"])
        assert sorted(seen) == ["endogenous", "exogenous"]
        orders.append(seen)
    assert orders[0] != orders[1]


@pytest.mark.parametrize("task, ratio", [("go_no_go", 0.25), ("sart", 1 / 9), ("ax_cpt", 0.3)])
def test_trial_proportions(task, ratio, tmp_path):
    rows = [r for r in _run(task, tmp_path) if r.get("loop") == "main" and r.get("resp.corr") is not None
            and r.get("routine") == "trial"]
    col = {"go_no_go": ("trial_type", "nogo"), "sart": ("trial_type", "nogo")}.get(task)
    if col:
        rare = sum(r[col[0]] == col[1] for r in rows)
    else:
        rare = sum(r["trial_type"] != "AX" for r in rows)
    assert rare / len(rows) == pytest.approx(ratio, abs=0.01)
