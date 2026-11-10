"""Builder editing endpoints: expression checks as you type, paste with files, trial-list files edited in place.

Routes (all behind the builder's request guard, JSON in and out; a bad request is a BadRequest -> 400):

* ``POST /api/edit/check``   ``{experiment, path?, expr, where?}`` -> ``{ok, issues: [{level, message, hint, fix?}],
  words?, names: [{name, kind, detail}]}``. One expression checked in the context of one place of the experiment
  (an item of a screen, a rule, a trial list's "stop early when", an if / otherwise, a workflow route ...): syntax,
  names that don't exist ("did you mean"), and names that don't exist *there* (the static scope check of
  edge/scope.py, run on the experiment with the expression put in that place). ``names`` lists what is available
  there, for autocomplete.
* ``POST /api/edit/paste_files`` ``{from, to, fragment}`` -> ``{copied, renamed, missing, skipped}``. Copies the
  files a pasted fragment (screens, items, trial lists) uses from the source experiment's folder into the target
  experiment's folder. Both paths are confined to the builder's folder, every file to its experiment's folder;
  participant data, hidden files and file types that could run are never copied; nothing is overwritten (a
  different file of the same name is copied as ``name_2.ext`` and reported in ``renamed``).
* ``GET  /api/edit/table?exp=&file=&sheet=`` -> a CSV, TSV or Excel trial list as columns and rows, with its
  fingerprint (to notice changes made elsewhere) and what saving would lose (other sheets, formulas).
* ``POST /api/edit/table`` ``{exp, file, sheet?, columns, rows, fingerprint, force?, confirm_values?, as_csv?,
  backup?}`` -> ``{saved, fingerprint, backup}``. Writes the rows back in the file's own format after a backup in the
  file's version history (``backup: false`` skips it: the builder backs up once per editing session) (the same History as experiments: .edge/backups/<file>/, restored with /api/restore).
  Nothing is written, and the answer is ``{ok: false, conflict}`` when the file changed since it was read, or
  ``{ok: false, needs_confirm}`` when saving a
  workbook would replace formulas by their values or the workbook has other sheets (they are kept, but the
  edited sheet is written as values only).
"""

from __future__ import annotations

import ast
import copy
import csv
import difflib
import io
import re
from pathlib import Path
from typing import Any

from .. import expressions, storage

TABLE_SUFFIXES = (".csv", ".tsv", ".txt", ".xlsx")
MAX_TABLE_ROWS = 20000
MAX_TABLE_COLS = 500


class Conflict(Exception):
    """Nothing was written: the file changed elsewhere, or saving needs the person's confirmation first. A question
    for the person, not a failed request: answered 200 with ok: false (a browser logs every 4xx as an error)."""

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.extra = extra


def handle(app: Any, method: str, path: str, query: dict[str, str], body: Any) -> tuple[dict[str, Any], int]:
    from .server import BadRequest
    try:
        if method == "POST" and not isinstance(body, dict):
            raise BadRequest("the request body must be a JSON object")
        if method == "POST" and path == "/api/edit/check":
            return check_expression(app, _need(body, "experiment", dict), body.get("path"),
                                    _need(body, "expr", str), body.get("where") or {}), 200
        if method == "POST" and path == "/api/edit/names":
            return {"names": available_names(app, _need(body, "experiment", dict), body.get("path"),
                                             body.get("where") or {})}, 200
        if method == "POST" and path == "/api/edit/paste_files":
            return paste_files(app, _need(body, "from", str), _need(body, "to", str),
                               _need(body, "fragment", dict)), 200
        if method == "GET" and path == "/api/edit/table":
            return read_table(app, query.get("exp") or "", _q(query, "file"), query.get("sheet") or None), 200
        if method == "POST" and path == "/api/edit/table":
            return save_table(app, body), 200
    except Conflict as e:
        return {"ok": False, "message": str(e), **e.extra}, 200
    return {"error": "not found"}, 404


def _q(query: dict[str, str], key: str) -> str:
    from .server import BadRequest
    v = query.get(key)
    if not v:
        raise BadRequest(f"the request needs ?{key}=…")
    return v


def _need(body: dict[str, Any], key: str, kind: type) -> Any:
    from .server import BadRequest
    v = body.get(key)
    if v is None:
        raise BadRequest(f"the request needs '{key}'")
    if not isinstance(v, kind) or isinstance(v, bool) and kind is not bool:
        raise BadRequest(f"'{key}' must be {'an object' if kind is dict else 'a list' if kind is list else 'text'}")
    return v


# ============================================================================ expression checks
WHERE_FIELDS = {"value", "rule", "end_if", "duration", "if", "stop_if", "repeats", "conditions", "route",
                "measure", None}


def _where_node(doc: dict[str, Any], flow_path: Any) -> Any:
    from .server import BadRequest
    if not isinstance(flow_path, list) or not flow_path or len(flow_path) > 40:
        raise BadRequest("'where.flow' must be a path into the flow, e.g. [1] or [1, \"children\", 0]")
    cur: Any = doc.get("flow")
    try:
        for k in flow_path:
            if isinstance(cur, list) and isinstance(k, int) and not isinstance(k, bool):
                cur = cur[k]
            elif isinstance(cur, dict) and isinstance(k, str):
                cur = cur[k]
            else:
                raise KeyError(k)
    except (KeyError, IndexError, TypeError):
        raise BadRequest("'where.flow' doesn't name a step of this experiment") from None
    return cur


def _set_flow(doc: dict[str, Any], flow_path: list, value: Any) -> None:
    parent = _where_node(doc, flow_path[:-1]) if len(flow_path) > 1 else doc["flow"]
    parent[flow_path[-1]] = value


def _place(doc: dict[str, Any], where: dict[str, Any], src: str | None) -> None:
    """Put the expression (``src`` without '$'; None: leave the place empty) where it will be used. An item's
    property and a rule are checked as a rule of the screen: the same names are visible there."""
    from .server import BadRequest
    field = where.get("field")
    if field not in WHERE_FIELDS:
        raise BadRequest(f"unknown 'where.field' {field!r}")
    rid = where.get("routine")
    if field == "measure":
        if src is not None:
            doc.setdefault("measures", [])
            if isinstance(doc["measures"], list):
                doc["measures"].append({"id": "__check__", "column": "x", "trials": "$" + src})
        return
    if where.get("flow") is not None:
        node = _where_node(doc, where["flow"])
        flow_path = where["flow"]
        if field == "if":
            if isinstance(node, str) or isinstance(node, dict) and "routine" in node and "loop" not in node:
                rname = node if isinstance(node, str) else node["routine"]
                _set_flow(doc, flow_path, {"routine": rname, "if": "$" + src} if src is not None else rname)
            elif isinstance(node, dict) and "if" in node and "then" in node:
                node["if"] = "$" + src if src is not None else "$True"
            elif isinstance(node, dict) and src is not None:      # a trial list or workflow shown only if …
                _set_flow(doc, flow_path, {"if": "$" + src, "then": [node], "else": []})
            elif not isinstance(node, dict):
                raise BadRequest("this step has no condition")
            return
        if not isinstance(node, dict):
            raise BadRequest("'where.flow' must name a trial list, an if / otherwise or a workflow here")
        if "loop" in node:
            if field not in ("stop_if", "repeats", "conditions"):
                raise BadRequest(f"a trial list has no {field!r}")
            if src is not None:
                node[field] = "$" + src
            elif field == "repeats":
                node["repeats"] = 1
            else:
                node.pop(field, None)
            return
        if "statemachine" in node and field == "route":
            states = node.get("states") if isinstance(node.get("states"), dict) else {}
            st = states.get(where.get("state"))
            if not isinstance(st, dict):
                raise BadRequest("'where.state' must name a phase of this workflow")
            nxt = st.setdefault("next", [])
            if not isinstance(nxt, list):
                raise BadRequest("this phase's routes can't be read")
            if src is not None:
                goto = next(iter(states))
                nxt.append({"goto": goto, "if": "$" + src})
            return
        raise BadRequest(f"this step has no {field!r}")
    if rid is not None:
        routines = doc.get("routines") or {}
        if not isinstance(rid, str) or rid not in routines:
            raise BadRequest(f"there is no screen called {rid!r}")
        r = routines[rid] = dict(routines[rid] or {})
        if src is not None:
            r["rules"] = list(r.get("rules") or []) + [{"when": "$" + src, "do": [{"log": "check"}]}]
        # a screen that isn't in the experiment is checked as if it were shown at the end
        if not any(True for _ in _routine_refs(doc.get("flow") or [], rid)):
            doc["flow"] = list(doc.get("flow") or []) + [rid]
        return
    # nowhere in particular: the names every place can see
    if src is not None:
        doc.setdefault("routines", {})["__check__"] = {"components": [], "rules": [{"when": "$" + src, "do": [{"log": "check"}]}]}
        doc["flow"] = list(doc.get("flow") or []) + ["__check__"]


def _routine_refs(nodes: list, rid: str):
    for n in nodes or []:
        if n == rid or isinstance(n, dict) and n.get("routine") == rid:
            yield n
        if isinstance(n, dict):
            yield from _routine_refs(n.get("children") or [], rid)
            yield from _routine_refs(n.get("then") or [], rid)
            yield from _routine_refs(n.get("else") or [], rid)
            for st in (n.get("states") or {}).values() if isinstance(n.get("states"), dict) else []:
                if isinstance(st, dict):
                    yield from _routine_refs(st.get("run") or [], rid)


def _issues(app: Any, doc: dict[str, Any], rel: str | None) -> list[tuple[str, str, str, str]] | str:
    from ..model import Experiment
    from ..scope import scope_issues
    base = app.safe_path(rel).parent if rel else app.root
    try:
        exp = Experiment.from_dict(doc, base_dir=base)
    except Exception as e:          # the experiment itself can't be read: say so once, don't guess
        return str(e)
    return [(i.level, i.where, i.message, i.hint or "") for i in scope_issues(exp)]


def _elsewhere(app: Any, doc: dict[str, Any], rel: str | None, message: str) -> str:
    """'wrd' isn't defined … : when a trial list elsewhere has a column of a close name, say so (it isn't available
    at this place, which is the point of checking here)."""
    m = re.match(r"'([A-Za-z_]\w*)' isn't defined anywhere", message)
    if not m or "Did you mean" in message:
        return message
    from ..model import Experiment
    from ..scope import resolved_loop_columns
    try:
        cols = resolved_loop_columns(Experiment.from_dict(doc, base_dir=app.safe_path(rel).parent if rel else app.root))
    except Exception:
        return message
    by_col = {c: lp for lp, cs in cols.items() for c in (cs or ())}
    close = difflib.get_close_matches(m.group(1), sorted(by_col), n=1, cutoff=0.6)
    if not close:
        return message
    c = close[0]
    return (f"'{m.group(1)}' isn't available here. Did you mean '{c}'? That is a column of the trial list "
            f"'{by_col[c]}', which doesn't repeat this screen.")


_QUOTED = re.compile(r"'([A-Za-z_][\w]*)'")
_MEAN = re.compile(r"Did you mean '?([A-Za-z_][\w.]*)'?")
_USES = re.compile(r"uses ([A-Za-z_]\w*)\.([A-Za-z_]\w*)")


def _fix_for(message: str) -> dict[str, str] | None:
    """{"from": "inkk", "to": "ink"} for a message with one suggestion."""
    m = _MEAN.search(message)
    if not m:
        return None
    to = m.group(1).rstrip(".")
    u = _USES.search(message)
    if u:
        return {"from": f"{u.group(1)}.{u.group(2)}", "to": to}
    q = _QUOTED.search(message)
    return {"from": q.group(1), "to": to} if q and q.group(1) != to else None


def _plain(message: str) -> str:
    message = (message.replace("this component", "this item").replace("the trial list of loop '", "the trial list '")
               .replace("loop '", "trial list '").replace("outside that loop", "outside that trial list")
               .replace("?. ", "? ").replace("with a variable component", "with a Set a variable item")
               .replace("a trial list (loop)", "a trial list"))
    return message[:1].upper() + message[1:] if message else message


def syntax_problem(src: str) -> dict[str, Any] | None:
    """A syntax error or something expressions may not contain, in plain words, with the column of the mistake."""
    text = src.strip()
    if not text:
        return None
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        msg = expressions.syntax_message(src, e)
        return {"level": "error", "message": msg.replace(f"'{src}' isn't", "This isn't"), "hint": "",
                "col": (e.offset or 0)}
    try:
        expressions._check(tree, text)         # what the sandbox refuses (lambda, __dunder__, …)
    except expressions.ExpressionError as e:
        return {"level": "error", "message": str(e).split(":")[0].replace("in expression", "in a formula")
                + ". Formulas can compute values but not define functions or reach Python internals; use a "
                "Python code item for that.", "hint": ""}
    return None


def check_expression(app: Any, doc: dict[str, Any], rel: str | None, expr: str,
                     where: dict[str, Any]) -> dict[str, Any]:
    from .server import BadRequest
    if not isinstance(where, dict):
        raise BadRequest("'where' must be an object")
    if len(expr) > 10_000:
        raise BadRequest("the formula is too long")
    src = expr.strip()
    if src.startswith("$$"):           # $$text: literal text, nothing to check
        return {"ok": True, "issues": [], "names": available_names(app, doc, rel, where)}
    if src.startswith("$"):
        src = src[1:].strip()
    out: dict[str, Any] = {"ok": True, "issues": []}
    if where.get("names", True):
        out["names"] = available_names(app, doc, rel, where)
    if not src:
        return out
    bad = syntax_problem(src)
    if bad:
        out["ok"] = False
        out["issues"] = [bad]
        return out
    before, after = copy.deepcopy(doc), copy.deepcopy(doc)
    _place(before, where, None)
    _place(after, where, src)
    a = _issues(app, before, rel)
    b = _issues(app, after, rel)
    if isinstance(b, str):
        out["note"] = "The rest of the experiment can't be read yet, so only the syntax was checked."
        return out
    old = set(a) if isinstance(a, list) else set()
    seen: set[str] = set()
    for level, _w, message, hint in b:
        if (level, _w, message, hint) in old or level == "info" and "can't be checked before running" not in message:
            continue
        if message in seen:
            continue
        seen.add(message)
        message = _elsewhere(app, after, rel, message)
        item: dict[str, Any] = {"level": level, "message": _plain(message), "hint": _plain(hint)}
        fix = _fix_for(message) if "isn't available here" not in message else None
        if fix:
            item["fix"] = fix
        out["issues"].append(item)
    out["ok"] = not any(i["level"] == "error" for i in out["issues"])
    return out


FUNCTIONS = [("abs", "abs(x)"), ("round", "round(x, digits)"), ("min", "min(a, b, …)"), ("max", "max(a, b, …)"),
             ("len", "len(list or text)"), ("sum", "sum(list)"), ("int", "int(x)"), ("float", "float(x)"),
             ("str", "str(x)"), ("mean", "mean(list)"), ("sorted", "sorted(list)"), ("range", "range(n)"),
             ("any", "any(list)"), ("all", "all(list)"), ("bool", "bool(x)"), ("list", "list(x)"),
             ("True", "yes"), ("False", "no"), ("None", "no value (e.g. no response yet)")]
MODULE_FUNCTIONS = {"math": ["sqrt", "log", "exp", "floor", "ceil", "pi", "sin", "cos"],
                    "random": ["random", "randint", "choice", "uniform", "gauss", "shuffle", "sample"],
                    "statistics": ["mean", "median", "stdev"]}
LOOP_STATS = [("n", "trial number in this list (from 1)"), ("total", "number of trials in the list"),
              ("accuracy", "share of correct answers so far"), ("n_correct", "correct answers so far"),
              ("mean_rt", "mean response time so far"), ("repeat", "which repeat of the list")]


def available_names(app: Any, doc: dict[str, Any], rel: str | None, where: dict[str, Any]) -> list[dict[str, str]]:
    """What a formula at this place can use: trial-list columns of the lists around it, variables, participant
    info, results of items (resp.rt), trial-list and workflow statistics, and functions."""
    from ..model import Branch, Experiment, Loop, RoutineRef, StateMachine
    from ..diagnostics import _outputs_of
    from ..scope import resolved_loop_columns
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(name: str, kind: str, detail: str = "") -> None:
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "kind": kind, "detail": detail})

    base = app.safe_path(rel).parent if rel else app.root
    try:
        exp = Experiment.from_dict(copy.deepcopy(doc), base_dir=base)
    except Exception:
        exp = None
    if exp is not None:
        cols = resolved_loop_columns(exp)
        rid = where.get("routine")
        target = where.get("flow")
        around: list[str] = []          # trial lists around this place (outermost first)

        def walk(nodes, stack, path):
            for i, n in enumerate(nodes):
                p = path + [i]
                if isinstance(n, RoutineRef) and rid is not None and n.routine == rid:
                    around.extend(x for x in stack if x not in around)
                if target is not None and p == list(target):
                    around.extend(x for x in stack if x not in around)
                    if isinstance(n, Loop) and where.get("field") == "stop_if":
                        around.append(n.id)
                if isinstance(n, Loop):
                    walk(n.children, stack + [n.id], p + ["children"])
                elif isinstance(n, Branch):
                    walk(n.then, stack, p + ["then"])
                    walk(n.else_, stack, p + ["else"])
                elif isinstance(n, StateMachine):
                    for sname, st in n.states.items():
                        walk(st.run, stack, p + ["states", sname, "run"])
        walk(exp.flow, [], [])
        for lp in reversed(around):
            for c in sorted(cols.get(lp) or ()):
                add(c, "column", f"trial list “{lp}”")
        for k in (exp.variables or {}):
            add(str(k), "variable", "variable")
        for k in (exp.settings.get("participant") or {}):
            add(str(k), "participant", "participant info")
        add("participant", "participant", "participant info")
        add("session", "participant", "participant info")
        loops: list[str] = []
        machines: list[str] = []

        def ids(nodes):
            for n in nodes:
                if isinstance(n, Loop):
                    loops.append(n.id)
                    ids(n.children)
                elif isinstance(n, Branch):
                    ids(n.then)
                    ids(n.else_)
                elif isinstance(n, StateMachine):
                    machines.append(n.id)
                    for st in n.states.values():
                        ids(st.run)
        ids(exp.flow)
        here = list(reversed(around)) + [x for x in loops if x not in around]
        for lp in here:
            for k, words in LOOP_STATS:
                add(f"{lp}.{k}", "list", words)
        for m in machines:
            add(f"{m}.state", "workflow", "the phase now")
            add(f"{m}.visit", "workflow", "how often this phase ran")
        first = exp.routines.get(rid) if rid else None
        ordered = ([(rid, first)] if first else []) + [(k, r) for k, r in exp.routines.items() if k != rid]
        for r_id, r in ordered:
            for c in r.components:
                for o in _outputs_of(c.type):
                    add(f"{c.id}.{o}", "result", f"{c.id} on “{r_id}”")
                if c.type == "variable":
                    for k in (c.props.get("set") or {}):
                        add(str(k), "variable", f"set by {c.id}")
    for name in ("t", "frame"):
        add(name, "time", "seconds since the screen began" if name == "t" else "screen refreshes so far")
    for name, words in FUNCTIONS:
        add(name, "function", words)
    for mod, fns in MODULE_FUNCTIONS.items():
        for f in fns:
            add(f"{mod}.{f}", "function", mod)
    return out[:600]


# ============================================================================ paste with files
def paste_files(app: Any, src_rel: str, dst_rel: str, fragment: dict[str, Any]) -> dict[str, Any]:
    """Copy what a pasted fragment uses from one experiment's folder to another's (see the module docstring)."""
    import shutil
    from .server import BLOCKED_UPLOAD_SUFFIXES
    from ..assistant.attachments import data_roots, is_data_path
    src_file, dst_file = app.safe_path(src_rel), app.safe_path(dst_rel)
    src, dst = src_file.parent.resolve(), dst_file.parent.resolve()
    out: dict[str, Any] = {"copied": [], "renamed": {}, "missing": [], "skipped": [], "same": src == dst}
    if src == dst:
        return out
    if not src.is_dir():
        raise FileNotFoundError(f"the experiment {src_rel} isn't there any more")
    frag = {"routines": fragment.get("routines") if isinstance(fragment.get("routines"), dict) else {},
            "flow": fragment.get("flow") if isinstance(fragment.get("flow"), list) else []}
    try:
        refs = storage.referenced_files(frag, src)
    except Exception:
        refs = set()
    roots = data_roots(src, exp_file=src_file if src_file.is_file() else None)
    renamed: dict[str, str] = {}
    for ref in sorted(refs):
        if not isinstance(ref, str) or not ref or ref.startswith(("/", "\\")) or "\0" in ref or ":" in ref:
            out["skipped"].append(ref)
            continue
        a = (src / ref).resolve()
        if src not in a.parents or app.root not in a.parents or not a.is_file():
            out["missing"].append(ref)
            continue
        parts = a.relative_to(src).parts
        if a.suffix.lower() in BLOCKED_UPLOAD_SUFFIXES or any(x.startswith(".") for x in parts) \
                or "data" in parts[:-1] or is_data_path(src, a, roots):
            out["skipped"].append(ref)
            continue
        b = (dst / ref).resolve()
        if dst not in b.parents or app.root not in b.parents:
            out["skipped"].append(ref)
            continue
        if b.exists():
            if b.is_file() and b.read_bytes() == a.read_bytes():
                continue                                    # the same file is already there
            stem, suf, n = b.stem, b.suffix, 2
            while (b.parent / f"{stem}_{n}{suf}").exists():
                if (b.parent / f"{stem}_{n}{suf}").read_bytes() == a.read_bytes():
                    break
                n += 1
            nb = b.parent / f"{stem}_{n}{suf}"
            new_ref = str(Path(ref).parent / nb.name).replace("\\", "/").removeprefix("./")
            renamed[ref] = new_ref
            if nb.exists():
                continue
            b = nb
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, b)
        out["copied"].append(str(b.relative_to(dst)).replace("\\", "/"))
    # a trial-list file copied here that names a renamed picture or sound: point its cells at the new name
    if renamed:
        for ref in out["copied"]:
            p = dst / ref
            if p.suffix.lower() in (".csv", ".tsv", ".txt"):
                try:
                    text = p.read_bytes().decode("utf-8-sig")
                    delim = "\t" if p.suffix.lower() == ".tsv" else _sniff(text)
                    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
                    if any(c in renamed for r in rows for c in r):
                        rows = [[renamed.get(c, c) for c in r] for r in rows]
                        buf = io.StringIO()
                        csv.writer(buf, delimiter=delim, lineterminator=_newline(text)).writerows(rows)
                        storage.atomic_write(p, buf.getvalue())
                except (OSError, UnicodeDecodeError, csv.Error):
                    pass
    out["renamed"] = renamed
    return out


# ============================================================================ trial-list files
def _sniff(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text[:4096] else "\n"


def _table_path(app: Any, exp_rel: str, file: str) -> Path:
    from .server import BadRequest
    base = app.safe_path(exp_rel).parent if exp_rel else app.root
    if not isinstance(file, str) or not file or "\0" in file or len(file) > 1000:
        raise BadRequest("name the trial-list file, e.g. conditions/words.csv")
    p = (base / file).resolve()
    if base.resolve() not in p.parents or app.root not in p.parents:
        raise PermissionError("a trial-list file must be inside the experiment's folder")
    if p.suffix.lower() not in TABLE_SUFFIXES:
        raise BadRequest(f"{p.name}: only CSV, TSV, text and Excel (.xlsx) trial lists can be edited here")
    if any(x.startswith(".") for x in p.relative_to(base.resolve()).parts):
        raise PermissionError("hidden files can't be edited here")
    return p


def has_openpyxl() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def _xlsx_info(p: Path, sheet: str | None) -> dict[str, Any]:
    """Rows of one sheet (values as Excel shows them), the sheet names and whether the sheet has formulas."""
    import zipfile
    from ..assistant.attachments import read_xlsx, xlsx_workbook
    t = read_xlsx(p, sheet=sheet, max_rows=MAX_TABLE_ROWS)
    formulas = 0
    z, sheets, _active, _shared = xlsx_workbook(p)
    try:
        target = dict(sheets).get(t.sheet or "")
        if target:
            with z.open(target) as fh:
                formulas = len(re.findall(rb"<(?:\w+:)?f[ >/]", fh.read()))
    except (KeyError, zipfile.BadZipFile):
        pass
    finally:
        z.close()
    return {"columns": t.columns, "rows": t.rows, "sheet": t.sheet, "sheets": [s["name"] for s in t.sheets or []],
            "formulas": formulas}


def read_table(app: Any, exp_rel: str, file: str, sheet: str | None = None) -> dict[str, Any]:
    p = _table_path(app, exp_rel, file)
    if not p.is_file():
        raise FileNotFoundError(f"{file} isn't in the experiment's folder")
    fp = storage.fingerprint(p)
    out: dict[str, Any] = {"file": file, "fingerprint": fp, "format": p.suffix.lower().lstrip("."),
                           "writable": True, "warnings": []}
    if p.suffix.lower() == ".xlsx":
        info = _xlsx_info(p, sheet)
        out.update(columns=info["columns"], rows=[[r.get(c) for c in info["columns"]] for r in info["rows"]],
                   sheet=info["sheet"], sheets=info["sheets"], formulas=info["formulas"])
        out["writable"] = has_openpyxl()
        if not out["writable"]:
            out["warnings"].append("Saving an Excel file needs openpyxl (pip install edge-experiments[excel]). "
                                   "You can save your changes as a CSV file instead.")
        others = [s for s in info["sheets"] if s != info["sheet"]]
        if others:
            out["warnings"].append(f"This workbook has other sheets ({', '.join(others)}). EDGE uses and edits only "
                                   f"“{info['sheet']}”; the other sheets are kept.")
        if info["formulas"]:
            out["warnings"].append(f"“{info['sheet']}” has {info['formulas']} formula"
                                   f"{'s' if info['formulas'] != 1 else ''}. Saving here writes their current "
                                   "values instead (a backup is kept in History).")
        return out
    text = p.read_bytes().decode("utf-8-sig", errors="replace")
    delim = "\t" if p.suffix.lower() == ".tsv" else _sniff(text)
    grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim)]
    while grid and not any(c.strip() for c in grid[0]):
        grid.pop(0)
    header = [h.strip() for h in grid[0]] if grid else []
    body = [r for r in grid[1:] if any(c.strip() for c in r)]
    width = max([len(header)] + [len(r) for r in body]) if grid else 0
    header += [""] * (width - len(header))
    out.update(columns=header, rows=[(r + [""] * (width - len(r)))[:width] for r in body[:MAX_TABLE_ROWS]],
               delimiter=delim, sheet=None, sheets=[])
    return out


def _cell_for_xlsx(v: Any) -> Any:
    """Typed cells: '12' is a number in Excel, 'true' a boolean, '' empty; other text stays text."""
    if v is None or isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    if s.strip() == "":
        return None
    if s.startswith("="):              # never write a formula typed in the builder: it is text here
        return "'" + s if not s.startswith("'") else s
    low = s.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if re.fullmatch(r"-?\d{1,15}", s.strip()) and not (s.strip().startswith("0") and len(s.strip()) > 1):
        return int(s)
    try:
        if re.fullmatch(r"-?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s.strip()):
            return float(s)
    except ValueError:
        pass
    return s


def _cell_for_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def save_table(app: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .server import BadRequest
    file = _need(body, "file", str)
    p = _table_path(app, body.get("exp") or "", file)
    columns = _need(body, "columns", list)
    rows = _need(body, "rows", list)
    if len(columns) > MAX_TABLE_COLS or len(rows) > MAX_TABLE_ROWS:
        raise BadRequest("the table is too large to save here")
    if not all(isinstance(c, str) for c in columns):
        raise BadRequest("column names must be text")
    clean = [c.strip() for c in columns]
    if any(not c for c in clean):
        raise BadRequest("every column needs a name")
    dupes = sorted({c for c in clean if clean.count(c) > 1})
    if dupes:
        raise BadRequest(f"two columns are called “{dupes[0]}”: give each column its own name")
    if not all(isinstance(r, list) and all(c is None or isinstance(c, (str, int, float, bool)) for c in r) for r in rows):
        raise BadRequest("'rows' must be a list of rows, each a list of cell values")
    rows = [(list(r) + [None] * len(clean))[:len(clean)] for r in rows]
    as_csv = bool(body.get("as_csv"))
    expected = body.get("fingerprint")
    current = storage.fingerprint(p)
    if not body.get("force") and isinstance(expected, str) and current and expected != current:
        raise Conflict(f"{p.name} was changed in another program since it was opened here.", conflict=True,
                       fingerprint=current)
    backup = None
    if as_csv:          # a copy as CSV next to the workbook: the workbook itself stays as it is
        target = p.with_suffix(".csv")
        n = 2
        while target.exists() and target != p:
            target = p.with_name(f"{p.stem}_{n}.csv")
            n += 1
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(clean)
        w.writerows([[_cell_for_text(c) for c in r] for r in rows])
        storage.atomic_write(target, buf.getvalue())
        rel = str(target.relative_to((app.safe_path(body["exp"]).parent if body.get("exp") else app.root).resolve()))
        return {"ok": True, "saved": rel.replace("\\", "/"), "fingerprint": storage.fingerprint(target), "backup": None,
                "new_file": True}
    if p.suffix.lower() == ".xlsx":
        if not has_openpyxl():
            raise Conflict("Saving an Excel file needs openpyxl (pip install edge-experiments[excel]). Save as "
                           "CSV instead?", needs_csv=True)
        info = _xlsx_info(p, body.get("sheet") or None) if p.exists() else {"sheets": [], "formulas": 0, "sheet": None}
        others = [s for s in info["sheets"] if s != info["sheet"]]
        if (info["formulas"] or others) and not body.get("confirm_values"):
            raise Conflict("Saving writes this sheet as plain values.", needs_confirm=True,
                           formulas=info["formulas"], other_sheets=others)
        if p.exists() and body.get("backup", True) is not False:
            backup = storage._make_backup(p, "before edit in builder").name
        data = _write_xlsx(p, info["sheet"], clean, rows)
        storage.atomic_write(p, data)
    else:
        text = p.read_bytes().decode("utf-8-sig") if p.exists() else ""
        delim = "\t" if p.suffix.lower() == ".tsv" else (_sniff(text) if text else ",")
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delim, lineterminator=_newline(text) if text else "\n")
        w.writerow(clean)
        w.writerows([[_cell_for_text(c) for c in r] for r in rows])
        new = buf.getvalue()
        if p.exists() and new == text:
            return {"ok": True, "saved": file, "fingerprint": current, "backup": None, "unchanged": True}
        if p.exists() and body.get("backup", True) is not False:
            backup = storage._make_backup(p, "before edit in builder").name
        raw = p.read_bytes() if p.exists() else b""
        storage.atomic_write(p, ("﻿" if raw.startswith(b"\xef\xbb\xbf") else "") + new)
    return {"ok": True, "saved": file, "fingerprint": storage.fingerprint(p), "backup": backup}


def _write_xlsx(p: Path, sheet: str | None, columns: list[str], rows: list[list[Any]]) -> bytes:
    """The workbook with one sheet's cells replaced (values only); other sheets, column widths and cell styles
    stay as openpyxl keeps them."""
    import openpyxl
    if p.exists():
        wb = openpyxl.load_workbook(p)
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
    old_rows, old_cols = ws.max_row, ws.max_column
    for r in range(1, max(old_rows, len(rows) + 1) + 1):
        for c in range(1, max(old_cols, len(columns)) + 1):
            if r > len(rows) + 1 or c > len(columns):
                if ws.cell(row=r, column=c).value is not None:
                    ws.cell(row=r, column=c).value = None
    for c, name in enumerate(columns, start=1):
        ws.cell(row=1, column=c).value = name
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c).value = _cell_for_xlsx(v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

