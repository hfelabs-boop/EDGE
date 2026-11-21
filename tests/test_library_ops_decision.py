"""Operational (defence human-factors) adaptations, group "ops_decision": the <id>_ops versions of BART, IGT, IAT,
lexical decision, the three self-paced reading tasks, mental rotation, Deary-Liewald, digit symbol substitution,
Fitts's law, Tower of Hanoi and the two VAAST versions (pattern: search_ops, tests/test_library_defense_kit.py).

Every adaptation: meta.yaml complete and valid as an adaptation (domain, themes, adaptation, variant_of), the same
measures and design as its classic task, a self-contained stimuli/ folder (kit copies unchanged, own pictures from a
generator in tools/library/), and in EVERY theme: validates without errors or warnings, a test run (virtual
participant) finishes and its measures are in measures.csv. Plus checks of what each theme shows in the data.
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

BASES = ["bart", "igt", "iat2", "ldt", "pacedreading1", "pacedreading2", "pacedreading3", "mentalrotation",
         "deary_liewald", "digit_substitution", "fitts", "tower_hanoi", "vaast_words", "vaast_images"]
OPS = {f"{b}_ops": b for b in BASES}

# generator of each adaptation's stimuli / trial lists
GENERATORS = {"pacedreading1_ops": "make_reading_ops.py", "pacedreading2_ops": "make_reading_ops.py",
              "pacedreading3_ops": "make_reading_ops.py"}
# pictures each adaptation draws itself (not copied from the kit), by file-name pattern
OWN_PICTURES = {
    "iat2_ops": r"(own|other)_\d+\.png",
    "mentalrotation_ops": r"(area|top)_[FLNP](_mirror)?\.png",
    "digit_substitution_ops": r"emitter_hopping_(high|medium|low)\.png",
    "fitts_ops": r"target_box_\d+x260\.png",
    "vaast_images_ops": r"(track_(friendly|hostile)_\d+\.png|scene_(friendly|hostile)_\d+\.jpg)",
}
# trial-list files that keep the classic task's design exactly (byte for byte)
SAME_LISTS = {
    "igt_ops": ["igt_trials.csv"],
    "mentalrotation_ops": ["mr_trials.csv", "mr_practice.csv"],
    "deary_liewald_ops": ["choice_practice.csv", "choice_test.csv"],
    "fitts_ops": ["fitts_trials.csv", "fitts_practice.csv"],
    "tower_hanoi_ops": ["hanoi_problems.csv"],
}
# measures that may stay empty in a test run (they need a solved problem; the virtual participant clicks at random)
MAY_BE_EMPTY = {"tower_hanoi_ops": {"excess_moves", "solve_time"}}

CASES = [(t, theme) for t in OPS for theme in yaml.safe_load((TASKS_DIR / t / "meta.yaml").read_text())["themes"]]


def _meta(task: str) -> dict:
    return yaml.safe_load((TASKS_DIR / task / "meta.yaml").read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ================================================================ meta.yaml and files
@pytest.mark.parametrize("task", OPS)
def test_meta_is_a_valid_adaptation(task):
    base = OPS[task]
    meta, base_meta = _meta(task), _meta(base)
    assert library.validate_meta(meta, TASKS_DIR / task) == []
    t = library.get_task(task)
    assert t.variant_of == base and t.domain == "defense"
    assert meta["category"] == base_meta["category"] and meta["input"] == base_meta["input"]
    assert meta["see_also"] == base_meta["see_also"]
    assert len(t.themes) >= 2 and set(t.themes) <= set(library.THEMES)
    assert Experiment.load(TASKS_DIR / task / f"{task}.yaml").variables["theme"] == t.themes[0]
    assert len(meta["adaptation"]) > 300 and len(meta["description"]) > 200
    for theme in t.themes:           # the adaptation paragraph says what each theme's stimuli stand for
        assert re.search(rf"\b{theme}:", meta["adaptation"]), (task, theme)
    assert all(r in meta["references"] for r in base_meta["references"])
    assert "generic" in meta["adaptation"] or "fictional" in meta["adaptation"]
    # the classic task's card links to its adaptation
    assert task in [a["id"] for a in library.get_task(base).adaptations]


@pytest.mark.parametrize("task", OPS)
def test_same_measures_and_flow_as_the_classic_task(task):
    ops, base = Experiment.load(TASKS_DIR / task / f"{task}.yaml"), Experiment.load(TASKS_DIR / OPS[task] / f"{OPS[task]}.yaml")
    assert [(m["id"], m["column"], m.get("summary"), m.get("loop")) for m in ops.measures] == \
           [(m["id"], m["column"], m.get("summary"), m.get("loop")) for m in base.measures]
    # the same loops (names, order, repeats) and keys
    loops = lambda text: re.findall(r"- loop: (\w+)", text)  # noqa: E731
    src_ops = (TASKS_DIR / task / f"{task}.yaml").read_text(encoding="utf-8")
    src_base = (TASKS_DIR / OPS[task] / f"{OPS[task]}.yaml").read_text(encoding="utf-8")
    assert loops(src_ops) == loops(src_base)
    keys = lambda text: sorted(set(re.findall(r"keys: (\[[^\]]*\])", text)))  # noqa: E731
    assert keys(src_ops) == keys(src_base)
    for name in SAME_LISTS.get(task, []):
        assert (TASKS_DIR / task / name).read_bytes() == (TASKS_DIR / OPS[task] / name).read_bytes(), name


def test_lists_with_new_stimuli_keep_the_design():
    # lexical decision: 20 high, 20 low, 40 non-words; 4 + 4 practice
    rows = _rows(TASKS_DIR / "ldt_ops" / "ldt_trials.csv")
    base = _rows(TASKS_DIR / "ldt" / "ldt_trials.csv")
    count = lambda rs: sorted((r["lexicality"], r["frequency"], r["corr_key"]) for r in rs)  # noqa: E731
    assert count(rows) == count(base) and len({r["letters"] for r in rows}) == 80
    assert count(_rows(TASKS_DIR / "ldt_ops" / "ldt_practice.csv")) == count(_rows(TASKS_DIR / "ldt" / "ldt_practice.csv"))
    # IAT: the same blocks, phases and roles; `item` (0-7) instead of the word
    for b in range(1, 8):
        ops, base = _rows(TASKS_DIR / "iat2_ops" / "lists" / f"block{b}.csv"), _rows(TASKS_DIR / "iat2" / "lists" / f"block{b}.csv")
        assert sorted((r["block"], r["phase"], r["role"], r["kind"], r["alternate"]) for r in ops) == \
               sorted((r["block"], r["phase"], r["role"], r["kind"], r["alternate"]) for r in base)
        assert all(0 <= int(r["item"]) <= 7 for r in ops)
    # reading: 20 items + 2 practice, the embedded verb at word 3 / 5 and the main verb at word 6 in both versions
    for n in (1, 2, 3):
        for name in ("sentences.csv", "practice.csv"):
            ops, base = _rows(TASKS_DIR / f"pacedreading{n}_ops" / name), _rows(TASKS_DIR / f"pacedreading{n}" / name)
            assert [(r["item"], r["practice"], r["answer"]) for r in ops] == [(r["item"], r["practice"], r["answer"]) for r in base]
        for r in _rows(TASKS_DIR / f"pacedreading{n}_ops" / "sentences.csv"):
            s, o = r["subject_version"].split(), r["object_version"].split()
            assert sorted(s) == sorted(o) and s[3] == o[5] and s[6] == o[6] and s[2] == o[2] == "that"
    # VAAST: 8 + 8 test stimuli, 4 + 4 (words) or 2 + 2 (pictures) practice
    for task, cats, practice in (("vaast_words_ops", {"safe", "threat"}, "practice_words.csv"),
                                 ("vaast_images_ops", {"friendly", "hostile"}, "practice_images.csv")):
        main_list = "words.csv" if task == "vaast_words_ops" else "images.csv"
        rows = _rows(TASKS_DIR / task / main_list)
        assert len(rows) == 16 and {r["valence"] for r in rows} == cats
        assert sum(r["valence"] == min(cats) for r in rows) == 8
        base_task = OPS[task]
        assert len(_rows(TASKS_DIR / task / practice)) == len(_rows(TASKS_DIR / base_task / practice.replace("_ops", "")))


@pytest.mark.parametrize("task", OPS)
def test_stimuli_are_self_contained_and_small(task):
    folder = TASKS_DIR / task
    gen = ROOT / "tools" / "library" / GENERATORS.get(task, f"make_{task}.py")
    assert gen.is_file() and task in gen.read_text(encoding="utf-8")
    own = OWN_PICTURES.get(task)
    for p in (folder / "stimuli").iterdir():
        if own and re.fullmatch(own, p.name):
            continue
        kit = list(KIT.rglob(p.name))
        assert len(kit) == 1 and kit[0].read_bytes() == p.read_bytes(), f"{task}: {p.name} is not an unchanged kit file"
    assert sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) < 2_000_000
    assert len(list((folder / "stimuli").glob("*.mp4"))) <= 1
    # every picture or video the experiment names is in the folder, and every file in stimuli/ is used
    src = (folder / f"{task}.yaml").read_text(encoding="utf-8")
    named = set(re.findall(r"stimuli/[\w.-]+\.(?:png|jpg|mp4)", src))
    assert all((folder / n).is_file() for n in named), [n for n in named if not (folder / n).is_file()]
    computed = {"fitts_ops"}        # file names worked out in an expression (target_box_{width}x260.png)
    if task not in computed:
        assert {f"stimuli/{p.name}" for p in (folder / "stimuli").iterdir()} == named


# ================================================================ every theme: validate, test run, measures
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
    measured = {r["measure"] for r in _rows(sessions[0] / "measures.csv") if r["value"] not in ("", "None", "nan")}
    outcomes = {m["id"] for m in exp.measures if m.get("role") in ("outcome", "check")}
    assert outcomes - MAY_BE_EMPTY.get(task, set()) <= measured, outcomes - measured
    rows = _rows(sessions[0] / "trials.csv")
    _check_theme_data(task, theme, exp, rows)


def _check_theme_data(task: str, theme: str, exp: Experiment, rows: list[dict[str, str]]) -> None:
    """What the theme shows ends up in the data, and only that theme's display items ran."""
    v = exp.variables
    others = [t for t in library.THEMES if t != theme]
    # items guarded for another theme never started (their onset column is empty, if it exists)
    for r in rows:
        for col, val in r.items():
            if col.endswith(".onset") and val not in ("", None) and any(col.split(".")[0].endswith(f"_{o}") for o in others):
                raise AssertionError(f"{task}/{theme}: {col} ran")
    if task == "iat2_ops":
        trials = [r for r in rows if r.get("routine") == "trial"]
        assert len(trials) == 200 and {r["key.shown_theme"] for r in trials} == {theme}
        for r in trials:
            want = v["targets"][theme][r["role"]] if r["kind"] == "target" else v["attr_words"][r["role"]]
            assert r["key.stimulus"] == want[int(r["item"])]
            if r["kind"] == "target" and v["pictures"][theme]:
                assert r["stim_pic.onset"] != "" and r.get("stim.onset", "") == ""
            else:
                assert r["stim.onset"] != ""
    if task == "mentalrotation_ops":
        trials = [r for r in rows if r.get("routine") == "trial"]
        assert len(trials) == 72
        for r in trials:
            assert r["shown.probe_pic"] == v["looks"][theme][r["shape"]][0 if r["match"] == "same" else 1]
            assert r["shown.probe_pic"].endswith("_mirror.png") == (r["match"] == "mirror")
    if task == "vaast_images_ops":
        trials = [r for r in rows if r.get("routine") == "trial"]
        assert len(trials) == 72
        for r in trials:
            assert r["cond.picture"] == v["looks"][theme][r["valence"]][int(r["item"])]
            assert r["valence"] in r["cond.picture"]
    if task in ("deary_liewald_ops", "fitts_ops") and theme == "video":
        played = [r for r in rows if r.get("feed_video.frames_shown") not in (None, "", "0")]
        assert played, "the camera feed did not play"
    if task == "bart_ops":
        outcome = [r for r in rows if r.get("routine") == "outcome"]
        assert len(outcome) == 30 and {r["result.shown_theme"] for r in outcome} == {theme}
    if task == "tower_hanoi_ops":
        ends = [r for r in rows if r.get("routine") == "problem_end"]
        assert len(ends) == 4 and {r["result.shown_theme"] for r in ends} == {theme}


def test_iat_is_about_systems_only():
    """The IAT's categories and stimuli name systems and their status, never people, nations or groups."""
    v = Experiment.load(TASKS_DIR / "iat2_ops" / "iat2_ops.yaml").variables
    assert (v["cat_a"], v["cat_b"], v["attr_pos"], v["attr_neg"]) == ("Own systems", "Other systems", "Reliable", "Unreliable")
    words = [w for t in v["targets"].values() for ws in t.values() for w in ws if not w.endswith(".png")]
    words += [w for ws in v["attr_words"].values() for w in ws]
    people = {"people", "person", "nation", "national", "country", "army", "soldier", "enemy", "ally", "allies",
              "forces", "troops", "race", "religion"}
    assert not [w for w in words if set(w.lower().split()) & people]
    assert all(w.split()[0] in ("own", "other") for t in v["targets"].values() for ws in t.values() for w in ws
               if not w.endswith(".png"))
