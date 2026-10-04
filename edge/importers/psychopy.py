"""PsychoPy Builder (.psyexp) importer.

Converts settings, routines and components (text, textbox, image, polygon, keyboard,
mouse, slider, sound, static periods, code, routine settings, eye-tracking ROI,
parallel/serial out), the flow, and loops (trial handlers with conditions files, nReps,
order, selected rows; staircases). Expressions and code are translated where PsychoPy
idioms have EDGE equivalents (``trials.thisN`` -> ``trials.n``, ``expInfo['x']`` -> ``x``,
``continueRoutine = False`` -> ``end_routine()``). Everything else is listed in the
import report.
"""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .base import Ids, ImportResult, ident, key_name, num

NOTE_HZ = {"C": 261.63, "Csh": 277.18, "D": 293.66, "Dsh": 311.13, "E": 329.63, "F": 349.23, "Fsh": 369.99,
           "G": 392.0, "Gsh": 415.3, "A": 440.0, "Ash": 466.16, "B": 493.88}
UNSUPPORTED_HINTS = {
    "MovieComponent": "movies are not supported yet",
    "MicrophoneComponent": "microphone recording is not supported yet",
    "JoystickComponent": "joysticks are not supported yet",
    "ButtonBoxComponent": "button boxes: use a keyboard component or a device driver",
    "FormComponent": "forms: rebuild as an html component (EDGE renders real HTML forms)",
}


def _translate(code: str) -> str:
    code = re.sub(r"\bexpInfo\[\s*['\"](\w+)['\"]\s*\]", r"\1", code)
    code = re.sub(r"\.thisN\b", ".n", code)
    code = re.sub(r"\.thisTrialN\b", ".n", code)
    code = re.sub(r"\.thisRepN\b", ".repeat", code)
    code = re.sub(r"\.nTotal\b", ".total", code)
    code = re.sub(r"\bcontinueRoutine\s*=\s*False\b", "end_routine()", code)
    return code


class _Params(dict):
    def text(self, name: str, default: str = "") -> str:
        p = self.get(name)
        return default if p is None else p[0]


def _params(el: ET.Element) -> _Params:
    out = _Params()
    for p in el.findall("Param"):
        out[p.get("name")] = (p.get("val", ""), p.get("valType", ""), p.get("updates", ""))
    return out


def _value(raw: str, val_type: str, res: ImportResult, where: str, as_str: bool = False) -> Any:
    """Convert a PsychoPy parameter to an EDGE value or $expression."""
    raw = raw if raw is not None else ""
    s = raw.strip()
    if s == "" or s == "None":
        return None
    if s.startswith("$"):
        expr = _translate(s[1:].strip())
        return _literal_or_expr(expr)
    if val_type in ("code", "extendedCode") and not as_str:
        return _literal_or_expr(_translate(s))
    if val_type == "bool":
        return s.lower() in ("true", "1", "yes")
    if val_type in ("num", "int"):
        n = num(s)
        return n if isinstance(n, (int, float)) else _literal_or_expr(_translate(s))
    if val_type == "list" and not as_str:
        return _literal_or_expr(s)
    return raw  # plain string (PsychoPy str params are literal text unless they start with $)


def _literal_or_expr(expr: str) -> Any:
    try:
        v = ast.literal_eval(expr)
        if isinstance(v, tuple):
            v = list(v)
        return v
    except (ValueError, SyntaxError):
        return "$" + expr


def _color(raw: str, vt: str, space: str, res: ImportResult, where: str) -> Any:
    v = _value(raw, vt, res, where)
    if v is None:
        return None
    if isinstance(v, list) and len(v) >= 3 and all(isinstance(x, (int, float)) for x in v):
        if space in ("rgb", ""):           # PsychoPy -1..1
            vals = [max(0, min(255, round((x + 1) * 127.5))) for x in v[:3]]
        elif space == "rgb1":
            vals = [round(x * 255) for x in v[:3]]
        elif space == "rgb255":
            vals = [round(x) for x in v[:3]]
        else:
            res.note("approx", where, f"colour space '{space}' converted as rgb")
            vals = [max(0, min(255, round((x + 1) * 127.5))) for x in v[:3]]
        return "#%02x%02x%02x" % tuple(vals)
    if isinstance(v, str) and space == "hex" and not v.startswith("#") and not v.startswith("$"):
        return "#" + v
    return v


def _timing(p: _Params, comp: dict[str, Any], res: ImportResult, where: str) -> None:
    st, sv = p.text("startType", "time (s)"), p.text("startVal", "0")
    et, ev = p.text("stopType", "duration (s)"), p.text("stopVal", "")
    start = _value(sv, "code", res, where)
    stop = _value(ev, "code", res, where)
    if st.startswith("time"):
        if start not in (None, 0, 0.0):
            comp["start"] = start
    elif st.startswith("frame"):
        comp["start_frame"] = start
    elif st.startswith("condition"):
        comp["start_if"] = "$" + _translate(sv.lstrip("$"))
    if stop in (None, ""):
        return
    if et.startswith("duration (s)"):
        comp["duration"] = stop
    elif et.startswith("duration (frames)"):
        comp["duration_frames"] = stop
    elif et.startswith("time"):
        if isinstance(stop, (int, float)) and isinstance(comp.get("start", 0), (int, float)):
            comp["duration"] = round(stop - comp.get("start", 0), 6)
        else:
            comp["stop_if"] = f"$t >= {str(stop).lstrip('$')}"
    elif et.startswith("frame"):
        if isinstance(stop, int) and isinstance(comp.get("start_frame", 0), int):
            comp["duration_frames"] = stop - comp.get("start_frame", 0)
        else:
            comp["stop_if"] = f"$frame >= {str(stop).lstrip('$')}"
    elif et.startswith("condition"):
        comp["stop_if"] = "$" + _translate(ev.lstrip("$"))


def _keys(raw: str, vt: str) -> Any:
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("$"):
        v = _literal_or_expr(s[1:])
        return [key_name(k) for k in v] if isinstance(v, list) else v
    try:
        v = ast.literal_eval(s if s.startswith(("[", "(")) else f"[{s}]")
        return [key_name(str(k)) for k in (v if isinstance(v, (list, tuple)) else [v])]
    except (ValueError, SyntaxError):
        return [key_name(k.strip(" '\"")) for k in s.split(",") if k.strip()]


def _component(el: ET.Element, res: ImportResult, where: str, space_default: str) -> dict[str, Any] | None:
    tag = el.tag
    p = _params(el)
    name = el.get("name") or p.text("name")
    cid = ident(name)
    w = f"{where}.{name}"
    cs = p.text("colorSpace", space_default)

    def g(key: str, as_str: bool = False) -> Any:
        if key not in p:
            return None
        raw, vt, _ = p[key]
        return _value(raw, vt, res, w, as_str)

    comp: dict[str, Any] = {"id": cid}
    if tag in ("TextComponent", "TextboxComponent"):
        comp["type"] = "text"
        comp["text"] = g("text", as_str=True) or ""
        col = p.get("color") or p.get("foreColor") or p.get("letterColor")
        if col:
            comp["color"] = _color(col[0], col[1], cs, res, w)
        for src, dst in (("letterHeight", "height"), ("pos", "pos"), ("ori", "ori"), ("opacity", "opacity"),
                         ("font", "font"), ("wrapWidth", "wrap_width"), ("bold", "bold"), ("italic", "italic")):
            v = g(src)
            if v not in (None, ""):
                comp[dst] = v
        if tag == "TextboxComponent" and p.text("editable") == "True":
            res.note("approx", w, "editable textbox converted to static text; collect typed input with an html form")
    elif tag == "ImageComponent":
        comp["type"] = "image"
        img = g("image", as_str=True)
        comp["image"] = img
        if isinstance(img, str) and img and not img.startswith("$"):
            res.assets.add(img)
        for src, dst in (("size", "size"), ("pos", "pos"), ("ori", "ori"), ("opacity", "opacity")):
            v = g(src)
            if v not in (None, ""):
                comp[dst] = v
    elif tag == "PolygonComponent":
        comp["type"] = "shape"
        shape = (p.text("shape") or "rectangle").lower()
        mapping = {"rectangle": "rect", "square": "rect", "circle": "circle", "cross": "cross", "line": "line",
                   "triangle": "polygon", "star": "polygon"}
        comp["shape"] = mapping.get(shape, "polygon" if "polygon" in shape else "rect")
        size = g("size")
        if comp["shape"] == "circle":
            if isinstance(size, list):
                comp["radius"] = size[0] / 2 if isinstance(size[0], (int, float)) else size[0]
            elif size is not None:
                comp["radius"] = size
        elif size is not None:
            comp["size"] = size
        if comp["shape"] == "polygon":
            if shape == "triangle":
                comp["vertices"] = [[-0.5, -0.5], [0.5, -0.5], [0, 0.5]]
            res.note("approx", w, f"polygon '{shape}' approximated; check its vertices")
        for key, dst in (("fillColor", "fill"), ("lineColor", "line_color")):
            if key in p:
                comp[dst] = _color(p[key][0], p[key][1], p.text(key + "Space", cs), res, w)
        for src, dst in (("pos", "pos"), ("ori", "ori"), ("opacity", "opacity"), ("lineWidth", "line_width")):
            v = g(src)
            if v not in (None, ""):
                comp[dst] = v
    elif tag == "KeyboardComponent":
        comp["type"] = "keyboard"
        keys = _keys(*p.get("allowedKeys", ("", ""))[:2])
        if keys:
            comp["keys"] = keys
        store = p.text("store", "last key")
        comp["store"] = {"first key": "first", "last key": "last", "all keys": "all"}.get(store, "first")
        if store == "nothing":
            comp["save"] = False
        if p.text("storeCorrect") == "True":
            ca = g("correctAns", as_str=True)
            if ca not in (None, ""):
                comp["correct"] = ca
        if p.text("forceEndRoutine") == "True":
            comp["end_routine"] = True
        if p.text("discard previous", "True") == "False":
            comp["discard_previous"] = False
    elif tag == "MouseComponent":
        comp["type"] = "mouse"
        clickable = p.text("clickable")
        if clickable.strip():
            comp["clickable"] = [ident(c.strip(" '\"")) for c in clickable.strip("[]$").split(",") if c.strip()]
        if p.text("forceEndRoutineOnPress", "never") != "never":
            comp["end_routine"] = True
        if p.text("saveMouseState") in ("every frame", "on click"):
            comp["track"] = p.text("saveMouseState") == "every frame"
    elif tag == "SliderComponent":
        comp["type"] = "slider"
        for src, dst in (("ticks", "ticks"), ("labels", "labels"), ("granularity", "granularity"), ("pos", "pos"),
                         ("size", "size")):
            v = g(src)
            if v not in (None, ""):
                comp[dst] = v
        if p.text("forceEndRoutine") == "True":
            comp["end_routine"] = True
    elif tag == "SoundComponent":
        comp["type"] = "sound"
        snd = (p.text("sound") or "A").strip()
        if snd.startswith("$"):
            comp["sound"] = _literal_or_expr(_translate(snd[1:]))
        elif snd.replace("_", "") in NOTE_HZ:
            comp["sound"] = NOTE_HZ[snd.replace("_", "")]
        elif num(snd) != snd:
            comp["sound"] = num(snd)
        else:
            comp["sound"] = snd
            res.assets.add(snd)
        vol = g("volume")
        if vol not in (None, ""):
            comp["volume"] = vol
        if isinstance(comp["sound"], (int, float)) and p.text("stopVal"):
            comp["tone_duration"] = num(p.text("stopVal"))
    elif tag == "StaticComponent":
        comp["type"] = "wait"
        res.note("info", w, "static period converted to a wait (EDGE preloads stimuli at routine start)")
    elif tag == "CodeComponent":
        comp["type"] = "code"
        mapping = {"Begin Routine": "on_begin", "Each Frame": "on_frame", "End Routine": "on_end"}
        for src, dst in mapping.items():
            code = p.text(src).strip()
            if code:
                comp[dst] = _translate(code)
        for exp_part in ("Before Experiment", "Begin Experiment", "End Experiment"):
            if p.text(exp_part).strip():
                res.note("approx", w, f"'{exp_part}' code moved into the setup routine at the start of the flow"
                         if exp_part != "End Experiment" else "'End Experiment' code was not converted")
        joined = " ".join(comp.get(k, "") for k in mapping.values())
        if re.search(r"\b(win|thisExp|core|event|visual|psychoJS)\.", joined):
            res.note("approx", w, "code uses PsychoPy APIs (win/thisExp/core/event/visual); adapt it to EDGE")
    elif tag in ("ParallelOutComponent", "SerialOutComponent"):
        comp["type"] = "marker"
        data = g("startData")
        comp["label"] = f"{name}_on"
        if isinstance(data, (int, float)):
            comp["code"] = int(data)
        elif data not in (None, ""):
            comp["label"] = data if isinstance(data, str) else str(data)
        res.note("info", w, "hardware output converted to an EDGE marker (sent to every TTL/LSL device you add)")
    elif tag == "ROIComponent":
        comp["type"] = "gaze_roi"
        for src, dst in (("pos", "pos"), ("size", "size")):
            v = g(src)
            if v not in (None, ""):
                comp[dst] = v
        comp["shape"] = "circle" if "circle" in (p.text("shape") or "").lower() else "rect"
        if p.text("endRoutineOn", "none") not in ("none", ""):
            comp["end_routine"] = True
            dt = g("minLookTime")
            if dt:
                comp["dwell"] = dt / 1000 if isinstance(dt, (int, float)) and dt > 20 else dt
    elif tag in ("EyetrackerRecordComponent",):
        res.note("info", w, "eye-tracker start/stop record: EDGE records devices for the whole session")
        return None
    elif tag == "RoutineSettingsComponent":
        return None
    else:
        hint = UNSUPPORTED_HINTS.get(tag, "no EDGE equivalent yet")
        res.note("unsupported", w, f"{tag}: {hint}")
        return None
    if comp["type"] not in ("code",):
        _timing(p, comp, res, w)
    units = p.text("units", "from exp settings")
    if units and units not in ("from exp settings", "None") and comp["type"] in ("text", "image", "shape", "slider",
                                                                                   "gaze_roi"):
        comp["units"] = {"pix": "px", "norm": "norm", "height": "height", "deg": "deg"}.get(units, units)
        if comp["units"] not in ("px", "norm", "height", "deg"):
            res.note("approx", w, f"units '{units}' are not supported; using '{comp['units']}' anyway")
    if p.text("disabled") == "True":
        comp["disabled"] = True
    res.count("components")
    return comp


def import_psychopy(path: Path) -> ImportResult:
    tree = ET.parse(path)
    root = tree.getroot()
    res = ImportResult({}, path, f"PsychoPy {root.get('version', '')}".strip())
    settings_el = root.find("Settings")
    sp = _params(settings_el) if settings_el is not None else _Params()
    name = sp.text("expName") or path.stem
    units = sp.text("Units", "height")
    window: dict[str, Any] = {"units": {"pix": "px"}.get(units, units)}
    size = _literal_or_expr(sp.text("Window size (pixels)", "[1920, 1080]"))
    if isinstance(size, list):
        window["size"] = size
    window["fullscreen"] = sp.text("Full-screen window", "True") == "True"
    if "color" in sp:
        window["background"] = _color(sp["color"][0], sp["color"][1], sp.text("colorSpace", "rgb"), res, "settings")
    try:
        info = ast.literal_eval(sp.text("Experiment info", "{}"))
        participant = {}
        for k, v in (info or {}).items():
            key = ident(str(k).rstrip("*"))
            participant[key] = v if isinstance(v, (str, int, float)) and not str(v).startswith("f\"") else ""
        if not participant.get("participant"):
            participant["participant"] = "001"
    except (ValueError, SyntaxError):
        participant = {"participant": "001", "session": "1"}
        res.note("approx", "settings", "experiment info dialog fields could not be read; defaults used")
    if sp.text("Monitor"):
        res.note("info", "settings", f"monitor '{sp.text('Monitor')}': set width_cm/distance_cm under settings.window.monitor for deg units")

    routines: dict[str, Any] = {}
    rid_map: dict[str, str] = {}
    ids = Ids()
    setup_code: list[str] = []
    routines_el = root.find("Routines")
    for r in (routines_el if routines_el is not None else []):
        rname = r.get("name")
        rid = ids.make(rname, "routine")
        rid_map[rname] = rid
        comps = []
        routine: dict[str, Any] = {"components": comps}
        for c in r:
            if c.tag == "RoutineSettingsComponent":
                cp = _params(c)
                if cp.text("stopVal").strip() and cp.text("stopType", "").startswith("duration"):
                    routine["duration"] = _value(cp.text("stopVal"), "code", res, rid)
                continue
            if c.tag == "CodeComponent":
                cp = _params(c)
                for part in ("Before Experiment", "Begin Experiment"):
                    if cp.text(part).strip():
                        setup_code.append(_translate(cp.text(part).strip()))
            comp = _component(c, res, f"routines.{rid}", sp.text("colorSpace", "rgb"))
            if comp is not None:
                comps.append(comp)
        routines[rid] = routine
        res.count("routines")

    # flow: LoopInitiator / Routine / LoopTerminator sequence -> nested structure
    flow: list[Any] = []
    stack: list[list[Any]] = [flow]
    flow_el = root.find("Flow")
    for el in (flow_el if flow_el is not None else []):
        if el.tag == "Routine":
            stack[-1].append(rid_map.get(el.get("name"), ident(el.get("name"))))
        elif el.tag == "LoopInitiator":
            lp = _params(el)
            loop_type = el.get("loopType", "TrialHandler")
            lid = ids.make(el.get("name") or lp.text("name"), "loop")
            node: dict[str, Any] = {"loop": lid}
            if loop_type in ("StairHandler", "MultiStairHandler"):
                steps = _literal_or_expr(lp.text("step sizes", "[0.1]"))
                node["staircase"] = {"variable": "level", "start": num(lp.text("start value", "0.5")),
                                     "step": steps, "reversals": num(lp.text("N reversals", "8")),
                                     "up": num(lp.text("N up", "1")), "down": num(lp.text("N down", "3")),
                                     "max_trials": num(lp.text("nReps", "50")) or 50, "correct": "resp.corr",
                                     "log": lp.text("step type", "lin").startswith("log")}
                if lp.text("min value"):
                    node["staircase"]["min"] = num(lp.text("min value"))
                if lp.text("max value"):
                    node["staircase"]["max"] = num(lp.text("max value"))
                res.note("approx", f"flow.{lid}", "staircase converted: the intensity variable is 'level' and "
                         "correctness is read from 'resp.corr'; adjust 'variable' and 'correct'")
                if loop_type == "MultiStairHandler":
                    res.note("approx", f"flow.{lid}", "interleaved staircases converted as a single staircase")
            else:
                cf = lp.text("conditionsFile").strip()
                if cf:
                    if cf.startswith("$"):
                        node["conditions"] = cf
                        res.note("approx", f"flow.{lid}", "conditions file chosen by an expression; check it")
                    else:
                        node["conditions"] = cf
                        res.assets.add(cf)
                reps = _value(lp.text("nReps", "1"), "num", res, lid)
                if reps not in (None, 1):
                    node["repeats"] = reps
                order = lp.text("loopType", "random")
                node["order"] = {"random": "random", "sequential": "sequential", "fullRandom": "fullrandom"}.get(order, "random")
                sel = lp.text("Selected rows").strip()
                if sel:
                    node["select"] = sel if ":" in sel else _literal_or_expr(sel)
            node["children"] = []
            stack[-1].append(node)
            stack.append(node["children"])
            res.count("loops")
        elif el.tag == "LoopTerminator":
            if len(stack) > 1:
                stack.pop()
    if setup_code:
        rid = ids.make("setup_code")
        routines[rid] = {"duration": 0, "description": "code from PsychoPy 'Begin Experiment' sections",
                         "components": [{"id": "begin_experiment", "type": "code", "on_begin": "\n".join(setup_code)}]}
        flow.insert(0, rid)

    res.doc = {"name": ident(name), "description": f"Imported from PsychoPy ({path.name})",
               "settings": {"window": window, "participant": participant},
               "devices": [], "variables": {}, "routines": routines, "flow": flow}
    _check_eyetracking(root, res)
    return res


def _check_eyetracking(root: ET.Element, res: ImportResult) -> None:
    sp = root.find("Settings")
    if sp is None:
        return
    p = _params(sp)
    et = p.text("eyetracker", "None")
    if et and et != "None":
        dev = {"Tobii Technology": "tobii", "GazePoint": "gazepoint", "MouseGaze": "mouse_gaze"}.get(et)
        if dev:
            res.doc["devices"].append({"id": "eyetracker", "type": dev})
            res.note("info", "devices", f"PsychoPy eye tracker '{et}' mapped to EDGE '{dev}'")
        else:
            res.note("approx", "devices", f"eye tracker '{et}': add the matching EDGE device manually")


def looks_like_psychopy(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:500]
    except OSError:
        return False
    return "<PsychoPy" in head
