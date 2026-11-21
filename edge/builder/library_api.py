"""Builder endpoints of the task library (edge/library), behind the builder's request guard like every route.

* ``GET  /api/library``      -> ``{tasks: [{id, title, category, summary, description, measures, duration_min, input,
  languages, variant_of, psytoolkit, references, see_also, notes, citation}], categories: [{name, count}],
  problems: [...], themes: [{id, title, about}]}`` (tasks also carry domain, themes, adaptation and, for a base task,
  adaptations: [{id, title, themes}]). ``?category=&search=&input=&language=&domain=&theme=`` narrow the list (as
  ``edge library list``).
* ``POST /api/library/new``  ``{id, name?, theme?}`` -> ``{path, title, citation, theme?}``: copies the task
  (experiment, stimuli, trial-list files, CITATION.md) into a new folder of the builder's folder,
  ``<name>/<name>.yaml``; an existing folder is never touched (the copy is then ``<name>_2``). ``theme`` (an
  operational adaptation's display theme) sets the copy's variable ``theme``. An unknown task or theme or a bad name
  is a 400 that says why.
"""

from __future__ import annotations

from typing import Any


def handle(app: Any, method: str, path: str, query: dict[str, str], body: Any) -> tuple[dict[str, Any], int]:
    from .. import library
    from .server import BadRequest
    try:
        if method == "GET" and path == "/api/library":
            tasks = library.list_tasks(query.get("category") or None, query.get("search") or None,
                                       query.get("input") or None, query.get("language") or None,
                                       domain=query.get("domain") or None, theme=query.get("theme") or None)
            _, problems = library.discover()
            themes = [{"id": th, "title": library.THEME_TITLES[th], "about": library.THEME_ABOUT[th]}
                      for th in library.THEMES]
            return {"tasks": [t.to_dict() for t in tasks], "categories": library.categories(),
                    "problems": problems, "themes": themes}, 200
        if method == "POST" and path == "/api/library/new":
            if not isinstance(body, dict):
                raise BadRequest("the request body must be a JSON object")
            tid, name, theme = body.get("id"), body.get("name"), body.get("theme")
            if not isinstance(tid, str) or not tid.strip():
                raise BadRequest("the request needs 'id' (a task of the library)")
            if name is not None and (not isinstance(name, str) or "/" in name or "\\" in name or name.strip() in ("", ".", "..")):
                raise BadRequest("'name' must be the name of a new folder (no / or \\)")
            if theme is not None and (not isinstance(theme, str) or not theme.strip()):
                raise BadRequest("'theme' must be the name of a display theme (c2, uav, ew, video)")
            task = library.get_task(tid)
            exp = library.copy_task(task.id, app.root, name or None, theme=theme or None)
            out = {"ok": True, "path": exp.resolve().relative_to(app.root.resolve()).as_posix(), "title": task.title,
                   "citation": task.citation()}
            if task.themes:
                out["theme"] = library.theme_name(theme) if theme else task.themes[0]
            return out, 200
    except library.LibraryError as e:
        raise BadRequest(str(e)) from None
    return {"error": "not found"}, 404
