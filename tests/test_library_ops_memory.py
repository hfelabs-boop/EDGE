"""Operational (defence human-factors) adaptations of the memory and vigilance tasks of the task library, group
'ops_memory': 2-back (keyboard, phone, touch), digit span (forward, backward), Corsi (forward, adaptive, backward),
AOSPAN, retro-cue, Mackworth clock (two versions) and PVT-B (keyboard, touch).

Every adaptation: meta.yaml complete and valid (domain, themes, adaptation, variant_of), the same measures and trial
lists as its base task, self-contained stimuli; and in EVERY theme it supports: a copy validates with 0 errors and
0 warnings and a test run (virtual participant) finishes with its measures in measures.csv and the theme recorded.
Plus checks that each theme's stimuli follow the classic design (items, contacts, alerts).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest
import yaml

from edge import library
from edge.cli import main
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "edge" / "library" / "tasks"
KIT = ROOT / "edge" / "library" / "defense_kit"

# adaptation -> base task
ADAPTATIONS = {
    "nback2_ops": "nback2", "nback2_phone_ops": "nback2_phone", "touch_nback2_ops": "touch_nback2",
    "digit" "span_ops": "digit" "span", "rdigit" "span_ops": "rdigit" "span",
    "corsi_ops": "corsi", "corsi2_ops": "corsi2", "backward_corsi_ops": "backward_corsi",
    "aospan_ops": "aospan", "retrocue_ops": "retrocue",
    "mackworth_ops": "mackworth", "mackworth2_ops": "mackworth2",
    "pvtb_ops": "pvtb", "pvtb_touch_ops": "pvtb_touch",
}
THEMES = {t: library.get_task(t).themes for t in ADAPTATIONS}
RUNS = [(t, th) for t in ADAPTATIONS for th in THEMES[t]]
# pictures drawn for a task (not copies of kit files), by tools/library/make_mackworth_ops.py
DRAWN = {"scope_600.png", "sweep_600.png", "sensor_ring_600.png", "channel_ring_600.png"}


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ================================================================ meta.yaml and files
def test_every_adaptation_is_listed():
    listed = {t.id for t in library.list_tasks(domain="defense")}
    assert set(ADAPTATIONS) <= listed
    _, problems = library.discover()
    assert not [p for p in problems if p.split("/")[0].split(":")[0] in ADAPTATIONS], problems
    for t, base in ADAPTATIONS.items():
        assert t in [a["id"] for a in library.get_task(base).adaptations], (t, base)


@pytest.mark.parametrize("task", ADAPTATIONS)
def test_meta(task):
    folder = TASKS_DIR / task
    meta = yaml.safe_load((folder / "meta.yaml").read_text(encoding="utf-8"))
    assert library.validate_meta(meta, folder) == []
    t, base = library.get_task(task), library.get_task(ADAPTATIONS[task])
    assert t.id == task and t.variant_of == base.id and t.category == base.category
    assert t.domain == "defense" and len(t.themes) >= 2 and len(t.adaptation) > 200
    assert all(th in library.THEMES for th in t.themes)
    assert t.measures == base.measures and t.input == base.input and t.languages == ["en"]
    assert set(base.references) <= set(t.references)
    assert all(re.search(r"\(\d{4}\)", r) for r in t.references)
    assert meta["see_also"]["psytoolkit"] == base.psytoolkit or meta["see_also"] == yaml.safe_load(
        (TASKS_DIR / base.id / "meta.yaml").read_text(encoding="utf-8"))["see_also"]
    # every theme the meta names is explained in the adaptation paragraph and the experiment's `theme` is the first
    for th in t.themes:
        assert f"{th}:" in t.adaptation, (task, th)
    assert Experiment.load(folder / f"{task}.yaml").variables["theme"] == t.themes[0]


@pytest.mark.parametrize("task", ADAPTATIONS)
def test_same_measures_and_trial_lists_as_the_base_task(task):
    base = ADAPTATIONS[task]
    ops = Experiment.load(TASKS_DIR / task / f"{task}.yaml")
    classic = Experiment.load(TASKS_DIR / base / f"{base}.yaml")
    key = lambda m: (m["id"], m["column"], m.get("role"), m.get("summary"), m.get("trials"), m.get("loop"))  # noqa: E731
    assert [key(m) for m in ops.measures] == [key(m) for m in classic.measures]
    for csv_file in (TASKS_DIR / base).glob("*.csv"):
        assert (TASKS_DIR / task / csv_file.name).read_bytes() == csv_file.read_bytes(), csv_file.name
    assert ops.name == task


@pytest.mark.parametrize("task", ADAPTATIONS)
def test_stimuli_are_kit_copies_or_drawn_and_small(task):
    folder = TASKS_DIR / task
    pics = list((folder / "stimuli").iterdir())
    assert pics
    for p in pics:
        if p.name in DRAWN:
            continue
        kit = list(KIT.rglob(p.name))
        assert len(kit) == 1 and kit[0].read_bytes() == p.read_bytes(), p.name
    assert sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) < 1_000_000
    # every picture the experiment names is in the folder, and every picture in the folder is used
    text = (folder / f"{task}.yaml").read_text(encoding="utf-8")
    named = set(re.findall(r"stimuli/[\w.]+", text))
    assert named == {f"stimuli/{p.name}" for p in pics}
    assert all((folder / n).is_file() for n in named)


@pytest.mark.parametrize("task", ADAPTATIONS)
def test_generator_is_committed(task):
    gens = list((ROOT / "tools" / "library").glob("make_*_ops.py"))
    assert any(f'"{task}"' in g.read_text(encoding="utf-8") for g in gens), task


# ================================================================ every theme: validate and test run
_RUN_DIRS: dict[tuple[str, str], Path] = {}


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("ops_memory")

    def go(task: str, theme: str) -> tuple[Path, Path]:
        if (task, theme) not in _RUN_DIRS:
            exp_file = library.copy_task(task, root / theme, theme=theme)
            assert main(["run", str(exp_file), "--dry-run", "-p", "7"]) == 0
            sessions = sorted(p.parent for p in (exp_file.parent / "data").rglob("session.json"))
            assert len(sessions) == 1
            _RUN_DIRS[(task, theme)] = exp_file
        exp_file = _RUN_DIRS[(task, theme)]
        return exp_file, next(p.parent for p in (exp_file.parent / "data").rglob("session.json"))
    return go


@pytest.mark.parametrize("task,theme", RUNS)
def test_validates_in_every_theme(task, theme, tmp_path):
    exp_file = library.copy_task(task, tmp_path, theme=theme)
    exp = Experiment.load(exp_file)
    assert exp.variables["theme"] == theme
    issues = [i for i in exp.validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))


@pytest.mark.parametrize("task,theme", RUNS)
def test_test_run_in_every_theme(task, theme, run):
    exp_file, session = run(task, theme)
    info = json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors") and info["variables"]["theme"] == theme
    measured = {r["measure"] for r in _rows(session / "measures.csv") if r["value"] not in ("", "None")}
    wanted = {m["id"] for m in Experiment.load(exp_file).measures if m.get("role") != "factor"}
    assert wanted <= measured, wanted - measured
    # the theme is in the trial data too (a variable item's shown_theme column)
    rows = _rows(session / "trials.csv")
    cols = [c for c in rows[0] if c.endswith(".shown_theme")]
    assert cols, "the trials record the theme"
    assert {r[c] for r in rows for c in cols if r.get(c)} == {theme}


# ================================================================ the stimuli follow the classic design
@pytest.mark.parametrize("task", ["nback2_ops", "nback2_phone_ops", "touch_nback2_ops"])
def test_nback_items_stand_for_the_letters(task, run):
    for theme in THEMES[task]:
        exp_file, session = run(task, theme)
        names = Experiment.load(exp_file).variables["names"][theme]
        assert len(set(names.values())) == len(names) == 10
        trials = [r for r in _rows(session / "trials.csv") if r["routine"] == "trial"]
        assert len([r for r in trials if r["loop"] == "trials"]) == 96
        for r in trials:
            assert r["show.item"] == names[r["letter"]]


@pytest.mark.parametrize("task,backward", [("digit" "span_ops", False), ("rdigit" "span_ops", True),
                                           ("corsi_ops", False), ("backward_corsi_ops", True)])
def test_span_tasks_keep_order_and_stopping_rule(task, backward, run):
    for theme in THEMES[task]:
        _, session = run(task, theme)
        rows = _rows(session / "trials.csv")
        for r in [r for r in rows if r.get("make.seq")]:
            seq, target = json.loads(r["make.seq"]), json.loads(r["order.target"])
            assert target == (seq[::-1] if backward else seq)
        res = [r for r in rows if r["routine"] == "result" and r["phase"] == "main"]
        by_len: dict[int, list[int]] = {}
        for r in res:
            ok = r.get("score.list_ok") or r.get("score.seq_ok")
            by_len.setdefault(int(float(r["span"])), []).append(int(ok))
        assert all(len(v) == 2 for v in by_len.values())
        lengths = sorted(by_len)
        assert lengths == list(range(lengths[0], lengths[-1] + 1))
        assert all(any(by_len[n]) for n in lengths[:-1])


def test_corsi2_staircase_in_every_theme(run):
    for theme in THEMES["corsi2_ops"]:
        _, session = run("corsi2_ops", theme)
        res = [r for r in _rows(session / "trials.csv") if r["routine"] == "result" and r["phase"] == "main"]
        assert len(res) == 14
        spans = [int(float(r["span"])) for r in res]
        assert spans[0] == 3
        for (a, b), r in zip(zip(spans, spans[1:]), res):
            assert b == (min(a + 1, 9) if int(r["score.seq_ok"]) else max(a - 1, 2))


def test_aospan_sets_in_every_theme(run):
    for theme in THEMES["aospan_ops"]:
        _, session = run("aospan_ops", theme)
        rows = _rows(session / "trials.csv")
        sizes = sorted(int(float(r["set_size"])) for r in rows if r["routine"] == "new_set" and r["loop"] == "sets")
        assert sizes == [3, 3, 4, 4, 5, 5, 6, 6, 7, 7]
        assert sum(r["routine"] == "recall" and r["loop"] == "letters_recall" for r in rows) == 50


def test_retrocue_contacts_come_from_the_theme(run):
    for theme in THEMES["retrocue_ops"]:
        exp_file, session = run("retrocue_ops", theme)
        pool = Experiment.load(exp_file).variables["looks"][theme]["pool"]
        trials = [r for r in _rows(session / "trials.csv") if r["routine"] == "trial"]
        assert len([r for r in trials if r["loop"] == "trials"]) == 48
        for r in trials:
            pics, i, probe = json.loads(r["draw.pics"]), int(r["draw.probe_i"]), r["pick.probe_pic"]
            assert len(set(pics)) == 4 and set(pics) <= set(pool)
            assert (probe == pics[i]) if r["change"] == "same" else (probe in pool and probe not in pics)
            assert (exp_file.parent / probe).is_file()


@pytest.mark.parametrize("task,n_ticks", [("mackworth_ops", 300), ("mackworth2_ops", 480)])
def test_mackworth_steps(task, n_ticks, run):
    for theme in THEMES[task]:
        _, session = run(task, theme)
        ticks = [r for r in _rows(session / "trials.csv") if r["loop"] == "ticks" and r["routine"] == "tick"]
        assert len(ticks) == n_ticks
        prev = 0
        for r in ticks:
            p = int(float(r["move.pointer"]))
            assert p == (prev + 1 + int(r["double"])) % 60
            prev = p


@pytest.mark.parametrize("task", ["pvtb_ops", "pvtb_touch_ops"])
def test_pvt_alert_and_counter_start_together(task, run):
    for theme in THEMES[task]:
        _, session = run(task, theme)
        trials = [r for r in _rows(session / "trials.csv") if r["loop"] == "trials" and r["routine"] == "trial"]
        assert len(trials) > 20
        shown = [r for r in trials if r.get("counter.onset") not in ("", None)]
        assert shown
        for r in shown:
            assert r["alert_pic.onset"] == r["counter.onset"]
