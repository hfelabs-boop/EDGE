"""Surveys: questionnaires built from structured questions instead of hand-written HTML.

    - id: about_you
      type: survey
      title: A few questions about you
      language: en                                   # he, ar … switch the page to right-to-left
      questions:
        - {instrument: demographics}                  # from the library (edge/survey_library.py)
        - {id: mood, type: likert, scale: agree7, text: "I feel good right now."}
        - {id: hobbies, type: multiple, text: "Which do you do weekly?", options: [Sport, Music, Reading],
           exclusive: [None of these]}
        - {type: page_break}
        - {instrument: phq9}

Question types follow the standard catalogue of professional survey platforms:

Standard
  text_block     text, HTML, an image, video or audio (``media``) without an answer
  single         one answer (radio buttons; ``layout: horizontal``; ``other_option``)
  dropdown       one answer from a drop-down list
  multiple       several answers (checkboxes; ``layout: listbox`` = multi-select box; ``min_choices``,
                 ``max_choices``, ``exclusive``)
  likert         one statement on a scale (``scale: agree5`` … or your own ``options``)
  matrix         statements (``items``) on a shared scale; ``multi: true`` = checkboxes per row,
                 ``display: dropdown`` = a drop-down per row
  semantic       bipolar items (``left``/``right``) on an N-point scale (semantic differential)
  scale          a number scale 1..N (``points``), optionally for several ``items``
  nps            Net Promoter 0-10, with promoter / passive / detractor saved
  slider         slider(s) (``min``, ``max``, ``step``, end ``labels``; ``items`` for several)
  graphic_slider faces that change with the value, or clickable stars / hearts (``style``)
  text           one line (``validate: email | number | integer``, ``pattern``, ``secret`` = password)
  essay          several lines (``rows``; 2 rows = multi-line short text)
  number         a number (``min``, ``max``, ``unit``)
  date           a calendar date picker (``min``, ``max``); ``calendar`` is the same
  form           several labelled fields (name, e-mail, phone …) in one question (``fields``)
  rank           put options in order (``method: drag | select | text``)
  side_by_side   several questions (``columns``) for the same rows (``items``) in one table
Advanced
  constant_sum   share a ``total`` across options (``must_total: exact | at_most | at_least``, ``unit``)
  group          pick, group & rank: sort ``items`` into ``groups`` (``rank_within``, ``require_all``)
  hot_spot       clickable regions on an image (``mode: select | rate``)
  heat_map       clicks anywhere on an image (x, y; ``max_clicks``; optional ``regions`` to count hits)
  drill_down     cascading drop-downs (``levels`` + ``tree``, e.g. country → region → city)
  highlight      highlight words of a ``passage`` in categories (e.g. like / dislike)
  signature      draw a signature (saved as a PNG file in the session folder)
  timing         invisible: time on page, clicks; ``min_seconds`` before Next, ``max_seconds`` auto-advance
  meta_info      invisible: browser, operating system, screen size, language, time zone
  file_upload    attach a file (``accept``, ``max_mb``; saved in the session folder)
  captcha        a typed code check (offline, no external service)
  autocomplete   a text field with suggestions (``options`` or ``list: countries | languages``)
Specialty
  tree_test      find an item in a navigation tree (``tree``, ``task``, ``correct``): path, success, directness
  video_response record video or audio with the webcam / microphone (``audio_only``, ``max_seconds``)
  screen_capture capture the screen and black out private parts (saved as PNG)
  location       mark a place on a map image (``bounds`` → latitude/longitude) or use the device location
  page_break     starts a new page

Every question can have ``required``, ``help``, ``show_if`` (display logic based on earlier answers) and,
for choice questions, ``randomize`` (the order shown is saved). ``correct`` marks a right answer (knowledge
or attention checks). ``test_answer`` fixes what the virtual participant answers in test runs (the consent
question uses ``test_answer: yes`` so test runs go through the whole study).

``show_if`` examples: ``{gender: Woman}``, ``{age: {">=": 18}}``, ``{hobbies: {contains: Sport}}``,
``{consent: yes, age: {">=": 18}}`` (all must hold), ``{any: [{a: 1}, {b: 1}]}``,
``{email: {answered: true}}``. Questions can show earlier answers with ``{{answer.<id>}}``.

Right-to-left: ``language: he`` / ``ar`` / ``fa`` … or ``direction: rtl`` lays the page out right to left
(and translates the buttons and messages where a translation exists). With ``direction: auto`` (the
default) the page follows the language, or the first strong character of the title and first question.
"""

from __future__ import annotations

import base64
import copy
import html as htmllib
import json
import random
import re
from pathlib import Path
from typing import Any

from . import survey_library as lib

QUESTION_TYPES: dict[str, dict[str, Any]] = {
    "text_block": {"label": "Text / graphic", "group": "Standard", "answer": False},
    "single": {"label": "Single choice", "group": "Standard", "answer": True},
    "dropdown": {"label": "Drop-down list", "group": "Standard", "answer": True},
    "multiple": {"label": "Multiple choice (checkboxes)", "group": "Standard", "answer": True},
    "likert": {"label": "Likert item", "group": "Standard", "answer": True},
    "matrix": {"label": "Matrix table", "group": "Standard", "answer": True},
    "semantic": {"label": "Bipolar / semantic differential", "group": "Standard", "answer": True},
    "scale": {"label": "Number scale", "group": "Standard", "answer": True},
    "nps": {"label": "Net Promoter Score", "group": "Standard", "answer": True},
    "slider": {"label": "Slider", "group": "Standard", "answer": True},
    "text": {"label": "Text entry (single line)", "group": "Standard", "answer": True},
    "essay": {"label": "Text entry (essay)", "group": "Standard", "answer": True},
    "number": {"label": "Number", "group": "Standard", "answer": True},
    "date": {"label": "Calendar (date)", "group": "Standard", "answer": True},
    "form": {"label": "Form fields", "group": "Standard", "answer": True},
    "rank": {"label": "Rank order", "group": "Standard", "answer": True},
    "side_by_side": {"label": "Side by side", "group": "Standard", "answer": True},
    "constant_sum": {"label": "Constant sum", "group": "Advanced", "answer": True},
    "group": {"label": "Pick, group & rank", "group": "Advanced", "answer": True},
    "hot_spot": {"label": "Hot spot (image regions)", "group": "Advanced", "answer": True},
    "heat_map": {"label": "Heat map (image clicks)", "group": "Advanced", "answer": True},
    "graphic_slider": {"label": "Graphic slider (faces / stars)", "group": "Advanced", "answer": True},
    "drill_down": {"label": "Drill down (cascading lists)", "group": "Advanced", "answer": True},
    "highlight": {"label": "Highlight words", "group": "Advanced", "answer": True},
    "signature": {"label": "Signature", "group": "Advanced", "answer": True},
    "timing": {"label": "Timing (invisible)", "group": "Advanced", "answer": True},
    "meta_info": {"label": "Meta info (invisible)", "group": "Advanced", "answer": True},
    "file_upload": {"label": "File upload", "group": "Advanced", "answer": True},
    "captcha": {"label": "Captcha (typed code)", "group": "Advanced", "answer": True},
    "autocomplete": {"label": "Autocomplete", "group": "Advanced", "answer": True},
    "tree_test": {"label": "Tree testing", "group": "Specialty", "answer": True},
    "video_response": {"label": "Video / audio response", "group": "Specialty", "answer": True},
    "screen_capture": {"label": "Screen capture", "group": "Specialty", "answer": True},
    "location": {"label": "Location (map / device)", "group": "Specialty", "answer": True},
    "page_break": {"label": "Page break", "group": "Display", "answer": False},
}
ALIASES = {"calendar": "date", "text_graphic": "text_block", "descriptive": "text_block", "form_field": "form",
           "pick_group_rank": "group", "multiple_choice": "single"}
CHOICE_TYPES = {"single", "dropdown", "multiple", "likert"}
OPTION_TYPES = CHOICE_TYPES | {"matrix", "nps", "scale", "semantic", "rank", "constant_sum", "autocomplete"}
ITEM_TYPES = {"matrix", "semantic"}                 # always have items
FILE_TYPES = {"signature", "file_upload", "video_response", "screen_capture"}
INVISIBLE = {"timing", "meta_info"}
OPS = {"=", "==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "answered"}
FORM_FIELD_TYPES = {"text", "email", "number", "tel", "date", "password", "url"}
META_KEYS = ["browser", "os", "screen", "viewport", "pixel_ratio", "language", "timezone", "touch", "user_agent"]
TIMING_KEYS = ["first_click", "last_click", "submit", "clicks"]
PNG_1PX = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8"
           "AAAAASUVORK5CYII=")


class SurveyError(ValueError):
    pass


# =========================================================================================== model
def slug(text: Any) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(text)).strip("_").lower()
    return (s or "option")[:40]


def _norm_list(raw: Any) -> list[dict[str, Any]]:
    out = []
    for o in raw or []:
        if isinstance(o, dict):
            label = str(o.get("label", o.get("value", "")))
            out.append({"value": o.get("value", label), "label": label})
        else:
            out.append({"value": o, "label": str(o)})
    return out


def norm_options(q: dict[str, Any]) -> list[dict[str, Any]]:
    """Options as [{value, label}], from ``options`` (strings or dicts), a named ``scale`` or a built-in ``list``."""
    t = q.get("type")
    if t == "nps":
        return [{"value": i, "label": str(i)} for i in range(11)]
    if t == "scale":
        n = int(q.get("points") or 7)
        start = int(q.get("start", 1))
        return [{"value": i, "label": str(i)} for i in range(start, start + n)]
    if t == "semantic":
        n = int(q.get("points") or 7)
        return [{"value": i, "label": str(i)} for i in range(1, n + 1)]
    if t == "autocomplete" and q.get("list") and not q.get("options"):
        from .survey_lists import LISTS
        if q["list"] not in LISTS:
            raise SurveyError(f"unknown list '{q['list']}' (available: {', '.join(LISTS)})")
        return _norm_list(LISTS[q["list"]])
    if q.get("options") is None and q.get("scale"):
        return lib.scale_options(str(q["scale"]))
    return _norm_list(q.get("options"))


def _items(q: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, it in enumerate(q.get("items") or [], 1):
        out.append(dict(it) if isinstance(it, dict) else {"id": f"{q.get('id', 'item')}_{i}", "text": str(it)})
    return out


def expand(questions: list[Any], rng: random.Random | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Expand ``{instrument: …}`` entries, resolve scales and lists and (with ``rng``) shuffle what should be
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
            sub, _ = expand(items, rng)
            flat += sub
            scores.update(ins.get("scores") or {})
            continue
        q = copy.deepcopy(q)
        t = ALIASES.get(q.get("type", "single"), q.get("type", "single"))
        q["type"] = t
        if t in OPTION_TYPES:
            q["options"] = norm_options(q)
        if t == "side_by_side":
            for c in q.get("columns") or []:
                c.setdefault("type", "single")
                if c["type"] in ("single", "multiple", "dropdown"):
                    c["options"] = norm_options({**c, "type": c["type"]})
        if t == "group":
            q["items"] = _norm_list(q.get("items"))
            q["groups"] = [g if isinstance(g, dict) else {"id": slug(g), "label": str(g)} for g in q.get("groups") or []]
            for g in q["groups"]:
                g.setdefault("id", slug(g.get("label", "group")))
                g.setdefault("label", g["id"])
        if t == "highlight" and not q.get("categories"):
            q["categories"] = [{"id": "like", "label": "Like", "color": "#9be3b0"},
                               {"id": "dislike", "label": "Dislike", "color": "#f5a3a3"}]
        if t == "highlight":
            for c in q["categories"]:
                c.setdefault("id", slug(c.get("label", "cat")))
                c.setdefault("label", c["id"])
                c.setdefault("color", "#ffe58a")
        if t in ("hot_spot", "heat_map"):
            for i, r in enumerate(q.get("regions") or [], 1):
                r.setdefault("id", f"r{i}")
        if t in ("drill_down", "tree_test") and q.get("rows") and not q.get("tree"):
            q["tree"] = rows_to_tree(q["rows"])
        if t == "form":
            for f in q.get("fields") or []:
                f.setdefault("type", "text")
                f.setdefault("label", f.get("id", ""))
        if rng is not None and q.get("randomize") and t in ("single", "multiple", "dropdown", "rank", "constant_sum"):
            fixed_tail = [o for o in q["options"] if o.get("label") in (q.get("other_option"),) or
                          o.get("value") in (q.get("exclusive") or [])]
            movable = [o for o in q["options"] if o not in fixed_tail]
            rng.shuffle(movable)
            q["options"] = movable + fixed_tail
            q["shown_order"] = [o["value"] for o in q["options"]]
        if t in ITEM_TYPES or (t in ("scale", "slider", "side_by_side") and q.get("items")):
            q["items"] = _items(q)
            if rng is not None and q.get("randomize"):
                rng.shuffle(q["items"])
                q["shown_order"] = [it["id"] for it in q["items"]]
        if rng is not None and q.get("randomize") and t == "group":
            rng.shuffle(q["items"])
            q["shown_order"] = [it["value"] for it in q["items"]]
        flat.append(q)
    return flat, scores


def rows_to_tree(rows: list[list[Any]]) -> dict[str, Any]:
    """[[USA, California, LA], [USA, California, SF]] -> {USA: {California: [LA, SF]}}"""
    tree: dict[str, Any] = {}
    for row in rows:
        row = [str(x) for x in row if str(x) != ""]
        if not row:
            continue
        node: Any = tree
        for i, part in enumerate(row[:-1]):
            if i == len(row) - 2:
                lst = node.setdefault(part, [])
                if isinstance(lst, list) and row[-1] not in lst:
                    lst.append(row[-1])
            else:
                nxt = node.setdefault(part, {})
                if isinstance(nxt, list):          # deeper rows under a former leaf list
                    nxt = node[part] = {x: [] for x in nxt}
                node = nxt
        if len(row) == 1:
            node.setdefault(row[0], [])
    return tree


def answer_ids(q: dict[str, Any]) -> list[str]:
    """Data ids a question produces (before suffixes)."""
    t = q.get("type")
    if t in ITEM_TYPES or (t in ("scale", "slider") and q.get("items")):
        return [str(it["id"]) for it in q.get("items") or []]
    if t == "side_by_side":
        return [f"{it['id']}_{c['id']}" for it in q.get("items") or [] for c in q.get("columns") or []]
    if t == "form":
        return [str(f["id"]) for f in q.get("fields") or []]
    if QUESTION_TYPES.get(t, {}).get("answer") and q.get("id"):
        return [str(q["id"])]
    return []


def count_items(questions: list[Any]) -> int:
    flat, _ = expand(questions)
    return sum(len(answer_ids(q)) for q in flat if q["type"] not in INVISIBLE)


def pages(flat: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = [[]]
    for q in flat:
        if q["type"] == "page_break":
            if out[-1]:
                out.append([])
        else:
            out[-1].append(q)
    return [p for p in out if p] or [[]]


def _children(tree: Any, k: Any) -> Any:
    return None if isinstance(tree, list) else tree[k]


def tree_paths(tree: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Every node path of a navigation tree (dict of dicts / lists)."""
    out = []
    for k in (tree if isinstance(tree, list) else list((tree or {}).keys())):
        p = prefix + (str(k),)
        out.append(p)
        child = _children(tree, k)
        if child:
            out += tree_paths(child, p)
    return out


def tree_leaves(tree: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    out = []
    for k in (tree if isinstance(tree, list) else list((tree or {}).keys())):
        p = prefix + (str(k),)
        child = _children(tree, k)
        out += tree_leaves(child, p) if child else [p]
    return out


def _path(p: Any) -> tuple[str, ...]:
    if isinstance(p, (list, tuple)):
        return tuple(str(x) for x in p)
    return tuple(x.strip() for x in re.split(r"\s*(?:>|/|›)\s*", str(p)) if x.strip())


def _correct_paths(q: dict[str, Any]) -> list[tuple[str, ...]]:
    corr = q.get("correct")
    if not corr:
        return []
    if isinstance(corr, list) and corr and isinstance(corr[0], (list, tuple)):
        return [_path(c) for c in corr]
    if isinstance(corr, list) and corr and all(isinstance(c, str) and (">" in c or "/" in c) for c in corr):
        return [_path(c) for c in corr]
    return [_path(corr)]


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
        if QUESTION_TYPES[t]["answer"] and t != "form":
            if not q.get("id"):
                problems.append(f"{label}: needs an id (the name of its data column)")
            elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(q["id"])):
                problems.append(f"{label}: id '{q['id']}' must use letters, digits and _ only")
        if t in CHOICE_TYPES | {"matrix", "rank", "constant_sum", "autocomplete"} and not q.get("options"):
            problems.append(f"{label}: needs options (or a scale such as agree5)")
        if t in ITEM_TYPES and not q.get("items"):
            problems.append(f"{label}: needs items (the statements to rate)")
        if t == "semantic":
            for it in q.get("items") or []:
                if not (it.get("left") and it.get("right")):
                    problems.append(f"{label}: semantic items need 'left' and 'right' words")
                    break
        if t == "slider" and float(q.get("max", 100)) <= float(q.get("min", 0)):
            problems.append(f"{label}: max must be larger than min")
        if t in ("multiple", "matrix") and q.get("min_choices") and q.get("max_choices") and \
                int(q["min_choices"]) > int(q["max_choices"]):
            problems.append(f"{label}: min_choices is larger than max_choices")
        if t == "side_by_side":
            if not q.get("items") or not q.get("columns"):
                problems.append(f"{label}: needs items (rows) and columns (the questions)")
            for c in q.get("columns") or []:
                if not c.get("id") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(c.get("id"))):
                    problems.append(f"{label}: every column needs an id (letters, digits, _)")
                elif c["type"] not in ("single", "multiple", "dropdown", "text", "number"):
                    problems.append(f"{label}: column '{c['id']}' type must be single, multiple, dropdown, text or number")
                elif c["type"] in ("single", "multiple", "dropdown") and not c.get("options"):
                    problems.append(f"{label}: column '{c['id']}' needs options (or a scale)")
        if t == "form":
            if not q.get("fields"):
                problems.append(f"{label}: needs fields")
            for f in q.get("fields") or []:
                if not f.get("id") or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(f.get("id"))):
                    problems.append(f"{label}: every field needs an id (letters, digits, _)")
                elif f["type"] not in FORM_FIELD_TYPES:
                    problems.append(f"{label}: field '{f['id']}' type must be one of {', '.join(sorted(FORM_FIELD_TYPES))}")
        if t == "group" and (not q.get("items") or not q.get("groups")):
            problems.append(f"{label}: needs items (to sort) and groups (the categories)")
        if t in ("hot_spot", "heat_map") and not q.get("image"):
            problems.append(f"{label}: needs an image")
        if t == "hot_spot":
            if not q.get("regions"):
                problems.append(f"{label}: needs regions (x, y, w, h in % of the image)")
            for r in q.get("regions") or []:
                if any(not isinstance(r.get(k), (int, float)) or not 0 <= r[k] <= 100 for k in ("x", "y", "w", "h")):
                    problems.append(f"{label}: region '{r.get('id')}' needs x, y, w, h between 0 and 100 (% of the image)")
                    break
            if q.get("mode", "select") not in ("select", "rate"):
                problems.append(f"{label}: mode must be select or rate")
        if t == "location":
            if not q.get("image") and not q.get("allow_geolocation"):
                problems.append(f"{label}: needs a map image or allow_geolocation: true")
            b = q.get("bounds")
            if b is not None and (not isinstance(b, dict) or set(b) != {"north", "south", "east", "west"}):
                problems.append(f"{label}: bounds needs north, south, east and west")
        if t == "drill_down" and (not q.get("levels") or not (q.get("tree") or q.get("file"))):
            problems.append(f"{label}: needs levels (the names of the lists) and a tree (or rows, or a file)")
        if t == "highlight" and not q.get("passage"):
            problems.append(f"{label}: needs a passage (the text to highlight)")
        if t == "tree_test":
            if not q.get("tree"):
                problems.append(f"{label}: needs a tree (the menu structure)")
            else:
                paths = set(tree_paths(q["tree"]))
                for c in _correct_paths(q):
                    if c not in paths:
                        problems.append(f"{label}: correct answer '{' > '.join(c)}' is not in the tree")
        if t == "graphic_slider" and q.get("style", "faces") not in ("faces", "stars", "hearts"):
            problems.append(f"{label}: style must be faces, stars or hearts")
        if t == "constant_sum" and q.get("must_total", "exact") not in ("exact", "at_most", "at_least"):
            problems.append(f"{label}: must_total must be exact, at_most or at_least")
        if t == "rank" and q.get("method", "drag") not in ("drag", "select", "text"):
            problems.append(f"{label}: method must be drag, select or text")
        if t == "multiple" and q.get("layout") not in (None, "vertical", "horizontal", "listbox"):
            problems.append(f"{label}: layout must be vertical, horizontal or listbox")
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


def media_files(questions: list[Any]) -> list[str]:
    """Local image / media files the questions use (for checks and bundles)."""
    flat, _ = expand(questions)
    out = []
    for q in flat:
        for k in ("media", "image"):
            v = q.get(k)
            if isinstance(v, str) and v and not re.match(r"^(https?:|data:|/)", v):
                out.append(v)
    return out


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
    return a is None or a == "" or a == [] or a == {}


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
            t = q["type"]
            if not condition_holds(q.get("show_if"), ans) and t != "meta_info":
                continue
            opts = q.get("options") or []
            if not QUESTION_TYPES.get(t, {}).get("answer"):
                continue
            qid = q.get("id")
            if q.get("test_answer") is not None:          # e.g. consent: test runs go through the study
                ans[qid] = q["test_answer"]
                continue
            if not q.get("required") and t not in INVISIBLE and rng.random() < 0.05:
                continue      # an occasional skipped optional question, like real data
            if q.get("correct") is not None and t != "tree_test" and rng.random() < attention:
                ans[qid] = q["correct"]
                continue
            if t in ("single", "dropdown", "likert", "nps", "autocomplete") or (t == "scale" and not q.get("items")):
                o = rng.choice(opts)
                ans[qid] = o["value"]
                if q.get("other_option") and o["label"] == q["other_option"]:
                    ans[qid + "_other"] = "virtual participant"
            elif t == "scale":
                for it in q["items"]:
                    ans[it["id"]] = rng.choice(opts)["value"]
            elif t == "multiple":
                excl = [str(x) for x in q.get("exclusive") or []]
                pool = [o["value"] for o in opts if str(o["value"]) not in excl]
                lo = int(q.get("min_choices") or (1 if q.get("required") else 0))
                hi = int(q.get("max_choices") or len(pool))
                k = rng.randint(min(lo, len(pool)), max(min(hi, len(pool)), min(lo, len(pool))))
                ans[qid] = rng.sample(pool, k) if pool else []
            elif t in ("matrix", "semantic"):
                for it in q["items"]:
                    if q.get("multi"):
                        lo = int(q.get("min_choices") or 1)
                        hi = int(q.get("max_choices") or len(opts))
                        k = rng.randint(min(lo, len(opts)), min(hi, len(opts)))
                        ans[it["id"]] = [o["value"] for o in rng.sample(opts, k)]
                    else:
                        ans[it["id"]] = rng.choice(opts)["value"]
            elif t == "side_by_side":
                for it in q["items"]:
                    for c in q["columns"]:
                        key = f"{it['id']}_{c['id']}"
                        if c["type"] in ("single", "dropdown"):
                            ans[key] = rng.choice(c["options"])["value"]
                        elif c["type"] == "multiple":
                            ans[key] = [o["value"] for o in rng.sample(c["options"], rng.randint(1, len(c["options"])))]
                        elif c["type"] == "number":
                            ans[key] = rng.randint(0, 10)
                        else:
                            ans[key] = "virtual participant"
            elif t == "slider":
                lo, hi, st = float(q.get("min", 0)), float(q.get("max", 100)), float(q.get("step", 1))
                n = int(round((hi - lo) / st))
                for key in ([it["id"] for it in q["items"]] if q.get("items") else [qid]):
                    v = lo + rng.randint(0, n) * st
                    ans[key] = int(v) if float(v).is_integer() else round(v, 6)
            elif t == "graphic_slider":
                ans[qid] = rng.randint(1, int(q.get("points") or 5))
            elif t == "number":
                lo, hi = int(_num(q.get("min")) or 0), int(_num(q.get("max")) or 99)
                ans[qid] = rng.randint(lo, max(lo, hi))
            elif t == "text":
                ans[qid] = {"email": "virtual.participant@example.org", "number": "42",
                            "integer": "42"}.get(q.get("validate"), "virtual participant")
            elif t == "essay":
                ans[qid] = "An answer written by the virtual participant."
            elif t == "date":
                ans[qid] = q.get("min") or "2000-01-01"
            elif t == "form":
                for f in q["fields"]:
                    ans[f["id"]] = {"email": "virtual.participant@example.org", "number": "42", "tel": "+1 555 0100",
                                    "date": "2000-01-01", "url": "https://example.org", "password": "secret"}.get(
                        f["type"], "virtual participant")
            elif t == "rank":
                order = [o["value"] for o in opts]
                rng.shuffle(order)
                ans[qid] = order
            elif t == "constant_sum":
                total = float(q.get("total", 100))
                cuts = sorted(rng.uniform(0, total) for _ in range(len(opts) - 1))
                parts = [b - a for a, b in zip([0.0] + cuts, cuts + [total])]
                ints = [int(round(p)) for p in parts]
                ints[-1] += int(total) - sum(ints)
                ans[qid] = {str(o["value"]): v for o, v in zip(opts, ints)}
            elif t == "group":
                out: dict[str, list] = {g["id"]: [] for g in q["groups"]}
                for it in q["items"]:
                    if q.get("require_all") or rng.random() < 0.85:
                        out[rng.choice(q["groups"])["id"]].append(it["value"])
                ans[qid] = out
            elif t == "hot_spot":
                if q.get("mode") == "rate":
                    ans[qid] = {r["id"]: rng.choice([1, 0, -1]) for r in q["regions"]}
                else:
                    k = rng.randint(1, min(len(q["regions"]), int(q.get("max_select") or len(q["regions"]))))
                    chosen = {r["id"] for r in rng.sample(q["regions"], k)}
                    ans[qid] = {r["id"]: int(r["id"] in chosen) for r in q["regions"]}
            elif t == "heat_map":
                ans[qid] = [[round(rng.random(), 4), round(rng.random(), 4)] for _ in range(int(q.get("max_clicks") or 1))]
            elif t == "location":
                if q.get("image"):
                    x, y = round(rng.random(), 4), round(rng.random(), 4)
                    a = {"x": x, "y": y, "source": "map"}
                    b = q.get("bounds")
                    if b:
                        a.update(lat=b["north"] - y * (b["north"] - b["south"]), lon=b["west"] + x * (b["east"] - b["west"]))
                    ans[qid] = a
                else:
                    ans[qid] = {"lat": 52.52, "lon": 13.405, "accuracy": 20, "source": "gps"}
            elif t == "drill_down":
                path, node = [], q.get("tree")
                for _ in q.get("levels") or []:
                    keys = node if isinstance(node, list) else list((node or {}).keys())
                    if not keys:
                        break
                    k = rng.choice(keys)
                    path.append(str(k))
                    node = _children(node, k)
                ans[qid] = path
            elif t == "highlight":
                words = [w for w in re.split(r"\s+", str(q.get("passage") or "")) if w]
                picked: dict[str, list] = {}
                for w in (rng.sample(words, min(len(words), rng.randint(1, 3))) if words else []):
                    picked.setdefault(rng.choice(q["categories"])["id"], []).append(w)
                ans[qid] = picked
            elif t == "signature":
                ans[qid] = PNG_1PX
            elif t == "screen_capture":
                ans[qid] = {"data": PNG_1PX, "name": f"{qid}.png", "boxes": 0}
            elif t == "file_upload":
                data = "data:text/plain;base64," + base64.b64encode(b"Test run: no real file was uploaded.\n").decode()
                ans[qid] = {"name": "test_run.txt", "size": 37, "type": "text/plain", "data": data}
            elif t == "video_response":
                data = "data:text/plain;base64," + base64.b64encode(b"Test run: no real recording.\n").decode()
                ans[qid] = {"data": data, "type": "text/plain", "duration": float(q.get("min_seconds") or 5),
                            "name": f"{qid}.txt"}
            elif t == "captcha":
                ans[qid] = 1
                ans[qid + "_attempts"] = 1
            elif t == "tree_test":
                leaves = tree_leaves(q.get("tree"))
                correct = _correct_paths(q)
                path = rng.choice(correct) if correct and rng.random() < 0.7 else rng.choice(leaves)
                visited = [" > ".join(path[:i]) for i in range(1, len(path) + 1)]
                ans[qid] = {"path": list(path), "clicks": len(visited) + rng.randint(0, 3), "visited": visited,
                            "time": round(4 + rng.random() * 12, 2)}
            elif t == "timing":
                first = round(0.5 + rng.random() * 3, 2)
                ans[qid] = {"first_click": first, "last_click": round(first + rng.random() * 8, 2),
                            "submit": round(first + 8 + rng.random() * 4, 2), "clicks": rng.randint(1, 12)}
            elif t == "meta_info":
                ans[qid] = {"browser": "virtual participant", "os": "test run", "screen": "1920x1080",
                            "viewport": "1280x720", "pixel_ratio": 1, "language": "en", "timezone": "UTC", "touch": 0,
                            "user_agent": "EDGE virtual participant"}
        ans[f"page{pi}_time"] = round(4 + rng.random() * 6 + 1.5 * len(page), 2)
    return ans


def _coerce_value(v: Any, opts: list[dict[str, Any]] | None, numeric: bool = False) -> Any:
    """Map a submitted value back to the option's own value (numbers stay numbers)."""
    for o in opts or []:
        if str(o["value"]) == str(v):
            return o["value"]
    if numeric and not (isinstance(v, str) and not v.strip()):
        n = _num(v)
        if n is not None:
            return int(n) if n.is_integer() else n
    return v


def _join(vals: list[Any]) -> str:
    return "; ".join(str(x) for x in vals)


DATA_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "application/pdf": ".pdf",
            "text/plain": ".txt", "video/webm": ".webm", "audio/webm": ".webm", "video/mp4": ".mp4", "audio/ogg": ".ogg",
            "audio/wav": ".wav", "audio/mpeg": ".mp3"}


def _decode_data_url(data: str) -> tuple[bytes, str]:
    m = re.match(r"data:([^;,]*)(;[^,]*)?,(.*)", data or "", re.S)
    if not m:
        raise SurveyError("not a data URL")
    mime, params, body = m.group(1) or "application/octet-stream", m.group(2) or "", m.group(3)
    raw = base64.b64decode(body) if ";base64" in params else body.encode()
    return raw, mime.split(";")[0]


def extract_files(flat: list[dict[str, Any]], raw: dict[str, Any], outdir: Path | None, prefix: str = "") -> dict[str, Any]:
    """Write uploaded files, signatures, recordings and screenshots to ``outdir``; the answers then hold the
    file's path (relative to the session folder) instead of the file's contents."""
    raw = dict(raw)
    for q in flat:
        qid = q.get("id")
        if q["type"] not in FILE_TYPES or qid not in raw or _empty(raw.get(qid)):
            continue
        v = raw[qid]
        meta = dict(v) if isinstance(v, dict) else {"data": v}
        data = meta.pop("data", "")
        try:
            content, mime = _decode_data_url(data)
        except (SurveyError, ValueError):
            raw[qid] = {**meta, "path": None}
            continue
        ext = Path(str(meta.get("name") or "")).suffix.lower() or DATA_EXT.get(mime, ".bin")
        if not re.fullmatch(r"\.[a-z0-9]{1,6}", ext):
            ext = ".bin"
        rel = None
        if outdir is not None:
            outdir.mkdir(parents=True, exist_ok=True)
            fname = f"{prefix}{qid}{ext}"
            n = 2
            while (outdir / fname).exists():
                fname = f"{prefix}{qid}_{n}{ext}"
                n += 1
            (outdir / fname).write_bytes(content)
            rel = f"{outdir.name}/{fname}"
        raw[qid] = {**meta, "path": rel, "bytes": len(content), "mime": mime}
    return raw


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def process(flat: list[dict[str, Any]], scores: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Turn what the page submitted into tidy data columns plus scores."""
    out: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    for q in flat:
        t = q["type"]
        if not QUESTION_TYPES.get(t, {}).get("answer"):
            continue
        shown = condition_holds(q.get("show_if"), answers) or t == "meta_info"
        qid = q.get("id")

        def get(k: str) -> Any:
            return raw.get(k) if shown else None

        opts = q.get("options") or []
        if t in ("matrix", "semantic") or (t in ("scale", "slider") and q.get("items")):
            for it in q["items"]:
                v = get(it["id"])
                if q.get("multi"):
                    vals = [] if _empty(v) else [_coerce_value(x, opts) for x in (v if isinstance(v, list) else [v])]
                    answers[it["id"]] = vals
                    out[it["id"]] = _join(vals) if shown else None
                    for o in opts:
                        out[f"{it['id']}_{slug(o['value'])}"] = (1 if any(str(x) == str(o["value"]) for x in vals) else 0) \
                            if shown else None
                else:
                    v = None if _empty(v) else _coerce_value(v, opts, numeric=True)
                    out[it["id"]] = answers[it["id"]] = v
        elif t == "side_by_side":
            for it in q["items"]:
                for c in q["columns"]:
                    key = f"{it['id']}_{c['id']}"
                    v = get(key)
                    if c["type"] == "multiple":
                        vals = [] if _empty(v) else [_coerce_value(x, c["options"]) for x in (v if isinstance(v, list) else [v])]
                        answers[key] = vals
                        out[key] = _join(vals) if shown else None
                    else:
                        v = None if _empty(v) else _coerce_value(v, c.get("options"), numeric=c["type"] == "number")
                        out[key] = answers[key] = v
        elif t == "form":
            for f in q["fields"]:
                v = get(f["id"])
                v = None if _empty(v) else (_coerce_value(v, None, numeric=True) if f["type"] == "number" else v)
                out[f["id"]] = answers[f["id"]] = v
        elif t == "multiple":
            v = get(qid)
            vals = [] if _empty(v) else (v if isinstance(v, list) else [v])
            vals = [_coerce_value(x, opts) for x in vals]
            answers[qid] = vals
            out[qid] = _join(vals) if shown else None
            for o in opts:
                out[f"{qid}_{slug(o['value'])}"] = (1 if any(str(x) == str(o["value"]) for x in vals) else 0) if shown else None
        elif t == "rank":
            v = get(qid)
            order = [_coerce_value(x, opts) for x in (v or [])] if isinstance(v, list) else []
            answers[qid] = order
            out[qid] = " > ".join(str(x) for x in order) if order else None
            for o in opts:
                out[f"{qid}_{slug(o['value'])}"] = next((i for i, x in enumerate(order, 1) if str(x) == str(o["value"])), None)
        elif t == "constant_sum":
            v = _dict(get(qid))
            answers[qid] = v
            for o in opts:
                n = _num(v.get(str(o["value"])))
                out[f"{qid}_{slug(o['value'])}"] = (int(n) if n is not None and n.is_integer() else n)
        elif t == "group":
            v = _dict(get(qid))
            answers[qid] = v
            where = {str(x): g for g, xs in v.items() for x in (xs or [])}
            for it in q["items"]:
                g = where.get(str(it["value"]))
                out[f"{qid}_{slug(it['value'])}"] = g if shown else None
                if q.get("rank_within"):
                    out[f"{qid}_{slug(it['value'])}_rank"] = ([str(x) for x in v.get(g, [])].index(str(it["value"])) + 1) \
                        if g else None
            for g in q["groups"]:
                out[f"{qid}_{g['id']}"] = _join(v.get(g["id"]) or []) if shown else None
        elif t == "hot_spot":
            v = _dict(get(qid))
            answers[qid] = [k for k, x in v.items() if x]
            for r in q["regions"]:
                out[f"{qid}_{r['id']}"] = int(v.get(r["id"]) or 0) if shown else None
            out[f"{qid}_n"] = sum(1 for x in v.values() if x) if shown else None
        elif t == "heat_map":
            pts = get(qid) if isinstance(get(qid), list) else []
            pts = [[float(p[0]), float(p[1])] for p in pts if isinstance(p, (list, tuple)) and len(p) == 2]
            answers[qid] = pts
            out[qid] = json.dumps(pts) if pts else None
            out[f"{qid}_x"] = pts[0][0] if pts else None
            out[f"{qid}_y"] = pts[0][1] if pts else None
            out[f"{qid}_clicks"] = len(pts) if shown else None
            for r in q.get("regions") or []:
                out[f"{qid}_{r['id']}"] = sum(1 for x, y in pts if r["x"] <= x * 100 <= r["x"] + r["w"]
                                              and r["y"] <= y * 100 <= r["y"] + r["h"]) if shown else None
        elif t == "location":
            v = _dict(get(qid))
            answers[qid] = v
            keys = (["x", "y"] if q.get("image") else []) + \
                (["lat", "lon"] if q.get("bounds") or q.get("allow_geolocation") else []) + \
                (["accuracy"] if q.get("allow_geolocation") else []) + ["source"]
            for k in keys:
                out[f"{qid}_{k}"] = v.get(k)
        elif t == "drill_down":
            v = get(qid) if isinstance(get(qid), list) else []
            answers[qid] = v
            out[qid] = " > ".join(str(x) for x in v) if v else None
            for i, lev in enumerate(q.get("levels") or []):
                out[f"{qid}_{slug(lev)}"] = v[i] if i < len(v) else None
        elif t == "highlight":
            v = _dict(get(qid))
            answers[qid] = v
            for c in q["categories"]:
                words = v.get(c["id"]) or []
                out[f"{qid}_{c['id']}"] = " | ".join(words) if words else None
                out[f"{qid}_{c['id']}_n"] = len(words) if shown else None
        elif t in FILE_TYPES:
            v = get(qid)
            meta = v if isinstance(v, dict) else ({"path": v} if isinstance(v, str) and not v.startswith("data:") else {})
            answers[qid] = meta.get("path")
            out[qid] = meta.get("path")
            if t == "signature":
                out[f"{qid}_signed"] = (1 if (meta.get("path") or meta.get("bytes") or (isinstance(v, str) and v)) else 0) \
                    if shown else None
            if t == "file_upload":
                out[f"{qid}_name"] = meta.get("name")
                out[f"{qid}_size"] = meta.get("size") or meta.get("bytes")
            if t == "video_response":
                out[f"{qid}_duration"] = meta.get("duration")
            if t == "screen_capture":
                out[f"{qid}_blackouts"] = meta.get("boxes")
        elif t == "captcha":
            v = get(qid)
            answers[qid] = v
            out[f"{qid}_passed"] = (1 if str(v) == "1" else 0) if shown else None
            out[f"{qid}_attempts"] = raw.get(qid + "_attempts")
        elif t == "tree_test":
            v = _dict(get(qid))
            path = tuple(str(x) for x in v.get("path") or [])
            answers[qid] = " > ".join(path)
            out[qid] = " > ".join(path) if path else None
            if q.get("correct"):
                out[f"{qid}_correct"] = (1 if path in _correct_paths(q) else 0) if path else None
            ancestors = {" > ".join(path[:i]) for i in range(1, len(path) + 1)}
            out[f"{qid}_direct"] = (1 if all(x in ancestors for x in v.get("visited") or []) else 0) if path else None
            out[f"{qid}_clicks"] = v.get("clicks")
            out[f"{qid}_time"] = v.get("time")
        elif t == "timing":
            v = _dict(get(qid))
            for k in TIMING_KEYS:
                out[f"{qid}_{k}"] = v.get(k)
        elif t == "meta_info":
            v = _dict(raw.get(qid))
            for k in META_KEYS:
                out[f"{qid}_{k}"] = v.get(k)
        else:
            v = get(qid)
            numeric = t in ("number", "slider", "graphic_slider", "scale", "nps") or \
                (t == "text" and q.get("validate") in ("number", "integer"))
            v = None if _empty(v) else _coerce_value(v, opts, numeric=numeric)
            out[qid] = answers[qid] = v
            if q.get("other_option"):
                out[qid + "_other"] = raw.get(qid + "_other") or None
            if t == "nps":
                out[qid + "_group"] = None if v is None else ("promoter" if v >= 9 else "passive" if v >= 7 else "detractor")
        if q.get("shown_order"):
            out[qid + "_order"] = " ".join(str(x) for x in q["shown_order"])
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
        if q["type"] == "slider":
            vals = [float(q.get("min", 0)), float(q.get("max", 100))]
        lo, hi = (min(vals), max(vals)) if vals else (None, None)
        for it in q.get("items") or []:
            if "id" in it:
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

    def codes_of(opts: list[dict[str, Any]] | None) -> str:
        c = "; ".join(f"{o['value']} = {o['label']}" for o in opts or [] if str(o["value"]) != o["label"])
        return f" [{c}]" if c else ""

    for q in flat:
        t = q["type"]
        if not QUESTION_TYPES.get(t, {}).get("answer"):
            continue
        qid, qt, opts = q.get("id"), txt(q.get("text") or q.get("task")), q.get("options")
        tail = codes_of(opts)
        if t in ("matrix", "semantic") or (t in ("scale", "slider") and q.get("items")):
            for it in q["items"]:
                stem = f"{it['left']} – {it['right']}" if t == "semantic" else txt(it.get("text"))
                cols[it["id"]] = f"{qt} {stem}".strip() + (" (reverse scored)" if it.get("reverse") else "") + \
                    (" (all selected, ; separated)" if q.get("multi") else "") + tail
                if q.get("multi"):
                    for o in opts:
                        cols[f"{it['id']}_{slug(o['value'])}"] = f"{qt} {stem} – {o['label']}: 1 if selected"
        elif t == "side_by_side":
            for it in q["items"]:
                for c in q["columns"]:
                    cols[f"{it['id']}_{c['id']}"] = f"{qt} – {txt(it.get('text'))} – {txt(c.get('label'))}" + \
                        codes_of(c.get("options"))
        elif t == "form":
            for f in q["fields"]:
                cols[f["id"]] = f"{qt} – {txt(f.get('label'))}".strip(" –")
        elif t in ("multiple", "rank", "constant_sum"):
            if t != "constant_sum":
                cols[qid] = qt + (" (all selected, ; separated)" if t == "multiple" else " (order, first = top)")
            for o in opts:
                what = {"multiple": "1 if selected", "rank": "rank position (1 = top)", "constant_sum": "amount given"}[t]
                cols[f"{qid}_{slug(o['value'])}"] = f"{qt} – {o['label']}: {what}"
        elif t == "group":
            for it in q["items"]:
                cols[f"{qid}_{slug(it['value'])}"] = f"{qt} – group chosen for '{it['label']}'"
                if q.get("rank_within"):
                    cols[f"{qid}_{slug(it['value'])}_rank"] = f"{qt} – rank of '{it['label']}' within its group (1 = top)"
            for g in q["groups"]:
                cols[f"{qid}_{g['id']}"] = f"{qt} – items put in '{txt(g['label'])}' (in order)"
        elif t == "hot_spot":
            for r in q["regions"]:
                cols[f"{qid}_{r['id']}"] = f"{qt} – region '{r.get('label', r['id'])}': " + (
                    "1 like, -1 dislike, 0 not rated" if q.get("mode") == "rate" else "1 if selected")
            cols[f"{qid}_n"] = f"{qt} – number of regions selected"
        elif t == "heat_map":
            cols[qid] = f"{qt} – all clicks as [[x, y], …], 0-1 from the image's top-left corner"
            cols[f"{qid}_x"], cols[f"{qid}_y"] = f"{qt} – x of the first click (0-1)", f"{qt} – y of the first click (0-1)"
            cols[f"{qid}_clicks"] = f"{qt} – number of clicks"
            for r in q.get("regions") or []:
                cols[f"{qid}_{r['id']}"] = f"{qt} – clicks inside region '{r.get('label', r['id'])}'"
        elif t == "location":
            if q.get("image"):
                cols[f"{qid}_x"], cols[f"{qid}_y"] = f"{qt} – x on the map (0-1)", f"{qt} – y on the map (0-1)"
            if q.get("bounds") or q.get("allow_geolocation"):
                cols[f"{qid}_lat"], cols[f"{qid}_lon"] = f"{qt} – latitude", f"{qt} – longitude"
            if q.get("allow_geolocation"):
                cols[f"{qid}_accuracy"] = f"{qt} – device location accuracy (m)"
            cols[f"{qid}_source"] = f"{qt} – map (clicked) or gps (device location)"
        elif t == "drill_down":
            cols[qid] = f"{qt} (full path)"
            for lev in q.get("levels") or []:
                cols[f"{qid}_{slug(lev)}"] = f"{qt} – {lev}"
        elif t == "highlight":
            for c in q["categories"]:
                cols[f"{qid}_{c['id']}"] = f"{qt} – words highlighted as '{c['label']}' (| separated)"
                cols[f"{qid}_{c['id']}_n"] = f"{qt} – number of words highlighted as '{c['label']}'"
        elif t in FILE_TYPES:
            cols[qid] = f"{qt} – saved file (path in the session folder)"
            extra = {"signature": [("signed", "1 if signed")],
                     "file_upload": [("name", "original file name"), ("size", "size (bytes)")],
                     "video_response": [("duration", "length of the recording (s)")],
                     "screen_capture": [("blackouts", "number of blacked-out areas")]}[t]
            for k, d in extra:
                cols[f"{qid}_{k}"] = f"{qt} – {d}"
        elif t == "captcha":
            cols[f"{qid}_passed"] = "1 if the typed code was correct"
            cols[f"{qid}_attempts"] = "number of attempts at the code"
        elif t == "tree_test":
            cols[qid] = f"Tree test '{qid}': path chosen"
            if q.get("correct"):
                cols[f"{qid}_correct"] = f"Tree test '{qid}': 1 if a correct destination was chosen"
            cols[f"{qid}_direct"] = f"Tree test '{qid}': 1 if no wrong branch was opened first (directness)"
            cols[f"{qid}_clicks"] = f"Tree test '{qid}': number of clicks in the tree"
            cols[f"{qid}_time"] = f"Tree test '{qid}': seconds until the answer was chosen"
        elif t == "timing":
            for k, d in (("first_click", "first click"), ("last_click", "last click"), ("submit", "pressing Next / Submit")):
                cols[f"{qid}_{k}"] = f"Timing '{qid}': seconds from showing the page to the {d}"
            cols[f"{qid}_clicks"] = f"Timing '{qid}': number of clicks on the page"
        elif t == "meta_info":
            for k in META_KEYS:
                cols[f"{qid}_{k}"] = f"Meta info: {k.replace('_', ' ')}"
        else:
            cols[qid] = qt + tail
            if q.get("other_option"):
                cols[qid + "_other"] = f"{qt} – text typed for '{q['other_option']}'"
            if t == "nps":
                cols[qid + "_group"] = f"{qt} – promoter (9-10), passive (7-8) or detractor (0-6)"
        if q.get("randomize"):
            cols[qid + "_order"] = f"Order in which the options/items of '{qid}' were shown"
    for name, sc in {**lib_scores, **(scores or {})}.items():
        cols[name] = (sc or {}).get("description") or f"Score '{name}'"
        if (sc or {}).get("bands"):
            cols[name + "_band"] = f"Interpretive band of {name}: " + ", ".join(f"≤{m} {lab}" for m, lab in sc["bands"])
    for i, _p in enumerate(pages(flat), 1):
        cols[f"page{i}_time"] = f"Time spent on page {i} (s)"
    return cols


# =========================================================================================== page
ASSETS = Path(__file__).parent / "survey_page"


def page_direction(spec: dict[str, Any], flat: list[dict[str, Any]]) -> str:
    """ltr or rtl: explicit ``direction``, else the language, else the first strong letters of the text."""
    from .bidi import first_strong_rtl, is_rtl_language
    d = str(spec.get("direction") or "auto").lower()
    if d in ("ltr", "rtl"):
        return d
    if spec.get("language"):
        return "rtl" if is_rtl_language(spec["language"]) else "ltr"
    sample = " ".join([re.sub(r"<[^>]+>", " ", str(spec.get("title") or ""))] +
                      [re.sub(r"<[^>]+>", " ", str(q.get("text") or q.get("task") or "")) for q in flat[:3]])
    return "rtl" if first_strong_rtl(sample) else "ltr"


def render_html(spec: dict[str, Any], rng: random.Random | None = None, asset_prefix: str = "") \
        -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """The participant-facing page. Returns (html, flat questions as shown, scores)."""
    from .survey_i18n import messages
    flat, lib_scores = expand(spec.get("questions") or [], rng)
    scores = {**lib_scores, **(spec.get("scores") or {})}
    direction = page_direction(spec, flat)
    language = spec.get("language")
    if not language and direction == "rtl":      # Hebrew / Arabic text without a language: messages to match
        from .bidi import guess_language
        language = guess_language(" ".join([str(spec.get("title") or "")] + [str(q.get("text") or "") for q in flat[:5]]))
    text = messages(language)
    text.update(spec.get("labels") or {})
    for k in ("next", "back", "submit"):
        if spec.get(f"{k}_label"):
            text[k] = spec[f"{k}_label"]
    data = {"title": spec.get("title") or "", "intro": spec.get("intro") or "", "pages": pages(flat), "flat": flat,
            "progress": spec.get("progress_bar", True), "back": spec.get("allow_back", True), "text": text,
            "dir": direction, "asset": asset_prefix}
    blob = json.dumps(data, default=str, ensure_ascii=False).replace("<", "\\u003c")     # no '<' can end or confuse the script block
    css = (ASSETS / "survey.css").read_text(encoding="utf-8")
    js = (ASSETS / "survey.js").read_text(encoding="utf-8")
    title = htmllib.escape(re.sub(r"<[^>]+>", "", str(spec.get("title") or "Survey")))
    lang = f" lang='{htmllib.escape(str(language))}'" if language else ""
    page = (f"<!doctype html><html{lang} dir='{direction}'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{css}{spec.get('css') or ''}</style></head>"
            "<body><div class='wrap'><div id='survey'></div></div>"
            f"<script type='application/json' id='edge-survey'>{blob}</script>"
            f"<script>window.addEventListener('load',function(){{{js}}});</script></body></html>")
    return page, flat, scores
