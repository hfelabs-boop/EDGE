"""Builder endpoints of the task library (edge/library), behind the builder's request guard like every route.

* ``GET  /api/library``      -> ``{tasks: [{id, title, category, summary, description, measures, duration_min, input,
  languages, variant_of, psytoolkit, references, see_also, notes, citation}], categories: [{name, count}],
  problems: [...]}``. ``?category=&search=&input=&language=`` narrow the list (as ``edge library list``).
* ``POST /api/library/new``  ``{id, name?}`` -> ``{path, title, citation}``: copies the task (experiment, stimuli,
  trial-list files, CITATION.md) into a new folder of the builder's folder, ``<name>/<name>.yaml``; an existing
  folder is never touched (the copy is then ``<name>_2``). An unknown task or a bad name is a 400 that says why.
"""

from __future__ import annotations

from typing import Any


def handle(app: Any, method: str, path: str, query: dict[str, str], body: Any) -> tuple[dict[str, Any], int]:
    from .. import library
    from .server import BadRequest
    try:
        if method == "GET" and path == "/api/library":
            tasks = library.list_tasks(query.get("category") or None, query.get("search") or None,
                                       query.get("input") or None, query.get("language") or None)
            _, problems = library.discover()
            return {"tasks": [t.to_dict() for t in tasks], "categories": library.categories(),
                    "problems": problems}, 200
        if method == "POST" and path == "/api/library/new":
            if not isinstance(body, dict):
                raise BadRequest("the request body must be a JSON object")
            tid, name = body.get("id"), body.get("name")
            if not isinstance(tid, str) or not tid.strip():
                raise BadRequest("the request needs 'id' (a task of the library)")
            if name is not None and (not isinstance(name, str) or "/" in name or "\\" in name or name.strip() in ("", ".", "..")):
                raise BadRequest("'name' must be the name of a new folder (no / or \\)")
            task = library.get_task(tid)
            exp = library.copy_task(task.id, app.root, name or None)
            return {"ok": True, "path": exp.resolve().relative_to(app.root.resolve()).as_posix(), "title": task.title,
                    "citation": task.citation()}, 200
    except library.LibraryError as e:
        raise BadRequest(str(e)) from None
    return {"error": "not found"}, 404
