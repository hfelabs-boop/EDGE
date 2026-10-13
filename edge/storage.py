"""Saving and loading experiment documents safely.

* **Atomic writes**: the file is written to a temporary sibling and renamed into
  place, so a crash or power cut can never leave a half-written experiment.
* **Automatic backups**: every save keeps the previous version under
  ``.edge/backups/<file>/`` (rotated). ``restore_backup`` / ``edge backups``
  bring any version back. The MCP server uses this as its undo history.
* **Conflict detection**: a file's fingerprint (mtime + content hash) is
  returned on load; saving with a stale fingerprint raises
  :class:`ConflictError` instead of silently overwriting someone else's edit
  (the builder, the MCP server and your text editor can all work on one file).
* **Format migrations**: documents carry ``edge_format``; older documents are
  upgraded on load and the applied migrations are reported.
* **Friendly errors**: YAML/JSON syntax errors come back with line and column; a key given twice in
  one mapping is an error too (YAML would otherwise keep only the last one, silently).
* **Comments survive saves**: ``# comments`` in a YAML file are carried over when EDGE rewrites it
  (the layout is EDGE's own: ``{a: 1}`` on one line becomes one key per line).
* **Permissions**: a rewritten file keeps its permissions; a new file follows the umask.
* **Bundles**: ``export_bundle`` packs an experiment and every file it
  references (conditions, images, sounds) into one ``.edgez`` archive.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import yaml

FORMAT_VERSION = 2
BACKUP_DIR = ".edge/backups"
MAX_BACKUPS = 50


class DocumentError(ValueError):
    """The file can't be parsed or isn't an experiment."""


class ConflictError(RuntimeError):
    """The file changed on disk since it was loaded."""

    def __init__(self, path: Path, expected: str, actual: str):
        super().__init__(f"{path} was modified by someone else since it was loaded "
                         f"(expected {expected[:12]}, found {actual[:12]}); reload or save with force")
        self.path, self.expected, self.actual = path, expected, actual


# ---------------------------------------------------------------------- fingerprints
def fingerprint(path: str | Path) -> str:
    """Content hash of the file ('' if it doesn't exist)."""
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------------- serialization
class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        # a routine or trial list used twice is written out twice: no &id001 / *id001 in a researcher's file
        return True


def _str_presenter(dumper, data: str):
    # multi-line strings (instructions, code) as readable block scalars
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_presenter)


class _Loader(yaml.SafeLoader):
    """SafeLoader that refuses a key given twice in one mapping (YAML keeps only the last one, silently)."""

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        if isinstance(node, yaml.MappingNode):
            seen: dict[Any, int] = {}
            for key_node, _ in node.value:
                if key_node.tag == "tag:yaml.org,2002:merge":
                    continue
                key = self.construct_object(key_node, deep=True)
                try:
                    first = seen.setdefault(key, key_node.start_mark.line)
                except TypeError:          # an unhashable key: the normal error explains it
                    continue
                if first != key_node.start_mark.line:
                    raise yaml.constructor.ConstructorError(
                        None, None, f"'{key}' is given twice (lines {first + 1} and {key_node.start_mark.line + 1}); "
                        "only one can count: keep one, or merge them into one entry", key_node.start_mark)
        return super().construct_mapping(node, deep=deep)


def _safe_load(text: str) -> Any:
    """``yaml.safe_load`` that also refuses a key given twice."""
    loader = _Loader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def unshare(data: Any) -> Any:
    """A copy in which no two places share one dict or list (YAML anchors and aliases, or a template that
    reuses a definition), so editing one routine can never change another."""
    if isinstance(data, dict):
        return {k: unshare(v) for k, v in data.items()}
    if isinstance(data, list):
        return [unshare(v) for v in data]
    return data


def dumps(doc: dict[str, Any], fmt: str = "yaml") -> str:
    if fmt == "json":
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=110)


def loads(text: str, fmt: str = "yaml", source: str = "<string>") -> dict[str, Any]:
    try:
        data = json.loads(text) if fmt == "json" else unshare(_safe_load(text))
    except json.JSONDecodeError as e:
        raise DocumentError(f"{source}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}") from None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(e, "problem", None) or str(e)
        raise DocumentError(f"{source}: invalid YAML{where}: {problem}") from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise DocumentError(f"{source}: an experiment must be a mapping (key: value pairs) at the top level")
    return data


def fmt_of(path: Path) -> str:
    return "json" if path.suffix.lower() == ".json" else "yaml"


# ---------------------------------------------------------------------- migrations
def _m1_code_hooks(doc: dict[str, Any]) -> bool:
    """v1 -> v2: code components used begin_routine/each_frame/end_routine."""
    changed = False
    for r in (doc.get("routines") or {}).values():
        for c in (r or {}).get("components", []) or []:
            if c.get("type") == "code":
                for old, new in (("begin_routine", "on_begin"), ("each_frame", "on_frame")):
                    if old in c:
                        c[new] = c.pop(old)
                        changed = True
                if isinstance(c.get("end_routine"), str):  # was code, not the scheduling flag
                    c["on_end"] = c.pop("end_routine")
                    changed = True
    return changed


MIGRATIONS = {1: _m1_code_hooks}  # from version -> function upgrading to version + 1


def migrate(doc: dict[str, Any]) -> list[str]:
    """Upgrade ``doc`` in place to FORMAT_VERSION. Returns descriptions of applied migrations."""
    applied = []
    v = int(doc.get("edge_format", 1) or 1)
    if v > FORMAT_VERSION:
        raise DocumentError(f"this experiment was saved by a newer EDGE (format {v}); please upgrade EDGE")
    while v < FORMAT_VERSION:
        fn = MIGRATIONS.get(v)
        if fn and fn(doc):
            applied.append(f"v{v}->v{v + 1}: {fn.__doc__.strip().splitlines()[0]}")
        v += 1
    doc["edge_format"] = FORMAT_VERSION
    return applied


# ---------------------------------------------------------------------- load / save
@dataclass
class Loaded:
    doc: dict[str, Any]
    path: Path
    fingerprint: str
    migrations: list[str] = field(default_factory=list)


def load_document(path: str | Path) -> Loaded:
    p = Path(path)
    if not p.exists():
        raise DocumentError(f"{p}: file not found")
    if p.is_dir():
        found = sorted(x.name for x in p.iterdir() if x.suffix.lower() in (".yaml", ".yml", ".json"))
        raise DocumentError(f"{p} is a folder; give the experiment file inside it"
                            + (f", e.g. {p / found[0]}" if found else " (this folder has no .yaml or .json file)"))
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentError(f"{p}: not a text file; an experiment is a .yaml or .json file") from None
    doc = loads(text, fmt_of(p), str(p))
    if doc is not None and not isinstance(doc, dict):
        raise DocumentError(f"{p}: doesn't look like an EDGE experiment (it should start with name:, routines: and flow:)")
    if doc and not ({"routines", "flow", "name"} & set(doc)):
        if "steps" in doc and "title" in doc:
            raise DocumentError(f"{p} is a tutorial, not an experiment; start it with:  edge tutorial {doc.get('id') or p.stem}")
        raise DocumentError(f"{p}: doesn't look like an EDGE experiment (no 'routines' or 'flow')")
    applied = migrate(doc)
    return Loaded(doc, p, hashlib.sha256(raw).hexdigest(), applied)


def atomic_write(path: str | Path, data: str | bytes) -> None:
    """Write via a temporary sibling + rename. The file keeps its permissions; a new one follows the umask
    (like any other file the user creates), so colleagues and lab accounts keep their access."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode: int | None = stat.S_IMODE(os.stat(p).st_mode)
    except OSError:
        mode = None
    while True:
        tmp = str(p.parent / f".{p.name}.{secrets.token_hex(4)}.tmp")
        try:     # 0o666 minus the umask, created exclusively (never through an existing file or link)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
            break
        except FileExistsError:
            continue
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(tmp, mode)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def backup_dir_for(path: Path) -> Path:
    return path.parent / BACKUP_DIR / path.name


def save_document(path: str | Path, doc: dict[str, Any], expected_fingerprint: str | None = None,
                  backup: bool = True, label: str = "") -> str:
    """Save atomically, keeping a backup of the previous version. Returns the new fingerprint.

    ``expected_fingerprint``: the fingerprint from when the caller loaded the file; if the
    file has changed since, :class:`ConflictError` is raised. Pass ``None`` to skip the check.
    """
    p = Path(path)
    current = fingerprint(p)
    if expected_fingerprint is not None and current and expected_fingerprint != current:
        raise ConflictError(p, expected_fingerprint, current)
    doc = dict(doc)
    doc["edge_format"] = FORMAT_VERSION
    doc = {"edge_format": doc.pop("edge_format"), **doc}  # keep it at the top of the file
    text = dumps(doc, fmt_of(p))
    if fmt_of(p) == "yaml" and p.is_file():
        try:
            old = p.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            old = ""
        if re.search(r"(?m)(^|\s)#", old):         # a comment (not just a colour such as '#111111')
            text = carry_comments(old, text)
    if backup and p.exists():
        if p.read_text(encoding="utf-8-sig") == text:
            return current  # no change: no new backup
        _make_backup(p, label)
    atomic_write(p, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_backup(p: Path, label: str = "") -> Path:
    bdir = backup_dir_for(p)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    slug = ("_" + re.sub(r"[^A-Za-z0-9_-]+", "-", label)[:40]) if label else ""
    dest = bdir / f"{stamp}{slug}{p.suffix}"
    shutil.copy2(p, dest)
    backups = sorted(bdir.glob(f"*{p.suffix}"))
    for old in backups[:-MAX_BACKUPS]:
        old.unlink()
    return dest


# ---------------------------------------------------------------------- comments
class _Layout:
    """Where things are in a YAML text: the outermost key or list item starting on each line (as a path that
    survives edits: list items with an id are named by it), the lines inside multi-line text, and where the
    last value on each line ends (anything after it is a comment)."""

    def __init__(self, text: str):
        self.path_at: dict[int, tuple] = {}
        self.line_of: dict[tuple, int] = {}
        self.inside: set[int] = set()
        self.multi_start: set[int] = set()
        self.ends: dict[int, int] = {}
        root = yaml.compose(text, Loader=_Loader)
        if root is not None:
            self._visit(root, (), set())

    def _at(self, path: tuple, line: int) -> None:
        self.path_at.setdefault(line, path)
        self.line_of.setdefault(path, line)

    def _end(self, n: Any) -> None:
        self.ends[n.end_mark.line] = max(self.ends.get(n.end_mark.line, 0), n.end_mark.column)

    def _visit(self, n: Any, path: tuple, stack: set[int]) -> None:
        if id(n) in stack:
            return
        stack = stack | {id(n)}
        if isinstance(n, yaml.ScalarNode):
            s, e = n.start_mark, n.end_mark
            if e.line > s.line:
                self.multi_start.add(s.line)
                self.inside.update(range(s.line + 1, e.line + (1 if e.column else 0)))
            self._end(n)
        elif isinstance(n, yaml.MappingNode):
            if n.flow_style:
                self._end(n)
            for k, v in n.value:
                p = path + (("key", k.value if isinstance(k, yaml.ScalarNode) else repr(k.start_mark)),)
                self._at(p, k.start_mark.line)
                self._visit(k, p, stack)
                self._visit(v, p, stack)
        elif isinstance(n, yaml.SequenceNode):
            if n.flow_style:
                self._end(n)
            seen: dict[Any, int] = {}
            for i, v in enumerate(n.value):
                name: Any = ("item", i)
                if isinstance(v, yaml.MappingNode):
                    for k, kv in v.value:
                        if isinstance(k, yaml.ScalarNode) and k.value in ("id", "loop", "statemachine", "routine") \
                                and isinstance(kv, yaml.ScalarNode):
                            name = (k.value, kv.value)
                            break
                elif isinstance(v, yaml.ScalarNode):
                    name = ("value", v.value)
                seen[name] = seen.get(name, -1) + 1
                p = path + (name + (seen[name],),)
                self._at(p, v.start_mark.line)
                self._visit(v, p, stack)


def carry_comments(old_text: str, new_text: str) -> str:
    """``new_text`` (a fresh dump of an edited document) with the ``# comments`` of ``old_text`` put back:
    a comment above a key or list item goes above the same key or item, a comment at the end of a line goes
    after the same key or item, and the comments at the top and bottom of the file stay there. Comments
    about something that was deleted are dropped. If anything could change the document's meaning, the
    comments are left out rather than risk it."""
    try:
        old, new = _Layout(old_text), _Layout(new_text)
    except yaml.YAMLError:
        return new_text
    lines = old_text.splitlines()
    out = new_text.splitlines()
    above: dict[Any, list[str]] = {}     # new line index, "top" or "end" -> comment lines to put above it
    trailing: dict[int, str] = {}
    first_content = next((i for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), len(lines))
    i = 0
    while i < len(lines):
        ln = lines[i]
        if i in old.inside or not ln.lstrip().startswith("#"):
            if i not in old.inside and i in old.ends:
                m = re.search(r"\s(#.*)$", ln[old.ends[i]:])
                if m and i in old.path_at:
                    path = old.path_at[i]
                    j = new.line_of.get(path)
                    if j is not None:
                        if j in new.multi_start or j in trailing:
                            above.setdefault(j, []).append(m.group(1))
                        else:
                            trailing[j] = m.group(1)
            i += 1
            continue
        start = i                      # a block of comment lines (blank lines between them belong to it)
        while i < len(lines) and i not in old.inside and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
            i += 1
        block = [x.strip() for x in lines[start:i]]
        while block and not block[-1]:
            block.pop()
        gap = start > 0 and not lines[start - 1].strip()
        if start < first_content:
            where: Any = "top"
        elif i >= len(lines):
            where = "end"
        else:
            path = old.path_at.get(i)
            where = new.line_of.get(path) if path is not None else None
        if where is None:
            continue
        above.setdefault(where, []).extend(([""] if gap and where != "top" else []) + block)
    if not above and not trailing:
        return new_text
    if above.get("top") and first_content > 0 and not lines[first_content - 1].strip():
        above["top"].append("")
    result: list[str] = list(above.get("top", []))
    for j, ln in enumerate(out):
        indent = ln[:len(ln) - len(ln.lstrip(" "))]
        result += [indent + c if c else "" for c in above.get(j, [])]
        result.append(f"{ln}  {trailing[j]}" if j in trailing else ln)
    result += above.get("end", [])
    text = "\n".join(result) + "\n"
    try:     # never at the price of the content
        if _safe_load(text) != _safe_load(new_text):
            return new_text
    except yaml.YAMLError:
        return new_text
    return text


def list_backups(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    out = []
    for b in sorted(backup_dir_for(p).glob(f"*{p.suffix}"), reverse=True):
        stem = b.stem
        stamp, _, label = stem.partition("_")
        try:
            when = datetime.strptime(stamp, "%Y%m%d-%H%M%S-%f").isoformat(timespec="seconds")
        except ValueError:
            when = stamp
        out.append({"id": b.name, "time": when, "label": label.replace("-", " "), "path": str(b)})
    return out


def restore_backup(path: str | Path, backup_id: str | None = None) -> str:
    """Restore the newest backup (or ``backup_id``). The current version is backed up first,
    so a restore can itself be undone."""
    p = Path(path)
    backups = list_backups(p)
    if not backups:
        raise DocumentError(f"no backups for {p}")
    if backup_id:
        chosen = next((b for b in backups if b["id"] == backup_id), None)
    else:  # "undo": the newest real edit, skipping the safety copies restores make of themselves
        chosen = next((b for b in backups if "before restore" not in b["label"]), None)
    if chosen is None:
        raise DocumentError(f"backup '{backup_id}' not found" if backup_id else f"nothing to undo for {p}")
    content = Path(chosen["path"]).read_bytes()
    if p.exists():
        _make_backup(p, "before-restore")
    atomic_write(p, content)
    if not backup_id:
        Path(chosen["path"]).unlink()  # popping the newest backup makes repeated undo walk back in time
    return chosen["id"]


# ---------------------------------------------------------------------- bundles
FILE_PROP_TYPES = {"file"}


def _html_assets(page: str, base_dir: Path) -> set[str]:
    """Local files (images, css, js) referenced by an HTML page, relative to the experiment folder."""
    p = base_dir / page
    if not p.exists():
        return set()
    found = set()
    for ref in re.findall(r"""(?:src|href)\s*=\s*["']([^"'#?]+)""", p.read_text(encoding="utf-8", errors="ignore")):
        if re.match(r"^(?:[a-z]+:|//|/)", ref):
            continue
        target = (p.parent / ref).resolve()
        if target.is_file() and base_dir.resolve() in target.parents:
            found.add(str(target.relative_to(base_dir.resolve()).as_posix()))
    return found


def referenced_files(doc: dict[str, Any], base_dir: Path | None = None) -> set[str]:
    """Relative paths of files an experiment depends on (conditions, images, sounds, HTML pages and
    the assets those pages use)."""
    from .components import component_registry

    reg = component_registry()
    out: set[str] = set()

    def literal(v: Any) -> bool:
        return isinstance(v, str) and v and not v.startswith("$") and not re.match(r"^[a-z]+://", v)

    for r in (doc.get("routines") or {}).values():
        for c in (r or {}).get("components", []) or []:
            cls = reg.get(c.get("type"))
            if cls is None:
                continue
            for k, meta in cls.all_props().items():
                if meta.get("type") in FILE_PROP_TYPES and literal(c.get(k)) and not _is_number(c.get(k)):
                    out.add(c[k])
            if c.get("type") == "survey":       # images / media / drill-down files used by survey questions
                try:
                    from .survey import media_files
                    out |= {f for f in media_files(c.get("questions") or []) if literal(f)}
                except Exception:
                    pass
                out |= {q["file"] for q in c.get("questions") or [] if isinstance(q, dict) and literal(q.get("file"))}

    def walk(nodes: Any) -> Iterator[dict]:
        for n in nodes or []:
            if isinstance(n, dict):
                yield n
                yield from walk(n.get("children"))
                yield from walk(n.get("then"))
                yield from walk(n.get("else"))
                for st in (n.get("states") or {}).values():
                    if isinstance(st, dict):
                        yield from walk(st.get("run"))

    html_pages = [f for f in out if f.lower().endswith((".html", ".htm"))]
    out |= {a for page in html_pages for a in _html_assets(page, base_dir)} if base_dir else set()

    for n in walk(doc.get("flow")):
        cond = n.get("conditions")
        if isinstance(cond, dict):
            cond = cond.get("file")
        if literal(cond):
            out.add(cond)
        # pictures, sounds and pages named in a trial list ($column) are part of the experiment too
        if base_dir is not None and n.get("conditions") is not None and not (isinstance(n.get("conditions"), str)
                                                                              and n["conditions"].startswith("$")):
            try:
                from .conditions import load_conditions
                rows = load_conditions(n["conditions"], Path(base_dir))
            except Exception:
                rows = []
            for row in rows:
                for v in row.values():
                    if literal(v) and "." in v and len(v) < 260 and not _is_number(v):
                        fp = Path(base_dir) / v
                        try:
                            if fp.is_file() and Path(base_dir).resolve() in fp.resolve().parents:
                                out.add(v)
                        except OSError:
                            continue
    return out


def _is_number(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def export_bundle(path: str | Path, out: str | Path | None = None) -> dict[str, Any]:
    """Pack the experiment + referenced files into a ``.edgez`` zip. Missing files are reported."""
    loaded = load_document(path)
    base = loaded.path.parent
    out = Path(out) if out else loaded.path.with_suffix(".edgez")
    files = sorted(referenced_files(loaded.doc, base))
    included, missing = [], []
    text = None
    if fmt_of(loaded.path) == "yaml" and not loaded.migrations:      # the file as written, comments and all
        try:
            text = loaded.path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            text = None
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("experiment.yaml", text if text is not None else dumps(loaded.doc))
        manifest = {"edge_format": FORMAT_VERSION, "name": loaded.doc.get("name"), "source": loaded.path.name,
                    "created": datetime.now().isoformat(timespec="seconds"), "files": []}
        for rel in files:
            fp = (base / rel)
            if fp.is_file() and base.resolve() in fp.resolve().parents:
                z.write(fp, f"files/{Path(rel).as_posix()}")
                included.append(rel)
            else:
                missing.append(rel)
        manifest["files"] = included
        try:   # versions and fingerprints, so the receiver can check they run the same thing
            from .reproduce import environment, file_hashes, lock_path
            manifest["environment"] = environment()
            manifest["sha256"] = {k: v for k, v in file_hashes(loaded.doc, base).items() if v}
            lp = lock_path(loaded.path)
            if lp.exists():
                z.write(lp, lp.name)
                manifest["lock"] = lp.name
        except Exception:
            pass
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return {"bundle": str(out), "files": included, "missing": missing}


def import_bundle(bundle: str | Path, dest_dir: str | Path, overwrite: bool = False) -> Path:
    """Unpack a ``.edgez`` bundle into ``dest_dir``; returns the experiment path.

    Everything is checked before anything is written: a bundle with an entry that would land outside
    ``dest_dir`` is refused as a whole, and so is unpacking over files in ``dest_dir`` that differ from the
    bundle's (an edited trial list, another experiment's files). With ``overwrite`` those files are replaced,
    each one backed up first (``edge backups FILE``)."""
    from .reproduce import lock_path
    dest = Path(dest_dir)
    root = dest.resolve()
    writes: list[tuple[Path, bytes]] = []
    with zipfile.ZipFile(bundle) as z:
        manifest = json.loads(z.read("manifest.json"))
        name = Path(manifest.get("source") or "experiment.yaml").name
        if Path(name).suffix.lower() not in (".yaml", ".yml", ".json"):
            name = "experiment.yaml"
        for info in z.infolist():
            if not info.filename.startswith("files/") or info.is_dir():
                continue
            rel = info.filename[len("files/"):]
            if root not in (dest / rel).resolve().parents:
                raise DocumentError(f"{Path(bundle).name} is not a safe bundle: its file '{rel}' would be written "
                                    f"outside {dest}. Nothing was unpacked.")
            writes.append((dest / rel, z.read(info)))
        text = z.read("experiment.yaml").decode("utf-8-sig")
        lock_data = z.read(manifest["lock"]) if manifest.get("lock") in z.namelist() else None
    doc = loads(text, "yaml", str(bundle))
    exp_path = dest / name
    if fmt_of(exp_path) == "yaml" and not migrate(copy.deepcopy(doc)):
        content = text.encode("utf-8")           # exactly as the sender wrote it, comments and all
    else:
        migrate(doc)
        content = dumps({"edge_format": FORMAT_VERSION, **{k: v for k, v in doc.items() if k != "edge_format"}},
                        fmt_of(exp_path)).encode("utf-8")
    writes.append((exp_path, content))
    if lock_data is not None:      # keep the lock, so 'edge verify' works on the receiving computer
        writes.append((lock_path(exp_path), lock_data))
    differ = [t for t, data in writes if t.exists() and (not t.is_file() or t.read_bytes() != data)]
    if differ and not overwrite:
        other = dest.with_name(dest.name + "_2")
        n = 3
        while other.exists():
            other, n = dest.with_name(f"{dest.name}_{n}"), n + 1
        shown = sorted({t.relative_to(dest).as_posix() for t in differ})
        raise DocumentError(f"the folder {dest.name or dest} already has {', '.join(shown[:6])}"
                            f"{' …' if len(shown) > 6 else ''}, different from the bundle's "
                            f"{'copy' if len(shown) == 1 else 'copies'}. Nothing was unpacked, so nothing of yours was "
                            f"replaced: unpack into a new folder instead (e.g. {other.name}), or move those files "
                            "away first.")
    for t, data in writes:
        if t.is_file():
            if t.read_bytes() == data:
                continue
            _make_backup(t, "before unbundle")
        atomic_write(t, data)
    return exp_path
