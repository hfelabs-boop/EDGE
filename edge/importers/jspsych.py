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

from .base import Ids, ImportResult, ident, key_name, ms


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


def extract_js(source: str) -> str:
    if "<script" in source.lower():
        blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", source, re.S | re.I)
        return "\n".join(blocks)
    return source


def collect(js: str, res: ImportResult) -> tuple[dict[str, Any], Any]:
    """Return (declared variables, the timeline passed to jsPsych.run / init)."""
    env: dict[str, Any] = {}
    pushes: dict[str, list[Any]] = {}
    for m in re.finditer(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*", js):
        p = JSParser(js)
        p.i = m.end()
        try:
            env[m.group(1)] = p.value()
        except (ValueError, IndexError, AttributeError):
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
        except (ValueError, IndexError, AttributeError):
            continue
    for name, items in pushes.items():
        if isinstance(env.get(name), list):
            env[name] = env[name] + items
        elif name not in env:
            env[name] = items
    timeline = None
    m = re.search(r"jsPsych\.run\(\s*", js)
    if m:
        p = JSParser(js)
        p.i = m.end()
        timeline = p.value()
    else:
        m = re.search(r"jsPsych\.init\(\s*", js)
        if m:
            p = JSParser(js)
            p.i = m.end()
            cfg = p.value()
            timeline = cfg.get("timeline") if isinstance(cfg, dict) else None
    if timeline is None:
        timeline = env.get("timeline")
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


def _strip_html(h: str) -> tuple[str, bool]:
    """Text content of simple HTML, and whether it was 'simple' (no images/tables/inputs)."""
    complex_ = bool(re.search(r"<(img|table|input|svg|canvas|video|audio|iframe)\b", h, re.I))
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", h, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines()).strip()
    return text, not complex_


def _font_px(h: str) -> float | None:
    m = re.search(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", h)
    return float(m.group(1)) if m else None


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


class _Conv:
    def __init__(self, res: ImportResult, env: dict[str, Any]):
        self.res, self.env = res, env
        self.ids = Ids()
        self.routines: dict[str, Any] = {}
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

    def trial(self, t: dict[str, Any], where: str) -> list[Any]:
        t = {k: _tv(v) for k, v in _resolve(t, self.env).items()}
        if "timeline" in t:
            return [self.node(t, where)]
        plugin = _plugin(t.get("type"))
        rid = self.ids.make(t.get("name") or plugin.replace("-", "_") or "trial", "trial")
        w = f"{where}.{rid}"
        for k, v in t.items():
            if isinstance(v, Func) and k not in ("on_load",):
                self.res.note("unsupported", w, f"'{k}' is a JavaScript function and was not converted")
        comps: list[dict[str, Any]] = []
        routine: dict[str, Any] = {"components": comps}
        stim = _value_text(t.get("stimulus", ""))
        if plugin in ("html-keyboard-response", "image-keyboard-response", "audio-keyboard-response",
                      "html-slider-response", "image-slider-response", "video-keyboard-response"):
            if plugin.startswith("html"):
                if isinstance(stim, str) and not stim.startswith("$"):
                    text, simple = _strip_html(stim)
                    c: dict[str, Any] = {"id": "stim", "type": "text", "text": _placeholders(text)}
                    fp = _font_px(stim)
                    if fp:
                        c["height"] = fp
                    if not simple:
                        self.res.note("approx", w, "HTML stimulus with images/tables shown as text; "
                                      "consider an html component")
                    comps.append(c)
                else:
                    comps.append({"id": "stim", "type": "text", "text": stim, "x_note": "HTML stripped at runtime"})
                    self.res.note("approx", w, "stimulus comes from a timeline variable containing HTML; "
                                  "EDGE shows it as text (tags are not stripped automatically)")
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
                ptext, _ = _strip_html(str(t["prompt"]))
                comps.append({"id": "prompt", "type": "text", "text": _placeholders(ptext), "pos": [0, -200],
                              "height": 24})
            td = t.get("trial_duration")
            if isinstance(td, Func):
                routine["duration"] = 0.5
                self.res.note("approx", w, "trial_duration is computed by a function; set to 0.5 s. For a random "
                              "duration use e.g. $random.choice([0.25, 0.5])")
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
            if t.get("trial_duration") is not None:
                routine["duration"] = ms(t["trial_duration"])
        elif plugin == "instructions":
            pages = t.get("pages") or []
            out = []
            for i, pg in enumerate(pages if isinstance(pages, list) else [pages]):
                prid = self.ids.make(f"{rid}_p{i + 1}")
                self.routines[prid] = {"components": [{"id": "page", "type": "html", "end_routine": True,
                                                       "file": self.page(_tpl(str(pg)), prid)}]}
                out.append(prid)
            self.res.count("routines", len(out))
            if t.get("allow_backward", True):
                self.res.note("approx", w, "instruction pages are shown forward only")
            return out
        elif plugin.startswith("survey"):
            comps.append({"id": "survey", "type": "html", "end_routine": True,
                          "file": self.page(_survey_html(plugin, t, self.res, w), rid)})
        elif plugin == "fullscreen":
            self.fullscreen = bool(t.get("fullscreen_mode", True))
            return []
        elif plugin in ("preload", "call-function", "browser-check"):
            self.res.note("info", w, f"'{plugin}' is not needed in EDGE and was skipped")
            return []
        else:
            self.res.note("unsupported", w, f"plugin '{plugin}' has no EDGE conversion yet")
            return []
        if t.get("post_trial_gap"):
            self.res.note("approx", w, f"post_trial_gap of {t['post_trial_gap']} ms not converted; "
                          "add a blank routine if the gap matters")
        self.routines[rid] = routine
        self.res.count("routines")
        cond = t.get("conditional_function")
        if isinstance(cond, Func):
            self.res.note("unsupported", w, "conditional_function not converted; use a branch or component 'if'")
        return [rid]

    def node(self, n: Any, where: str) -> Any:
        n = _resolve(n, self.env)
        if isinstance(n, list):
            return [x for item in n for x in self.items(item, where)]
        if not isinstance(n, dict):
            return []
        if "timeline" not in n:
            return self.trial(n, where)
        children = []
        for item in n["timeline"] if isinstance(n["timeline"], list) else [n["timeline"]]:
            children += self.items(item, where)
        tv = n.get("timeline_variables")
        reps = n.get("repetitions", 1)
        if tv is None and reps in (1, None) and not n.get("randomize_order"):
            if isinstance(n.get("loop_function"), Func):
                self.res.note("unsupported", where, "loop_function not converted; use a state machine "
                              "(repeat a state until a condition holds)")
            return children
        lid = self.ids.make(n.get("name") or "trials", "loop")
        node: dict[str, Any] = {"loop": lid}
        if isinstance(tv, list):
            node["conditions"] = [{ident(k): (v if not isinstance(v, (Ref, Func, Call)) else str(v))
                                   for k, v in row.items()} for row in tv if isinstance(row, dict)]
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

    def items(self, item: Any, where: str) -> list[Any]:
        item = _resolve(item, self.env)
        if isinstance(item, list):
            return [x for i in item for x in self.items(i, where)]
        r = self.node(item, where)
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
    js = extract_js(path.read_text(encoding="utf-8", errors="replace"))
    env, timeline = collect(js, res)
    if timeline is None:
        res.note("unsupported", "timeline", "no jsPsych timeline found")
        timeline = []
    conv = _Conv(res, env)
    flow = conv.items(timeline, "flow")
    for f in re.findall(r"<script[^>]+src=['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8", errors="ignore")):
        if "jspsych" not in f.lower() and not f.startswith("http"):
            res.note("approx", "scripts", f"local script '{f}' was not analysed (only inline code is read)")
    window: dict[str, Any] = {"size": [1280, 720], "background": "#ffffff", "units": "px", "fullscreen": conv.fullscreen}
    res.doc = {"name": ident(path.stem), "description": f"Imported from jsPsych ({path.name})",
               "settings": {"window": window}, "devices": [], "variables": {}, "routines": conv.routines, "flow": flow}
    res.doc = _sanitize(res.doc, res, "experiment")
    # jsPsych pages are black text on white; make converted text readable
    for r in conv.routines.values():
        for c in r["components"]:
            if c["type"] == "text":
                c.setdefault("color", "black")
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
