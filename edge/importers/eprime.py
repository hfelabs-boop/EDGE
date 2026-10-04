"""E-Prime 2/3 importer (best effort).

E-Prime's ``.es3``/``.es2`` files are a proprietary binary format. E-Studio, however,
*generates* a plain-text E-Basic script (``.ebs3``/``.ebs2``, written next to the
experiment whenever you press Generate or Run). This importer reads that script:

* display objects (TextDisplay, ImageDisplay, Slide with SlideText/SlideImage sub-objects,
  SoundOut, Wait, FeedbackDisplay) become one routine each, with Duration, Text,
  colours, positions and input masks (allowed keys, correct answer, time limit, end action);
* Procedures become sequences in the flow; Lists become loops (order, cycles/samples) whose
  rows come from the script, from an external list file, or from List exports
  (``<ListName>.txt``, tab-delimited, as saved from E-Studio) placed next to the script;
* ``[Attribute]`` references become ``$attribute`` expressions;
* InLine E-Basic code is preserved in the report (it cannot be run) and flagged.

The generated E-Basic varies across E-Prime versions, so treat the result as a strong
starting point and review the import report.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .base import Ids, ImportResult, ident, key_name, ms, num

DISPLAY_TYPES = {"TextDisplay", "ImageDisplay", "Slide", "SoundOut", "Wait", "FeedbackDisplay", "MovieDisplay"}
ORDERS = {"SequentialOrder": "sequential", "RandomOrder": "random", "RandomReplaceOrder": "random",
          "PermutedOrder": "random", "CounterbalanceOrder": "counterbalance", "OffsetOrder": "latin_square"}

RE_NEW = re.compile(r"^\s*Set\s+(\w+)\s*=\s*New\s+(\w+)", re.M)
RE_SUB = re.compile(r"^\s*Sub\s+(\w+)_Run\s*\(.*?\)\s*$(.*?)^\s*End Sub", re.M | re.S)
RE_ASSIGN = re.compile(r"^\s*(?:Set\s+)?(\w+)\.(\w+)\s*=\s*(.+?)\s*$", re.M)
RE_ATTRIB = re.compile(r'^\s*(\w+)\.AddAttrib\s+"([^"]+)"', re.M)
RE_SETATTRIB = re.compile(r'^\s*(\w+)\.SetAttrib\s+(\d+)\s*,\s*"([^"]+)"\s*,\s*"([^"]*)"', re.M)
RE_SUBOBJ = re.compile(r'^\s*Set\s+(\w+)\s*=\s*CSlide(Text|Image)\((\w+)_State\.Objects\("([^"]+)"\)\)', re.M)
RE_INPUT = re.compile(r'(\w+)\.InputMasks\.Add\s+(\w+)\.CreateInputMask\((.*)\)\s*$', re.M)
RE_INLINE = re.compile(r"'InLine\s*:?\s*(\w+)(.*?)(?='-{5,}|'InLine|^\s*End Sub)", re.S | re.M)


def _split_args(s: str) -> list[str]:
    out, cur, depth, q = [], "", 0, False
    for ch in s:
        if ch == '"':
            q = not q
        if not q and ch == "(":
            depth += 1
        if not q and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not q:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _expr(v: str) -> Any:
    """Translate an E-Basic value expression into an EDGE literal or $expression."""
    v = v.strip()
    m = re.fullmatch(r'(?:C\w+\()?\s*c\.GetAttrib\("([^"]+)"\)\s*\)?', v)
    if m:
        return "$" + _aname(m.group(1))
    m = re.fullmatch(r'CColor\("([^"]+)"\)', v)
    if m:
        return _color(m.group(1))
    m = re.fullmatch(r'C\w+\("([^"]*)"\)', v)  # CLng("1000"), CLogical("Yes") ...
    if m:
        v = f'"{m.group(1)}"'
    if v.startswith('"') and v.endswith('"'):
        text = v[1:-1].replace('""', '"').replace("\\n", "\n")
        return _attr_text(text)
    n = num(v)
    return n


BUILTIN_ATTRS = {"Subject": "participant", "Session": "session", "Group": "group"}


def _aname(a: str) -> str:
    return BUILTIN_ATTRS.get(a, ident(a))


def _attr_text(text: str) -> Any:
    refs = re.findall(r"\[(\w+)\]", text)
    if not refs:
        return text
    if re.fullmatch(r"\[(\w+)\]", text):
        return "$" + _aname(refs[0])
    body = re.sub(r"\[(\w+)\]", lambda m: "{" + _aname(m.group(1)) + "}", text.replace("{", "{{").replace("}", "}}"))
    return "$f" + repr(body)


def _color(c: Any) -> Any:
    if isinstance(c, str) and c.startswith("$"):
        return c
    s = str(c).strip().strip('"')
    if re.fullmatch(r"\d+\s*,\s*\d+\s*,\s*\d+(\s*,\s*\d+)?", s):
        parts = [int(x) for x in s.split(",")][:3]
        return "#%02x%02x%02x" % tuple(parts)
    return s.lower()


def _keys(allow: Any) -> Any:
    if isinstance(allow, str) and allow.startswith("$"):
        return allow
    s = str(allow or "")
    if not s or s.upper() == "{ANY}":
        return None
    keys, i = [], 0
    while i < len(s):
        if s[i] == "{":
            j = s.index("}", i)
            keys.append(key_name(s[i + 1:j]))
            i = j + 1
        else:
            keys.append(key_name(s[i]))
            i += 1
    return keys


def _pos(v: Any, axis_size: int) -> Any:
    """E-Prime X/Y: 'center', '50%', or pixels from the left/top. Returns px from centre (y up)."""
    if isinstance(v, (int, float)):
        return v - axis_size / 2
    s = str(v).strip().lower()
    if s in ("center", "middle"):
        return 0
    if s.endswith("%"):
        return (float(s[:-1]) / 100 - 0.5) * axis_size
    return 0


def read_list_file(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """E-Prime list export: tab-delimited, columns Weight, Nested, Procedure, attributes..."""
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    out, procs = [], []
    for r in rows:
        weight = int(num(r.get("Weight", 1)) or 1) if str(r.get("Weight", "1")).strip() else 1
        procs.append(r.get("Procedure"))
        clean = {ident(k): num(v) for k, v in r.items() if k and k not in ("Weight", "Nested", "Procedure", "ID")}
        out += [dict(clean) for _ in range(max(weight, 1))]
    proc = max(set(procs), key=procs.count) if procs else None
    return out, proc


def import_eprime(path: Path) -> ImportResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    res = ImportResult({}, path, "E-Prime (generated E-Basic script)")
    res.note("info", "source", "converted from the generated E-Basic script; review the result against E-Studio")
    objects: dict[str, str] = {m.group(1): m.group(2) for m in RE_NEW.finditer(text)}
    props: dict[str, dict[str, Any]] = {}
    for m in RE_ASSIGN.finditer(text):
        obj, prop, val = m.group(1), m.group(2), m.group(3)
        if obj == "c" or prop in ("Name", "Tag"):
            continue
        props.setdefault(obj, {})[prop] = val
    run_subs = {m.group(1): m.group(2) for m in RE_SUB.finditer(text)}

    # --- slides: sub-objects
    slide_parts: dict[str, list[tuple[str, str, str]]] = {}
    for m in RE_SUBOBJ.finditer(text):
        var, kind, slide, objname = m.groups()
        slide_parts.setdefault(slide, []).append((var, kind, objname))

    # --- input masks (per object, last one wins)
    inputs: dict[str, dict[str, Any]] = {}
    for m in RE_INPUT.finditer(text):
        obj, dev, args = m.group(1), m.group(2), _split_args(m.group(3))
        allow = _expr(args[0]) if args else ""
        correct = _expr(args[1]) if len(args) > 1 else ""
        limit = args[2] if len(args) > 2 else ""
        end_action = args[4] if len(args) > 4 else ""
        inputs[obj] = {"device": dev, "keys": _keys(allow), "correct": correct if correct not in ("", None) else None,
                       "limit": limit, "terminate": "Terminate" in end_action}

    W, H = 1024, 768
    ids = Ids()
    routines: dict[str, Any] = {}
    rmap: dict[str, str] = {}

    def duration_of(obj: str) -> Any:
        d = _expr(props.get(obj, {}).get("Duration", "-1"))
        if isinstance(d, (int, float)):
            return None if d < 0 else ms(d)
        return d if not isinstance(d, str) or d.startswith("$") else None

    def make_routine(obj: str) -> str | None:
        kind = objects.get(obj)
        if kind not in DISPLAY_TYPES:
            return None
        if obj in rmap:
            return rmap[obj]
        rid = ids.make(obj, "routine")
        rmap[obj] = rid
        p = props.get(obj, {})
        comps: list[dict[str, Any]] = []
        dur = duration_of(obj)
        if kind == "TextDisplay":
            c: dict[str, Any] = {"id": "text", "type": "text", "text": _expr(p.get("Text", '""'))}
            if "ForeColor" in p:
                c["color"] = _color(_expr(p["ForeColor"]))
            if "FontSize" in p:
                fs = _expr(p["FontSize"])
                c["height"] = fs * 1.33 if isinstance(fs, (int, float)) else fs
            comps.append(c)
        elif kind == "ImageDisplay":
            img = _expr(p.get("Filename", '""'))
            comps.append({"id": "image", "type": "image", "image": img})
            if isinstance(img, str) and img and not img.startswith("$"):
                res.assets.add(img)
        elif kind == "Slide":
            for var, sub_kind, objname in slide_parts.get(obj, []):
                sp = props.get(var, {})
                cid = ident(objname)
                x = _pos(_expr(sp.get("X", '"center"')), W)
                y = -_pos(_expr(sp.get("Y", '"center"')), H)
                if sub_kind == "Text":
                    c = {"id": cid, "type": "text", "text": _expr(sp.get("Text", '""')), "pos": [x, y]}
                    if "ForeColor" in sp:
                        c["color"] = _color(_expr(sp["ForeColor"]))
                else:
                    c = {"id": cid, "type": "image", "image": _expr(sp.get("Filename", '""')), "pos": [x, y]}
                    if isinstance(c["image"], str) and c["image"] and not c["image"].startswith("$"):
                        res.assets.add(c["image"])
                comps.append(c)
            if not slide_parts.get(obj):
                res.note("approx", f"routines.{rid}", "slide sub-objects were not found in the script; add them manually")
        elif kind == "SoundOut":
            f = _expr(p.get("Filename", '""'))
            comps.append({"id": "sound", "type": "sound", "sound": f})
            if isinstance(f, str) and f and not f.startswith("$"):
                res.assets.add(f)
        elif kind == "FeedbackDisplay":
            comps.append({"id": "feedback", "type": "text",
                          "text": "$'Correct' if prev_corr else ('Too slow' if prev_corr is None else 'Incorrect')"})
            res.note("approx", f"routines.{rid}", "FeedbackDisplay converted to a text that reads the variable "
                     "'prev_corr', set by the response before it; check the feedback states")
        elif kind == "MovieDisplay":
            res.note("unsupported", f"routines.{rid}", "MovieDisplay: movies are not supported yet")
        if "BackColor" in p:
            res.note("info", f"routines.{rid}", f"BackColor {p['BackColor']} ignored (EDGE uses the window background)")
        inp = inputs.get(obj)
        routine: dict[str, Any] = {"components": comps}
        if inp:
            k: dict[str, Any] = {"id": "resp", "type": "keyboard"}
            if inp["keys"]:
                k["keys"] = inp["keys"]
            if inp["correct"] is not None:
                k["correct"] = inp["correct"]
            if inp["terminate"]:
                k["end_routine"] = True
            limit = inp["limit"]
            if limit and "Duration" not in limit and not limit.startswith("-"):
                lv = _expr(limit)
                if isinstance(lv, (int, float)) and lv > 0:
                    k["duration"] = ms(lv)
            comps.append(k)
            comps.append({"id": "remember", "type": "variable", "when": "end", "set": {"prev_corr": "$resp.corr"}})
            if dur is not None:
                if inp["terminate"]:
                    k.setdefault("duration", dur)
                else:
                    routine["duration"] = dur
            if inp["device"].lower().startswith("mouse"):
                k["type"] = "mouse"
                k.pop("keys", None)
                res.note("approx", f"routines.{rid}", "mouse input mask converted to a mouse component")
        elif dur is not None:
            routine["duration"] = dur
        elif kind == "Wait":
            routine["duration"] = duration_of(obj) or 0
        else:
            routine["duration"] = 1.0
            res.note("approx", f"routines.{rid}", f"{kind} '{obj}' has no fixed duration or input; set to 1 s")
        if kind == "Wait":
            comps.append({"id": "wait", "type": "wait"})
        if "PreRelease" in p and str(p["PreRelease"]).strip() not in ("0", '"0"'):
            res.note("info", f"routines.{rid}", "PreRelease is not needed in EDGE (stimuli are prepared before each routine)")
        routines[rid] = routine
        res.count("routines")
        return rid

    # --- lists
    lists: dict[str, dict[str, Any]] = {}
    for name, kind in objects.items():
        if kind != "List":
            continue
        p = props.get(name, {})
        order_m = re.search(rf"Set\s+{name}\.Order\s*=\s*New\s+(\w+)", text)
        cyc = re.search(rf"Set\s+{name}\.TerminateCondition\s*=\s*Cycles\((\d+)\)", text)
        samples = re.search(rf"Set\s+{name}\.TerminateCondition\s*=\s*Samples\((\d+)\)", text)
        rows: list[dict[str, Any]] = []
        proc = None
        attribs = [a for (lst, a) in RE_ATTRIB.findall(text) if lst == name]
        set_rows: dict[int, dict[str, Any]] = {}
        for lst, i, attr, val in RE_SETATTRIB.findall(text):
            if lst == name:
                set_rows.setdefault(int(i), {})[attr] = val
        if set_rows:
            for i in sorted(set_rows):
                r = set_rows[i]
                weight = int(num(r.pop("Weight", 1)) or 1)
                proc = r.pop("Procedure", proc)
                rows += [{ident(k): num(v) for k, v in r.items()} for _ in range(max(weight, 1))]
        else:
            fname = _expr(p.get("Filename", '""'))
            candidates = [path.parent / f"{name}.txt"] + ([path.parent / fname] if isinstance(fname, str) and fname else [])
            for cand in candidates:
                if cand.is_file():
                    rows, proc = read_list_file(cand)
                    res.note("info", f"lists.{name}", f"rows read from {cand.name}")
                    break
        if not rows:
            rows = [{ident(a): "" for a in attribs}] if attribs else []
            res.note("unsupported", f"lists.{name}", "list rows not found: in E-Studio export the list "
                     f"(right-click → Save to file) as '{name}.txt' next to the script and import again")
        lists[name] = {"rows": rows, "order": ORDERS.get(order_m.group(1), "random") if order_m else "sequential",
                       "cycles": int(cyc.group(1)) if cyc else 1, "samples": int(samples.group(1)) if samples else None,
                       "procedure": proc}
        if order_m and order_m.group(1) not in ORDERS:
            res.note("approx", f"lists.{name}", f"order {order_m.group(1)} converted to random")

    # --- procedures -> flow
    def proc_nodes(proc: str, depth: int = 0) -> list[Any]:
        body = run_subs.get(proc, "")
        nodes: list[Any] = []
        for m in re.finditer(r"^\s*(\w+)\.Run\b", body, re.M):
            obj = m.group(1)
            kind = objects.get(obj)
            if kind == "List":
                nodes.append(list_node(obj, depth))
            elif kind == "Procedure":
                nodes += proc_nodes(obj, depth + 1)
            elif kind in DISPLAY_TYPES:
                rid = make_routine(obj)
                if rid:
                    nodes.append(rid)
            elif kind:
                res.note("unsupported", f"procedures.{proc}", f"{kind} '{obj}' was not converted")
        for m in RE_INLINE.finditer(body):
            code = m.group(2).strip()
            if code:
                res.note("unsupported", f"procedures.{proc}.{m.group(1)}",
                         "InLine E-Basic code was not converted:\n\n```vb\n" + code[:1500] + "\n```")
        return nodes

    def list_node(name: str, depth: int) -> dict[str, Any]:
        L = lists.get(name, {"rows": [], "order": "sequential", "cycles": 1, "procedure": None})
        rows = L["rows"]
        proc = L.get("procedure")
        if not proc:
            m = re.search(rf"{name}\.Procedure\s*=\s*\"(\w+)\"", text)
            proc = m.group(1) if m else None
        if not proc:  # fall back: a procedure whose Run sub isn't referenced elsewhere
            proc = next((p for p, k in objects.items() if k == "Procedure" and p != "SessionProc"
                         and not re.search(rf"\b{p}\.Run", text)), None)
        lid = ids.make(name, "loop")
        node: dict[str, Any] = {"loop": lid, "conditions": rows or None, "order": L["order"]}
        if L["cycles"] and L["cycles"] != 1:
            node["repeats"] = L["cycles"]
        if L.get("samples"):
            node["select"] = f"0:{L['samples']}"
            res.note("approx", f"flow.{lid}", "Samples() termination converted to a row selection")
        node["children"] = proc_nodes(proc, depth + 1) if proc and depth < 8 else []
        res.count("loops")
        return node

    top = "SessionProc" if "SessionProc" in run_subs else next(
        (p for p, k in objects.items() if k == "Procedure" and p in run_subs), None)
    flow = proc_nodes(top) if top else []
    if not flow:
        res.note("unsupported", "flow", "no runnable procedure found in the script")

    res.doc = {"name": ident(path.stem), "description": f"Imported from E-Prime ({path.name})",
               "settings": {"window": {"size": [W, H], "background": "#000000", "units": "px"}},
               "devices": [], "variables": {"prev_corr": None}, "routines": routines, "flow": flow}
    return res


def looks_like_eprime(path: Path) -> bool:
    return path.suffix.lower() in (".ebs", ".ebs2", ".ebs3")
