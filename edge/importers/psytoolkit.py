"""PsyToolkit importer: a PsyToolkit experiment script (version 3 scripting language), or the zip downloaded from a
PsyToolkit account (the script, e.g. ``code.psy``, with its pictures and sounds).

What is converted (everything else is listed in the import report with its line number):

* ``options``: ``resolution``, ``fullscreen``, ``background color``, ``bitmapdir`` / ``sounddir`` (where the files
  are); ``scale``, ``mouse on``, ``vertical`` and the rest are reported.
* ``fonts`` (the first size becomes the text size; ``font <name>`` in a task switches size), ``bitmaps``, ``sounds``.
* ``table <name>``: rows of quoted texts and numbers become a trial list with columns ``col1``, ``col2`` …;
  ``@1``, ``@2`` … in the task read those columns.
* ``task <name>``: ``keys``, ``table``, ``show bitmap|text|rectangle|circle`` (x, y, colours, also from columns),
  ``clear`` / ``hide`` (by number, ``-1``, ``screen``), ``delay`` (also ``delay &var``), ``sound``,
  ``readkey <correct> <timeout>`` and ``readmouse l <stimulus> <timeout>``, ``if … else … fi`` (on STATUS, RT,
  variables, columns), ``set`` (number, column, ``random``, ``increase``/``decrease``, ``expression``), ``part``
  (inlined), ``save`` (the saved values are data columns and feed block feedback). A task becomes a series of
  screens: what is shown and cleared between two responses is one screen with its timing; a response ends a screen
  and the next one carries on with what is still visible; an ``if`` becomes an if/otherwise in the trial list.
  PsyToolkit's ``RT``, ``STATUS`` (CORRECT = 1, WRONG = 2, TIMEOUT = 3) and ``KEY`` are kept as variables.
* ``block <name>``: ``tasks <task> <n>`` (a trial list of n trials), ``message`` (a picture or a text; space or a
  mouse click continues), ``maxtrials``, ``feedback … end`` (texts, and ``set &v mean|median|count|sd|min|max cN ;
  select …`` over the saved columns, computed in EDGE as the trials go).
* ``blockorder`` (the first one when there are several), top-level ``message`` lines, ``include`` (other script
  files next to the script or in the zip).
"""

from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .base import Ids, ImportError_, ImportResult, decode_text, ident, key_name, num, read_text

SECTIONS = {"options", "fonts", "bitmaps", "sounds", "table", "task", "block", "blockorder", "part", "message",
            "include", "videos"}
# keywords that are also commands inside a task or block: a new section only after an empty line (or at the top)
INNER = {"table", "message", "part"}
STATUS_CODES = {"CORRECT": "1", "WRONG": "2", "TIMEOUT": "3"}
SYSTEM_VARS = {"RT": 0, "STATUS": 0, "KEY": 0, "TRIALCOUNT": 0, "BLOCKNAME": "", "BLOCKNUMBER": 0}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp")
SOUND_EXT = (".mp3", ".wav", ".ogg", ".flac", ".m4a")
SCRIPT_EXT = (".psy", ".txt", ".psytoolkit", ".code")
MAX_ZIP_FILES = 5000
MAX_ZIP_BYTES = 1024 * 1024 * 1024
STAT_FUNCS = {"mean": "round(statistics.mean({v}))", "median": "round(statistics.median({v}))", "count": "len({v})",
              "sd": "round(statistics.stdev({v}), 1) if len({v}) > 1 else 0", "min": "min({v})", "max": "max({v})",
              "sum": "sum({v})"}


# ------------------------------------------------------------------ recognising and reading the source
def _script_score(text: str) -> int:
    head = text[:300000]
    task = bool(re.search(r"^task\s+\w+", head, re.M))
    block = bool(re.search(r"^block\s+\w+", head, re.M)) or bool(re.search(r"^\s*tasks\s+\w+", head, re.M))
    cmds = len(re.findall(r"^\s*(?:show\s+(?:bitmap|text|rectangle|circle)|readkey|readmouse|delay|keys|save)\b",
                          head, re.M))
    return (task and block) * 2 + (cmds >= 2)


def looks_like_psytoolkit_text(text: str) -> bool:
    return _script_score(text) >= 3


def _zip_members(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    out = []
    for m in z.infolist():
        if m.is_dir():
            continue
        parts = [p for p in m.filename.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or ".." in parts or (len(parts[0]) > 1 and parts[0][1] == ":") or parts[0] == "__MACOSX" \
                or parts[-1].startswith("."):
            continue
        out.append(m)
    return out


def _zip_script(z: zipfile.ZipFile) -> zipfile.ZipInfo | None:
    best = None
    for m in _zip_members(z):
        name = m.filename.lower()
        if not name.endswith(SCRIPT_EXT) and "." in PurePosixPath(name).name or m.file_size > 5 * 1024 * 1024:
            continue
        try:
            text = decode_text(z.read(m))
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError, EOFError):
            continue
        score = _script_score(text) + name.endswith(".psy") * 2 + (PurePosixPath(name).name == "code.psy")
        if _script_score(text) >= 3 and (best is None or score > best[0]):
            best = (score, m)
    return best[1] if best else None


def looks_like_psytoolkit(path: Path) -> bool:
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            if not zipfile.is_zipfile(path):
                return False
            with zipfile.ZipFile(path) as z:
                return _zip_script(z) is not None
        if suffix == ".psy":
            return True
        if suffix in SCRIPT_EXT or suffix == "":
            return looks_like_psytoolkit_text(read_text(path)[:300000])
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, EOFError):
        return False
    return False


class _Source:
    """The script's files: a folder on disk, or the inside of a zip (kept in memory, nothing extracted)."""

    def __init__(self, path: Path, res: ImportResult):
        self.path, self.res = path, res
        self.files: dict[str, bytes] | None = None      # zip contents, relative to the script's folder
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as z:
                    script = _zip_script(z)
                    if script is None:
                        raise ImportError_(f"{path.name} holds no PsyToolkit script (a text file with task and block "
                                           "sections, usually code.psy). Download the experiment again from your "
                                           "PsyToolkit account, or import the script file itself.")
                    base = PurePosixPath(script.filename.replace("\\", "/")).parent
                    self.files, total = {}, 0
                    for m in _zip_members(z)[:MAX_ZIP_FILES]:
                        total += m.file_size
                        if total > MAX_ZIP_BYTES:
                            res.note("approx", "files", f"{path.name} is very large: files after {m.filename} were "
                                                        "left out")
                            break
                        p = PurePosixPath(m.filename.replace("\\", "/"))
                        try:
                            rel = p.relative_to(base) if str(base) != "." else p
                        except ValueError:
                            rel = PurePosixPath(p.name)       # a file outside the script's folder: by its name
                        self.files.setdefault(str(rel), z.read(m))
                    self.script_name = str(PurePosixPath(script.filename).name)
                    self.text = decode_text(self.files.get(str(PurePosixPath(script.filename.replace('\\', '/')).relative_to(base))
                                                           if str(base) != "." else script.filename.replace("\\", "/"), b""))
            except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as e:
                raise ImportError_(f"{path.name} could not be read: the zip file is incomplete or damaged ({e}). "
                                   "Download the experiment again from your PsyToolkit account.") from None
        else:
            self.script_name = path.name
            self.text = read_text(path)
        self.lower = {k.lower(): k for k in (self.files or {})}

    def find(self, rel: str) -> str | None:
        """The file's path relative to the script's folder (its own spelling), or None when it isn't there."""
        rel = rel.replace("\\", "/").lstrip("./") if rel.startswith("./") else rel.replace("\\", "/")
        if self.files is not None:
            return self.lower.get(rel.lower())
        p = self.path.parent / rel
        if p.is_file():
            return rel
        parent = p.parent
        if parent.is_dir():                    # PsyToolkit runs on Linux servers: names may differ only in case
            for f in parent.iterdir():
                if f.name.lower() == p.name.lower() and f.is_file():
                    return str(Path(rel).parent / f.name).replace("\\", "/").lstrip("./") if str(Path(rel).parent) != "." else f.name
        return None

    def read(self, rel: str) -> str | None:
        found = self.find(rel)
        if found is None:
            return None
        return decode_text(self.files[found]) if self.files is not None else read_text(self.path.parent / found)

    def use(self, rel: str) -> None:
        """Copy this file along with the experiment."""
        if self.files is not None:
            self.res.generated_files[rel] = self.files[rel]
        else:
            self.res.assets.add(rel)


# ------------------------------------------------------------------ the script as lines and sections
def _tokens(s: str) -> list[str]:
    """Words of a line; a "quoted text" is one word (kept with its quotes)."""
    return [m.group(0) for m in re.finditer(r'"[^"]*"?|\S+', s)]


def _unquote(t: str) -> str:
    return t[1:-1] if len(t) >= 2 and t[0] == t[-1] == '"' else t.strip('"')


class Line:
    __slots__ = ("n", "where", "text", "indented")

    def __init__(self, n: int, where: str, text: str, indented: bool):
        self.n, self.where, self.text, self.indented = n, where, text, indented


def _lines(text: str, src: _Source, res: ImportResult, file_label: str = "", depth: int = 0) -> list[Line]:
    out: list[Line] = []
    for i, raw in enumerate(text.split("\n"), 1):
        where = f"{file_label}line {i}" if not file_label else f"{file_label}:{i}"
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        if not raw[:1].isspace() and re.match(r"include\s+\S", stripped):
            name = _unquote(stripped.split(None, 1)[1].strip())
            inc = src.read(name) if depth < 5 else None
            if inc is None:
                res.note("unsupported", where, f"include {name}: the file was not found next to the script "
                                               f"({'too many nested includes' if depth >= 5 else 'add it and import again'})")
                continue
            out.append(Line(i, where, "", False))
            out += _lines(inc, src, res, name, depth + 1)
            out.append(Line(i, where, "", False))
            continue
        out.append(Line(i, where, stripped, raw[:1].isspace()))
    return out


def _sections(lines: list[Line], res: ImportResult) -> list[dict[str, Any]]:
    """[{kind, name, args, line, body: [Line]}] in script order."""
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    blank_before = True
    for ln in lines:
        if not ln.text:
            blank_before = True
            continue
        word = ln.text.split()[0].lower()
        starts = not ln.indented and word in SECTIONS and (word not in INNER or blank_before or cur is None
                                                            or cur["kind"] not in ("task", "block", "part"))
        if word == "message" and cur is not None and cur["kind"] == "block" and not blank_before:
            starts = False
        if starts:
            toks = _tokens(ln.text)
            cur = {"kind": word, "name": _unquote(toks[1]) if len(toks) > 1 else "", "args": toks[1:], "line": ln,
                   "body": []}
            sections.append(cur)
        elif cur is None:
            res.note("unsupported", ln.where, f"'{ln.text[:80]}' is outside any section (options, task, block …)")
        else:
            cur["body"].append(ln)
        blank_before = False
    return sections


# ------------------------------------------------------------------ values and expressions
def _ms_to_s(v: float) -> float:
    return round(v / 1000.0, 6)


def _num(t: str) -> int | float | None:
    v = num(t)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


class Conv:
    """Turns PsyToolkit values and conditions into EDGE expressions; records the variables they use."""

    def __init__(self, res: ImportResult):
        self.res = res
        self.vars: dict[str, Any] = {}
        self.columns: set[int] = set()

    def var(self, name: str) -> str:
        v = ident(name)
        if v in ("True", "False", "None", "and", "or", "not", "in", "is", "if", "else", "t", "frame", "math",
                 "random", "statistics"):
            v = f"v_{v}"
        self.vars.setdefault(v, 0)
        return v

    def col(self, n: str | int) -> str:
        self.columns.add(int(n))
        return f"col{int(n)}"

    def expr(self, s: str) -> str:
        """A PsyToolkit expression or condition as Python (without the leading $)."""
        s = re.sub(r"\s&&\s|\s+and\s+", " and ", f" {s} ").strip()
        s = re.sub(r"\s*\|\|\s*", " or ", s)
        s = re.sub(r"@(\d+)", lambda m: self.col(m.group(1)), s)
        s = re.sub(r"&{1,2}(\w+)|\$(\w+)", lambda m: self.var(m.group(1) or m.group(2)), s)
        s = re.sub(r"\b(CORRECT|WRONG|TIMEOUT)\b", lambda m: STATUS_CODES[m.group(1)], s)
        s = re.sub(r"(?<![=!<>])=(?!=)", "==", s)
        s = re.sub(r"!(?!=)", " not ", s)
        for k in SYSTEM_VARS:
            if re.search(rf"\b{k}\b", s):
                self.vars.setdefault(k, SYSTEM_VARS[k])
        return " ".join(s.split())

    def value(self, t: str) -> Any:
        """One word: a number stays a number, a "text" stays text, anything else is an $expression."""
        if len(t) >= 2 and t[0] == t[-1] == '"':
            return self.text(_unquote(t))
        n = _num(t)
        if n is not None:
            return n
        return "$" + self.expr(t)

    def text(self, s: str) -> Any:
        """Text shown to participants; &variables and @columns in it are filled in."""
        if re.fullmatch(r"@\d+|&{1,2}\w+|\$\w+", s.strip()):
            return "$" + self.expr(s.strip())
        if not re.search(r"@\d+|&{1,2}\w+", s):
            return s.replace("$", "$$") if s.startswith("$") else s
        parts = re.split(r"(@\d+|&{1,2}\w+)", s)
        out = "".join("{" + self.expr(p) + "}" if re.fullmatch(r"@\d+|&{1,2}\w+", p)
                      else p.replace("{", "{{").replace("}", "}}") for p in parts)
        return "$f" + repr(out)

    def color(self, toks: list[str]) -> Any:
        """A colour from 'r g b' (numbers or columns), a name, or #rrggbb."""
        if len(toks) >= 3:
            vals = [self.value(t) for t in toks[:3]]
            if all(isinstance(v, (int, float)) for v in vals):
                return "#%02x%02x%02x" % tuple(max(0, min(255, int(v))) for v in vals)
            return "$[" + ", ".join(str(v)[1:] if isinstance(v, str) else str(v) for v in vals) + "]"
        if toks:
            t = _unquote(toks[0])
            return t if re.fullmatch(r"#?[0-9a-fA-F]{6}|[a-zA-Z]+", t) and not t.startswith("@") else self.value(toks[0])
        return None


class Time:
    """A moment in a screen: milliseconds plus delays given by variables (delay &isi)."""

    def __init__(self, ms: float = 0, exprs: tuple[str, ...] = ()):
        self.ms, self.exprs = ms, tuple(exprs)

    def plus(self, v: Any) -> "Time":
        if isinstance(v, (int, float)):
            return Time(self.ms + v, self.exprs)
        return Time(self.ms, self.exprs + (str(v),))

    def minus(self, start: "Time") -> "Time":
        return Time(self.ms - start.ms, self.exprs[len(start.exprs):])

    @property
    def zero(self) -> bool:
        return not self.exprs and self.ms == 0

    def seconds(self) -> Any:
        if not self.exprs:
            return _ms_to_s(self.ms)
        terms = " + ".join(f"({e})" for e in self.exprs) + (f" + {self.ms:g}" if self.ms else "")
        return f"$({terms}) / 1000"


# ------------------------------------------------------------------ the converter
class Converter:
    def __init__(self, path: Path):
        self.res = ImportResult({}, path, "PsyToolkit")
        self.src = _Source(path, self.res)
        self.cv = Conv(self.res)
        self.rids = Ids()
        self.routines: dict[str, Any] = {}
        self.window = {"size": [800, 600], "background": "#000000", "units": "px"}
        self.bitmapdir = self.sounddir = ""
        self.text_height = 24
        self.fonts: dict[str, Any] = {}
        self.bitmaps: dict[str, str] = {}
        self.sounds: dict[str, str] = {}
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.parts: dict[str, list[Line]] = {}
        self.task_nodes: dict[str, list[Any]] = {}
        self.feedback_stats: list[dict[str, Any]] = []        # accumulators the tasks fill and block feedback reads
        self.text = self.src.text

    # ---------------------------------------------------------- files
    def _file(self, name: str, folder: str, exts: tuple[str, ...], where: str, kind: str) -> str:
        cand = [name] if PurePosixPath(name).suffix else [name + e for e in exts]
        for c in cand:
            rel = f"{folder.rstrip('/')}/{c}" if folder else c
            found = self.src.find(rel)
            if found is not None:
                self.src.use(found)
                self.res.count(f"{kind}s")
                return found
        rel = f"{folder.rstrip('/')}/{cand[0]}" if folder else cand[0]
        self.res.note("approx", where, f"{kind} file '{rel}' was not found next to the script: copy it into the "
                                       "experiment's folder")
        return rel

    # ---------------------------------------------------------- top-level sections
    def options(self, sec: dict[str, Any]) -> None:
        for ln in sec["body"]:
            toks = _tokens(ln.text)
            key = toks[0].lower()
            if key == "resolution" and len(toks) >= 3 and _num(toks[1]) and _num(toks[2]):
                self.window["size"] = [int(_num(toks[1])), int(_num(toks[2]))]
            elif key == "fullscreen":
                self.window["fullscreen"] = True
            elif key == "background" and len(toks) >= 2:
                rest = toks[2:] if toks[1].lower() in ("color", "colour") else toks[1:]
                c = self.cv.color(rest)
                if isinstance(c, str) and not c.startswith("$"):
                    self.window["background"] = c if c.startswith("#") or not re.fullmatch(r"[0-9a-fA-F]{6}", c) else f"#{c}"
                else:
                    self.res.note("approx", ln.where, "background colour not understood; set it in Settings")
            elif key == "bitmapdir" and len(toks) > 1:
                self.bitmapdir = _unquote(toks[1])
            elif key == "sounddir" and len(toks) > 1:
                self.sounddir = _unquote(toks[1])
            elif key == "scale":
                self.res.note("approx", ln.where, "scale: PsyToolkit scales the screen to the browser window; EDGE "
                                                  "draws at the size in Settings (or full screen); positions are kept "
                                                  "in pixels")
            elif key == "mouse":
                self.res.note("info", ln.where, "mouse on/off: EDGE shows the mouse pointer on screens that wait for a "
                                                "click")
            elif key == "vertical":
                self.res.note("approx", ln.where, "vertical (a portrait layout for phones) is not converted; set the "
                                                  "window size in Settings")
            else:
                self.res.note("unsupported", ln.where, f"option '{ln.text[:80]}' not converted")

    def fonts_section(self, sec: dict[str, Any]) -> None:
        for ln in sec["body"]:
            toks = _tokens(ln.text)
            size = next((_num(t) for t in reversed(toks) if _num(t)), None)
            if size:
                self.fonts[toks[0]] = size
                if len(self.fonts) == 1:
                    self.text_height = size
        if self.fonts:
            self.res.note("info", sec["line"].where, "fonts: EDGE uses its own font; the sizes were kept as text heights")

    def media(self, sec: dict[str, Any], store: dict[str, str], folder: str, exts: tuple[str, ...], kind: str) -> None:
        for ln in sec["body"]:
            toks = _tokens(ln.text)
            name = _unquote(toks[0])
            file = _unquote(toks[1]) if len(toks) > 1 else name
            store[name] = self._file(file, folder, exts, ln.where, kind)

    def table(self, sec: dict[str, Any]) -> None:
        rows = []
        for ln in sec["body"]:
            toks = _tokens(ln.text)
            row = {}
            for i, t in enumerate(toks, 1):
                n = _num(t)
                row[f"col{i}"] = n if n is not None else _unquote(t)
            rows.append(row)
        if not rows:
            self.res.note("approx", sec["line"].where, f"table {sec['name']} has no rows")
        width = max((len(r) for r in rows), default=0)
        for r in rows:          # every row has every column (a short row: empty cells)
            for i in range(1, width + 1):
                r.setdefault(f"col{i}", "")
        self.tables[sec["name"]] = rows
        self.res.count("tables")

    # ---------------------------------------------------------- tasks
    def task(self, sec: dict[str, Any]) -> None:
        name = sec["name"]
        stmts = self._parse_block(self._inline_parts(sec["body"]), sec["line"])
        info: dict[str, Any] = {"keys": [], "table": None, "save": [], "line": sec["line"], "maxtrials": None}
        self.tasks[name] = info
        seq = _Seq(self, name, info)
        seq.run(stmts)
        self.task_nodes[name] = seq.finish()
        self.res.count("tasks")

    def _inline_parts(self, body: list[Line], depth: int = 0) -> list[Line]:
        out = []
        for ln in body:
            toks = ln.text.split()
            if toks and toks[0] == "part" and len(toks) > 1 and depth < 5:
                part = self.parts.get(toks[1])
                if part is None:
                    self.res.note("unsupported", ln.where, f"part {toks[1]} is not defined")
                    continue
                out += self._inline_parts(part, depth + 1)
            else:
                out.append(ln)
        return out

    def _parse_block(self, body: list[Line], head: Line) -> list[Any]:
        """Statements with if/else/fi and while/while-end nested: [Line | {"if": Line, "then": [...], "else": [...]}]."""
        root: list[Any] = []
        stack: list[tuple[str, dict[str, Any] | None, list[Any]]] = [("root", None, root)]
        for ln in body:
            word = ln.text.split()[0]
            if word == "if":
                node = {"if": ln, "then": [], "else": []}
                stack[-1][2].append(node)
                stack.append(("then", node, node["then"]))
            elif word == "else" and stack[-1][0] in ("then",):
                node = stack.pop()[1]
                stack.append(("else", node, node["else"]))  # type: ignore[index]
            elif word == "fi" and stack[-1][0] in ("then", "else"):
                stack.pop()
            elif word == "while":
                node = {"while": ln, "body": []}
                stack[-1][2].append(node)
                stack.append(("while", node, node["body"]))
            elif word in ("while-end", "end-while") and stack[-1][0] == "while":
                stack.pop()
            else:
                stack[-1][2].append(ln)
        if len(stack) > 1:
            self.res.note("approx", head.where, f"an '{stack[-1][0] if stack[-1][0] != 'then' else 'if'}' in this "
                                                "task is never closed (fi / while-end): read to the end of the task")
        return root

    # ---------------------------------------------------------- blocks
    def block(self, sec: dict[str, Any], number: int) -> list[Any]:
        name = sec["name"]
        bid = ident(name)
        nodes: list[Any] = []
        start_vars: dict[str, Any] = {}
        if "BLOCKNAME" in self.text:
            start_vars["BLOCKNAME"] = name
            self.cv.vars.setdefault("BLOCKNAME", "")
        if "BLOCKNUMBER" in self.text:
            start_vars["BLOCKNUMBER"] = number
            self.cv.vars.setdefault("BLOCKNUMBER", 0)
        if "TRIALCOUNT" in self.text:
            start_vars["TRIALCOUNT"] = 0
        body = sec["body"]
        i, maxtrials = 0, None
        feedback_nodes: list[Any] = []
        while i < len(body):
            ln = body[i]
            toks = _tokens(ln.text)
            word = toks[0].lower()
            if word == "tasks":
                nodes += self._tasks_line(bid, toks, ln, maxtrials)
            elif word == "message":
                nodes.append(self.message(toks[1:], ln, f"{bid}_message"))
            elif word == "maxtrials" and len(toks) > 1 and _num(toks[1]):
                maxtrials = int(_num(toks[1]))
                for n in nodes:
                    if isinstance(n, dict) and n.get("loop"):         # at most this many trials
                        n["stop_if"] = f"${n['loop']}.n >= {maxtrials - 1}"
            elif word == "feedback":
                j = i + 1
                fb_lines = []
                while j < len(body) and body[j].text.split()[0].lower() != "end":
                    fb_lines.append(body[j])
                    j += 1
                feedback_nodes.append(self.feedback(bid, fb_lines, ln, start_vars, nodes))
                i = j
            elif word in ("delay", "wait") and len(toks) > 1:
                d = self.cv.value(toks[1])
                rid = self.rids.make(f"{bid}_pause", "pause")
                self.routines[rid] = {"duration": _ms_to_s(d) if isinstance(d, (int, float)) else f"({d[1:]}) / 1000",
                                      "components": [{"id": "wait", "type": "wait"}]}
                nodes.append(rid)
            elif word == "set" and len(toks) >= 3:
                var, val = self._set_value(toks, ln)
                if var:
                    start_vars[var] = val
            else:
                self.res.note("unsupported", ln.where, f"block {name}: '{ln.text[:80]}' not converted")
            i += 1
        nodes += feedback_nodes
        if start_vars:
            first = next((n for n in nodes if isinstance(n, str) and n.endswith("_message")), None)
            comp = {"id": "block_start", "type": "variable", "set": start_vars}
            if first is not None and nodes.index(first) == 0:
                self.routines[first]["components"].insert(0, comp)
            else:
                rid = self.rids.make(f"{bid}_start", "start")
                self.routines[rid] = {"duration": 0, "description": f"Start of block {name}: its variables",
                                      "components": [comp]}
                nodes.insert(0, rid)
        self.res.count("blocks")
        return nodes

    def _tasks_line(self, bid: str, toks: list[str], ln: Line, maxtrials: int | None) -> list[Any]:
        args = [t for t in toks[1:] if t.lower() != "random"]
        names = [t for t in args if t in self.tasks]
        n = next((int(_num(t)) for t in args if _num(t)), None)
        if not names:
            self.res.note("unsupported", ln.where, f"'{ln.text[:80]}': no task of that name in the script")
            return []
        if len(names) > 1:
            self.res.note("approx", ln.where, f"tasks {' '.join(names)}: PsyToolkit picks one of these tasks at random "
                                              f"for each trial; EDGE runs {names[0]} only (add the others as their "
                                              "own trial lists, or an if/otherwise on a random column)")
        tname = names[0]
        info = self.tasks[tname]
        rows = self.tables.get(info["table"]) if info["table"] else None
        lid = self.rids.make(f"{bid}_{tname}", "trials")
        loop: dict[str, Any] = {"loop": lid, "children": list(self.task_nodes[tname])}
        if rows:
            loop["conditions"] = [dict(r) for r in rows]
            loop["order"] = "random"
            total = n or len(rows)
            reps = max(1, math.ceil(total / len(rows)))
            if reps > 1:
                loop["repeats"] = reps
            if total != reps * len(rows):
                loop["stop_if"] = f"${lid}.n >= {total - 1}"
            self.res.note("approx", ln.where, f"tasks {tname} {total}: PsyToolkit chooses a table row at random for "
                                              f"each trial; EDGE shows the {len(rows)} rows in a shuffled order, each "
                                              "equally often (change the order on the trial list)")
        else:
            loop["repeats"] = n or 1
        if maxtrials:
            loop["stop_if"] = f"${lid}.n >= {maxtrials - 1}"
        self.res.count("loops")
        return [loop]

    def message(self, args: list[str], ln: Line, base: str) -> str:
        rid = self.rids.make(base, "message")
        comps: list[dict[str, Any]] = []
        mouse = any(a.lower() == "mouse" for a in args[1:])
        what = args[0] if args else ""
        if what.startswith('"'):
            comps.append({"id": "message_text", "type": "text", "text": self.cv.text(_unquote(what)),
                          "height": self.text_height, "wrap_width": int(self.window["size"][0] * 0.8)})
        elif what in self.bitmaps:
            comps.append({"id": "message_picture", "type": "image", "image": self.bitmaps[what]})
        elif what:
            comps.append({"id": "message_picture", "type": "image",
                          "image": self._file(what, self.bitmapdir, IMAGE_EXT, ln.where, "picture")})
        else:
            self.res.note("unsupported", ln.where, "message without a picture or text")
        comps.append({"id": "go", "type": "mouse", "end_routine": True} if mouse else
                     {"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True})
        self.routines[rid] = {"components": comps}
        self.res.count("messages")
        return rid

    def feedback(self, bid: str, lines: list[Line], head: Line, start_vars: dict[str, Any], nodes: list[Any]) -> str:
        rid = self.rids.make(f"{bid}_feedback", "feedback")
        comps: list[dict[str, Any]] = []
        sets: dict[str, Any] = {}
        color = "white"
        task_names = [n["loop"] for n in nodes if isinstance(n, dict) and n.get("loop")]
        saved = self._saved_of(nodes)
        for ln in lines:
            toks = _tokens(ln.text)
            word = toks[0].lower()
            if word == "text" and len(toks) >= 2 and toks[1].lower() in ("align", "color", "colour", "size", "font"):
                if toks[1].lower() in ("color", "colour"):
                    color = self.cv.color(toks[2:]) or color
                elif toks[1].lower() == "size" and len(toks) > 2 and _num(toks[2]):
                    self.text_height = _num(toks[2])
                else:
                    self.res.note("info", ln.where, f"feedback '{ln.text[:60]}': EDGE centres texts on their position")
            elif word == "text" and len(toks) >= 4:
                x, y = self.cv.value(toks[1]), self.cv.value(toks[2])
                comps.append({"id": f"fb_text{len(comps) + 1}", "type": "text", "text": self.cv.text(_unquote(toks[3])),
                              "pos": self._pos(x, y), "color": color, "height": self.text_height})
            elif word == "set" and len(toks) >= 3:
                stat = self._feedback_stat(ln, saved, start_vars)
                if stat:
                    sets[stat[0]] = stat[1]
            else:
                self.res.note("unsupported", ln.where, f"feedback '{ln.text[:80]}' not converted (EDGE shows the "
                                                       "texts; charts such as xyplot are not converted)")
        if sets:
            comps.insert(0, {"id": "fb_values", "type": "variable", "set": sets})
        h = self.window["size"][1]
        comps.append({"id": "fb_continue", "type": "text", "text": "Press SPACE to continue", "pos": [0, -int(h * 0.4)],
                      "height": max(14, int(self.text_height * 0.7)), "color": "#aaaaaa"})
        comps.append({"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True})
        self.routines[rid] = {"description": f"Feedback after block {bid}", "components": comps}
        self.res.note("info", head.where, "feedback: EDGE adds 'Press SPACE to continue' at the bottom")
        if not task_names:
            self.res.note("approx", head.where, "feedback before any 'tasks' line: its values are computed from no trials")
        return rid

    def _saved_of(self, nodes: list[Any]) -> tuple[str, list[str]]:
        for n in nodes:
            if isinstance(n, dict) and n.get("loop"):
                for tname, info in self.tasks.items():
                    if n["children"] == self.task_nodes.get(tname) and info["save"]:
                        return tname, info["save"]
        return "", []

    def _feedback_stat(self, ln: Line, saved: tuple[str, list[str]], start_vars: dict[str, Any]) -> tuple[str, str] | None:
        m = re.match(r"set\s+(&{1,2}\w+|\$\w+)\s+(\w+)\s*(c\d+)?\s*(?:;\s*select\s+(.+))?$", ln.text)
        tname, cols = saved
        if not m or m.group(2).lower() not in STAT_FUNCS:
            self.res.note("unsupported", ln.where, f"feedback '{ln.text[:80]}' not converted (mean, median, count, sd, "
                                                   "min, max and sum of a saved column are)")
            return None
        if not cols:
            self.res.note("unsupported", ln.where, "feedback: the task of this block saves nothing (no save line), so "
                                                   "its columns can't be summarised")
            return None
        var = self.cv.var(re.sub(r"^[&$]+", "", m.group(1)))
        func = m.group(2).lower()

        def column(c: str) -> str | None:
            k = int(c[1:])
            return cols[k - 1] if 1 <= k <= len(cols) else None

        value = column(m.group(3)) if m.group(3) else "1"
        if value is None:
            self.res.note("unsupported", ln.where, f"feedback: {m.group(3)} is not one of the {len(cols)} saved columns")
            return None
        cond = None
        if m.group(4):
            bad = [c for c in re.findall(r"\bc\d+\b", m.group(4)) if column(c) is None]
            if bad:
                self.res.note("unsupported", ln.where, f"feedback: {', '.join(bad)} is not a saved column")
                return None
            cond = self.cv.expr(re.sub(r"\bc(\d+)\b", lambda x: f"({column('c' + x.group(1))})", m.group(4)))
        acc = f"fb{len(self.feedback_stats) + 1}_values"
        self.feedback_stats.append({"task": tname, "name": acc, "value": value, "cond": cond})
        self.cv.vars[acc] = []
        start_vars[acc] = []
        self.res.note("info", ln.where, f"feedback {func} of {value}{f' where {cond}' if cond else ''}: computed in EDGE "
                                        f"as the trials go (the list {acc})")
        value_expr = STAT_FUNCS[func].format(v=acc)
        if func in ("mean", "median", "min", "max"):          # no trial selected yet: 0, as PsyToolkit shows
            value_expr = f"{value_expr} if {acc} else 0"
        return var, "$" + value_expr

    def _set_value(self, toks: list[str], ln: Line) -> tuple[str | None, Any]:
        target = toks[1]
        if not re.fullmatch(r"&{1,2}\w+|\$\w+", target):
            self.res.note("unsupported", ln.where, f"'{ln.text[:80]}': set needs a variable (&name or $name)")
            return None, None
        var = self.cv.var(re.sub(r"^[&$]+", "", target))
        rest = toks[2:]
        op = rest[0].lower()
        if op in ("increase", "decrease"):
            step = self.cv.value(rest[1]) if len(rest) > 1 else 1
            step_s = step[1:] if isinstance(step, str) and step.startswith("$") else repr(step)
            return var, f"${var} {'+' if op == 'increase' else '-'} {step_s}"
        if op == "random" and len(rest) >= 2:
            if rest[1].lower() == "from":
                vals = [self.cv.value(t) for t in rest[2:]]
                return var, "$random.choice([" + ", ".join(v[1:] if isinstance(v, str) and v.startswith("$")
                                                          else repr(v) for v in vals) + "])"
            if len(rest) >= 3:
                a, b = (self.cv.value(t) for t in rest[1:3])
                a_s = a[1:] if isinstance(a, str) else repr(a)
                b_s = b[1:] if isinstance(b, str) else repr(b)
                return var, f"$random.randint({a_s}, {b_s})"
        if op == "expression":
            return var, "$" + self.cv.expr(" ".join(rest[1:]))
        if op == "timestamp":
            self.res.note("approx", ln.where, "set … timestamp: EDGE uses the time on the screen (t) in seconds")
            return var, "$round(t * 1000)"
        if len(rest) == 1:
            return var, self.cv.value(rest[0])
        return var, "$" + self.cv.expr(" ".join(rest))

    def _pos(self, x: Any, y: Any) -> Any:
        """PsyToolkit's y grows downwards, EDGE's upwards."""
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return [x, -y]
        xs = x[1:] if isinstance(x, str) else repr(x)
        ys = repr(-y) if isinstance(y, (int, float)) else f"-({y[1:]})"
        return f"$[{xs}, {ys}]"

    # ---------------------------------------------------------- the whole script
    def convert(self) -> ImportResult:
        sections = _sections(_lines(self.text, self.src, self.res), self.res)
        if not any(s["kind"] == "task" for s in sections):
            self.res.note("unsupported", "flow", "the script has no task section")
        for s in sections:            # definitions first: tasks may use bitmaps and tables defined after them
            if s["kind"] == "options":
                self.options(s)
            elif s["kind"] == "fonts":
                self.fonts_section(s)
            elif s["kind"] == "part":
                self.parts[s["name"]] = s["body"]
        for s in sections:
            if s["kind"] == "bitmaps":
                self.media(s, self.bitmaps, self.bitmapdir, IMAGE_EXT, "picture")
            elif s["kind"] == "sounds":
                self.media(s, self.sounds, self.sounddir, SOUND_EXT, "sound")
            elif s["kind"] == "table":
                self.table(s)
            elif s["kind"] == "videos":
                self.res.note("unsupported", s["line"].where, "videos are not converted: add movie items by hand")
        for s in sections:
            if s["kind"] == "task":
                self.task(s)
        blocks = [s for s in sections if s["kind"] == "block"]
        orders = [s for s in sections if s["kind"] == "blockorder"]
        flow: list[Any] = []
        by_name = {b["name"]: b for b in blocks}
        if orders:
            if len(orders) > 1:
                self.res.note("approx", orders[1]["line"].where, f"{len(orders)} blockorders: PsyToolkit gives each "
                              "participant one of them at random; EDGE runs the first (use a workflow or an "
                              "if/otherwise on the participant number for the others)")
            names = [ln.text.split()[0] for ln in orders[0]["body"]]
            for m in [s for s in sections if s["kind"] == "message"]:
                flow.append(self.message(m["args"], m["line"], "message"))
            for i, n in enumerate(names, 1):
                if n not in by_name:
                    self.res.note("unsupported", orders[0]["line"].where, f"blockorder names '{n}', which is not a block")
                    continue
                flow += self.block(by_name[n], i)
        else:
            i = 0
            for s in sections:
                if s["kind"] == "message":
                    flow.append(self.message(s["args"], s["line"], "message"))
                elif s["kind"] == "block":
                    i += 1
                    flow += self.block(s, i)
        if not blocks and self.tasks:
            first = next(iter(self.tasks))
            self.res.note("approx", "flow", f"the script has no block: EDGE runs task {first} once for each row of its "
                                            "table (add a block with 'tasks <name> <n>' for more)")
            flow += self._tasks_line("main", ["tasks", first], self.tasks[first]["line"], None)
        self._fill_accumulators()
        variables = {k: v for k, v in self.cv.vars.items()}
        for c in sorted(self.cv.columns):
            if not any(f"col{c}" in r for rows in self.tables.values() for r in rows):
                self.res.note("approx", "tables", f"@{c} is used, but no table has a column {c}")
                variables.setdefault(f"col{c}", 0)
        name = self.res.source.stem
        if name.lower() in ("code", "script", "experiment") and self.src.files is None:
            name = self.res.source.parent.name or name
        settings: dict[str, Any] = {"window": self.window}
        self.res.doc = {"name": ident(name), "description": f"Imported from PsyToolkit ({self.res.source.name})",
                        "settings": settings, "devices": [], "variables": variables, "routines": self.routines,
                        "flow": flow}
        self._measures()
        return self.res

    def _fill_accumulators(self) -> None:
        for acc in self.feedback_stats:
            info = self.tasks.get(acc["task"])
            if not info or not info.get("save_routine"):
                continue
            value = self.cv.expr(acc["value"])
            cond = acc["cond"]
            expr = f"${acc['name']} + [{value}] if ({cond}) else {acc['name']}" if cond else f"${acc['name']} + [{value}]"
            comps = self.routines[info["save_routine"]]["components"]
            comps.append({"id": self._free_id(comps, f"{acc['name']}_add"), "type": "variable", "when": "end",
                          "set": {acc["name"]: expr}})

    @staticmethod
    def _free_id(comps: list[dict[str, Any]], base: str) -> str:
        taken = {c.get("id") for c in comps}
        cand, i = base, 2
        while cand in taken:
            cand, i = f"{base}_{i}", i + 1
        return cand

    def _measures(self) -> None:
        """Declare the outcomes of each response so EDGE's summaries are meaningful."""
        measures, seen = [], set()
        for rid, r in self.routines.items():
            for c in r.get("components") or []:
                if c.get("type") in ("keyboard", "mouse") and c.get("correct") is not None and c["id"] not in seen:
                    seen.add(c["id"])
                    measures.append({"id": f"{c['id']}_rt", "label": f"Reaction time ({c['id']})", "role": "outcome",
                                     "column": f"{c['id']}.rt", "trials": f"${c['id']}.corr == 1", "summary": "median",
                                     "units": "s"})
                    measures.append({"id": f"{c['id']}_accuracy", "label": f"Accuracy ({c['id']})", "role": "outcome",
                                     "column": f"{c['id']}.corr", "summary": "proportion"})
        if measures:
            self.res.doc["measures"] = measures


class _Seq:
    """Turns one task's statements into screens (routines) and if/otherwise nodes, keeping the timing."""

    def __init__(self, conv: Converter, task: str, info: dict[str, Any], visible: dict[int, dict[str, Any]] | None = None,
                 shown: dict[int, str] | None = None, counter: list[int] | None = None):
        self.c, self.task, self.info = conv, task, info
        self.nodes: list[Any] = []
        self.comps: list[dict[str, Any]] = []
        self.t = Time()
        self.visible: dict[int, dict[str, Any]] = {}     # show number -> {comp, start}
        self.shown = shown if shown is not None else {}  # show number -> component id (for readmouse, clear)
        self.counter = counter if counter is not None else [0]
        self.order: list[int] = []
        self.first = True                                # no screen made yet
        self.top = True                                  # the task itself (not one part of an if)
        self.carried: set[str] = set()                   # ids of stimuli carried over from the screen before
        self.cond: str | None = None                     # inside a simple if: the condition of what is shown
        for k, v in (visible or {}).items():
            self._carry(k, v)

    # ---------------------------------------------------------- screens
    def _carry(self, k: int, v: dict[str, Any]) -> None:
        comp = {kk: vv for kk, vv in v["comp"].items() if kk not in ("start", "duration")}
        comp["id"] = self._unique(comp["id"])
        self.comps.append(comp)
        self.carried.add(comp["id"])
        self.visible[k] = {"comp": comp, "start": Time()}
        self.order.append(k)

    def _unique(self, base: str) -> str:
        taken = {c.get("id") for c in self.comps}
        cand, i = base, 2
        while cand in taken or cand.startswith("col") and cand[3:].isdigit():
            cand, i = f"{base}_{i}", i + 1
        return cand

    def _nothing_new(self) -> bool:
        """Nothing happened on this screen yet: no time passed, only stimuli still visible from the one before."""
        return self.t.zero and all(c["id"] in self.carried for c in self.comps)

    def close(self, duration: bool = True) -> str | None:
        """End the current screen; returns its routine id (None when nothing happened on it)."""
        if self._nothing_new():
            return None
        rid = self.c.rids.make(self.task if self.first else f"{self.task}_{len(self.nodes) + 1}", "screen")
        routine: dict[str, Any] = {"components": self.comps}
        if duration:
            routine["duration"] = self.t.seconds()
        if self.first and self.top and "TRIALCOUNT" in self.c.text:
            self.comps.insert(0, {"id": "trial_count", "type": "variable", "set": {"TRIALCOUNT": "$TRIALCOUNT + 1"}})
            self.c.cv.vars.setdefault("TRIALCOUNT", 0)
        self.first = False
        self.c.routines[rid] = routine
        self.nodes.append(rid)
        self.c.res.count("routines")
        remaining = {k: self.visible[k] for k in self.order if k in self.visible}
        self.comps, self.t, self.visible, self.order, self.carried = [], Time(), {}, [], set()
        for k, v in remaining.items():
            self._carry(k, v)
        return rid

    def _last_routine(self) -> str | None:
        return self.nodes[-1] if self.nodes and isinstance(self.nodes[-1], str) else None

    def instant(self, comp: dict[str, Any]) -> None:
        """A variable change: at the end of the screen before when nothing happened since, else as this one starts."""
        last = self._last_routine()
        if last and self._nothing_new():
            comps = self.c.routines[last]["components"]
            comp["id"] = Converter._free_id(comps, comp["id"])
            comp["when"] = "end"
            comps.append(comp)
            return
        comp["id"] = self._unique(comp["id"])
        self.comps.append(comp)

    def finish(self) -> list[Any]:
        # what is still on the screen at the end of the trial is not carried into the next one
        self.close()
        return self.nodes

    # ---------------------------------------------------------- statements
    def run(self, stmts: list[Any]) -> None:
        for st in stmts:
            if isinstance(st, dict) and "if" in st:
                self.branch(st)
            elif isinstance(st, dict) and "while" in st:
                self.c.res.note("unsupported", st["while"].where, f"'{st['while'].text[:60]}' … while-end: loops "
                                "inside a trial are not converted (use a trial list with 'stop early when', or a rule)")
            else:
                self.statement(st)

    INLINE = {"show", "set", "sound", "font"}

    def branch(self, st: dict[str, Any]) -> None:
        ln: Line = st["if"]
        cond = self.c.cv.expr(ln.text.split(None, 1)[1] if len(ln.text.split()) > 1 else "True")
        simple = all(isinstance(x, Line) and x.text.split()[0].lower() in self.INLINE for x in st["then"] + st["else"])
        if simple and self.cond is None:
            # only things that appear (and variables): items of this screen shown only when the condition holds,
            # so a delay after fi keeps them on the screen as in PsyToolkit
            for key, c in (("then", cond), ("else", f"not ({cond})")):
                self.cond = c
                try:
                    for x in st[key]:
                        self.statement(x)
                finally:
                    self.cond = None
            self.c.res.count("conditional items")
            return
        visible = {k: self.visible[k] for k in self.order if k in self.visible}
        self.close()
        parts = {}
        for key in ("then", "else"):
            if key == "else" and not st["else"]:
                continue
            sub = _Seq(self.c, f"{self.task}_{_branch_name(cond) if key == 'then' else 'otherwise'}", self.info,
                       visible, self.shown, self.counter)
            sub.top = False
            sub.run(st[key])
            if [k for k in sub.order if k in sub.visible and k not in visible]:
                self.c.res.note("approx", ln.where, "something shown inside if … fi stays on the screen in PsyToolkit "
                                                    "until it is cleared; in EDGE it is shown on that screen only")
            sub.visible = {k: v for k, v in sub.visible.items() if k in visible}
            sub.order = [k for k in sub.order if k in sub.visible]
            still = set(sub.visible)
            sub.close()
            parts[key] = (sub.nodes, still)
        node: dict[str, Any] = {"if": "$" + cond, "then": parts["then"][0]}
        if "else" in parts:
            node["else"] = parts["else"][0]
        if node["then"] or node.get("else"):
            self.nodes.append(node)
            self.c.res.count("if/otherwise")
        # stimuli shown before the if and cleared in neither part are still there afterwards
        stay = parts["then"][1] & (parts["else"][1] if "else" in parts else set(visible))
        self.comps, self.visible, self.order, self.carried = [], {}, [], set()
        for k in [k for k in visible if k in stay]:
            self._carry(k, visible[k])

    def statement(self, ln: Line) -> None:
        toks = _tokens(ln.text)
        word = toks[0].lower()
        cv, res = self.c.cv, self.c.res
        if word == "keys":
            self.info["keys"] = [key_name(_unquote(k)) for k in toks[1:]]
        elif word == "table" and len(toks) > 1:
            if toks[1] not in self.c.tables:
                res.note("unsupported", ln.where, f"table {toks[1]} is not defined in the script")
            self.info["table"] = toks[1]
        elif word == "font" and len(toks) > 1:
            if toks[1] in self.c.fonts:
                self.c.text_height = self.c.fonts[toks[1]]
        elif word == "show" and len(toks) > 1:
            self.show(toks, ln)
        elif word in ("clear", "hide") and len(toks) > 1:
            self.clear(toks, ln)
        elif word == "unhide":
            res.note("unsupported", ln.where, "unhide: show the stimulus again with its own show line")
        elif word == "delay" and len(toks) > 1:
            v = cv.value(toks[1])
            self.t = self.t.plus(v if isinstance(v, (int, float)) else v[1:])
        elif word == "sound" and len(toks) > 1:
            name = toks[1]
            f = self.c.sounds.get(name) or self.c._file(name, self.c.sounddir, SOUND_EXT, ln.where, "sound")
            comp = {"id": self._unique(f"sound_{ident(name)}"), "type": "sound", "sound": f}
            if self.cond:
                comp["if"] = "$" + self.cond
            if not self.t.zero:
                comp["start"] = self.t.seconds()
            self.comps.append(comp)
        elif word == "readkey":
            self.readkey(toks, ln)
        elif word == "readmouse":
            self.readmouse(toks, ln)
        elif word == "set" and len(toks) >= 3:
            var, val = self.c._set_value(toks, ln)
            if var and self.cond:
                val = f"$({_e(val)}) if ({self.cond}) else {var}"
            if var:
                self.instant({"id": f"set_{var}", "type": "variable", "set": {var: val}})
        elif word == "save":
            self.save(toks, ln)
        elif word == "error":
            res.note("approx", ln.where, "error: EDGE records whether each answer was right (resp.corr) and the "
                                         "PsyToolkit STATUS; the trial is not repeated")
        elif word == "part":
            res.note("unsupported", ln.where, f"part {toks[1] if len(toks) > 1 else ''} is not defined")
        elif word in ("else", "fi", "while-end"):
            res.note("approx", ln.where, f"'{word}' without its if / while")
        elif word == "readkeys":
            res.note("unsupported", ln.where, "readkeys (typed answers) is not converted: add a text-entry item")
        else:
            res.note("unsupported", ln.where, f"task {self.task}: '{ln.text[:80]}' not converted")

    def show(self, toks: list[str], ln: Line) -> None:
        cv = self.c.cv
        kind = toks[1].lower()
        self.counter[0] += 1
        n = self.counter[0]
        args = toks[2:]
        comp: dict[str, Any]
        if kind == "bitmap" and args:
            what = args[0]
            if what.startswith("@") or what.startswith("&") or what.startswith("$"):
                col = cv.value(what)
                names = sorted(self.c.bitmaps)
                image = "$" + "{" + ", ".join(f"{k!r}: {self.c.bitmaps[k]!r}" for k in names) + "}" + f".get({col[1:]}, {col[1:]})" \
                    if names else col
                cid = "picture"
            else:
                image = self.c.bitmaps.get(what) or self.c._file(what, self.c.bitmapdir, IMAGE_EXT, ln.where, "picture")
                self.c.bitmaps.setdefault(what, image)
                cid = ident(what)
            comp = {"id": cid, "type": "image", "image": image}
            pos = args[1:3]
        elif kind == "text" and args:
            comp = {"id": "text", "type": "text", "text": cv.text(_unquote(args[0])) if args[0].startswith('"')
                    else cv.value(args[0]), "height": self.c.text_height}
            pos = args[1:3]
            col = cv.color(args[3:6]) if len(args) >= 6 else (cv.color(args[3:4]) if len(args) == 4 else None)
            comp["color"] = col or "white"
        elif kind in ("rectangle", "rect") and len(args) >= 4:
            w, h = cv.value(args[2]), cv.value(args[3])
            comp = {"id": "rectangle", "type": "shape", "shape": "rect", "size": [w, h] if all(
                isinstance(v, (int, float)) for v in (w, h)) else f"$[{_e(w)}, {_e(h)}]",
                "fill": cv.color(args[4:7]) or "white"}
            pos = args[0:2]
        elif kind == "circle" and len(args) >= 3:
            comp = {"id": "circle", "type": "shape", "shape": "circle", "radius": cv.value(args[2]),
                    "fill": cv.color(args[3:6]) or "white"}
            pos = args[0:2]
        else:
            self.c.res.note("unsupported", ln.where, f"'{ln.text[:80]}' not converted (show bitmap, text, rectangle "
                                                     "and circle are)")
            return
        if len(pos) == 2:
            x, y = cv.value(pos[0]), cv.value(pos[1])
            if (x, y) != (0, 0):
                comp["pos"] = self.c._pos(x, y)
        comp["id"] = self._unique(comp["id"])
        if self.cond:
            comp["if"] = "$" + self.cond
        if not self.t.zero:
            comp["start"] = self.t.seconds()
        self.comps.append(comp)
        self.visible[n] = {"comp": comp, "start": self.t}
        self.order.append(n)
        self.shown[n] = comp["id"]

    def clear(self, toks: list[str], ln: Line) -> None:
        arg = toks[1].lower()
        if arg == "screen":
            targets = list(self.visible)
        elif arg == "range" and len(toks) >= 4 and _num(toks[2]) and _num(toks[3]):
            targets = [k for k in self.visible if int(_num(toks[2])) <= k <= int(_num(toks[3]))]
        elif _num(arg) is not None and int(_num(arg)) < 0:
            k = -int(_num(arg))
            targets = [self.order[-k]] if len(self.order) >= k else []
        else:
            targets = [int(_num(t)) for t in toks[1:] if _num(t) is not None]
            if not targets:
                self.c.res.note("unsupported", ln.where, f"'{ln.text[:60]}' not converted")
                return
        for k in targets:
            v = self.visible.pop(k, None)
            if v is None:
                continue
            self.order.remove(k)
            d = self.t.minus(v["start"])
            if d.zero and v["comp"]["id"] in self.carried:      # carried over and cleared at once: not shown here
                self.comps = [c for c in self.comps if c is not v["comp"]]
                self.carried.discard(v["comp"]["id"])
                continue
            v["comp"]["duration"] = d.seconds()

    def _correct_key(self, t: str, keys: list[str], ln: Line) -> Any:
        if _num(t) is not None:
            i = int(_num(t))
            if 1 <= i <= len(keys):
                return keys[i - 1]
            self.c.res.note("approx", ln.where, f"readkey {t}: there is no key number {t} in 'keys {' '.join(keys)}'")
            return None
        v = self.c.cv.value(t)
        if isinstance(v, str) and v.startswith("$"):
            return f"${keys!r}[int({v[1:]}) - 1]"
        return None

    def readkey(self, toks: list[str], ln: Line) -> None:
        keys = self.info["keys"]
        if not keys:
            self.c.res.note("approx", ln.where, "readkey before a 'keys' line: any key is accepted")
        comp: dict[str, Any] = {"id": "resp", "type": "keyboard", "end_routine": True}
        if keys:
            comp["keys"] = list(keys)
        if len(toks) > 1:
            corr = self._correct_key(toks[1], keys, ln)
            if corr is not None:
                comp["correct"] = corr
        timeout = self.c.cv.value(toks[2]) if len(toks) > 2 else None
        if not self.t.zero:
            comp["start"] = self.t.seconds()
        if isinstance(timeout, (int, float)):
            comp["duration"] = _ms_to_s(timeout)
        elif isinstance(timeout, str):
            comp["duration"] = f"$({timeout[1:]}) / 1000"
        self._respond(comp, "keys", timeout)

    def readmouse(self, toks: list[str], ln: Line) -> None:
        args = toks[1:]
        if args and args[0].lower() in ("l", "r", "m", "left", "right", "middle"):
            button = {"l": "left", "r": "right", "m": "middle"}.get(args[0].lower(), args[0].lower())
            args = args[1:]
        else:
            button = "left"
        target = args[0] if args else None
        timeout = self.c.cv.value(args[1]) if len(args) > 1 else None
        rng = args[args.index("range") + 1:args.index("range") + 3] if "range" in args else None
        visible_ids = [self.visible[k]["comp"]["id"] for k in self.order if k in self.visible]
        if rng and all(_num(x) for x in rng):
            lo, hi = int(_num(rng[0])), int(_num(rng[1]))
            clickable = [self.shown[k] for k in range(lo, hi + 1) if k in self.shown and self.shown[k] in visible_ids]
        else:
            clickable = visible_ids
        comp: dict[str, Any] = {"id": "click", "type": "mouse", "end_routine": True}
        if button != "left":
            comp["buttons"] = [button]
        if target is not None and _num(target) is not None:
            tid = self.shown.get(int(_num(target)))
            if tid and tid in visible_ids:
                comp["correct"] = tid
                if tid not in clickable:
                    clickable.append(tid)
            else:
                self.c.res.note("approx", ln.where, f"readmouse: stimulus {target} is not on the screen here; any "
                                                    "click ends the screen")
        elif target is not None:
            v = self.c.cv.value(target)
            ids = [self.shown.get(k) for k in range(1, self.counter[0] + 1)]
            comp["correct"] = f"${ids!r}[int({v[1:] if isinstance(v, str) else v}) - 1]"
        if clickable:
            comp["clickable"] = clickable
        if not self.t.zero:
            comp["start"] = self.t.seconds()
        if isinstance(timeout, (int, float)):
            comp["duration"] = _ms_to_s(timeout)
        elif isinstance(timeout, str):
            comp["duration"] = f"$({timeout[1:]}) / 1000"
        self._respond(comp, "clicked", timeout)

    def _respond(self, comp: dict[str, Any], answered: str, timeout: Any) -> None:
        comp["id"] = self._unique(comp["id"])
        r = comp["id"]
        self.comps.append(comp)
        to = timeout if isinstance(timeout, (int, float)) else (timeout[1:] if isinstance(timeout, str) else 0)
        sets: dict[str, Any] = {"RT": f"$round({r}.rt * 1000) if {r}.rt is not None else {to}"}
        if comp.get("correct") is not None:
            sets["STATUS"] = f"$1 if {r}.corr else (3 if not {r}.{answered} else 2)"
        else:
            sets["STATUS"] = f"$3 if not {r}.{answered} else 1"
        if answered == "keys" and comp.get("keys"):
            sets["KEY"] = f"$({comp['keys']!r}.index({r}.keys) + 1) if {r}.keys in {comp['keys']!r} else 0"
        for k in sets:
            self.c.cv.vars.setdefault(k, SYSTEM_VARS[k])
        self.comps.append({"id": self._unique("psytoolkit_status"), "type": "variable", "when": "end", "set": sets})
        # the screen ends with the answer; what is still visible carries on in the next one
        self.close(duration=False)

    def save(self, toks: list[str], ln: Line) -> None:
        names = []
        for t in toks[1:]:
            v = self.c.cv.value(t)
            names.append(v[1:] if isinstance(v, str) and v.startswith("$") else repr(v))
        self.info["save"] = names
        rid = self._last_routine() if self._nothing_new() else None
        if rid is None:
            rid = self.close()
        self.info["save_routine"] = rid
        self.c.res.note("info", ln.where, "save: EDGE records every response, the trial list's columns and the "
                                          f"variables ({', '.join(names)}) in each data row")


def _branch_name(cond: str) -> str:
    m = re.fullmatch(r"STATUS\s*(==|!=)\s*([123])", cond.strip())
    if not m:
        return "if"
    word = {"1": "correct", "2": "wrong", "3": "timeout"}[m.group(2)]
    return word if m.group(1) == "==" else f"not_{word}"


def _e(v: Any) -> str:
    return v[1:] if isinstance(v, str) and v.startswith("$") else repr(v)


def import_psytoolkit(path: Path) -> ImportResult:
    conv = Converter(path)
    if not looks_like_psytoolkit_text(conv.text) and not conv.text.strip():
        raise ImportError_(f"{path.name} is empty")
    return conv.convert()
