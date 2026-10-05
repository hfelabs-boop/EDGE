"""What an experiment measures, and everything it records.

Two things live here:

* the **recording plan**: before anything runs, every column and stream the experiment will save
  (participant fields, trial-list columns, what each component records, device streams), worked out
  from the components' and devices' own declarations;
* **measures**: the experiment's ``measures:`` section, where the researcher says which of those
  columns are the outcomes (dependent variables), the factors (independent variables), covariates
  and checks, how each is summarised, and on which trials::

      measures:
        - id: rt
          label: Reaction time
          role: outcome               # outcome | factor | covariate | check | info
          column: resp.rt
          trials: $resp.corr == 1     # optional: only these trials
          loop: trials                # optional: only trials of this loop (e.g. skip practice)
          summary: median             # mean | median | sd | min | max | sum | count | proportion | first | last | none
          expect: [0.15, 2.5]         # optional plausible range; values outside are flagged
        - {id: congruency, role: factor, column: congruent}

After a session the declared measures are computed per participant (overall and per cell of the
factors) into ``measures.csv`` and checked (never recorded, many missing, outside the expected range).
"""

from __future__ import annotations

import difflib
import statistics
from typing import Any

from . import expressions
from .components.base import Results

ROLES = {
    "outcome": "outcome (dependent variable)",
    "factor": "factor (independent variable)",
    "covariate": "covariate",
    "check": "manipulation / attention check",
    "info": "descriptive information",
}
SUMMARIES = ("mean", "median", "sd", "min", "max", "sum", "count", "proportion", "first", "last", "none")
MEASURE_KEYS = {"id", "label", "role", "column", "trials", "loop", "summary", "units", "expect", "description"}


# ============================================================================ the recording plan
def recording_plan(exp) -> dict[str, Any]:
    """Everything the experiment will save, before it runs."""
    from .components import component_registry
    from .devices import device_registry
    from .model import Branch, Loop, StateMachine
    from .scope import loop_columns

    comps, devs = component_registry(), device_registry()
    plan: dict[str, Any] = {"participant": [], "loops": [], "variables": [], "components": [], "devices": [],
                            "always": [], "columns": {}}
    cols = plan["columns"]

    for f in (exp.settings.get("participant") or {}):
        plan["participant"].append(f)
        cols[f] = {"source": "participant", "desc": "Participant information field (entered at the start)",
                   "units": "", "kind": "info", "saved": True}

    def walk(nodes, parents: list[str]):
        for n in nodes:
            if isinstance(n, Loop):
                known = loop_columns(n, exp.base_dir)
                src = ("staircase" if n.staircase else n.conditions if isinstance(n.conditions, str)
                       else "factorial design" if isinstance(n.conditions, dict) else "table in the experiment")
                plan["loops"].append({"loop": n.id, "columns": sorted(known) if known is not None else None,
                                      "source": src, "inside": parents[-1] if parents else None})
                for c in sorted(known or ()):
                    cols.setdefault(c, {"source": f"loop:{n.id}", "desc": f"Trial-list column of '{n.id}'",
                                        "units": "", "kind": "condition", "saved": True})
                for k, d in (("n", "iteration (0-based)"), ("repeat", "repetition (0-based)")):
                    cols.setdefault(f"{n.id}.{k}", {"source": f"loop:{n.id}", "desc": f"'{n.id}' {d}",
                                                    "units": "", "kind": "design", "saved": True})
                walk(n.children, parents + [n.id])
            elif isinstance(n, Branch):
                walk(n.then, parents)
                walk(n.else_, parents)
            elif isinstance(n, StateMachine):
                cols.setdefault(f"{n.id}.state", {"source": f"workflow:{n.id}", "desc": f"State of workflow '{n.id}'",
                                                  "units": "", "kind": "design", "saved": True})
                for st in n.states.values():
                    walk(st.run, parents + [n.id])
    walk(exp.flow, [])

    variables = list(exp.variables)
    for routine in exp.routines.values():
        for c in routine.components:
            if c.type == "variable":
                variables += [str(k) for k in (c.props.get("set") or {}) if str(k) not in variables]
    for v in variables:
        plan["variables"].append(v)
        cols.setdefault(v, {"source": "variable", "desc": "Experiment variable (value at the end of each trial)",
                            "units": "", "kind": "variable", "saved": True})

    for rid, routine in exp.routines.items():
        for c in routine.components:
            cls = comps.get(c.type)
            if cls is None:
                continue
            try:
                outs = cls.planned_outputs(c.props, exp.base_dir)
            except Exception:
                outs = dict(cls.outputs)
            who = f"'{c.id}' ({c.type})"
            entry = {"routine": rid, "id": c.id, "type": c.type, "save": bool(c.save),
                     "disabled": c.disabled is True, "outputs": []}
            for key, meta in outs.items():
                col = f"{c.id}.{key}"
                desc = str(meta.get("desc", key)).replace("{who}", who)
                entry["outputs"].append({"column": col, "key": key, "desc": desc, "units": meta.get("units", ""),
                                         "type": meta.get("type", ""), "kind": meta.get("kind", "other")})
                cols.setdefault(col, {"source": f"component:{rid}.{c.id}", "desc": desc, "units": meta.get("units", ""),
                                      "kind": meta.get("kind", "other"), "saved": bool(c.save)})
            plan["components"].append(entry)

    for d in exp.devices:
        cls = devs.get(d.type)
        if cls is None:
            continue
        try:
            streams = cls.planned_streams(d.options)
            note = cls.records_note(d.options)
        except Exception:
            streams, note = [], ""
        plan["devices"].append({"id": d.id, "type": d.type, "record": d.record, "markers": d.markers,
                                "streams": streams, "note": note,
                                "files": [f"streams/{d.id}.{s['name']}.csv" for s in streams] if d.record else []})

    data = exp.settings.get("data") or {}
    plan["always"] = [
        {"file": "trials_wide.csv", "what": "one row per trial with every column above"},
        {"file": "events.jsonl", "what": "every event marker, time-locked to the screen flip, and which device got it"},
        {"file": "session.json", "what": "settings, participant fields, device clock alignment, timing summary"},
        {"file": "data_dictionary.csv", "what": "what every column means, its units and range"},
    ]
    if data.get("save_frame_log", True):
        plan["always"].append({"file": "frames.csv", "what": "the time of every screen refresh (timing audit)"})
    if exp.measures:
        plan["always"].append({"file": "measures.csv", "what": "your declared measures, summarised per condition"})
    return plan


# ============================================================================ suggestions
def suggest_measures(exp, plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Reasonable measures for an experiment that has none yet: RT and accuracy of the main response,
    survey scores, gaze dwell times, and trial-list columns with a few levels as factors."""
    from .conditions import load_conditions
    from .model import Loop

    plan = plan or recording_plan(exp)
    out: list[dict[str, Any]] = []
    taken: set[str] = set()

    def add(m: dict[str, Any]) -> None:
        base = m["id"]
        i = 2
        while m["id"] in taken:
            m["id"] = f"{base}_{i}"
            i += 1
        taken.add(m["id"])
        out.append(m)

    where = _routine_loops(exp)          # routine -> enclosing loops, outermost first
    has_loops = any(where.values())
    responders = [c for c in plan["components"] if c["save"] and not c["disabled"]
                  and c["type"] in ("keyboard", "mouse", "slider", "gaze_roi")
                  and (where.get(c["routine"]) or not has_loops)]      # "press space to continue" isn't a measure
    for c in responders:
        keys = {o["key"]: o for o in c["outputs"]}
        loops = [lp for lp in where.get(c["routine"], []) if "practi" not in lp.lower()]
        if where.get(c["routine"]) and not loops:
            continue                                                    # only inside practice loops
        lp = {"loop": loops[-1]} if loops else {}
        if c["type"] == "slider":
            add({"id": f"{c['id']}_rating", "label": f"Rating ({c['id']})", "role": "outcome",
                 "column": f"{c['id']}.rating", "summary": "mean", **lp})
            continue
        if c["type"] == "gaze_roi":
            add({"id": f"{c['id']}_dwell", "label": f"Dwell time on {c['id']}", "role": "outcome",
                 "column": f"{c['id']}.dwell_time", "summary": "mean", "units": "s", **lp})
            continue
        if "corr" in keys:
            add({"id": "accuracy" if not any(m["id"] == "accuracy" for m in out) else f"{c['id']}_accuracy",
                 "label": "Accuracy" + (f" ({c['id']})" if len(responders) > 1 else ""), "role": "outcome",
                 "column": f"{c['id']}.corr", "summary": "proportion", **lp})
        add({"id": "rt" if not any(m["id"] == "rt" for m in out) else f"{c['id']}_rt",
             "label": "Reaction time" + (f" ({c['id']})" if len(responders) > 1 else ""), "role": "outcome",
             "column": f"{c['id']}.rt", "summary": "median", "units": "s", "expect": [0.1, 5],
             **({"trials": f"${c['id']}.corr == 1"} if "corr" in keys else {}), **lp})
    for c in plan["components"]:
        if c["type"] == "survey" and c["save"]:
            for o in c["outputs"]:
                if o["kind"] == "score" and not o["key"].endswith("_band"):
                    add({"id": o["key"], "label": o["desc"].split(" (survey")[0][:60], "role": "outcome",
                         "column": o["column"], "summary": "first"})

    cands: dict[str, int] = {}

    def factors(nodes):
        for n in nodes:
            if isinstance(n, Loop):
                if not n.staircase and n.conditions is not None and not (isinstance(n.conditions, str) and n.conditions.startswith("$")):
                    try:
                        rows = load_conditions(n.conditions, exp.base_dir)
                    except Exception:
                        rows = []
                    for col in (rows[0].keys() if rows else []):
                        levels = {repr(r.get(col)) for r in rows}
                        low = str(col).lower()
                        if str(col).startswith("_") or not 2 <= len(levels) <= 8 or \
                                any(w in low for w in ("correct", "answer", "key", "file", "image", "sound", "stim")):
                            continue
                        cands.setdefault(str(col), len(levels))
                factors(n.children)
    factors(exp.flow)
    preferred = ("condition", "congru", "type", "block", "group", "cue", "valid", "load", "difficulty")
    ranked = sorted(cands, key=lambda c: (not any(w in c.lower() for w in preferred), cands[c], c))
    named = [c for c in ranked if any(w in c.lower() for w in preferred)]
    for col in (named[:2] if named else ranked[:1]):
        if not any(m["column"] == col for m in out):
            add({"id": col, "label": col.replace("_", " ").capitalize(), "role": "factor", "column": col, "summary": "none"})
    return out


def _routine_loops(exp) -> dict[str, list[str]]:
    """Routine id -> ids of the loops around it (outermost first). A routine used both in a practice
    loop and in the main loop maps to the main one."""
    from .model import Branch, Loop, StateMachine
    out: dict[str, list[str]] = {}

    def walk(nodes, stack):
        for n in nodes:
            if isinstance(n, Loop):
                walk(n.children, stack + [n.id])
            elif isinstance(n, Branch):
                walk(n.then, stack)
                walk(n.else_, stack)
            elif isinstance(n, StateMachine):
                for st in n.states.values():
                    walk(st.run, stack)
            else:
                rid = getattr(n, "routine", None)
                practice = any("practi" in x.lower() for x in stack)
                if rid and (rid not in out or (out[rid] and any("practi" in x.lower() for x in out[rid]) and not practice)):
                    out[rid] = stack
    walk(exp.flow, [])
    return out


# ============================================================================ validation
def normalize(m: dict[str, Any]) -> dict[str, Any]:
    """Fill in defaults: id from the column, role outcome, a summary that suits the column."""
    m = dict(m)
    col = str(m.get("column") or "")
    m.setdefault("id", col.replace(".", "_") or "measure")
    m.setdefault("role", "outcome")
    if "summary" not in m:
        key = col.rpartition(".")[2]
        m["summary"] = ("none" if m["role"] in ("factor", "info") else
                        "proportion" if key in ("corr", "entered", "completed", "submitted") else "mean")
    return m


def validate_measures(exp) -> list:
    from .model import Issue, _check_expr

    raw = exp.measures
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [Issue("error", "measures", "measures must be a list, e.g. - {id: rt, column: resp.rt}")]
    issues: list = []
    plan = recording_plan(exp)
    cols = plan["columns"]
    comp_ids = {c["id"]: c for c in plan["components"]}
    loop_ids = {lp["loop"] for lp in plan["loops"]}
    unknown_loops = any(lp["columns"] is None for lp in plan["loops"])
    seen: set[str] = set()
    for i, m0 in enumerate(raw):
        where = f"measures[{i}]"
        if not isinstance(m0, dict) or not m0.get("column"):
            issues.append(Issue("error", where, "a measure needs a 'column': the data column it is based on, e.g. resp.rt"))
            continue
        m = normalize(m0)
        where = f"measures.{m['id']}"
        for k in set(m0) - MEASURE_KEYS:
            issues.append(Issue("warning", where, f"unknown measure setting '{k}'", hint=", ".join(sorted(MEASURE_KEYS))))
        if not str(m["id"]).isidentifier():
            issues.append(Issue("error", where, "a measure id must be a name (letters, digits, _)"))
        if m["id"] in seen:
            issues.append(Issue("error", where, "two measures have the same id"))
        seen.add(m["id"])
        if m["role"] not in ROLES:
            issues.append(Issue("error", where, f"unknown role '{m['role']}'", hint=", ".join(ROLES)))
        if m["summary"] not in SUMMARIES:
            issues.append(Issue("error", where, f"unknown summary '{m['summary']}'", hint=", ".join(SUMMARIES)))
        col = str(m["column"])
        comp, _, key = col.rpartition(".")
        if col in cols and not cols[col]["saved"]:
            issues.append(Issue("error", where, f"'{comp}' is not saved (save: off), so {col} will not be in the data",
                                hint=f"turn saving back on for '{comp}'"))
        elif col not in cols:
            if comp in comp_ids:
                keys = [o["key"] for o in comp_ids[comp]["outputs"]]
                close = difflib.get_close_matches(key, keys, 1)
                issues.append(Issue("error" if keys else "warning", where,
                                    f"'{comp}' ({comp_ids[comp]['type']}) records " +
                                    (", ".join(keys) if keys else "nothing") + f", not '{key}'",
                                    hint=f"did you mean {comp}.{close[0]}?" if close else ""))
            elif not unknown_loops:
                close = difflib.get_close_matches(col, list(cols), 1)
                issues.append(Issue("warning", where, f"no column called '{col}' will be recorded",
                                    hint=f"did you mean {close[0]}?" if close else "see the list of recorded columns"))
        if m.get("trials") is not None:
            t = str(m["trials"])
            _check_expr(t if t.startswith("$") else "$" + t, where + ".trials", issues)
        if m.get("loop") is not None and m["loop"] not in loop_ids:
            issues.append(Issue("error", where, f"there is no loop called '{m['loop']}'",
                                hint=", ".join(sorted(loop_ids)) if loop_ids else "this experiment has no loops"))
        e = m.get("expect")
        if e is not None and not (isinstance(e, list) and len(e) == 2 and all(isinstance(x, (int, float)) for x in e)
                                  and e[0] <= e[1]):
            issues.append(Issue("error", where, "expect must be [lowest, highest], e.g. [0.15, 2.5]"))
    if raw and not any(normalize(m).get("role") == "outcome" for m in raw if isinstance(m, dict) and m.get("column")):
        issues.append(Issue("info", "measures", "no outcome measure declared: which column is the result you care about?"))
    return issues


def describe(exp) -> list[str]:
    """The measures in plain words, one line each."""
    out = []
    for m0 in exp.measures or []:
        if not isinstance(m0, dict) or not m0.get("column"):
            continue
        m = normalize(m0)
        s = f"{m.get('label') or m['id']}: {ROLES.get(m['role'], m['role'])} from {m['column']}"
        if m["summary"] != "none":
            s += f", {m['summary']}"
        if m.get("loop"):
            s += f", trials of '{m['loop']}'"
        if m.get("trials"):
            s += f", only when {str(m['trials']).lstrip('$')}"
        if m.get("expect"):
            s += f", expected {m['expect'][0]}–{m['expect'][1]}"
        out.append(s)
    return out


# ============================================================================ after a session
def _row_ns(row: dict[str, Any]) -> dict[str, Any]:
    ns: dict[str, Any] = {}
    for k, v in row.items():
        if "." in k:
            head, _, tail = k.partition(".")
            grp = ns.get(head)
            if not isinstance(grp, Results):
                grp = ns[head] = Results()
            grp[tail] = v
        else:
            ns.setdefault(k, v)
    return ns


def _select(m: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Rows a measure uses (its loop, its trials filter), and how many rows the filter couldn't evaluate."""
    col = m["column"]
    sel = [r for r in rows if col in r or m["role"] in ("factor", "info")]
    if m.get("loop"):
        sel = [r for r in sel if r.get("loop") == m["loop"] or f"{m['loop']}.n" in r]
    bad = 0
    if m.get("trials"):
        src = str(m["trials"]).lstrip("$")
        kept = []
        for r in sel:
            try:
                if expressions.evaluate(src, _row_ns(r)):
                    kept.append(r)
            except Exception:
                bad += 1
        sel = kept
    return sel, bad


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _summary(kind: str, values: list[Any]) -> Any:
    present = [v for v in values if v not in (None, "", [], {})]
    nums = [x for x in (_num(v) for v in present) if x is not None]
    if kind == "count":
        return len(present)
    if kind == "first":
        return present[0] if present else None
    if kind == "last":
        return present[-1] if present else None
    if kind == "none" or not nums:
        return None
    if kind == "proportion":
        return round(sum(1 for x in nums if x) / len(nums), 4)
    fn = {"mean": statistics.fmean, "median": statistics.median, "min": min, "max": max, "sum": sum,
          "sd": lambda xs: statistics.stdev(xs) if len(xs) > 1 else None}[kind]
    r = fn(nums)
    return round(r, 6) if isinstance(r, float) else r


def declared(source: dict[str, Any]) -> list[dict[str, Any]]:
    return [normalize(m) for m in (source.get("measures") or []) if isinstance(m, dict) and m.get("column")]


def measure_table(source: dict[str, Any], rows: list[dict[str, Any]], session: dict[str, Any] | None = None
                  ) -> tuple[list[str], list[dict[str, Any]]]:
    """Each measure overall and per cell of the declared factors, for one session's trial rows."""
    ms = declared(source)
    facs = [m for m in ms if m["role"] == "factor"]
    fcols = [f["id"] for f in facs]
    base = dict(session or {})
    out: list[dict[str, Any]] = []
    for m in ms:
        if m["role"] == "factor":
            continue
        sel, _ = _select(m, rows)
        vals = [r.get(m["column"]) for r in sel]

        def row(cell: dict[str, Any], vs: list[Any]) -> dict[str, Any]:
            return {**base, "measure": m["id"], "label": m.get("label") or m["id"], "role": m["role"],
                    "column": m["column"], "summary": m["summary"], **cell,
                    "n": sum(v not in (None, "") for v in vs), "missing": sum(v in (None, "") for v in vs),
                    "value": _summary(m["summary"], vs), "units": m.get("units", "")}
        out.append(row({f: "(all)" for f in fcols}, vals))
        if facs and m["role"] in ("outcome", "check", "covariate"):
            cells: dict[tuple, list[Any]] = {}
            for r in sel:
                key = tuple(_cell(r.get(f["column"])) for f in facs)
                if all(k in (None, "") for k in key):
                    continue                     # outside the trial list (instructions, goodbye …)
                cells.setdefault(key, []).append(r.get(m["column"]))
            for key in sorted(cells, key=lambda k: tuple(str(x) for x in k)):
                out.append(row(dict(zip(fcols, key)), cells[key]))
    cols = list(base) + ["measure", "label", "role", "column", "summary"] + fcols + ["n", "missing", "value", "units"]
    return cols, out


def _cell(v: Any) -> Any:
    return v if isinstance(v, (str, int, float, bool)) or v is None else str(v)


def measure_checks(source: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Problems with the declared measures in one session's data."""
    notes = []
    for m in declared(source):
        if m["role"] == "factor":
            if rows and not any(m["column"] in r for r in rows):
                notes.append({"measure": m["id"], "level": "warning", "message": f"factor {m['id']}: column {m['column']} was never recorded"})
            continue
        if not any(m["column"] in r for r in rows):
            notes.append({"measure": m["id"], "level": "warning",
                          "message": f"measure {m['id']}: column {m['column']} was never recorded"})
            continue
        sel, bad = _select(m, rows)
        if bad:
            notes.append({"measure": m["id"], "level": "warning",
                          "message": f"measure {m['id']}: the trials filter failed on {bad} trial(s)"})
        vals = [r.get(m["column"]) for r in sel]
        n_miss = sum(v in (None, "") for v in vals)
        if vals and m["role"] in ("outcome", "check") and n_miss / len(vals) > 0.2:
            notes.append({"measure": m["id"], "level": "warning",
                          "message": f"measure {m['id']}: missing on {n_miss} of {len(vals)} trials ({100 * n_miss / len(vals):.0f}%)"})
        if not sel and rows:
            notes.append({"measure": m["id"], "level": "warning", "message": f"measure {m['id']}: no trials matched"})
        e = m.get("expect")
        if e:
            nums = [x for x in (_num(v) for v in vals if v not in (None, "")) if x is not None]
            out = [x for x in nums if not e[0] <= x <= e[1]]
            if out:
                notes.append({"measure": m["id"], "level": "warning",
                              "message": f"measure {m['id']}: {len(out)} value(s) outside the expected {e[0]}–{e[1]}"
                                         f" (e.g. {out[0]:g})"})
    return notes
