"""Analysis-ready data tables and exports.

What the raw session log looks like (``trials.jsonl``): one record per routine
run. What analysts want: **one row per trial**, columns in a sensible order,
a per-condition summary and a codebook explaining every column. This module
builds those automatically:

* ``wide_trials``     merges all routines of one loop iteration into one row, renames
                      clashing columns, orders columns (ids, design, conditions,
                      responses, timing, variables) and drops columns that are always empty
* ``summarize``       detects the main response component and the condition factors and
                      computes n, accuracy, miss rate and RT mean/median/SD (correct trials,
                      outliers excluded) overall and per factor level, per participant
* ``data_dictionary`` describes every column: meaning, group, type, units, levels/range,
                      missing count, derived from the experiment definition itself
* writers             CSV, TSV, JSON, JSONL, Excel (.xlsx, no dependencies), Parquet (pyarrow/pandas),
                      MATLAB (.mat, scipy) and a BIDS-style folder (beh, events, physio)
* ``export_many``     merges many sessions/participants into one dataset with a sessions table
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
import statistics
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

import yaml

FORMATS = ("csv", "tsv", "xlsx", "json", "jsonl", "parquet", "mat", "bids")

STRUCT_COLS = {"routine", "routine_index", "routine_start", "routine_duration", "trial_key", "loop", "experiment"}

RESPONSE_SUFFIXES = ("keys", "rt", "corr", "rating", "clicked", "button", "x", "y", "entered", "first_entry",
                     "dwell_time", "entries", "completed", "result", "history", "path")
TIMING_SUFFIXES = ("onset", "duration", "start", "time")
UNITS = {"rt": "s", "onset": "s", "duration": "s", "start": "s", "time": "s", "first_entry": "s", "dwell_time": "s"}
GROUP_ORDER = ["id", "design", "condition", "response", "timing", "variable", "other"]


# ============================================================================ loading
class SessionTables:
    """Raw rows + metadata + the experiment definition for one session folder."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.meta: dict[str, Any] = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
        self.rows: list[dict[str, Any]] = _read_jsonl(self.root / "trials.jsonl")
        self.events: list[dict[str, Any]] = _read_jsonl(self.root / "events.jsonl")
        exp_file = self.root / "experiment.yaml"
        self.experiment: dict[str, Any] = (yaml.safe_load(exp_file.read_text(encoding="utf-8")) or {}) \
            if exp_file.exists() else {}
        self.comp_types: dict[str, str] = {}
        self.comp_routine: dict[str, str] = {}
        self.survey_columns: dict[str, dict[str, str]] = {}   # survey component -> column -> description
        for rid, r in (self.experiment.get("routines") or {}).items():
            for c in (r or {}).get("components", []) or []:
                self.comp_types.setdefault(c.get("id"), c.get("type"))
                self.comp_routine.setdefault(c.get("id"), rid)
                if c.get("type") == "survey" and c.get("id") not in self.survey_columns:
                    try:
                        from .survey import columns
                        self.survey_columns[c["id"]] = columns(c.get("questions") or [], c.get("scores") or {})
                    except Exception:
                        self.survey_columns[c["id"]] = {}
        self.loops: dict[str, dict[str, Any]] = self.meta.get("loops", {}) or {}
        self.condition_cols: dict[str, str] = {}   # column -> loop id
        for lid, info in self.loops.items():
            for col in info.get("columns", []) or []:
                self.condition_cols.setdefault(col, lid)
        self.participant_fields = list((self.meta.get("participant") or {}).keys())
        self.variables = set((self.meta.get("variables") or {}).keys()) | set(self.experiment.get("variables") or {})

    @property
    def name(self) -> str:
        return self.root.name


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # a truncated last line after a crash
    return out


def find_sessions(path: str | Path, include_dry_runs: bool = False) -> list[Path]:
    p = Path(path)
    if (p / "session.json").exists():
        return [p]
    out = []
    for s in sorted(p.rglob("session.json")):
        root = s.parent
        if not include_dry_runs and "dry_runs" in root.parts:
            continue
        out.append(root)
    return out


# ============================================================================ wide trials
def _is_loop_col(col: str, loops: Iterable[str]) -> bool:
    head, _, tail = col.rpartition(".")
    return tail in ("n", "repeat", "row", "state", "visit") and head in loops


def wide_trials(st: SessionTables, drop_empty: bool = True) -> tuple[list[str], list[dict[str, Any]]]:
    """One row per trial (loop iteration); routines outside loops get their own row."""
    loops = set(st.loops)
    groups: list[list[dict[str, Any]]] = []
    for row in st.rows:
        key = row.get("trial_key") or ""
        if groups and key and groups[-1][0].get("trial_key") == key:
            groups[-1].append(row)
        else:
            groups.append([row])

    session_started = st.meta.get("started")
    out_rows = []
    for i, grp in enumerate(groups, 1):
        first = grp[0]
        w: dict[str, Any] = {"experiment": first.get("experiment", st.meta.get("experiment"))}
        for f in st.participant_fields:
            w[f] = first.get(f, st.meta.get("participant", {}).get(f))
        w["session_started"] = session_started
        w["trial"] = i
        w["loop"] = first.get("loop") or ""
        w["routines"] = "+".join(r.get("routine", "") for r in grp)
        for k, v in first.items():
            if _is_loop_col(k, loops) or k in st.condition_cols:
                w[k] = v
        for r in grp:
            rid = r.get("routine", "")
            for k, v in r.items():
                if k in STRUCT_COLS or k in st.participant_fields or k in w and (k in st.condition_cols or _is_loop_col(k, loops)):
                    if k == "routine_start":
                        _put(w, f"{rid}.start", v, rid)
                    elif k == "routine_duration":
                        _put(w, f"{rid}.duration", v, rid)
                    continue
                if k in st.variables:
                    w[k] = v  # value at the end of the trial
                    continue
                _put(w, k, v, rid)
        out_rows.append({k: _round(v) for k, v in w.items()})

    cols = order_columns(st, out_rows)
    if drop_empty:
        cols = [c for c in cols if any(r.get(c) not in (None, "", [], {}) for r in out_rows)
                or c in ("experiment", "trial")]
    return cols, out_rows


def _round(v: Any) -> Any:
    """Clock arithmetic leaves float noise (0.49999999999954525); microsecond precision is plenty."""
    if isinstance(v, float) and not math.isnan(v):
        return round(v, 6)
    return v


def _put(w: dict[str, Any], key: str, value: Any, routine: str) -> None:
    if key not in w:
        w[key] = value
        return
    alt = f"{routine}.{key}"
    n = 2
    while alt in w:
        alt = f"{routine}.{key}_{n}"
        n += 1
    w[alt] = value


def classify(col: str, st: SessionTables) -> str:
    if col in ("experiment", "session_started") or col in st.participant_fields:
        return "id"
    if col in ("trial", "loop", "routines", "trial_key", "routine_index") or _is_loop_col(col, st.loops):
        return "design"
    if col in st.condition_cols:
        return "condition"
    if col in st.variables:
        return "variable"
    suffix = col.rpartition(".")[2]
    comp = col.rpartition(".")[0]
    if comp in (st.experiment.get("routines") or {}) and suffix in ("start", "duration"):
        return "timing"
    if st.comp_types.get(comp) in ("html", "survey") and suffix not in ("onset", "duration"):
        return "response"
    if "." in col and suffix.rstrip("_0123456789") in RESPONSE_SUFFIXES:
        return "response"
    if "." in col and suffix in TIMING_SUFFIXES or col in ("routine_start", "routine_duration"):
        return "timing"
    if "." in col and suffix in ("label", "code"):
        return "other"
    return "other"


def order_columns(st: SessionTables, rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    s = set()
    for r in rows:
        for k in r:
            if k not in s:
                s.add(k)
                seen.append(k)
    groups: dict[str, list[str]] = {g: [] for g in GROUP_ORDER}
    for c in seen:
        groups[classify(c, st)].append(c)
    # responses: keep components together, primary measures first (keys, rt, corr ...)
    rank = {suf: i for i, suf in enumerate(RESPONSE_SUFFIXES)}

    first_idx: dict[str, int] = {}
    for i, x in enumerate(groups["response"]):
        first_idx.setdefault(x.rpartition(".")[0], i)

    def comp_key(c: str) -> tuple[int, int]:
        return first_idx[c.rpartition(".")[0]], rank.get(c.rpartition(".")[2].rstrip("_0123456789"), 99)

    groups["response"].sort(key=comp_key)
    return [c for g in GROUP_ORDER for c in groups[g]]


# ============================================================================ summary
def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        return float(v)
    return None


def detect_measures(st: SessionTables, rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Pick the main response component: the one with the most non-missing RTs (corr preferred)."""
    best, best_score = None, -1
    comps = {c.rpartition(".")[0] for r in rows for c in r if c.endswith(".rt")
             and st.comp_types.get(c.rpartition(".")[0]) not in ("survey", "html")}   # page times aren't RTs
    for comp in comps:
        n_rt = sum(_num(r.get(f"{comp}.rt")) is not None for r in rows)
        n_corr = sum(r.get(f"{comp}.corr") is not None for r in rows)
        score = n_rt + (0.5 * n_corr)
        if score > best_score:
            best, best_score = comp, score
    if best is None:
        return None, None
    corr = f"{best}.corr" if any(r.get(f"{best}.corr") is not None for r in rows) else None
    return f"{best}.rt", corr


def detect_factors(st: SessionTables, rows: list[dict[str, Any]], max_levels: int = 12) -> list[str]:
    out = []
    for col in st.condition_cols:
        if re.search(r"(correct|answer|corr_?key|^key|_key$|stim(ulus)?_?file|image|sound|file)", col, re.I):
            continue
        levels = {json.dumps(r.get(col), default=str) for r in rows if col in r}
        if 2 <= len(levels) <= max_levels:
            out.append(col)
    return out


def _stats(rows: list[dict[str, Any]], rt: str | None, corr: str | None, outlier_sd: float,
           min_rt: float) -> dict[str, Any]:
    d: dict[str, Any] = {"n_trials": len(rows)}
    if corr:
        cs = [_num(r.get(corr)) for r in rows]
        cs = [c for c in cs if c is not None]
        d["accuracy"] = round(statistics.fmean(cs), 4) if cs else None
    if rt:
        rts_all = [(r, _num(r.get(rt))) for r in rows]
        responded = [(r, v) for r, v in rts_all if v is not None]
        d["n_responses"] = len(responded)
        d["miss_rate"] = round(1 - len(responded) / len(rows), 4) if rows else None
        pool = [v for r, v in responded if not corr or _num(r.get(corr)) == 1]
        pool = [v for v in pool if v >= min_rt]
        n_fast = sum(1 for r, v in responded if v < min_rt)
        if len(pool) >= 3 and outlier_sd:
            m, sd = statistics.fmean(pool), statistics.pstdev(pool)
            kept = [v for v in pool if abs(v - m) <= outlier_sd * sd] if sd > 0 else pool
        else:
            kept = pool
        d["n_rt_outliers"] = (len(pool) - len(kept)) + n_fast
        d["rt_mean"] = round(statistics.fmean(kept), 5) if kept else None
        d["rt_median"] = round(statistics.median(kept), 5) if kept else None
        d["rt_sd"] = round(statistics.stdev(kept), 5) if len(kept) > 1 else None
    return d


def summarize(st: SessionTables, rows: list[dict[str, Any]] | None = None, by: list[str] | None = None,
              rt: str | None = None, correct: str | None = None, outlier_sd: float = 3.0,
              min_rt: float = 0.1) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Per-participant summary overall and per level of each condition factor.

    RT statistics use correct trials only (when correctness is known), exclude
    anticipations (< ``min_rt``) and values beyond ``outlier_sd`` SDs.
    Returns (columns, rows, info about what was detected).
    """
    if rows is None:
        _, rows = wide_trials(st, drop_empty=False)
    cfg = (st.experiment.get("settings") or {}).get("data", {}).get("summary") or {}
    auto_rt, auto_corr = detect_measures(st, rows)
    rt = rt or cfg.get("rt") or auto_rt
    correct = correct or cfg.get("correct") or (auto_corr if not cfg.get("rt") else None)
    declared_factors = [m["column"] for m in _declared(st) if m["role"] == "factor"]
    factors = by if by is not None else (cfg.get("by") or declared_factors or detect_factors(st, rows))
    trial_rows = [r for r in rows if r.get("loop")] or rows   # instructions etc. aren't trials
    pid_fields = [f for f in st.participant_fields if f in ("participant", "session")] or st.participant_fields[:1]
    out: list[dict[str, Any]] = []
    parts: dict[tuple, list[dict[str, Any]]] = {}
    for r in trial_rows:
        parts.setdefault(tuple(r.get(f) for f in pid_fields), []).append(r)
    for pid, prow in parts.items():
        base = dict(zip(pid_fields, pid))
        out.append({**base, "factor": "(all)", "level": "", **_stats(prow, rt, correct, outlier_sd, min_rt)})
        for f in factors:
            levels: dict[str, list[dict[str, Any]]] = {}
            for r in prow:
                levels.setdefault(json.dumps(r.get(f), default=str), []).append(r)
            for lev, lrows in sorted(levels.items()):
                out.append({**base, "factor": f, "level": json.loads(lev),
                            **_stats(lrows, rt, correct, outlier_sd, min_rt)})
    cols = pid_fields + ["factor", "level", "n_trials"]
    for c in ("n_responses", "miss_rate", "accuracy", "rt_mean", "rt_median", "rt_sd", "n_rt_outliers"):
        if any(c in r for r in out):
            cols.append(c)
    info = {"rt_column": rt, "correct_column": correct, "factors": factors, "outlier_sd": outlier_sd,
            "min_rt": min_rt, "rt_uses": "correct trials only" if correct else "all responded trials"}
    return cols, out, info


def _declared(st: SessionTables) -> list[dict[str, Any]]:
    from .measures import declared
    return declared(st.experiment)


def measures_table(st: SessionTables, rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    from .measures import measure_table
    p = st.meta.get("participant") or {}
    base = {k: p[k] for k in ("participant", "session") if k in p}
    return measure_table(st.experiment, rows, base)


# ============================================================================ dictionary
def _output_meta(col: str, st: SessionTables) -> dict[str, Any] | None:
    """The component's own declaration of this column (Component.outputs), if any."""
    comp, _, attr = col.rpartition(".")
    cid = comp.split(".")[-1]
    ctype = st.comp_types.get(cid)
    if not ctype:
        return None
    from .components import component_registry
    cls = component_registry().get(ctype)
    if cls is None:
        return None
    meta = cls.outputs.get(attr) or cls.outputs.get(attr.rstrip("_0123456789"))
    return dict(meta, who=f"'{comp}' ({ctype})") if meta else None


def describe_column(col: str, st: SessionTables) -> str:
    group = classify(col, st)
    if col == "experiment":
        return "Experiment name"
    if col == "session_started":
        return "Date and time the session started"
    if col in st.participant_fields:
        return "Participant information field"
    if col == "trial":
        return "Row number in this table (1 = first trial of the session)"
    if col == "loop":
        return "Innermost loop this trial belongs to (empty for routines outside loops)"
    if col == "routines":
        return "Routines that ran in this trial, in order"
    if _is_loop_col(col, st.loops):
        lid, _, what = col.rpartition(".")
        return {"n": f"Iteration index within loop '{lid}' (0-based)",
                "repeat": f"Repetition number of loop '{lid}' (0-based)",
                "row": f"Row of loop '{lid}''s conditions table used for this trial (0-based)",
                "state": f"Current state of state machine '{lid}'",
                "visit": f"How many times the current state of '{lid}' has been entered (1 = first)"}[what]
    if group == "condition":
        lid = st.condition_cols[col]
        src = st.loops.get(lid, {}).get("source")
        return f"Condition variable from loop '{lid}'" + (f" ({src})" if src else "")
    if group == "variable":
        return "Experiment variable (value at the end of the trial)"
    comp, _, attr = col.rpartition(".")
    base_attr = attr.rstrip("_0123456789")
    if comp in st.experiment.get("routines", {}) and attr in ("start", "duration"):
        return {"start": f"Master-clock time (s) of the first screen flip of routine '{comp}'",
                "duration": f"Duration (s) of routine '{comp}'"}[attr]
    ctype = st.comp_types.get(comp.split(".")[-1], "")
    who = f"'{comp}'" + (f" ({ctype})" if ctype else "")
    if ctype == "survey":
        cid = comp.split(".")[-1]
        known = st.survey_columns.get(cid, {})
        if attr in known:
            return f"{known[attr]} (survey {who})"
        if attr == "submitted":
            return f"1 if the survey {who} was completed"
        if attr == "rt":
            return f"Time (s) from showing the survey {who} to its submission"
    if ctype == "html" and attr not in ("onset", "duration", "rt", "submitted"):
        return f"Answer to form field '{attr}' on HTML page {who}"
    if ctype == "html" and attr == "submitted":
        return f"1 if the HTML page {who} was submitted"
    if ctype == "html" and attr == "rt":
        return f"Time (s) from showing the HTML page {who} to its submission"
    templates = {
        "keys": f"Key(s) pressed in {who}; empty = no response",
        "rt": f"Response time (s) of {who}, from its onset flip to the response",
        "corr": f"Correctness of the {who} response: 1 = correct, 0 = incorrect",
        "time": f"Master-clock time (s) of the {who} response",
        "onset": f"Onset of {who} (s from routine start, at the screen flip)",
        "duration": f"How long {who} was active (s)",
        "rating": f"Rating given on {who}",
        "clicked": f"Which target was clicked in {who}",
        "button": f"Mouse button used in {who}",
        "x": f"Horizontal response position in {who} (experiment units)",
        "y": f"Vertical response position in {who} (experiment units)",
        "entered": f"1 if gaze entered {who}",
        "first_entry": f"Time (s) from onset until gaze first entered {who}",
        "dwell_time": f"Total gaze dwell time (s) in {who}",
        "entries": f"Number of gaze entries into {who}",
        "completed": f"1 if the dwell criterion of {who} was met",
        "result": f"Result of {who}",
        "label": f"Marker label sent by {who}",
        "code": f"TTL code sent by {who}",
        "history": f"All values selected in {who} (time, value)",
        "path": f"Mouse trajectory in {who} (time, x, y)",
    }
    if base_attr in templates:
        return templates[base_attr]
    meta = _output_meta(col, st)
    if meta:
        return meta["desc"].replace("{who}", who)
    return f"{attr} of {who}" if comp else col


def _type_of(values: list[Any]) -> str:
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return "empty"
    if all(isinstance(v, bool) for v in vals):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return "number"
    if all(isinstance(v, (list, dict)) for v in vals):
        return "list"
    return "text"


def data_dictionary(st: SessionTables, cols: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in cols:
        vals = [r.get(c) for r in rows]
        t = _type_of(vals)
        meta = _output_meta(c, st)
        units = meta["units"] if meta and meta.get("units") else \
            UNITS.get(c.rpartition(".")[2].rstrip("_0123456789"), "") if classify(c, st) in ("response", "timing") else ""
        entry: dict[str, Any] = {"column": c, "group": classify(c, st), "description": describe_column(c, st),
                                 "type": t, "units": units,
                                 "n": sum(v not in (None, "") for v in vals),
                                 "missing": sum(v in (None, "") for v in vals)}
        present = [v for v in vals if v not in (None, "")]
        if t in ("integer", "number") and present:
            entry["min"], entry["max"] = min(present), max(present)
        is_categorical = entry["group"] in ("condition", "id") or t in ("text", "boolean") \
            or (t == "integer" and c.rpartition(".")[2] in ("corr", "entered", "completed", "repeat"))
        if is_categorical:
            levels = {json.dumps(v, default=str) for v in present}
            if 0 < len(levels) <= 20:
                entry["levels"] = sorted((json.loads(x) for x in levels), key=lambda v: (str(type(v)), v))
        out.append(entry)
    return out


# ============================================================================ writers
def _cell(v: Any) -> Any:
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, default=str)
    return "" if v is None else v


def write_delimited(path: Path, cols: list[str], rows: list[dict[str, Any]], delimiter: str = ",") -> Path:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in cols])
    # utf-8-sig so Excel opens accents/symbols correctly
    path.write_text(buf.getvalue(), encoding="utf-8-sig")
    return path


def write_json(path: Path, cols: list[str], rows: list[dict[str, Any]], lines: bool = False) -> Path:
    clean = [{c: r.get(c) for c in cols} for r in rows]
    if lines:
        path.write_text("".join(json.dumps(r, default=str) + "\n" for r in clean), encoding="utf-8")
    else:
        path.write_text(json.dumps(clean, indent=1, default=str), encoding="utf-8")
    return path


_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_sheet(cols: list[str], rows: list[dict[str, Any]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews>', "<cols>"]
    for i, c in enumerate(cols):
        width = max([len(str(c))] + [len(str(_cell(r.get(c)))) for r in rows[:200]]) + 2
        out.append(f'<col min="{i + 1}" max="{i + 1}" width="{min(max(width, 6), 60)}" customWidth="1"/>')
    out.append("</cols><sheetData>")

    def cell(ref: str, v: Any, header: bool = False) -> str:
        style = ' s="1"' if header else ""
        if isinstance(v, bool):
            return f'<c r="{ref}" t="b"{style}><v>{int(v)}</v></c>'
        if isinstance(v, (int, float)) and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return f'<c r="{ref}"{style}><v>{repr(v) if isinstance(v, float) else v}</v></c>'
        v = _cell(v)
        if v == "":
            return ""
        text = escape(_ILLEGAL_XML.sub("", str(v)))[:32000]
        return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>'

    out.append('<row r="1">' + "".join(cell(f"{_col_letter(i)}1", c, True) for i, c in enumerate(cols)) + "</row>")
    for n, r in enumerate(rows, start=2):
        out.append(f'<row r="{n}">' + "".join(cell(f"{_col_letter(i)}{n}", r.get(c)) for i, c in enumerate(cols)) + "</row>")
    out.append("</sheetData>")
    if cols:
        out.append(f'<autoFilter ref="A1:{_col_letter(len(cols) - 1)}{max(len(rows) + 1, 1)}"/>')
    out.append("</worksheet>")
    return "".join(out)


def write_xlsx(path: Path, sheets: dict[str, tuple[list[str], list[dict[str, Any]]]]) -> Path:
    """Minimal, dependency-free .xlsx writer: typed cells, bold frozen header, filters, column widths."""
    names = []
    for name in sheets:
        clean = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "Sheet"
        while clean in names:
            clean = clean[:28] + f"_{len(names)}"
        names.append(clean)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(names))) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + "</sheets><definedNames>"
                   + "".join(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                             f"'{escape(n)}'!$A$1:${_col_letter(len(sheets[k][0]) - 1)}${len(sheets[k][1]) + 1}"
                             "</definedName>"
                             for i, (n, k) in enumerate(zip(names, sheets)) if sheets[k][0])
                   + "</definedNames>"
                   + "</workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(len(names)))
                   + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   "</styleSheet>")
        for i, key in enumerate(sheets):
            cols, rows = sheets[key]
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _xlsx_sheet(cols, rows))
    return path


def write_parquet(path: Path, cols: list[str], rows: list[dict[str, Any]]) -> Path:
    clean = [{c: _cell(r.get(c)) if isinstance(r.get(c), (list, dict)) else r.get(c) for c in cols} for r in rows]
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(clean), path)
        return path
    except ImportError:
        pass
    try:
        import pandas as pd
        pd.DataFrame(clean, columns=cols).to_parquet(path)
        return path
    except ImportError as e:
        raise ImportError("Parquet export needs pyarrow: pip install pyarrow") from e


def write_mat(path: Path, cols: list[str], rows: list[dict[str, Any]]) -> Path:
    try:
        import numpy as np
        from scipy.io import savemat
    except ImportError as e:
        raise ImportError("MATLAB export needs scipy: pip install scipy") from e
    data = {}
    for c in cols:
        vals = [r.get(c) for r in rows]
        key = re.sub(r"\W", "_", c)[:63]
        if _type_of(vals) in ("integer", "number", "boolean"):
            data[key] = np.array([np.nan if v is None else float(v) for v in vals])
        else:
            data[key] = np.array([str(_cell(v)) for v in vals], dtype=object)
    savemat(path, {"trials": data})
    return path


def write_table(path: Path, fmt: str, cols: list[str], rows: list[dict[str, Any]]) -> Path:
    if fmt == "csv":
        return write_delimited(path, cols, rows, ",")
    if fmt == "tsv":
        return write_delimited(path, cols, rows, "\t")
    if fmt == "json":
        return write_json(path, cols, rows)
    if fmt == "jsonl":
        return write_json(path, cols, rows, lines=True)
    if fmt == "parquet":
        return write_parquet(path, cols, rows)
    if fmt == "mat":
        return write_mat(path, cols, rows)
    if fmt == "xlsx":
        return write_xlsx(path, {"trials": (cols, rows)})
    raise ValueError(f"unknown format '{fmt}' (choose from {', '.join(FORMATS)})")


DICT_COLS = ["column", "group", "description", "type", "units", "n", "missing", "min", "max", "levels"]


# ============================================================================ BIDS
def _bids_label(v: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(v)) or "x"


def export_bids(st: SessionTables, out_root: Path) -> list[Path]:
    """BIDS-style folder: behavioural table, events and continuous recordings (physio)."""
    p = st.meta.get("participant", {})
    sub, ses = _bids_label(p.get("participant", "01")), _bids_label(p.get("session", "1"))
    task = _bids_label(st.meta.get("experiment", "task"))
    d = out_root / f"sub-{sub}" / f"ses-{ses}" / "beh"
    d.mkdir(parents=True, exist_ok=True)
    stem = f"sub-{sub}_ses-{ses}_task-{task}"
    files = []
    cols, rows = wide_trials(st)
    files.append(write_delimited(d / f"{stem}_beh.tsv", cols, rows, "\t"))
    dd = data_dictionary(st, cols, rows)
    (d / f"{stem}_beh.json").write_text(json.dumps(
        {e["column"]: {k: v for k, v in {"Description": e["description"], "Units": e["units"] or None,
                                         "Levels": {str(lv): str(lv) for lv in e.get("levels", [])} or None}.items() if v}
         for e in dd}, indent=2), encoding="utf-8")
    files.append(d / f"{stem}_beh.json")
    t0 = next((e["time"] for e in st.events if e.get("label") == "session_start"), None)
    if t0 is None:
        t0 = st.events[0]["time"] if st.events else 0.0
    ev_rows = [{"onset": round(e["time"] - t0, 6), "duration": "n/a", "trial_type": e.get("label"),
                "value": e.get("code") if e.get("code") is not None else "n/a", "source": e.get("source") or "n/a"}
               for e in st.events]
    files.append(write_delimited(d / f"{stem}_events.tsv", ["onset", "duration", "trial_type", "value", "source"],
                                 ev_rows, "\t"))
    (d / f"{stem}_events.json").write_text(json.dumps({
        "onset": {"Description": "Seconds from session start (EDGE 'session_start' marker)", "Units": "s"},
        "trial_type": {"Description": "EDGE marker label"},
        "value": {"Description": "TTL code sent to hardware"},
        "source": {"Description": "Routine.component that sent the marker"},
        "StimulusPresentation": {"SoftwareName": "EDGE", "SoftwareVersion": st.meta.get("edge_version")},
    }, indent=2), encoding="utf-8")
    files.append(d / f"{stem}_events.json")
    for f in sorted((st.root / "streams").glob("*.csv")):
        if f.name.endswith(".raw.csv"):
            continue
        device, stream = f.stem.split(".", 1)
        info = st.meta.get("devices", {}).get(device, {}).get("streams", {}).get(stream, {})
        with f.open(newline="", encoding="utf-8") as src:
            r = csv.reader(src)
            header = next(r)
            data = list(r)
        if not data:
            continue
        rec = f"{stem}_recording-{_bids_label(device + stream)}_physio"
        with gzip.open(d / f"{rec}.tsv.gz", "wt", encoding="utf-8", newline="") as gz:
            w = csv.writer(gz, delimiter="\t", lineterminator="\n")
            for row in data:
                w.writerow([row[0]] + row[3:])
        (d / f"{rec}.json").write_text(json.dumps({
            "SamplingFrequency": info.get("srate") or "n/a",
            "StartTime": round(float(data[0][0]) - t0, 6),
            "Columns": ["time"] + header[3:],
            "Manufacturer": st.meta.get("devices", {}).get(device, {}).get("type"),
            "RecordingType": info.get("kind"),
        }, indent=2), encoding="utf-8")
        files += [d / f"{rec}.tsv.gz", d / f"{rec}.json"]
    desc = out_root / "dataset_description.json"
    if not desc.exists():
        desc.write_text(json.dumps({"Name": st.meta.get("experiment"), "BIDSVersion": "1.9.0",
                                    "GeneratedBy": [{"Name": "EDGE", "Version": st.meta.get("edge_version")}]},
                                   indent=2), encoding="utf-8")
    ptsv = out_root / "participants.tsv"
    existing = ptsv.read_text(encoding="utf-8").splitlines() if ptsv.exists() else ["participant_id"]
    if f"sub-{sub}" not in existing:
        existing.append(f"sub-{sub}")
        ptsv.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return files


# ============================================================================ high level
def session_tables(st: SessionTables, layout: str = "wide") -> dict[str, tuple[list[str], list[dict[str, Any]]]]:
    if layout == "long":
        cols = order_columns(st, st.rows)
        rows = st.rows
        cols = [c for c in cols if any(r.get(c) not in (None, "") for r in rows)]
    else:
        cols, rows = wide_trials(st)
    _, wide = wide_trials(st, drop_empty=False) if layout == "long" else (cols, rows)
    scols, srows, _ = summarize(st, wide)
    dd = data_dictionary(st, cols, rows)
    ev_cols = ["time", "label", "code", "source", "on_flip"]
    t = timing_row(st)
    out = {"trials": (cols, rows), "summary": (scols, srows), "dictionary": (DICT_COLS, dd),
           "events": (ev_cols, st.events), "session": (list(t), [t])}
    if _declared(st):
        out["measures"] = measures_table(st, wide)
    return out


def timing_row(st: SessionTables) -> dict[str, Any]:
    m = st.meta
    t = m.get("timing") or {}
    return {"session": st.name, "experiment": m.get("experiment"), **{k: v for k, v in (m.get("participant") or {}).items()},
            "started": m.get("started"), "ended": m.get("ended"), "aborted": m.get("aborted"),
            "dry_run": m.get("dry_run"), "frames": t.get("frames"), "dropped_frames": t.get("dropped_frames"),
            "refresh_rate_hz": t.get("refresh_rate_hz"), "devices": ", ".join(m.get("devices", {}).keys()),
            "errors": len(m.get("errors", [])), "seed": m.get("seed"), "edge_version": m.get("edge_version")}


def export_session(session_dir: str | Path, formats: Iterable[str] = ("csv",), out_dir: str | Path | None = None,
                   layout: str = "wide") -> list[Path]:
    st = SessionTables(session_dir)
    out = Path(out_dir) if out_dir else st.root / "exports"
    out.mkdir(parents=True, exist_ok=True)
    tables = session_tables(st, layout)
    return _write_all(tables, formats, out, st.name, [st])


def _write_all(tables, formats, out: Path, stem: str, sessions: list[SessionTables]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for fmt in formats:
        fmt = fmt.lower().strip()
        if fmt == "bids":
            for st in sessions:
                files += export_bids(st, out / "bids")
        elif fmt == "xlsx":
            files.append(write_xlsx(out / f"{stem}.xlsx", tables))
        else:
            ext = {"jsonl": "jsonl", "mat": "mat"}.get(fmt, fmt)
            files.append(write_table(out / f"{stem}_trials.{ext}", fmt, *tables["trials"]))
            if fmt in ("csv", "tsv", "json"):
                files.append(write_table(out / f"{stem}_summary.{ext}", fmt, *tables["summary"]))
                files.append(write_table(out / f"{stem}_dictionary.{ext}", fmt, *tables["dictionary"]))
                if "sessions" in tables:
                    files.append(write_table(out / f"{stem}_sessions.{ext}", fmt, *tables["sessions"]))
                if "measures" in tables:
                    files.append(write_table(out / f"{stem}_measures.{ext}", fmt, *tables["measures"]))
    return files


def export_many(path: str | Path, formats: Iterable[str] = ("csv", "xlsx"), out_dir: str | Path | None = None,
                include_dry_runs: bool = False, name: str | None = None) -> dict[str, Any]:
    """Merge every session under ``path`` into one dataset (trials, summary, dictionary, sessions)."""
    roots = find_sessions(path, include_dry_runs)
    if not roots:
        raise FileNotFoundError(f"no EDGE sessions found under {path}")
    sessions = [SessionTables(r) for r in roots]
    all_rows, sum_rows, sess_rows, dd_by_col = [], [], [], {}
    meas_cols: list[str] = []
    meas_rows: list[dict[str, Any]] = []
    col_order: list[str] = []
    for st in sessions:
        cols, rows = wide_trials(st)
        for c in cols:
            if c not in col_order:
                col_order.append(c)
        for r in rows:
            r["session_folder"] = st.name
        all_rows += rows
        scols, srows, _ = summarize(st)
        sum_rows += srows
        if _declared(st):
            mcols, mrows = measures_table(st, rows)
            meas_cols += [c for c in mcols if c not in meas_cols]
            meas_rows += mrows
        sess_rows.append(timing_row(st))
        for e in data_dictionary(st, cols, rows):
            dd_by_col.setdefault(e["column"], e)
    # stable global order: group, then first appearance
    first = sessions[0]
    col_order = sorted(col_order, key=lambda c: (GROUP_ORDER.index(classify(c, first)), col_order.index(c)))
    col_order.insert(1, "session_folder")
    dd_by_col["session_folder"] = {"column": "session_folder", "group": "id", "type": "text",
                                   "description": "Session folder the row came from"}
    scols = []
    for r in sum_rows:
        for k in r:
            if k not in scols:
                scols.append(k)
    sess_cols = []
    for r in sess_rows:
        for k in r:
            if k not in sess_cols:
                sess_cols.append(k)
    tables = {"trials": (col_order, all_rows), "summary": (scols, sum_rows),
              "dictionary": (DICT_COLS, [dd_by_col[c] for c in col_order if c in dd_by_col]),
              "sessions": (sess_cols, sess_rows)}
    if meas_rows:
        tables["measures"] = (meas_cols, meas_rows)
    out = Path(out_dir) if out_dir else Path(path) / "exports"
    out.mkdir(parents=True, exist_ok=True)
    stem = name or f"{sessions[0].meta.get('experiment', 'edge')}_all_{datetime.now():%Y%m%d}"
    files = _write_all(tables, list(formats), out, stem, sessions)
    return {"sessions": len(sessions), "participants": len({r.get("participant") for r in sess_rows}),
            "trials": len(all_rows), "files": [str(f) for f in files]}


README_TXT = """EDGE session data
=================
trials_wide.csv      one row per trial (all routines of a loop iteration merged), analysis-ready
summary.csv          per-participant accuracy / RT overall and per condition level
measures.csv         your declared measures (experiment "measures:"), overall and per condition cell
data_dictionary.csv  what every column in trials_wide.csv means (type, units, levels, range)
trials.csv           one row per routine run (long format; trials.jsonl is the crash-safe original)
events.jsonl         every marker: master-clock time, label, TTL code, delivery time per device
frames.csv           every screen flip (frame-timing audit)
streams/             device recordings: time (aligned master clock), device_time, arrival_time, channels
session.json         settings, devices, clock models, marker codebook, timing summary, seed
experiment.yaml      the exact experiment that produced this data
Times are in seconds. Re-export any time with:  edge export <this folder> --formats xlsx,bids
"""


def auto_export(session_dir: str | Path, settings: dict[str, Any]) -> list[Path]:
    """Called at the end of every session: write the intelligent tables next to the raw data."""
    st = SessionTables(session_dir)
    files = []
    tables = session_tables(st, "wide")
    files.append(write_delimited(st.root / "trials_wide.csv", *tables["trials"]))
    files.append(write_delimited(st.root / "summary.csv", *tables["summary"]))
    files.append(write_delimited(st.root / "data_dictionary.csv", *tables["dictionary"]))
    if "measures" in tables:
        files.append(write_delimited(st.root / "measures.csv", *tables["measures"]))
    (st.root / "README.txt").write_text(README_TXT, encoding="utf-8")
    extra = [f for f in (settings.get("data", {}).get("exports") or []) if f != "csv"]
    if extra:
        files += _write_all(tables, extra, st.root / "exports", st.name, [st])
    return files
