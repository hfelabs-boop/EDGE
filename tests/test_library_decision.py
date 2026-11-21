"""Task library, group "decision": BART, IGT, IAT, lexical decision, three self-paced reading tasks, mental
rotation, Deary-Liewald, digit symbol substitution, Fitts's law, Tower of Hanoi and the two VAAST versions.

Every task: meta.yaml complete, validates without errors or warnings, a test run (virtual participant) finishes and
its measures are in measures.csv. Plus checks of each task's own logic on the recorded data."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

import pytest
import yaml

from edge.engine import run_experiment
from edge.model import Experiment
from edge.participant import VirtualParticipant

TASKS_DIR = Path(__file__).resolve().parents[1] / "edge" / "library" / "tasks"
TASKS = ["bart", "igt", "iat2", "ldt", "pacedreading1", "pacedreading2", "pacedreading3", "mentalrotation",
         "deary_liewald", "digit_substitution", "fitts", "tower_hanoi", "vaast_words", "vaast_images"]
CATEGORIES = {"Attention", "Inhibition and conflict", "Cognitive control", "Working memory", "Vigilance",
              "Decision making", "Language", "Social and implicit", "Perception and motor", "Problem solving"}
INPUTS = {"keyboard", "mouse", "touch", "keyboard+mouse"}
REQUIRED = ["id", "title", "category", "summary", "description", "measures", "duration_min", "input", "languages",
            "references", "see_also"]


def load(task: str) -> Experiment:
    return Experiment.load(TASKS_DIR / task / f"{task}.yaml")


def run(task: str, out: Path, participant: str = "001", vp: VirtualParticipant | None = None) -> Path:
    s = run_experiment(load(task), dry_run=True, data_dir=str(out), participant={"participant": participant},
                       virtual_participant=vp or VirtualParticipant(seed=7), log=lambda *a: None)
    assert not s.get("errors"), s.get("errors")
    return Path(s["data_dir"])


def rows(folder: Path, name: str = "trials_wide.csv") -> list[dict]:
    with open(folder / name, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def num(v):
    return float(v) if v not in (None, "") else None


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """One test run per task (participant 001), shared by the tests below."""
    cache: dict[str, Path] = {}

    def get(task: str) -> Path:
        if task not in cache:
            cache[task] = run(task, tmp_path_factory.mktemp(task))
        return cache[task]
    return get


# ------------------------------------------------------------------------------------------- every task
@pytest.mark.parametrize("task", TASKS)
def test_meta_complete(task):
    meta = yaml.safe_load((TASKS_DIR / task / "meta.yaml").read_text(encoding="utf-8"))
    for key in REQUIRED:
        assert meta.get(key) not in (None, "", [], {}), f"{task}: meta.yaml has no {key}"
    assert meta["id"] == task
    assert meta["category"] in CATEGORIES
    assert meta["input"] in INPUTS
    assert isinstance(meta["duration_min"], (int, float)) and 1 <= meta["duration_min"] <= 15
    assert meta["see_also"]["psytoolkit"] == f"https://www.psytoolkit.org/experiment-library/{task}.html"
    assert all(isinstance(r, str) and "(" in r for r in meta["references"])
    if meta.get("variant_of"):
        assert meta["variant_of"] in TASKS


@pytest.mark.parametrize("task", TASKS)
def test_validates_cleanly(task):
    issues = [i for i in load(task).validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(f"{i.level}: {i.where}: {i.message}" for i in issues)


@pytest.mark.parametrize("task", TASKS)
def test_test_run_records_the_measures(task, runs):
    folder = runs(task)
    exp = load(task)
    declared = [m for m in exp.measures if m.get("role", "outcome") != "factor"]
    assert declared, f"{task} declares no outcome measures"
    table = rows(folder, "measures.csv")
    have = {r["measure"] for r in table}
    for m in declared:
        assert m["id"] in have, f"{task}: measure {m['id']} missing from measures.csv"
    main = next(r for r in table if r["measure"] == declared[0]["id"])
    assert main["value"] not in ("", None), f"{task}: the main measure {declared[0]['id']} has no value"
    assert (folder / "summary.csv").exists()


# ------------------------------------------------------------------------------------------- task logic
def test_bart_bursts_and_adjusted_pumps(runs):
    data = [r for r in rows(runs("bart")) if r.get("result.balloon_pumps")]
    assert len(data) == 30
    for r in data:
        pumps, burst = int(r["result.balloon_pumps"]), int(r["result.burst_point"])
        assert 1 <= burst <= 128
        assert (r["result.exploded"] == "1") == (pumps >= burst)       # a balloon bursts exactly at its burst point
        assert pumps <= burst
    kept = [int(r["result.balloon_pumps"]) for r in data if r["result.exploded"] == "0"]
    m = {r["measure"]: r for r in rows(runs("bart"), "measures.csv")}
    assert math.isclose(float(m["adjusted_pumps"]["value"]), statistics.fmean(kept), abs_tol=1e-4)
    earned = sum(5 * int(r["result.balloon_pumps"]) for r in data if r["result.exploded"] == "0")
    assert int(m["earnings"]["value"]) == earned


def test_igt_payoffs_follow_the_schedule(runs):
    exp = load("igt")
    gains, losses = exp.variables["gains"], exp.variables["losses"]
    for deck, sched in losses.items():               # the classic net outcome per 10 cards
        for k in range(4):
            net = 10 * gains[deck] - sum(sched[10 * k:10 * k + 10])
            assert net == (-250 if deck in "AB" else 250)
    data = [r for r in rows(runs("igt")) if r["loop"] == "trials"]
    assert len(data) == 100
    drawn = {d: 0 for d in "ABCD"}
    money = 2000
    for r in data:
        d = r["card.deck"]
        assert int(r["card.win"]) == gains[d]
        assert int(r["card.loss"]) == losses[d][drawn[d] % 40]
        drawn[d] += 1
        money += gains[d] - losses[d][drawn[d] - 1]
        assert int(r["card.total"]) == money
    per_block = {r["block"]: r["value"] for r in rows(runs("igt"), "measures.csv") if r["measure"] == "net_score"}
    for b in "12345":
        want = sum(1 if r["card.deck"] in "CD" else -1 for r in data if r["block"] == b)
        assert float(per_block[b]) == want


def _d_score(data):
    lat = {b: [float(r["fix.rt"]) for r in data if r["block"] == str(b) and float(r["fix.rt"]) < 10] for b in (3, 4, 6, 7)}
    parts = [(statistics.fmean(lat[late]) - statistics.fmean(lat[early])) / statistics.stdev(lat[early] + lat[late])
             for early, late in ((3, 6), (4, 7))]
    return sum(parts) / 2


@pytest.mark.parametrize("participant,a_left_first", [("001", True), ("002", False)])
def test_iat_blocks_keys_and_d_score(tmp_path, participant, a_left_first):
    folder = run("iat2", tmp_path, participant=participant)
    data = [r for r in rows(folder) if r.get("fix.rt")]
    assert [sum(r["block"] == str(b) for r in data) for b in range(1, 8)] == [20, 20, 20, 40, 40, 20, 40]
    for r in data:
        b = int(r["block"])
        a_left = a_left_first == (b < 5)
        want = "e" if r["role"] == "positive" or (r["role"] == "target_a") == a_left and r["role"] != "negative" else "i"
        assert r["key.corr_key"] == want, r
        if b in (3, 4, 6, 7):
            assert r["pairing"] == ("compatible" if a_left else "incompatible")
    for b in (3, 4, 6, 7):          # target and attribute words take turns in the combined blocks
        kinds = [r["kind"] for r in data if r["block"] == str(b)]
        assert all(x != y for x, y in zip(kinds, kinds[1:]))
    d = float(next(r for r in rows(folder) if r.get("result.d_score"))["result.d_score"])
    sign = 1 if a_left_first else -1
    assert math.isclose(d, sign * _d_score(data), abs_tol=1e-3)


def test_ldt_lists(runs):
    data = [r for r in rows(runs("ldt")) if r["loop"] == "trials"]
    assert len(data) == 80
    assert sum(r["lexicality"] == "word" for r in data) == 40
    assert all(r["corr_key"] == ("j" if r["lexicality"] == "word" else "f") for r in data)
    assert len({r["letters"] for r in data}) == 80


@pytest.mark.parametrize("task", ["pacedreading2", "pacedreading3"])
def test_word_by_word_reading(task, runs):
    data = rows(runs(task))
    words = [r for r in data if r["loop"] == "words"]
    by_sentence: dict[str, list] = {}
    for r in words:
        by_sentence.setdefault(r["sentences.n"], []).append(r)
    assert len(by_sentence) == 20
    structures = []
    for ws in by_sentence.values():
        assert [int(r["cur.position"]) for r in ws] == list(range(len(ws)))
        sentence = " ".join(r["cur.word"] for r in ws)
        s = ws[0]["structure"]
        structures.append(s)
        assert sentence == (ws[0]["object_version"] if s == "object" else ws[0]["subject_version"])
        assert ws[6]["cur.region"] == "main_verb"
        assert ws[3 if s == "subject" else 5]["cur.region"] == "embedded_verb"
    assert structures.count("subject") == structures.count("object") == 10


def test_reading_versions_swap_between_participants(tmp_path):
    def versions(participant):
        data = rows(run("pacedreading1", tmp_path / participant, participant))
        return {r["item"]: r["setup.structure"] for r in data if r["loop"] == "sentences" and r.get("setup.structure")}
    a, b = versions("001"), versions("002")
    assert set(a) == set(b) and len(a) == 20
    assert all(a[i] != b[i] for i in a)


def test_mental_rotation_design(runs):
    data = [r for r in rows(runs("mentalrotation")) if r["loop"] == "trials"]
    assert len(data) == 64
    assert {int(r["disparity"]) for r in data} == {0, 45, 90, 135, 180}
    assert all(r["corr_key"] == ("f" if r["match"] == "same" else "j") for r in data)


def test_mental_rotation_shapes_are_chiral():
    """No mirror image of a shape can be turned (in 90-degree steps, on its grid) into the shape itself."""
    for cells in load("mentalrotation").variables["shapes"].values():
        def norm(pts):
            pts = [(round(x * 2), round(y * 2)) for x, y in pts]
            mx, my = min(p[0] for p in pts), min(p[1] for p in pts)
            return sorted((x - mx, y - my) for x, y in pts)
        rots = [cells]
        for _ in range(3):
            rots.append([(-y, x) for x, y in rots[-1]])
        mirrored = [(-x, y) for x, y in cells]
        assert norm(mirrored) not in [norm(r) for r in rots]


def test_deary_liewald_blocks(runs):
    data = [r for r in rows(runs("deary_liewald")) if r.get("phase") == "test"]
    assert sum(r["task"] == "simple" for r in data) == 20
    choice = [r for r in data if r["task"] == "choice"]
    assert len(choice) == 40 and all(sum(r["box"] == str(b) for r in choice) == 10 for b in range(1, 5))
    waits = [float(r["wait_time.delay"]) for r in data]
    assert all(1.0 <= w <= 3.0 for w in waits) and len(set(waits)) > 10


def test_digit_symbol_lasts_90_seconds(runs):
    data = [r for r in rows(runs("digit_substitution")) if r["loop"] == "test"]
    total = sum(float(r["item.duration"]) for r in data)
    assert 89.5 <= total <= 90.6
    assert all(r["resp.corr"] == ("1" if r["resp.keys"] == r["digit"] else "0") for r in data if r["resp.keys"])
    m = {r["measure"]: r for r in rows(runs("digit_substitution"), "measures.csv")}
    assert int(float(m["n_correct"]["value"])) == sum(r["resp.corr"] == "1" for r in data)


def test_fitts_index_and_fit(runs):
    data = [r for r in rows(runs("fitts")) if r["loop"] == "trials"]
    assert len(data) == 36
    for r in data:
        assert math.isclose(float(r["index_of_difficulty"]),
                            math.log2(2 * float(r["distance"]) / float(r["width"])), abs_tol=0.01)
    hits = [(float(r["index_of_difficulty"]), float(r["click.rt"])) for r in data if r["click.corr"] == "1"]
    mx, my = statistics.fmean(p[0] for p in hits), statistics.fmean(p[1] for p in hits)
    slope = sum((x - mx) * (y - my) for x, y in hits) / sum((x - mx) ** 2 for x, _ in hits)
    fit = next(r for r in rows(runs("fitts")) if r.get("fit.slope"))
    assert math.isclose(float(fit["fit.slope"]), slope, abs_tol=1e-3)
    assert math.isclose(float(fit["fit.intercept"]), my - slope * mx, abs_tol=1e-3)


class HanoiSolver(VirtualParticipant):
    """Clicks an optimal solution, after first trying one illegal move (a larger disk onto a smaller one)."""

    def respond(self, component, allowed, correct, backend):
        if component.type_name != "mouse" or component.run.routine.id != "board":
            return super().respond(component, allowed, correct, backend)
        v = component.session.vars
        ns = component.run.namespace()
        if v["moves"] == 0 and not getattr(self, "queue", None):
            n, a, c = ns["n_disks"], ns["start_peg"], ns["goal_peg"]
            b = 3 - a - c

            def solve(k, src, dst, via):
                return [] if k == 0 else solve(k - 1, src, via, dst) + [(src, dst)] + solve(k - 1, via, dst, src)
            self.queue = [a, b, a, b, b, a] + [p for move in solve(n, a, c, b) for p in move]
        peg = self.queue.pop(0)
        pos = component.run.components[f"zone{peg}"].stim.props["pos"]
        backend.move_mouse(pos, component.t_start + 0.25)
        backend.click(pos, component.t_start + 0.3)


def test_tower_of_hanoi_moves_and_violations(tmp_path):
    folder = run("tower_hanoi", tmp_path, vp=HanoiSolver(seed=1))
    res = [r for r in rows(folder) if r.get("result.moves") and r["loop"] == "problems"]
    assert len(res) == 3
    for r in res:
        assert r["result.solved"] == "1"
        assert r["result.violations"] == "1"                     # the refused move
        assert int(r["result.excess_moves"]) == 2                # disk 1 out and back
        assert int(r["result.moves"]) == int(r["min_moves"]) + 2
        assert float(r["result.solve_time"]) > 0


@pytest.mark.parametrize("task,pos", [("vaast_words", "pleasant"), ("vaast_images", "smiling")])
def test_vaast_keys_follow_the_block_rule(task, pos, tmp_path):
    for participant, first in (("001", pos), ("002", None)):
        data = [r for r in rows(run(task, tmp_path / participant, participant)) if r.get("resp.rt") is not None and r.get("valence")]
        for r in data:
            approach = r["approach"]
            assert r["cond.corr_key"] == ("y" if r["valence"] == approach else "n")
            assert r["cond.movement"] == ("approach" if r["valence"] == approach else "avoid")
        block1 = {r["approach"] for r in data if r["block"] == "1"}
        block2 = {r["approach"] for r in data if r["block"] == "2"}
        assert len(block1) == len(block2) == 1 and block1 != block2
        if first:
            assert block1 == {first}
        tests = [r for r in data if r["phase"] == "test"]
        assert len(tests) == 64


def test_vaast_pictures_exist():
    exp_dir = TASKS_DIR / "vaast_images"
    for name in ("images.csv", "practice_images.csv"):
        with open(exp_dir / name, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                p = exp_dir / r["stimulus"]
                assert p.exists() and p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
