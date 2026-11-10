"""Presentation importer (Neurobehavioral Systems; ``.sce`` scenario files and their ``.pcl`` programs).

The scenario (SDL) is read completely enough for typical tasks:

* header parameters (background, font size, text colour, active buttons, ``pcl_file``);
* ``text``, ``bitmap``, ``wavefile``/``sound``, ``box``, ``picture`` definitions (named or inline, with x/y);
* ``trial`` definitions with ``trial_duration`` (ms, ``forever``, ``stimuli_length``), ``trial_type``
  (``first_response`` …) and ``stimulus_event`` blocks (``time``, ``duration``, ``code``, ``port_code``,
  ``target_button``) -> screens with timed items, a keyboard and markers;
* ``TEMPLATE "file.tem" { columns; rows }`` -> a trial list whose columns fill the template's ``$variables``;
  ``LOOP $i N; … ENDLOOP;`` -> repeats.

Without a PCL program, the scenario's trials run in the order they are written. With one, the common PCL
patterns are translated: arrays (``array<string> words[3] = {...}``), ``.shuffle()``, ``loop int i = 1 until
i > n begin … end;`` over the trials, ``set_caption``/``set_font_color``/``set_filename``/``set_target_button``/
``set_port_code``/``set_duration`` with values taken from the arrays (they become trial-list columns),
``trial.present()`` and ``if last.type() == stimulus_hit then … else … end;`` checks of the response. Every other
statement is listed in the report with its line number.

Presentation's response buttons are mapped to keys in its Settings, which are not part of the scenario: button 1
becomes the key ``1``, button 2 the key ``2``, and so on (the report says so).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .base import (
    Ids,
    ImportError_,
    ImportResult,
    avoid_column_clashes,
    ident,
    inside,
    ms,
    num,
    portable_path,
    read_text,
)

W, H = 1024, 768


class Var:
    """A ``$name`` in a template (filled per row of the TEMPLATE table)."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"${self.name}"


# ------------------------------------------------------------------ SDL tokens and definitions
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\$\w+|[A-Za-z_]\w*|-?\d+(?:\.\d+)?|[{};=,]|\S')


def strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        q, cut = False, len(line)
        for i, ch in enumerate(line):
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                q = not q
            elif ch == "#" and not q:
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def tokens(text: str) -> list[tuple[str, int]]:
    out = []
    for m in TOKEN.finditer(text):
        out.append((m.group(0), text.count("\n", 0, m.start()) + 1))
    return out


def value(tok: str) -> Any:
    if tok.startswith('"'):
        return tok[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    if tok.startswith("$"):
        return Var(tok[1:])
    return num(tok)


class SDL:
    """A recursive-descent reader of SDL statements: params, definitions and references."""

    def __init__(self, toks: list[tuple[str, int]], res: ImportResult, folder: Path, depth: int = 0):
        self.t, self.i, self.res, self.folder, self.depth = toks, 0, res, folder, depth

    def peek(self, k: int = 0) -> str | None:
        return self.t[self.i + k][0] if self.i + k < len(self.t) else None

    def line(self) -> int:
        return self.t[min(self.i, len(self.t) - 1)][1] if self.t else 0

    def take(self) -> str:
        tok = self.t[self.i][0]
        self.i += 1
        return tok

    def block(self, top: bool = False) -> list[dict[str, Any]]:
        """Statements up to the closing brace (or the end at the top level)."""
        out: list[dict[str, Any]] = []
        while self.i < len(self.t):
            tok = self.peek()
            if tok == "}":
                if top:
                    self.res.note("approx", f"line {self.line()}", "an unmatched '}' was skipped")
                    self.take()
                    continue
                self.take()
                return out
            if tok == ";":
                self.take()
                continue
            line = self.line()
            if tok == "LOOP":
                self.take()
                var, n = self.take(), num(self.take())
                body: list[dict[str, Any]] = []
                if self.peek() == ";":
                    self.take()
                start = self.i
                depth = 0
                while self.i < len(self.t) and not (self.peek() == "ENDLOOP" and depth == 0):
                    if self.peek() == "LOOP":
                        depth += 1
                    elif self.peek() == "ENDLOOP":
                        depth -= 1
                    self.i += 1
                inner = SDL(self.t[start:self.i], self.res, self.folder, self.depth)
                body = inner.block(top=True)
                if self.peek() == "ENDLOOP":
                    self.take()
                out.append({"kind": "LOOP", "var": var, "n": n if isinstance(n, int) else 1, "body": body, "line": line})
                continue
            if tok == "TEMPLATE":
                self.take()
                fname = value(self.take())
                rows: list[list[Any]] = []
                if self.peek() == "{":
                    self.take()
                    cur: list[Any] = []
                    while self.i < len(self.t) and self.peek() != "}":
                        x = self.take()
                        if x == ";":
                            if cur:
                                rows.append(cur)
                            cur = []
                        elif x != ",":
                            cur.append(value(x) if (x.startswith('"') or x.startswith("$") or
                                                    isinstance(num(x), (int, float))) else x)
                    if cur:
                        rows.append(cur)
                    if self.peek() == "}":
                        self.take()
                out.append({"kind": "TEMPLATE", "file": fname, "rows": rows, "line": line})
                continue
            if not re.fullmatch(r"[A-Za-z_]\w*|\$\w+", tok or ""):
                self.res.note("approx", f"line {line}", f"unexpected '{tok}' in the scenario was skipped")
                self.take()
                continue
            name = self.take()
            nxt = self.peek()
            if nxt == "=":
                self.take()
                vals: list[Any] = []
                while self.i < len(self.t) and self.peek() not in (";", "}"):
                    x = self.take()
                    if x != ",":
                        vals.append(value(x))
                out.append({"kind": "param", "name": name.lower() if not name.startswith("$") else name,
                            "values": vals, "line": line})
            elif nxt == "{":
                self.take()
                body = self.block()
                label = None
                if self.peek() and re.fullmatch(r"[A-Za-z_]\w*", self.peek() or "") and self.peek(1) in (";", None, "}"):
                    label = self.take()
                out.append({"kind": "def", "type": name.lower(), "body": body, "name": label, "line": line})
            elif nxt and re.fullmatch(r"[A-Za-z_]\w*", nxt):
                self.take()
                out.append({"kind": "ref", "type": name.lower(), "name": nxt, "line": line})
            else:
                out.append({"kind": "word", "name": name, "line": line})
        return out


def params(body: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {s["name"]: s["values"] for s in body if s["kind"] == "param"}


def rgb(vals: list[Any]) -> Any:
    if len(vals) >= 3 and all(isinstance(v, int) for v in vals[:3]):
        return "#%02x%02x%02x" % tuple(max(0, min(255, v)) for v in vals[:3])
    if len(vals) == 1 and isinstance(vals[0], Var):
        return f"${vals[0].name}"
    return None


def expr(v: Any) -> Any:
    """A parameter value as an EDGE value: $name for template variables."""
    return f"${v.name}" if isinstance(v, Var) else v


# ------------------------------------------------------------------ PCL
PCL_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[A-Za-z_]\w*|\d+(?:\.\d+)?|==|!=|<=|>=|&&|\|\||[^\s]')


def pcl_statements(text: str) -> list[tuple[str, int]]:
    """PCL source -> statements (text, first line); 'begin', 'then' and 'else' also end a statement."""
    out: list[tuple[str, int]] = []
    cur: list[str] = []
    start = None
    depth = 0
    text = strip_comments(text)
    for m in PCL_TOKEN.finditer(text):
        tok = m.group(0)
        line = text.count("\n", 0, m.start()) + 1
        if start is None:
            start = line
        if tok in "([{":
            depth += 1
        elif tok in ")]}":
            depth -= 1
        if depth == 0 and tok == ";":
            out.append((" ".join(cur), start))
            cur, start = [], None
        elif depth == 0 and tok in ("begin", "then", "else"):
            cur.append(tok)
            out.append((" ".join(cur), start))
            cur, start = [], None
        else:
            cur.append(tok)
    if cur:
        out.append((" ".join(cur), start or 0))
    return [(re.sub(r"\s*([\[\]().,])\s*", r"\1", s).replace(",", ", "), ln) for s, ln in out if s.strip()]


def pcl_tree(stmts: list[tuple[str, int]]) -> list[dict[str, Any]]:
    """Statements -> a tree with loop/if/sub blocks."""
    pos = 0

    def parse(stop: tuple[str, ...]) -> list[dict[str, Any]]:
        nonlocal pos
        out: list[dict[str, Any]] = []
        while pos < len(stmts):
            s, ln = stmts[pos]
            first = s.split(" ", 1)[0]
            if first in stop or (s.startswith("elseif") and "elseif" in stop):
                return out
            pos += 1
            if first == "loop" and s.endswith("begin"):
                body = parse(("end",))
                pos += 1
                out.append({"kind": "loop", "head": s[:-5].strip(), "body": body, "line": ln})
            elif first == "if" and s.endswith("then"):
                branches = [(s[2:-4].strip(), parse(("else", "elseif", "end")), ln)]
                while pos < len(stmts) and stmts[pos][0].startswith("elseif"):
                    es, eln = stmts[pos]
                    pos += 1
                    branches.append((es[6:-4].strip(), parse(("else", "elseif", "end")), eln))
                if pos < len(stmts) and stmts[pos][0] == "else":
                    pos += 1
                    branches.append((None, parse(("end",)), stmts[pos - 1][1] if pos else ln))
                pos += 1
                out.append({"kind": "if", "branches": branches, "line": ln})
            elif first == "sub" and s.endswith("begin"):
                body = parse(("end",))
                pos += 1
                out.append({"kind": "sub", "head": s, "body": body, "line": ln})
            else:
                out.append({"kind": "stmt", "text": s, "line": ln})
        return out

    return parse(())


class Arr(list):
    """A PCL array (1-based)."""

    def at(self, i: Any) -> Any:
        if not isinstance(i, int) or not 1 <= i <= len(self):
            raise IndexError(i)
        return self[i - 1]


def pcl_value(src: str, names: dict[str, Any]) -> Any:
    """Evaluate a small PCL expression (literals, arrays, indexing, + - * /, rgb_color(), string()) without eval."""
    tree = ast.parse(src.replace("&&", " and ").replace("||", " or "), mode="eval")

    def ev(n: ast.AST) -> Any:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in names:
                return names[n.id]
            raise KeyError(n.id)
        if isinstance(n, ast.Subscript):
            base = ev(n.value)
            idx = ev(n.slice)
            if isinstance(base, Arr):
                return base.at(idx)
            raise KeyError("index")
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Mod):
                return a % b
            return a // b if isinstance(a, int) and isinstance(b, int) else a / b
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            args = [ev(a) for a in n.args]
            if n.func.id == "rgb_color" and len(args) >= 3:
                return "#%02x%02x%02x" % tuple(max(0, min(255, int(x))) for x in args[:3])
            if n.func.id in ("string", "printf"):
                return str(args[0])
            if n.func.id == "int":
                return int(args[0])
            if n.func.id == "double":
                return float(args[0])
        if isinstance(n, ast.Attribute) and n.attr == "count" or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                                                                   and n.func.attr == "count"):
            target = n.func.value if isinstance(n, ast.Call) else n.value
            arr = ev(target)
            if isinstance(arr, Arr):
                return len(arr)
        raise KeyError(type(n).__name__)

    return ev(tree)


def pcl_literal(src: str) -> Any:
    """'{ "RED", "GREEN" }' / '{{1, 2}, {3, 4}}' / '{ rgb_color(255,0,0) }' -> Arr."""
    s = src.strip()
    py = s.replace("{", "[").replace("}", "]")
    py = re.sub(r"rgb_color\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*\d+\s*)?\)",
                lambda m: repr("#%02x%02x%02x" % tuple(min(255, int(x)) for x in m.groups())), py)
    py = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", py))
    try:
        v = ast.literal_eval(py)
    except (ValueError, SyntaxError):
        return None

    def wrap(x: Any) -> Any:
        return Arr(wrap(y) for y in x) if isinstance(x, list) else x

    return wrap(v)


def pcl_ident(s: str) -> str:
    return s.strip().split("[")[0].split(".")[0]


# ------------------------------------------------------------------ the converter
class Converter:
    def __init__(self, path: Path):
        self.path = path
        self.res = ImportResult({}, path, "Presentation")
        self.ids = Ids()
        self.routines: dict[str, Any] = {}
        self.objects: dict[str, dict[str, Any]] = {}      # named SDL objects
        self.trials: list[dict[str, Any]] = []             # trial defs in scenario order (top level)
        self.made: dict[Any, str] = {}
        self.marker_codes: dict[str, int] = {}
        self.button_note = False
        self._pending_markers: list[tuple[str, str]] = []
        self.file_columns: set[str] = set()
        self.n_buttons = 2
        self.used_pcl = False

    # ------------------------------------------------------------- reading
    def read(self) -> tuple[dict[str, list[Any]], list[dict[str, Any]], str | None]:
        text = strip_comments(read_text(self.path))
        m = re.search(r"(?m)^\s*begin\s*;", text)
        if not m:
            raise ImportError_(f"{self.path.name} has no 'begin;' line, so it is not a complete Presentation scenario "
                               "(the file may be cut short). Open it in Presentation, check that it runs, and import "
                               "it again")
        head, body = text[:m.start()], text[m.end():]
        pcl_inline = None
        pm = re.search(r"(?m)^\s*begin_pcl\s*;", body)
        if pm:
            pcl_inline = body[pm.end():]
            body = body[:pm.start()]
        hp = SDL(tokens(head), self.res, self.path.parent)
        header = params(hp.block(top=True))
        sp = SDL(tokens(body), self.res, self.path.parent)
        offset = text.count("\n", 0, m.end())
        sp.t = [(t, ln + offset) for t, ln in sp.t]
        stmts = sp.block(top=True)
        if sp.depth == 0 and body.count("{") != body.count("}"):
            self.res.note("unsupported", "scenario", "the braces { } of the scenario do not match: the file may be cut "
                          "short, so the definitions at its end may be missing")
        return header, stmts, pcl_inline

    def register(self, stmts: list[dict[str, Any]]) -> None:
        for s in stmts:
            if s["kind"] == "def":
                if s["name"]:
                    self.objects[s["name"]] = s
                self.register(s["body"])

    # ------------------------------------------------------------- stimuli
    def resolve(self, s: dict[str, Any]) -> dict[str, Any] | None:
        if s["kind"] == "ref":
            obj = self.objects.get(s["name"])
            if obj is None:
                self.res.note("unsupported", f"line {s['line']}", f"'{s['name']}' is used but not defined")
            return obj
        return s

    def stim_parts(self, obj: dict[str, Any], where: str, overrides: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """A picture/text/bitmap/box/sound definition -> EDGE items (without timing)."""
        t = obj["type"]
        p = params(obj["body"])
        name = obj.get("name")
        ov = overrides.get(name or "", {})
        if t == "picture":
            out = []
            parts = [s for s in obj["body"] if s["kind"] in ("def", "ref")]
            body = obj["body"]
            for idx, s in enumerate(body):
                if s["kind"] not in ("def", "ref"):
                    continue
                x = y = 0
                for s2 in body[idx + 1:]:
                    if s2["kind"] in ("def", "ref"):
                        break
                    if s2["kind"] == "param" and s2["name"] in ("x", "y") and s2["values"]:
                        if s2["name"] == "x":
                            x = expr(s2["values"][0])
                        else:
                            y = expr(s2["values"][0])
                part = self.resolve(s)
                if part is None:
                    continue
                for c in self.stim_parts(part, where, overrides):
                    if c["type"] in ("text", "image", "shape"):
                        c["pos"] = [x, y]
                    out.append(c)
            if not parts:
                out.append({"type": "_blank"})
            for k in p:
                if k not in ("x", "y", "background_color", "display_index"):
                    self.res.note("approx", where, f"picture setting '{k}' not converted")
            return out
        if t == "text":
            caption = ov.get("text", expr((p.get("caption") or [""])[0]))
            c: dict[str, Any] = {"type": "text", "text": caption, "_obj": name}
            col = ov.get("color") or (rgb(p["font_color"]) if "font_color" in p else None)
            if col:
                c["color"] = col
            if "font_size" in p:
                c["height"] = expr(p["font_size"][0])
            if p.get("font") and p["font"][0] not in ("Arial",):
                c["font"] = expr(p["font"][0])
            if isinstance(c["text"], str) and "<" in c["text"] and re.search(r"</?[bi]>", c["text"]):
                c["text"] = re.sub(r"</?\w+>", "", c["text"])
                self.res.note("approx", where, "formatted text tags (<b>, <i>, <font>) were removed")
            return [c]
        if t == "bitmap":
            f = ov.get("image", portable_path(expr((p.get("filename") or [""])[0])))
            if isinstance(f, str) and f and not f.startswith("$"):
                self.res.assets.add(f)
            c = {"type": "image", "image": f, "_obj": name}
            if "width" in p and "height" in p and isinstance(p["width"][0], (int, float)):
                c["size"] = [p["width"][0], p["height"][0]]
            elif "scale_factor" in p:
                self.res.note("approx", where, "bitmap scale_factor not converted")
            return [c]
        if t in ("box", "ellipse_graphic"):
            c = {"type": "shape", "shape": "rect" if t == "box" else "ellipse",
                 "size": [expr((p.get("width") or [50])[0]), expr((p.get("height") or [50])[0])]}
            if "color" in p and rgb(p["color"]):
                c["fill"] = rgb(p["color"])
            return [c]
        if t in ("wavefile", "sound"):
            if t == "sound":
                inner = next((self.resolve(s) for s in obj["body"] if s["kind"] in ("def", "ref")), None)
                return self.stim_parts(inner, where, overrides) if inner else []
            f = ov.get("sound", portable_path(expr((p.get("filename") or [""])[0])))
            if isinstance(f, str) and f and not f.startswith("$"):
                self.res.assets.add(f)
            return [{"type": "sound", "sound": f, "_obj": name}]
        if t == "nothing":
            return []
        self.res.note("unsupported", where, f"'{t}' stimuli are not converted" + (f" ({name})" if name else ""))
        return []

    # ------------------------------------------------------------- trials
    def events(self, trial: dict[str, Any]) -> list[dict[str, Any]]:
        """The trial's stimulus events, also for the short form (``picture x; code = "a";`` in the trial)."""
        evs: list[dict[str, Any]] = []
        implicit: dict[str, Any] | None = None
        for s in trial["body"]:
            if s["kind"] == "def" and s["type"] == "stimulus_event":
                stim = next((x for x in s["body"] if x["kind"] in ("def", "ref")), None)
                evs.append({"stim": stim, "p": params(s["body"]), "name": s["name"], "line": s["line"]})
                implicit = None
            elif s["kind"] in ("def", "ref") and s["type"] in ("picture", "sound", "wavefile", "nothing", "video", "text"):
                implicit = {"stim": s, "p": {}, "name": None, "line": s["line"]}
                evs.append(implicit)
            elif s["kind"] == "param" and implicit is not None and s["name"] in (
                    "time", "duration", "code", "port_code", "target_button", "response_active", "deltat", "delta_time"):
                implicit["p"][s["name"]] = s["values"]
        return evs

    def trial_routine(self, trial: dict[str, Any], rid_hint: str, ov: dict[str, Any] | None = None) -> str:
        ov = ov or {"objects": {}, "events": {}, "trial": {}}
        key = (id(trial), repr(sorted((k, repr(v)) for k, v in ov["objects"].items())),
               repr(ov["events"]), repr(ov["trial"].get(trial.get("name") or "", {})))
        if key in self.made:
            return self.made[key]
        rid = self.ids.make(rid_hint, "trial")
        self.made[key] = rid
        where = f"trials.{rid}"
        tp = params(trial["body"])
        t_ov = ov["trial"].get(trial.get("name") or "", {})
        comps: list[dict[str, Any]] = []
        cids = Ids()
        evs = self.events(trial)
        times: list[Any] = []
        t_prev: Any = 0
        for e in evs:
            p = e["p"]
            if "time" in p:
                t_prev = expr(p["time"][0])
            elif "deltat" in p or "delta_time" in p:
                d = expr((p.get("deltat") or p.get("delta_time"))[0])
                t_prev = t_prev + d if isinstance(t_prev, (int, float)) and isinstance(d, (int, float)) else d
            times.append(t_prev)
        target_time = None
        target: Any = None
        resp_active = False
        for k, e in enumerate(evs):
            p = e["p"]
            e_ov = ov["events"].get(e["name"] or "", {})
            stim = self.resolve(e["stim"]) if e["stim"] else None
            parts = self.stim_parts(stim, where, ov["objects"]) if stim else []
            start = e_ov.get("time", times[k])
            dur = e_ov.get("duration", expr(p["duration"][0]) if "duration" in p else None)
            visual = [c for c in parts if c["type"] != "sound"]
            if dur in (None, "next_picture") and visual:
                nxt = next((times[j] for j in range(k + 1, len(evs)) if evs[j]["stim"] is not None and
                            (self.resolve(evs[j]["stim"]) or {}).get("type") == "picture"), None)
                dur = (nxt - start) if isinstance(nxt, (int, float)) and isinstance(start, (int, float)) else None
            elif dur == "response":
                dur = None
            tb = e_ov.get("target_button", expr(p["target_button"][0]) if "target_button" in p else None)
            if tb is not None or (p.get("response_active") or [""])[0] == "true":
                resp_active = True
                if target_time is None:
                    target_time, target = start, tb
                if "target_button" in p and len(p["target_button"]) > 1:
                    self.res.note("approx", where, "several target buttons: only the first counts as correct")
            code = e_ov.get("code", expr(p["code"][0]) if "code" in p else None)
            port = e_ov.get("port_code", expr(p["port_code"][0]) if "port_code" in p else None)
            first = True
            for c in parts:
                if c["type"] == "_blank":
                    c = {"type": "wait"}
                obj = c.pop("_obj", None)
                c = {"id": cids.make(obj or (e["name"] or c["type"]), c["type"]), **c}
                if c["type"] != "wait" and start not in (0, None):
                    c["start"] = ms(start) if isinstance(start, (int, float)) else _sec(start)
                elif c["type"] == "wait" and start not in (0, None):
                    c["start"] = ms(start) if isinstance(start, (int, float)) else _sec(start)
                if dur not in (None, "forever") and c["type"] not in ("sound",):
                    c["duration"] = ms(dur) if isinstance(dur, (int, float)) else _sec(dur)
                if first and port is not None:
                    c["marker"] = self.marker(code or e["name"] or rid, port)
                first = False
                comps.append(c)
        # the response
        ttype = (tp.get("trial_type") or ["fixed"])[0]
        ends = ttype in ("first_response", "specific_response", "correct_response")
        if ends or resp_active:
            n_buttons = self.n_buttons
            r: dict[str, Any] = {"id": "resp", "type": "keyboard", "keys": [str(i) for i in range(1, n_buttons + 1)]}
            if target is not None:
                r["correct"] = str(target) if not (isinstance(target, str) and target.startswith("$")) else target
            if target_time not in (None, 0):
                r["start"] = ms(target_time) if isinstance(target_time, (int, float)) else _sec(target_time)
            if ends:
                r["end_routine"] = True
            if ttype in ("specific_response", "correct_response"):
                self.res.note("approx", where, f"trial_type {ttype}: the trial ends at the first button press")
            comps.append(r)
            if not self.button_note:
                self.button_note = True
                self.res.note("approx", "buttons", "Presentation's response buttons are mapped to keys in its "
                              "Settings, which are not part of the scenario: button 1 became the key '1', button 2 "
                              "the key '2' and so on. Change the keys of the 'resp' items to the keys you use")
        routine: dict[str, Any] = {"components": comps}
        td = t_ov.get("duration", (tp.get("trial_duration") or ["stimuli_length"])[0])
        if isinstance(td, Var):
            td = f"${td.name}"
        if isinstance(td, (int, float)):
            routine["duration"] = ms(td)
        elif isinstance(td, str) and td.startswith("$"):
            routine["duration"] = _sec(td)
        elif td == "forever" and not ends:
            routine["duration"] = 1.0
            self.res.note("approx", where, "trial_duration = forever without a response: set to 1 s")
        elif td == "stimuli_length" or td is None:
            ends_at = [(times[k] or 0) + (ms_or_0(evs[k]["p"].get("duration")) or 0) for k in range(len(evs))
                       if isinstance(times[k], (int, float))]
            if not ends:
                routine["duration"] = ms(max(ends_at or [1000]))
        if not comps:
            comps.append({"id": "blank", "type": "wait"})
        for k in tp:
            if k not in ("trial_duration", "trial_type", "all_responses", "code", "port_code", "time", "duration",
                         "target_button", "response_active", "picture_duration", "stimulus_event", "deltat",
                         "delta_time", "terminator_button"):
                self.res.note("approx", where, f"trial setting '{k}' not converted")
        if "terminator_button" in tp:
            self.res.note("approx", where, "terminator_button: any button ends the trial")
        self.routines[rid] = routine
        self.res.count("screens")
        return rid

    def marker(self, code: Any, port: Any) -> Any:
        label = code if code is not None else "event"
        if isinstance(port, (int, float)) and not (isinstance(label, str) and label.startswith("$")):
            return {"onset": str(label), "code": int(port)}
        if isinstance(port, (int, float)):
            return {"onset": label, "code": int(port)}
        # the port code comes from a trial-list column: one label per code, each with its code in settings
        col = str(port)[1:]
        base = re.sub(r"\W+", "_", str(label).lstrip("$")) or "event"
        self._pending_markers.append((base, col))
        return {"onset": f"$f'{base}_{{{col}}}'"}

    # ------------------------------------------------------------- flows without PCL
    def sdl_flow(self, stmts: list[dict[str, Any]], tvars: dict[str, Any] | None = None) -> list[Any]:
        flow: list[Any] = []
        for s in stmts:
            if s["kind"] == "def" and s["type"] == "trial":
                flow.append(self.trial_routine(s, s["name"] or "trial"))
            elif s["kind"] == "LOOP":
                inner = self.sdl_flow(s["body"])
                if len(inner) == 1 and isinstance(inner[0], dict) and "loop" in inner[0]:
                    inner[0]["repeats"] = inner[0].get("repeats", 1) * s["n"]
                    flow += inner
                elif inner:
                    flow.append({"loop": self.ids.make(f"loop_{s['var'].lstrip('$')}", "loop"),
                                 "conditions": [{s["var"].lstrip("$"): i + 1} for i in range(s["n"])],
                                 "order": "sequential", "children": inner})
                    self.res.count("trial lists")
            elif s["kind"] == "TEMPLATE":
                flow += self.template(s)
        return flow

    def template(self, s: dict[str, Any]) -> list[Any]:
        f = s["file"]
        where = f"line {s['line']}"
        if not isinstance(f, str):
            self.res.note("unsupported", where, "TEMPLATE without a file name")
            return []
        src = inside(self.path.parent, portable_path(f))
        if src is None or not src.is_file():
            self.res.note("unsupported", where, f"template file '{f}' was not found next to the scenario: copy it "
                          "there and import again" if src is not None else
                          f"template file '{f}' is outside the scenario's folder and was not read")
            return []
        if not s["rows"]:
            self.res.note("unsupported", where, f"TEMPLATE '{f}' has no table")
            return []
        cols = [str(c) for c in s["rows"][0]]
        rows = []
        for r in s["rows"][1:]:
            if len(r) != len(cols):
                self.res.note("approx", where, f"a TEMPLATE row has {len(r)} values for {len(cols)} columns: skipped")
                continue
            rows.append({ident(c): (v.name if isinstance(v, Var) else v) for c, v in zip(cols, r)})
        sp = SDL(tokens(strip_comments(read_text(src))), self.res, self.path.parent)
        body = sp.block(top=True)
        self.register(body)
        children = [self.trial_routine(t, t["name"] or Path(f).stem) for t in body if t["kind"] == "def" and t["type"] == "trial"]
        if not children:
            self.res.note("unsupported", where, f"template '{f}' defines no trial")
            return []
        self.res.count("trial lists")
        self.res.note("info", where, f"TEMPLATE '{f}' became a trial list with the columns {', '.join(rows[0]) if rows else '-'}"
                      " (the trials run in the order of the table, as in Presentation)")
        return [{"loop": self.ids.make("trials", "loop"), "conditions": rows, "order": "sequential",
                 "children": children}]

    # ------------------------------------------------------------- PCL
    def pcl(self, text: str, first_line_offset: int = 0) -> list[Any]:
        tree = pcl_tree(pcl_statements(text))
        self.arrays: dict[str, Arr] = {}
        self.shuffled: set[str] = set()
        self.pcl_notes: list[str] = []
        self.output_lines: list[int] = []
        self.ints: dict[str, Any] = {}
        return self.pcl_block(tree, None)

    def leftover(self, node: dict[str, Any]) -> None:
        if node["kind"] == "stmt":
            t = node["text"]
            if re.search(r"\boutput_file\b|^\w+\.(?:print|open|close|open_append)\(", t):
                self.output_lines.append(node["line"])
                return
            self.pcl_notes.append(f"line {node['line']}: {t[:160]}")
        elif node["kind"] == "loop":
            self.pcl_notes.append(f"line {node['line']}: loop {node['head'][4:].strip()[:120]} begin … end")
        elif node["kind"] == "if":
            self.pcl_notes.append(f"line {node['line']}: if {node['branches'][0][0][:120]} then … end")
        elif node["kind"] == "sub":
            self.pcl_notes.append(f"line {node['line']}: {node['head'][:120]} … end (a subroutine)")

    def pcl_block(self, nodes: list[dict[str, Any]], loop: dict[str, Any] | None) -> list[Any]:
        """Statements -> flow nodes. Inside a trial loop, ``loop`` holds the loop variable and the overrides."""
        out: list[Any] = []
        for n in nodes:
            if n["kind"] == "stmt":
                t = n["text"]
                m = re.fullmatch(r"array\s*<\s*(\w+)\s*>\s*(\w+)((?:\[\d+\])+)\s*=\s*(\{.*\})", t, re.S)
                if m:
                    arr = pcl_literal(m.group(4))
                    if arr is None:
                        self.leftover(n)
                    else:
                        self.arrays[m.group(2)] = arr
                    continue
                m = re.fullmatch(r"(\w+)\.shuffle\(\)", t)
                if m and m.group(1) in self.arrays:
                    self.shuffled.add(m.group(1))
                    continue
                m = re.fullmatch(r"(\w+)\.present\(\)", t)
                if m:
                    trial = self.objects.get(m.group(1))
                    if trial is None or trial["type"] != "trial":
                        self.res.note("unsupported", f"PCL line {n['line']}", f"'{m.group(1)}' is not a trial of the scenario")
                        continue
                    ov = loop["ov"] if loop else None
                    out.append(self.trial_routine(trial, m.group(1), ov))
                    continue
                m = re.fullmatch(r"(?:int|double)\s+(\w+)\s*=\s*(-?\d+(?:\.\d+)?)", t)
                if m and loop is None:
                    self.ints[m.group(1)] = num(m.group(2))
                    continue
                if loop is not None and self.loop_stmt(n, loop):
                    continue
                if re.fullmatch(r"\w+\.redraw\(\)|\w+\.load\(\)|\w+\.unload\(\)", t):
                    continue
                self.leftover(n)
            elif n["kind"] == "loop":
                node = self.pcl_loop(n, loop)
                if node is None:
                    self.leftover(n)
                else:
                    out.append(node)
            elif n["kind"] == "if":
                conv = self.pcl_if(n, loop)
                if conv is None:
                    self.leftover(n)
                else:
                    out += conv
            else:
                self.leftover(n)
        return out

    def pcl_if(self, n: dict[str, Any], loop: dict[str, Any] | None) -> list[Any] | None:
        conds = []
        for cond, body, _ in n["branches"]:
            if cond is None:
                conds.append(None)
                continue
            c = re.sub(r"\s+", "", cond)
            m = re.fullmatch(r"(\w+)\.type\(\)==stimulus_(hit|incorrect|miss|false_alarm|other)", c)
            m2 = re.fullmatch(r"response_manager\.last_response\(\)==(\d+)", c)
            m3 = re.fullmatch(r"response_manager\.hits\(\)>0|stimulus_manager\.last_stimulus_data\(\)\.type\(\)==stimulus_hit", c)
            if m:
                conds.append({"hit": "$resp.corr == 1", "incorrect": "$resp.keys is not None and not resp.corr",
                              "miss": "$resp.keys is None", "false_alarm": "$resp.keys is not None and not resp.corr",
                              "other": "$resp.keys is not None"}[m.group(2)])
            elif m2:
                conds.append(f"$resp.keys == {m2.group(1)!r}")
            elif m3:
                conds.append("$resp.corr == 1")
            else:
                return None
        out: list[Any] = []
        taken: list[str] = []
        for (cond, body, ln), c in zip(n["branches"], conds):
            expr_c = c if c else ("$not (" + " or ".join(x[1:] for x in taken) + ")" if taken else None)
            if c:
                taken.append(c)
            for x in body:
                if x["kind"] == "stmt" and re.fullmatch(r"(\w+)\.present\(\)", x["text"]):
                    sub = self.pcl_block([x], loop)
                    out += [{"routine": r, "if": expr_c} if expr_c else r for r in sub]
                else:
                    self.leftover(x)
        return out

    def loop_stmt(self, n: dict[str, Any], loop: dict[str, Any]) -> bool:
        t = n["text"]
        var = loop["var"]
        m = re.fullmatch(rf"{var}\s*=\s*{var}\s*\+\s*1", t)
        if m:
            return True
        if re.fullmatch(r"stimulus_data\s+\w+\s*=\s*stimulus_manager\.last_stimulus_data\(\)", t):
            return True                        # read by the 'if last.type() == stimulus_hit' check
        m = re.fullmatch(r"(?:int|double|string|rgb_color)\s+(\w+)\s*=\s*(.+)", t)
        if m and self.column(m.group(2), loop, m.group(1), register=False) is not None:
            loop["aliases"][m.group(1)] = f"({m.group(2)})"
            return True
        m = re.fullmatch(r"(\w+)\.(set_caption|set_font_color|set_filename|set_target_button|set_port_code|"
                         r"set_event_code|set_duration|set_time)\((.*)\)", t)
        if not m:
            return False
        obj, meth, arg = m.group(1), m.group(2), m.group(3)
        arg = re.sub(r",\s*(true|false)\s*$", "", arg)          # set_caption(x, true) redraws
        if meth == "set_duration" and re.fullmatch(r"random\(\s*(\d+)\s*,\s*(\d+)\s*\)", arg):
            a, b = re.fullmatch(r"random\(\s*(\d+)\s*,\s*(\d+)\s*\)", arg).groups()
            val: Any = f"$random.randint({a}, {b})"          # ms, as every duration here
        elif meth == "set_font_color" and re.fullmatch(r"\d+\s*,\s*\d+\s*,\s*\d+.*", arg):
            val = "#%02x%02x%02x" % tuple(int(x) for x in re.findall(r"\d+", arg)[:3])
        else:
            val = self.column(arg, loop, {"set_caption": obj, "set_font_color": f"{obj}_color",
                                          "set_filename": obj, "set_target_button": "target_button",
                                          "set_port_code": "port_code", "set_event_code": "event_code",
                                          "set_duration": f"{obj}_duration", "set_time": f"{obj}_time"}[meth])
            if val is None:
                return False
        target = self.objects.get(obj)
        kind = target["type"] if target else None
        ov = loop["ov"]
        if meth in ("set_caption", "set_font_color", "set_filename"):
            if kind not in ("text", "bitmap", "wavefile"):
                return False
            prop = {"set_caption": "text", "set_font_color": "color"}.get(meth) or \
                ("image" if kind == "bitmap" else "sound")
            ov["objects"].setdefault(obj, {})[prop] = val
            if meth == "set_filename":
                self.file_columns.add(str(val)[1:] if str(val).startswith("$") else "")
        elif meth in ("set_target_button", "set_port_code", "set_event_code", "set_time") or \
                (meth == "set_duration" and kind == "stimulus_event"):
            if kind != "stimulus_event":
                return False
            prop = {"set_target_button": "target_button", "set_port_code": "port_code", "set_event_code": "code",
                    "set_duration": "duration", "set_time": "time"}[meth]
            ov["events"].setdefault(obj, {})[prop] = val
        elif meth == "set_duration" and kind == "trial":
            ov["trial"].setdefault(obj, {})["duration"] = val
        else:
            return False
        return True

    def column(self, src: str, loop: dict[str, Any], name: str, register: bool = True) -> Any:
        """A PCL expression evaluated for every iteration of the loop: a constant, or a new trial-list column."""
        e = src
        for a, rep in sorted(loop["aliases"].items(), key=lambda kv: -len(kv[0])):
            e = re.sub(rf"\b{re.escape(a)}\b", rep, e)
        e = re.sub(r"(\w+)\.count\(\)", r"len_\1", e)
        names: dict[str, Any] = dict(self.arrays)
        names.update(self.ints)
        names.update({f"len_{k}": len(v) for k, v in self.arrays.items()})
        vals = []
        try:
            for i in range(1, loop["n"] + 1):
                vals.append(pcl_value(e, {**names, loop["var"]: i}))
        except (KeyError, IndexError, SyntaxError, TypeError, ValueError, ZeroDivisionError):
            return None
        if len(set(map(repr, vals))) == 1 and loop["var"] not in re.findall(r"\w+", e):
            return vals[0]
        if not register:
            return vals
        refs = re.findall(r"[A-Za-z_]\w*", src)
        base = next((r for r in refs if r in self.arrays), name)
        col = ident(base)
        if col in loop["columns"] and loop["columns"][col] != vals:
            col = ident(name)
            k = 2
            while col in loop["columns"] and loop["columns"][col] != vals:
                col, k = f"{ident(name)}_{k}", k + 1
        loop["columns"][col] = vals
        if any(a in self.shuffled for a in re.findall(r"[A-Za-z_]\w*", e)):
            loop["shuffled"] = True
        return f"${col}"

    def pcl_loop(self, n: dict[str, Any], outer: dict[str, Any] | None) -> dict[str, Any] | None:
        head = n["head"]
        m = re.fullmatch(r"loop\s+(?:int\s+)?(\w+)\s*=\s*(\d+)\s+until\s+(\w+)\s*>\s*(.+)", head)
        if not m or m.group(1) != m.group(3) or int(m.group(2)) != 1:
            m2 = re.fullmatch(r"loop\s+(?:int\s+)?(\w+)\s*=\s*(\d+)\s+until\s+(\w+)\s*(>=|==)\s*(.+)", head)
            if not m2:
                return None
            start, limit_src = int(m2.group(2)), m2.group(5)
            var = m2.group(1)
            shift = 0 if m2.group(4) == ">=" else 1
        else:
            var, start, limit_src, shift = m.group(1), 1, m.group(4), 1
        try:
            limit = pcl_value(re.sub(r"(\w+)\.count\(\)", r"len_\1", limit_src),
                              {**self.arrays, **self.ints, **{f"len_{k}": len(v) for k, v in self.arrays.items()}})
        except (KeyError, IndexError, SyntaxError, TypeError, ValueError):
            return None
        if not isinstance(limit, int):
            return None
        count = limit - start + shift
        if count <= 0:
            return None
        if outer is not None:      # a loop inside the trial loop (e.g. blocks of trials): kept as repeats
            body = self.pcl_block(n["body"], outer)
            self.res.count("trial lists")
            return {"loop": self.ids.make(f"repeat_{var}", "loop"), "conditions": [{}], "repeats": count,
                    "order": "sequential", "children": body}
        loop: dict[str, Any] = {"var": var, "n": count, "aliases": {}, "columns": {}, "shuffled": False,
                                "ov": {"objects": {}, "events": {}, "trial": {}}}
        if start != 1:
            loop["aliases"][var] = f"({var} + {start - 1})"
        children = self.pcl_block(n["body"], loop)
        if not children:
            return None
        rows = [{c: v[i] for c, v in loop["columns"].items()} for i in range(count)] if loop["columns"] else \
            [{} for _ in range(count)]
        repeats = 1
        for k in range(1, len(rows) + 1):          # the same rows k times over -> k repeats
            if len(rows) % k == 0 and rows[: len(rows) // k] * k == rows:
                repeats, base_rows = k, rows[: len(rows) // k]
        if repeats > 1:
            rows = base_rows
        node: dict[str, Any] = {"loop": self.ids.make("trials", "loop"), "conditions": rows,
                                "order": "random" if loop["shuffled"] else "sequential", "children": children}
        if repeats > 1:
            node["repeats"] = repeats
        for c in self.file_columns:
            for r in rows:
                v = r.get(c)
                if isinstance(v, str) and v:
                    self.res.assets.add(portable_path(v))
        for base, col in self._pending_markers:
            for r in rows:
                if r.get(col) is not None:
                    self.marker_codes[f"{base}_{r[col]}"] = int(r[col])
        self._pending_markers.clear()
        self.res.count("trial lists")
        self.res.note("info", f"PCL line {n['line']}", f"the PCL loop over {count} trials became a trial list"
                      + (f" with the columns {', '.join(loop['columns'])}" if loop["columns"] else "")
                      + (" in random order (the array was shuffled)" if loop["shuffled"] else ""))
        return node

    # ------------------------------------------------------------- whole scenario
    def run(self) -> ImportResult:
        res = self.res
        header, stmts, pcl_inline = self.read()
        self.register(stmts)
        self.n_buttons = int(num((header.get("active_buttons") or [0])[0]) or 0)
        if not self.n_buttons:
            self.n_buttons = max([len(header.get("button_codes") or [])] + [2])
        pcl_file = (header.get("pcl_file") or [None])[0]
        flow: list[Any]
        if pcl_file or pcl_inline:
            text = pcl_inline
            if pcl_file:
                src = inside(self.path.parent, portable_path(str(pcl_file)))
                if src is None or not src.is_file():
                    res.note("unsupported", "pcl_file", f"the PCL program '{pcl_file}' was not found next to the "
                             "scenario (or is outside its folder): copy it there and import again. The scenario's "
                             "trials were imported in the order they are written")
                    text = None
                else:
                    text = read_text(src)
            if text is not None:
                res.note("info", "PCL", "the PCL program was translated where it follows common patterns (arrays, "
                         "shuffle, a loop over the trials, set_caption/set_target_button…, present(), checks of the "
                         "last response); the rest is listed below with line numbers. Code translation is partial: "
                         "compare the result with the original")
                self.used_pcl = True
                flow = self.pcl(text)
                if self.pcl_notes:
                    res.note("unsupported", "PCL", "PCL statements not converted (do these by hand, e.g. with a "
                             "variable item, a component condition or a workflow):\n\n```\n"
                             + "\n".join(self.pcl_notes) + "\n```")
                if self.output_lines:
                    res.note("info", "PCL", "writing an output file (lines " + ", ".join(map(str, sorted(set(self.output_lines))))
                             + ") is not needed: EDGE saves every response, RT, correctness and trial-list column")
            else:
                flow = self.sdl_flow(stmts)
        else:
            flow = self.sdl_flow(stmts)
            if flow:
                res.note("info", "scenario", "without a PCL program, the trials run in the order they are written "
                         "in the scenario")
        if not flow:
            res.note("unsupported", "flow", "the PCL program presents no trial of the scenario (it may be cut short)"
                     if (pcl_file or pcl_inline) and self.used_pcl else "no trial was found in the scenario")
        bg = rgb(header.get("default_background_color") or [0, 0, 0]) or "#000000"
        fg = rgb(header.get("default_text_color") or [255, 255, 255]) or "#ffffff"
        size = (header.get("default_font_size") or [18])[0]
        for r in self.routines.values():
            for c in r["components"]:
                if c["type"] == "text":
                    c.setdefault("color", fg)
                    c.setdefault("height", size if isinstance(size, (int, float)) else 18)
        known = {"scenario", "pcl_file", "scenario_type", "response_matching", "active_buttons", "button_codes",
                 "target_button_codes", "response_logging", "write_codes", "pulse_width", "default_background_color",
                 "default_font", "default_font_size", "default_text_color", "default_formatted_text",
                 "no_logfile", "default_output_port", "screen_width", "screen_height", "screen_bit_depth"}
        if header.get("write_codes") and (header["write_codes"][0] in ("true", True)):
            res.note("info", "port codes", "port_code values became markers, sent to every TTL/LSL device you add "
                     "under Devices")
        if "target_button_codes" in header or "button_codes" in header:
            res.note("info", "button codes", "button_codes/target_button_codes (log-file codes) are not needed: "
                     "EDGE saves the key, RT and correctness of every response")
        for k in header:
            if k not in known:
                res.note("approx", "header", f"header parameter '{k}' not converted")
        settings: dict[str, Any] = {"window": {"size": [W, H], "background": bg, "units": "px"}}
        sw, sh = (header.get("screen_width") or [None])[0], (header.get("screen_height") or [None])[0]
        if isinstance(sw, int) and isinstance(sh, int):
            settings["window"]["size"] = [sw, sh]
        if self.marker_codes:
            settings["markers"] = {"codes": dict(sorted(self.marker_codes.items()))}
        res.doc = {"name": ident(self.path.stem),
                   "description": f"Imported from Presentation ({self.path.name})", "settings": settings,
                   "devices": [], "variables": {}, "routines": self.routines, "flow": flow}
        avoid_column_clashes(res.doc)
        return res


def _sec(v: Any) -> Any:
    s = str(v)
    return f"$({s[1:]}) / 1000" if s.startswith("$") else v


def ms_or_0(v: Any) -> Any:
    if not v:
        return 0
    x = v[0]
    return x if isinstance(x, (int, float)) else 0


def import_presentation(path: Path) -> ImportResult:
    if path.suffix.lower() == ".pcl":
        scen = _scenario_of(path)
        if scen is None:
            raise ImportError_(f"{path.name} is a PCL program: import the scenario (.sce) that names it with "
                               f"pcl_file = \"{path.name}\", in the same folder")
        res = Converter(scen).run()
        res.note("info", "source", f"imported through its scenario {scen.name}")
        return res
    return Converter(path).run()


def _scenario_of(pcl: Path) -> Path | None:
    for sce in sorted(pcl.parent.glob("*.sce")):
        try:
            head = read_text(sce)[:20000]
        except OSError:
            continue
        m = re.search(r'pcl_file\s*=\s*"([^"]+)"', head)
        if m and Path(portable_path(m.group(1))).name.lower() == pcl.name.lower():
            return sce
    return None


def looks_like_presentation(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in (".sce", ".pcl"):
        return False
    try:
        text = read_text(path)[:200000]
    except OSError:
        return False
    if suffix == ".sce":
        return True
    return bool(re.search(r"\.present\s*\(|\barray\s*<|\bloop\b.*\buntil\b|stimulus_manager|response_manager", text))
