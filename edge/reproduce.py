"""Reproducibility: lock an experiment once it's piloted, and notice anything that changes it.

``edge lock study.yaml`` writes ``study.lock.json`` next to the experiment with:

* the environment: EDGE, Python, operating system, the versions of the packages that matter
  (display, sound, LSL, serial …) and any plugins;
* a fingerprint (SHA-256) of the experiment and of every file it uses: conditions files, pictures,
  sounds, pages, including the files named inside trial lists;
* a **golden participant**: a dry run with fixed seeds whose trial sequence and data columns are
  recorded.

``edge verify study.yaml`` (and the preflight before every real session) repeats all of it and says
what differs: an EDGE or package update, a picture that was edited, an experiment that was changed
after locking, or, most importantly, an experiment that now *behaves* differently (another trial
order, other screens, other data columns) even though nobody meant to change it.
"""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

KEY_PACKAGES = ["pyglet", "PyYAML", "pylsl", "pyserial", "numpy", "sounddevice", "python-bidi", "pywebview",
                "mcp", "tobii-research", "LabJackPython", "pyarrow", "scipy", "openpyxl"]
GOLDEN_SEED = 20240101
LOCK_VERSION = 1


def environment() -> dict[str, Any]:
    from importlib import metadata
    from . import __version__
    pkgs = {}
    for name in KEY_PACKAGES:
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    plugins = {}
    try:
        for group in ("edge.devices", "edge.components"):
            for ep in metadata.entry_points(group=group):
                dist = getattr(ep, "dist", None)
                plugins[f"{group}:{ep.name}"] = f"{ep.value}" + (f" ({dist.name} {dist.version})" if dist else "")
    except Exception:
        pass
    return {"edge": __version__, "python": platform.python_version(), "os": platform.platform(),
            "machine": platform.machine(), "packages": pkgs, "plugins": plugins}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hashes(doc: dict[str, Any], base: Path) -> dict[str, str | None]:
    from .storage import referenced_files
    out: dict[str, str | None] = {}
    for rel in sorted(referenced_files(doc, base)):
        p = base / rel
        out[rel] = _sha(p.read_bytes()) if p.is_file() else None
    return out


def experiment_hash(doc: dict[str, Any]) -> str:
    return _sha(json.dumps(doc, sort_keys=True, default=str).encode())


def golden_run(doc: dict[str, Any], base: Path) -> dict[str, Any]:
    """A dry run with fixed seeds: what a participant would go through, step by step."""
    import copy
    from .engine import run_experiment
    from .export import SessionTables, wide_trials
    from .model import Experiment
    from .participant import VirtualParticipant
    d = copy.deepcopy(doc)
    d.setdefault("settings", {})
    if d["settings"].get("seed") is None:
        d["settings"]["seed"] = GOLDEN_SEED
    exp = Experiment.from_dict(d, base_dir=base)
    with tempfile.TemporaryDirectory() as td:
        s = run_experiment(exp, dry_run=True, data_dir=td, log=lambda *a: None,
                           virtual_participant=VirtualParticipant(seed=0), participant={"participant": "golden"})
        st = SessionTables(s["data_dir"])
        cols, rows = wide_trials(st, drop_empty=False)
    conds = list(st.condition_cols)
    steps = [[r.get("routines", ""), {c: r.get(c) for c in conds if c in r}] for r in rows]
    return {"seed": d["settings"]["seed"], "n_trials": len(rows), "columns": cols,
            "steps_sha256": _sha(json.dumps(steps, sort_keys=True, default=str).encode()),
            "steps": steps[:400]}


def lock(path: str | Path, golden: bool = True) -> dict[str, Any]:
    from .storage import load_document
    loaded = load_document(path)
    base = loaded.path.parent
    data = {"edge_lock": LOCK_VERSION, "experiment": loaded.doc.get("name"), "file": loaded.path.name,
            "created": datetime.now().isoformat(timespec="seconds"),
            "experiment_sha256": experiment_hash(loaded.doc), "environment": environment(),
            "files": file_hashes(loaded.doc, base)}
    if golden:
        data["golden"] = golden_run(loaded.doc, base)
    out = lock_path(loaded.path)
    out.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    return {"lock": str(out), **{k: data[k] for k in ("experiment", "created")},
            "files": len(data["files"]), "trials": data.get("golden", {}).get("n_trials")}


def lock_path(exp_path: str | Path) -> Path:
    p = Path(exp_path)
    return p.with_name(p.stem + ".lock.json")


def verify(path: str | Path, golden: bool = True) -> dict[str, Any]:
    """Compare the experiment and this computer with the lock. Findings: level (ok/info/warning/error) + text."""
    from .storage import load_document
    loaded = load_document(path)
    lp = lock_path(loaded.path)
    if not lp.exists():
        return {"locked": False, "findings": [{"level": "info", "what": "not locked yet",
                                               "detail": "lock it after piloting (edge lock) so later changes are caught"}]}
    lk = json.loads(lp.read_text(encoding="utf-8"))
    base = loaded.path.parent
    out: list[dict[str, Any]] = []

    def add(level: str, what: str, detail: str = "") -> None:
        out.append({"level": level, "what": what, "detail": detail})

    if experiment_hash(loaded.doc) != lk.get("experiment_sha256"):
        add("warning", "the experiment was changed after it was locked",
            "if the change is intended, lock it again (edge lock) so the record matches what participants get")
    env, old = environment(), lk.get("environment") or {}
    if env["edge"] != old.get("edge"):
        add("warning", f"EDGE {old.get('edge')} → {env['edge']}",
            "a different EDGE version than the pilot: the golden participant below shows whether the experiment behaves the same")
    if env["python"].rsplit(".", 1)[0] != str(old.get("python", "")).rsplit(".", 1)[0]:
        add("info", f"Python {old.get('python')} → {env['python']}")
    for name in sorted(set(env["packages"]) | set(old.get("packages") or {})):
        a, b = (old.get("packages") or {}).get(name), env["packages"].get(name)
        if a != b:
            lvl = "warning" if name in ("pyglet", "pylsl", "pyserial", "sounddevice", "tobii-research", "LabJackPython") else "info"
            add(lvl, f"{name}: {a or 'not installed'} → {b or 'not installed'}",
                "this package handles the display/sound/devices" if lvl == "warning" else "")
    if env["plugins"] != (old.get("plugins") or {}):
        add("warning", "plugins differ from the pilot",
            f"locked: {sorted(old.get('plugins') or {})}; now: {sorted(env['plugins'])}")
    now = file_hashes(loaded.doc, base)
    for rel, h in sorted((lk.get("files") or {}).items()):
        if rel not in now:
            add("info", f"{rel} is no longer used")
        elif now[rel] is None:
            add("error", f"{rel} is missing", "the experiment needs it")
        elif h is not None and now[rel] != h:
            add("warning", f"{rel} changed since the lock", "participants will see/hear a different file than in the pilot")
    for rel in sorted(set(now) - set(lk.get("files") or {})):
        add("info", f"{rel} is new since the lock")
    if golden and lk.get("golden"):
        try:
            g = golden_run(loaded.doc, base)
        except Exception as e:
            add("error", "the golden participant could not finish", f"{type(e).__name__}: {e}")
        else:
            lg = lk["golden"]
            if g["steps_sha256"] != lg.get("steps_sha256") or g["n_trials"] != lg.get("n_trials"):
                add("warning", "the experiment now behaves differently from the pilot", _first_difference(lg, g))
            missing = [c for c in lg.get("columns", []) if c not in g["columns"]]
            extra = [c for c in g["columns"] if c not in lg.get("columns", [])]
            if missing:
                add("warning", f"data columns no longer recorded: {', '.join(missing[:6])}")
            if extra:
                add("info", f"new data columns: {', '.join(extra[:6])}")
            if not any(f["what"].startswith("the experiment now behaves") for f in out):
                add("ok", f"the golden participant goes through the same {g['n_trials']} trials as in the pilot")
    if not any(f["level"] in ("warning", "error") for f in out):
        add("ok", f"matches the lock of {lk.get('created')}")
    return {"locked": True, "lock": str(lp), "created": lk.get("created"), "findings": out}


def _first_difference(old: dict[str, Any], new: dict[str, Any]) -> str:
    if old.get("n_trials") != new.get("n_trials"):
        head = f"{old.get('n_trials')} trials in the pilot, {new.get('n_trials')} now"
    else:
        head = "same number of trials, different order or content"
    for i, (a, b) in enumerate(zip(old.get("steps") or [], new.get("steps") or [])):
        if a != b:
            return f"{head}; first difference at trial {i + 1}: pilot {_step(a)}, now {_step(b)}"
    return head


def _step(s: list[Any]) -> str:
    routines, cond = s
    c = ", ".join(f"{k}={v}" for k, v in (cond or {}).items())
    return f"{routines}" + (f" ({c})" if c else "")


def format_verify(res: dict[str, Any]) -> str:
    mark = {"ok": "✓", "info": "·", "warning": "!", "error": "✗"}
    lines = [f"Lock: {res.get('lock', 'none')}" + (f" (made {res['created']})" if res.get("created") else ""), ""]
    for f in res["findings"]:
        lines.append(f"  {mark.get(f['level'], '?')} {f['what']}")
        if f.get("detail"):
            lines.append(f"      {f['detail']}")
    return "\n".join(lines)

