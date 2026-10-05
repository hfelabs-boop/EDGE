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
* **Friendly errors**: YAML/JSON syntax errors come back with line and column.
* **Bundles**: ``export_bundle`` packs an experiment and every file it
  references (conditions, images, sounds) into one ``.edgez`` archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
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
    pass


def _str_presenter(dumper, data: str):
    # multi-line strings (instructions, code) as readable block scalars
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_presenter)


def dumps(doc: dict[str, Any], fmt: str = "yaml") -> str:
    if fmt == "json":
        return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=110)


def loads(text: str, fmt: str = "yaml", source: str = "<string>") -> dict[str, Any]:
    try:
        data = json.loads(text) if fmt == "json" else yaml.safe_load(text)
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
    raw = p.read_bytes()
    doc = loads(raw.decode("utf-8-sig"), fmt_of(p), str(p))
    if doc and not ({"routines", "flow", "name"} & set(doc)):
        raise DocumentError(f"{p}: doesn't look like an EDGE experiment (no 'routines' or 'flow')")
    applied = migrate(doc)
    return Loaded(doc, p, hashlib.sha256(raw).hexdigest(), applied)


def atomic_write(path: str | Path, data: str | bytes) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
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

    html_pages = [f for f in out if f.lower().endswith((".html", ".htm"))]
    out |= {a for page in html_pages for a in _html_assets(page, base_dir)} if base_dir else set()

    for n in walk(doc.get("flow")):
        cond = n.get("conditions")
        if isinstance(cond, dict):
            cond = cond.get("file")
        if literal(cond):
            out.add(cond)
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
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("experiment.yaml", dumps(loaded.doc))
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
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return {"bundle": str(out), "files": included, "missing": missing}


def import_bundle(bundle: str | Path, dest_dir: str | Path) -> Path:
    """Unpack a ``.edgez`` bundle into ``dest_dir``; returns the experiment path."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle) as z:
        manifest = json.loads(z.read("manifest.json"))
        name = Path(manifest.get("source") or "experiment.yaml").name
        if Path(name).suffix.lower() not in (".yaml", ".yml", ".json"):
            name = "experiment.yaml"
        for info in z.infolist():
            if not info.filename.startswith("files/") or info.is_dir():
                continue
            rel = Path(info.filename[len("files/"):])
            target = (dest / rel).resolve()
            if dest.resolve() not in target.parents:
                raise DocumentError(f"unsafe path in bundle: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
        doc = loads(z.read("experiment.yaml").decode("utf-8"), "yaml", str(bundle))
    exp_path = dest / name
    save_document(exp_path, doc, backup=exp_path.exists())
    return exp_path
