"""``edge library list|show|new``: browse the task library and start an experiment from one of its tasks."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

from . import CATEGORIES, INPUTS, copy_task, discover, get_task, list_tasks


def add_cli(sub: Any) -> None:
    """The `edge library` command (registered by edge/cli.py)."""
    lb = sub.add_parser("library", help="ready-made classic tasks (Stroop, flanker, n-back …): list, show, start from one")
    acts = lb.add_subparsers(dest="action", metavar="<list|show|new>", help="list the tasks, show one, or start an "
                             "experiment from one (default: list)")
    ls = acts.add_parser("list", help="list the tasks (optionally one category, or those matching some words)")
    ls.add_argument("--category", help="one category: " + "; ".join(CATEGORIES) + " (the start of its name is enough)")
    ls.add_argument("--search", help="words that must all appear (title, description, measures, references)")
    ls.add_argument("--input", choices=INPUTS, help="only tasks answered this way")
    ls.add_argument("--language", help="only tasks in this language (e.g. en, de)")
    ls.add_argument("--json", action="store_true", help="machine-readable output")
    sh = acts.add_parser("show", help="what a task does, measures and cites")
    sh.add_argument("id", help="the task's id (see edge library list)")
    sh.add_argument("--json", action="store_true", help="machine-readable output")
    nw = acts.add_parser("new", help="copy a task into a new experiment folder (never over anything)")
    nw.add_argument("id", help="the task's id (see edge library list)")
    nw.add_argument("directory", nargs="?", default=".", help="where to create the experiment's folder (default: here)")
    nw.add_argument("--name", help="name of the new experiment (default: the task's id)")
    lb.set_defaults(fn=cmd_library, action=None)


def cmd_library(a: Any) -> int:
    if a.action == "show":
        return _show(a)
    if a.action == "new":
        return _new(a)
    if a.action is None:
        a.category = a.search = a.input = a.language = None
        a.json = False
    return _list(a)


def _list(a: Any) -> int:
    tasks = list_tasks(a.category, a.search, a.input, a.language)
    _, problems = discover()
    if a.json:
        print(json.dumps({"tasks": [t.to_dict(full=False) for t in tasks], "problems": problems}, indent=1,
                         ensure_ascii=False))
        return 0
    if not tasks:
        print("No task matches." if any((a.category, a.search, a.input, a.language)) else "The task library is empty.")
    for cat in CATEGORIES:
        group = [t for t in tasks if t.category == cat]
        if not group:
            continue
        print(f"\n{cat}")
        width = max(len(t.id) for t in group)
        for t in group:
            print(f"  {t.id:<{width}}  {t.title}  ({_minutes(t.duration_min)}, {t.input})")
    if tasks:
        print(f"\n{len(tasks)} task(s). More about one:  edge library show <id>    Start from one:  edge library new <id>")
    for p in problems:
        print(f"warning: left out of the library: {p}", file=sys.stderr)
    return 0


def _minutes(m: float) -> str:
    return f"about {m:g} min"


def _show(a: Any) -> int:
    t = get_task(a.id)
    if a.json:
        print(json.dumps(t.to_dict(), indent=1, ensure_ascii=False))
        return 0
    wrap = lambda s, ind="  ": textwrap.fill(s, 100, initial_indent=ind, subsequent_indent=ind)  # noqa: E731
    print(f"{t.title}  ({t.id})")
    print(f"{t.category} · {_minutes(t.duration_min)} · {t.input} · {', '.join(t.languages)}"
          + (f" · a version of {t.variant_of}" if t.variant_of else ""))
    print()
    print(wrap(t.summary, ""))
    print()
    print(wrap(t.description, ""))
    print("\nMeasures")
    for m in t.measures:
        print(wrap(m, "  - "))
    print("\nReferences (please cite them)")
    for r in t.references:
        print(textwrap.fill(r, 100, initial_indent="  - ", subsequent_indent="    "))
    if t.see_also:
        print("\nSee also")
        for k, u in t.see_also.items():
            print(f"  - {'PsyToolkit' if k == 'psytoolkit' else k}: {u}")
    if t.notes:
        print("\nNotes")
        print(wrap(t.notes))
    print(f"\nStart from it:  edge library new {t.id} [folder]")
    return 0


def _new(a: Any) -> int:
    from ..cli import shlex_quote
    t = get_task(a.id)
    path = copy_task(t.id, Path(a.directory), a.name)
    wanted = a.name or t.id
    if path.parent.name != wanted.strip():
        print(f"a folder '{wanted}' already exists there, so it was left as it is")
    print(f"created {path}  ({t.title}, from the task library; how to cite it: {path.parent / 'CITATION.md'})")
    print(f"  try:   edge run {shlex_quote(str(path))} --dry-run\n  edit:  edge builder {shlex_quote(str(path))}")
    return 0
