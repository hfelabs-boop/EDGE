"""Structured error reports: when something fails, say what, where, when and in what state.

Every runtime failure becomes a report that answers the five questions a researcher (or support)
needs: what failed, in which routine/component, in which phase (preparing, starting, every frame,
a key press, stopping, a rule, the routine's end condition, the flow), in which trial, and what the
experiment's variables were at that moment. Errors in Python code components point at the line of
the researcher's code. A plain-language hint comes with the common causes.

The report is printed by ``edge run``, shown in the builder, saved in ``session.json`` under
``crash`` (data recorded up to that point is kept), and included in support bundles.
"""

from __future__ import annotations

import re
import traceback
from typing import Any

PHASES = {
    "prepare": "while preparing the screen (before it appeared)",
    "start": "when it started",
    "frame": "while it was on screen (every frame)",
    "event": "while handling a key press / click / device input",
    "stop": "when it stopped",
    "timing": "while working out when it starts or stops (start_if / stop_if / duration)",
    "rule": "in a rule (when → do)",
    "end_if": "in the screen's end condition",
    "flow": "in the flow (a loop, branch or workflow)",
    "setup": "while starting the session (window, devices)",
}


class ExperimentError(RuntimeError):
    """A runtime failure with its structured report attached (``.report``)."""

    def __init__(self, report: dict[str, Any]):
        super().__init__(report.get("what", "error"))
        self.report = report


def _simple(v: Any) -> Any:
    if isinstance(v, (bool, int, float)) or v is None:
        return v
    if isinstance(v, str):
        return v if len(v) <= 80 else v[:77] + "…"
    if isinstance(v, (list, tuple)) and len(v) <= 8 and all(isinstance(x, (bool, int, float, str, type(None))) for x in v):
        return [_simple(x) for x in v]
    return None


def snapshot(ns: dict[str, Any] | None, limit: int = 40) -> dict[str, Any]:
    """The simple values an expression could see at the moment of the error."""
    out: dict[str, Any] = {}
    for k, v in (ns or {}).items():
        if k.startswith("_") or k in ("vars", "session", "routine", "marker", "end_routine", "__builtins__"):
            continue
        if isinstance(v, dict):                 # component results / loop state: a few fields
            for kk, vv in list(v.items())[:6]:
                sv = _simple(vv)
                if sv is not None or vv is None:
                    out[f"{k}.{kk}"] = sv
        else:
            sv = _simple(v)
            if sv is not None or v is None:
                out[k] = sv
        if len(out) >= limit:
            break
    return out


def user_code_line(exc: BaseException, code_sources: dict[str, str]) -> dict[str, Any] | None:
    """The researcher's line in a code component (compiled as '<routine.comp.part>')."""
    tb = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    for fr in reversed(tb):
        if fr.filename.startswith("<") and fr.filename[1:-1] in code_sources:
            src = code_sources[fr.filename[1:-1]].splitlines()
            line = src[fr.lineno - 1].strip() if 0 < (fr.lineno or 0) <= len(src) else ""
            return {"where": fr.filename[1:-1], "line": fr.lineno, "code": line}
    return None


def hint_for(exc: BaseException) -> str:
    name, msg = type(exc).__name__, str(exc)
    low = msg.lower()
    if name == "ExpressionError":
        return ""                                  # already explained in plain words
    if name in ("NameError", "UnboundLocalError"):
        m = re.search(r"name '(\w+)'", msg)
        return (f"'{m.group(1) if m else 'a name'}' is not defined here: check the spelling, whether the trial list has "
                "that column, and whether it is set before this point (Check shows names that don't exist).")
    if name == "KeyError":
        return f"there is no {msg} here: a trial-list column or dictionary key with that name doesn't exist."
    if name == "ZeroDivisionError":
        return "a division by zero: e.g. accuracy before any response (guard it with 'if n > 0')."
    if name == "TypeError" and "nonetype" in low:
        return ("a value was empty (None), typically a response that hasn't happened yet (resp.rt before a key "
                "press) or a missing trial-list value; check for None first.")
    if name in ("FileNotFoundError",) or "no such file" in low or "not found" in low:
        return "a file is missing: file names are relative to the experiment's folder (Check lists missing files)."
    if name == "DeviceError" or "device" in low:
        return "a device failed: check it is on and connected, or run with simulated hardware to test the rest."
    if "display" in low or "xlib" in low:
        return "no screen to open the window on (e.g. over SSH): run on the computer with the monitor, or use a dry run."
    if name == "MemoryError":
        return "out of memory: very large pictures or videos? Make them smaller (the screen can't show more pixels anyway)."
    return "'edge validate' and the FAQ explain most problems; a support bundle (edge support-bundle) has everything needed to ask for help."


def build_report(exc: BaseException, *, phase: str, routine: str | None = None, component: Any = None,
                 run: Any = None, runner: Any = None) -> dict[str, Any]:
    """Turn an exception into the structured report."""
    if isinstance(exc, ExperimentError):
        return exc.report
    rep: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc), "phase": phase,
                           "phase_text": PHASES.get(phase, phase)}
    if routine:
        rep["routine"] = routine
    if component is not None:
        rep["component"] = getattr(component, "id", str(component))
        rep["component_type"] = getattr(component, "type_name", "")
    ns = None
    if run is not None:
        try:
            ns = run.namespace()
        except Exception:
            ns = None
        rep["routine_time"] = round(float(ns.get("t", 0.0)), 4) if ns else None
        rep["frame"] = getattr(run, "frame", None)
    runner = runner or (getattr(run, "runner", None) if run is not None else None)
    if runner is not None:
        rep["trial"] = {f["loop"]: (f["state"].get("n") if hasattr(f["state"], "get") else None) for f in runner.stack}
        rep["routine_index"] = getattr(runner, "routine_count", None)
        machines = getattr(runner, "machines", [])
        if machines:
            rep["workflow"] = {m["id"]: m.get("state") for m in machines}
        if ns is None:
            ns = {}
            for f in runner.stack:
                ns.update(f["row"])
            ns.update(getattr(runner.session, "vars", {}) or {})
    rep["variables"] = snapshot(ns)
    sources: dict[str, str] = {}
    if run is not None:
        for c in getattr(run, "components", {}).values():
            for k, v in (getattr(c, "spec", None).props.items() if getattr(c, "spec", None) else []):
                if isinstance(v, str) and k.startswith("on_"):
                    sources[f"{run.routine.id}.{c.id}.{k}"] = v
    code = user_code_line(exc, sources)
    if code:
        rep["user_code"] = code
    rep["hint"] = hint_for(exc)
    tb = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    rep["traceback"] = [f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno} {f.name}" for f in tb[-4:]]
    rep["what"] = summary_line(rep)
    return rep


def summary_line(rep: dict[str, Any]) -> str:
    where = []
    if rep.get("component"):
        where.append(f"'{rep['component']}'" + (f" ({rep['component_type']})" if rep.get("component_type") else ""))
    if rep.get("routine"):
        where.append(f"on screen '{rep['routine']}'")
    trial = ", ".join(f"{k} #{v + 1 if isinstance(v, int) else v}" for k, v in (rep.get("trial") or {}).items())
    s = f"{rep['type']}: {rep['message']}"
    if where:
        s += " — in " + " ".join(where)
    s += f", {rep.get('phase_text', rep.get('phase'))}"
    if trial:
        s += f" ({trial})"
    return s


def format_report(rep: dict[str, Any]) -> str:
    lines = ["The experiment stopped because of an error.", "", f"  What:   {rep['type']}: {rep['message']}"]
    if rep.get("component") or rep.get("routine"):
        lines.append("  Where:  " + " · ".join(x for x in (
            f"component '{rep['component']}' ({rep.get('component_type', '')})" if rep.get("component") else "",
            f"screen '{rep['routine']}'" if rep.get("routine") else "") if x))
    lines.append(f"  When:   {rep.get('phase_text', rep.get('phase'))}"
                 + (f", {rep['routine_time']:.3f} s into the screen" if rep.get("routine_time") else ""))
    if rep.get("trial"):
        lines.append("  Trial:  " + ", ".join(f"{k} #{(v + 1) if isinstance(v, int) else v}" for k, v in rep["trial"].items()))
    if rep.get("user_code"):
        uc = rep["user_code"]
        lines.append(f"  Code:   line {uc['line']} of {uc['where']}:  {uc['code']}")
    if rep.get("variables"):
        vs = ", ".join(f"{k}={v!r}" for k, v in list(rep["variables"].items())[:12])
        lines.append(f"  State:  {vs}")
    if rep.get("hint"):
        lines += ["", f"  Hint:   {rep['hint']}"]
    lines += ["", "  Everything recorded until then is saved. 'edge support-bundle' packs what's needed to ask for help."]
    return "\n".join(lines)


# ---------------------------------------------------------------- the same report, in a researcher's words
TYPE_WORDS = {
    "keyboard": "a key press", "mouse": "a mouse response", "slider": "a rating slider", "text": "a text",
    "image": "a picture", "sound": "a sound", "shape": "a shape", "fixation": "a fixation cross",
    "html": "a web page", "survey": "a questionnaire", "device_response": "a device response",
    "gaze_roi": "a gaze area", "calibrate": "a calibration", "marker": "a marker",
}


def _find_component(doc: dict[str, Any] | None, cid: str | None) -> tuple[str | None, dict[str, Any] | None]:
    for rid, r in ((doc or {}).get("routines") or {}).items():
        for c in (r or {}).get("components") or []:
            if isinstance(c, dict) and c.get("id") == cid:
                return rid, c
    return None, None


def _outputs_of(ctype: str | None) -> list[str]:
    """The results a component type always has; [] when they depend on its settings (a survey's questions, a web
    page's fields, a marker's labels), where a name can't be called a typo."""
    try:
        from .components import component_registry
        from .components.base import Component
        cls = component_registry().get(str(ctype))
        if not cls or getattr(cls.planned_outputs, "__func__", None) is not Component.planned_outputs.__func__:
            return []
        return sorted(cls.outputs)
    except Exception:
        return []


def plain_error(rep: dict[str, Any], doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """What went wrong, in one plain sentence, and where to fix it.

    → {"text", "routine", "component", "prop"}: e.g. 'On screen “feedback”, the text formula of “fb” uses
    resp.cor, but a key press has no “cor”. Did you mean resp.corr?'. The raw report stays for Expert mode."""
    import difflib

    typ, msg = str(rep.get("type") or ""), str(rep.get("message") or "")
    routine, comp = rep.get("routine"), rep.get("component")
    out: dict[str, Any] = {"routine": routine, "component": comp, "prop": None}
    src, etype, emsg = None, "", ""
    m = re.search(r"error evaluating '(.+?)': (\w+): (.*)$", msg, re.S)
    if m:
        src, etype, emsg = m.group(1), m.group(2), m.group(3)
    else:
        m2 = re.search(r"\(in '(.+?)'\)", msg)
        src = m2.group(1) if m2 else None
    # which property holds the formula
    if src and comp:
        _, cdict = _find_component(doc, comp)
        for k, v in (cdict or {}).items():
            if isinstance(v, str) and src in v:
                out["prop"] = k
                break
    where = f"On screen “{routine}”" if routine else "While the experiment ran"
    what = (f"the {str(out['prop']).replace('_', ' ')} formula of “{comp}”" if out["prop"] else
            f"“{comp}”" if comp else "a formula")
    text = ""
    if etype == "AttributeError" and src:
        attr = (emsg.split() or [""])[0].strip("'\"(")
        mm = re.search(r"\b([A-Za-z_]\w*)\s*\.\s*%s\b" % re.escape(attr), src) if attr else None
        obj = mm.group(1) if mm else None
        _, odict = _find_component(doc, obj)
        ctype = (odict or {}).get("type")
        thing = TYPE_WORDS.get(str(ctype), f"“{obj}”") if obj else "that value"
        close = difflib.get_close_matches(attr, _outputs_of(ctype), n=1, cutoff=0.5)
        text = (f"{where}, {what} uses {obj}.{attr}" if obj else f"{where}, {what} uses “{attr}”") \
            + f", but {thing} has no “{attr}”." + (f" Did you mean {obj}.{close[0]}?" if close and obj else "")
    elif "isn't defined here" in msg:
        name = re.search(r"'(\w+)' isn't defined", msg)
        dym = re.search(r"Did you mean ([^?]+)\?", msg)
        text = f"{where}, {what} uses “{name.group(1) if name else '?'}”, which doesn't exist at that point." \
            + (f" Did you mean {dym.group(1)}?" if dym else "")
    elif etype in ("TypeError",) and "NoneType" in emsg:
        text = (f"{where}, {what} used a value that was still empty (for example a response before any key "
                "was pressed). Check for “no response” first.")
    elif etype == "ZeroDivisionError":
        text = f"{where}, {what} divided by zero (for example accuracy before any answer)."
    elif typ == "ExpressionError" and "isn't a valid expression" in msg:
        text = f"{where}, {what} isn't a valid formula: {msg.split('(syntax error', 1)[-1].split(').', 1)[-1].strip() or 'check the quotes and brackets.'}"
    elif rep.get("user_code"):
        uc = rep["user_code"]
        text = f"{where}, the Python code of “{comp}” failed on line {uc.get('line')}: {typ}: {msg}"
    else:
        text = f"{where}, {what} stopped the experiment: {msg or typ}"
    out["text"] = text.replace("  ", " ")
    return out
