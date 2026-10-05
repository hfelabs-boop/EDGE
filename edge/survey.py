"""Surveys: questionnaires built from structured questions instead of hand-written HTML.

    - id: about_you
      type: survey
      title: A few questions about you
      questions:
        - {instrument: demographics}                  # from the library (edge/survey_library.py)
        - {id: mood, type: likert, scale: agree7, text: "I feel good right now."}
        - {id: hobbies, type: multiple, text: "Which do you do weekly?", options: [Sport, Music, Reading],
           exclusive: [None of these]}
        - {type: page_break}
        - {instrument: phq9}

Question types (modelled on the standard set of professional survey tools):

=============  ==========================================================================
text_block     text or HTML without an answer (instructions, section headings, images)
single         one answer from a list (radio buttons; ``layout: horizontal``; ``other_option``)
dropdown       one answer from a drop-down list
multiple       any number of answers (checkboxes; ``min_choices``, ``max_choices``, ``exclusive``)
likert         one statement rated on a scale (``scale: agree5`` … or your own ``options``)
matrix         several statements (``items``) rated on the same scale, as a table
semantic       bipolar items (``left``/``right`` adjectives) on an N-point scale (semantic differential)
scale          a numbered scale 1..N (``points``) with end labels (e.g. valence 1-9)
nps            0-10 "how likely are you to recommend" scale
slider         a visual analogue scale (``min``, ``max``, ``step``, end ``labels``)
text           one line of text (``validate: email | number | integer``, ``pattern``, ``max_length``)
essay          several lines of text (``min_length``, ``max_length``, ``rows``)
number         a number (``min``, ``max``, ``step``)
date           a date
rank           put options in order (drag, or the ↑/↓ buttons)
constant_sum   share a total (e.g. 100 points) across options
page_break     starts a new page
=============  ==========================================================================

Every question can have ``required``, ``help`` (small print under the question), ``show_if``
(display logic based on earlier answers) and, for choice questions, ``randomize`` (shuffle the
options, the order shown is saved). ``correct`` marks a right answer (knowledge or attention checks).

``test_answer`` fixes what the virtual participant answers in test runs (the consent question uses
``test_answer: yes`` so test runs go through the whole study).

``show_if`` examples: ``{gender: Woman}``, ``{age: {">=": 18}}``, ``{hobbies: {contains: Sport}}``,
``{consent: yes, age: {">=": 18}}`` (all must hold), ``{any: [{a: 1}, {b: 1}]}``,
``{email: {answered: true}}``. Questions can show earlier answers with ``{{answer.<id>}}``.

Data: one column per answer (``about_you.age``, ``about_you.phq9_3`` …), checkbox questions as
``a; b`` plus one 0/1 column per option, rank orders and constant sums one column per option,
``<id>_other`` for "other" text, ``pageN_time`` (seconds per page), and every score defined by the
instruments or by ``scores:`` (``phq9_total``, ``phq9_total_band`` …).
"""

from __future__ import annotations

import copy
import html as htmllib
import json
import random
import re
from typing import Any

from . import survey_library as lib

QUESTION_TYPES: dict[str, dict[str, Any]] = {
    "text_block": {"label": "Text / instructions", "group": "Display", "answer": False},
    "single": {"label": "Single choice", "group": "Choice", "answer": True},
    "dropdown": {"label": "Drop-down list", "group": "Choice", "answer": True},
    "multiple": {"label": "Multiple choice (checkboxes)", "group": "Choice", "answer": True},
    "likert": {"label": "Likert item", "group": "Rating", "answer": True},
    "matrix": {"label": "Matrix / Likert table", "group": "Rating", "answer": True},
    "semantic": {"label": "Semantic differential (bipolar)", "group": "Rating", "answer": True},
    "scale": {"label": "Numbered scale (1-N)", "group": "Rating", "answer": True},
    "nps": {"label": "Net Promoter (0-10)", "group": "Rating", "answer": True},
    "slider": {"label": "Slider / visual analogue scale", "group": "Rating", "answer": True},
    "text": {"label": "Short text", "group": "Text entry", "answer": True},
    "essay": {"label": "Long text (essay)", "group": "Text entry", "answer": True},
    "number": {"label": "Number", "group": "Text entry", "answer": True},
    "date": {"label": "Date", "group": "Text entry", "answer": True},
    "rank": {"label": "Rank order", "group": "Advanced", "answer": True},
    "constant_sum": {"label": "Constant sum", "group": "Advanced", "answer": True},
    "page_break": {"label": "Page break", "group": "Display", "answer": False},
}
CHOICE_TYPES = {"single", "dropdown", "multiple", "likert"}
OPS = {"=", "==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "answered"}


class SurveyError(ValueError):
    pass


# =========================================================================================== model
def slug(text: Any) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(text)).strip("_").lower()
    return (s or "option")[:40]


def norm_options(q: dict[str, Any]) -> list[dict[str, Any]]:
    """Options as [{value, label}], from ``options`` (strings or dicts) or a named ``scale``."""
    if q.get("type") in ("nps",):
        return [{"value": i, "label": str(i)} for i in range(11)]
    if q.get("type") == "scale":
        n = int(q.get("points") or 7)
        start = int(q.get("start", 1))
        return [{"value": i, "label": str(i)} for i in range(start, start + n)]
    if q.get("type") == "semantic":
        n = int(q.get("points") or 7)
        return [{"value": i, "label": str(i)} for i in range(1, n + 1)]
    raw = q.get("options")
    if raw is None and q.get("scale"):
        return lib.scale_options(str(q["scale"]))
    out = []
    for o in raw or []:
        if isinstance(o, dict):
            label = str(o.get("label", o.get("value", "")))
            out.append({"value": o.get("value", label), "label": label})
        else:
            out.append({"value": o, "label": str(o)})
    return out


def expand(questions: list[Any], rng: random.Random | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Expand ``{instrument: …}`` entries, resolve scales and (with ``rng``) shuffle what should be
    shuffled. Returns (flat question list, scores)."""
    flat: list[dict[str, Any]] = []
    scores: dict[str, Any] = {}
    for q in questions or []:
        if not isinstance(q, dict):
            raise SurveyError(f"each question must be a mapping, not {q!r}")
        if "instrument" in q:
            ins = lib.instrument(str(q["instrument"]))
            items = ins["questions"]
            if q.get("required") is not None:
                for it in items:
                    if QUESTION_TYPES.get(it.get("type"), {}).get("answer"):
                        it["required"] = bool(q["required"])
            for it in items:
                it.setdefault("source", ins["id"])
            sub, sub_scores = expand(items, rng)
            flat += sub
            scores.update(ins.get("scores") or {})
            continue
        q = copy.deepcopy(q)
        t = q.get("type", "single")
        q["type"] = t
        if t in CHOICE_TYPES or t in ("matrix", "nps", "scale", "semantic", "rank", "constant_sum"):
            q["options"] = norm_options(q)
        if rng is not None and q.get("randomize") and t in ("single", "multiple", "dropdown", "rank", "constant_sum"):
            fixed_tail = [o for o in q["options"] if o.get("label") in (q.get("other_option"),) or
                          o.get("value") in (q.get("exclusive") or [])]
            movable = [o for o in q["options"] if o not in fixed_tail]
            rng.shuffle(movable)
            q["options"] = movable + fixed_tail
            q["shown_order"] = [o["value"] for o in q["options"]]
        if t in ("matrix", "semantic"):
            q["items"] = [dict(it) if isinstance(it, dict) else {"id": f"{q.get('id', 'item')}_{i}", "text": str(it)}
                          for i, it in enumerate(q.get("items") or [], 1)]
            if rng is not None and q.get("randomize"):
                rng.shuffle(q["items"])
                q["shown_order"] = [it["id"] for it in q["items"]]
        flat.append(q)
    return flat, scores


def answer_ids(q: dict[str, Any]) -> list[str]:
    """Data ids a question produces (before suffixes)."""
    t = q.get("type")
    if t in ("matrix", "semantic"):
        return [str(it["id"]) for it in q.get("items") or []]
    if QUESTION_TYPES.get(t, {}).get("answer") and q.get("id"):
        return [str(q["id"])]
    return []


def count_items(questions: list[Any]) -> int:
    flat, _ = expand(questions)
    return sum(len(answer_ids(q)) for q in flat)


def pages(flat: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = [[]]
    for q in flat:
        if q["type"] == "page_break":
            if out[-1]:
                out.append([])
        else:
            out[-1].append(q)
    return [p for p in out if p] or [[]]


def validate(questions: list[Any], scores: dict[str, Any] | None = None) -> list[str]:
    """Problems with a question list, in plain words."""
    problems: list[str] = []
    try:
        flat, lib_scores = expand(questions)
    except (SurveyError, KeyError) as e:
        return [str(e).strip("'\"")]
    seen: dict[str, int] = {}
    for n, q in enumerate(flat, 1):
        t = q["type"]
        label = f"question {n}" + (f" ('{q['id']}')" if q.get("id") else "")
        if t not in QUESTION_TYPES:
            problems.append(f"{label}: unknown question type '{t}' (choose: {', '.join(QUESTION_TYPES)})")
            continue
        if QUESTION_TYPES[t]["answer"]:
            if not q.get("id"):
                problems.append(f"{label}: needs an id (the name of its data column)")
            elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(q["id"])):
                problems.append(f"{label}: id '{q['id']}' must use letters, digits and _ only")
        if t in CHOICE_TYPES | {"matrix", "rank", "constant_sum"} and not q.get("options"):
            problems.append(f"{label}: needs options (or a scale such as agree5)")
        if t in ("matrix", "semantic") and not q.get("items"):
            problems.append(f"{label}: needs items (the statements to rate)")
        if t == "semantic":
            for it in q.get("items") or []:
                if not (it.get("left") and it.get("right")):
                    problems.append(f"{label}: semantic items need 'left' and 'right' words")
                    break
        if t == "slider" and float(q.get("max", 100)) <= float(q.get("min", 0)):
            problems.append(f"{label}: max must be larger than min")
        if t == "multiple" and q.get("min_choices") and q.get("max_choices") and \
                int(q["min_choices"]) > int(q["max_choices"]):
            problems.append(f"{label}: min_choices is larger than max_choices")
        for aid in answer_ids(q):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", aid):
                problems.append(f"{label}: item id '{aid}' must use letters, digits and _ only")
            if aid in seen:
                problems.append(f"{label}: id '{aid}' is used twice (questions {seen[aid]} and {n})")
            seen.setdefault(aid, n)
        for ref in _cond_refs(q.get("show_if")):
            if ref not in seen:
                problems.append(f"{label}: show_if refers to '{ref}', which is not an earlier question")
            elif seen[ref] == n:
                problems.append(f"{label}: show_if can't refer to the question itself")
        if q.get("show_if") is not None:
            bad = _cond_problem(q["show_if"])
            if bad:
                problems.append(f"{label}: show_if {bad}")
    for name, sc in {**lib_scores, **(scores or {})}.items():
        for it in (sc or {}).get("items", []) + (sc or {}).get("correct", []):
            if it not in seen:
                problems.append(f"score '{name}': no question or item called '{it}'")
    return problems


def _cond_refs(cond: Any) -> list[str]:
    if not isinstance(cond, dict):
        return []
    refs = []
    for k, v in cond.items():
        if k in ("any", "all") and isinstance(v, list):
            for c in v:
                refs += _cond_refs(c)
        else:
            refs.append(str(k))
    return refs


def _cond_problem(cond: Any) -> str:
    if not isinstance(cond, dict) or not cond:
        return "must be a mapping like {gender: Woman} or {age: {'>=': 18}}"
    for k, v in cond.items():
        if k in ("any", "all"):
            if not isinstance(v, list):
                return f"'{k}' needs a list of conditions"
            for c in v:
                p = _cond_problem(c)
                if p:
                    return p
        elif isinstance(v, dict):
            bad = set(v) - OPS
            if bad:
                return f"unknown comparison {', '.join(map(str, bad))} (use {', '.join(sorted(OPS))})"
    return ""


def condition_holds(cond: Any, answers: dict[str, Any]) -> bool:
    """Same semantics as the page's JavaScript."""
    if not cond:
        return True
    for k, v in cond.items():
        if k == "any":
            if not any(condition_holds(c, answers) for c in v):
                return False
            continue
        if k == "all":
            if not all(condition_holds(c, answers) for c in v):
                return False
            continue
        a = answers.get(k)
        tests = v.items() if isinstance(v, dict) else [("in" if isinstance(v, list) else "=", v)]
        for op, ref in tests:
            if not _compare(a, op, ref):
                return False
    return True


def _empty(a: Any) -> bool:
    return a is None or a == "" or a == []


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _compare(a: Any, op: str, ref: Any) -> bool:
    if op == "answered":
        return (not _empty(a)) == bool(ref)
    if _empty(a):
        return op in ("!=", "not_in")
    vals = a if isinstance(a, list) else [a]
    s = [str(x) for x in vals]
    if op in ("=", "=="):
        return str(ref) in s
    if op == "!=":
        return str(ref) not in s
    if op == "contains":
        return str(ref) in s
    if op == "in":
        return any(str(r) in s for r in (ref if isinstance(ref, list) else [ref]))
    if op == "not_in":
        return not any(str(r) in s for r in (ref if isinstance(ref, list) else [ref]))
    x, y = _num(vals[0]), _num(ref)
    if x is None or y is None:
        return False
    return {">": x > y, ">=": x >= y, "<": x < y, "<=": x <= y}[op]


# =========================================================================================== answers
def auto_answer(flat: list[dict[str, Any]], rng: random.Random, attention: float = 0.95) -> dict[str, Any]:
    """What a plausible participant would submit (used by test runs and the virtual participant)."""
    ans: dict[str, Any] = {}
    for pi, page in enumerate(pages(flat), 1):
        for q in page:
            if not condition_holds(q.get("show_if"), ans):
                continue
            t = q["type"]
            opts = q.get("options") or []
            if not QUESTION_TYPES.get(t, {}).get("answer"):
                continue
            if not q.get("required") and rng.random() < 0.05:
                continue      # an occasional skipped optional question, like real data
            if q.get("test_answer") is not None:          # e.g. consent: test runs go through the study
                ans[q["id"]] = q["test_answer"]
                continue
            if q.get("correct") is not None and rng.random() < attention:
                ans[q["id"]] = q["correct"]
                continue
            if t in ("single", "dropdown", "likert", "scale", "nps"):
                o = rng.choice(opts)
                ans[q["id"]] = o["value"]
                if q.get("other_option") and o["label"] == q["other_option"]:
                    ans[q["id"] + "_other"] = "virtual participant"
            elif t == "multiple":
                excl = [str(x) for x in q.get("exclusive") or []]
                pool = [o["value"] for o in opts if str(o["value"]) not in excl]
                lo = int(q.get("min_choices") or (1 if q.get("required") else 0))
                hi = int(q.get("max_choices") or len(pool))
                k = rng.randint(min(lo, len(pool)), max(min(hi, len(pool)), min(lo, len(pool))))
                ans[q["id"]] = rng.sample(pool, k) if pool else []
            elif t in ("matrix", "semantic"):
                for it in q["items"]:
                    ans[it["id"]] = rng.choice(opts)["value"]
            elif t == "slider":
                lo, hi, st = float(q.get("min", 0)), float(q.get("max", 100)), float(q.get("step", 1))
                n = int(round((hi - lo) / st))
                v = lo + rng.randint(0, n) * st
                ans[q["id"]] = int(v) if float(v).is_integer() else round(v, 6)
            elif t == "number":
                lo, hi = int(_num(q.get("min")) or 0), int(_num(q.get("max")) or 99)
                ans[q["id"]] = rng.randint(lo, max(lo, hi))
            elif t == "text":
                ans[q["id"]] = {"email": "virtual.participant@example.org", "number": "42",
                                "integer": "42"}.get(q.get("validate"), "virtual participant")
            elif t == "essay":
                ans[q["id"]] = "An answer written by the virtual participant."
            elif t == "date":
                ans[q["id"]] = "2000-01-01"
            elif t == "rank":
                order = [o["value"] for o in opts]
                rng.shuffle(order)
                ans[q["id"]] = order
            elif t == "constant_sum":
                total = float(q.get("total", 100))
                cuts = sorted(rng.uniform(0, total) for _ in range(len(opts) - 1))
                parts = [b - a for a, b in zip([0.0] + cuts, cuts + [total])]
                ints = [int(round(p)) for p in parts]
                ints[-1] += int(total) - sum(ints)
                ans[q["id"]] = {str(o["value"]): v for o, v in zip(opts, ints)}
        ans[f"page{pi}_time"] = round(4 + rng.random() * 6 + 1.5 * len(page), 2)
    return ans


def _coerce_value(v: Any, q: dict[str, Any]) -> Any:
    """Map a submitted value back to the option's own value (numbers stay numbers)."""
    for o in q.get("options") or []:
        if str(o["value"]) == str(v):
            return o["value"]
    if q.get("type") in ("number", "slider") or (q.get("type") == "text" and q.get("validate") in ("number", "integer")):
        n = _num(v)
        if n is not None:
            return int(n) if n.is_integer() else n
    return v


def process(flat: list[dict[str, Any]], scores: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Turn what the page submitted into tidy data columns plus scores."""
    out: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    for q in flat:
        t = q["type"]
        if not QUESTION_TYPES.get(t, {}).get("answer"):
            continue
        shown = condition_holds(q.get("show_if"), answers)
        if t in ("matrix", "semantic"):
            for it in q["items"]:
                v = raw.get(it["id"]) if shown else None
                v = None if _empty(v) else _coerce_value(v, q)
                out[it["id"]] = answers[it["id"]] = v
        elif t == "multiple":
            v = raw.get(q["id"]) if shown else None
            vals = [] if _empty(v) else (v if isinstance(v, list) else [v])
            vals = [_coerce_value(x, q) for x in vals]
            answers[q["id"]] = vals
            out[q["id"]] = "; ".join(str(x) for x in vals) if shown else None
            for o in q["options"]:
                out[f"{q['id']}_{slug(o['value'])}"] = (1 if any(str(x) == str(o["value"]) for x in vals) else 0) \
                    if shown else None
        elif t == "rank":
            v = raw.get(q["id"]) if shown else None
            order = [_coerce_value(x, q) for x in (v or [])] if isinstance(v, list) else []
            answers[q["id"]] = order
            out[q["id"]] = " > ".join(str(x) for x in order) if order else None
            for o in q["options"]:
                pos = next((i for i, x in enumerate(order, 1) if str(x) == str(o["value"])), None)
                out[f"{q['id']}_{slug(o['value'])}"] = pos
        elif t == "constant_sum":
            v = raw.get(q["id"]) if shown else None
            v = v if isinstance(v, dict) else {}
            answers[q["id"]] = v
            for o in q["options"]:
                x = v.get(str(o["value"]))
                n = _num(x)
                out[f"{q['id']}_{slug(o['value'])}"] = (int(n) if n is not None and n.is_integer() else n)
        else:
            v = raw.get(q["id"]) if shown else None
            v = None if _empty(v) else _coerce_value(v, q)
            out[q["id"]] = answers[q["id"]] = v
            if q.get("other_option"):
                out[q["id"] + "_other"] = raw.get(q["id"] + "_other") or None
        if q.get("shown_order"):
            out[q["id"] + "_order"] = " ".join(str(x) for x in q["shown_order"])
    for k, v in raw.items():
        if re.fullmatch(r"page\d+_time", str(k)):
            out[k] = _num(v)
    out.update(compute_scores(flat, scores, answers))
    return out


def compute_scores(flat: list[dict[str, Any]], scores: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Scores from the scoring rules (sum / mean / flag / correct, reverse items, multipliers, bands)."""
    info: dict[str, dict[str, Any]] = {}       # item id -> {reverse, min, max, correct}
    for q in flat:
        vals = [_num(o["value"]) for o in q.get("options") or [] if _num(o["value"]) is not None]
        lo, hi = (min(vals), max(vals)) if vals else (None, None)
        for it in q.get("items") or []:
            info[it["id"]] = {"reverse": bool(it.get("reverse")), "min": lo, "max": hi}
        if q.get("id"):
            info.setdefault(q["id"], {"reverse": bool(q.get("reverse")), "min": lo, "max": hi,
                                      "correct": q.get("correct")})
    out: dict[str, Any] = {}
    for name, sc in (scores or {}).items():
        sc = sc or {}
        method = sc.get("method", "sum" if "items" in sc else "correct")
        if method == "correct":
            ids = sc.get("correct") or sc.get("items") or []
            out[name] = sum(1 for i in ids if info.get(i, {}).get("correct") is not None
                            and str(answers.get(i)) == str(info[i]["correct"]))
            continue
        vals = []
        missing = 0
        for i in sc.get("items", []):
            x = _num(answers.get(i))
            if x is None:
                if sc.get("missing_as") is not None:
                    vals.append(float(sc["missing_as"]))
                else:
                    missing += 1
                continue
            m = info.get(i, {})
            if (m.get("reverse") or i in (sc.get("reverse") or [])) and m.get("min") is not None:
                x = m["min"] + m["max"] - x
            vals.append(x)
        if method == "flag":
            out[name] = (1 if any(v >= float(sc.get("threshold", 1)) for v in vals) else 0) if vals else None
            continue
        need = int(sc.get("min_answered", len(sc.get("items", []))))
        if not vals or len(vals) < need or (method == "sum" and missing and sc.get("missing_as") is None):
            out[name] = None
        else:
            s = sum(vals) if method == "sum" else sum(vals) / len(vals)
            s = s * float(sc.get("multiply", 1)) + float(sc.get("add", 0))
            out[name] = int(s) if float(s).is_integer() else round(s, 4)
        if sc.get("bands"):
            out[name + "_band"] = None if out[name] is None else next(
                (lab for mx, lab in sc["bands"] if out[name] <= mx), sc["bands"][-1][1])
    return out


def columns(questions: list[Any], scores: dict[str, Any] | None = None) -> dict[str, str]:
    """Data column -> plain description (for the data dictionary)."""
    flat, lib_scores = expand(questions)
    cols: dict[str, str] = {}

    def txt(s: Any) -> str:
        return re.sub(r"<[^>]+>", "", str(s or "")).strip()

    for q in flat:
        t = q["type"]
        if not QUESTION_TYPES.get(t, {}).get("answer"):
            continue
        codes = "; ".join(f"{o['value']} = {o['label']}" for o in q.get("options") or []
                          if str(o["value"]) != o["label"])
        tail = f" [{codes}]" if codes else ""
        if t in ("matrix", "semantic"):
            for it in q["items"]:
                stem = f"{it['left']} – {it['right']}" if t == "semantic" else txt(it.get("text"))
                cols[it["id"]] = f"{txt(q.get('text'))} {stem}".strip() + (" (reverse scored)" if it.get("reverse") else "") + tail
        elif t in ("multiple", "rank", "constant_sum"):
            if t != "constant_sum":
                cols[q["id"]] = txt(q.get("text")) + (" (all selected, ; separated)" if t == "multiple" else " (order, first = top)")
            for o in q["options"]:
                what = {"multiple": "1 if selected", "rank": "rank position (1 = top)", "constant_sum": "amount given"}[t]
                cols[f"{q['id']}_{slug(o['value'])}"] = f"{txt(q.get('text'))} – {o['label']}: {what}"
        else:
            cols[q["id"]] = txt(q.get("text")) + tail
            if q.get("other_option"):
                cols[q["id"] + "_other"] = f"{txt(q.get('text'))} – text typed for '{q['other_option']}'"
        if q.get("randomize"):
            cols[q["id"] + "_order"] = f"Order in which the options/items of '{q['id']}' were shown"
    for name, sc in {**lib_scores, **(scores or {})}.items():
        cols[name] = (sc or {}).get("description") or f"Score '{name}'"
        if (sc or {}).get("bands"):
            cols[name + "_band"] = f"Interpretive band of {name}: " + ", ".join(f"≤{m} {lab}" for m, lab in sc["bands"])
    for i, _p in enumerate(pages(flat), 1):
        cols[f"page{i}_time"] = f"Time spent on page {i} (s)"
    return cols


# =========================================================================================== page
SURVEY_CSS = """
:root{--accent:#2f6fde;--line:#d9dee5;--muted:#667085;--err:#c62828;--bg:#f7f8fa}
*{box-sizing:border-box}body{font:17px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:#1d2228}
.wrap{max-width:860px;margin:0 auto;padding:28px 20px 60px}
h1.title{font-size:26px;margin:0 0 6px}.intro{color:#333;margin:0 0 18px}
.progress{height:6px;background:#e6e9ee;border-radius:3px;margin:0 0 22px;overflow:hidden}.progress div{height:100%;background:var(--accent);transition:width .3s}
.q{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 14px}
.q.err{border-color:var(--err);box-shadow:0 0 0 2px rgba(198,40,40,.12)}
.qt{font-weight:600;margin:0 0 10px}.req{color:var(--err);margin-left:3px}.help{color:var(--muted);font-size:14px;margin:-6px 0 10px}
.msg{color:var(--err);font-size:14px;margin-top:8px;display:none}.q.err .msg{display:block}
label.opt{display:flex;align-items:flex-start;gap:9px;padding:7px 9px;border-radius:7px;cursor:pointer}
label.opt:hover{background:#f1f4f9}label.opt input{margin-top:5px;width:18px;height:18px;flex:none}
.horizontal{display:flex;flex-wrap:wrap;gap:6px}.horizontal label.opt{flex:1;min-width:110px;flex-direction:column;align-items:center;text-align:center;border:1px solid var(--line)}
.likert{display:grid;grid-auto-columns:1fr;grid-auto-flow:column;gap:6px}
.likert label.opt{flex-direction:column;align-items:center;text-align:center;border:1px solid var(--line);font-size:14px}
.likert label.opt input{margin:0 0 4px}
.ends{display:flex;justify-content:space-between;color:var(--muted);font-size:14px;margin-top:4px}
table.matrix{border-collapse:collapse;width:100%;font-size:15px}table.matrix th{font-weight:500;font-size:13px;color:#444;padding:4px;vertical-align:bottom}
table.matrix td{border-top:1px solid #eef0f3;padding:8px 4px;text-align:center}table.matrix td.stem{text-align:left;padding-right:10px}
table.matrix tr.miss td.stem{color:var(--err)}table.matrix input{width:19px;height:19px;cursor:pointer}
table.matrix tbody tr:nth-child(odd){background:#fafbfc}
input[type=text],input[type=email],input[type=number],input[type=date],textarea,select{font:inherit;padding:8px 10px;border:1px solid #c5ccd6;border-radius:7px;width:100%;max-width:520px;background:#fff}
textarea{max-width:100%}input[type=number]{max-width:200px}
.other{margin:4px 0 0 36px;max-width:360px}
input[type=range]{width:100%}.sval{font-weight:600;color:var(--accent);margin-left:6px}.untouched .sval{color:var(--muted);font-weight:400}
ol.rank{list-style:none;padding:0;margin:0;counter-reset:r}ol.rank li{counter-increment:r;display:flex;align-items:center;gap:8px;border:1px solid var(--line);border-radius:7px;padding:8px 10px;margin:0 0 6px;background:#fff;cursor:grab}
ol.rank li::before{content:counter(r);font-weight:700;color:var(--accent);width:20px}ol.rank li span{flex:1}ol.rank li button{border:1px solid var(--line);background:#fff;border-radius:5px;cursor:pointer;padding:0 8px}
ol.rank li.drag{opacity:.4}
.csum{display:grid;grid-template-columns:1fr 110px;gap:6px 10px;align-items:center;max-width:520px}.csum input{max-width:110px}.ctotal{font-weight:600}.ctotal.bad{color:var(--err)}
.sem{display:grid;grid-template-columns:minmax(80px,1fr) auto minmax(80px,1fr);gap:8px;align-items:center;margin:6px 0}.sem .l{text-align:right}.sem .pts{display:flex;gap:12px}.sem input{width:19px;height:19px}
.nav{display:flex;gap:10px;justify-content:space-between;margin-top:22px}
.nav button{font:inherit;font-size:17px;padding:10px 26px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer}
.nav button.primary{background:var(--accent);border-color:var(--accent);color:#fff;margin-left:auto}
.pageerr{color:var(--err);text-align:right;margin-top:8px;min-height:1em}
@media (max-width:640px){table.matrix thead{display:none}table.matrix tr{display:block;padding:8px 0}table.matrix td{display:inline-block;border:0}
table.matrix td.stem{display:block}table.matrix td.cell::after{content:attr(data-label);font-size:12px;color:var(--muted);display:block}
.likert{grid-auto-flow:row;gap:4px}.likert label.opt,.horizontal label.opt{flex-direction:row;align-items:center;text-align:left;font-size:15px}
.likert label.opt input{margin:0}.horizontal{flex-direction:column}}
"""

SURVEY_JS = r"""
(function(){
var S = JSON.parse(document.getElementById('edge-survey').textContent);
var T = S.text, root = document.getElementById('survey'), ans = {}, page = 0, t0 = Date.now(), times = {};
function el(tag, attrs, kids){ var e=document.createElement(tag); attrs=attrs||{};
  for (var k in attrs){ if(k==='html') e.innerHTML=attrs[k]; else if(k==='text') e.textContent=attrs[k];
    else if(k.slice(0,2)==='on') e.addEventListener(k.slice(2), attrs[k]); else if(attrs[k]!==null&&attrs[k]!==undefined&&attrs[k]!==false) e.setAttribute(k, attrs[k]===true?'':attrs[k]); }
  (kids||[]).forEach(function(c){ if(c!==null&&c!==undefined) e.appendChild(typeof c==='string'?document.createTextNode(c):c); }); return e; }
function empty(a){ return a===undefined||a===null||a===''||(Array.isArray(a)&&!a.length); }
function cmp(a, op, ref){
  if(op==='answered') return (!empty(a))===!!ref;
  if(empty(a)) return op==='!='||op==='not_in';
  var vals=Array.isArray(a)?a:[a], s=vals.map(String), refs=Array.isArray(ref)?ref.map(String):[String(ref)];
  if(op==='='||op==='=='||op==='contains') return s.indexOf(String(ref))>=0;
  if(op==='!=') return s.indexOf(String(ref))<0;
  if(op==='in') return refs.some(function(r){return s.indexOf(r)>=0;});
  if(op==='not_in') return !refs.some(function(r){return s.indexOf(r)>=0;});
  var x=parseFloat(vals[0]), y=parseFloat(ref); if(isNaN(x)||isNaN(y)) return false;
  return {'>':x>y,'>=':x>=y,'<':x<y,'<=':x<=y}[op]; }
function holds(c){ if(!c) return true;
  for(var k in c){ var v=c[k];
    if(k==='any'){ if(!v.some(holds)) return false; continue; }
    if(k==='all'){ if(!v.every(holds)) return false; continue; }
    var tests = (v!==null&&typeof v==='object'&&!Array.isArray(v)) ? v : (Array.isArray(v)?{'in':v}:{'=':v});
    for(var op in tests) if(!cmp(ans[k], op, tests[op])) return false; }
  return true; }
function labelOf(id){ var v=ans[id]; if(empty(v)) return '…'; var out=[];
  S.flat.forEach(function(q){ (q.options||[]).forEach(function(o){ if(q.id===id && (Array.isArray(v)?v.map(String).indexOf(String(o.value))>=0:String(o.value)===String(v))) out.push(o.label); }); });
  return out.length?out.join(', '):(Array.isArray(v)?v.join(', '):String(v)); }
function pipe(s){ return String(s||'').replace(/\{\{\s*answer\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, function(_, id){ return labelOf(id).replace(/</g,'&lt;'); }); }
function setv(id, v){ ans[id]=v; refreshVisibility(); }
var cards = [];
function radioGroup(q, cls){
  var box=el('div',{'class':cls||''});
  q.options.forEach(function(o){
    var inp=el('input',{type:'radio',name:q.id,value:String(o.value),onchange:function(){ setv(q.id,o.value); if(q.other_option){ other.style.display=(o.label===q.other_option)?'':'none'; } }});
    if(String(ans[q.id])===String(o.value)) inp.checked=true;
    box.appendChild(el('label',{'class':'opt'},[inp, el('span',{html:o.label})]));
  });
  var other=null;
  if(q.other_option){ other=el('input',{type:'text','class':'other',placeholder:T.other,oninput:function(){ ans[q.id+'_other']=other.value; }}); other.style.display='none'; box.appendChild(other); }
  return box; }
function ends(q){ var l=q.labels||[]; return l.length? el('div',{'class':'ends'},[el('span',{text:l[0]||''}), el('span',{text:l[l.length-1]||''})]):null; }
function build(q){
  var t=q.type, body=[];
  if(t==='text_block') return el('div',{'class':'q block',html:pipe(q.text)});
  if(t==='single') body.push(radioGroup(q, q.layout==='horizontal'?'horizontal':''));
  else if(t==='likert'||t==='scale'||t==='nps'){ body.push(radioGroup(q,'likert')); if(t!=='likert') body.push(ends(q)); }
  else if(t==='dropdown'){ var sel=el('select',{onchange:function(){ var o=q.options[sel.selectedIndex-1]; setv(q.id, o?o.value:''); }},[el('option',{value:'',text:T.choose})]);
    q.options.forEach(function(o){ sel.appendChild(el('option',{value:String(o.value),text:o.label})); }); if(!empty(ans[q.id])) sel.value=String(ans[q.id]); body.push(sel); }
  else if(t==='multiple'){ var box=el('div',{'class':q.layout==='horizontal'?'horizontal':''}), excl=(q.exclusive||[]).map(String); ans[q.id]=ans[q.id]||[];
    q.options.forEach(function(o){ var inp=el('input',{type:'checkbox',value:String(o.value),onchange:function(){
        var cur=(ans[q.id]||[]).filter(function(x){return String(x)!==String(o.value);});
        if(inp.checked){ if(excl.indexOf(String(o.value))>=0){ cur=[]; box.querySelectorAll('input[type=checkbox]').forEach(function(c){ if(c!==inp) c.checked=false; }); }
          else { cur=cur.filter(function(x){ return excl.indexOf(String(x))<0; }); box.querySelectorAll('input[type=checkbox]').forEach(function(c){ if(excl.indexOf(c.value)>=0) c.checked=false; }); }
          cur.push(o.value); }
        setv(q.id, cur); }});
      if(ans[q.id].map(String).indexOf(String(o.value))>=0) inp.checked=true;
      box.appendChild(el('label',{'class':'opt'},[inp, el('span',{html:o.label})])); });
    body.push(box); }
  else if(t==='matrix'){ var tb=el('tbody'), head=el('tr',{},[el('th')]);
    q.options.forEach(function(o){ head.appendChild(el('th',{html:o.label})); });
    q.items.forEach(function(it){ var tr=el('tr',{'data-item':it.id},[el('td',{'class':'stem',html:pipe(it.text)})]);
      q.options.forEach(function(o){ var inp=el('input',{type:'radio',name:it.id,value:String(o.value),'aria-label':o.label,onchange:function(){ tr.classList.remove('miss'); setv(it.id,o.value); }});
        if(String(ans[it.id])===String(o.value)) inp.checked=true;
        tr.appendChild(el('td',{'class':'cell','data-label':o.label},[inp])); });
      tb.appendChild(tr); });
    body.push(el('table',{'class':'matrix'},[el('thead',{},[head]), tb])); }
  else if(t==='semantic'){ q.items.forEach(function(it){ var pts=el('div',{'class':'pts'});
      q.options.forEach(function(o){ var r=el('input',{type:'radio',name:it.id,value:String(o.value),'aria-label':it.left+' '+o.label+' '+it.right,onchange:function(){ setv(it.id,o.value); }});
        if(String(ans[it.id])===String(o.value)) r.checked=true; pts.appendChild(r); });
      body.push(el('div',{'class':'sem','data-item':it.id},[el('span',{'class':'l',text:it.left}), pts, el('span',{text:it.right})])); }); }
  else if(t==='slider'){ var lo=+(q.min||0), hi=+(q.max===undefined?100:q.max), st=+(q.step||1), wrap=el('div',{'class':'untouched'});
    var val=el('span',{'class':'sval',text:T.move}), rng=el('input',{type:'range',min:lo,max:hi,step:st,value:q.start!==undefined?q.start:(lo+hi)/2,
      oninput:function(){ wrap.classList.remove('untouched'); val.textContent=rng.value; setv(q.id, +rng.value); }});
    if(!empty(ans[q.id])){ rng.value=ans[q.id]; wrap.classList.remove('untouched'); val.textContent=ans[q.id]; }
    wrap.appendChild(rng); wrap.appendChild(ends(q)); body.push(el('div',{},[wrap, el('div',{},[T.value, val])])); }
  else if(t==='text'||t==='number'||t==='date'){ var ty=t==='text'?(q.validate==='email'?'email':'text'):t;
    var inp=el('input',{type:ty,min:q.min,max:q.max,step:q.step||(t==='number'?'any':null),maxlength:q.max_length,placeholder:q.placeholder,
      oninput:function(){ ans[q.id]=inp.value; },onchange:function(){ setv(q.id, inp.value); }}); if(!empty(ans[q.id])) inp.value=ans[q.id]; body.push(inp); }
  else if(t==='essay'){ var ta=el('textarea',{rows:q.rows||5,maxlength:q.max_length,placeholder:q.placeholder,oninput:function(){ ans[q.id]=ta.value; cnt.textContent=ta.value.length+(q.max_length?' / '+q.max_length:''); },onchange:function(){ setv(q.id, ta.value); }});
    var cnt=el('div',{'class':'help',style:'margin:4px 0 0;text-align:right'}); if(!empty(ans[q.id])) ta.value=ans[q.id]; body.push(ta, cnt); }
  else if(t==='rank'){ var ol=el('ol',{'class':'rank'}), drag=null;
    function save(){ ans[q.id]=[].map.call(ol.children,function(li){ return q.options[+li.dataset.i].value; }); }
    var prev=(ans[q.id]||[]).map(String), idx=q.options.map(function(o,i){return i;});
    if(prev.length) idx.sort(function(a,b){ return prev.indexOf(String(q.options[a].value))-prev.indexOf(String(q.options[b].value)); });
    idx.forEach(function(i){ var o=q.options[i]; var li=el('li',{draggable:'true','data-i':i},[el('span',{html:o.label}),
        el('button',{type:'button','aria-label':T.up,onclick:function(){ if(li.previousElementSibling) ol.insertBefore(li, li.previousElementSibling); save(); }},['↑']),
        el('button',{type:'button','aria-label':T.down,onclick:function(){ if(li.nextElementSibling) ol.insertBefore(li.nextElementSibling, li); save(); }},['↓'])]);
      li.addEventListener('dragstart',function(){ drag=li; li.classList.add('drag'); }); li.addEventListener('dragend',function(){ li.classList.remove('drag'); save(); });
      li.addEventListener('dragover',function(e){ e.preventDefault(); if(drag&&drag!==li){ var r=li.getBoundingClientRect(); ol.insertBefore(drag, (e.clientY-r.top)>r.height/2?li.nextSibling:li); } });
      ol.appendChild(li); });
    save(); body.push(ol, el('div',{'class':'help',style:'margin:6px 0 0',text:T.rank})); }
  else if(t==='constant_sum'){ var total=+(q.total||100), grid=el('div',{'class':'csum'}), tot=el('span',{'class':'ctotal'}); ans[q.id]=ans[q.id]||{};
    function upd(){ var s=0; for(var k in ans[q.id]) s+=(+ans[q.id][k]||0); tot.textContent=s+' / '+total; tot.classList.toggle('bad', s!==total); }
    q.options.forEach(function(o){ var inp=el('input',{type:'number',min:0,max:total,step:q.step||1,value:ans[q.id][String(o.value)]===undefined?'':ans[q.id][String(o.value)],oninput:function(){ ans[q.id][String(o.value)]=inp.value===''?'':+inp.value; upd(); }});
      grid.appendChild(el('span',{html:o.label})); grid.appendChild(inp); });
    grid.appendChild(el('span',{'class':'help',style:'margin:0',text:T.total})); grid.appendChild(tot); upd(); body.push(grid); }
  var card=el('div',{'class':'q','data-q':q.id||''},[el('div',{'class':'qt',html:pipe(q.text)},[q.required?el('span',{'class':'req',text:'*'}):null]),
    q.help?el('div',{'class':'help',html:q.help}):null].concat(body).concat([el('div',{'class':'msg'})]));
  return card; }
function refreshVisibility(){ cards.forEach(function(c){ var show=holds(c.q.show_if); c.el.style.display=show?'':'none';
  if(c.el.querySelector('.qt') && c.q.text && c.q.text.indexOf('{{answer.')>=0){ var qt=c.el.querySelector('.qt'); var req=qt.querySelector('.req'); qt.innerHTML=pipe(c.q.text); if(req) qt.appendChild(req); } }); }
function problem(q){ var t=q.type, a=ans[q.id];
  if(t==='matrix'||t==='semantic'){ var miss=q.items.filter(function(it){ return empty(ans[it.id]); });
    cardOf(q).querySelectorAll('tr[data-item],div[data-item]').forEach(function(r){ r.classList.toggle('miss', q.required && empty(ans[r.dataset.item])); });
    return q.required&&miss.length? (miss.length===q.items.length?T.required:T.rows.replace('{n}',miss.length)) : ''; }
  if(t==='constant_sum'){ var s=0, any=false; for(var k in a){ if(a[k]!==''){ any=true; s+=+a[k]; } }
    if(!any) return q.required?T.required:''; return s!==+(q.total||100)?T.sum.replace('{total}',q.total||100):''; }
  if(t==='rank') return '';
  if(empty(a)) return q.required?(t==='slider'?T.slider:T.required):'';
  if(t==='multiple'){ if(q.min_choices&&a.length<q.min_choices) return T.min.replace('{n}',q.min_choices); if(q.max_choices&&a.length>q.max_choices) return T.max.replace('{n}',q.max_choices); }
  if(t==='number'||(t==='text'&&(q.validate==='number'||q.validate==='integer'))){ var x=Number(a); if(isNaN(x)||(q.validate==='integer'&&Math.round(x)!==x)) return T.number;
    if(q.min!==undefined&&x<q.min) return T.low.replace('{n}',q.min); if(q.max!==undefined&&x>q.max) return T.high.replace('{n}',q.max); }
  if(t==='text'&&q.validate==='email'&&!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) return T.email;
  if(t==='text'&&q.pattern&&!(new RegExp('^(?:'+q.pattern+')$')).test(a)) return q.pattern_message||T.format;
  if(t==='essay'&&q.min_length&&String(a).length<q.min_length) return T.short.replace('{n}',q.min_length);
  if(q.other_option&&labelOf(q.id)===q.other_option&&empty(ans[q.id+'_other'])) return T.other_missing;
  return ''; }
function cardOf(q){ return cards.filter(function(c){ return c.q===q; })[0].el; }
function show(p){ page=p; root.innerHTML=''; cards=[];
  if(S.title&&p===0) root.appendChild(el('h1',{'class':'title',html:S.title}));
  if(S.intro&&p===0) root.appendChild(el('p',{'class':'intro',html:pipe(S.intro)}));
  if(S.progress&&S.pages.length>1){ var pr=el('div',{'class':'progress'},[el('div',{style:'width:'+Math.round(100*p/S.pages.length)+'%'})]); root.appendChild(pr); }
  S.pages[p].forEach(function(q){ var c=build(q); cards.push({q:q, el:c}); root.appendChild(c); });
  refreshVisibility();
  var last=p===S.pages.length-1, err=el('div',{'class':'pageerr'});
  var nav=el('div',{'class':'nav'},[ (p>0&&S.back)?el('button',{type:'button',onclick:function(){ leave(); show(p-1); }},[T.back]):null,
    el('button',{type:'button','class':'primary',onclick:function(){ if(!check(err)) return; leave(); if(last) finish(); else show(p+1); }},[last?T.submit:T.next]) ]);
  root.appendChild(nav); root.appendChild(err); window.scrollTo(0,0); t0=Date.now(); }
function leave(){ var k='page'+(page+1)+'_time'; times[k]=(times[k]||0)+(Date.now()-t0)/1000; }
function check(err){ var bad=null;
  cards.forEach(function(c){ if(!c.q.id&&c.q.type!=='matrix'&&c.q.type!=='semantic') return; var visible=c.el.style.display!=='none';
    var m=visible?problem(c.q):''; c.el.classList.toggle('err', !!m); var box=c.el.querySelector('.msg'); if(box) box.textContent=m; if(m&&!bad) bad=c.el; });
  err.textContent=bad?T.fix:''; if(bad) bad.scrollIntoView({behavior:'smooth',block:'center'}); return !bad; }
function finish(){ var out={};
  S.flat.forEach(function(q){ if(!holds(q.show_if)) return; var ids=(q.type==='matrix'||q.type==='semantic')?q.items.map(function(i){return i.id;}):(q.id?[q.id]:[]);
    ids.forEach(function(id){ if(id in ans) out[id]=ans[id]; }); if(q.other_option&&ans[q.id+'_other']) out[q.id+'_other']=ans[q.id+'_other']; });
  for(var k in times) out[k]=Math.round(times[k]*100)/100;
  window.edge.submit(out); }
show(0);
})();
"""

DEFAULT_TEXT = {"next": "Next", "back": "Back", "submit": "Submit", "required": "Please answer this question.",
                "rows": "Please answer all statements ({n} missing).", "fix": "Some answers are missing or need a fix.",
                "choose": "Choose …", "other": "Please specify", "other_missing": "Please write your answer in the box.",
                "min": "Please choose at least {n}.", "max": "Please choose at most {n}.",
                "number": "Please enter a number.", "low": "The number must be at least {n}.",
                "high": "The number must be at most {n}.", "email": "Please enter a valid e-mail address.",
                "format": "Please check the format of your answer.", "short": "Please write at least {n} characters.",
                "sum": "The amounts must add up to {total}.", "total": "Total", "slider": "Please move the slider.",
                "move": "(move the slider)", "value": "Your answer: ", "rank": "Drag the options, or use ↑ ↓, to put "
                                                                            "them in order (top = first).",
                "up": "Move up", "down": "Move down"}


def render_html(spec: dict[str, Any], rng: random.Random | None = None) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """The participant-facing page. Returns (html, flat questions as shown, scores)."""
    flat, lib_scores = expand(spec.get("questions") or [], rng)
    scores = {**lib_scores, **(spec.get("scores") or {})}
    pg = pages(flat)
    text = {**DEFAULT_TEXT, **(spec.get("labels") or {})}
    for k in ("next", "back", "submit"):
        if spec.get(f"{k}_label"):
            text[k] = spec[f"{k}_label"]
    data = {"title": spec.get("title") or "", "intro": spec.get("intro") or "", "pages": pg, "flat": flat,
            "progress": spec.get("progress_bar", True), "back": spec.get("allow_back", True), "text": text}
    blob = json.dumps(data, default=str).replace("<", "\\u003c")     # no '<' can end or confuse the script block
    page = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{htmllib.escape(re.sub(r'<[^>]+>', '', str(spec.get('title') or 'Survey')))}</title>"
            f"<style>{SURVEY_CSS}{spec.get('css') or ''}</style></head><body><div class='wrap'><div id='survey'></div></div>"
            f"<script type='application/json' id='edge-survey'>{blob}</script>"
            f"<script>window.addEventListener('load',function(){{{SURVEY_JS}}});</script></body></html>")
    return page, flat, scores
