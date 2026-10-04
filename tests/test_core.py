import math
import random

import pytest

from edge import expressions
from edge.conditions import Staircase, balanced_latin_square, load_conditions, order_trials
from edge.model import Experiment
from edge.sync import ArrivalSync, RoundTripSync, fit_linear


# ------------------------------------------------------------------ expressions
def test_expressions_basic():
    ns = {"word": "red", "score": 3, "resp": type("R", (), {"rt": 0.5})()}
    assert expressions.resolve("$word.upper()", ns) == "RED"
    assert expressions.resolve("$score * 2 + 1", ns) == 7
    assert expressions.resolve("$f'{word}-{score}'", ns) == "red-3"
    assert expressions.resolve("$[x * 2 for x in range(score)]", ns) == [0, 2, 4]
    assert expressions.resolve("$resp.rt < 1", ns) is True
    assert expressions.resolve("$$5", ns) == "$5"
    assert expressions.resolve("plain", ns) == "plain"
    assert expressions.resolve({"a": "$score"}, ns) == {"a": 3}


@pytest.mark.parametrize("bad", [
    "__import__('os').system('true')",
    "().__class__.__bases__",
    "open('/etc/passwd')",
    "(lambda: 1)()",
    "word._secret",
])
def test_expressions_are_sandboxed(bad):
    with pytest.raises(expressions.ExpressionError):
        expressions.evaluate(bad, {"word": "x"})


# ------------------------------------------------------------------ conditions
def test_factorial_and_files(tmp_path):
    rows = load_conditions({"factorial": {"a": [1, 2], "b": ["x", "y", "z"]}, "extra": {"c": 0}}, tmp_path)
    assert len(rows) == 6 and all(r["c"] == 0 for r in rows)
    (tmp_path / "c.csv").write_text("word,n,flag\nred,1,true\nblue,2.5,false\n")
    assert load_conditions("c.csv", tmp_path) == [{"word": "red", "n": 1, "flag": True},
                                                  {"word": "blue", "n": 2.5, "flag": False}]
    (tmp_path / "c.tsv").write_text("a\tb\n1\t2\n")
    assert load_conditions("c.tsv", tmp_path) == [{"a": 1, "b": 2}]


def test_order_constraints():
    rows = [{"c": "A"}, {"c": "A"}, {"c": "B"}, {"c": "B"}, {"c": "C"}]
    rng = random.Random(1)
    for _ in range(50):
        seq = order_trials(rows, "fullrandom", 6, rng, {"c": 1})
        assert len(seq) == 30
        assert all(a["c"] != b["c"] for a, b in zip(seq, seq[1:]))


def test_per_value_max_repeat():
    rows = [{"k": "std"}] * 4 + [{"k": "dev"}]
    seq = order_trials(rows, "fullrandom", 20, random.Random(3), {"k": {"dev": 1}})
    assert not any(a["k"] == b["k"] == "dev" for a, b in zip(seq, seq[1:]))


def test_sequential_and_row_index():
    seq = order_trials([{"x": 1}, {"x": 2}], "sequential", 2, random.Random(0))
    assert [r["x"] for r in seq] == [1, 2, 1, 2]
    assert [r["_row"] for r in seq] == [0, 1, 0, 1]


def test_balanced_latin_square_is_balanced():
    for n in (4, 6):
        sq = balanced_latin_square(n)
        assert all(sorted(r) == list(range(n)) for r in sq)
        # each ordered pair (a -> b) occurs exactly once across rows
        pairs = [(r[i], r[i + 1]) for r in sq for i in range(n - 1)]
        assert len(pairs) == len(set(pairs)) == n * (n - 1)


def test_latin_square_uses_participant():
    rows = [{"c": i} for i in range(4)]
    a = [r["c"] for r in order_trials(rows, "latin_square", 1, random.Random(0), participant_index=1)]
    b = [r["c"] for r in order_trials(rows, "latin_square", 1, random.Random(0), participant_index=2)]
    assert a != b and sorted(a) == [0, 1, 2, 3]


def test_staircase_converges():
    true_thresh = 0.3
    sc = Staircase({"start": 0.8, "step": [0.1, 0.05, 0.02], "down": 3, "up": 1, "min": 0, "max": 1,
                    "reversals": 12, "max_trials": 300})
    rng = random.Random(0)
    for _ in sc:
        p = 0.5 + 0.5 / (1 + math.exp(-(sc.level - true_thresh) * 30))
        sc.update(rng.random() < p)
    assert sc.finished and abs(sc.threshold - true_thresh) < 0.12


# ------------------------------------------------------------------ sync
def test_fit_linear_recovers_offset_and_drift():
    pairs = [(d, 5.0 + 0.99998 * d) for d in range(0, 3600, 10)]
    m = fit_linear(pairs)
    assert abs(m.offset - 5.0) < 1e-6 and abs(m.slope - 0.99998) < 1e-9


def test_arrival_sync_lower_envelope():
    rng = random.Random(0)
    s = ArrivalSync(bin_seconds=1.0)
    for i in range(20000):
        true = i / 500
        dev = (true + 100) * 1.00005
        s.add(dev, true + rng.random() * 0.004)  # up to 4 ms transport delay
    m = s.model()
    for true in (0.0, 20.0, 39.0):
        assert abs(m.to_master((true + 100) * 1.00005) - true) < 0.0005


def test_roundtrip_sync():
    t = [0.0]
    rng = random.Random(1)

    def master():
        t[0] += rng.random() * 0.0005
        return t[0]

    def device():
        t[0] += rng.random() * 0.0005
        return (t[0] - 7.0) * 1.0001

    rt = RoundTripSync(device, master)
    rt.probe(400)
    m = rt.model()
    assert abs(m.to_master((10.0 - 7.0) * 1.0001) - 10.0) < 0.001


# ------------------------------------------------------------------ model
def test_validation_catches_problems(tmp_path):
    exp = Experiment.from_dict({
        "devices": [{"id": "x", "type": "no_such_device"}],
        "routines": {"r": {"components": [
            {"id": "a", "type": "text", "text": "$1 +"},
            {"id": "a", "type": "bogus"},
            {"id": "k", "type": "keyboard", "start_after": "missing"},
        ]}},
        "flow": ["r", "nope", {"loop": "L", "conditions": "missing.csv", "order": "weird", "children": ["r"]}],
    }, base_dir=tmp_path)
    msgs = [str(i) for i in exp.validate()]
    joined = "\n".join(msgs)
    for needle in ["unknown device type", "syntax error", "duplicate component id", "unknown component type",
                   "start_after", "unknown routine 'nope'", "conditions file not found", "unknown loop order"]:
        assert needle in joined, needle


def test_roundtrip_save_load(tmp_path):
    exp = Experiment.load("examples/stroop/stroop.yaml")
    exp.save(tmp_path / "copy.yaml")
    again = Experiment.load(tmp_path / "copy.yaml")
    assert again.to_dict()["flow"] == exp.to_dict()["flow"]
    assert again.to_dict()["routines"] == exp.to_dict()["routines"]
