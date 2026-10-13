"""Update EDGE to the newest version: ``edge update`` (or ``update.sh`` / ``update.bat``).

Two kinds of installation are handled:

* **a clone of the repository** (``git clone`` + ``pip install -e``): the newest commits are fetched
  and applied (a fast-forward, or a merge when the clone has commits of its own), then EDGE is
  reinstalled into the Python that has this clone installed, so new dependencies arrive too. A
  separately installed EDGE (e.g. the installer's ``~/.edge``) is left alone. Local changes are
  never overwritten: without ``--stash`` the update stops and says so, with ``--stash`` they are set
  aside and put back afterwards (or, if they conflict with the update, kept safe in git's stash).
* **an installed copy** (the installer scripts, or ``pip install`` from the repository): the commit
  it was installed from is compared with the newest one, and pip reinstalls EDGE from the repository.

Experiments, data and settings are never touched. ``edge update --check`` only looks.
Every outcome is said in plain words; the result dict has ``ok`` (and ``updated``).
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import url2pathname

REPO_URL = "https://github.com/hfelabs-boop/EDGE.git"
DEFAULT_BRANCH = "main"

Runner = Callable[[list[str], Path | None], "tuple[int, str]"]
Say = Callable[[str], None]

AFTER_UPDATE = ["Restart the builder if it is open, and press Ctrl+Shift+R in the browser.",
                "Check this computer with:  edge doctor"]


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
    from . import checkout_dir
    return checkout_dir()


def current_version() -> str:
    from . import __version__
    return __version__


def _is_commit(s: str) -> bool:
    return len(s) in (40, 64) and all(c in "0123456789abcdef" for c in s)


def _short(commit: str | None) -> str:
    return commit[:7] if commit else "?"


def _last_line(text: str) -> str:
    return text.strip().splitlines()[-1] if text and text.strip() else ""


def _git_missing(code: int, text: str) -> bool:
    low = (text or "").lower()
    return code == 127 or "cannot find command 'git'" in low or "git: command not found" in low


GIT_MISSING = "git is not installed (https://git-scm.com/downloads), and EDGE needs it to download updates"
OFFLINE = "could not reach the repository (is this computer connected to the internet?)"


def _reach_problem(code: int, text: str, branch: str | None) -> str:
    """Plain words for a failed git fetch / ls-remote."""
    if _git_missing(code, text):
        return GIT_MISSING
    if "couldn't find remote ref" in (text or "").lower():
        return f"there is no branch called '{branch}' in the EDGE repository (check the spelling, or leave out --branch)"
    return OFFLINE


def _git(root: Path, run: Runner, *args: str) -> tuple[int, str]:
    return run(["git", *args], root)


# ============================================================================ a git clone
def check_checkout(root: Path, run: Runner = run_cmd, branch: str | None = None) -> dict[str, Any]:
    """Fetch and compare with the remote: how many new commits, what they are."""
    out: dict[str, Any] = {"kind": "checkout", "root": str(root)}
    code, text = _git(root, run, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0:
        return {**out, "error": GIT_MISSING if _git_missing(code, text) else f"{root} is not a usable git copy of EDGE",
                "detail": _last_line(text)}
    current = text.strip()
    target = branch or (current if current != "HEAD" else DEFAULT_BRANCH)
    code, text = _git(root, run, "fetch", "origin", target)
    if code != 0:
        return {**out, "error": _reach_problem(code, text, target), "detail": _last_line(text)}
    code, text = _git(root, run, "rev-list", "--count", f"HEAD..origin/{target}")
    behind = int(text) if code == 0 and text.strip().isdigit() else 0
    code, text = _git(root, run, "rev-list", "--count", f"origin/{target}..HEAD")
    ahead = int(text) if code == 0 and text.strip().isdigit() else 0
    _, log = _git(root, run, "log", "--format=%h %s", f"HEAD..origin/{target}", "-n", "20")
    _, status = _git(root, run, "status", "--porcelain", "--untracked-files=no")
    return {**out, "branch": current, "target": target, "behind": behind, "ahead": ahead,
            "new": log.splitlines() if behind else [], "dirty": [line for line in status.splitlines() if line.strip()]}


def _conflicted(root: Path, run: Runner) -> list[str]:
    _, text = _git(root, run, "diff", "--name-only", "--diff-filter=U")
    return [line.strip() for line in text.splitlines() if line.strip()]


def install_kind(root: Path) -> str:
    """How the Python running this has EDGE from ``root``: "editable" (pip install -e), "copy" (pip
    install of the folder), or "" (EDGE in this Python came from somewhere else, or isn't installed:
    then nothing is installed into it)."""
    from . import installed_source
    src = installed_source(running=False)
    if not src or not str(src["url"]).startswith("file:"):
        return ""
    try:
        where = Path(url2pathname(urlparse(src["url"]).path)).resolve()
    except (OSError, ValueError):
        return ""
    if where != Path(root).resolve():
        return ""
    return "editable" if src["editable"] else "copy"


def _reinstall(root: Path, run: Runner, say: Say) -> str | None:
    """Install the updated clone into the Python that has it installed. Returns an error, or None."""
    kind = install_kind(root)
    if not kind:
        from . import installed_source
        src = installed_source(running=False)
        if src:
            exe = Path(sys.executable).with_name("edge.exe" if sys.platform.startswith("win") else "edge")
            say(f"The EDGE installed for {sys.executable} came from somewhere else ({src['url']}),")
            say(f"so it was left as it is. Update that one with:  {exe if exe.exists() else 'edge'} update")
        return None
    say("Installing what's new (a minute or two)…")
    editable = ["-e"] if kind == "editable" else []
    code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", *editable, ".[all]"], root)
    if code != 0:
        code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", *editable, "."], root)
    if code != 0:
        return text or "pip failed"
    return None


def update_checkout(root: Path, run: Runner = run_cmd, stash: bool = False, branch: str | None = None,
                    reinstall: bool = True, say: Say = print) -> dict[str, Any]:
    info = check_checkout(root, run, branch)
    if info.get("error"):
        say(f"Could not update: {info['error']}. Nothing was changed.")
        if info.get("detail"):
            say(f"  (git said: {info['detail']})")
        return {**info, "ok": False, "updated": False}
    if info["behind"] == 0:
        say(f"EDGE {current_version()} is already the newest version ({info['target']}).")
        return {**info, "ok": True, "updated": False}
    say(f"{info['behind']} new change{'s' if info['behind'] > 1 else ''} on {info['target']}:")
    for line in info["new"][:10]:
        say("  " + line)
    if info["behind"] > 10:
        say(f"  … and {info['behind'] - 10} more")
    stashed = None
    if info["dirty"]:
        if not stash:
            say("")
            say("You have changes of your own in this folder, so nothing was changed:")
            for line in info["dirty"][:8]:
                say("  " + line)
            say("Keep them and update:  edge update --stash      (they are put back afterwards)")
            return {**info, "ok": False, "updated": False, "reason": "local changes"}
        code, text = _git(root, run, "stash", "push", "-m", "edge update")
        if code != 0:
            say(f"Could not set your changes aside, so nothing was changed: {_last_line(text)}")
            return {**info, "ok": False, "updated": False, "reason": f"could not set your changes aside: {text}"}
        _, stashed = _git(root, run, "rev-parse", "-q", "--verify", "refs/stash")
        stashed = stashed.strip() or "?"
    if info["branch"] != info["target"] and info["branch"] != "HEAD":
        code, text = _git(root, run, "checkout", info["target"])
        if code != 0:
            say(f"Could not switch to {info['target']}, so nothing was changed: {_last_line(text)}")
            return _restore({**info, "ok": False, "updated": False, "reason": f"could not switch to {info['target']}"},
                            root, run, stashed, say)
    before = _head(root, run)
    if info["ahead"]:
        res = _merge(root, run, info, say)
        if res is not None:
            return _restore(res, root, run, stashed, say)
    else:
        code, text = _git(root, run, "pull", "--ff-only", "origin", info["target"])
        if code != 0:
            why = _last_line(text) or "git pull failed"
            say(f"The update could not be applied, so nothing was changed: {why}")
            return _restore({**info, "ok": False, "updated": False, "reason": why}, root, run, stashed, say)
    res = {**info, "ok": True, "updated": True, "commit_before": before, "commit_after": _head(root, run)}
    if reinstall:
        err = _reinstall(root, run, say)
        if err:
            say("The files were updated but the installation step failed: " + _last_line(err))
            res["install_error"] = err
    res = _restore(res, root, run, stashed, say)
    if res["ok"]:
        say(f"EDGE updated: {_short(before)} → {_short(res['commit_after'])}.")
    return res


def _head(root: Path, run: Runner) -> str | None:
    code, text = _git(root, run, "rev-parse", "HEAD")
    return text.strip() if code == 0 and text.strip() else None


def _merge(root: Path, run: Runner, info: dict[str, Any], say: Say) -> dict[str, Any] | None:
    """The clone has commits of its own: combine them with the update. None when that worked."""
    ident: list[str] = []
    code, text = _git(root, run, "config", "user.email")
    if code != 0 or not text.strip():          # a merge commit needs a name; don't fail for want of one
        ident = ["-c", "user.name=EDGE update", "-c", "user.email=edge-update@localhost"]
    code, text = _git(root, run, *ident, "merge", "--no-edit", f"origin/{info['target']}")
    if code == 0:
        say("Your own commits were kept and combined with the update.")
        return None
    files = _conflicted(root, run)
    _git(root, run, "merge", "--abort")
    if files:
        say("The update changes the same lines as commits you made yourself, so nothing was changed:")
        for f in files[:8]:
            say("  " + f)
        say("Your commits are safe. To take the update and keep your commits aside in a branch called my-changes:")
        say(f"  git branch my-changes  &&  git reset --hard origin/{info['target']}")
        why = "your own commits conflict with the update"
    else:
        why = _last_line(text) or "git merge failed"
        say(f"The update could not be combined with your own commits, so nothing was changed: {why}")
    return {**info, "ok": False, "updated": False, "reason": why, "conflicts": files}


def _restore(res: dict[str, Any], root: Path, run: Runner, stashed: str | None, say: Say) -> dict[str, Any]:
    if not stashed:
        return res
    code, text = _git(root, run, "stash", "pop")
    if code == 0:
        say("Your own changes were put back.")
        return res
    # A conflicting pop leaves half-applied files with <<<<<<< markers, and keeps the stash. Go back to
    # the clean, updated files; the user's changes stay in the stash (checked first, so nothing is lost).
    files = _conflicted(root, run)
    _, top = _git(root, run, "rev-parse", "-q", "--verify", "refs/stash")
    if top.strip() and top.strip() == stashed:
        _git(root, run, "reset", "--hard", "--quiet", "HEAD")
    if res.get("updated"):
        say("EDGE was updated, but your own changes edit the same lines as the update, so they were not put back:")
    else:
        say("Your own changes could not be put back automatically:")
    for f in files[:8]:
        say("  " + f)
    say("They are safe in git's stash (see them with:  git stash list  and  git stash show -p).")
    say("To put them back and sort out the differences by hand:  git stash pop")
    return {**res, "ok": False, "stash_conflict": True, "conflicts": files,
            "reason": "your own changes conflict with the update"}


# ============================================================================ an installed copy
def _source() -> dict[str, Any]:
    from . import installed_source
    importlib.invalidate_caches()
    return installed_source() or {}


def check_installed(run: Runner = run_cmd, branch: str | None = None) -> dict[str, Any]:
    """Compare the commit this copy was installed from with the newest one in its repository."""
    src = _source()
    url = src["url"] if src.get("vcs") == "git" else REPO_URL
    rev = branch or src.get("revision")
    out: dict[str, Any] = {"kind": "installed", "url": url, "revision": rev, "installed": src.get("commit")}
    refs = [f"refs/heads/{rev}", f"refs/tags/{rev}", f"refs/tags/{rev}^{{}}"] if rev else ["HEAD"]
    code, text = run(["git", "ls-remote", url, *refs], None)
    if code != 0:
        return {**out, "error": _reach_problem(code, text, rev), "detail": _last_line(text)}
    found = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            found[parts[1]] = parts[0]
    if not rev:
        newest = found.get("HEAD")
    elif _is_commit(rev):                     # installed from a fixed commit: that stays the newest
        newest = rev
    else:                                     # a branch, else a tag (an annotated tag's commit)
        newest = next((found[r] for r in (refs[0], refs[2], refs[1]) if r in found), None)
    if rev and newest is None and branch:
        return {**out, "error": f"there is no branch called '{branch}' in the EDGE repository "
                                "(check the spelling, or leave out --branch)"}
    return {**out, "newest": newest}


def update_installed(run: Runner = run_cmd, source: str | None = None, say: Say = print,
                     branch: str | None = None) -> dict[str, Any]:
    """An installed copy (no git clone): reinstall EDGE from the repository with pip."""
    before = current_version()
    info = check_installed(run, branch)
    if info.get("error"):
        say(f"Could not update: {info['error']}. Nothing was changed.")
        if info.get("detail"):
            say(f"  (git said: {info['detail']})")
        return {**info, "ok": False, "updated": False, "reason": info["error"], "version_before": before}
    if not source and info.get("installed") and info["installed"] == info.get("newest"):
        say(f"EDGE {before} is already the newest version.")
        return {**info, "ok": True, "updated": False, "version_before": before}
    src = source or f"git+{info['url']}" + (f"@{info['revision']}" if info.get("revision") else "")
    say("Downloading the newest EDGE (a minute or two)…")
    # 1. new dependencies (pip leaves EDGE itself alone when the version number is unchanged) …
    code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", f"edge-experiments[all] @ {src}"], None)
    if code == 0:   # … 2. so reinstall EDGE itself, whatever its version number
        code, text = run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade", "--force-reinstall",
                          "--no-deps", f"edge-experiments @ {src}"], None)
    if code != 0:
        why = GIT_MISSING if _git_missing(code, text) else (_last_line(text) or "pip failed")
        say(f"Could not update: {why}")
        return {**info, "ok": False, "updated": False, "reason": why, "version_before": before}
    after = _source().get("commit")
    if info.get("installed") and after:
        say(f"EDGE updated: {_short(info['installed'])} → {_short(after)}.")
    else:
        say("EDGE was reinstalled from the repository.")
    return {**info, "ok": True, "updated": True, "version_before": before, "commit_after": after}


# ============================================================================ edge update
def update(check_only: bool = False, stash: bool = False, branch: str | None = None, run: Runner = run_cmd,
           say: Say = print, root: Path | None = None) -> dict[str, Any]:
    root = root or find_checkout()
    if root is not None:
        if check_only:
            info = check_checkout(root, run, branch)
            if info.get("error"):
                say("Could not check: " + info["error"])
                if info.get("detail"):
                    say(f"  (git said: {info['detail']})")
            elif info["behind"]:
                say(f"{info['behind']} new change{'s' if info['behind'] > 1 else ''} available on {info['target']}. Update with:  edge update")
                for line in info["new"][:5]:
                    say("  " + line)
            else:
                say(f"EDGE {current_version()} is up to date.")
            return {**info, "ok": "error" not in info}
        res = update_checkout(root, run, stash=stash, branch=branch, say=say)
    elif check_only:
        info = check_installed(run, branch)
        if info.get("error"):
            say("Could not check: " + info["error"])
        elif not info.get("installed") or not info.get("newest"):
            say("This copy of EDGE was not installed from git, so it can't tell what is new. Update with:  edge update")
        elif info["installed"] == info["newest"]:
            say(f"EDGE {current_version()} is up to date.")
        else:
            say(f"A newer EDGE is available ({_short(info['installed'])} → {_short(info['newest'])}). Update with:  edge update")
        return {**info, "ok": "error" not in info}
    else:
        res = update_installed(run, say=say, branch=branch)
    if res.get("ok") and res.get("updated"):
        say("")
        for line in AFTER_UPDATE:
            say(line)
    return res
