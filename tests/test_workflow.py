"""State machines, routine rules, component-level if, live loop performance."""
import json

import pytest

from edge.export import SessionTables, wide_trials
from edge.model import Experiment
from edge.participant import VirtualParticipant

TRIAL = {"components": [
    {"id": "stim", "type": "text", "text": "$w", "duration": 0.2},
    {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$ans", "duration": 1.5, "end_routine": True}]}
CONDS = [{"w": "a", "ans": "f"}, {"w": "b", "ans": "j"}]


def machine_exp(accuracy_threshold, max_visits=3):
    return {"name": "sm",
            "routines": {"trial": TRIAL,
                         "msg": {"duration": 0.1, "components": [{"id": "t", "type": "text", "text": "x"}]},
                         "main_trial": TRIAL},
            "flow": [{"statemachine": "session", "start": "practice", "states": {
                "practice": {"run": [{"loop": "prac", "conditions": CONDS, "repeats": 2, "children": ["trial"]}],
                             "max_visits": max_visits,
                             "next": [{"if": f"$prac.accuracy >= {accuracy_threshold}", "goto": "main",
                                       "set": {"passed": True}},
                                      {"goto": "practice"}]},
                "main": {"run": [{"loop": "block", "conditions": CONDS, "repeats": 1, "children": ["main_trial"]}],
                         "next": ["end"]}}}]}


def test_repeat_until_passed(run):
    # accuracy 1.0 participant passes on the first visit
    summary, session, _ = run(machine_exp(0.75), vp=VirtualParticipant(accuracy=1.0, respond_prob=1, seed=1))
    st = summary["loops"]["session"]
    assert st["path"] == ["practice", "main"] and summary["variables"]["passed"] is True


def test_max_visits_forces_progress(run):
    # impossible criterion: practice repeats, but only max_visits times, then moves on
    summary, session, _ = run(machine_exp(2.0, max_visits=3), vp=VirtualParticipant(seed=2))
    assert summary["loops"]["session"]["path"] == ["practice", "practice", "practice", "main"]
    rows = session.data.trial_rows
    assert {r["session.visit"] for r in rows if r["session.state"] == "practice"} == {1, 2, 3}
    # trial table keeps visits apart and records state columns
    cols, wide = wide_trials(SessionTables(session.data.root))
    assert "session.state" in cols and len([r for r in wide if r.get("loop") == "prac"]) == 12


def test_loop_performance_is_live(run):
    d = {"routines": {"trial": TRIAL, "check": {"duration": 0.05, "components": [
        {"id": "v", "type": "variable", "set": {"acc_seen": "$prac.accuracy", "n_seen": "$prac.n_responses"}}]}},
         "flow": [{"loop": "prac", "conditions": CONDS, "repeats": 3, "children": ["trial", "check"]}]}
    summary, session, _ = run(d, vp=VirtualParticipant(accuracy=1.0, respond_prob=1, seed=3))
    assert summary["variables"]["n_seen"] == 6 and summary["variables"]["acc_seen"] == 1.0


def test_rule_goto_jumps_out_of_state(run):
    d = {"routines": {
        "trial": {"rules": [{"when": "$resp.keys == 'q'", "do": [{"goto": "bye"}]}],
                  "components": [{"id": "resp", "type": "keyboard", "keys": ["q", "space"], "end_routine": True}]},
        "bye": {"duration": 0.1, "components": [{"id": "t", "type": "text", "text": "bye"}]}},
        "flow": [{"statemachine": "m", "start": "task", "states": {
            "task": {"run": [{"loop": "L", "repeats": 50, "children": ["trial"]}], "next": ["end"]},
            "bye": {"run": ["bye"]}}}]}

    def script(be):
        for i, k in enumerate(["space", "space", "q"]):
            be.press(k, 1000.2 + i * 0.5)

    summary, session, _ = run(d, script=script)
    routines = [r["routine"] for r in session.data.trial_rows]
    assert routines == ["trial", "trial", "trial", "bye"]
    assert summary["loops"]["m"]["path"] == ["task", "bye"]


def test_rules_start_stop_set_marker(run):
    d = {"devices": [{"id": "ttl", "type": "ttl_loopback"}],
         "variables": {"hits": 0},
         "routines": {"r": {"duration": 2.0, "rules": [
             {"name": "show_hint", "when": "$t > 0.5", "do": [{"start": "hint"}, {"marker": "hint_on"}]},
             {"name": "count", "when": "$resp.keys is not None", "do": [{"set": {"hits": "$hits + 1"}}, "end_routine"]}],
             "components": [
                 {"id": "hint", "type": "text", "text": "hint", "start_if": "$False"},
                 {"id": "resp", "type": "keyboard", "keys": ["space"]}]}},
         "flow": ["r"]}

    def script(be):
        be.press("space", 1001.2)

    summary, session, be = run(d, script=script)
    shown = be.frames_showing(lambda k, p: p.get("text") == "hint")
    assert shown and abs(shown[0] - 31) <= 1          # forced start just after t = 0.5 s
    assert summary["variables"]["hits"] == 1
    row = session.data.trial_rows[0]
    assert row["rules_fired"] == ["show_hint", "count"] and row["routine_duration"] < 1.3
    assert "hint_on" in summary["marker_codebook"]


def test_component_if(run):
    d = {"routines": {"r": {"duration": 0.1, "components": [
        {"id": "fb", "type": "text", "text": "practice feedback", "if": "$practice"},
        {"id": "x", "type": "text", "text": "always"}]}},
         "flow": [{"loop": "L", "conditions": [{"practice": True}, {"practice": False}], "children": ["r"]}]}
    _, session, be = run(d)
    rows = session.data.trial_rows
    assert "fb.onset" in rows[0] and "fb.onset" not in rows[1]


def test_state_machine_validation(tmp_path):
    exp = Experiment.from_dict({"routines": {"r": {"duration": 1, "components": []}},
                                "flow": [{"statemachine": "m", "start": "nope", "states": {
                                    "a": {"run": ["r"], "next": [{"goto": "b"}, {"if": "$x", "goto": "a"}]},
                                    "orphan": {"run": ["r"]}}}]}, base_dir=tmp_path)
    msgs = "\n".join(str(i) for i in exp.validate())
    assert "start state 'nope' does not exist" in msgs
    assert "unknown state 'b'" in msgs
    assert "never run" in msgs
    assert "can never be reached" in msgs


def test_rule_validation(tmp_path):
    exp = Experiment.from_dict({"routines": {"r": {"duration": 1, "rules": [
        {"when": "$t > 1", "do": [{"explode": True}, {"start": "ghost"}]}, {"do": []}], "components": []}},
        "flow": ["r"]}, base_dir=tmp_path)
    msgs = "\n".join(str(i) for i in exp.validate())
    assert "unknown rule action explode" in msgs and "no component 'ghost'" in msgs and "needs 'when'" in msgs


def test_round_trip_preserves_workflow(tmp_path):
    d = machine_exp(0.8)
    d["routines"]["trial"] = dict(TRIAL, rules=[{"when": "$t > 5", "do": ["end_routine"]}])
    d["routines"]["trial"]["components"][0] = dict(TRIAL["components"][0], **{"if": "$show"})
    exp = Experiment.from_dict(d, base_dir=tmp_path)
    again = Experiment.from_dict(json.loads(json.dumps(exp.to_dict())), base_dir=tmp_path)
    assert again.to_dict()["flow"] == exp.to_dict()["flow"]
    assert again.to_dict()["routines"]["trial"]["rules"] == d["routines"]["trial"]["rules"]
    assert again.to_dict()["routines"]["trial"]["components"][0]["if"] == "$show"


def test_conditions_file_from_variable(run, tmp_path):
    (tmp_path / "a.csv").write_text("w\nA1\nA2\n")
    (tmp_path / "b.csv").write_text("w\nB1\n")
    d = {"routines": {"t": {"duration": 0.05, "components": [{"id": "x", "type": "text", "text": "$w"}]}},
         "flow": [{"loop": "blocks", "conditions": [{"block_file": "a.csv"}, {"block_file": "b.csv"}],
                   "order": "latin_square",
                   "children": [{"loop": "trials", "conditions": "$block_file", "children": ["t"]}]}]}
    _, session, _ = run(d)
    assert sorted(r["w"] for r in session.data.trial_rows) == ["A1", "A2", "B1"]
