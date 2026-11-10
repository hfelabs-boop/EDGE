"""Inquisit importer (Millisecond Software; ``.iqx`` scripts, older ``.exp`` scripts).

Reads the element syntax of an Inquisit script:

* ``<defaults>`` (screen and text colour, font size) -> window settings;
* ``<values>`` -> experiment variables; simple ``ontrialbegin``/``ontrialend`` assignments such as
  ``[values.n = values.n + 1]`` -> variable items, everything else is listed in the report;
* stimulus elements ``<text>``, ``<picture>``, ``<sound>``, ``<shape>``, ``<port>`` with their ``<item>`` sets
  -> text, image, sound, shape and marker items;
* ``<trial>`` (stimulustimes/stimulusframes, validresponse, correctresponse, timeout, trialduration,
  pre/posttrialpause, correctmessage/errormessage, simple branch) -> screens;
* ``<block>`` trials lists (``[1 = a; 2-13 = noreplace(b, c)]``, ``sequence``, ``replace``) -> trial lists. Trials
  that differ only in their stimuli and correct key (the usual Stroop/flanker layout) become ONE screen whose
  differences are columns of the trial list;
* ``<expt>`` blocks, ``<page>``/``<instruct>`` instruction pages, ``<survey>``/``<surveypage>`` with textbox,
  radiobuttons, dropdown, checkboxes and slider questions -> the flow, text screens and a survey;
* ``<list>``/``<counter>`` and other elements are listed in the report.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import (
    Ids,
    ImportResult,
    avoid_column_clashes,
    ident,
    key_name,
    ms,
    num,
    portable_path,
    read_text,
)

W, H = 1024, 768
STIMULI = ("text", "picture", "sound", "shape", "port", "video")
COLORS = {"white", "black", "red", "green", "blue", "yellow", "gray", "grey", "orange", "purple", "cyan",
          "magenta", "pink", "brown", "lightgray", "darkgray", "lightgrey", "darkgrey", "navy", "lime", "maroon"}
SCANCODES = {1: "escape", 28: "return", 57: "space", 203: "left", 205: "right", 200: "up", 208: "down", 14: "backspace"}
for _i, _c in enumerate("1234567890"):
    SCANCODES[2 + _i] = _c
for _row, _start in (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for _i, _c in enumerate(_row):
        SCANCODES[_start + _i] = _c

RE_ELEMENT = re.compile(r"<\s*(\w+)(?:[ \t]+([\w.\-]+))?\s*>(.*?)<\s*/\s*\1\s*>", re.S | re.I)
RE_OPEN = re.compile(r"<\s*(\w+)(?:[ \t]+([\w.\-]+))?\s*>")


# ------------------------------------------------------------------ parsing
def parse_script(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    """Every element as {kind, name, attrs {attr: value}, body, line}; plus elements opened but never closed."""
    elements: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for m in RE_ELEMENT.finditer(text):
        kind, name, body = m.group(1).lower(), m.group(2) or "", m.group(3)
        attrs: dict[str, str] = {}
        cur = None
        for raw in body.split("\n"):
            am = re.match(r"\s*/\s*([\w.]+)\s*(?:=\s*)?(.*)$", raw)
            if am and kind != "page":
                cur = am.group(1).lower()
                attrs[cur] = am.group(2).strip()
            elif cur and raw.strip():
                attrs[cur] += " " + raw.strip()
        elements.append({"kind": kind, "name": name, "attrs": attrs, "body": body,
                         "line": text.count("\n", 0, m.start()) + 1})
        spans.append((m.start(), m.end()))
    unclosed = []
    for m in RE_OPEN.finditer(text):
        if not any(a <= m.start() < b for a, b in spans) and m.group(1).lower() in KNOWN:
            unclosed.append((text.count("\n", 0, m.start()) + 1, f"<{m.group(1)}{' ' + m.group(2) if m.group(2) else ''}>"))
    return elements, unclosed


KNOWN = {"defaults", "values", "expressions", "data", "summarydata", "item", "text", "picture", "sound", "video", "shape",
         "port", "trial", "block", "expt", "list", "counter", "instruct", "page", "survey", "surveypage", "textbox",
         "radiobuttons", "dropdown", "checkboxes", "slider", "likert", "openended", "caption", "include",
         "monkey", "parameters", "html", "listbox", "script", "batch"}


def split_top(s: str, sep: str) -> list[str]:
    """Split on ``sep`` outside quotes and brackets."""
    out, cur, depth, q = [], "", 0, False
    for ch in s:
        if ch == '"':
            q = not q
        elif not q and ch in "([":
            depth += 1
        elif not q and ch in ")]":
            depth -= 1
        if ch == sep and depth == 0 and not q:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def plist(v: str) -> list[str]:
    """'("a", b, 3)' -> ['a', 'b', '3'] (quotes removed)."""
    v = v.strip()
    if v.startswith("(") and v.endswith(")"):
        v = v[1:-1]
    return [unquote(x) for x in split_top(v, ",")]


def is_quoted_list(v: str) -> bool:
    return v.strip().startswith("(")


def schedule(v: str) -> list[tuple[float, list[str]]]:
    """'[0 = fixation; 500 = word, reminder]' -> [(0, ['fixation']), (500, ['word', 'reminder'])]."""
    v = v.strip().strip("[]")
    out = []
    for part in split_top(v, ";"):
        t, _, names = part.partition("=")
        n = num(t.strip())
        if isinstance(n, (int, float)):
            out.append((n, [x.strip() for x in split_top(names, ",") if x.strip()]))
    return out


def trial_segments(v: str) -> list[dict[str, Any]] | None:
    """'[1 = a; 2-13 = noreplace(b, c)]' -> [{count, mode, names}]; None when it can't be read."""
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    out = []
    for part in split_top(v[1:-1], ";"):
        pos, _, sel = part.partition("=")
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", pos)
        if not m or not sel.strip():
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        sm = re.fullmatch(r"\s*(noreplace|replace|sequence|noreplacenorepeat|noreplacecorrect|noreplaceerror)\s*\((.*)\)\s*",
                          sel, re.S | re.I)
        if sm:
            mode, names = sm.group(1).lower(), [x.strip() for x in split_top(sm.group(2), ",")]
        else:
            mode, names = "sequence", [x.strip() for x in split_top(sel, ",")]
        if not all(re.fullmatch(r"[\w.]+", n) for n in names):
            return None
        out.append({"count": b - a + 1, "mode": mode, "names": names})
    return out


def color(v: str) -> str | None:
    v = v.strip().strip('"').lower()
    m = re.fullmatch(r"\(?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)?", v)
    if m:
        return "#%02x%02x%02x" % tuple(min(255, int(x)) for x in m.groups())
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    if v in COLORS:
        return {"lightgrey": "lightgray", "darkgrey": "darkgray", "grey": "gray"}.get(v, v)
    return None


def pct(v: str, axis: int) -> float | None:
    v = v.strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(%|px|pt|mm)?", v)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or "px"
    if unit == "%":
        return n / 100 * axis
    if unit == "pt":
        return n * 4 / 3
    if unit == "mm":
        return n * 3.78
    return n


def keys_of(v: str) -> list[str] | None:
    """validresponse/correctresponse values -> EDGE key names; None for '(0)' (no response)."""
    keys = []
    for k in plist(v):
        n = num(k)
        if isinstance(n, int):
            if n == 0:
                return None
            keys.append(SCANCODES.get(n, str(n)))
        else:
            keys.append(key_name(k) if k.strip() else "space")
    return keys


# ------------------------------------------------------------------ expressions
def expression(e: str, trial: str | None, values: set[str]) -> str | None:
    """An Inquisit expression in EDGE's Python form, or None when it uses something that has no counterpart."""
    s = e.strip()
    if trial:
        s = re.sub(rf"\btrial\.{re.escape(trial)}\.correct\b", "resp.corr", s)
        s = re.sub(rf"\btrial\.{re.escape(trial)}\.error\b", "(1 - resp.corr)", s)
        s = re.sub(rf"\btrial\.{re.escape(trial)}\.latency\b", "(resp.rt * 1000)", s)
    s = re.sub(r"\bvalues\.(\w+)", r"\1", s)
    s = s.replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?!=)", " not ", s)
    s = re.sub(r"\btrue\b", "True", s)
    s = re.sub(r"\bfalse\b", "False", s)
    if re.search(r"\b(?:trial|block|expt|list|counter|script|computer|parameters|text|picture|"
                 r"sound|item|display|monkey|survey|surveypage|data)\.\w", s):
        return None
    if re.search(r"[^\w\s.+\-*/%()<>=!\"',]", s):
        return None
    names = set(re.findall(r"(?<![\w.\"'])([A-Za-z_]\w*)\b", s)) - {"and", "or", "not", "True", "False", "resp",
                                                                    "corr", "rt", "if", "else", "round", "abs"}
    if names - values:
        return None
    return s


def statements(v: str, trial: str | None, values: set[str]) -> tuple[dict[str, str], list[str]]:
    """'[values.n += 1; if (x) values.y = 2]' -> ({n: '$n + 1', ...}, [statements that were not converted])."""
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    done: dict[str, str] = {}
    left: list[str] = []
    for st in split_top(v, ";"):
        cond = None
        m = re.fullmatch(r"if\s*\((.*)\)\s*(.+)", st, re.S)
        if m and " else " not in m.group(2):
            cond, st2 = expression(m.group(1), trial, values), m.group(2)
            if cond is None:
                left.append(st)
                continue
        else:
            st2 = st
        a = re.fullmatch(r"values\.(\w+)\s*([+\-*/]?=)\s*(.+)", st2.strip(), re.S)
        rhs = expression(a.group(3), trial, values | ({a.group(1)} if a else set())) if a else None
        if not a or rhs is None or a.group(1) in done:
            left.append(st)
            continue
        var = a.group(1)
        if a.group(2) != "=":
            rhs = f"{var} {a.group(2)[0]} ({rhs})"
        if cond:
            rhs = f"({rhs}) if ({cond}) else {var}"
        done[var] = "$" + rhs
    return done, left


# ------------------------------------------------------------------ converter
class Converter:
    def __init__(self, path: Path, text: str):
        self.path = path
        self.res = ImportResult({}, path, "Inquisit")
        self.ids = Ids()
        self.elements, unclosed = parse_script(text)
        for line, tag in unclosed:
            self.res.note("unsupported", f"line {line}", f"{tag} is not closed: the file may be cut short, so this "
                          "element and everything after it may be missing")
        self.by: dict[str, dict[str, dict[str, Any]]] = {}
        for el in self.elements:
            self.by.setdefault(el["kind"], {})[el["name"].lower()] = el
        self.routines: dict[str, Any] = {}
        self.made: dict[tuple[str, str], list[Any]] = {}      # (kind, name) -> flow nodes already made
        self.defaults = self.one("defaults")
        self.instruct = self.one("instruct")
        self.values: dict[str, Any] = {}
        for k, v in self.one("values").items():
            self.values[k] = num(unquote(v))
        self.unconverted: dict[str, list[str]] = {}            # expression -> where it was
        fs = plist(self.defaults.get("fontstyle", '("Arial", 5%)'))
        self.font_h = pct(fs[1], H) if len(fs) > 1 and pct(fs[1], H) else H * 0.05
        self.font_bold = len(fs) > 2 and fs[2].lower() == "true"
        self.txcolor = color(self.defaults.get("txcolor", "white")) or "white"

    def one(self, kind: str) -> dict[str, str]:
        els = [e for e in self.elements if e["kind"] == kind and not e["name"]]
        out: dict[str, str] = {}
        for e in els:
            out.update(e["attrs"])
        return out

    def el(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.by.get(kind, {}).get(name.lower())

    def find(self, name: str, kinds: tuple[str, ...]) -> tuple[str, dict[str, Any]] | None:
        for k in kinds:
            e = self.el(k, name)
            if e:
                return k, e
        return None

    def keep_out(self, where: str, what: str) -> None:
        self.unconverted.setdefault(what, []).append(where)

    # ------------------------------------------------------------------ stimuli
    def items_of(self, el: dict[str, Any], where: str) -> list[str]:
        v = el["attrs"].get("items", "")
        if is_quoted_list(v):
            return plist(v)
        item = self.el("item", v.strip())
        if item:
            return [unquote(item["attrs"][k]) for k in sorted((k for k in item["attrs"] if k.isdigit()), key=int)]
        if v:
            self.res.note("approx", where, f"items '{v}' could not be read; fill in the stimulus by hand")
        return []

    def stimulus(self, name: str, where: str) -> dict[str, Any] | None:
        """A stimulus element as an EDGE item (without id)."""
        found = self.find(name, STIMULI)
        if not found:
            other = next((k for k, d in self.by.items() if name.lower() in d), None)
            self.res.note("unsupported", where, f"'{name}' is not a stimulus EDGE can show"
                          + (f" (it is a <{other}>)" if other else " (no element of that name)"))
            return None
        kind, el = found
        a = el["attrs"]
        w = f"{where}.{name}"
        items = self.items_of(el, w) if kind != "shape" else []
        if len(items) > 1:
            sel = a.get("select", "noreplace")
            value: Any = "$random.choice(" + repr(items) + ")"
            self.res.note("approx", w, f"<{kind} {name}> has {len(items)} items, selected by '{sel}': converted to a "
                          "random choice on each trial. For a balanced selection, put the items in a trial list column")
        else:
            value = items[0] if items else ""
        c: dict[str, Any]
        if kind == "text":
            text = value.replace("^", "\n") if isinstance(value, str) and not value.startswith("$") else value
            c = {"type": "text", "text": text, "color": self.txcolor, "height": round(self.font_h, 1)}
            if "txcolor" in a:
                col = color(a["txcolor"])
                if col:
                    c["color"] = col
                else:
                    self.res.note("approx", w, f"text colour '{a['txcolor']}' could not be converted")
            if "fontstyle" in a:
                fs = plist(a["fontstyle"])
                h = pct(fs[1], H) if len(fs) > 1 else None
                if h:
                    c["height"] = round(h, 1)
                if len(fs) > 2 and fs[2].lower() == "true":
                    c["bold"] = True
            elif self.font_bold:
                c["bold"] = True
        elif kind == "picture":
            img = portable_path(value)
            c = {"type": "image", "image": img}
            if isinstance(img, str) and img and not img.startswith("$"):
                self.res.assets.add(img)
            if "size" in a:
                sz = plist(a["size"])
                if len(sz) == 2 and pct(sz[0], W) and pct(sz[1], H):
                    c["size"] = [round(pct(sz[0], W), 1), round(pct(sz[1], H), 1)]
        elif kind == "sound":
            snd = portable_path(value)
            c = {"type": "sound", "sound": snd}
            if isinstance(snd, str) and snd and not snd.startswith("$"):
                self.res.assets.add(snd)
        elif kind == "shape":
            shape = a.get("shape", "rectangle").strip().lower()
            c = {"type": "shape", "shape": {"rectangle": "rect", "circle": "circle", "triangle": "triangle"}.get(shape, "rect"),
                 "fill": color(a.get("color", "white")) or "white"}
            sz = plist(a.get("size", "(10%, 10%)"))
            if len(sz) == 2 and pct(sz[0], W) and pct(sz[1], H):
                c["size"] = [round(pct(sz[0], W), 1), round(pct(sz[1], H), 1)]
        elif kind == "port":
            raw = value.strip()
            code = int(raw, 2) if re.fullmatch(r"[01]{8}", raw) else num(raw)
            c = {"type": "marker", "label": name, "code": code if isinstance(code, int) else 1}
            self.res.note("info", w, f"<port {name}> became a marker (code {c['code']}), sent to every TTL/LSL device")
        else:
            self.res.note("unsupported", w, "videos are not converted; add the movie by hand")
            return None
        if "position" in a and kind in ("text", "picture", "shape"):
            p = plist(a["position"])
            if len(p) == 2 and pct(p[0], 100) is not None and pct(p[1], 100) is not None and "%" in a["position"]:
                c["pos"] = [round((pct(p[0], 1) - 0.5) * W, 1), round((0.5 - pct(p[1], 1)) * H, 1)]
        ignored = [k for k in a if k not in ("items", "select", "txcolor", "fontstyle", "position", "size", "erase",
                                             "txbgcolor", "color", "shape", "port", "subport", "hjustify", "vjustify")]
        if ignored:
            self.res.note("approx", w, f"settings not converted: {', '.join('/' + k for k in ignored)}")
        return c

    # ------------------------------------------------------------------ trials
    def trial_spec(self, name: str) -> dict[str, Any] | None:
        el = self.el("trial", name)
        if not el:
            return None
        a = el["attrs"]
        w = f"trial.{name}"
        events = []
        unit = "frames" if "stimulusframes" in a and "stimulustimes" not in a else "ms"
        for t, names in schedule(a.get("stimulustimes") or a.get("stimulusframes") or "[]"):
            for n in names:
                events.append((t, n))
        spec: dict[str, Any] = {"name": name, "events": events, "unit": unit, "where": w,
                                "keys": None, "mouse": False, "correct": None, "timeout": None, "duration": None,
                                "pre": num(a.get("pretrialpause", "0")), "post": num(a.get("posttrialpause", "0")),
                                "messages": [], "branch": [], "begin": {}, "end": {}, "begin_resp": None,
                                "interrupt": a.get("responseinterrupt", "immediate").strip().lower()}
        vr = a.get("validresponse", "")
        if vr:
            items = plist(vr)
            if any(i.lower() in ("lbuttondown", "rbuttondown", "mousebuttondown", "lbuttonup") for i in items) or \
                    any(self.find(i, STIMULI) for i in items):
                spec["mouse"] = [i for i in items if self.find(i, STIMULI)]
            else:
                spec["keys"] = keys_of(vr)
        if a.get("correctresponse"):
            cr = a["correctresponse"].strip()
            vm = re.fullmatch(r"\(\s*values\.(\w+)\s*\)", cr)
            if vm:
                spec["correct"] = "$" + vm.group(1)
            elif spec["mouse"] is not False:
                spec["correct"] = plist(cr)[0]
            else:
                ks = keys_of(cr) or []
                spec["correct"] = ks[0] if len(ks) == 1 else (ks or None)
                if len(ks) > 1:
                    self.res.note("approx", w, f"several correct responses ({', '.join(ks)}): only the first counts")
                    spec["correct"] = ks[0]
        for key in ("timeout", "trialduration", "beginresponsetime"):
            if key in a:
                n = num(a[key])
                if not isinstance(n, (int, float)):
                    self.res.note("approx", w, f"/{key} = {a[key]} is an expression: not converted")
                    continue
                spec[{"timeout": "timeout", "trialduration": "duration", "beginresponsetime": "begin_resp"}[key]] = n
        for key in ("correctmessage", "errormessage"):
            m = re.fullmatch(r"\s*true\s*\(\s*(\w+)\s*,\s*(\d+)\s*\)\s*", a.get(key, ""), re.I)
            if m:
                spec["messages"].append((key, m.group(1), int(m.group(2))))
            elif a.get(key) and a[key].strip().lower() not in ("false", "true"):
                self.res.note("approx", w, f"/{key} = {a[key]} not converted")
        if a.get("branch"):
            for part in split_top(a["branch"].strip()[1:-1] if a["branch"].strip().startswith("[") else a["branch"], ";"):
                m = re.fullmatch(r"\s*if\s*\(\s*trial\.(\w+)\.(correct|error)\s*\)\s*trial\.(\w+)\s*", part)
                if m and m.group(1).lower() == name.lower():
                    spec["branch"].append(("$resp.corr == 1" if m.group(2) == "correct" else "$not resp.corr", m.group(3)))
                else:
                    self.keep_out(f"trial.{name}", f"/branch = [{part.strip()}]")
        vals = set(self.values)
        for key, slot in (("ontrialbegin", "begin"), ("ontrialend", "end")):
            for raw in [v for k, v in a.items() if k == key]:
                done, left = statements(raw, name, vals)
                spec[slot].update(done)
                for st in left:
                    self.keep_out(w, f"/{key} = [{st}]")
        known = {"stimulustimes", "stimulusframes", "validresponse", "correctresponse", "timeout", "trialduration",
                 "beginresponsetime", "pretrialpause", "posttrialpause", "correctmessage", "errormessage", "branch",
                 "ontrialbegin", "ontrialend", "responseinterrupt", "inputdevice", "recorddata", "responsetrial"}
        for k in a:
            if k not in known:
                self.keep_out(w, f"/{k} = {a[k]}")
        return spec

    def components(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        comps: list[dict[str, Any]] = []
        ids = Ids()
        frames = spec["unit"] == "frames"
        last_onset = 0
        for t, n in spec["events"]:
            c = self.stimulus(n, spec["where"])
            if c is None:
                continue
            c = {"id": ids.make(n, "stim"), **c}
            if frames:
                if t > 1:
                    c["start_frame"] = int(t) - 1
                last_onset = (t - 1) / 60 * 1000
            elif t:
                c["start"] = ms(t)
                last_onset = t
            c["_name"] = n
            comps.append(c)
        # Inquisit draws a later text over an earlier one at the same place (with its background): end the earlier one
        for i, c in enumerate(comps):
            if c["type"] not in ("text", "image", "shape"):
                continue
            for later in comps[i + 1:]:
                if later["type"] in ("text", "image") and later.get("pos", [0, 0]) == c.get("pos", [0, 0]) \
                        and later.get("start", 0) > c.get("start", 0):
                    c["duration"] = round(later["start"] - c.get("start", 0), 6)
                    break
        if spec["keys"] is not None or spec["mouse"] is not False:
            r: dict[str, Any] = {"id": "resp", "type": "keyboard" if spec["mouse"] is False else "mouse"}
            if spec["keys"]:
                r["keys"] = spec["keys"]
            if spec["mouse"]:
                clickable = [c["id"] for c in comps if c.get("_name") in spec["mouse"]]
                if clickable:
                    r["clickable"] = clickable
            if spec["correct"] is not None:
                r["correct"] = spec["correct"]
            begin = spec["begin_resp"] if spec["begin_resp"] is not None else last_onset
            if begin:
                r["start"] = ms(begin)
            if spec["timeout"]:
                r["duration"] = ms(spec["timeout"])
            if spec["interrupt"] != "trial":
                r["end_routine"] = True
            comps.append(r)
        for c in comps:
            c.pop("_name", None)
        if spec["begin"]:
            comps.insert(0, {"id": "on_begin", "type": "variable", "when": "start", "set": spec["begin"]})
        if spec["end"]:
            comps.append({"id": "on_end", "type": "variable", "when": "end", "set": spec["end"]})
        return comps

    def routine_of(self, spec: dict[str, Any], comps: list[dict[str, Any]], rid: str) -> dict[str, Any]:
        r: dict[str, Any] = {"components": comps}
        has_resp = any(c["id"] == "resp" for c in comps)
        if spec["duration"]:
            r["duration"] = ms(spec["duration"])
        elif not has_resp:
            last = max([t for t, _ in spec["events"]] or [0])
            last = last / 60 * 1000 if spec["unit"] == "frames" else last
            r["duration"] = ms(last + 1000)
            self.res.note("approx", spec["where"], "the trial has no response and no /trialduration: it was set to "
                          f"end 1 s after its last stimulus ({r['duration']} s)")
        return r

    def trial_nodes(self, name: str, rid: str, spec: dict[str, Any]) -> list[Any]:
        """What runs for one trial: pretrialpause, the screen, the correct/error message, posttrialpause, branches."""
        nodes: list[Any] = []
        if spec["pre"]:
            nodes.append(self.pause(f"{rid}_pretrialpause", spec["pre"]))
        nodes.append(rid)
        nodes += self.messages(rid, spec)
        if spec["post"]:
            nodes.append(self.pause(f"{rid}_posttrialpause", spec["post"]))
        for cond, target in spec["branch"]:
            sub = self.trial_or_other(target, f"trial.{name}.branch")
            for s in sub:
                nodes.append({"routine": s, "if": cond} if isinstance(s, str) else {"if": cond, "then": [s]})
        return nodes

    def pause(self, rid: str, value: Any) -> str:
        rid_final = rid if rid in self.routines else self.ids.make(rid, "pause")
        if rid_final not in self.routines:
            self.routines[rid_final] = {"duration": ms(value) if isinstance(value, (int, float)) else value,
                                        "components": [{"id": "blank", "type": "wait"}]}
            self.res.count("screens")
        return rid_final

    def messages(self, rid: str, spec: dict[str, Any]) -> list[Any]:
        out = []
        for key, elname, dur in spec["messages"]:
            c = self.stimulus(elname, f"{spec['where']}.{key}")
            if c is None:
                continue
            mid = self.ids.make(f"{rid}_{key}", "message")
            self.routines[mid] = {"duration": ms(dur), "components": [{"id": ident(elname), **c}]}
            self.res.count("screens")
            out.append({"routine": mid, "if": "$resp.corr == 1" if key == "correctmessage" else "$not resp.corr"})
        return out

    def single_trial(self, name: str) -> list[Any]:
        key = ("trial", name.lower())
        if key in self.made:
            return self.made[key]
        spec = self.trial_spec(name)
        self.made[key] = []
        if spec is None:
            return []
        rid = self.ids.make(name, "trial")
        self.routines[rid] = self.routine_of(spec, self.components(spec), rid)
        self.res.count("screens")
        self.made[key] = self.trial_nodes(name, rid, spec)
        return self.made[key]

    def trial_or_other(self, name: str, where: str) -> list[Any]:
        """A name in a block's trials list or a branch: a trial, a survey page, an instruction page."""
        if self.el("trial", name):
            return self.single_trial(name)
        if self.el("surveypage", name):
            return [self.survey_routine(name, [name])]
        if self.el("page", name):
            return [self.page(name)]
        other = next((k for k, d in self.by.items() if name.lower() in d), None)
        self.res.note("unsupported", where, f"'{name}' was not converted"
                      + (f": <{other}> trials are not supported" if other else ": there is no element of that name"))
        return []

    # ------------------------------------------------------------------ merging trials into one screen + trial list
    def merge(self, names: list[str], block: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]] | None:
        """Trials that share their timing and response layout -> (screen id, a row per trial, the first spec)."""
        uniq = list(dict.fromkeys(n.lower() for n in names))
        specs = [self.trial_spec(next(x for x in names if x.lower() == u)) for u in uniq]
        if len(specs) < 2 or any(s is None for s in specs):
            return None
        first = specs[0]
        sig = lambda s: ([t for t, _ in s["events"]], s["unit"], s["keys"], s["mouse"], s["duration"], s["interrupt"],
                         [(k, el, d) for k, el, d in s["messages"]], s["begin_resp"], s["branch"],
                         sorted(s["begin"]), sorted(s["end"]))
        base = sig(first)
        if any(sig(s) != base for s in specs[1:]):
            return None
        kinds = [[(self.find(n, STIMULI) or ("?", None))[0] for _, n in s["events"]] for s in specs]
        if any(k != kinds[0] for k in kinds):
            return None
        comp_sets = [self.components(s) for s in specs]
        merged = [dict(c) for c in comp_sets[0]]
        rows: list[dict[str, Any]] = [{"trial": s["name"]} for s in specs]
        stim_no = 0
        for i, c in enumerate(merged):
            if c["id"] in ("resp", "on_begin", "on_end"):
                continue
            versions = [cs[i] for cs in comp_sets]
            props = [p for p in c if p != "id" and any(v.get(p) != c.get(p) for v in versions)]
            if not props and len({v["id"] for v in versions}) == 1:
                continue
            stim_no += 1
            cid = "stim" if stim_no == 1 else f"stim{stim_no}"
            c["id"] = cid
            for p in props:
                col = f"{cid}_{p}"
                for row, v in zip(rows, versions):
                    row[col] = v.get(p)
                c[p] = "$" + col
        resp = next((c for c in merged if c["id"] == "resp"), None)
        if resp is not None and any(s["correct"] != first["correct"] for s in specs):
            for row, s in zip(rows, specs):
                row["correct_response"] = s["correct"]
            resp["correct"] = "$correct_response"
        if resp is not None and any(s["timeout"] != first["timeout"] for s in specs):
            for row, s in zip(rows, specs):
                row["timeout"] = ms(s["timeout"]) if s["timeout"] else None
            resp["duration"] = "$timeout"
        for key in ("pre", "post"):
            if any(s[key] != first[key] for s in specs):
                for row, s in zip(rows, specs):
                    row[f"{key}trialpause"] = ms(s[key] or 0)
        for slot in ("begin", "end"):           # the same assignments, written for each trial's own name
            if any(s[slot] != first[slot] for s in specs):
                return None
        rid = self.ids.make(f"{block}_trial", "trial")
        self.routines[rid] = self.routine_of(first, merged, rid)
        self.res.count("screens")
        nodes: list[Any] = []
        varying = {k for r in rows for k in r}
        for key in ("pre", "post"):
            val = f"${key}trialpause" if f"{key}trialpause" in varying else first[key]
            if val:
                p = self.pause(f"{rid}_{key}trialpause", val)
                nodes.append((key, p))
        node_list = [p for k, p in nodes if k == "pre"] + [rid] + self.messages(rid, first) + \
            [p for k, p in nodes if k == "post"]
        self.res.note("info", f"blocks.{block}", f"the trials {', '.join(s['name'] for s in specs)} differ only in "
                      f"their stimuli and responses: they became one screen, '{rid}', and the differences became "
                      f"columns of the trial list ({', '.join(sorted(varying - {'trial'}))})")
        return rid, rows, {"nodes": node_list}

    # ------------------------------------------------------------------ pages, surveys, blocks
    def page(self, name: str) -> str:
        key = ("page", name.lower())
        if key in self.made:
            return self.made[key][0]
        el = self.el("page", name)
        body = el["body"] if el else ""
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.split("^")]
        text = "\n".join(lines).strip("\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        rid = self.ids.make(name, "page")
        fs = plist(self.instruct.get("fontstyle", '("Arial", 3%)'))
        height = pct(fs[1], H) if len(fs) > 1 and pct(fs[1], H) else H * 0.03
        nk = self.instruct.get("nextkey")
        keys = keys_of(nk) if nk else None
        comps: list[dict[str, Any]] = [
            {"id": "text", "type": "text", "text": text, "height": round(height, 1),
             "color": color(self.instruct.get("txcolor", "")) or self.txcolor, "wrap_width": round(W * 0.8)},
            {"id": "next", "type": "keyboard", "keys": keys or ["space"], "end_routine": True}]
        if not keys and "next" not in self.res.stats:
            self.res.note("approx", f"pages.{name}", "Inquisit's Continue button on instruction pages became the "
                          "space bar")
            self.res.stats["next"] = 0
        self.routines[rid] = {"components": comps}
        self.res.count("screens")
        self.made[key] = [rid]
        return rid

    def pages(self, v: str | None) -> list[Any]:
        if not v:
            return []
        out = []
        for n in plist(v):
            if self.el("page", n):
                out.append(self.page(n))
            else:
                self.res.note("unsupported", f"instructions.{n}", f"instruction page '{n}' not found")
        return out

    def question(self, kind: str, el: dict[str, Any], where: str) -> dict[str, Any] | None:
        a = el["attrs"]
        q: dict[str, Any] = {"id": ident(el["name"]), "text": unquote(a.get("caption", el["name"]))}
        opts = plist(a["options"]) if "options" in a else []
        rng = [num(x) for x in plist(a["range"])] if "range" in a else []
        if kind == "textbox":
            mask = a.get("mask", "").strip().lower()
            if mask in ("integer", "positiveinteger", "number", "decimal"):
                q["type"] = "number"
                if len(rng) == 2:
                    q["min"], q["max"] = rng
            else:
                q["type"] = "essay" if a.get("multiline", "").strip().lower() == "true" else "text"
        elif kind in ("radiobuttons", "dropdown", "checkboxes", "listbox"):
            q["type"] = {"radiobuttons": "single", "dropdown": "dropdown", "checkboxes": "multiple",
                         "listbox": "dropdown"}[kind]
            q["options"] = opts or ["yes", "no"]
        elif kind == "slider":
            q["type"] = "slider"
            if len(rng) == 2:
                q["min"], q["max"] = rng
        else:
            self.res.note("unsupported", where, f"<{kind} {el['name']}> questions are not converted")
            return None
        if a.get("required", "").strip().lower() == "true":
            q["required"] = True
        return q

    def survey_routine(self, sid: str, pages: list[str]) -> str:
        key = ("survey", sid.lower())
        if key in self.made:
            return self.made[key][0]
        questions: list[dict[str, Any]] = []
        title = None
        for i, p in enumerate(pages):
            pel = self.el("surveypage", p)
            if not pel:
                self.res.note("unsupported", f"surveys.{sid}", f"survey page '{p}' not found")
                continue
            title = title or (unquote(pel["attrs"]["caption"]) if "caption" in pel["attrs"] else None)
            if i and questions:
                questions.append({"type": "page_break"})
            for seg in trial_segments(pel["attrs"].get("questions", "[]")) or []:
                for qn in seg["names"]:
                    found = self.find(qn, ("textbox", "radiobuttons", "dropdown", "checkboxes", "slider", "listbox",
                                           "caption", "likert"))
                    if not found:
                        self.res.note("unsupported", f"surveys.{sid}.{p}", f"question '{qn}' not found")
                        continue
                    if found[0] == "caption":
                        questions.append({"type": "text_block", "text": unquote(found[1]["attrs"].get("caption", ""))})
                        continue
                    q = self.question(found[0], found[1], f"surveys.{sid}.{qn}")
                    if q:
                        questions.append(q)
        rid = self.ids.make(sid, "survey")
        comp: dict[str, Any] = {"id": ident(sid), "type": "survey", "questions": questions or
                                [{"type": "text_block", "text": "(empty survey)"}], "end_routine": True}
        if title:
            comp["title"] = title
        self.routines[rid] = {"components": [comp]}
        self.res.count("screens")
        self.res.count("survey questions", sum(1 for q in questions if q.get("type") not in ("page_break", "text_block")))
        self.made[key] = [rid]
        return rid

    def selection_loop(self, lid: str, seg: dict[str, Any], rows: list[dict[str, Any]], children: list[Any],
                       where: str) -> dict[str, Any]:
        count, mode = seg["count"], seg["mode"]
        n = len(seg["names"])
        if ident(lid) in self.ids.taken:            # a trial of the same name ('practice' in block 'practice')
            lid = f"{lid}_trials"
        node: dict[str, Any] = {"loop": self.ids.make(lid, "loop")}
        expanded = [rows[seg["names"].index(nm)] for nm in seg["names"]] if len(rows) != n else rows
        if count % n == 0:
            node["conditions"] = [dict(r) for r in expanded]
            if count // n != 1:
                node["repeats"] = count // n
        else:
            node["conditions"] = [dict(expanded[i % n]) for i in range(count)]
            self.res.note("approx", where, f"{count} trials drawn from {n} kinds: the trial list holds the first "
                          f"{count} in cycle, shuffled")
        node["order"] = "sequential" if mode == "sequence" else "random"
        if mode == "replace":
            self.res.note("approx", where, "replace() (drawing with replacement) became a shuffled list in which every "
                          "kind appears equally often")
        elif mode not in ("noreplace", "sequence"):
            self.res.note("approx", where, f"{mode}() converted to a shuffled list (its special rule is not kept)")
        node["children"] = children
        self.res.count("trial lists")
        return node

    def segment_nodes(self, seg: dict[str, Any], owner: str, kind: str) -> list[Any]:
        where = f"{kind}.{owner}"
        names = seg["names"]
        if len(set(n.lower() for n in names)) == 1:
            sub = self.block(names[0]) if kind == "expt" else self.trial_or_other(names[0], where)
            if seg["count"] == 1 or not sub:
                return sub
            return [self.selection_loop(owner, {**seg, "names": [names[0]]}, [{kind_col(kind): names[0]}], sub, where)]
        if kind == "block":
            merged = self.merge(names, owner)
            if merged:
                rid, rows, extra = merged
                first_names = list(dict.fromkeys(n.lower() for n in names))
                rows_by = {r["trial"].lower(): r for r in rows}
                ordered = [rows_by[n.lower()] for n in names]
                if len(first_names) == len(names):
                    ordered = [rows_by[n] for n in first_names]
                return [self.selection_loop(owner, {**seg, "names": [r["trial"] for r in ordered]}, ordered,
                                            extra["nodes"], where)]
        col = kind_col(kind)
        children: list[Any] = []
        for nm in dict.fromkeys(names):
            sub = self.block(nm) if kind == "expt" else self.trial_or_other(nm, where)
            if sub:
                children.append({"if": f"${col} == {nm!r}", "then": sub})
        rows = [{col: nm} for nm in names]
        return [self.selection_loop(owner, seg, rows, children, where)]

    def block(self, name: str) -> list[Any]:
        key = ("block", name.lower())
        if key in self.made:
            self.res.note("info", f"blocks.{name}", "the block runs more than once: its screens are reused")
            return self.made[key]
        if self.el("survey", name):
            pages = [n for s in trial_segments(self.el("survey", name)["attrs"].get("pages", "[]")) or [] for n in s["names"]]
            self.made[key] = [self.survey_routine(name, pages)]
            return self.made[key]
        if self.el("surveypage", name):
            return [self.survey_routine(name, [name])]
        el = self.el("block", name)
        if not el:
            other = next((k for k, d in self.by.items() if name.lower() in d), None)
            self.res.note("unsupported", f"expt.blocks.{name}", f"block '{name}' was not converted"
                          + (f" (it is a <{other}>)" if other else " (there is no element of that name)"))
            return []
        a = el["attrs"]
        nodes: list[Any] = self.pages(a.get("preinstructions"))
        vals = set(self.values)
        for key2, when in (("onblockbegin", "begin"), ("onblockend", "end")):
            if key2 in a:
                done, left = statements(a[key2], None, vals)
                for st in left:
                    self.keep_out(f"block.{name}", f"/{key2} = [{st}]")
                if done:
                    rid = self.ids.make(f"{name}_{when}", "block")
                    self.routines[rid] = {"duration": 0, "components": [
                        {"id": "set_values", "type": "variable", "when": "start", "set": done}]}
                    self.res.count("screens")
                    a[f"_{when}"] = rid
        if a.get("_begin"):
            nodes.append(a["_begin"])
        segs = trial_segments(a.get("trials", "")) if a.get("trials") else []
        if segs is None:
            self.res.note("unsupported", f"blocks.{name}", f"the trials list '{a['trials']}' could not be read")
            segs = []
        for seg in segs:
            nodes += self.segment_nodes(seg, name, "block")
        if a.get("_end"):
            nodes.append(a["_end"])
        nodes += self.pages(a.get("postinstructions"))
        for k in a:
            if k not in ("preinstructions", "postinstructions", "trials", "onblockbegin", "onblockend", "_begin",
                         "_end", "recorddata"):
                self.keep_out(f"block.{name}", f"/{k} = {a[k]}")
        self.res.count("blocks")
        self.made[key] = nodes
        return nodes

    # ------------------------------------------------------------------ the whole script
    def run(self) -> ImportResult:
        res = self.res
        res.note("info", "source", "converted from the Inquisit script; Inquisit's expressions, scripts and "
                 "data settings are listed below where they could not be converted")
        expt = self.one("expt")
        flow: list[Any] = []
        if any(e["kind"] == "expt" for e in self.elements):
            flow += self.pages(expt.get("preinstructions"))
            if expt.get("blocks"):
                segs = trial_segments(expt["blocks"])
                if segs is None:
                    res.note("unsupported", "expt", f"the blocks list '{expt['blocks']}' could not be read")
                for seg in segs or []:
                    flow += self.segment_nodes(seg, "expt", "expt")
            flow += self.pages(expt.get("postinstructions"))
            for k in expt:
                if k not in ("preinstructions", "postinstructions", "blocks"):
                    self.keep_out("expt", f"/{k} = {expt[k]}")
            if len([e for e in self.elements if e["kind"] == "expt"]) > 1:
                res.note("approx", "expt", "several <expt> elements (e.g. one per group): only the first was used")
        else:
            blocks = [e["name"] for e in self.elements if e["kind"] == "block"]
            for b in blocks:
                flow += self.block(b)
            if blocks:
                res.note("approx", "expt", "the script has no <expt>: its blocks run in the order they are written")
        for what, wheres in self.unconverted.items():
            places = list(dict.fromkeys(wheres))
            res.note("unsupported", places[0] if len(places) == 1 else f"{places[0]} (and {len(places) - 1} more)",
                     f"not converted: {what[:300]}")
        for kind in ("list", "counter", "script", "expressions", "include", "html", "video", "likert", "openended",
                     "monkey", "batch", "summarydata", "parameters"):
            for name in self.by.get(kind, {}):
                if kind == "include":
                    res.note("unsupported", "include", "an <include> file is not read: import a script with "
                             "everything in one file, or add its parts by hand")
                elif kind in ("list", "counter"):
                    items = plist(self.by[kind][name]["attrs"].get("items", "()"))
                    res.note("unsupported", f"{kind}.{name}", f"<{kind} {name}> ({len(items)} items) is not converted: "
                             "put its items in a trial list column, or use $random.choice([...]) where it is used")
                else:
                    res.note("unsupported", f"{kind}.{name or kind}", f"<{kind}{' ' + name if name else ''}> is not "
                             "converted")
        if self.by.get("data") or self.by.get("summarydata"):
            res.note("info", "data", "<data> columns are not needed: EDGE saves every response, RT, correctness and "
                     "trial-list column automatically")
        if not flow:
            cut = next((n for n in res.notes if n["message"].endswith("may be missing") and "is not closed" in n["message"]), None)
            res.note("unsupported", "flow", "no <expt> or <block> with trials was found"
                     + (f" (the file seems cut short: {cut['message'].split(' is not closed')[0]} at {cut['where']} "
                        "is not closed)" if cut else ""))
        res.stats.pop("next", None)
        bg = color(self.defaults.get("screencolor", "white")) or "white"
        res.doc = {"name": ident(self.path.stem), "description": f"Imported from Inquisit ({self.path.name})",
                   "settings": {"window": {"size": [W, H], "background": bg, "units": "px"}},
                   "devices": [], "variables": dict(self.values), "routines": self.routines, "flow": flow}
        avoid_column_clashes(res.doc)
        return res


def kind_col(kind: str) -> str:
    return "block" if kind == "expt" else "trial"


def import_inquisit(path: Path) -> ImportResult:
    text = read_text(path)
    return Converter(path, text).run()


def looks_like_inquisit(path: Path) -> bool:
    if path.suffix.lower() not in (".iqx", ".exp", ".iqjs"):
        return False
    try:
        head = read_text(path)[:200000].lower()
    except OSError:
        return False
    return path.suffix.lower() == ".iqx" or bool(re.search(r"<\s*(trial|block|expt|defaults|text|values)\b", head))
