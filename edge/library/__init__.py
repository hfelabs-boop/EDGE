"""The EDGE task library: ready-made, tested versions of classic paradigms (Stroop, flanker, go/no-go, n-back …).

Each task is a folder ``edge/library/tasks/<id>/`` with

* ``<id>.yaml``  the EDGE experiment (instructions, practice, main block(s), thanks; measures declared),
* ``meta.yaml``  what the task is, what it measures, how long it takes, its input and its literature (schema below),
* ``stimuli/``   pictures and sounds the task uses (made for EDGE; never copied from elsewhere),
* any trial-list files the experiment names next to it.

``meta.yaml``::

    id: stroop                          # the folder's name
    title: Stroop task
    category: Inhibition and conflict   # one of CATEGORIES
    summary: one sentence
    description: one paragraph
    measures: [RT congruent vs incongruent (Stroop effect), accuracy]
    duration_min: 5
    input: keyboard                     # one of INPUTS
    languages: [en]
    variant_of: stroop                  # optional (phone/touch/language versions)
    references: ["Stroop, J. R. (1935). …"]
    see_also: {psytoolkit: "https://www.psytoolkit.org/experiment-library/stroop.html"}
    notes: optional limits

``copy_task(id, folder)`` makes a researcher's own copy (a new experiment folder, never over anything). The CLI is
``edge library list|show|new``, the builder shows the library on Home and in the new-experiment flow
(``/api/library``), and the MCP server has ``list_library`` / ``create_from_library``.

``EDGE_LIBRARY_DIR`` (an environment variable) points the library at another folder of task folders: for
contributors trying a new task before adding it, and for EDGE's own tests.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

CATEGORIES = ("Attention", "Inhibition and conflict", "Cognitive control", "Working memory", "Vigilance",
              "Decision making", "Language", "Social and implicit", "Perception and motor", "Problem solving")
INPUTS = ("keyboard", "mouse", "touch", "keyboard+mouse")
REQUIRED = ("id", "title", "category", "summary", "description", "measures", "duration_min", "input", "languages",
            "references", "see_also")
OPTIONAL = ("variant_of", "notes")
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
# what a copy leaves behind: the library's own description, recorded sessions, caches and hidden files
_SKIP = {"meta.yaml", "data", "__pycache__", ".edge"}


class LibraryError(ValueError):
    """A task that does not exist, a meta.yaml that does not follow the schema, or a copy that cannot be made;
    the message says what to change."""


@dataclass
class Task:
    id: str
    title: str
    category: str
    summary: str
    description: str
    measures: list[str]
    duration_min: float
    input: str
    languages: list[str]
    references: list[str]
    see_also: dict[str, str]
    folder: Path
    variant_of: str | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def experiment_path(self) -> Path:
        return self.folder / f"{self.id}.yaml"

    @property
    def psytoolkit(self) -> str | None:
        return (self.see_also or {}).get("psytoolkit")

    def citation(self) -> str:
        return citation_text(self)

    def matches(self, words: str) -> bool:
        hay = " ".join([self.id, self.id.replace("_", " "), self.title, self.category, self.summary,
                        self.description, self.input, " ".join(self.measures), " ".join(self.references),
                        self.notes or ""]).lower()
        return all(w in hay for w in words.lower().split())

    def to_dict(self, full: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "title": self.title, "category": self.category, "summary": self.summary,
                             "measures": list(self.measures), "duration_min": self.duration_min, "input": self.input,
                             "languages": list(self.languages), "variant_of": self.variant_of,
                             "psytoolkit": self.psytoolkit}
        if full:
            d.update(description=self.description, references=list(self.references), see_also=dict(self.see_also),
                     notes=self.notes, citation=self.citation())
        return d


# ------------------------------------------------------------------ where the tasks are
def tasks_dir() -> Path:
    env = os.environ.get("EDGE_LIBRARY_DIR")
    return Path(env).expanduser() if env else TASKS_DIR


def _root(root: str | Path | None) -> Path:
    return Path(root) if root is not None else tasks_dir()


# ------------------------------------------------------------------ meta.yaml schema
def _suggest(word: str, choices: Any) -> str:
    close = difflib.get_close_matches(str(word), list(choices), 1, 0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x.strip() for x in v)


def validate_meta(meta: Any, folder: str | Path | None = None) -> list[str]:
    """Every way ``meta`` breaks the schema, in words ([] when it is fine). ``folder``: the task folder, to check
    that the id is its name and that the experiment file is there."""
    if not isinstance(meta, dict):
        return ["meta.yaml must be a set of 'key: value' lines (id, title, category …), not "
                f"{type(meta).__name__ if meta is not None else 'empty'}"]
    errors: list[str] = []
    unknown = [k for k in meta if k not in REQUIRED + OPTIONAL]
    for k in REQUIRED:
        if k not in meta or meta[k] is None or meta[k] == "":
            typo = difflib.get_close_matches(k, [str(u) for u in unknown], 1, 0.75)
            errors.append(f"'{k}' is missing" + (f" ('{typo[0]}' is spelled differently)" if typo else ""))
    tid = meta.get("id")
    if tid is not None:
        if not isinstance(tid, str) or not _ID.match(tid):
            errors.append(f"id '{tid}' must be lower-case letters, digits and _ (e.g. go_no_go), starting with a letter")
        elif folder is not None and Path(folder).name != tid:
            errors.append(f"id '{tid}' must be the name of its folder ('{Path(folder).name}')")
    for k in ("title", "summary", "description"):
        if k in meta and meta[k] not in (None, "") and not (isinstance(meta[k], str) and meta[k].strip()):
            errors.append(f"'{k}' must be text")
    cat = meta.get("category")
    if cat not in (None, "") and cat not in CATEGORIES:
        errors.append(f"category '{cat}' is not one of: {', '.join(CATEGORIES)}{_suggest(cat, CATEGORIES)}")
    inp = meta.get("input")
    if inp not in (None, "") and inp not in INPUTS:
        errors.append(f"input '{inp}' is not one of: {', '.join(INPUTS)}{_suggest(inp, INPUTS)}")
    for k in ("measures", "references"):
        if meta.get(k) not in (None, "") and not _str_list(meta[k]):
            errors.append(f"'{k}' must be a list of texts, e.g. {k}: [\"…\", \"…\"]")
    langs = meta.get("languages")
    if langs not in (None, ""):
        if not _str_list(langs):
            errors.append("'languages' must be a list of language codes, e.g. languages: [en]")
        else:
            bad = [x for x in langs if not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z]{2,4})?", x)]
            if bad:
                errors.append(f"'languages': {', '.join(bad)} is not a language code like en, de or pt-BR")
    dur = meta.get("duration_min")
    if dur not in (None, "") and (isinstance(dur, bool) or not isinstance(dur, (int, float)) or not 0 < dur <= 240):
        errors.append(f"duration_min must be the number of minutes the task takes (e.g. 5), not '{dur}'")
    see = meta.get("see_also")
    if see not in (None, ""):
        if not isinstance(see, dict):
            errors.append("see_also must be links by name, e.g. see_also: {psytoolkit: \"https://www.psytoolkit.org/…\"}")
        else:
            for name, url in see.items():
                if not isinstance(url, str) or not re.match(r"https?://\S+$", url):
                    errors.append(f"see_also.{name} must be a web address (https://…)")
    for k in OPTIONAL:
        if meta.get(k) is not None and not isinstance(meta[k], str):
            errors.append(f"'{k}' must be text")
    if isinstance(meta.get("variant_of"), str) and not _ID.match(meta["variant_of"]):
        errors.append(f"variant_of '{meta['variant_of']}' must be a task id (e.g. stroop)")
    if folder is not None and isinstance(tid, str) and _ID.match(tid) and not (Path(folder) / f"{tid}.yaml").is_file():
        errors.append(f"the experiment file {tid}.yaml is missing next to meta.yaml")
    return errors


def load_task(folder: str | Path) -> Task:
    """The task in ``folder``; LibraryError (naming the folder and every problem) when its meta.yaml is wrong."""
    folder = Path(folder)
    meta_file = folder / "meta.yaml"
    try:
        meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LibraryError(f"{folder.name}: there is no meta.yaml in {folder}") from None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        where = getattr(e, "problem_mark", None)
        at = f" (line {where.line + 1})" if where is not None else ""
        raise LibraryError(f"{folder.name}: meta.yaml could not be read{at}: {getattr(e, 'problem', None) or e}") from None
    errors = validate_meta(meta, folder)
    if errors:
        raise LibraryError(f"{folder.name}/meta.yaml: " + "; ".join(errors))
    known = {k: meta.get(k) for k in REQUIRED + OPTIONAL}
    return Task(id=known["id"], title=known["title"].strip(), category=known["category"],
                summary=" ".join(known["summary"].split()), description=" ".join(known["description"].split()),
                measures=list(known["measures"]), duration_min=known["duration_min"], input=known["input"],
                languages=list(known["languages"]), references=list(known["references"]),
                see_also=dict(known["see_also"]), folder=folder, variant_of=known.get("variant_of"),
                notes=known.get("notes"), extra={k: v for k, v in meta.items() if k not in known})


_CACHE: dict[Any, tuple[list[Task], list[str]]] = {}


def discover(root: str | Path | None = None) -> tuple[list[Task], list[str]]:
    """(the tasks, sorted by title; the problems: folders whose meta.yaml is wrong, which are left out, and
    variants of tasks that are not in the library)."""
    base = _root(root)
    metas = sorted(base.glob("*/meta.yaml")) if base.is_dir() else []
    key = (str(base.resolve()) if base.exists() else str(base),
           tuple((str(m), m.stat().st_mtime_ns) for m in sorted(base.glob("*/*.yaml")))) if base.is_dir() else (str(base),)
    if key in _CACHE:
        return _CACHE[key]
    tasks, problems = [], []
    for m in metas:
        try:
            tasks.append(load_task(m.parent))
        except LibraryError as e:
            problems.append(str(e))
    ids = {t.id for t in tasks}
    for t in tasks:
        if t.variant_of and t.variant_of not in ids:
            problems.append(f"{t.id}/meta.yaml: variant_of '{t.variant_of}' is not a task in the library")
    tasks.sort(key=lambda t: (t.title.lower(), t.id))
    if len(_CACHE) > 16:
        _CACHE.clear()
    _CACHE[key] = (tasks, problems)
    return tasks, problems


def list_tasks(category: str | None = None, search: str | None = None, input: str | None = None,
               language: str | None = None, root: str | Path | None = None) -> list[Task]:
    """The library's tasks, optionally only one category (its name or the start of it, any case), those that
    contain every word of ``search``, one input type (``keyboard`` also matches ``keyboard+mouse``) or one
    language."""
    tasks, _ = discover(root)
    if category:
        cat = category_name(category)
        tasks = [t for t in tasks if t.category == cat]
    if input:
        want = input.strip().lower()
        if want not in INPUTS:
            raise LibraryError(f"input '{input}' is not one of: {', '.join(INPUTS)}{_suggest(want, INPUTS)}")
        tasks = [t for t in tasks if t.input == want or want in t.input.split("+")]
    if language:
        tasks = [t for t in tasks if language.strip().lower() in [x.lower() for x in t.languages]]
    if search and search.strip():
        tasks = [t for t in tasks if t.matches(search)]
    return tasks


def category_name(category: str) -> str:
    """'attention', 'working', 'Inhibition and conflict' -> the category's name; unknown names list the choices."""
    c = " ".join(str(category).split()).lower()
    exact = [x for x in CATEGORIES if x.lower() == c]
    starts = [x for x in CATEGORIES if x.lower().startswith(c)] if c else []
    if exact or len(starts) == 1:
        return (exact or starts)[0]
    raise LibraryError(f"unknown category '{category}': choose one of {', '.join(CATEGORIES)}"
                       + _suggest(category, CATEGORIES))


def categories(root: str | Path | None = None) -> list[dict[str, Any]]:
    """[{name, count}] for every category, in the fixed order (empty categories included)."""
    tasks, _ = discover(root)
    return [{"name": c, "count": sum(t.category == c for t in tasks)} for c in CATEGORIES]


def get_task(task_id: str, root: str | Path | None = None) -> Task:
    tasks, problems = discover(root)
    tid = str(task_id).strip().replace("-", "_").lower()
    for t in tasks:
        if t.id == tid:
            return t
    broken = [p for p in problems if p.startswith(f"{tid}/") or p.startswith(f"{tid}:")]
    if broken:
        raise LibraryError(f"the library task '{tid}' can't be used: {broken[0]}")
    ids = [t.id for t in tasks]
    raise LibraryError(f"there is no task '{task_id}' in the library" + _suggest(tid, ids)
                       + ("" if ids else " (the library is empty)") + ". See them all with: edge library list")


# ------------------------------------------------------------------ citing a task
def citation_text(task: Task | str, root: str | Path | None = None) -> str:
    """What to write in a methods section, and where the paradigm comes from."""
    t = task if isinstance(task, Task) else get_task(task, root)
    lines = [f"{t.title} (EDGE task library: {t.id})", "",
             "This is EDGE's own implementation of the paradigm, written from the published method. "
             "When you use it, please cite the original work:", ""]
    lines += [f"- {r}" for r in t.references]
    if t.see_also:
        lines += ["", "See also:"] + [f"- {('PsyToolkit' if k == 'psytoolkit' else k)}: {u}" for k, u in t.see_also.items()]
    lines += ["", "Say in your methods which version you ran (trial numbers, timing, keys) and any changes you made."]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ a researcher's own copy
def _slug(name: str) -> str:
    s = re.sub(r"[^\w-]+", "_", str(name).strip()).strip("_")
    if not s:
        raise LibraryError("give the new experiment a name made of letters, digits, - or _")
    return s


def copy_task(task_id: str, dest_dir: str | Path, name: str | None = None, root: str | Path | None = None) -> Path:
    """Copy library task ``task_id`` into a new experiment folder ``dest_dir/<name>/`` (``name``: the task's id when
    left out) with its stimuli and trial-list files, and a CITATION.md. Nothing is ever overwritten: when that
    folder exists, the copy goes to ``<name>_2`` (``_3`` …), as for templates. Returns the experiment file."""
    t = get_task(task_id, root)
    dest_dir = Path(dest_dir)
    if dest_dir.exists() and not dest_dir.is_dir():
        raise LibraryError(f"'{dest_dir}' is a file, not a folder: choose a folder for the new experiment")
    base = _slug(name or t.id)
    slug, n = base, 2
    while (dest_dir / slug).exists():
        slug = f"{base}_{n}"
        n += 1
    target = dest_dir / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = t.folder.resolve()

    def ignore(folder: str, names: list[str]) -> set[str]:
        here = Path(folder).resolve()
        skip = {x for x in names if x.startswith(".") or x == "__pycache__"}
        if here == src:
            skip |= _SKIP & set(names)
        # links could reach outside the library; files that run code are not part of a task
        skip |= {x for x in names if (Path(folder) / x).is_symlink()}
        skip |= {x for x in names if x.endswith((".pyc", ".pyo"))}
        return skip

    shutil.copytree(src, target, ignore=ignore)
    exp_src = target / f"{t.id}.yaml"
    exp = target / f"{slug}.yaml"
    text = exp_src.read_text(encoding="utf-8")
    if re.search(r"^name:", text, re.M):
        text = re.sub(r"^name:.*$", f"name: {slug}", text, count=1, flags=re.M)
    else:
        text = f"name: {slug}\n{text}"
    header = f"# From the EDGE task library: {t.title} ({t.id}). How to cite it: CITATION.md\n"
    exp_src.unlink()
    exp.write_text(header + text, encoding="utf-8")
    (target / "CITATION.md").write_text(f"# {t.title}\n\n" + citation_text(t).split("\n", 2)[2], encoding="utf-8")
    return exp


__all__ = ["CATEGORIES", "INPUTS", "REQUIRED", "LibraryError", "Task", "tasks_dir", "validate_meta", "load_task",
           "discover", "list_tasks", "categories", "category_name", "get_task", "citation_text", "copy_task"]
