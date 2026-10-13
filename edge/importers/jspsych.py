"""jsPsych importer (v6 and v7 timelines in .html or .js files).

A small tolerant parser reads JavaScript object/array literals (unquoted keys, single/
double/template quotes, comments, trailing commas, references to variables declared in
the same file, ``jsPsych.timelineVariable('x')``). Functions can't be translated; they are
listed in the report. Plugin mapping:

* html/image/audio-keyboard-response -> text (or image/sound) + keyboard, durations in seconds
* html-button-response, survey-likert, survey-text, survey-multi-choice, survey-multi-select,
  survey-html-form, instructions -> EDGE ``html`` components with real HTML forms
* fullscreen -> window setting; preload/call-function -> skipped (noted)
* nested ``timeline`` + ``timeline_variables`` + ``randomize_order`` / ``repetitions`` -> loops
"""

from __future__ import annotations

import html as htmllib
import re
from pathlib import Path
from typing import Any

from .base import Ids, ImportResult, has_html, html_to_text, ident, key_name, ms, read_text


# =========================================================================== JS literal parser
class Ref:
    """Reference to a JS identifier or member expression (e.g. jsPsychHtmlKeyboardResponse)."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"Ref({self.name})"


class Call:
    def __init__(self, name: str, args: list[Any]):
        self.name, self.args = name, args


class Func:
    def __init__(self, src: str):
        self.src = src


class JSParser:
    def __init__(self, src: str):
        self.s = src
        self.i = 0

    def ws(self) -> None:
        s = self.s
        while self.i < len(s):
            if s[self.i].isspace():
                self.i += 1
            elif s.startswith("//", self.i):
                j = s.find("\n", self.i)
                self.i = len(s) if j < 0 else j
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                self.i = len(s) if j < 0 else j + 2
            else:
                break

    def peek(self) -> str:
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def value(self) -> Any:
        c = self.peek()
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "'\"`":
            return self.string()
        if c == "-" or c.isdigit() or (c == "." and self.s[self.i + 1:self.i + 2].isdigit()):
            m = re.match(r"-?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", self.s[self.i:])
            self.i += m.end()
            t = m.group(0)
            return float(t) if any(x in t for x in ".eE") else int(t)
        if self.s.startswith("function", self.i) or self.s.startswith("async", self.i):
            return self.func()
        if c == "(":   # arrow function or parenthesized
            start = self.i
            depth = 0
            while self.i < len(self.s):
                ch = self.s[self.i]
                depth += ch == "("
                depth -= ch == ")"
                self.i += 1
                if depth == 0:
                    break
            self.ws()
            if self.s.startswith("=>", self.i):
                self.i = start
                return self.func()
            return Func(self.s[start:self.i])
        m = re.match(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", self.s[self.i:])
        if not m:
            raise ValueError(f"unexpected character {c!r} at {self.i}")
        name = m.group(0)
        self.i += m.end()
        self.ws()
        if self.s.startswith("=>", self.i):
            self.i -= len(name)
            return self.func()
        if name in ("true", "false"):
            return name == "true"
        if name in ("null", "undefined"):
            return None
        if self.peek() == "(":
            self.i += 1
            args = []
            while self.peek() != ")":
                args.append(self.value())
                if self.peek() == ",":
                    self.i += 1
            self.i += 1
            return Call(name, args)
        if name == "new":
            return Func("new ...")
        return Ref(name)

    def func(self) -> Func:
        start = self.i
        depth, started, q = 0, False, ""
        while self.i < len(self.s):
            ch = self.s[self.i]
            if q:
                if ch == "\\":
                    self.i += 2
                    continue
                if ch == q:
                    q = ""
            elif ch in "'\"`":
                q = ch
            elif ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    self.i += 1
                    break
            elif not started and ch in ",]}\n" and "=>" in self.s[start:self.i]:
                break  # expression-bodied arrow function
            self.i += 1
        return Func(self.s[start:self.i])

    def string(self) -> str:
        q = self.s[self.i]
        self.i += 1
        out = []
        while self.i < len(self.s) and self.s[self.i] != q:
            ch = self.s[self.i]
            if ch == "\\":
                nxt = self.s[self.i + 1]
                out.append({"n": "\n", "t": "\t", "'": "'", '"': '"', "\\": "\\", "`": "`"}.get(nxt, nxt))
                self.i += 2
                continue
            out.append(ch)
            self.i += 1
        self.i += 1
        text = "".join(out)
        if q == "`" and "${" in text:
            text = re.sub(r"\$\{([^}]*)\}", r"{{\1}}", text)  # template interpolation -> placeholder
        return text

    def obj(self) -> dict[str, Any]:
        self.i += 1
        out: dict[str, Any] = {}
        while self.peek() != "}":
            c = self.peek()
            if c in "'\"":
                key = self.string()
            elif self.s.startswith("...", self.i):
                self.i += 3
                self.value()
                if self.peek() == ",":
                    self.i += 1
                continue
            else:
                m = re.match(r"[\w$]+", self.s[self.i:])
                key = m.group(0)
                self.i += m.end()
            if self.peek() == "(":   # method shorthand: on_finish(data) {...}
                out[key] = self.func()
            else:
                self.ws()
                if self.s[self.i] == ":":
                    self.i += 1
                    out[key] = self.value()
                else:
                    out[key] = Ref(key)  # shorthand property
            if self.peek() == ",":
                self.i += 1
        self.i += 1
        return out

    def arr(self) -> list[Any]:
        self.i += 1
        out = []
        while self.peek() != "]":
            out.append(self.value())
            if self.peek() == ",":
                self.i += 1
        self.i += 1
        return out


_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
# script files that are libraries, not the experiment: jsPsych itself, its plugins, common helpers
_LIBRARY = re.compile(r"jspsych|(^|/)plugin-[^/]*$|\.min\.js$|(^|/)(jquery|bootstrap|lodash|underscore|d3|papaparse|"
                      r"seedrandom|require)([.-][\w.-]*)?\.js$", re.I)


def extract_js(source: str, folder: Path | None = None, res: ImportResult | None = None) -> str:
    """The JavaScript of a page in page order: inline scripts and, when ``folder`` is given, the experiment's
    own script files next to the page (``<script src="experiment.js">``, the usual jsPsych project layout)."""
    if "<script" not in source.lower():
        return source
    parts = []
    for attrs, body in _SCRIPT.findall(source):
        m = re.search(r"\bsrc\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.I)
        if not m:
            parts.append(body)
        elif folder is not None:
            parts.append(_local_script(m.group(1), folder, res))
    return "\n".join(parts)


def _local_script(src: str, folder: Path, res: ImportResult | None) -> str:
    rel = src.split("?")[0].split("#")[0].strip()
    if not rel or re.match(r"[a-z][\w+.-]*:|//", rel, re.I) or _LIBRARY.search(rel):
        return ""                                         # online, or a library: nothing of the experiment
    f = (folder / rel).resolve()
    if folder.resolve() not in f.parents or not f.is_file():
        if res is not None:
            res.note("unsupported", "scripts", f"the page loads '{src}', which "
                     + ("was not found" if folder.resolve() in f.parents else "is outside the page's folder")
                     + ", so its code was not read: put it next to the HTML file and import again")
        return ""
    if f.stat().st_size > 2_000_000:
        if res is not None:
            res.note("approx", "scripts", f"'{src}' is too large to be the experiment's own code and was not read")
        return ""
    if res is not None:
        res.note("info", "scripts", f"read the experiment's script '{src}'")
    return read_text(f)


def collect(js: str, res: ImportResult) -> tuple[dict[str, Any], Any]:
    """Return (declared variables, the timeline passed to jsPsych.run / init)."""
    env: dict[str, Any] = {}
    pushes: dict[str, list[Any]] = {}
    for m in re.finditer(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*", js):
        p = JSParser(js)
        p.i = m.end()
        try:
            env[m.group(1)] = p.value()
        except Exception:        # a tolerant parser: code it can't read is skipped (functions are noted later)
            continue
    for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\.push\(\s*", js):
        p = JSParser(js)
        p.i = m.end()
        try:
            v = p.value()
            while p.peek() == ",":
                pushes.setdefault(m.group(1), []).append(v)
                p.i += 1
                v = p.value()
            pushes.setdefault(m.group(1), []).append(v)
        except Exception:
            continue
    for name, items in pushes.items():
        if isinstance(env.get(name), list):
            env[name] = env[name] + items
        elif name not in env:
            env[name] = items
    timeline = None
    m = re.search(r"jsPsych\.run\(\s*", js) or re.search(r"jsPsych\.init\(\s*", js)
    if m:
        p = JSParser(js)
        p.i = m.end()
        try:
            v = p.value()
        except Exception:
            v = None
        timeline = v.get("timeline") if isinstance(v, dict) else v      # init({timeline: ...}) / run(timeline)
    if timeline is None and env.get("timeline") is not None:
        timeline = env["timeline"]
        res.note("approx", "timeline", "jsPsych.run/init not found; used a variable named 'timeline'")
    return env, timeline


# =========================================================================== conversion
def _resolve(v: Any, env: dict[str, Any], depth: int = 0) -> Any:
    if depth > 30:
        return v
    if isinstance(v, Ref) and v.name in env:
        return _resolve(env[v.name], env, depth + 1)
    if isinstance(v, list):
        out = []
        for x in v:
            r = _resolve(x, env, depth + 1)
            out.append(r)
        return out
    if isinstance(v, dict):
        return {k: _resolve(x, env, depth + 1) for k, x in v.items()}
    return v


def _tv(v: Any) -> Any:
    """jsPsych.timelineVariable('x') -> $x."""
    if isinstance(v, Call) and v.name.endswith("timelineVariable") and v.args:
        return "$" + ident(str(v.args[0]))
    return v


def _plugin(t: Any) -> str:
    if isinstance(t, Ref):
        name = t.name.split(".")[-1]
        name = re.sub(r"^jsPsych", "", name)
        name = re.sub(r"Plugin$", "", name)
        return re.sub(r"(?<!^)([A-Z])", r"-\1", name).lower()
    return str(t or "")


_COMPLEX = re.compile(r"<(img|table|input|svg|canvas|video|audio|iframe)\b", re.I)
_KEYBOARD_FAMILY = ("html-keyboard-response", "image-keyboard-response", "audio-keyboard-response",
                    "html-slider-response", "image-slider-response", "video-keyboard-response")


def _deref(v: Any, env: dict[str, Any]) -> tuple[Any, str | None]:
    """Follow references to declared variables; also returns the variable's name (it names the routine or loop)."""
    name = None
    for _ in range(30):
        if not (isinstance(v, Ref) and v.name in env):
            break
        name, v = v.name, env[v.name]
    return v, name


def _choices(v: Any) -> Any:
    v = _tv(v)
    if v in ("ALL_KEYS", "allkeys", None) or (isinstance(v, Ref) and "ALL_KEYS" in v.name):
        return None
    if v in ("NO_KEYS", "none") or (isinstance(v, Ref) and "NO_KEYS" in v.name):
        return []
    if isinstance(v, list):
        return [key_name(str(k)) for k in v]
    return v


def _value_text(v: Any) -> Any:
    v = _tv(v)
    if isinstance(v, str) and "{{" in v:   # template literal interpolation
        return v
    return v


def _html_columns(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Timeline-variable columns that hold HTML (e.g. "<p style='color:blue'>BLUE</p>"): the text, and the styling a
    text component can show, go into new columns next to the original one (stimulus_text, stimulus_color), which
    still serves HTML pages. Returns {column: {"spec": text component properties, "dropped": styling not kept}}."""
    out: dict[str, dict[str, Any]] = {}
    taken = {k for r in rows for k in r}
    for col in sorted({k for r in rows for k, v in r.items() if has_html(v)}):
        parsed = [html_to_text(str(r[col])) if r.get(col) is not None else ("", {}, []) for r in rows]

        def new_col(suffix: str) -> str:
            name, i = f"{col}_{suffix}", 2
            while name in taken:
                name, i = f"{col}_{suffix}{i}", i + 1
            taken.add(name)
            return name

        tcol = new_col("text")
        for r, (text, _, _) in zip(rows, parsed):
            r[tcol] = text
        spec: dict[str, Any] = {"text": "$" + tcol}
        for prop, default in (("color", "black"), ("height", 40), ("bold", False), ("italic", False)):
            vals = [st.get(prop) for _, st, _ in parsed]
            if all(v is None for v in vals):
                continue
            if len({repr(v) for v in vals}) == 1:
                spec[prop] = vals[0]
            else:                                  # differs between rows: a column of its own
                pcol = new_col(prop)
                for r, v in zip(rows, vals):
                    r[pcol] = default if v is None else v
                spec[prop] = "$" + pcol
        out[col] = {"spec": spec, "dropped": sorted({d for _, _, ds in parsed for d in ds})}
    return out


class _Conv:
    def __init__(self, res: ImportResult, env: dict[str, Any]):
        self.res, self.env = res, env
        self.ids = Ids()
        self.routines: dict[str, Any] = {}
        self.data: dict[str, dict[str, Any]] = {}     # routine -> the jsPsych 'data' fields saved with it
        self.tv_stack: list[tuple[set[str], dict[str, dict[str, Any]]]] = []   # enclosing timeline variables
        self.noted_columns: set[str] = set()
        self.pages = 0
        self.fullscreen = False

    def page(self, body: str, rid: str) -> str:
        self.pages += 1
        rel = f"pages/{rid}.html"
        self.res.generated_files[rel] = (
            "<!doctype html><html><head><meta charset='utf-8'><style>body{font:20px/1.5 system-ui,sans-serif;"
            "max-width:900px;margin:40px auto;padding:0 20px;text-align:center}"
            "label{margin:0 8px}button{font-size:18px;padding:8px 20px;margin:6px}</style></head><body>"
            + body + "</body></html>")
        return rel

    def tv_column(self, col: str) -> dict[str, Any] | None:
        """How a text component shows timeline variable ``col``: {} for plain text, None when its values are unknown."""
        for cols, html in reversed(self.tv_stack):
            if col in cols:
                return html.get(col, {})
        return None

    def text_stim(self, stim: Any, w: str) -> dict[str, Any]:
        c: dict[str, Any] = {"id": "stim", "type": "text"}
        if isinstance(stim, str) and not stim.startswith("$"):
            text, style, dropped = html_to_text(stim)
            c.update(text=_placeholders(text), **style)
            if _COMPLEX.search(stim):
                self.res.note("approx", w, "HTML stimulus with images/tables shown as text; consider an html component")
            if dropped:
                self.res.note("approx", w, f"stimulus styling not kept: {', '.join(dropped)}")
        elif isinstance(stim, str):                              # a timeline variable
            col = stim[1:]
            info = self.tv_column(col)
            if info is None:
                c["text"] = stim
                self.res.note("approx", w, f"the stimulus comes from timeline variable '{col}', whose values are not "
                              "in this file: if they hold HTML, its tags will be shown as text")
            elif info:
                c.update(info["spec"])
                if col not in self.noted_columns:
                    self.noted_columns.add(col)
                    new = [v[1:] for v in info["spec"].values() if str(v).startswith("$")]
                    self.res.note("info", w, f"timeline variable '{col}' holds HTML: its text and styling were put in "
                                  f"the columns {', '.join(new)}")
                if info["dropped"]:
                    self.res.note("approx", w, f"stimulus styling not kept: {', '.join(info['dropped'])}")
            else:
                c["text"] = stim
        elif isinstance(stim, (int, float)) and not isinstance(stim, bool):
            c["text"] = str(stim)
        # a function is not converted (noted with the trial's other functions): the text is left to fill in
        return c

    def keep_data(self, t: dict[str, Any], rids: list[str], w: str) -> None:
        """jsPsych's per-trial ``data`` (task: 'response' …) is saved with each of the trial's routines."""
        data = t.get("data")
        if not isinstance(data, dict):
            return
        fields: dict[str, Any] = {}
        for k, v in data.items():
            v, key = _tv(v), ident(k)
            if isinstance(v, (Func, Ref, Call)):
                self.res.note("unsupported", w, f"data field '{k}' is computed by JavaScript and was not saved")
            elif isinstance(v, dict) or (isinstance(v, list) and not all(isinstance(x, (str, int, float, bool))
                                                                         for x in v)):
                self.res.note("approx", w, f"data field '{k}' holds nested values and was not saved")
            elif v != f"${key}":       # a timeline variable of the same name is saved with every trial anyway
                fields[key] = v
        for rid in rids:
            self.data[rid] = fields

    def trial(self, t: dict[str, Any], where: str, hint: str | None = None) -> list[Any]:
        t = {k: _tv(v) for k, v in _resolve(t, self.env).items()}
        plugin = _plugin(t.get("type"))
        rid = self.ids.make(t.get("name") or hint or plugin.replace("-", "_") or "trial", "trial")
        page_ids: list[str] = []
        if plugin == "instructions":
            pages = t.get("pages") or []
            pages = pages if isinstance(pages, list) else [pages]
            page_ids = [self.ids.make(f"{rid}_p{i + 1}") for i in range(len(pages))]
        w = f"routines.{page_ids[0] if page_ids else rid}"
        handled = {"on_load", "conditional_function"} | ({"trial_duration"} if plugin in _KEYBOARD_FAMILY else set())
        for k, v in t.items():
            if isinstance(v, Func) and k not in handled:
                self.res.note("unsupported", w, f"'{k}' is a JavaScript function and was not converted"
                              + ("; write what it shows in the stimulus component" if k == "stimulus" else ""))
        comps: list[dict[str, Any]] = []
        routine: dict[str, Any] = {"components": comps}
        stim = _value_text(t.get("stimulus", ""))
        if plugin in _KEYBOARD_FAMILY:
            if plugin.startswith("html"):
                comps.append(self.text_stim(stim, w))
            elif plugin.startswith("image"):
                c = {"id": "stim", "type": "image", "image": stim}
                if t.get("stimulus_width") and t.get("stimulus_height"):
                    c["size"] = [t["stimulus_width"], t["stimulus_height"]]
                comps.append(c)
                if isinstance(stim, str) and not stim.startswith("$"):
                    self.res.assets.add(stim)
            elif plugin.startswith("audio"):
                comps.append({"id": "stim", "type": "sound", "sound": stim})
                if isinstance(stim, str) and not stim.startswith("$"):
                    self.res.assets.add(stim)
            elif plugin.startswith("video"):
                self.res.note("unsupported", w, "video stimuli are not supported yet")
            if t.get("stimulus_duration") is not None and comps:
                comps[0]["duration"] = ms(t["stimulus_duration"])
            if "slider" in plugin:
                comps.append({"id": "resp", "type": "slider", "ticks": [t.get("min", 0), t.get("max", 100)],
                              "granularity": t.get("step", 1), "require_confirm": True, "end_routine": True,
                              "labels": t.get("labels", [])})
            else:
                choices = _choices(t.get("choices", "ALL_KEYS"))
                if choices != []:
                    k: dict[str, Any] = {"id": "resp", "type": "keyboard"}
                    if choices:
                        k["keys"] = choices
                    data = t.get("data") if isinstance(t.get("data"), dict) else {}
                    for ck in ("correct_response", "correct", "correct_key", "answer"):
                        if ck in data:
                            k["correct"] = _tv(data[ck]) if not isinstance(data[ck], str) or data[ck].startswith("$") \
                                else key_name(data[ck])
                    if t.get("response_ends_trial", True) is not False:
                        k["end_routine"] = True
                    comps.append(k)
            if t.get("prompt"):
                ptext, pstyle, _ = html_to_text(str(t["prompt"]))
                comps.append({"id": "prompt", "type": "text", "text": _placeholders(ptext), "pos": [0, -200],
                              "height": 24, **{k: v for k, v in pstyle.items() if k != "height"}})
            td = t.get("trial_duration")
            if isinstance(td, Func):
                routine["duration"] = 0.5
                self.res.note("approx", w, "trial_duration is computed by a JavaScript function, which was not "
                              "converted; set to 0.5 s. For a random duration use e.g. $random.choice([0.25, 0.5])")
            elif td is not None:
                routine["duration"] = ms(td) if not isinstance(td, str) else td
            elif not any(c.get("end_routine") for c in comps):
                routine["duration"] = 1.0
                self.res.note("approx", w, "trial has no duration and no response; set to 1 s")
        elif plugin in ("html-button-response", "image-button-response"):
            choices = t.get("choices") or ["Continue"]
            stim_html = f"<img src='{stim}'>" if plugin.startswith("image") else str(stim)
            if plugin.startswith("image") and isinstance(stim, str) and not stim.startswith("$"):
                self.res.assets.add(stim)
            buttons = "".join(f"<button type='submit' name='response' value='{i}'>{htmllib.escape(str(c))}</button>"
                              for i, c in enumerate(choices if isinstance(choices, list) else [choices]))
            prompt = str(t.get("prompt") or "")
            comps.append({"id": "page", "type": "html", "end_routine": True,
                          "file": self.page(f"<div>{_tpl(stim_html)}</div><form>{buttons}</form>{prompt}", rid)})
            if t.get("trial_duration") is not None and not isinstance(t["trial_duration"], Func):
                routine["duration"] = ms(t["trial_duration"])
        elif plugin == "instructions":
            for prid, pg in zip(page_ids, pages):
                self.routines[prid] = {"components": [{"id": "page", "type": "html", "end_routine": True,
                                                       "file": self.page(_tpl(str(pg)), prid)}]}
            self.res.count("routines", len(page_ids))
            if t.get("allow_backward", True) and page_ids:
                self.res.note("approx", w, f"instruction pages ({', '.join(page_ids)}) are shown forward only")
            self.keep_data(t, page_ids, w)
            return page_ids
        elif plugin.startswith("survey"):
            comps.append({"id": "survey", "type": "html", "end_routine": True,
                          "file": self.page(_survey_html(plugin, t, self.res, w), rid)})
        elif plugin == "fullscreen":
            self.fullscreen = bool(t.get("fullscreen_mode", True))
            return []
        elif plugin in ("preload", "call-function", "browser-check"):
            self.res.note("info", f"timeline.{rid}", f"'{plugin}' is not needed in EDGE and was skipped")
            return []
        else:
            self.res.note("unsupported", f"timeline.{rid}", f"plugin '{plugin}' has no EDGE conversion yet")
            return []
        if t.get("post_trial_gap"):
            self.res.note("approx", w, f"post_trial_gap of {t['post_trial_gap']} ms not converted; "
                          "add a blank routine if the gap matters")
        self.routines[rid] = routine
        self.res.count("routines")
        self.keep_data(t, [rid], w)
        if isinstance(t.get("conditional_function"), Func):
            self.res.note("unsupported", w, "conditional_function not converted; use a branch or component 'if'")
        return [rid]

    def node(self, n: Any, where: str, hint: str | None = None, depth: int = 0) -> Any:
        n, name = _deref(n, self.env)
        hint = name or hint
        if depth > 40:
            return []
        if isinstance(n, list):
            return [x for item in n for x in self.items(item, where, depth + 1)]
        if not isinstance(n, dict):
            return []
        if "timeline" not in n:
            return self.trial(n, where, hint)
        timeline, _ = _deref(n["timeline"], self.env)      # its items keep their names (they name routines)
        n = {k: _resolve(v, self.env) for k, v in n.items() if k != "timeline"}
        tv = n.get("timeline_variables")
        reps = n.get("repetitions", 1)
        rows, cols, html = None, set(), {}
        if isinstance(tv, list):
            rows = [{ident(k): (v if not isinstance(v, (Ref, Func, Call)) else str(v)) for k, v in row.items()}
                    for row in tv if isinstance(row, dict)]
            cols = {k for r in rows for k in r}
            html = _html_columns(rows)
        self.tv_stack.append((cols, html))
        try:
            children = []
            for item in timeline if isinstance(timeline, list) else [timeline]:
                children += self.items(item, where, depth + 1)
        finally:
            self.tv_stack.pop()
        if tv is None and reps in (1, None) and not n.get("randomize_order"):
            if isinstance(n.get("loop_function"), Func):
                self.res.note("unsupported", f"timeline.{hint or 'timeline'}", "loop_function not converted; use a "
                              "state machine (repeat a state until a condition holds)")
            return children
        lid = self.ids.make(n.get("name") or hint or "trials", "loop")
        node: dict[str, Any] = {"loop": lid}
        if rows is not None:
            node["conditions"] = rows
        order = "random" if n.get("randomize_order") else "sequential"
        if isinstance(n.get("sample"), dict):
            st = n["sample"].get("type")
            if st in ("with-replacement", "without-replacement", "fixed-repetitions"):
                order = "random"
            self.res.note("approx", f"flow.{lid}", f"sample type '{st}' converted to random order")
        node["order"] = order
        if isinstance(reps, int) and reps > 1:
            node["repeats"] = reps
        node["children"] = children
        if isinstance(n.get("loop_function"), Func):
            self.res.note("unsupported", f"flow.{lid}", "loop_function not converted; use a state machine")
        self.res.count("loops")
        return [node]

    def items(self, item: Any, where: str, depth: int = 0) -> list[Any]:
        item, name = _deref(item, self.env)
        if depth > 40:
            return []
        if isinstance(item, list):
            return [x for i in item for x in self.items(i, where, depth + 1)]
        r = self.node(item, where, name, depth + 1)
        return r if isinstance(r, list) else [r]


def _tpl(h: Any) -> str:
    """Timeline-variable references in generated pages become {{placeholders}} (filled per trial)."""
    h = str(h)
    return re.sub(r"\$([A-Za-z_]\w*)", r"{{\1}}", h) if "$" in h else h


def _placeholders(text: str) -> Any:
    """'{{word}}' interpolations in text -> f-string expression."""
    if "{{" not in text:
        return text
    body = re.sub(r"\{\{\s*([^}]+?)\s*\}\}", lambda m: "{" + ident(m.group(1).split(".")[-1]) + "}",
                  text.replace("{", "{{").replace("}", "}}").replace("{{{{", "{{").replace("}}}}", "}}"))
    return "$f" + repr(body)


def _survey_html(plugin: str, t: dict[str, Any], res: ImportResult, where: str) -> str:
    qs = t.get("questions") or []
    preamble = str(t.get("preamble") or "")
    parts = [preamble, "<form style='text-align:left'>"]
    if plugin == "survey-html-form":
        parts.append(str(t.get("html", "")))
    for i, q in enumerate(qs if isinstance(qs, list) else []):
        q = q if isinstance(q, dict) else {"prompt": str(q)}
        name = ident(q.get("name") or f"Q{i}")
        prompt = str(q.get("prompt", ""))
        req = " required" if q.get("required") else ""
        parts.append(f"<fieldset><legend>{prompt}</legend>")
        if plugin == "survey-likert":
            for j, lab in enumerate(q.get("labels") or []):
                parts.append(f"<label><input type='radio' name='{name}' value='{j}'{req}> {htmllib.escape(str(lab))}</label>")
        elif plugin in ("survey-multi-choice", "survey-multi-select"):
            kind = "radio" if plugin == "survey-multi-choice" else "checkbox"
            for opt in q.get("options") or []:
                o = htmllib.escape(str(opt))
                parts.append(f"<label><input type='{kind}' name='{name}' value='{o}'{req if kind == 'radio' else ''}> {o}</label><br>")
        elif plugin == "survey-text":
            rows = int(q.get("rows", 1) or 1)
            ph = htmllib.escape(str(q.get("placeholder", "")))
            parts.append(f"<textarea name='{name}' rows='{rows}' placeholder='{ph}'{req}></textarea>" if rows > 1
                         else f"<input type='text' name='{name}' placeholder='{ph}'{req}>")
        else:
            res.note("approx", where, f"{plugin}: question {i} converted as free text")
            parts.append(f"<input type='text' name='{name}'{req}>")
        parts.append("</fieldset>")
    parts.append(f"<p style='text-align:center'><button type='submit'>{htmllib.escape(str(t.get('button_label', 'Continue')))}</button></p></form>")
    return "".join(parts)


def import_jspsych(path: Path) -> ImportResult:
    res = ImportResult({}, path, "jsPsych")
    js = extract_js(read_text(path), path.parent, res)     # inline code and the page's own script files
    env, timeline = collect(js, res)
    if timeline is None:
        res.note("unsupported", "timeline", "no jsPsych timeline found (no jsPsych.run or jsPsych.init)")
        timeline = []
    conv = _Conv(res, env)
    flow = conv.items(timeline, "flow")
    window: dict[str, Any] = {"size": [1280, 720], "background": "#ffffff", "units": "px", "fullscreen": conv.fullscreen}
    res.doc = {"name": ident(path.stem), "description": f"Imported from jsPsych ({path.name})",
               "settings": {"window": window}, "devices": [], "variables": {}, "routines": conv.routines, "flow": flow}
    res.doc = _sanitize(res.doc, res, "experiment")
    keys = list(dict.fromkeys(k for d in conv.data.values() for k in d))
    for rid, r in res.doc["routines"].items():
        for c in r["components"]:
            if c["type"] == "text":
                c.setdefault("color", "black")   # jsPsych pages are black text on white
        if keys:   # the trial's 'data' fields, and empty ones where jsPsych has none (no stale values)
            fields = conv.data.get(rid, {})
            r["components"].append({"id": "data", "type": "variable", "when": "start",
                                    "set": {k: fields.get(k) for k in keys}})
    return res


def _sanitize(v: Any, res: ImportResult, where: str) -> Any:
    """Replace JS values that have no EDGE meaning (functions, unresolved references) with notes."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if isinstance(x, (Func, Ref, Call)):
                res.note("unsupported", f"{where}.{k}", f"JavaScript value not converted: {_describe(x)}")
                continue
            out[k] = _sanitize(x, res, f"{where}.{k}")
        return out
    if isinstance(v, list):
        return [_sanitize(x, res, where) for x in v if not isinstance(x, (Func, Ref, Call))]
    return v


def _describe(x: Any) -> str:
    if isinstance(x, Func):
        return "function " + x.src[:80].replace("\n", " ")
    if isinstance(x, Ref):
        return f"reference to '{x.name}'"
    return f"call {x.name}(...)"


def looks_like_jspsych(path: Path) -> bool:
    if path.suffix.lower() not in (".html", ".htm", ".js"):
        return False
    try:
        return "jsPsych" in path.read_text(encoding="utf-8", errors="ignore") or \
            "jspsych" in path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
