"""Design wizard: a finished, runnable experiment from a handful of plain answers.

The builder's "New experiment → Guided" dialog, ``edge wizard`` and the MCP server all call
:func:`build_experiment`. Every answer is optional; sensible defaults give a working task.

    answers = {
        "name": "word_task",
        "stimulus": {"kind": "word",                 # word | picture | sound | shape
                     "items": [{"stimulus": "RED", "correct": "f", "condition": "colour"}, ...]},
        "response": {"kind": "keys", "keys": ["f", "j"]},   # keys | buttons | mouse | rating | none
        "timing": {"fixation": 0.5, "stimulus_duration": None, "response_deadline": 2.0, "iti": 0.5},
        "feedback": True,
        "practice": {"mode": "until", "criterion": 0.8, "max_rounds": 3},   # none | once | until
        "blocks": {"count": 2, "repeats": 1, "order": "random", "break_text": "..."},
        "instructions": "...", "thanks": "...",
        "devices": ["sim_eyetracker"],
        "questionnaires": ["consent", "demographics", "tipi"],   # from edge/survey_library.py
    }

``buttons`` answers with a response box (the first one in ``devices``; a simulated one is added when there
is none). Answers that can't work are refused with a :class:`WizardError` that says what to change; answers
that were adjusted or left out are explained in the ``notes`` list :func:`build_experiment` fills in.
"""

from __future__ import annotations

import difflib
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

STIMULUS_KINDS = ("word", "picture", "sound", "shape")
RESPONSE_KINDS = ("keys", "buttons", "mouse", "rating", "none")
PRACTICE_MODES = ("none", "once", "until")
_WHAT = {"word": "words", "picture": "pictures", "sound": "sounds", "shape": "shapes"}
_ANSWERED = {"keys": "answered with key presses", "buttons": "answered with a response box",
             "mouse": "answered with mouse clicks", "rating": "answered with ratings",
             "none": "with no response (participants just watch or listen)"}
_NOUN = {"keys": "key presses", "buttons": "button presses", "mouse": "mouse clicks", "rating": "ratings",
         "none": "no responses"}
_SOUND_FILES = (".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff", ".m4a")

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
    s = str(text or "").strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")   # é -> e, ø -> (dropped)
    s = re.sub(r"[^0-9a-zA-Z_]+", "_", s).strip("_").lower()
    if not s:
        return "my_experiment"
    return s if not s[0].isdigit() else "x_" + s


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _section(a: dict[str, Any], key: str, takes: str) -> dict[str, Any]:
    v = a.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise WizardError(f"the '{key}' answer must be a set of named answers ({takes}), not {_text(v)[:40]!r}")
    return dict(v)


def _num(v: Any, default: float | None, label: str = "", *, zero_ok: bool = True, hint: str = "") -> float | None:
    """Seconds: empty = ``default`` (None) / no value ("none"); never negative; 0 only where it means 'none'."""
    if v is None or (isinstance(v, str) and v.strip() in ("", "none", "None")):
        return default if v is None else None
    try:
        x = float(v)
        if isinstance(v, bool) or not math.isfinite(x):
            raise ValueError
    except (TypeError, ValueError):
        raise WizardError(f"{label}: '{v}' is not a number of seconds" if label else
                          f"'{v}' is not a number of seconds") from None
    if x < 0:
        raise WizardError(f"{label} can't be negative (you gave {v}){hint}")
    if x == 0 and not zero_ok:
        raise WizardError(f"{label} must be more than 0 seconds (you gave {v}){hint}")
    return x


def _int(v: Any, default: int, label: str, minimum: int = 1) -> int:
    """A whole number (``"3"`` and ``3.0`` are fine), at least ``minimum``; empty = ``default``."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    try:
        x = float(v)
        if isinstance(v, bool) or not math.isfinite(x) or x != int(x):
            raise ValueError
    except (TypeError, ValueError):
        raise WizardError(f'{label} must be a whole number (you gave "{v}")') from None
    if x < minimum:
        raise WizardError(f"{label} must be at least {minimum} (you gave {v})")
    return int(x)


def _key(v: Any, rkind: str, where: str = "") -> str:
    """A key as the keyboard names it (F -> f, Enter -> return), or a response-box button name as given."""
    s = _text(v)
    if not s:
        return ""
    if rkind == "keys":
        from .importers.base import key_name
        s = key_name(s)
    if re.search(r"\s", s) or len(s) > 30:
        raise WizardError(f"{where}'{s}' is not a {'key' if rkind == 'keys' else 'button'} name: a "
                          f"{'key' if rkind == 'keys' else 'button'} name is one word, such as "
                          f"{'f, j, space or left' if rkind == 'keys' else 'left, right or 1'}"
                          + (" (if this row is a header, leave it out)" if where else ""))
    return s


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
    elif kind == "shape":
        base.update(type="shape", shape="$stimulus", size=[200, 200], fill="white")
    base["marker"] = "$f'stim_{condition}'"      # every onset: EEG / TTL / LSL get a trigger to time-lock to
    return base


def _response_component(resp: dict[str, Any], start: float, deadline: float | None, has_correct: bool,
                        stimulus_duration: float | None) -> list[dict[str, Any]]:
    kind = resp.get("kind", "keys")
    comps: list[dict[str, Any]] = []
    if kind == "none":
        return comps
    c: dict[str, Any] = {"id": "response", "start": start}
    if kind in ("keys", "buttons"):
        keys = list(resp.get("keys") or [])
        if not keys:
            raise WizardError(f"give at least one response {'key' if kind == 'keys' else 'button'}")
        if kind == "keys":
            c.update(type="keyboard", keys=keys, end_routine=True)
        else:      # the box's buttons, and the same-named keys as a stand-in for Try it and piloting
            from .importers.base import key_name
            c.update(type="device_response", device=resp["_device"], inputs=keys, end_routine=True,
                     keys={key_name(k): k for k in keys if re.fullmatch(r"[A-Za-z0-9]+", k)})
        if has_correct:
            c["correct"] = "$correct"
    elif kind == "mouse":
        c.update(type="mouse", buttons=["left"], end_routine=True)
        if resp.get("_clickable", True):
            c["clickable"] = [resp.get("_target", "word")]
    elif kind == "rating":
        ticks = _int(resp.get("ticks"), 7, "Points on the rating scale", minimum=2)
        labels = resp.get("labels") or ["not at all", "very much"]
        if isinstance(labels, str):
            labels = [x.strip() for x in re.split(r"[,/]", labels) if x.strip()]
        if not isinstance(labels, list):
            raise WizardError("the rating scale's end labels must be a list, e.g. [not at all, very much]")
        c.update(type="slider", ticks=list(range(1, ticks + 1)), labels=[_text(x) for x in labels],
                 end_routine=True, pos=[0, -250])
    else:
        raise WizardError(f"unknown response kind '{kind}' (choose: {', '.join(RESPONSE_KINDS)})")
    if deadline is not None:
        c["duration"] = deadline
    comps.append(c)
    return comps


def _feedback_routine(rkind: str, practice_only: bool = False) -> dict[str, Any]:
    # a correctly withheld response (go/no-go: no correct key) is 'Correct!', not 'Too slow'
    nothing = "response.keys is None" if rkind == "keys" else "response.input is None"
    return {"description": "correct / wrong / too slow" + (" (practice)" if practice_only else ""), "duration": 0.8,
            "components": [{"id": "message", "type": "text", "height": 40,
                            "text": f"$'Correct!' if response.corr else ('Too slow' if {nothing} else 'Wrong')",
                            "color": f"$'#55dd55' if response.corr else ('#dddddd' if {nothing} else '#ff5555')"}]}


def build_experiment(answers: dict[str, Any] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    """Turn wizard answers into an experiment document (a dict ready to save).

    Raises :class:`WizardError` (in plain words) for answers that can't work. Pass a list as ``notes`` to
    hear about answers that were filled in, adjusted or left out (show them to the researcher)."""
    if answers is not None and not isinstance(answers, dict):
        raise WizardError("the answers must be a set of named answers, e.g. "
                          "{\"stimulus\": {\"kind\": \"word\"}, \"response\": {\"kind\": \"keys\"}}")
    notes = notes if notes is not None else []
    a = dict(answers or {})
    stim = _section(a, "stimulus", "kind, items")
    kind = stim.get("kind") or "word"
    if kind not in STIMULUS_KINDS:
        raise WizardError(f"unknown stimulus kind '{kind}' (choose: {', '.join(STIMULUS_KINDS)})")
    resp = _section(a, "response", "kind, keys, ticks, labels") or {"kind": "keys"}
    rkind = resp.get("kind") or "keys"
    if rkind not in RESPONSE_KINDS:
        raise WizardError(f"unknown response kind '{rkind}' (choose: {', '.join(RESPONSE_KINDS)})")
    raw_items = stim.get("items")
    if raw_items is None:
        raw_items = [dict(i) for i in _DEFAULT_ITEMS[kind]]
        if rkind == "buttons":
            for i, button in zip(raw_items, ("left", "right")):
                i["correct"] = button
        notes.append(f"No stimuli were given, so the examples {' and '.join(str(i['stimulus']) for i in raw_items)} "
                     "were used: replace them with your own.")
    if not isinstance(raw_items, list):
        raise WizardError("the stimuli must be a list of rows, e.g. [{\"stimulus\": \"RED\", \"correct\": \"f\"}]")
    items = []
    for i in raw_items:
        if isinstance(i, (str, int, float)) and not isinstance(i, bool):
            i = {"stimulus": i}
        if not isinstance(i, dict):
            raise WizardError("each stimulus must be a row with stimulus, correct and condition, "
                              "e.g. {\"stimulus\": \"RED\", \"correct\": \"f\", \"condition\": \"red\"}")
        if _text(i.get("stimulus")):
            items.append(dict(i))
    if not items:
        raise WizardError("add at least one stimulus")
    if kind == "picture":      # bare file names live in images/, as the builder and the description say
        for i in items:
            s = _text(i["stimulus"])
            if not re.search(r"[/\\]|://|^\$", s):
                i["stimulus"] = f"images/{s}"
    choice = rkind in ("keys", "buttons")
    for n, i in enumerate(items, 1):
        i["correct"] = _key(i.get("correct"), rkind, f"row {n} ({_text(i['stimulus'])}): ") if choice else ""
    has_correct = choice and any(i["correct"] for i in items)
    given = resp.get("keys")
    if isinstance(given, str):
        given = re.split(r"[\s,]+", given)
    if given is not None and not isinstance(given, list):
        raise WizardError("the response keys must be a list, e.g. [f, j]")
    keys = [_key(k, rkind) for k in given or [] if _text(k)] if choice else []
    keys = list(dict.fromkeys(keys)) or sorted({i["correct"] for i in items if i["correct"]}) \
        or (["left", "right"] if rkind == "buttons" else ["f", "j"])
    resp["keys"] = keys
    if has_correct:
        bad = sorted({i["correct"] for i in items} - set(keys) - {""})
        if bad:
            raise WizardError(f"correct answer(s) {', '.join(bad)} are not among the response keys ({', '.join(keys)})")
        nogo = [_text(i["stimulus"]) for i in items if not i["correct"]]
        if nogo:
            notes.append(f"No correct key for {', '.join(nogo[:5])}{' …' if len(nogo) > 5 else ''}: not pressing "
                         "anything counts as correct there (a no-go trial).")
    rows = []
    for i in items:
        row = {"stimulus": _cell(i.get("stimulus")), "condition": _text(i.get("condition")) or "all"}
        if has_correct:
            row["correct"] = i["correct"]
        rows.append(row)

    timing = _section(a, "timing", "fixation, stimulus_duration, response_deadline, iti")
    fixation = _num(timing.get("fixation"), 0.5, "Fixation time", hint="; use 0 for no fixation cross") or 0.0
    stim_dur = _num(timing.get("stimulus_duration"), None, "Stimulus duration", zero_ok=False,
                    hint="; leave it empty to show the stimulus until the response")
    deadline = _num(timing.get("response_deadline"), 2.0 if choice else None, "Time limit to respond",
                    zero_ok=False, hint="; leave it empty for no time limit")
    iti = _num(timing.get("iti"), 0.5, "Pause between trials", hint="; use 0 for no pause") or 0.0

    devices = _devices(a.get("devices"), notes)
    if rkind == "buttons":
        resp["_device"] = _response_box(devices, keys, notes)
    else:
        boxes = [d["type"] for d in devices if d["type"] in _INPUT_TYPES and d["type"] != "voice_key"]
        if boxes:
            notes.append(f"{boxes[0]} (a response box) was added, but the trials take {_NOUN[rkind]}: "
                         "choose the response 'buttons' to answer with the box.")

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
        if kind == "sound" and stim_dur is None:    # a tone stops by itself: hold the trial for its full length
            trial.append({"id": "listen", "type": "wait", "start": fixation, "duration": 2.0})

    routines: dict[str, Any] = {}
    name = _slug(a.get("name") or "my_experiment")
    instructions = _text(a.get("instructions")) or _default_instructions(kind, rkind, keys, rows if has_correct else [],
                                                                        notes)
    routines["instructions"] = _instructions(instructions + "\n\nPress SPACE to begin.")
    routines["trial"] = trial_routine
    feedback = bool(a.get("feedback")) and has_correct
    if a.get("feedback") and not has_correct:
        notes.append("No feedback: " + ("it needs a correct key for each stimulus." if choice else
                                        "there is no response to judge." if rkind == "none" else
                                        f"{_NOUN[rkind]} have no right or wrong answer here."))
    if feedback:
        routines["feedback"] = _feedback_routine(rkind)
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

    blocks = _section(a, "blocks", "count, repeats, order, break_text")
    n_blocks = _int(blocks.get("count"), 1, "Number of blocks")
    repeats = _int(blocks.get("repeats"), 1, "How many times each stimulus appears per block")
    order = _text(blocks.get("order")) or "random"
    from .model import LOOP_ORDERS
    if order not in LOOP_ORDERS:
        close = difflib.get_close_matches(order, LOOP_ORDERS, 1)
        raise WizardError(f"unknown order '{order}'" + (f" (did you mean {close[0]}?)" if close else "")
                          + f"; choose {', '.join(LOOP_ORDERS)} (random shuffles the stimuli in each block)")
    flow: list[Any] = ["instructions"]

    practice = _section(a, "practice", "mode, criterion, max_rounds, repeats")
    pmode = _text(practice.get("mode")) or "none"
    if pmode not in PRACTICE_MODES:
        raise WizardError(f"unknown practice mode '{pmode}' (choose: {', '.join(PRACTICE_MODES)})")
    if pmode != "none" and rkind == "none":
        notes.append("No practice: with no response there is nothing to practise.")
        pmode = "none"
    practice_loop = {"loop": "practice", "conditions": rows, "order": "random",
                     "repeats": _int(practice.get("repeats"), 1, "Practice repeats"),
                     "children": trial_children(has_correct)}
    if has_correct and "feedback" not in routines:
        routines["feedback"] = _feedback_routine(rkind, practice_only=True)
    elif not has_correct and pmode != "none":
        practice_loop["children"] = trial_children(False)
    if pmode == "until" and not has_correct:
        notes.append("Practice runs once: repeating it until a pass mark needs a correct key for each stimulus.")
    if pmode != "none":
        routines["ready"] = _instructions("Practice is over. The real task starts now.\n\nPress SPACE to begin.")

    main_children: list[Any] = []
    if n_blocks == 1:
        main_children = [{"loop": "trials", "conditions": rows, "order": order, "repeats": repeats,
                          "children": trial_children(feedback)}]
    else:
        routines["block_break"] = _instructions(
            _text(blocks.get("break_text")) or "Take a short break.\n\nPress SPACE when you are ready to continue.")
        main_children = [{"loop": "blocks", "repeats": n_blocks, "children": [
            {"loop": "trials", "conditions": rows, "order": order, "repeats": repeats,
             "children": trial_children(feedback)},
            {"if": "$not blocks.last", "then": ["block_break"]}]}]

    if pmode == "until" and has_correct:
        crit = practice.get("criterion")
        pass_mark = ("Practice pass mark must be a proportion between 0 and 1, e.g. 0.8 for 80% correct "
                     f"(you gave {crit})")
        try:
            crit = 0.8 if _text(crit) == "" else float(crit)
        except (TypeError, ValueError):
            raise WizardError(pass_mark) from None
        if isinstance(practice.get("criterion"), bool) or not 0 < crit <= 1:
            raise WizardError(pass_mark)
        rounds = _int(practice.get("max_rounds"), 3, "At most how many practice rounds")
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
    chosen = a.get("questionnaires") or []
    if isinstance(chosen, str):
        chosen = re.split(r"[\s,]+", chosen)
    if not isinstance(chosen, list):
        raise WizardError("the questionnaires must be a list of names, e.g. [consent, demographics, tipi]")
    chosen = [_text(x) for x in chosen if _text(x)]
    twice = sorted({x for x in chosen if chosen.count(x) > 1})
    if twice:
        notes.append(f"{', '.join(twice)} {'was' if len(twice) == 1 else 'were'} chosen twice: asked once.")
        chosen = list(dict.fromkeys(chosen))
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
        {"id": "message", "type": "text", "text": _text(a.get("thanks")) or "Thank you! You're done.", "height": 32}]}
    flow.append("thanks")
    if "consent" in before:      # people who don't agree see a short goodbye and nothing else (no task, no data)
        routines["declined"] = {"description": "shown instead of the study to people who do not agree",
                                "duration": 4, "components": [
                                    {"id": "message", "type": "text", "height": 32,
                                     "text": "You chose not to take part. Thank you for your time."}]}
        flow = ["consent", {"if": "$consent_form.consent == 'yes'", "then": flow[1:], "else": ["declined"]}]
    if "feedback" in routines and not _uses(flow, "feedback"):
        del routines["feedback"]

    doc: dict[str, Any] = {
        "name": name,
        "description": _text(a.get("description")) or f"Made with the EDGE design wizard: {_WHAT[kind]}, "
                                                       f"{_ANSWERED[rkind]}.",
        "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
        "devices": devices,
        "routines": routines,
        "flow": flow,
    }
    files = [str(r["stimulus"]) for r in rows]
    if kind == "picture":
        doc["description"] += (" Put your images in the images/ folder next to this file."
                               if all(f.startswith("images/") for f in files) else
                               " Your pictures are read from the files the trial list names, relative to this file's "
                               "folder.")
    elif kind == "sound" and any(f.lower().endswith(_SOUND_FILES) for f in files):
        doc["description"] += " Put your sound files next to this file (at the paths the trial list names)."
    from .model import Experiment
    try:   # say what the experiment measures, so the summary and the checks focus on it
        from .measures import suggest_measures
        ms = suggest_measures(Experiment.from_dict(doc))
        if ms:
            doc["measures"] = ms
    except Exception:
        pass
    try:
        est = estimate_experiment(Experiment.from_dict(doc))
        if est["seconds"] > 2 * 3600:
            notes.append(f"This makes {est['trials']} trials, about {est['seconds'] / 3600:.1f} hours: check the "
                         "numbers of blocks and repeats.")
    except Exception:
        pass
    return doc


_INPUT_TYPES = ("serial_inputs", "parallel_inputs", "labjack", "voice_key", "sim_inputs")


def _devices(answer: Any, notes: list[str]) -> list[dict[str, Any]]:
    """The chosen devices, checked against the installed drivers; eye trackers calibrate at the start."""
    from .devices import device_registry
    if answer is None or answer == "":
        return []
    if isinstance(answer, (str, dict)):
        answer = [answer]
    if not isinstance(answer, list):
        raise WizardError("the devices must be a list of device types, e.g. [sim_eyetracker, lsl_markers]")
    reg = device_registry()
    devices: list[dict[str, Any]] = []
    for d in answer:
        dtype = _text(d.get("type") if isinstance(d, dict) else d)
        if not dtype:
            continue
        if dtype not in reg:
            close = difflib.get_close_matches(dtype, sorted(reg), 1, 0.6)
            raise WizardError(f"unknown device type '{dtype}'" + (f" (did you mean {close[0]}?)" if close else "")
                              + f"; available: {', '.join(sorted(reg))}")
        entry: dict[str, Any] = {"id": _device_id(dtype, devices), "type": dtype}
        if "calibration" in getattr(reg[dtype], "capabilities", ()):
            entry["calibrate"] = True       # gaze data are only as good as the calibration at the start
        devices.append(entry)
    return devices


def _response_box(devices: list[dict[str, Any]], buttons: list[str], notes: list[str]) -> str:
    """The id of the response box the 'buttons' answers come from (a simulated one is added if none was
    chosen), with its buttons named after the answers."""
    box = next((d for d in devices if d["type"] in _INPUT_TYPES), None)
    if box is None:
        box = {"id": _device_id("sim_inputs", devices), "type": "sim_inputs"}
        devices.append(box)
        notes.append(f"Added a simulated response box ('{box['id']}', sim_inputs) for test runs: replace it with "
                     "your box (serial_inputs, parallel_inputs or labjack) before testing participants.")
    if box["type"] != "voice_key" and not (box.get("options") or {}).get("inputs"):
        box["options"] = {"inputs": {str(n): b for n, b in enumerate(buttons, 1)}}
        if box["type"] != "sim_inputs":
            notes.append(f"The buttons of '{box['id']}' are named "
                         + ", ".join(f"{n} = {b}" for n, b in enumerate(buttons, 1))
                         + ": check that this matches how your box is wired.")
    return box["id"]


def read_answers(path: str | Path) -> dict[str, Any]:
    """Wizard answers from a JSON or YAML file; a mistake in the file is a :class:`WizardError` saying where."""
    import json

    import yaml
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise WizardError(f"{p}: file not found") from None
    except (OSError, UnicodeDecodeError):
        raise WizardError(f"{p} can't be read as a text file of answers (JSON or YAML)") from None
    try:
        data = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)     # YAML reads JSON too
    except json.JSONDecodeError as e:
        raise WizardError(f"{p.name} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}") from None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise WizardError(f"{p.name} is not valid YAML{where}: {getattr(e, 'problem', None) or e}") from None
    if not isinstance(data, dict):
        raise WizardError(f"{p.name} must hold named answers, e.g. {{\"stimulus\": {{\"kind\": \"word\"}}}}")
    return data


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
            "parallel_port": "ttl", "sim_inputs": "response_box", "serial_inputs": "response_box",
            "parallel_inputs": "response_box", "labjack": "response_box"}.get(dtype, _slug(dtype))
    ids = {d["id"] for d in existing}
    out, n = base, 2
    while out in ids:
        out, n = f"{base}{n}", n + 1
    return out


def _default_instructions(kind: str, rkind: str, keys: list[str], rows: list[dict],
                          notes: list[str] | None = None) -> str:
    what = _WHAT[kind]
    see = "hear" if kind == "sound" else "see"

    def say(k: str) -> str:
        return k.upper() if rkind == "keys" else f"the {k} button"

    if rkind in ("keys", "buttons") and rows:
        # name what each key is for only when every condition (or word) has exactly one correct key:
        # in a Stroop or flanker design the conditions are not the answers, and the pairs would be nonsense
        label_keys: dict[str, set[str]] = {}
        for r in rows:
            label = r["condition"] if r["condition"] != "all" else (str(r["stimulus"]) if kind == "word" else "")
            label_keys.setdefault(label, set()).add(r["correct"])
        if "" not in label_keys and all(len(v) == 1 for v in label_keys.values()):
            by_key: dict[str, list[str]] = {}
            for label, ks in label_keys.items():
                by_key.setdefault(next(iter(ks)), []).append(label)
            lines = [f"Press {say(k)} for {' / '.join(v)}" for k, v in by_key.items() if k]
            lines += [f"Do not press anything for {' / '.join(v)}" for k, v in by_key.items() if not k]
            return f"You will {see} {what}.\n" + "\n".join(lines) + "\n\nAnswer as quickly and accurately as you can."
        if notes is not None:
            notes.append("The instructions don't say which key to press when (the conditions don't each go with "
                         "one key): write that into the instructions yourself.")
    if rkind in ("keys", "buttons"):
        shown = [say(k) for k in keys]
        either = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " or " + shown[-1]
        return f"You will {see} {what}. Respond with {either}.\n\nAnswer as quickly and accurately as you can."
    if rkind == "mouse":
        return f"You will {see} {what}. " + ("Click the mouse after each one." if kind == "sound" else "Click on each one.")
    if rkind == "rating":
        return f"You will {see} {what}. Rate each one on the scale."
    return f"You will {see} {what}. Just {'listen' if kind == 'sound' else 'watch'}."


def estimate(doc: dict[str, Any], base_dir=None) -> dict[str, Any]:
    """Quick estimate of trial count and session length (no run needed)."""
    from pathlib import Path

    from .model import Experiment
    exp = Experiment.from_dict(doc, base_dir=Path(base_dir) if base_dir else Path.cwd())
    return estimate_experiment(exp)


def _natural_end(r) -> float | None:
    """Seconds after which every component of routine ``r`` has stopped by itself (the routine then ends), or
    None when one runs until the routine ends or its timing isn't fixed. Frames are counted at 60 Hz."""
    from .components import component_registry
    reg = component_registry()
    end = 0.0
    for c in r.components:
        cls = reg.get(c.type)
        if cls is not None and not cls.keeps_routine_alive:      # marker, variable, code
            continue
        if c.start_after or c.start_if or c.end_routine or c.stop_if:
            return None
        if isinstance(c.start_frame, (int, float)):
            start = c.start_frame / 60
        elif isinstance(c.start, (int, float)):
            start = float(c.start)
        else:
            return None
        if isinstance(c.duration, (int, float)):
            dur = float(c.duration)
        elif isinstance(c.duration_frames, (int, float)):
            dur = c.duration_frames / 60
        elif c.type == "sound" and isinstance(c.props.get("sound"), (int, float)):   # a tone stops once played
            dur = float(c.props.get("tone_duration") or 0.2)
        else:
            return None
        end = max(end, start + dur)
    return end + 2 / 60 if r.components else None     # + about two frames to notice the end and move on


def estimate_experiment(exp) -> dict[str, Any]:
    """Expected number of trials and minutes, assuming ~0.7 s responses and ~3 s on instruction screens."""
    from .model import Branch, Loop, RoutineRef, StateMachine
    from .scope import loop_columns

    def routine_seconds(rid: str) -> float:
        r = exp.routines.get(rid)
        if r is None:
            return 0.0
        if isinstance(r.duration, (int, float)):     # a cap: the routine also ends when everything in it has stopped
            natural = _natural_end(r)
            return min(float(r.duration), natural) if natural is not None else float(r.duration)
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

    repeating: list[tuple[str, int]] = []      # workflow states that may run more than once (practice until ...)

    def count(nodes, mult: float, worst: bool) -> tuple[float, float]:
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
                t, s = count(n.children, mult * reps, worst)
                has_inner_loop = any(isinstance(c, Loop) for c in n.children)
                trials += t if has_inner_loop or t else 0
                if not has_inner_loop and not t:
                    trials += mult * reps
                secs += s
            elif isinstance(n, Branch):
                t, s = count(n.then, mult, worst)
                trials += t
                secs += s
            elif isinstance(n, StateMachine):
                for st in n.states.values():
                    visits = 1
                    if isinstance(st.max_visits, int) and st.max_visits > 1 and any(
                            tr.goto == st.name for tr in st.next):
                        visits = st.max_visits if worst else 1
                        if worst:
                            repeating.append((st.name, st.max_visits))
                    t, s = count(st.run, mult * visits, worst)
                    trials += t
                    secs += s
        return trials, secs

    trials, secs = count(exp.flow, 1.0, False)
    t_max, s_max = count(exp.flow, 1.0, True)
    out = {"trials": int(round(trials)), "seconds": round(secs, 1), "minutes": round(secs / 60, 1),
           "text": (f"{int(round(trials))} trials, about {_minutes(secs)}" if round(trials)
                    else f"about {_minutes(secs)}")}
    if round(t_max) > round(trials) or round(s_max) > round(secs):    # e.g. practice repeated until a pass mark
        why = ", ".join(f"{name} may run up to {n}×" for name, n in dict(repeating).items())
        out.update(trials_max=int(round(t_max)), seconds_max=round(s_max, 1), minutes_max=round(s_max / 60, 1),
                   text=(f"{int(round(trials))} to {int(round(t_max))} trials, " if round(t_max) else "")
                   + f"about {_span(secs, s_max)} ({why})")
    return out


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
    if secs >= 2 * 3600:
        return f"{secs / 3600:.1f} hours"
    return f"{round(secs / 60):.0f} minutes"


def _span(lo: float, hi: float) -> str:
    """'17 to 23 seconds', '2 to 3 minutes', '50 seconds to 2 minutes'."""
    a, b = _minutes(lo), _minutes(hi)
    if a == b:
        return a
    if a.split()[1] == b.split()[1]:
        return f"{a.split()[0]} to {b}"
    return f"{a} to {b}"


def write_placeholders(doc: dict[str, Any], folder: Path) -> list[str]:
    """Write a plain coloured stand-in for every picture the trial lists name but that doesn't exist yet,
    so a new picture experiment runs straight away (replace them with the real pictures)."""
    import struct
    import zlib
    made = []
    colours = [(70, 130, 180), (205, 92, 92), (60, 179, 113), (218, 165, 32), (147, 112, 219), (64, 224, 208)]

    def png(path: Path, rgb: tuple[int, int, int], w: int = 400, h: int = 300) -> None:
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

        def chunk(t: bytes, d: bytes) -> bytes:
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    for r in _rows(doc.get("flow")):
        for v in r.values():
            if isinstance(v, str) and v.lower().endswith((".png", ".jpg", ".jpeg")) and not Path(v).is_absolute():
                p = folder / v
                if not p.exists() and folder.resolve() in p.resolve().parents:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    rgb = colours[len(made) % len(colours)]
                    if p.suffix.lower() == ".png":
                        png(p, rgb)
                    else:      # a .jpg stand-in is a real JPEG, so any program opens it
                        p.write_bytes(_solid_jpeg(rgb))
                    made.append(v)
    return made


def _rows(nodes: Any):
    """Every trial-list row written into the flow (loops, branches and workflow states)."""
    for n in nodes or []:
        if isinstance(n, dict):
            if isinstance(n.get("conditions"), list):
                yield from (r for r in n["conditions"] if isinstance(r, dict))
            for k in ("children", "then", "else"):
                yield from _rows(n.get(k))
            for st in (n.get("states") or {}).values():
                if isinstance(st, dict):
                    yield from _rows(st.get("run"))


def prepare_files(doc: dict[str, Any], folder: Path, made: list[str] | None = None) -> list[str]:
    """After saving a wizard experiment in ``folder``: make stand-ins for missing pictures (unless ``made`` lists
    the ones :func:`write_placeholders` already made), and say (in notes for the researcher) which pictures are
    stand-ins and which sound files still have to be put in place."""
    notes = []
    made = write_placeholders(doc, folder) if made is None else made
    if made:
        notes.append(f"Made {len(made)} stand-in picture{'s' if len(made) > 1 else ''} "
                     f"({', '.join(made[:6])}{' …' if len(made) > 6 else ''}) so you can try the experiment now: "
                     "replace them with your real pictures, under the same names.")
    sounds = sorted({v for r in _rows(doc.get("flow")) for v in r.values()
                     if isinstance(v, str) and v.lower().endswith(_SOUND_FILES) and not (folder / v).exists()})
    if sounds:
        notes.append(f"Put the sound file{'s' if len(sounds) > 1 else ''} {', '.join(sounds[:6])}"
                     f"{' …' if len(sounds) > 6 else ''} in {folder} before running: "
                     f"{'they are' if len(sounds) > 1 else 'it is'} not there yet.")
    return notes


def _solid_jpeg(rgb: tuple[int, int, int], w: int = 400, h: int = 300) -> bytes:
    """A baseline JPEG of one flat colour (every 8x8 block is its DC value; no other coefficients)."""
    import struct
    r, g, b = rgb
    ycc = (0.299 * r + 0.587 * g + 0.114 * b, 128 - 0.168736 * r - 0.331264 * g + 0.5 * b,
           128 + 0.5 * r - 0.418688 * g - 0.081312 * b)
    dc_bits = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]       # the standard DC table (ITU T.81 Annex K)
    codes, code, k = {}, 0, 0
    for length, count in enumerate(dc_bits, 1):
        for _ in range(count):
            codes[k] = (code, length)
            code, k = code + 1, k + 1
        code <<= 1

    def seg(marker: int, data: bytes) -> bytes:
        return struct.pack(">HH", marker, len(data) + 2) + data

    out, acc, nbits = bytearray(), 0, 0

    def put(value: int, length: int) -> None:
        nonlocal acc, nbits
        acc, nbits = (acc << length) | value, nbits + length
        while nbits >= 8:
            byte = (acc >> (nbits - 8)) & 0xFF
            out.append(byte)
            if byte == 0xFF:
                out.append(0)
            nbits -= 8
        acc &= (1 << nbits) - 1

    blocks = ((w + 7) // 8) * ((h + 7) // 8)
    for n in range(blocks):
        for c in range(3):
            diff = round(8 * (ycc[c] - 128)) if n == 0 else 0      # DC of a flat block; later blocks: no change
            size = abs(diff).bit_length()
            put(*codes[size])
            if size:
                put(diff if diff > 0 else diff + (1 << size) - 1, size)
            put(0, 1)                                              # end of block (the only AC code)
    if nbits:
        put((1 << (8 - nbits)) - 1, 8 - nbits)
    return (b"\xff\xd8"
            + seg(0xFFDB, b"\x00" + bytes([1] * 64))
            + seg(0xFFC0, struct.pack(">BHHB", 8, h, w, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00")
            + seg(0xFFC4, b"\x00" + bytes(dc_bits) + bytes(range(12)))
            + seg(0xFFC4, b"\x10" + bytes([1] + [0] * 15) + b"\x00")
            + seg(0xFFDA, b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00")
            + bytes(out) + b"\xff\xd9")
