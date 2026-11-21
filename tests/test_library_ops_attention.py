"""Operational (defence human-factors) adaptations of the attention group of the task library:
ab_ops, abba_ops, ant_ops, ax_cpt_ops, cueing_ops, endo_exo_cueing_ops, ior_ops, dotprobe_ops, go_no_go_ops, sart_ops,
sart2_ops, stopsignal_ops, flanker_ops, flanker_arrows_ops, maabrams_ops.

Each adaptation: meta.yaml is complete and matches its classic task (category, measures, references), the experiment
keeps the classic task's declared measures and trial lists, its pictures are small (kit copies unchanged), and in
every one of its themes a copy validates with 0 errors and 0 warnings and passes a whole test run with the virtual
participant, recording the theme and the declared measures.
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
BASES = ["ab", "abba", "ant", "ax_cpt", "cueing", "endo_exo_cueing", "ior", "dotprobe", "go_no_go", "sart", "sart2",
         "stopsignal", "flanker", "flanker_arrows", "maabrams"]
OPS = [f"{b}_ops" for b in BASES]
# trial lists copied unchanged from the classic task (adaptation file -> classic file)
SAME_LISTS = {
    "ab_ops": {"ab_ops.csv": "ab.csv"}, "abba_ops": {"abba_ops.csv": "abba.csv"}, "ant_ops": {"ant_ops.csv": "ant.csv"},
    "ax_cpt_ops": {"ax_cpt_ops.csv": "ax_cpt.csv"}, "cueing_ops": {"cueing_ops.csv": "cueing.csv"},
    "endo_exo_cueing_ops": {n: n for n in ("blocks.csv", "endogenous.csv", "exogenous.csv")},
    "ior_ops": {"ior_ops.csv": "ior.csv"}, "sart_ops": {"sart_ops.csv": "sart.csv"},
    "sart2_ops": {"sart2_ops.csv": "sart2.csv"}, "stopsignal_ops": {"stopsignal_ops.csv": "stopsignal.csv"},
    "flanker_ops": {"flanker_ops.csv": "flanker.csv"}, "flanker_arrows_ops": {"flanker_arrows_ops.csv": "flanker_arrows.csv"},
    "maabrams_ops": {"maabrams_ops.csv": "maabrams.csv"},
}
# pictures drawn for the task (not kit copies) by tools/library/ops_attention_pics.py
OWN_PICTURES = {"c2_heading_left.png", "c2_heading_right.png", "c2_heading_none.png",
                "uav_heading_left.png", "uav_heading_right.png", "uav_heading_none.png"}


def _meta(task: str) -> dict:
    return yaml.safe_load((TASKS / task / "meta.yaml").read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


CASES = [(t, th) for t in OPS for th in _meta(t)["themes"]]


def test_every_adaptation_is_listed():
    ops = {t.id: t for t in library.list_tasks(domain="defense")}
    assert set(OPS) <= set(ops)
    _tasks, problems = library.discover()
    assert not [p for p in problems if any(t in p for t in OPS)], problems
    for base in BASES:
        assert f"{base}_ops" in [a["id"] for a in library.get_task(base).adaptations]


@pytest.mark.parametrize("task", OPS)
def test_meta_matches_the_classic_task(task):
    meta, folder = _meta(task), TASKS / task
    assert library.validate_meta(meta, folder) == []
    base = task[:-4]
    t, b = library.get_task(task), library.get_task(base)
    assert meta["id"] == task and t.variant_of == base and t.domain == "defense"
    assert t.category == b.category and t.measures == b.measures and t.input == b.input
    assert len(t.themes) >= 2 and set(t.themes) <= set(library.THEMES) and t.themes[0] == "c2"
    assert len(t.adaptation) > 300 and all(th in t.adaptation for th in t.themes)
    assert set(b.references) <= set(t.references)
    assert meta["see_also"] == _meta(base)["see_also"]
    assert (ROOT / "tools" / "library" / f"make_{task}.py").is_file()
    assert t.title.endswith("operational)")


@pytest.mark.parametrize("task", OPS)
def test_experiment_keeps_the_design(task):
    base = task[:-4]
    ops = Experiment.load(TASKS / task / f"{task}.yaml")
    classic = Experiment.load(TASKS / base / f"{base}.yaml")
    # the same declared measures (ids, columns, trials, summaries)
    strip = lambda ms: [{k: v for k, v in m.items() if k != "label"} for m in ms]
    assert strip(ops.measures) == strip(classic.measures)
    themes = _meta(task)["themes"]
    assert ops.variables["theme"] == themes[0]
    text = (TASKS / task / f"{task}.yaml").read_text(encoding="utf-8")
    for th in themes:   # the display / instructions of every theme are there
        assert f"$theme == '{th}'" in text, th
    for mine, theirs in SAME_LISTS.get(task, {}).items():
        assert (TASKS / task / mine).read_text() == (TASKS / base / theirs).read_text(), mine


@pytest.mark.parametrize("task", OPS)
def test_stimuli_are_small_and_from_the_kit(task):
    folder = TASKS / task
    assert sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) < 1_000_000
    stim = folder / "stimuli"
    assert stim.is_dir()
    for p in stim.iterdir():
        if p.name in OWN_PICTURES:
            continue
        kit = list(KIT.rglob(p.name))
        assert len(kit) == 1 and kit[0].read_bytes() == p.read_bytes(), p.name
    # every picture / video the experiment names is in the folder, and every file there is used
    text = (folder / f"{task}.yaml").read_text(encoding="utf-8")
    named = {w.split("/")[1].rstrip(",]}'\"") for w in text.replace("[", " ").split() if w.startswith("stimuli/")}
    assert named == {p.name for p in stim.iterdir()}


@pytest.mark.parametrize("task,theme", CASES)
def test_runs_in_every_theme(task, theme, tmp_path):
    exp_file = library.copy_task(task, tmp_path, theme=theme)
    exp = Experiment.load(exp_file)
    assert exp.variables["theme"] == theme
    issues = [i for i in exp.validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))
    assert main(["run", str(exp_file), "--dry-run", "-p", "5"]) == 0
    sessions = sorted(p.parent for p in (exp_file.parent / "data").rglob("session.json"))
    assert len(sessions) == 1
    info = json.loads((sessions[0] / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors") and info["variables"]["theme"] == theme
    # every declared outcome has a value (SSRT may be None for the virtual participant; it is reported anyway)
    outcomes = {m["id"] for m in exp.measures if m.get("role") == "outcome"}
    values = {r["measure"]: r["value"] for r in _rows(sessions[0] / "measures.csv")}
    assert outcomes <= set(values)
    assert all(values[m] not in ("", "None") for m in outcomes - {"ssrt"}), values
    # the trial data records the theme on every main trial
    rows = [r for r in _rows(sessions[0] / "trials.csv") if r.get("loop") == "main"]
    assert rows
    shown = [v for r in rows for k, v in r.items() if k.endswith(".shown_theme") and v]
    assert shown and set(shown) == {theme}
