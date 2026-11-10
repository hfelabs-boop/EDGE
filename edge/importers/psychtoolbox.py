"""Psychtoolbox importer (MATLAB ``.m`` scripts) — a PARTIAL translation of common patterns.

A Psychtoolbox experiment is a program, not a description, so only recognisable patterns are translated:

* ``Screen('OpenWindow')`` / ``PsychImaging('OpenWindow', …, colour)`` -> background; ``Screen('TextSize')``;
* ``DrawFormattedText`` / ``Screen('DrawText')`` / ``Screen('DrawTexture')`` (``imread`` + ``MakeTexture``) /
  ``Screen('DrawLines')`` (a fixation cross), followed by ``Screen('Flip')`` -> one screen with those items;
* ``WaitSecs`` after a flip -> the screen's duration; ``KbStrokeWait``/``KbWait`` -> wait for a key;
  ``while`` loops polling ``KbCheck`` with ``keyCode(KbName(...))`` and a time limit, and
  ``KbQueueStart``/``KbQueueCheck`` -> a keyboard item with the keys and the time limit;
* ``PsychPortAudio('Start')`` of a buffer filled from ``audioread('file.wav')`` -> a sound item;
* a ``for`` loop over a condition matrix (``[1 1; 1 2; …]``, ``repmat``, ``Shuffle``/``randperm``) or over the
  rows of ``readtable``/``csvread`` -> a trial list (columns named after the variables they are read into, with
  values looked up in cell arrays and colour matrices), random when shuffled;
* ``correct = response == colorNum`` / ``strcmp(KbName(key), T.correct_key{row})`` -> the correct answer;
* the results matrix, ``save``/``writetable``/``fprintf`` -> not needed (EDGE saves every response).

Everything else is listed in the report with its line number.
"""

from __future__ import annotations

import csv
import io
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
    key_name,
    num,
    portable_path,
    read_text,
)

W, H = 1024, 768
SETUP = re.compile(r"^(?:sca|clc|clear\b.*|close\s+all|commandwindow|HideCursor.*|ShowCursor.*|ListenChar.*|Priority\(.*|"
                   r"PsychDefaultSetup\(.*|AssertOpenGL.*|InitializePsychSound.*|KbName\('UnifyKeyNames'\)|"
                   r"Screen\('Preference'.*|Screen\('BlendFunction'.*|Screen\('TextFont'.*|Screen\('TextStyle'.*|"
                   r"Screen\('Close'.*|Screen\('CloseAll'\)|KbQueueRelease.*|KbQueueFlush.*|KbQueueCreate.*|"
                   r"KbReleaseWait.*|PsychPortAudio\('(?:Close|Stop)'.*|rng\(.*|rand\('(?:seed|state)'.*|"
                   r"RandStream.*|warning\(.*|format\b.*|return|rethrow\(.*|"
                   r"\w+\s*=\s*(?:Screen\('Screens'\)|max\(.*\)|"
                   r"Screen\('GetFlipInterval'.*|MaxPriority\(.*|GetSecs|Screen\('WindowSize'.*)|"
                   r"\[\w+\s*,\s*\w+\]\s*=\s*(?:RectCenter|Screen\('WindowSize').*|"
                   r"\w+\s*=\s*zeros\(1,\s*256\))$")
RESULTS = re.compile(r"^(?:save\b.*|save\(.*|writetable\(.*|writematrix\(.*|csvwrite\(.*|dlmwrite\(.*|fprintf\(\s*\w+.*|"
                     r"fclose\(.*|\w+\s*=\s*fopen\(.*|\w+\s*=\s*(?:nan|zeros|NaN|cell)\(.*|\w+\(\w+\s*,\s*[:\d]+\)\s*=.*|"
                     r"\w+\{\w+\s*,\s*[:\d]+\}\s*=.*|\w+\(\w+\)\.\w+\s*=.*|\w+\.\w+\(\w+\)\s*=.*)$")


# ------------------------------------------------------------------ reading MATLAB
def statements(text: str) -> list[tuple[str, int]]:
    """MATLAB source -> statements (text, line): comments removed, '...' continuations joined, split at ; and newlines
    outside brackets and strings."""
    text = re.sub(r"(?ms)^\s*%\{.*?^\s*%\}", lambda m: "\n" * m.group(0).count("\n"), text)
    out: list[tuple[str, int]] = []
    cur, line, depth, q = "", 1, 0, None
    start = 1
    i = 0
    prev = ""
    while i < len(text):
        ch = text[i]
        if q:
            cur += ch
            if ch == q:
                if i + 1 < len(text) and text[i + 1] == q:
                    cur += q
                    i += 2
                    continue
                q = None
            elif ch == "\n":            # an unclosed string ends at the line end
                q = None
                line += 1
            i += 1
            prev = ch
            continue
        if ch == "%":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if text.startswith("...", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            i += 1
            line += 1
            cur += " "
            continue
        if ch in "'\"" and (ch == '"' or not re.match(r"[\w)\]}.']", prev or " ")):
            q = ch
            cur += ch
            i += 1
            prev = ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "\n" or (ch in ";," and depth == 0):
            if ch == "," and not re.match(r"\s*(?:if|for|while|elseif|switch|case)\b", cur):
                cur += ch          # a comma between statements is rare outside 'if x, y'; keep it
            else:
                if cur.strip():
                    out.append((cur.strip(), start))
                cur = ""
            if ch == "\n":
                line += 1
            if not cur.strip():
                start = line
            i += 1
            prev = ch if ch != "\n" else ""
            continue
        if not cur.strip():
            start = line
        cur += ch
        if not ch.isspace():
            prev = ch
        i += 1
    if cur.strip():
        out.append((cur.strip(), start))
    return out


BLOCK = re.compile(r"^(for|while|if|switch|try|function|parfor)\b")


def tree(stmts: list[tuple[str, int]]) -> list[dict[str, Any]]:
    pos = 0

    def parse(stops: tuple[str, ...]) -> list[dict[str, Any]]:
        nonlocal pos
        out: list[dict[str, Any]] = []
        while pos < len(stmts):
            s, ln = stmts[pos]
            word = re.match(r"\w*", s).group(0)
            if word in stops:
                return out
            pos += 1
            m = BLOCK.match(s)
            if m:
                kind = m.group(1)
                if kind == "if":
                    branches = [(s[2:].strip().rstrip(","), parse(("elseif", "else", "end")), ln)]
                    while pos < len(stmts) and re.match(r"elseif\b", stmts[pos][0]):
                        cs, cl = stmts[pos]
                        pos += 1
                        branches.append((cs[6:].strip().rstrip(","), parse(("elseif", "else", "end")), cl))
                    if pos < len(stmts) and re.match(r"else\b", stmts[pos][0]):
                        pos += 1
                        branches.append((None, parse(("end",)), stmts[pos - 1][1]))
                    pos += 1
                    out.append({"kind": "if", "branches": branches, "line": ln})
                elif kind == "try":
                    body = parse(("catch", "end"))
                    catch: list[dict[str, Any]] = []
                    if pos < len(stmts) and re.match(r"catch\b", stmts[pos][0]):
                        pos += 1
                        catch = parse(("end",))
                    pos += 1
                    out.append({"kind": "try", "body": body, "catch": catch, "line": ln})
                elif kind == "switch":
                    depth_body = parse(("end",))
                    pos += 1
                    out.append({"kind": "switch", "head": s, "body": depth_body, "line": ln})
                elif kind == "function":
                    body = parse(("end", "function"))
                    if pos < len(stmts) and stmts[pos][0] == "end":
                        pos += 1
                    out.append({"kind": "function", "head": s, "body": body, "line": ln})
                else:
                    body = parse(("end",))
                    pos += 1
                    out.append({"kind": kind if kind != "parfor" else "for", "head": s, "body": body, "line": ln})
            else:
                out.append({"kind": "stmt", "text": s, "line": ln})
        return out

    return parse(())


def mstring(s: str) -> str | None:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        body = s[1:-1].replace("''", "'") if s[0] == "'" else s[1:-1].replace('""', '"')
        return body.replace("\\n", "\n")
    return None


def split_args(s: str) -> list[str]:
    out, cur, depth, q = [], "", 0, None
    for i, ch in enumerate(s):
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"" and (ch == '"' or not re.match(r"[\w)\]}.']", cur.rstrip()[-1:] or " ")):
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def matrix(s: str) -> list[list[Any]] | None:
    """'[1 1; 2 2]' -> [[1, 1], [2, 2]]; numbers only (and true/false)."""
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    rows = []
    for r in re.split(r";|\n", s[1:-1]):
        if not r.strip():
            continue
        vals = [num(x) for x in re.split(r"[\s,]+", r.strip()) if x]
        if not all(isinstance(v, (int, float)) for v in vals):
            return None
        rows.append(vals)
    return rows


def cell(s: str) -> list[Any] | None:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    items = []
    for part in split_args(s[1:-1].replace(";", ",")):
        for p in (part.split() if mstring(part) is None and " " in part.strip() else [part]):
            v = mstring(p)
            if v is None:
                n = num(p)
                if not isinstance(n, (int, float)):
                    return None
                v = n
            items.append(v)
    return items


# ------------------------------------------------------------------ the converter
class Converter:
    def __init__(self, path: Path):
        self.path = path
        self.res = ImportResult({}, path, "Psychtoolbox (MATLAB, partial translation)")
        self.ids = Ids()
        self.routines: dict[str, Any] = {}
        self.vars: dict[str, Any] = {}          # literals: numbers, strings, cells, matrices
        self.keys: dict[str, str] = {}          # keyVar -> EDGE key name
        self.mats: dict[str, dict[str, Any]] = {}
        self.tables: dict[str, dict[str, Any]] = {}
        self.perms: dict[str, dict[str, Any]] = {}
        self.sounds: dict[str, str] = {}        # audio buffer / pahandle -> file
        self.images: dict[str, Any] = {}        # image / texture var -> file or $column
        self.scale = 255
        self.background = "#000000"
        self.text_height = 32
        self.left: list[str] = []
        self.results_lines: list[int] = []
        self.setup_lines = 0
        self.key_values: dict[str, Any] = {}    # key -> value of 'response = N'
        self.window: str | None = None

    def skip(self, n: dict[str, Any]) -> None:
        if n["kind"] == "stmt":
            self.left.append(f"line {n['line']}: {n['text'][:150]}")
        else:
            head = n.get("head") or (f"if {n['branches'][0][0]}" if n["kind"] == "if" else n["kind"])
            self.left.append(f"line {n['line']}: {head[:120]} … end")

    # ------------------------------------------------------------- values
    def color(self, s: str, ctx: dict[str, Any] | None = None) -> Any:
        s = s.strip()
        if ctx and s in ctx["cols"]:
            return f"${ctx['cols'][s]}"
        if s in self.vars and isinstance(self.vars[s], str) and self.vars[s].startswith("#"):
            return self.vars[s]
        m = matrix(s) if s.startswith("[") else None
        if m is None and s in self.vars and isinstance(self.vars[s], list):
            m = [self.vars[s]] if not isinstance(self.vars[s][0], list) else None
        if m and len(m) == 1 and len(m[0]) in (1, 3, 4):
            vals = m[0] * 3 if len(m[0]) == 1 else m[0][:3]
            return self.rgb(vals)
        n = self.number(s)
        if isinstance(n, (int, float)):
            return self.rgb([n, n, n])
        return None

    def rgb(self, vals: list[Any]) -> str:
        scale = 255 if (self.scale == 1 and max(vals) <= 1) else 1
        return "#%02x%02x%02x" % tuple(max(0, min(255, round(float(v) * scale))) for v in vals[:3])

    def number(self, s: str) -> Any:
        s = s.strip()
        n = num(s)
        if isinstance(n, (int, float)):
            return n
        if s in self.vars and isinstance(self.vars[s], (int, float)):
            return self.vars[s]
        m = re.fullmatch(r"(\w+)\s*([*/+-])\s*(\w+(?:\.\d+)?)", s)
        if m:
            a, b = self.number(m.group(1)), self.number(m.group(3))
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return {"*": a * b, "/": a / b if b else None, "+": a + b, "-": a - b}[m.group(2)]
        m = re.fullmatch(r"(?:size\((\w+)\s*,\s*1\)|length\((\w+)\)|numel\((\w+)\)|height\((\w+)\))", s)
        if m:
            name = next(g for g in m.groups() if g)
            if name in self.mats:
                return len(self.mats[name]["rows"]) * self.mats[name]["repeats"]
            if name in self.tables:
                return len(self.tables[name]["rows"])
            if name in self.perms:
                return self.perms[name]["n"]
            if isinstance(self.vars.get(name), list):
                return len(self.vars[name])
        return None

    # ------------------------------------------------------------- top-level statements
    def assign(self, s: str, line: int) -> bool:
        """Remember values and recognisable set-up; True when the statement needs no screen."""
        m = re.fullmatch(r"(\w+)\s*=\s*(.+)", s, re.S)
        lhs, rhs = (m.group(1), m.group(2).strip()) if m else (None, None)
        if re.fullmatch(r"PsychDefaultSetup\(\s*2\s*\)", s):
            self.scale = 1
        cm = re.fullmatch(r"(\w+)\s*=\s*(White|Black|Gray|Grey)Index\(.*\)", s)
        if cm:
            self.vars[cm.group(1)] = {"White": "#ffffff", "Black": "#000000"}.get(cm.group(2), "#808080")
            self.setup_lines += 1
            return True
        am = re.fullmatch(r"\[\s*(\w+)\s*,\s*\w+\s*\]\s*=\s*audioread\(\s*'([^']+)'\s*\)", s) or \
            re.fullmatch(r"(\w+)\s*=\s*audioread\(\s*'([^']+)'\s*\)", s)
        if am:
            self.sounds[am.group(1)] = portable_path(am.group(2))
            return True
        if SETUP.match(s):
            self.setup_lines += 1
            return True
        if RESULTS.match(s):
            self.results_lines.append(line)
            return True
        om = re.search(r"(?:Screen|PsychImaging)\(\s*'OpenWindow'\s*,([^;]*)\)", s)
        if om:
            if "PsychImaging" in s:
                self.scale = 1
            args = split_args(om.group(1))
            if len(args) > 1:
                c = self.color(args[1]) if args[1] not in ("[]",) else None
                if isinstance(c, str) and c.startswith("#"):
                    self.background = c
                elif args[1].strip() in ("white", "black", "grey", "gray"):
                    self.background = {"white": "#ffffff", "black": "#000000"}.get(args[1].strip(), "#808080")
            wm = re.match(r"\[?\s*(\w+)", s)
            self.window = wm.group(1) if wm else None
            if len(args) > 2 and matrix(args[2]):
                r = matrix(args[2])[0]
                if len(r) == 4:
                    self.size = [int(r[2] - r[0]), int(r[3] - r[1])]
            return True
        tm = re.fullmatch(r"Screen\(\s*'TextSize'\s*,\s*\w+\s*,\s*(.+)\)", s)
        if tm and isinstance(self.number(tm.group(1)), (int, float)):
            self.text_height = self.number(tm.group(1))
            return True
        if lhs is None:
            if re.fullmatch(r"(\w+)\(\[([\w\s,]+)\]\)\s*=\s*1", s):      # keysOfInterest([a b]) = 1
                km = re.fullmatch(r"(\w+)\(\[([\w\s,]+)\]\)\s*=\s*1", s)
                self.vars[f"_keys_{km.group(1)}"] = [k for k in re.split(r"[\s,]+", km.group(2)) if k]
                return True
            pm = re.fullmatch(r"PsychPortAudio\(\s*'FillBuffer'\s*,\s*(\w+)\s*,\s*(\w+)'?.*\)", s)
            if pm and pm.group(2) in self.sounds:
                self.sounds[pm.group(1)] = self.sounds[pm.group(2)]
                return True
            return False
        km = re.fullmatch(r"KbName\(\s*'([^']+)'\s*\)", rhs)
        if km:
            self.keys[lhs] = key_name(km.group(1))
            return True
        if re.fullmatch(r"PsychPortAudio\(\s*'Open'.*\)", rhs):
            self.sounds.setdefault(lhs, "")
            return True
        rt = re.fullmatch(r"(readtable|readmatrix|csvread|dlmread|xlsread|readcell)\(\s*'([^']+)'.*\)", rhs)
        if rt:
            self.read_table(lhs, rt.group(1), portable_path(rt.group(2)), line)
            return True
        v = mstring(rhs)
        if v is not None:
            self.vars[lhs] = v
            return True
        c = cell(rhs)
        if c is not None:
            self.vars[lhs] = c
            return True
        mx = matrix(rhs)
        if mx is not None:
            if len(mx) == 1:
                self.vars[lhs] = mx[0]
            else:
                self.mats[lhs] = {"rows": mx, "repeats": 1, "shuffled": False, "line": line}
                self.vars[lhs] = mx
            return True
        n = self.number(rhs)
        if isinstance(n, (int, float)):
            self.vars[lhs] = n
            return True
        if rhs.lower() in ("true", "false", "nan", "[]", "{}"):
            return True
        rm = re.fullmatch(r"repmat\(\s*(\w+)\s*,\s*(\w+)\s*,\s*1\s*\)", rhs)
        if rm and rm.group(1) in self.mats and isinstance(self.number(rm.group(2)), int):
            base = self.mats[rm.group(1)]
            self.mats[lhs] = {**base, "repeats": base["repeats"] * self.number(rm.group(2))}
            return True
        pm = re.fullmatch(r"(?:Shuffle\(\s*1\s*:\s*(.+)\)|randperm\(\s*(.+)\))", rhs)
        if pm:
            n = self.number(pm.group(1) or pm.group(2))
            if isinstance(n, int):
                self.perms[lhs] = {"n": n, "shuffled": True}
                return True
        sm = re.fullmatch(r"(\w+)\(\s*(\w+)\s*,\s*:\s*\)", rhs)
        if sm and sm.group(1) in self.mats and sm.group(2) in self.perms:
            self.mats[lhs] = {**self.mats[sm.group(1)], "shuffled": True}
            return True
        sm = re.fullmatch(r"Shuffle\(\s*(\w+)\s*\)", rhs)
        if sm and sm.group(1) in self.mats:
            self.mats[lhs] = {**self.mats[sm.group(1)], "shuffled": True}
            self.res.note("approx", f"line {line}", "Shuffle() of a matrix shuffles each column separately in MATLAB; "
                          "it was converted to a shuffled order of the rows")
            return True
        if re.fullmatch(r"input\(.*\)", rhs):
            self.res.note("info", f"line {line}", f"input() for '{lhs}': EDGE asks for the participant and session at "
                          "the start of each session")
            return True
        return False

    def read_table(self, name: str, how: str, rel: str, line: int) -> None:
        src = inside(self.path.parent, rel)
        if src is None or not src.is_file():
            self.res.note("unsupported", f"line {line}", f"{how}('{rel}'): the file was not found next to the script"
                          " (or is outside its folder): copy it there and import again")
            self.tables[name] = {"rows": [], "file": rel, "header": False}
            return
        if src.suffix.lower() in (".xlsx", ".xls"):
            from ..conditions import load_conditions
            try:
                rows = load_conditions(src.name, src.parent)
            except Exception as e:
                self.res.note("unsupported", f"line {line}", f"{rel} could not be read: {e}")
                rows = []
            self.tables[name] = {"rows": rows, "file": rel, "header": True}
            return
        text = read_text(src)
        delim = "\t" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else ","
        cells = [r for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim) if any(c.strip() for c in r)]
        if how in ("readtable", "readcell") and cells:
            header = [ident(h.strip()) for h in cells[0]]
            rows = [{h: num(v.strip()) for h, v in zip(header, r)} for r in cells[1:]]
            self.tables[name] = {"rows": rows, "file": rel, "header": True}
        else:
            mx = [[num(v.strip()) for v in r] for r in cells]
            self.mats[name] = {"rows": mx, "repeats": 1, "shuffled": False, "line": line}
            self.res.note("info", f"line {line}", f"{how}('{rel}') read as a condition matrix ({len(mx)} rows)")

    # ------------------------------------------------------------- screens
    def new_ctx(self) -> dict[str, Any]:
        return {"cols": {}, "pending": [], "screens": [], "cur": None, "rowcols": {}, "pending_if": None}

    def screen_stmt(self, n: dict[str, Any], ctx: dict[str, Any]) -> bool:
        """Drawing, flipping, waiting and responses; True when the statement was used."""
        s = n["text"]
        line = n["line"]
        dm = re.fullmatch(r"(?:\[[^\]]*\]\s*=\s*)?DrawFormattedText\((.*)\)", s, re.S)
        if dm:
            args = split_args(dm.group(1))
            text = self.text_value(args[1] if len(args) > 1 else "''", ctx)
            if text is None:
                self.skip(n)
                return True
            c: dict[str, Any] = {"type": "text", "text": text, "height": self.text_height,
                                 "wrap_width": round(W * 0.9)}
            if len(args) > 4:
                col = self.color(args[4], ctx)
                if col:
                    c["color"] = col
            else:
                c["color"] = "white" if self.background in ("#000000",) else "black"
            if len(args) > 3 and not (mstring(args[2]) == "center" and mstring(args[3]) == "center"):
                if mstring(args[2]) not in ("center", None) or mstring(args[3]) not in ("center", None) or \
                        args[2].strip() not in ("xCenter", "'center'"):
                    self.res.note("approx", f"line {line}", "text position converted to the centre of the screen")
            ctx["pending"].append(c)
            return True
        tm = re.fullmatch(r"Screen\(\s*'DrawText'\s*,\s*\w+\s*,(.*)\)", s, re.S)
        if tm:
            args = split_args(tm.group(1))
            text = self.text_value(args[0], ctx)
            c = {"type": "text", "text": text, "height": self.text_height}
            if len(args) > 3:
                col = self.color(args[3], ctx)
                if col:
                    c["color"] = col
            x, y = (self.number(args[1]), self.number(args[2])) if len(args) > 2 else (None, None)
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                c["pos"] = [round(x - W / 2), round(H / 2 - y)]
                self.res.note("approx", f"line {line}", "DrawText positions the text's top-left corner; EDGE centres "
                              "text on its position: check it")
            ctx["pending"].append(c)
            return True
        xm = re.fullmatch(r"(\w+)\s*=\s*imread\((.+)\)", s)
        if xm:
            self.images[xm.group(1)] = self.file_value(xm.group(2), ctx)
            return True
        mm = re.fullmatch(r"(\w+)\s*=\s*Screen\(\s*'MakeTexture'\s*,\s*\w+\s*,\s*(\w+).*\)", s)
        if mm:
            self.images[mm.group(1)] = self.images.get(mm.group(2), "")
            return True
        dt = re.fullmatch(r"Screen\(\s*'DrawTextures?'\s*,\s*\w+\s*,\s*(\w+)(.*)\)", s)
        if dt:
            img = self.images.get(dt.group(1))
            if img is None:
                self.skip(n)
                return True
            ctx["pending"].append({"type": "image", "image": img})
            if dt.group(2).strip(" ,"):
                self.res.note("approx", f"line {line}", "the texture's rectangle/angle was not converted: the "
                              "picture is shown at its own size in the centre")
            return True
        if re.fullmatch(r"Screen\(\s*'DrawLines'.*\)", s):
            ctx["pending"].append({"type": "fixation"})
            self.res.note("approx", f"line {line}", "Screen('DrawLines') was taken to be a fixation cross")
            return True
        fr = re.fullmatch(r"Screen\(\s*'(FillRect|FillOval|FrameRect|DrawDots)'(.*)\)", s)
        if fr:
            args = split_args(fr.group(2).strip(" ,"))
            if fr.group(1) == "FillRect" and len(args) <= 2:
                if len(args) == 2:
                    col = self.color(args[1], ctx)
                    if col and not str(col).startswith("$"):
                        ctx["pending"].append({"type": "_bg", "color": col})
                return True
            ctx["pending"].append({"type": "shape", "shape": "circle" if "Oval" in fr.group(1) or "Dots" in fr.group(1)
                                   else "rect", "size": [100, 100]})
            self.res.note("approx", f"line {line}", f"Screen('{fr.group(1)}') became a shape of 100 px: set its size "
                          "and position")
            return True
        if re.fullmatch(r"(?:\[?[\w\s,]*\]?\s*=\s*)?Screen\(\s*'Flip'.*\)", s):
            self.flip(ctx, s, line)
            return True
        wm = re.fullmatch(r"WaitSecs\((.+)\)", s)
        if wm:
            d = self.duration_value(wm.group(1), ctx)
            cur = ctx["cur"]
            if cur is None:
                self.skip(n)
                return True
            if cur.get("_queue"):
                cur["_queue"]["duration"] = d
            if "duration" in cur and isinstance(cur["duration"], (int, float)) and isinstance(d, (int, float)):
                cur["duration"] = round(cur["duration"] + d, 6)
            elif "duration" not in cur:
                cur["duration"] = d
            return True
        if re.fullmatch(r"(?:\[[^\]]*\]\s*=\s*)?(?:KbStrokeWait|KbWait|KbPressWait|GetClicks|KbWaitForKey)(?:\(.*\))?", s):
            cur = ctx["cur"]
            if cur is None:
                self.skip(n)
                return True
            k = {"id": "resp", "type": "keyboard", "end_routine": True}
            if "GetClicks" in s:
                k = {"id": "click", "type": "mouse", "end_routine": True}
            cur["components"].append(k)
            return True
        if re.fullmatch(r"KbQueueStart.*", s):
            cur = ctx["cur"]
            if cur is None:
                self.skip(n)
                return True
            keys = next((v for k, v in self.vars.items() if k.startswith("_keys_")), None)
            k = {"id": "resp", "type": "keyboard"}
            names = [self.keys[x] for x in (keys or []) if x in self.keys]
            if names:
                k["keys"] = names
            cur["components"].append(k)
            cur["_queue"] = k
            return True
        if re.fullmatch(r"(?:\[[^\]]*\]\s*=\s*)?KbQueue(?:Stop|Check|Flush)(?:\(.*\))?", s):
            return True
        pa = re.fullmatch(r"PsychPortAudio\(\s*'Start'\s*,\s*(\w+).*\)", s)
        if pa:
            f = self.sounds.get(pa.group(1))
            if not f:
                self.skip(n)
                return True
            self.res.assets.add(f)
            c = {"type": "sound", "sound": f}
            if ctx.get("pending_if"):
                c["if"] = ctx["pending_if"]
            ctx["pending"].append(c)
            return True
        return False

    def text_value(self, a: str, ctx: dict[str, Any]) -> Any:
        v = mstring(a)
        if v is not None:
            return v
        a = a.strip()
        if a in ctx["cols"]:
            return f"${ctx['cols'][a]}"
        if isinstance(self.vars.get(a), str):
            return self.vars[a]
        tv = self.table_ref(a, ctx)
        if tv:
            return tv
        m = re.fullmatch(r"num2str\((\w+)\)|sprintf\('%d'\s*,\s*(\w+)\)", a)
        if m:
            name = m.group(1) or m.group(2)
            if name in ctx["cols"]:
                return f"${ctx['cols'][name]}"
        return None

    def file_value(self, a: str, ctx: dict[str, Any]) -> Any:
        v = mstring(a)
        if v is not None:
            self.res.assets.add(portable_path(v))
            return portable_path(v)
        a = a.strip()
        if a in ctx["cols"]:
            return f"${ctx['cols'][a]}"
        tv = self.table_ref(a, ctx)
        return tv or ""

    def duration_value(self, a: str, ctx: dict[str, Any]) -> Any:
        n = self.number(a)
        if isinstance(n, (int, float)):
            return n
        e = a.strip()
        for name, col in ctx["cols"].items():
            e = re.sub(rf"\b{re.escape(name)}\b", col, e)
        e = re.sub(r"(\w+)\.(\w+)[({]\s*\w+\s*[)}]", lambda m: (self.table_ref(m.group(0), ctx) or "$" + m.group(0))[1:], e)
        e = re.sub(r"\brand\b(?:\(\))?", "random.random()", e)
        if re.fullmatch(r"[\w\s.+\-*/()]+", e):
            names = set(re.findall(r"[A-Za-z_]\w*", e)) - {"random"}
            if names <= set(ctx["rowcols"]) | {"random"}:
                return f"${e}"
        self.res.note("approx", "timing", f"WaitSecs({a}) could not be converted: set to 1 s")
        return 1.0

    def table_ref(self, a: str, ctx: dict[str, Any]) -> str | None:
        m = re.fullmatch(r"(\w+)\.(\w+)[({]\s*(\w+)\s*[)}]", a.strip()) or \
            re.fullmatch(r"(\w+)\{\s*(\w+)\s*,\s*'(\w+)'\s*\}", a.strip())
        if not m:
            return None
        if "{" in a and "'" in a:
            t, idx, col = m.group(1), m.group(2), m.group(3)
        else:
            t, col, idx = m.group(1), m.group(2), m.group(3)
        if t in self.tables and idx in ctx.get("index_vars", ()):
            ctx["table"] = t
            ctx["rowcols"].setdefault(ident(col), None)
            return f"${ident(col)}"
        return None

    def flip(self, ctx: dict[str, Any], s: str, line: int) -> None:
        comps = []
        cids = Ids()
        bg = None
        for c in ctx["pending"]:
            if c["type"] == "_bg":
                bg = c["color"]
                continue
            comps.append({"id": cids.make({"text": "text", "image": "image", "sound": "sound", "fixation": "fixation",
                                           "shape": "shape"}[c["type"]]), **c})
        ctx["pending"] = []
        ctx["pending_if"] = None
        if bg and bg != self.background:
            self.res.note("approx", f"line {line}", f"Screen('FillRect') with colour {bg} (a background for one screen) "
                          "was not converted")
        when = re.search(r"'Flip'\s*,\s*\w+\s*,\s*(.+)\)", s)
        prev = ctx["cur"]
        if when and prev is not None and "duration" not in prev:
            fm = re.search(r"\(\s*(\w+)\s*-\s*0\.5\s*\)\s*\*\s*\w+", when.group(1))
            n = self.number(fm.group(1)) if fm else None
            if isinstance(n, (int, float)):
                prev["duration"] = round(n / 60, 6)
                self.res.note("approx", f"line {line}", f"a flip timed {n} frames after the previous one: the previous "
                              f"screen lasts {n} frames at 60 Hz ({prev['duration']} s); check it for your monitor")
        cur = {"components": comps, "_line": line}
        ctx["screens"].append(cur)
        ctx["cur"] = cur

    # ------------------------------------------------------------- responses inside while / if
    def response_loop(self, n: dict[str, Any], ctx: dict[str, Any]) -> bool:
        """while … KbCheck … end: a keyboard with the keys it tests and its time limit."""
        body_txt = "\n".join(self.flatten(n["body"]))
        if "KbCheck" not in body_txt and "GetMouse" not in body_txt:
            return False
        cur = ctx["cur"]
        if cur is None:
            return False
        keyvars = re.findall(r"keyCode\(\s*(\w+)\s*\)", body_txt) + \
            [f"'{k}'" for k in re.findall(r"keyCode\(\s*KbName\(\s*'([^']+)'\s*\)\s*\)", body_txt)]
        keys, escape = [], False
        for kv in keyvars:
            k = key_name(kv.strip("'")) if kv.startswith("'") else self.keys.get(kv)
            if k == "escape":
                escape = True
            elif k and k not in keys:
                keys.append(k)
        # response = N after a key test
        for kv, val in re.findall(r"keyCode\(\s*(\w+)\s*\)\s*\n\s*(?:\w+\s*=\s*)?\w+\s*=\s*(\d+)", body_txt):
            if kv in self.keys:
                self.key_values[self.keys[kv]] = num(val)
        k: dict[str, Any] = {"id": "resp", "type": "keyboard", "end_routine": True}
        if keys:
            k["keys"] = keys
        lim = re.search(r"GetSecs\s*-\s*\w+\s*<=?\s*([\w.]+)", n["head"])
        if lim:
            d = self.number(lim.group(1))
            if isinstance(d, (int, float)):
                k["duration"] = d
        cur["components"].append(k)
        if escape:
            self.res.note("info", f"line {n['line']}", "the escape key that quits the experiment is not needed: "
                          "EDGE stops a session with Escape (asking first)")
        return True

    def flatten(self, nodes: list[dict[str, Any]]) -> list[str]:
        out = []
        for x in nodes:
            if x["kind"] == "stmt":
                out.append(x["text"])
            elif x["kind"] == "if":
                for cond, body, _ in x["branches"]:
                    out.append(f"if {cond}" if cond else "else")
                    out += self.flatten(body)
            else:
                out.append(x.get("head", x["kind"]))
                out += self.flatten(x.get("body", []))
        return out

    def correct_stmt(self, s: str, ctx: dict[str, Any]) -> bool:
        m = re.fullmatch(r"(\w+)\s*=\s*\(?\s*(\w+)\s*==\s*(\w+)\s*\)?", s)
        if m and m.group(3) in ctx["cols"] and self.key_values:
            ctx["correct"] = ("value", m.group(3))
            return True
        m = re.fullmatch(r"\w+\s*=\s*strcmpi?\(\s*KbName\(\s*\w+\s*\)\s*,\s*(.+)\)", s)
        if m:
            ref = self.table_ref(m.group(1), ctx) or (f"${ctx['cols'][m.group(1).strip()]}"
                                                      if m.group(1).strip() in ctx["cols"] else None)
            if ref:
                ctx["correct"] = ("key", ref[1:])
                return True
        if re.fullmatch(r"(?:rt|RT|\w*[rR][tT]\w*)\s*=\s*.*-\s*\w+", s) or re.fullmatch(r"\w+\s*=\s*find\(.*\)", s) or \
                re.fullmatch(r"\[\s*\w+\s*,\s*\w+\s*\]\s*=\s*KbQueueCheck.*", s):
            return True
        return False

    # ------------------------------------------------------------- blocks
    def block(self, nodes: list[dict[str, Any]], ctx: dict[str, Any], in_loop: bool) -> list[Any]:
        """Statements -> flow nodes (screens, loops)."""
        flow: list[Any] = []
        for n in nodes:
            if n["kind"] == "stmt":
                s = n["text"]
                if in_loop and self.loop_assign(s, ctx, n["line"]):
                    continue
                if self.screen_stmt(n, ctx):
                    continue
                if in_loop and self.correct_stmt(s, ctx):
                    continue
                if self.assign(s, n["line"]):
                    continue
                self.skip(n)
            elif n["kind"] == "for":
                loop = self.for_loop(n, ctx)
                if loop is None:
                    self.skip(n)
                else:
                    flow += self.close_screens(ctx)
                    flow.append(loop)
            elif n["kind"] == "while":
                if not self.response_loop(n, ctx):
                    self.skip(n)
            elif n["kind"] == "if":
                self.if_block(n, ctx, in_loop)
            elif n["kind"] == "try":
                flow += self.close_screens(ctx)
                flow += self.block(n["body"], ctx, in_loop)
                if n["catch"]:
                    self.setup_lines += 1
            elif n["kind"] == "function":
                self.skip(n)
            else:
                self.skip(n)
        return flow

    def if_block(self, n: dict[str, Any], ctx: dict[str, Any], in_loop: bool) -> None:
        """'if ~correct, play a sound' and 'if pressed … else … end' (RT bookkeeping) are understood."""
        br = n["branches"]
        cond = (br[0][0] or "").strip()
        if len(br) == 1 and re.fullmatch(r"~\s*(\w+)|(\w+)\s*==\s*0|(\w+)", cond):
            var = next(g for g in re.fullmatch(r"~\s*(\w+)|(\w+)\s*==\s*0|(\w+)", cond).groups() if g)
            negative = not re.fullmatch(r"\w+", cond)
            if var in ("correct", "corr", "acc", "accuracy", "isCorrect", "iscorrect"):
                ctx["pending_if"] = "$not resp.corr" if negative else "$resp.corr == 1"
                for x in br[0][1]:
                    if x["kind"] != "stmt" or not self.screen_stmt(x, ctx):
                        self.skip(x)
                return
        if all(all(x["kind"] == "stmt" and (self.correct_stmt(x["text"], ctx) or re.fullmatch(
                r"\w+\s*=\s*(?:NaN|nan|0|1|true|false|\d+)", x["text"])) for x in body) for _, body, _ in br):
            return
        self.skip(n)

    def close_screens(self, ctx: dict[str, Any]) -> list[str]:
        out = []
        for scr in ctx["screens"]:
            out.append(self.make_routine(scr, ctx))
        ctx["screens"] = []
        ctx["cur"] = None
        return out

    def make_routine(self, scr: dict[str, Any], ctx: dict[str, Any]) -> str:
        comps = scr["components"]
        texts = [c for c in comps if c["type"] == "text"]
        resp = next((c for c in comps if c["id"] == "resp"), None)
        if resp is not None and ctx.get("correct"):
            kind, col = ctx["correct"]
            resp["correct"] = f"${'correct_key' if kind == 'value' else col}"
        if not texts and not any(c["type"] in ("image", "fixation", "shape") for c in comps):
            name = "blank"
        elif texts and isinstance(texts[0]["text"], str) and not texts[0]["text"].startswith("$") and \
                len(texts[0]["text"]) <= 2:
            name = "fixation"
        elif resp is not None and resp.get("keys") or any(str(c.get("image", "")).startswith("$") for c in comps) or \
                any(str(c.get("text", "")).startswith("$") for c in texts):
            name = "stimulus"
        elif texts and resp is not None and len(str(texts[0]["text"])) > 40:
            name = "instructions"
        elif texts:
            words = re.findall(r"[A-Za-z]+", str(texts[0]["text"]))[:2]
            name = "_".join(w.lower() for w in words) or "screen"
        else:
            name = "screen"
        rid = self.ids.make(name, "screen")
        routine: dict[str, Any] = {"components": comps}
        queue = scr.get("_queue")
        if queue is not None and "duration" in queue:
            queue.pop("duration")
        if "duration" in scr:
            d = scr["duration"]
            routine["duration"] = d
            if resp is not None and resp.get("end_routine") and "duration" not in resp:
                resp["duration"] = d
                del routine["duration"]
        if not any(c.get("end_routine") for c in comps) and "duration" not in routine:
            routine["duration"] = 1.0
            self.res.note("approx", f"line {scr['_line']}", f"the screen '{rid}' has no wait and no response after "
                          "its flip: set to 1 s")
        if not comps:
            comps.append({"id": "blank", "type": "wait"})
        self.routines[rid] = routine
        self.res.count("screens")
        return rid

    # ------------------------------------------------------------- the trial loop
    def for_loop(self, n: dict[str, Any], outer: dict[str, Any]) -> dict[str, Any] | None:
        m = re.fullmatch(r"for\s+(\w+)\s*=\s*1\s*:\s*(.+?)\s*,?", n["head"])
        if not m:
            return None
        var, limit = m.group(1), self.number(m.group(2))
        if not isinstance(limit, int) or limit <= 0:
            return None
        ctx = self.new_ctx()
        ctx["index_vars"] = {var}
        ctx["loopvar"] = var
        ctx["n"] = limit
        ctx["source"] = None
        children = self.block(n["body"], ctx, True)
        children += self.close_screens(ctx)
        if not children:
            return None
        rows, order, repeats = self.loop_rows(ctx, limit, n["line"])
        node: dict[str, Any] = {"loop": self.ids.make("trials", "loop"), "conditions": rows, "order": order,
                                "children": children}
        if repeats > 1:
            node["repeats"] = repeats
        self.res.count("trial lists")
        return node

    def loop_assign(self, s: str, ctx: dict[str, Any], line: int) -> bool:
        """Reading this trial's values: from the condition matrix, a table, a cell array or a colour matrix."""
        m = re.fullmatch(r"(\w+)\s*=\s*(.+)", s)
        if not m:
            return False
        lhs, rhs = m.group(1), m.group(2).strip()
        # row = order(t)
        pm = re.fullmatch(r"(\w+)\(\s*(\w+)\s*\)", rhs)
        if pm and pm.group(1) in self.perms and pm.group(2) in ctx["index_vars"]:
            ctx["index_vars"].add(lhs)
            ctx["perm"] = pm.group(1)
            return True
        mm = re.fullmatch(r"(\w+)\(\s*(\w+(?:\(\s*\w+\s*\))?)\s*,\s*(\d+)\s*\)", rhs)
        if mm and mm.group(1) in self.mats:
            idx = mm.group(2)
            im = re.fullmatch(r"(\w+)\(\s*(\w+)\s*\)", idx)
            if im and im.group(1) in self.perms and im.group(2) in ctx["index_vars"]:
                ctx["perm"] = im.group(1)
            elif idx not in ctx["index_vars"]:
                return False
            ctx["source"] = ctx.get("source") or ("mat", mm.group(1))
            ctx["cols"][lhs] = ident(lhs)
            ctx["rowcols"][ident(lhs)] = ("mat", int(mm.group(3)) - 1)
            return True
        cm = re.fullmatch(r"(\w+)\{\s*(\w+)\s*\}", rhs)
        if cm and isinstance(self.vars.get(cm.group(1)), list) and cm.group(2) in ctx["cols"]:
            ctx["cols"][lhs] = ident(lhs)
            ctx["rowcols"][ident(lhs)] = ("lookup", cm.group(1), ctx["cols"][cm.group(2)])
            return True
        km = re.fullmatch(r"(\w+)\(\s*(\w+)\s*,\s*:\s*\)", rhs)
        if km and km.group(1) in self.mats and km.group(2) in ctx["cols"]:
            ctx["cols"][lhs] = ident(lhs)
            ctx["rowcols"][ident(lhs)] = ("color", km.group(1), ctx["cols"][km.group(2)])
            return True
        tv = self.table_ref(rhs, ctx)
        if tv:
            ctx["cols"][lhs] = tv[1:]
            return True
        return False

    def loop_rows(self, ctx: dict[str, Any], n: int, line: int) -> tuple[list[dict[str, Any]], str, int]:
        src = ctx.get("source")
        shuffled = bool(ctx.get("perm")) and self.perms.get(ctx.get("perm"), {}).get("shuffled")
        repeats = 1
        if ctx.get("table"):
            t = self.tables[ctx["table"]]
            base = [dict(r) for r in t["rows"]]
            keycol = ctx["correct"][1] if ctx.get("correct") and ctx["correct"][0] == "key" else None
            for r in base:
                if keycol and isinstance(r.get(keycol), str):
                    r[keycol] = key_name(r[keycol])
            self.res.note("info", f"line {line}", f"the rows of {t['file']} were copied into the trial list"
                          + (f" (key names in '{keycol}' written the EDGE way)" if keycol else ""))
            rows = base
            if n != len(rows) and rows:
                repeats = max(1, n // len(rows))
        elif src and src[0] == "mat":
            mat = self.mats[src[1]]
            shuffled = shuffled or mat["shuffled"]
            repeats = mat["repeats"]
            rows = []
            for r in mat["rows"]:
                row: dict[str, Any] = {}
                for col, spec in ctx["rowcols"].items():
                    if spec and spec[0] == "mat" and spec[1] < len(r):
                        row[col] = r[spec[1]]
                rows.append(row)
            if n != len(rows) * repeats:
                self.res.note("approx", f"line {line}", f"the loop runs {n} times over a matrix of {len(rows)} rows "
                              f"× {repeats}: check the trial count")
        else:
            rows = [{} for _ in range(n)]
        for col, spec in ctx["rowcols"].items():       # values looked up from other columns
            if not spec or spec[0] == "mat":
                continue
            for r in rows:
                key = r.get(spec[2])
                if spec[0] == "lookup":
                    lst = self.vars.get(spec[1]) or []
                    r[col] = lst[key - 1] if isinstance(key, int) and 1 <= key <= len(lst) else None
                elif spec[0] == "color":
                    mrows = self.mats[spec[1]]["rows"]
                    r[col] = self.rgb(mrows[key - 1]) if isinstance(key, int) and 1 <= key <= len(mrows) else None
        if ctx.get("correct") and ctx["correct"][0] == "value":
            by_value = {v: k for k, v in self.key_values.items()}
            col = ident(ctx["correct"][1])
            for r in rows:
                r["correct_key"] = by_value.get(r.get(col))
            self.res.note("info", f"line {line}", "the correct key of each trial was worked out from the key → "
                          f"response number mapping ({', '.join(f'{k} = {v}' for k, v in self.key_values.items())}) "
                          f"and the column '{col}': see the column correct_key")
        if repeats > 1 and not ctx.get("table") and len(rows) * repeats != n:
            repeats = 1
        return rows, "random" if shuffled else "sequential", repeats

    # ------------------------------------------------------------- the whole script
    def run(self) -> ImportResult:
        res = self.res
        text = read_text(self.path)
        if not re.search(r"Screen\s*\(|PsychImaging|DrawFormattedText|KbCheck|KbWait|PsychPortAudio", text):
            raise ImportError_(f"{self.path.name} does not look like a Psychtoolbox experiment (it never calls Screen, "
                               "PsychImaging, DrawFormattedText or KbCheck)")
        stmts = statements(text)
        opened = sum(1 for st, _ in stmts if BLOCK.match(st))
        closed = sum(1 for st, _ in stmts if st == "end")
        self.unclosed = closed < opened - sum(1 for st, _ in stmts if st.startswith("function"))
        nodes = tree(stmts)
        if nodes and nodes[0]["kind"] == "function":      # a script written as a function: its body is the experiment
            main = nodes[0]
            for other in nodes[1:]:
                self.skip(other)
            res.note("info", f"line {main['line']}", f"the experiment is the function '{main['head'][9:].strip()}'"
                     + ("; the other functions in the file are listed below" if len(nodes) > 1 else ""))
            nodes = main["body"]
        res.note("approx", "translation", "Code translation is partial: Psychtoolbox experiments are MATLAB programs, "
                 "so only the common patterns (drawing and flipping screens, waits, keyboard checks, sounds, a loop "
                 "over a condition matrix or table) were translated. Everything else is listed below with its line "
                 "number: compare the result with the original before collecting data")
        ctx = self.new_ctx()
        ctx["index_vars"] = set()
        flow = self.block(nodes, ctx, False)
        flow += self.close_screens(ctx)
        if self.left:
            res.note("unsupported", "MATLAB code", "some lines were not translated; do these by hand (the lines, with their numbers, "
                     "are below):\n\n```matlab\n" + "\n".join(self.left) + "\n```")
        if self.results_lines:
            res.note("info", "results", "the results matrix and saving it (lines "
                     + ", ".join(map(str, sorted(set(self.results_lines))))
                     + ") are not needed: EDGE saves every key, RT, correctness and trial-list column automatically")
        if self.setup_lines:
            res.note("info", "setup", f"{self.setup_lines} set-up line(s) (opening the screen, sync tests, cursor, "
                     "priority, key name set-up, clean-up) are done by EDGE itself and were skipped")
        if not flow:
            res.note("unsupported", "flow", "no screen (drawing followed by Screen('Flip')) was found"
                     + (" (the script ends inside a for/while/if block: it may be cut short)" if self.unclosed else ""))
        size = getattr(self, "size", [W, H])
        res.doc = {"name": ident(self.path.stem), "description": f"Imported from Psychtoolbox ({self.path.name})",
                   "settings": {"window": {"size": size, "background": self.background, "units": "px"}},
                   "devices": [], "variables": {}, "routines": self.routines, "flow": flow}
        for r in self.routines.values():
            for c in r["components"]:
                if c["type"] == "image" and isinstance(c.get("image"), str) and c["image"] and not c["image"].startswith("$"):
                    res.assets.add(c["image"])
        avoid_column_clashes(res.doc)
        return res


def import_psychtoolbox(path: Path) -> ImportResult:
    return Converter(path).run()


def looks_like_psychtoolbox(path: Path) -> bool:
    if path.suffix.lower() != ".m":
        return False
    try:
        text = read_text(path)[:300000]
    except OSError:
        return False
    return bool(re.search(r"Screen\s*\(\s*'(?:OpenWindow|Flip)'|PsychImaging|DrawFormattedText|KbCheck|KbWait|"
                          r"PsychPortAudio|PsychDefaultSetup", text))
