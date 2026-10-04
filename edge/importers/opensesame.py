"""OpenSesame importer (.osexp, .opensesame script).

Reads the OpenSesame script language: experiment settings, sequences (with run-if
conditions), loops (``setcycle`` tables, repeat, order, break_if), sketchpads/feedback
items (textline, fixdot, rect, circle, ellipse, line, image), keyboard and mouse responses,
samplers/synths and inline_script (kept as code, flagged). A sketchpad followed by a
keyboard_response is merged into one routine, the way OpenSesame users build trials.
``.osexp`` files may be plain text or a tar.gz with a file pool; pool files are copied.
"""

from __future__ import annotations

import re
import shlex
import tarfile
from pathlib import Path
from typing import Any

from .base import Ids, ImportResult, ident, key_name, ms, num


def _val(s: str) -> Any:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        s = s[1:-1].replace('\\"', '"')
    return _vars(num(s)) if isinstance(num(s), str) else num(s)


def _vars(text: Any) -> Any:
    if not isinstance(text, str) or "[" not in text:
        return text
    refs = re.findall(r"\[(\w+)\]", text)
    if not refs:
        return text
    if re.fullmatch(r"\[(\w+)\]", text):
        return "$" + refs[0]
    return "$f" + repr(re.sub(r"\[(\w+)\]", r"{\1}", text.replace("{", "{{").replace("}", "}}")))


def _cond(c: str) -> str | None:
    c = c.strip().strip('"')
    if c.lower() in ("always", "true", ""):
        return None
    if c.lower() in ("never", "false"):
        return "$False"
    c = re.sub(r"\[(\w+)\]", r"\1", c)
    c = re.sub(r"(?<![=!<>])=(?!=)", "==", c)
    c = re.sub(r"\band\b|\bor\b|\bnot\b", lambda m: m.group(0).lower(), c, flags=re.I)
    c = re.sub(r"==\s*([A-Za-z_]\w*)\b", lambda m: m.group(0) if m.group(1) in ("True", "False", "None") else f"== '{m.group(1)}'", c)
    return "$" + c


def parse_script(script: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Returns (experiment variables, items {name: {type, set: {}, lines: [...]}})."""
    exp_vars: dict[str, str] = {}
    items: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    in_code: str | None = None
    for raw in script.splitlines():
        line = raw.rstrip("\n")
        if in_code is not None and cur is not None:
            if line.strip() == "__end__":
                in_code = None
            else:
                cur.setdefault("code", {}).setdefault(in_code, []).append(line[1:] if line.startswith("\t") else line)
            continue
        if line.startswith("define "):
            parts = line.split()
            cur = {"type": parts[1], "set": {}, "lines": []}
            items[parts[2] if len(parts) > 2 else parts[1]] = cur
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(("\t", " ")):
            cur = None
            if stripped.startswith("set "):
                k, _, v = stripped[4:].partition(" ")
                exp_vars[k] = v
            continue
        if cur is None:
            continue
        m = re.match(r"__(\w+)__$", stripped)
        if m:
            in_code = m.group(1)
            continue
        if stripped.startswith("set "):
            k, _, v = stripped[4:].partition(" ")
            cur["set"][k] = v
        else:
            cur["lines"].append(stripped)
    return exp_vars, items


def _kv(tokens: list[str]) -> dict[str, Any]:
    out = {}
    for t in tokens:
        if "=" in t:
            k, _, v = t.partition("=")
            out[k] = _val(v)
    return out


def import_opensesame(path: Path) -> ImportResult:
    res = ImportResult({}, path, "OpenSesame")
    script, pool = _read(path, res)
    exp_vars, items = parse_script(script)
    W = int(num(exp_vars.get("width", "1024")) or 1024)
    H = int(num(exp_vars.get("height", "768")) or 768)
    fg = str(_val(exp_vars.get("foreground", "white")))
    ids = Ids()
    routines: dict[str, Any] = {}

    def sketch_components(item: dict[str, Any], where: str) -> list[dict[str, Any]]:
        comps = []
        for line in item["lines"]:
            if not line.startswith("draw "):
                continue
            try:
                tokens = shlex.split(line[5:], posix=True)
            except ValueError:
                tokens = line[5:].split()
            kind, kv = tokens[0], _kv(tokens[1:])
            x = kv.get("x", 0)
            y = kv.get("y", 0)
            pos = [x, -y if isinstance(y, (int, float)) else y]
            color = kv.get("color", fg)
            n = len(comps) + 1
            if kind == "textline":
                comps.append({"id": f"text{n}", "type": "text", "text": kv.get("text", ""), "pos": pos, "color": color,
                              "height": kv.get("font_size", 18) * 1.33 if isinstance(kv.get("font_size", 18), (int, float)) else 24})
            elif kind == "fixdot":
                comps.append({"id": f"fix{n}", "type": "fixation", "shape": "circle", "radius": 6, "pos": pos,
                              "fill": color})
            elif kind in ("rect", "ellipse"):
                w_, h_ = kv.get("w", 100), kv.get("h", 100)
                cx = x + w_ / 2 if all(isinstance(v, (int, float)) for v in (x, w_)) else x
                cy = -(y + h_ / 2) if all(isinstance(v, (int, float)) for v in (y, h_)) else pos[1]
                filled = kv.get("fill", 0) in (1, "1", True)
                c = {"id": f"{kind}{n}", "type": "shape", "shape": "rect" if kind == "rect" else "ellipse",
                     "pos": [cx, cy], "size": [w_, h_], "fill": color if filled else "transparent"}
                if not filled:
                    c["line_color"] = color
                comps.append(c)
            elif kind == "circle":
                filled = kv.get("fill", 0) in (1, "1", True)
                c = {"id": f"circle{n}", "type": "shape", "shape": "circle", "pos": pos, "radius": kv.get("r", 50),
                     "fill": color if filled else "transparent"}
                comps.append(c)
            elif kind in ("line", "arrow"):
                comps.append({"id": f"line{n}", "type": "shape", "shape": "line", "pos": [0, 0],
                              "start": [kv.get("x1", 0), -kv.get("y1", 0) if isinstance(kv.get("y1", 0), (int, float)) else 0],
                              "end": [kv.get("x2", 0), -kv.get("y2", 0) if isinstance(kv.get("y2", 0), (int, float)) else 0],
                              "line_color": color})
                if kind == "arrow":
                    res.note("approx", where, "arrow drawn as a line")
            elif kind == "image":
                f = kv.get("file", "")
                comps.append({"id": f"image{n}", "type": "image", "image": f, "pos": pos})
                if isinstance(f, str) and f and not f.startswith("$"):
                    res.assets.add(f if not pool else f"__pool__/{f}")
                if kv.get("scale", 1) not in (1, 1.0):
                    res.note("approx", where, "image scale not converted; set the image size")
            else:
                res.note("unsupported", where, f"sketchpad element '{kind}' not converted")
            if "show_if" in kv and comps:
                cond = _cond(str(kv["show_if"]))
                if cond:
                    comps[-1]["if"] = cond
        return comps

    def keyboard_from(item: dict[str, Any], cid: str = "resp") -> dict[str, Any]:
        s = item["set"]
        k: dict[str, Any] = {"id": cid, "type": "keyboard", "end_routine": True}
        allowed = _val(s.get("allowed_responses", '""'))
        if isinstance(allowed, str) and allowed and not allowed.startswith("$"):
            k["keys"] = [key_name(x) for x in re.split(r"[;,]", allowed) if x.strip()]
        corr = s.get("correct_response")
        if corr:
            v = _val(corr)
            k["correct"] = key_name(v) if isinstance(v, str) and not v.startswith("$") else v
        to = _val(s.get("timeout", '"infinite"'))
        if isinstance(to, (int, float)):
            k["duration"] = ms(to)
        elif isinstance(to, str) and to.startswith("$"):
            k["duration"] = to
            res.note("approx", f"items.{cid}", "timeout taken from a variable: it must be in seconds in EDGE")
        return k

    def routine_for(name: str, item: dict[str, Any], resp: dict[str, Any] | None) -> str:
        rid = ids.make(name, "routine")
        t = item["type"]
        routine: dict[str, Any] = {"components": []}
        if t in ("sketchpad", "feedback"):
            routine["components"] = sketch_components(item, f"routines.{rid}")
            dur = _val(item["set"].get("duration", "keypress"))
            if isinstance(dur, (int, float)):
                if resp is None:
                    routine["duration"] = ms(dur) if dur > 0 else 0
            elif dur == "keypress":
                routine["components"].append({"id": "resp", "type": "keyboard", "end_routine": True})
            elif dur == "mouseclick":
                routine["components"].append({"id": "click", "type": "mouse", "end_routine": True})
            if t == "feedback":
                res.note("approx", f"routines.{rid}", "feedback variables (acc, avg_rt) are not computed; "
                         "use loop statistics like $trials.accuracy and $trials.mean_rt")
        elif t == "keyboard_response":
            pass
        elif t == "sampler":
            f = _val(item["set"].get("sample", '""'))
            routine["components"].append({"id": "sound", "type": "sound", "sound": f})
            if isinstance(f, str) and f and not f.startswith("$"):
                res.assets.add(f if not pool else f"__pool__/{f}")
            dur = _val(item["set"].get("duration", "sound"))
            routine["duration"] = ms(dur) if isinstance(dur, (int, float)) else 0.5
        elif t == "synth":
            freq = _val(item["set"].get("freq", 440))
            length = _val(item["set"].get("length", 100))
            routine["components"].append({"id": "tone", "type": "sound", "sound": freq,
                                          "tone_duration": ms(length) if isinstance(length, (int, float)) else 0.1})
            dur = _val(item["set"].get("duration", "sound"))
            routine["duration"] = ms(dur) if isinstance(dur, (int, float)) else (ms(length) if isinstance(length, (int, float)) else 0.1)
        elif t == "advanced_delay" or t == "delay":
            d = _val(item["set"].get("duration", 1000))
            routine["duration"] = ms(d) if isinstance(d, (int, float)) else d
            routine["components"].append({"id": "wait", "type": "wait"})
        elif t == "inline_script":
            code = item.get("code", {})
            run = "\n".join(code.get("run", []))
            prep = "\n".join(code.get("prepare", []))
            body = "\n".join(x for x in (prep, run) if x.strip())
            routine["duration"] = 0
            routine["components"].append({"id": "script", "type": "code", "on_begin": body})
            res.note("approx", f"routines.{rid}", "inline_script kept as Python code; OpenSesame objects "
                     "(var, exp, clock, items) must be adapted to EDGE (vars, session)")
        if resp is not None:
            routine["components"].append(resp)
            # OpenSesame's built-in response variables, so [correct] / [response] / [response_time] keep working
            routine["components"].append({"id": "os_response_vars", "type": "variable", "when": "end", "set": {
                "correct": f"$int({resp['id']}.corr or 0)", "response": f"${resp['id']}.keys",
                "response_time": f"$({resp['id']}.rt or 0) * 1000"}})
        if not routine["components"]:
            routine["duration"] = routine.get("duration", 0)
        routines[rid] = routine
        res.count("routines")
        return rid

    def nodes_for(name: str, depth: int = 0) -> list[Any]:
        item = items.get(name)
        if item is None:
            res.note("unsupported", f"items.{name}", "referenced item is not defined")
            return []
        t = item["type"]
        if depth > 20:
            return []
        if t == "sequence":
            out: list[Any] = []
            runs = []
            for line in item["lines"]:
                if line.startswith("run "):
                    parts = shlex.split(line[4:]) if '"' in line else line[4:].split(None, 1)
                    runs.append((parts[0], _cond(parts[1]) if len(parts) > 1 else None))
            i = 0
            while i < len(runs):
                child, cond = runs[i]
                ci = items.get(child, {"type": "?"})
                nxt = runs[i + 1] if i + 1 < len(runs) else None
                if ci["type"] in ("sketchpad", "feedback") and nxt and items.get(nxt[0], {}).get("type") == "keyboard_response" \
                        and nxt[1] == cond and str(_val(ci["set"].get("duration", "0"))) in ("0", "0.0"):
                    rid = routine_for(child, ci, keyboard_from(items[nxt[0]]))
                    out.append(rid if not cond else {"routine": rid, "if": cond})
                    i += 2
                    continue
                if ci["type"] in ("logger",):
                    res.count("loggers skipped (EDGE logs automatically)")
                    i += 1
                    continue
                if ci["type"] in ("sequence", "loop"):
                    sub = nodes_for(child, depth + 1)
                    if cond:
                        out.append({"if": cond, "then": sub})
                    else:
                        out += sub
                elif ci["type"] == "keyboard_response":
                    rid = routine_for(child, {"type": "keyboard_response", "set": {}, "lines": []}, keyboard_from(ci))
                    out.append(rid if not cond else {"routine": rid, "if": cond})
                elif ci["type"] in ("sketchpad", "feedback", "sampler", "synth", "inline_script", "advanced_delay"):
                    rid = routine_for(child, ci, None)
                    out.append(rid if not cond else {"routine": rid, "if": cond})
                else:
                    res.note("unsupported", f"items.{child}", f"item type '{ci['type']}' not converted")
                i += 1
            return out
        if t == "loop":
            s = item["set"]
            rows: dict[int, dict[str, Any]] = {}
            for line in item["lines"]:
                if line.startswith("setcycle "):
                    parts = shlex.split(line[9:]) if '"' in line else line[9:].split(None, 2)
                    if len(parts) >= 3:
                        rows.setdefault(int(parts[0]), {})[ident(parts[1])] = _val(parts[2] if '"' not in line else f'"{parts[2]}"')
            cycles = int(num(s.get("cycles", len(rows) or 1)) or 1)
            table = [rows.get(i, {}) for i in range(max(cycles, len(rows)))]
            child = s.get("item", "").strip('"')
            run_line = next((l for l in item["lines"] if l.startswith("run ")), None)
            if not child and run_line:
                child = run_line[4:].split()[0]
            lid = ids.make(name, "loop")
            node: dict[str, Any] = {"loop": lid, "conditions": table if any(table) else None,
                                    "order": "random" if _val(s.get("order", "random")) == "random" else "sequential"}
            rep = num(s.get("repeat", "1"))
            if isinstance(rep, (int, float)) and rep != 1:
                if float(rep).is_integer():
                    node["repeats"] = int(rep)
                else:
                    node["repeats"] = max(1, round(rep))
                    res.note("approx", f"flow.{lid}", f"fractional repeat {rep} rounded")
            if s.get("break_if") and _cond(s["break_if"]) not in (None, "$False"):
                node["stop_if"] = _cond(s["break_if"])
            if s.get("source", "table").strip('"') == "file":
                f = _val(s.get("source_file", '""'))
                node["conditions"] = f
                res.assets.add(f if not pool else f"__pool__/{f}")
            node["children"] = nodes_for(child, depth + 1) if child else []
            res.count("loops")
            return [node]
        return [routine_for(name, item, keyboard_from(item) if t == "keyboard_response" else None)]

    start = exp_vars.get("start", "experiment").strip('"')
    flow = nodes_for(start) if start in items else []
    if not flow:
        res.note("unsupported", "flow", f"start item '{start}' not found")
    res.doc = {"name": ident(_val(exp_vars.get("title", path.stem)) or path.stem),
               "description": f"Imported from OpenSesame ({path.name})",
               "settings": {"window": {"size": [W, H], "units": "px",
                                       "background": str(_val(exp_vars.get("background", "black")))}},
               "devices": [], "variables": {"correct": 0, "response": None, "response_time": None},
               "routines": routines, "flow": flow}
    if pool:
        res.generated_files.update(pool)
        res.assets = {a.replace("__pool__/", "") for a in res.assets if not a.startswith("__pool__/")}
    return res


def _read(path: Path, res: ImportResult) -> tuple[str, dict[str, bytes]]:
    pool: dict[str, bytes] = {}
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tar:
            script = ""
            for m in tar.getmembers():
                if m.name.endswith("script.opensesame"):
                    script = tar.extractfile(m).read().decode("utf-8", errors="replace")  # type: ignore[union-attr]
                elif m.isfile() and "/pool/" in "/" + m.name and ".." not in m.name:
                    pool[m.name.split("pool/", 1)[1]] = tar.extractfile(m).read()  # type: ignore[union-attr]
            return script, pool
    return path.read_text(encoding="utf-8", errors="replace"), pool


def looks_like_opensesame(path: Path) -> bool:
    if path.suffix.lower() in (".osexp", ".opensesame"):
        return True
    try:
        return path.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("# Generated by OpenSesame")
    except OSError:
        return False
