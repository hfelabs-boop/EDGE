"""EDGE — experiment builder and runtime for behavioral, eye-tracking, physiology and EEG research.

Scripting EDGE from Python (see "Scripting EDGE from Python" in docs/DATA.md)::

    import edge
    summary = edge.run("stroop.yaml", participant="012", dry_run=True)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The release number. Keep it equal to `version` in pyproject.toml and raise it for every release.
__release__ = "0.1.0"


def _is_commit(s: str) -> bool:
    return len(s) in (40, 64) and all(c in "0123456789abcdef" for c in s)


def _git_commit(top: Path) -> str | None:
    """The commit checked out in the git clone at ``top``, read from ``.git`` without running git."""
    git = top / ".git"
    try:
        if git.is_file():                              # a worktree: ".git" says "gitdir: <path>"
            line = git.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir:"):
                return None
            git = (top / line[len("gitdir:"):].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if _is_commit(head) else None   # detached HEAD
        ref = head[len("ref:"):].strip()
        common = git
        if (git / "commondir").is_file():
            common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for d in (git, common):
            if (d / ref).is_file():
                sha = (d / ref).read_text(encoding="utf-8").strip()
                return sha if _is_commit(sha) else None
        if (common / "packed-refs").is_file():
            for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref and _is_commit(parts[0]):
                    return parts[0]
    except (OSError, UnicodeDecodeError):
        return None
    return None


def installed_source(running: bool = True) -> dict[str, Any] | None:
    """Where pip installed EDGE from (its ``direct_url.json``), or None if unknown.

    ``{"url": ..., "vcs": "git" or None, "commit": full commit or None, "revision": requested branch/tag
    or None, "editable": bool}``. With ``running`` (the default) only the copy whose code is running
    counts, not another EDGE installed in this Python (e.g. when ``python -m edge`` runs a clone
    because it is the current folder).
    """
    try:
        from importlib import metadata
        dists = list(metadata.distributions(name="edge-experiments"))
    except Exception:
        return None
    here = Path(__file__).resolve()
    for dist in dists:
        try:
            info = json.loads(dist.read_text("direct_url.json") or "null")
        except Exception:
            continue
        if not isinstance(info, dict) or not isinstance(info.get("url"), str):
            continue
        editable = bool((info.get("dir_info") or {}).get("editable"))
        if running:
            try:
                if editable:
                    from urllib.parse import urlparse
                    from urllib.request import url2pathname
                    ok = Path(url2pathname(urlparse(info["url"]).path)).resolve() == here.parent.parent
                else:
                    ok = Path(str(dist.locate_file("edge/__init__.py"))).resolve() == here
            except Exception:
                ok = False
            if not ok:
                continue
        vcs = info.get("vcs_info") or {}
        commit = vcs.get("commit_id") if isinstance(vcs.get("commit_id"), str) and _is_commit(vcs["commit_id"]) else None
        return {"url": info["url"], "vcs": vcs.get("vcs"), "commit": commit,
                "revision": vcs.get("requested_revision"), "editable": editable}
    return None


def checkout_dir() -> Path | None:
    """The git clone this EDGE runs from, if it does."""
    top = Path(__file__).resolve().parent.parent
    return top if (top / ".git").exists() and (top / "pyproject.toml").is_file() else None


def build_commit() -> str | None:
    """The git commit of the EDGE code that is running: from its clone, or the one pip installed it from."""
    top = checkout_dir()
    if top is not None:
        return _git_commit(top)
    src = installed_source()
    return src["commit"] if src else None


def build_version() -> str:
    """The release number plus the commit when known, e.g. ``0.1.0+g61bc96e``, so that session data,
    locks and ``edge --version`` tell apart two EDGE builds that share a release number."""
    commit = build_commit()
    return f"{__release__}+g{commit[:7]}" if commit else __release__


__version__ = build_version()

from .model import Experiment  # noqa: E402


def run(path_or_experiment: Any, participant: Any = None, **kw: Any) -> dict[str, Any]:
    """Load (if needed) and run an experiment; returns the session summary.

    ``participant`` is the participant ID (``"012"``), or a dict of participant fields such as
    ``{"participant": "012", "session": "1", "group": "A"}``: the same as ``edge run -p 012 -s 1 -f group=A``.
    Other keywords go to :func:`edge.engine.run_experiment`, e.g. ``dry_run=True``, ``data_dir="data"``.
    """
    from .engine import run_experiment

    if participant is not None:
        if isinstance(participant, (str, int)) and not isinstance(participant, bool):
            participant = {"participant": participant}
        elif not isinstance(participant, dict):
            raise TypeError("participant must be a participant ID such as '012', or a dict of participant fields "
                            "such as {'participant': '012', 'session': '1'}")
        # IDs are text, as on the command line: 012 stays "012" and 9 is stored as "9"
        participant = {k: (str(v) if k in ("participant", "session") and v is not None else v) for k, v in participant.items()}
    exp = path_or_experiment if isinstance(path_or_experiment, Experiment) else Experiment.load(path_or_experiment)
    return run_experiment(exp, participant=participant, **kw)


__all__ = ["Experiment", "run", "__version__"]
