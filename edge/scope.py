"""Static "is this name defined here?" check for expressions.

Walks the flow the way the runner does, carrying the names each routine can see at that point:
trial-list columns of the enclosing loops, loop / workflow ids, component ids, participant fields,
variables set anywhere (variable components, rules, workflow routes, code components) and the
built-ins. An expression that reads a name nobody defines is reported in plain language before
the experiment ever runs ("The trial list has no column called 'ink'").
"""

from __future__ import annotations

import ast
import difflib
from pathlib import Path
from typing import Any, Iterable

from . import expressions

ALWAYS = {"t", "frame", "vars", "experiment", "routine_index"}


def _expr_sources(value: Any, *, bare: bool = False) -> Iterable[str]:
    """Expression sources (without '$') inside a property value."""
    if isinstance(value, str):
        if value.startswith("$$"):
            return
        if value.startswith("$"):
            yield value[1:]
        elif bare and value.strip():
            yield value
    elif isinstance(value, list):
        for v in value:
            yield from _expr_sources(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _expr_sources(v)


def _code_assigned(src: str) -> set[str]:
    try:
        tree = ast.parse(src or "")
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.add(node.id)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) \
                and isinstance(node.value, ast.Name) and node.value.id == "vars" \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            out.add(node.slice.value)
    return out


def loop_columns(loop, base_dir: Path) -> set[str] | None:
    """Column names a loop provides; None when they can't be known statically."""
    from .conditions import load_conditions

    if loop.staircase:
        return {str(loop.staircase.get("variable", "level")), "staircase_trial"}
    cond = loop.conditions
    if cond is None:
        return set()
    if isinstance(cond, str) and cond.startswith("$"):
        return None
    try:
        rows = load_conditions(cond, base_dir)
    except Exception:
        return None
    cols: set[str] = set()
    for r in rows:
        cols.update(k for k in r if not str(k).startswith("_"))
    return cols


def global_names(exp) -> tuple[set[str], bool]:
    """Names visible everywhere, and whether code components make the check uncertain."""
    from .model import Loop, StateMachine, Branch

    names = set(ALWAYS) | set(exp.settings.get("participant", {}) or {}) | {"participant", "session"}
    has_code = False
    for routine in exp.routines.values():
        for c in routine.components:
            names.add(c.id)
            if c.type == "variable":
                names.update(str(k) for k in (c.props.get("set") or {}))
            if c.type == "code":
                has_code = True
                for k in ("on_begin", "on_frame", "on_end"):
                    names |= _code_assigned(c.props.get(k, ""))
        for rule in routine.rules:
            for a in (rule.get("do") or []) if isinstance(rule, dict) else []:
                if isinstance(a, dict) and isinstance(a.get("set"), dict):
                    names.update(str(k) for k in a["set"])

    def walk(nodes):
        for n in nodes:
            if isinstance(n, Loop):
                names.add(n.id)
                if n.staircase:
                    names.add(f"{n.id}_threshold")
                walk(n.children)
            elif isinstance(n, Branch):
                walk(n.then)
                walk(n.else_)
            elif isinstance(n, StateMachine):
                names.add(n.id)
                for st in n.states.values():
                    for t in st.next:
                        names.update(str(k) for k in t.set)
                    walk(st.run)
    walk(exp.flow)
    return names, has_code


def scope_issues(exp) -> list:
    """Plain-language issues for names an expression reads but nothing defines at that point."""
    from .model import Branch, Issue, Loop, RoutineRef, StateMachine

    glob, has_code = global_names(exp)
    issues: list[Issue] = []
    all_columns: dict[str, str] = {}     # column -> loop id providing it
    loops: list[Loop] = []

    def collect(nodes):
        for n in nodes:
            if isinstance(n, Loop):
                loops.append(n)
                collect(n.children)
            elif isinstance(n, Branch):
                collect(n.then)
                collect(n.else_)
            elif isinstance(n, StateMachine):
                for st in n.states.values():
                    collect(st.run)
    collect(exp.flow)
    columns_of: dict[str, set[str] | None] = {}
    for lp in loops:
        cols = loop_columns(lp, exp.base_dir)
        columns_of[lp.id] = cols
        for c in cols or ():
            all_columns.setdefault(c, lp.id)

    seen: set[tuple[str, str]] = set()

    def report(src: str, where: str, scope: set[str], unknown_scope: bool, enclosing: list[str]) -> None:
        for name in sorted(expressions.names_in(src)):
            if name in scope or name in glob:
                continue
            key = (where, name)
            if key in seen:
                continue
            seen.add(key)
            if name in all_columns:
                if unknown_scope:
                    continue
                lp = all_columns[name]
                issues.append(Issue("warning", where,
                                    f"'{name}' comes from the trial list of loop '{lp}', but this screen also "
                                    f"runs outside that loop, where '{name}' doesn't exist",
                                    hint=f"move it inside '{lp}', or give it a value with a variable component"))
                continue
            if unknown_scope or has_code:
                level = "warning"
            else:
                level = "error"
            cols = sorted(set().union(*[columns_of.get(e) or set() for e in enclosing])) if enclosing else []
            if enclosing and cols:
                msg = f"the trial list has no column called '{name}'"
                hint = f"columns here: {', '.join(cols)}"
            else:
                msg = f"'{name}' isn't defined anywhere in this experiment"
                hint = ("add a trial list (loop) with that column, or set it with a variable component; "
                        "to show the text literally, remove the leading '$'")
            close = difflib.get_close_matches(name, sorted(scope | glob - ALWAYS), n=2, cutoff=0.6)
            if close:
                msg += f". Did you mean {' or '.join(repr(c) for c in close)}?"
            issues.append(Issue(level, where, msg, hint=hint))

    def check_routine(rid: str, scope: set[str], unknown: bool, enclosing: list[str]) -> None:
        routine = exp.routines.get(rid)
        if routine is None:
            return
        for c in routine.components:
            where = f"routines.{rid}.{c.id}"
            if c.id in scope and (where, "@" + c.id) not in seen:
                seen.add((where, "@" + c.id))
                issues.append(Issue("info", where,
                                    f"this component has the same name as the trial-list column '{c.id}': "
                                    f"${c.id} gives the column's value, so this component's results (like "
                                    f"{c.id}.onset) can't be used by name",
                                    hint=f"rename the component (e.g. '{c.id}_stim') if you need its results"))
            for key in ("start", "duration", "start_if", "stop_if", "only_if"):
                v = getattr(c, key, None)
                for src in _expr_sources(v, bare=True):
                    report(src, f"{where}.{'if' if key == 'only_if' else key}", scope, unknown, enclosing)
            if c.type == "code":
                continue
            for k, v in c.props.items():
                if c.type == "survey" and k in ("questions", "scores", "labels", "css"):
                    continue
                for src in _expr_sources(v):
                    report(src, f"{where}.{k}", scope, unknown, enclosing)
        if isinstance(routine.end_if, str):
            for src in _expr_sources(routine.end_if, bare=True):
                report(src, f"routines.{rid}.end_if", scope, unknown, enclosing)
        for i, rule in enumerate(routine.rules):
            if not isinstance(rule, dict):
                continue
            for src in _expr_sources(str(rule.get("when", "")), bare=True):
                report(src, f"routines.{rid}.rules[{i}].when", scope, unknown, enclosing)
            for a in rule.get("do") or []:
                if isinstance(a, dict):
                    for k in ("set", "marker", "log"):
                        if k in a:
                            for src in _expr_sources(a[k]):
                                report(src, f"routines.{rid}.rules[{i}]", scope, unknown, enclosing)

    def walk(nodes, scope: set[str], unknown: bool, enclosing: list[str], where: str) -> None:
        for i, n in enumerate(nodes):
            w = f"{where}[{i}]"
            if isinstance(n, RoutineRef):
                if n.if_:
                    for src in _expr_sources(n.if_, bare=True):
                        report(src, w + ".if", scope, unknown, enclosing)
                check_routine(n.routine, scope, unknown, enclosing)
            elif isinstance(n, Loop):
                for src in _expr_sources(n.conditions if isinstance(n.conditions, str) else None):
                    report(src, w + ".conditions", scope, unknown, enclosing)
                for src in _expr_sources(n.repeats if isinstance(n.repeats, str) else None, bare=True):
                    report(src, w + ".repeats", scope, unknown, enclosing)
                cols = columns_of.get(n.id)
                inner = scope | (cols or set())
                walk(n.children, inner, unknown or cols is None, enclosing + [n.id], f"{w}.{n.id}")
                if n.stop_if:
                    for src in _expr_sources(n.stop_if, bare=True):
                        report(src, w + ".stop_if", inner, unknown or cols is None, enclosing + [n.id])
            elif isinstance(n, Branch):
                for src in _expr_sources(n.condition, bare=True):
                    report(src, w + ".if", scope, unknown, enclosing)
                walk(n.then, scope, unknown, enclosing, w + ".then")
                walk(n.else_, scope, unknown, enclosing, w + ".else")
            elif isinstance(n, StateMachine):
                for sname, st in n.states.items():
                    sw = f"{w}.{n.id}.{sname}"
                    walk(st.run, scope, unknown, enclosing, sw)
                    for j, t in enumerate(st.next):
                        if t.condition:
                            for src in _expr_sources(t.condition, bare=True):
                                report(src, f"{sw}.next[{j}]", scope, unknown, enclosing)

    walk(exp.flow, set(), False, [], "flow")
    return issues
