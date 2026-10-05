"""Design wizard: a finished, runnable experiment from a handful of plain answers.

The builder's "New experiment → Guided" dialog, ``edge wizard`` and the MCP server all call
:func:`build_experiment`. Every answer is optional; sensible defaults give a working task.

    answers = {
        "name": "word_task",
        "stimulus": {"kind": "word",                 # word | picture | sound | shape
                     "items": [{"stimulus": "RED", "correct": "f", "condition": "colour"}, ...]},
        "response": {"kind": "keys", "keys": ["f", "j"]},   # keys | mouse | rating | none
        "timing": {"fixation": 0.5, "stimulus_duration": None, "response_deadline": 2.0, "iti": 0.5},
        "feedback": True,
        "practice": {"mode": "until", "criterion": 0.8, "max_rounds": 3},   # none | once | until
        "blocks": {"count": 2, "repeats": 1, "order": "random", "break_text": "..."},
        "instructions": "...", "thanks": "...",
        "devices": ["sim_eyetracker"],
        "questionnaires": ["consent", "demographics", "tipi"],   # from edge/survey_library.py
    }
"""

from __future__ import annotations

import re
from typing import Any

STIMULUS_KINDS = ("word", "picture", "sound", "shape")
RESPONSE_KINDS = ("keys", "mouse", "rating", "none")
PRACTICE_MODES = ("none", "once", "until")

_DEFAULT_ITEMS = {
    "word": [{"stimulus": "LEFT", "correct": "f", "condition": "left"},
             {"stimulus": "RIGHT", "correct": "j", "condition": "right"}],
    "picture": [{"stimulus": "images/cat.png", "correct": "f", "condition": "animal"},
                {"stimulus": "images/car.png", "correct": "j", "condition": "object"}],
    "sound": [{"stimulus": "440", "correct": "f", "condition": "low"},
              {"stimulus": "880", "correct": "j", "condition": "high"}],
    "shape": [{"stimulus": "circle", "correct": "f", "condition": "round"},
              {"stimulus": "rect", "correct": "j", "condition": "square"}],
}


class WizardError(ValueError):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", str(text or "").strip()).strip("_").lower()
    if not s:
        return "my_experiment"
    return s if not s[0].isdigit() else "x_" + s


def _num(v: Any, default: float | None) -> float | None:
    if v in (None, "", "none", "None"):
        return default if v is None else None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise WizardError(f"'{v}' is not a number of seconds") from None


def _instructions(rid_text: str, key: str = "space") -> dict[str, Any]:
    return {"components": [
        {"id": "message", "type": "text", "text": rid_text, "height": 28, "wrap_width": 1000},
        {"id": "go", "type": "keyboard", "keys": [key], "end_routine": True}]}


def _stimulus_component(kind: str, start: float, duration: float | None) -> dict[str, Any]:
    base: dict[str, Any] = {"id": kind, "start": start}   # never "stimulus": that's the column name
    if duration is not None:
        base["duration"] = duration
    if kind == "word":
        base.update(type="text", text="$stimulus", height=60)
    elif kind == "picture":
        base.update(type="image", image="$stimulus", size=[400, 400])
    elif kind == "sound":
        base.update(type="sound", sound="$stimulus")
        base.pop("duration", None)
        base["tone_duration"] = duration or 0.3
        return base
    elif kind == "shape":
        base.update(type="shape", shape="$stimulus", size=[200, 200], fill="white")
    base["marker"] = "$f'stim_{condition}'"
    return base


def _response_component(resp: dict[str, Any], start: float, deadline: float | None, has_correct: bool,
                        stimulus_duration: float | None) -> list[dict[str, Any]]:
    kind = resp.get("kind", "keys")
    comps: list[dict[str, Any]] = []
    if kind == "none":
        return comps
    c: dict[str, Any] = {"id": "response", "start": start}
    if kind == "keys":
        keys = [str(k).strip() for k in (resp.get("keys") or ["f", "j"]) if str(k).strip()]
        if not keys:
            raise WizardError("give at least one response key")
        c.update(type="keyboard", keys=keys, end_routine=True)
        if has_correct:
            c["correct"] = "$correct"
    elif kind == "mouse":
        c.update(type="mouse", buttons=["left"], end_routine=True)
        if resp.get("_clickable", True):
            c["clickable"] = [resp.get("_target", "word")]
    elif kind == "rating":
        ticks = int(resp.get("ticks") or 7)
        labels = resp.get("labels") or ["not at all", "very much"]
        c.update(type="slider", ticks=list(range(1, ticks + 1)), labels=list(labels), end_routine=True,
                 pos=[0, -250])
    else:
        raise WizardError(f"unknown response kind '{kind}' (choose: {', '.join(RESPONSE_KINDS)})")
    if deadline is not None:
        c["duration"] = deadline
    comps.append(c)
    return comps


def build_experiment(answers: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn wizard answers into an experiment document (a dict ready to save)."""
    a = dict(answers or {})
    stim = dict(a.get("stimulus") or {})
    kind = stim.get("kind", "word")
    if kind not in STIMULUS_KINDS:
        raise WizardError(f"unknown stimulus kind '{kind}' (choose: {', '.join(STIMULUS_KINDS)})")
    resp = dict(a.get("response") or {"kind": "keys"})
    rkind = resp.get("kind", "keys")
    items = [dict(i) for i in (stim.get("items") or _DEFAULT_ITEMS[kind]) if isinstance(i, dict)]
    items = [i for i in items if str(i.get("stimulus", "")).strip()]
    if not items:
        raise WizardError("add at least one stimulus")
    has_correct = rkind == "keys" and any(str(i.get("correct", "")).strip() for i in items)
    keys = resp.get("keys") or sorted({str(i["correct"]).strip() for i in items if str(i.get("correct", "")).strip()}) \
        or ["f", "j"]
    resp["keys"] = keys
    if has_correct:
        bad = sorted({str(i.get("correct")).strip() for i in items} - set(map(str, keys)) - {""})
        if bad:
            raise WizardError(f"correct answer(s) {', '.join(bad)} are not among the response keys ({', '.join(keys)})")
    rows = []
    for i in items:
        row = {"stimulus": _cell(i.get("stimulus")), "condition": str(i.get("condition") or "").strip() or "all"}
        if has_correct:
            row["correct"] = str(i.get("correct", "")).strip()
        rows.append(row)

    timing = dict(a.get("timing") or {})
    fixation = _num(timing.get("fixation"), 0.5) or 0.0
    stim_dur = _num(timing.get("stimulus_duration"), None)
    deadline = _num(timing.get("response_deadline"), 2.0 if rkind == "keys" else None)
    iti = _num(timing.get("iti"), 0.5) or 0.0

    trial: list[dict[str, Any]] = []
    if fixation > 0:
        trial.append({"id": "fixation", "type": "fixation", "duration": fixation})
    trial.append(_stimulus_component(kind, fixation, stim_dur))
    resp["_clickable"] = kind != "sound"
    resp["_target"] = kind
    trial += _response_component(resp, fixation, deadline, has_correct, stim_dur)
    trial_routine: dict[str, Any] = {"description": "one trial: fixation, stimulus, response", "components": trial}
    if rkind == "none":
        trial_routine["duration"] = fixation + (stim_dur or 2.0)
    elif deadline is None and stim_dur is None and rkind == "mouse":
        pass

    routines: dict[str, Any] = {}
    name = _slug(a.get("name") or "my_experiment")
    instructions = a.get("instructions") or _default_instructions(kind, rkind, keys, rows if has_correct else [])
    routines["instructions"] = _instructions(instructions + "\n\nPress SPACE to begin.")
    routines["trial"] = trial_routine
    feedback = bool(a.get("feedback")) and has_correct
    if feedback:
        routines["feedback"] = {"description": "correct / wrong / too slow", "duration": 0.8, "components": [
            {"id": "message", "type": "text", "height": 40,
             "text": "$'Too slow' if response.keys is None else ('Correct!' if response.corr else 'Wrong')",
             "color": "$'#dddddd' if response.keys is None else ('#55dd55' if response.corr else '#ff5555')"}]}
    if iti > 0:
        routines["pause"] = {"description": "blank screen between trials", "duration": iti,
                             "components": [{"id": "blank", "type": "wait"}]}

    def trial_children(with_feedback: bool) -> list[Any]:
        ch: list[Any] = ["trial"]
        if with_feedback:
            ch.append("feedback")
        if iti > 0:
            ch.append("pause")
        return ch

    blocks = dict(a.get("blocks") or {})
    n_blocks = max(int(blocks.get("count") or 1), 1)
    repeats = max(int(blocks.get("repeats") or 1), 1)
    order = blocks.get("order") or "random"
    flow: list[Any] = ["instructions"]

    practice = dict(a.get("practice") or {})
    pmode = practice.get("mode", "none") if rkind != "none" else "none"
    if pmode not in PRACTICE_MODES:
        raise WizardError(f"unknown practice mode '{pmode}' (choose: {', '.join(PRACTICE_MODES)})")
    practice_loop = {"loop": "practice", "conditions": rows, "order": "random",
                     "repeats": max(int(practice.get("repeats") or 1), 1),
                     "children": trial_children(has_correct)}
    if has_correct and "feedback" not in routines:
        routines["feedback"] = {"description": "correct / wrong / too slow (practice)", "duration": 0.8, "components": [
            {"id": "message", "type": "text", "height": 40,
             "text": "$'Too slow' if response.keys is None else ('Correct!' if response.corr else 'Wrong')",
             "color": "$'#dddddd' if response.keys is None else ('#55dd55' if response.corr else '#ff5555')"}]}
    elif not has_correct and pmode != "none":
        practice_loop["children"] = trial_children(False)
    if pmode != "none":
        routines["ready"] = _instructions("Practice is over. The real task starts now.\n\nPress SPACE to begin.")

    main_children: list[Any] = []
    if n_blocks == 1:
        main_children = [{"loop": "trials", "conditions": rows, "order": order, "repeats": repeats,
                          "children": trial_children(feedback)}]
    else:
        routines["block_break"] = _instructions(
            blocks.get("break_text") or "Take a short break.\n\nPress SPACE when you are ready to continue.")
        main_children = [{"loop": "blocks", "repeats": n_blocks, "children": [
            {"loop": "trials", "conditions": rows, "order": order, "repeats": repeats,
             "children": trial_children(feedback)},
            {"if": "$not blocks.last", "then": ["block_break"]}]}]

    if pmode == "until" and has_correct:
        crit = float(practice.get("criterion") or 0.8)
        rounds = max(int(practice.get("max_rounds") or 3), 1)
        flow.append({"statemachine": "session", "start": "practice", "states": {
            "practice": {"run": [practice_loop], "max_visits": rounds,
                         "next": [{"if": f"$practice.accuracy is not None and practice.accuracy >= {crit:g}",
                                   "goto": "main"}, {"goto": "practice"}],
                         "description": f"repeat practice until {crit:.0%} correct (at most {rounds}×)"},
            "main": {"run": ["ready"] + main_children}}})
    else:
        if pmode in ("once", "until"):
            flow += [practice_loop, "ready"]
        flow += main_children
    # questionnaires: consent and demographics before the task, everything else after it
    chosen = [str(x) for x in a.get("questionnaires") or []]
    from .survey_library import INSTRUMENTS
    unknown = [x for x in chosen if x not in INSTRUMENTS]
    if unknown:
        raise WizardError(f"unknown questionnaire(s) {', '.join(unknown)} (available: {', '.join(INSTRUMENTS)})")
    before = [x for x in chosen if x in ("consent", "demographics")]
    after = [x for x in chosen if x not in before]
    if "consent" in before:
        routines["consent"] = {"description": "information and consent", "components": [
            {"id": "consent_form", "type": "survey", "end_routine": True, "questions": [{"instrument": "consent"}]}]}
        flow.insert(0, "consent")
    if "demographics" in before:
        routines["about_you"] = {"description": "demographics", "components": [
            {"id": "about_you", "type": "survey", "end_routine": True, "title": "About you",
             "questions": [{"instrument": "demographics"}]}]}
        flow.insert(1 if "consent" in before else 0, "about_you")
    if after:
        qs: list[Any] = []
        for i, x in enumerate(after):
            if i:
                qs.append({"type": "page_break"})
            qs.append({"instrument": x})
        routines["questionnaires"] = {"description": "questionnaires after the task", "components": [
            {"id": "questionnaires", "type": "survey", "end_routine": True, "title": "A few more questions",
             "questions": qs}]}
        flow.append("questionnaires")
    routines["thanks"] = {"duration": 3, "components": [
        {"id": "message", "type": "text", "text": a.get("thanks") or "Thank you! You're done.", "height": 32}]}
    flow.append("thanks")
    if "feedback" in routines and not _uses(flow, "feedback"):
        del routines["feedback"]

    devices = []
    for d in a.get("devices") or []:
        dtype = d if isinstance(d, str) else d.get("type")
        if dtype:
            devices.append({"id": _device_id(dtype, devices), "type": dtype})
    doc: dict[str, Any] = {
        "name": name,
        "description": a.get("description") or f"Made with the EDGE design wizard: {kind} stimuli, {rkind} responses.",
        "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
        "devices": devices,
        "routines": routines,
        "flow": flow,
    }
    if kind == "picture":
        doc["description"] += " Put your images in the images/ folder next to this file."
    try:   # say what the experiment measures, so the summary and the checks focus on it
        from .measures import suggest_measures
        from .model import Experiment
        ms = suggest_measures(Experiment.from_dict(doc))
        if ms:
            doc["measures"] = ms
    except Exception:
        pass
    return doc


def _cell(v: Any) -> Any:
    s = str(v).strip()
    try:
        return int(s) if s.lstrip("-").isdigit() else float(s) if re.fullmatch(r"-?\d+\.\d*", s) else s
    except ValueError:
        return s


def _uses(nodes: list[Any], rid: str) -> bool:
    for n in nodes:
        if n == rid:
            return True
        if isinstance(n, dict):
            for k in ("children", "then", "else"):
                if _uses(n.get(k) or [], rid):
                    return True
            for st in (n.get("states") or {}).values():
                if _uses(st.get("run") or [], rid):
                    return True
    return False


def _device_id(dtype: str, existing: list[dict]) -> str:
    base = {"tobii": "eyetracker", "gazepoint": "eyetracker", "sim_eyetracker": "eyetracker",
            "mouse_gaze": "eyetracker", "gtec": "eeg", "sim_eeg": "eeg", "mindware": "physio",
            "sim_physio": "physio", "lsl_markers": "lsl", "ttl_serial": "ttl", "ttl_loopback": "ttl",
            "parallel_port": "ttl"}.get(dtype, _slug(dtype))
    ids = {d["id"] for d in existing}
    out, n = base, 2
    while out in ids:
        out, n = f"{base}{n}", n + 1
    return out


def _default_instructions(kind: str, rkind: str, keys: list[str], rows: list[dict]) -> str:
    what = {"word": "words", "picture": "pictures", "sound": "sounds", "shape": "shapes"}[kind]
    if rkind == "keys" and rows:
        pairs = {}
        for r in rows:
            pairs.setdefault(r["correct"], [])
            if r["condition"] not in pairs[r["correct"]]:
                pairs[r["correct"]].append(r["condition"])
        lines = [f"Press {k.upper()} for {' / '.join(v)}" for k, v in pairs.items()]
        return f"You will see {what}.\n" + "\n".join(lines) + "\n\nAnswer as quickly and accurately as you can."
    if rkind == "keys":
        return f"You will see {what}. Respond with {', '.join(k.upper() for k in keys)}."
    if rkind == "mouse":
        return f"You will see {what}. Click on each one."
    if rkind == "rating":
        return f"You will see {what}. Rate each one on the scale."
    return f"You will see {what}. Just watch."


def estimate(doc: dict[str, Any], base_dir=None) -> dict[str, Any]:
    """Quick estimate of trial count and session length (no run needed)."""
    from pathlib import Path

    from .model import Experiment
    exp = Experiment.from_dict(doc, base_dir=Path(base_dir) if base_dir else Path.cwd())
    return estimate_experiment(exp)


def estimate_experiment(exp) -> dict[str, Any]:
    """Expected number of trials and minutes, assuming ~0.7 s responses and ~3 s on instruction screens."""
    from .model import Branch, Loop, RoutineRef, StateMachine
    from .scope import loop_columns

    def routine_seconds(rid: str) -> float:
        r = exp.routines.get(rid)
        if r is None:
            return 0.0
        if isinstance(r.duration, (int, float)):
            return float(r.duration)
        end = 0.0
        waits_for_response = False
        for c in r.components:
            if c.type == "survey":
                end = max(end, survey_seconds(c.props.get("questions") or []))
                waits_for_response = True
                continue
            start = c.start if isinstance(c.start, (int, float)) else 0.0
            dur = c.duration if isinstance(c.duration, (int, float)) else None
            if c.end_routine:
                waits_for_response = True
                end_c = start + (min(dur, 0.7) if dur is not None else (0.7 if c.type in ("keyboard", "mouse", "slider")
                                                                        and start > 0 else 3.0))
            else:
                end_c = start + (dur or 0.0)
            end = max(end, end_c)
        if not waits_for_response and end == 0:
            end = 1.0
        return end

    def count(nodes, mult: float) -> tuple[float, float]:
        trials = secs = 0.0
        for n in nodes:
            if isinstance(n, RoutineRef):
                secs += routine_seconds(n.routine) * mult
            elif isinstance(n, Loop):
                if n.staircase:
                    reps = float(n.staircase.get("max_trials", 50))
                else:
                    cols = loop_columns(n, exp.base_dir)
                    rows = _row_count(n, exp.base_dir) if cols is not None else 1
                    r = n.repeats if isinstance(n.repeats, (int, float)) else 1
                    reps = max(rows, 1) * r
                t, s = count(n.children, mult * reps)
                has_inner_loop = any(isinstance(c, Loop) for c in n.children)
                trials += t if has_inner_loop or t else 0
                if not has_inner_loop and not t:
                    trials += mult * reps
                secs += s
            elif isinstance(n, Branch):
                t, s = count(n.then, mult)
                trials += t
                secs += s
            elif isinstance(n, StateMachine):
                for st in n.states.values():
                    t, s = count(st.run, mult)
                    trials += t
                    secs += s
        return trials, secs

    trials, secs = count(exp.flow, 1.0)
    return {"trials": int(round(trials)), "seconds": round(secs, 1), "minutes": round(secs / 60, 1),
            "text": (f"{int(round(trials))} trials, about {_minutes(secs)}" if round(trials)
                     else f"about {_minutes(secs)}")}


def survey_seconds(questions: list[Any]) -> float:
    """Typical time to answer: published minutes for library questionnaires, ~4 s per own item."""
    from .survey import answer_ids, expand
    from .survey_library import INSTRUMENTS
    secs = 0.0
    for q in questions:
        if isinstance(q, dict) and q.get("instrument") in INSTRUMENTS:
            secs += float(INSTRUMENTS[q["instrument"]]["minutes"]) * 60
        elif isinstance(q, dict):
            try:
                flat, _ = expand([q])
                secs += 4.0 * sum(max(len(answer_ids(x)), 0) for x in flat) + (3.0 if q.get("type") == "text_block" else 0)
            except Exception:
                secs += 4.0
    return max(secs, 3.0)


def _row_count(loop, base_dir) -> int:
    from .conditions import load_conditions
    try:
        return len(load_conditions(loop.conditions, base_dir)) if loop.conditions is not None else 1
    except Exception:
        return 1


def _minutes(secs: float) -> str:
    if secs < 90:
        return f"{max(int(round(secs)), 1)} seconds"
    return f"{round(secs / 60):.0f} minutes"
