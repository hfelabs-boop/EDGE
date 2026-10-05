"""Update EDGE to the newest version: ``edge update`` (or ``update.sh`` / ``update.bat``).

Two kinds of installation are handled:

* **a clone of the repository** (``git clone`` + ``pip install -e``): the newest commits are fetched
  and applied with a fast-forward ``git pull``, then EDGE is reinstalled so new dependencies arrive
  too. Local changes are never overwritten: without ``--stash`` the update stops and says so, with
  ``--stash`` they are set aside and put back afterwards.
* **an installed copy** (the installer scripts, or ``pip install`` from the repository): pip
  upgrades EDGE from the repository.

Experiments, data and settings are never touched. ``edge update --check`` only looks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_URL = "https://github.com/hfelabs-boop/EDGE.git"
DEFAULT_BRANCH = "main"

Runner = Callable[[list[str], Path | None], "tuple[int, str]"]


def run_cmd(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=600,
                           creationflags=0x08000000 if sys.platform.startswith("win") else 0)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd[:3])} …: took too long"
    return r.returncode, (r.stdout + r.stderr).strip()


def find_checkout() -> Path | None:
    """The git clone EDGE runs from, if it does."""
    here = Path(__file__).resolve().parent.parent
    return here if (here / ".git").exists() and (here / "pyproject.toml").exists() else None


def current_version() -> str:
    from . import __version__
    return __version__


def _git(root: Path, run: Runner, *args: str) -> tuple[int, str]:
    return run(["git", *args], root)


def check_checkout(root: Path, run: Runner = run_cmd, branch: str | None = None) -> dict[str, Any]:
    """Fetch and compare with the remote: how many new commits, what they are."""
    out: dict[str, Any] = {"kind": "checkout", "root": str(root)}
    code, text = _git(root, run, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return {**out, "error": f"not a usable git repository ({text})"}
    current = text.strip()
    target = branch or (current if current != "HEAD" else DEFAULT_BRANCH)
    code, text = _git(root, run, "fetch", "origin", target)
    if code != 0:
        return {**out, "error": "could not reach the repository: " + (text.splitlines()[-1] if text else "check the internet connection")}
    code, text = _git(root, run, "rev-list", "--count", f"HEAD..origin/{target}")
    behind = int(text) if code == 0 and text.strip().isdigit() else 0
    code, text = _git(root, run, "rev-list", "--count", f"origin/{target}..HEAD")
    ahead = int(text) if code == 0 and text.strip().isdigit() else 0
    _, log = _git(root, run, "log", "--format=%h %s", f"HEAD..origin/{target}", "-n", "20")
    _, status = _git(root, run, "status", "--porcelain", "--untracked-files=no")
    return {**out, "branch": current, "target": target, "behind": behind, "ahead": ahead,
            "new": log.splitlines() if behind else [], "dirty": [line for line in status.splitlines() if line.strip()]}


def update_checkout(root: Path, run: Runner = run_cmd, stash: bool = False, branch: str | None = None,
                    reinstall: bool = True, say: Callable[[str], None] = print) -> dict[str, Any]:
    info = check_checkout(root, run, branch)
    if info.get("error"):
        return {**info, "ok": False}
    if info["behind"] == 0:
        say(f"EDGE {current_version()} is already the newest version ({info['target']}).")
        return {**info, "ok": True, "updated": False}
    say(f"{info['behind']} new change{'s' if info['behind'] > 1 else ''} on {info['target']}:")
    for line in info["new"][:10]:
        say("  " + line)
    if info["behind"] > 10:
        say(f"  … and {info['behind'] - 10} more")
    stashed = False
    if info["dirty"]:
        if not stash:
            say("")
            say("You have changes of your own in this folder, so nothing was changed:")
            for line in info["dirty"][:8]:
                say("  " + line)
            say("Keep them and update:  edge update --stash      (they are put back afterwards)")
            say("Save them first:       git commit -am \"my changes\", then edge update")
            return {**info, "ok": False, "updated": False, "reason": "local changes"}
        code, text = _git(root, run, "stash", "push", "-m", "edge update")
        if code != 0:
            return {**info, "ok": False, "updated": False, "reason": f"could not set your changes aside: {text}"}
        stashed = True
    if info["branch"] != info["target"] and info["branch"] != "HEAD":
        code, text = _git(root, run, "checkout", info["target"])
        if code != 0:
            return _restore({**info, "ok": False, "updated": False, "reason": f"could not switch to {info['target']}: {text}"},
                            root, run, stashed, say)
    code, text = _git(root, run, "pull", "--ff-only", "origin", info["target"])
    if code != 0:
        why = ("your copy has commits that aren't in the repository, so it can't be fast-forwarded"
               if info["ahead"] else text.splitlines()[-1] if text else "git pull failed")
        say(f"The update could not be applied: {why}.")
        return _restore({**info, "ok": False, "updated": False, "reason": why}, root, run, stashed, say)
    res = {**info, "ok": True, "updated": True}
    if reinstall:
        say("Installing what's new (a minute or two)…")
        code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "-e", ".[all]"], root)
        if code != 0:
            code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "-e", "."], root)
        if code != 0:
            say("The files were updated but the installation step failed: " + (text.splitlines()[-1] if text else ""))
            res["install_error"] = text
    return _restore(res, root, run, stashed, say)


def _restore(res: dict[str, Any], root: Path, run: Runner, stashed: bool, say: Callable[[str], None]) -> dict[str, Any]:
    if stashed:
        code, text = _git(root, run, "stash", "pop")
        if code != 0:
            say("Your own changes could not be put back automatically (they conflict with the update).")
            say("They are safe: see them with  git stash list  and apply with  git stash pop  after resolving.")
            res["stash_conflict"] = True
        else:
            say("Your own changes were put back.")
    return res


def update_installed(run: Runner = run_cmd, source: str | None = None, say: Callable[[str], None] = print) -> dict[str, Any]:
    """An installed copy (no git clone): upgrade from the repository with pip."""
    before = current_version()
    src = source or f"git+{REPO_URL}"
    say("Downloading the newest EDGE (a minute or two)…")
    code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", f"edge-experiments[all] @ {src}"], None)
    if code != 0:
        code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", f"{src}#egg=edge-experiments[all]"], None)
    if code != 0:
        why = text.splitlines()[-1] if text else "pip failed"
        if "git" in text.lower() and ("not found" in text.lower() or "cannot find command" in text.lower()):
            why = "git is not installed (https://git-scm.com/downloads), and pip needs it to download EDGE"
        return {"kind": "installed", "ok": False, "reason": why, "version_before": before}
    return {"kind": "installed", "ok": True, "updated": True, "version_before": before}


def update(check_only: bool = False, stash: bool = False, branch: str | None = None, run: Runner = run_cmd,
           say: Callable[[str], None] = print, root: Path | None = None) -> dict[str, Any]:
    root = root or find_checkout()
    if root is not None:
        if check_only:
            info = check_checkout(root, run, branch)
            if info.get("error"):
                say("Could not check: " + info["error"])
            elif info["behind"]:
                say(f"{info['behind']} new change{'s' if info['behind'] > 1 else ''} available on {info['target']}. Update with:  edge update")
                for line in info["new"][:5]:
                    say("  " + line)
            else:
                say(f"EDGE {current_version()} is up to date.")
            return {**info, "ok": "error" not in info}
        return update_checkout(root, run, stash=stash, branch=branch, say=say)
    if check_only:
        say("This copy of EDGE was installed without git, so it can't tell what is new. Update with:  edge update")
        return {"kind": "installed", "ok": True}
    return update_installed(run, say=say)
