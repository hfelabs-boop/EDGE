"""Regression tests for group E of the usability audit: install, update, packaging, docs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

import edge
from edge import updater

ROOT = Path(__file__).resolve().parent.parent
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
HAVE_SH = os.name != "nt" and Path("/bin/sh").exists()


def sh(cwd, *cmd):
    r = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def repos(tmp_path):
    """A bare 'remote', a developer copy that pushes to it, and the user's clone."""
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(work))
    (work / "pyproject.toml").write_text("[project]\nname='x'\n")
    (work / "a.txt").write_text("one\ntwo\nthree\n")
    sh(work, *GIT, "add", "-A")
    sh(work, *GIT, "commit", "-q", "-m", "first")
    sh(work, "git", "push", "-q", "origin", "main")
    clone = tmp_path / "clone"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(clone))

    def upstream(name, text, msg):
        (work / name).write_text(text)
        sh(work, *GIT, "add", "-A")
        sh(work, *GIT, "commit", "-q", "-m", msg)
        sh(work, "git", "push", "-q", "origin", "main")
    return clone, upstream


def no_pip(calls):
    def run(cmd, cwd=None):
        if cmd[:3] == [sys.executable, "-m", "pip"]:
            calls.append(cmd)
            return 0, ""
        return updater.run_cmd(cmd, cwd)
    return run


# ============================================================================ install#0: irm … | iex
def test_windows_installer_works_when_piped_into_iex():
    ps1 = (ROOT / "install" / "install_edge.ps1").read_text(encoding="utf-8")
    # Split-Path on $MyInvocation.MyCommand.Path (null under iex) was a binding error that ended the script
    assert "Split-Path -Parent $MyInvocation" not in ps1
    # "exit" inside iex closes the researcher's PowerShell window: only a script run from a file exits
    exits = [line.strip() for line in ps1.splitlines() if re.search(r"\bexit\b", line) and not line.lstrip().startswith("#")]
    assert exits == ["if ($failed -and $scriptFile) { exit 1 }"]
    pwsh = os.environ.get("EDGE_TEST_PWSH") or shutil.which("pwsh")
    if not pwsh:
        return
    r = subprocess.run([pwsh, "-NoProfile", "-Command",
                        f"Get-Content -Raw '{ROOT / 'install' / 'install_edge.ps1'}' | Invoke-Expression; Write-Host still-open"],
                       capture_output=True, text=True, timeout=120, env={**os.environ, "PATH": "/nonexistent"})
    assert "Cannot bind argument" not in r.stdout + r.stderr and "still-open" in r.stdout


# ============================================================================ install#1, #5: installed copies
def fake_installed(monkeypatch, commit, newest, *, url="file:///srv/edge.git", pip_ok=True):
    """An EDGE installed by pip from git at `commit`; the repository's newest commit is `newest`."""
    state = {"commit": commit}
    monkeypatch.setattr(edge, "installed_source", lambda running=True: {
        "url": url, "vcs": "git", "commit": state["commit"], "revision": None, "editable": False})
    calls = []

    def run(cmd, cwd=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "ls-remote"]:
            return 0, f"{newest}\tHEAD"
        if "--force-reinstall" in cmd and pip_ok:
            state["commit"] = newest
        return (0, "") if pip_ok else (1, "ERROR: something went wrong")
    return calls, run


def test_installed_copy_installs_the_new_commit_even_with_the_same_version_number(monkeypatch):
    old, new = "a" * 40, "b" * 40
    calls, run = fake_installed(monkeypatch, old, new)
    out = []
    r = updater.update_installed(run, say=out.append)
    assert r["ok"] and r["updated"]
    pip = [c for c in calls if c[1:3] == ["-m", "pip"]]
    assert any("--force-reinstall" in c and "--no-deps" in c and c[-1] == "edge-experiments @ git+file:///srv/edge.git" for c in pip)
    assert any(c[-1] == "edge-experiments[all] @ git+file:///srv/edge.git" for c in pip)   # new dependencies too
    assert f"EDGE updated: {old[:7]} → {new[:7]}." in out


def test_installed_copy_that_is_newest_says_so_and_installs_nothing(monkeypatch):
    calls, run = fake_installed(monkeypatch, "c" * 40, "c" * 40)
    out = []
    r = updater.update_installed(run, say=out.append)
    assert r["ok"] and not r["updated"] and "already the newest version" in out[0]
    assert not [c for c in calls if c[1:3] == ["-m", "pip"]]
    # --check gives a real answer now
    calls, run = fake_installed(monkeypatch, "c" * 40, "d" * 40)
    out.clear()
    monkeypatch.setattr(updater, "find_checkout", lambda: None)
    r = updater.update(check_only=True, run=run, say=out.append)
    assert r["ok"] and "A newer EDGE is available (ccccccc → ddddddd)" in out[0]


def test_installed_copy_explains_unknown_branch_offline_and_missing_git(monkeypatch):
    monkeypatch.setattr(edge, "installed_source", lambda running=True: {
        "url": "file:///srv/edge.git", "vcs": "git", "commit": "a" * 40, "revision": None, "editable": False})
    out = []
    r = updater.update_installed(lambda cmd, cwd=None: (0, ""), say=out.append, branch="mian")
    assert not r["ok"] and "no branch called 'mian'" in out[0] and "Nothing was changed" in out[0]
    out.clear()
    r = updater.update_installed(lambda cmd, cwd=None: (128, "fatal: unable to access 'x': Could not resolve host"), say=out.append)
    assert not r["ok"] and "could not reach the repository" in out[0]
    out.clear()
    r = updater.update_installed(lambda cmd, cwd=None: (127, "git: command not found"), say=out.append)
    assert not r["ok"] and "git is not installed" in out[0]


# ============================================================================ install#4: --stash conflict
def test_stash_conflict_leaves_a_clean_updated_folder_and_keeps_the_changes(repos):
    clone, upstream = repos
    (clone / "a.txt").write_text("mine\ntwo\nthree\n")
    upstream("a.txt", "theirs\ntwo\nthree\n", "change a")
    out = []
    r = updater.update(root=clone, stash=True, run=no_pip([]), say=out.append)
    assert not r["ok"] and r["updated"] and r["stash_conflict"] and r["conflicts"] == ["a.txt"]
    assert (clone / "a.txt").read_text() == "theirs\ntwo\nthree\n"            # the new version, no <<<<<<< markers
    assert sh(clone, "git", "status", "--porcelain", "--untracked-files=no") == ""
    assert "mine" in sh(clone, "git", "stash", "show", "-p")                  # the user's change is kept
    text = "\n".join(out)
    assert "a.txt" in text and "git stash pop" in text and "up to date" not in text


# ============================================================================ install#5: say what went wrong
def test_update_failures_are_always_explained(repos, tmp_path):
    clone, upstream = repos
    out = []
    r = updater.update(root=clone, branch="mian", run=no_pip([]), say=out.append)
    assert not r["ok"] and out and "no branch called 'mian'" in out[0] and "Nothing was changed" in out[0]
    sh(clone, "git", "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    out.clear()
    r = updater.update(root=clone, run=no_pip([]), say=out.append)
    assert not r["ok"] and out and "could not reach the repository" in out[0]


def test_cli_update_prints_each_reason_once(repos, monkeypatch, capsys):
    from edge.cli import main
    clone, upstream = repos
    monkeypatch.setattr(updater, "find_checkout", lambda: clone)
    assert main(["update", "--branch", "mian"]) == 1
    text = capsys.readouterr().out
    assert text.count("no branch called 'mian'") == 1 and "Update failed" not in text


# ============================================================================ install#6: commit, then update
def test_update_after_committing_own_changes(repos):
    clone, upstream = repos
    (clone / "a.txt").write_text("one\ntwo\nthree\nmine\n")
    sh(clone, *GIT, "commit", "-qam", "my changes")
    upstream("b.txt", "new\n", "add b")
    out = []
    r = updater.update(root=clone, run=no_pip([]), say=out.append)
    assert r["ok"] and r["updated"] and (clone / "b.txt").exists() and "mine" in (clone / "a.txt").read_text()


def test_conflicting_own_commits_change_nothing_and_say_what_to_do(repos):
    clone, upstream = repos
    (clone / "a.txt").write_text("mine\ntwo\nthree\n")
    sh(clone, *GIT, "commit", "-qam", "my changes")
    head = sh(clone, "git", "rev-parse", "HEAD")
    upstream("a.txt", "theirs\ntwo\nthree\n", "change a")
    out = []
    r = updater.update(root=clone, run=no_pip([]), say=out.append)
    assert not r["ok"] and r["conflicts"] == ["a.txt"]
    assert sh(clone, "git", "rev-parse", "HEAD") == head and (clone / "a.txt").read_text() == "mine\ntwo\nthree\n"
    assert sh(clone, "git", "status", "--porcelain") == ""
    assert any("git branch my-changes" in line for line in out)


# ============================================================================ install#7: never take over ~/.edge
def test_reinstall_only_into_the_python_that_has_this_clone(repos, monkeypatch):
    clone, upstream = repos
    src = {"url": clone.resolve().as_uri(), "vcs": None, "commit": None, "revision": None, "editable": True}
    monkeypatch.setattr(edge, "installed_source", lambda running=True: src)
    assert updater.install_kind(clone) == "editable"
    src["editable"] = False
    assert updater.install_kind(clone) == "copy"
    src.update(url="git+https://github.com/hfelabs-boop/EDGE.git", vcs="git")     # e.g. the installer's ~/.edge
    assert updater.install_kind(clone) == ""
    upstream("b.txt", "new\n", "add b")
    calls, out = [], []
    r = updater.update(root=clone, run=no_pip(calls), say=out.append)
    assert r["ok"] and r["updated"] and calls == [] and any("left as it is" in line for line in out)


FAKE_PY = r"""#!/bin/sh
case "$*" in
  *"edge.__file__"*) exit "$RUNS_CLONE";;
  *"-m edge update --help"*) exit 0;;
  *"-m edge update"*) echo "$NAME ran edge update in $(pwd)"; exit 0;;
  *"import edge"*) exit 0;;
esac
exit 1
"""


def _fake_python(path: Path, name: str, runs_clone: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FAKE_PY.replace("$NAME", name).replace('"$RUNS_CLONE"', str(runs_clone)))
    path.chmod(0o755)


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_update_sh_uses_the_python_that_has_this_clone(tmp_path):
    clone = tmp_path / "EDGE"
    (clone / ".git").mkdir(parents=True)
    (clone / "pyproject.toml").write_text('[project]\nname = "edge-experiments"\n')
    shutil.copy(ROOT / "update.sh", clone / "update.sh")
    home = tmp_path / "home"
    _fake_python(home / ".edge" / "venv" / "bin" / "python", "installer-python", 1)   # EDGE from elsewhere
    _fake_python(tmp_path / "bin" / "python3", "clone-python", 0)                     # has this clone (-e)
    env = {"HOME": str(home), "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"}
    r = subprocess.run(["/bin/sh", str(clone / "update.sh")], capture_output=True, text=True, env=env, timeout=60,
                       cwd=str(tmp_path))
    assert r.stdout.strip() == f"clone-python ran edge update in {clone}", r.stdout + r.stderr


# ============================================================================ install#9, #16, #17: the sh installer
FAKE_SYS_PY = r"""#!/bin/sh
echo "$0 $*" >> "$FAKE_LOG"
here="$(dirname "$0")"
case "$1" in
  -c) case "$2" in
        *version_info*) exit 0;;
        *"import edge"*) [ -f "$here/../installed" ] && exit 0; exit 1;;
      esac; exit 0;;
  -m) case "$2" in
        venv) mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0;;
        pip) case "$*" in *"--upgrade pip"*) exit 0;; esac
             if [ -n "$FAKE_PIP_FAIL" ]; then echo "ERROR: pip could not do it (fake)" >&2; exit 1; fi
             touch "$here/../installed"; exit 0;;
      esac;;
esac
exit 0
"""


def run_installer(tmp_path, script: Path, *, piped=False, cwd=None, path_extra="/usr/bin:/bin", **env):
    fake = tmp_path / "fakebin"
    fake.mkdir(exist_ok=True)
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3", "python"):
        (fake / name).write_text(FAKE_SYS_PY)
        (fake / name).chmod(0o755)
    log = tmp_path / "calls.log"
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    full_env = {"HOME": str(home), "PATH": f"{fake}:{path_extra}", "FAKE_LOG": str(log), "SHELL": "/bin/zsh", **env}
    if piped:
        # as in `curl … | sh`: $0 is then just "sh"
        r = subprocess.run(["sh"], input=script.read_text(), capture_output=True, text=True, env=full_env,
                           cwd=str(cwd or tmp_path), timeout=60)
    else:
        r = subprocess.run(["/bin/sh", str(script)], capture_output=True, text=True, env=full_env,
                           cwd=str(cwd or tmp_path), timeout=60)
    pips = [line for line in (log.read_text().splitlines() if log.exists() else []) if " -m pip install" in line
            and "--upgrade pip" not in line]
    return r, pips, home


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_piped_installer_ignores_the_project_it_is_run_in(tmp_path):
    lab = tmp_path / "mylab"
    (lab / "notebooks").mkdir(parents=True)
    (lab / "pyproject.toml").write_text('[project]\nname = "mylab-analysis"\nversion = "1.0"\n')
    r, pips, _ = run_installer(tmp_path, ROOT / "install" / "install_edge.sh", piped=True, cwd=lab / "notebooks")
    assert r.returncode == 0, r.stdout + r.stderr
    assert pips and pips[0].endswith("edge-experiments[all] @ git+https://github.com/hfelabs-boop/edge.git")
    assert not any("mylab" in p for p in pips)


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_installer_from_a_downloaded_copy_installs_that_copy(tmp_path):
    copy = tmp_path / "EDGE copy"
    (copy / "install").mkdir(parents=True)
    shutil.copy(ROOT / "install" / "install_edge.sh", copy / "install")
    shutil.copy(ROOT / "pyproject.toml", copy)
    r, pips, _ = run_installer(tmp_path, copy / "install" / "install_edge.sh")
    assert r.returncode == 0 and pips[0].endswith(f"{copy}[all]")


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_installer_shows_its_own_message_when_pip_fails(tmp_path):
    r, pips, _ = run_installer(tmp_path, ROOT / "install" / "install_edge.sh", FAKE_PIP_FAIL="1",
                               EDGE_SOURCE="git+https://example.invalid/edge.git")
    assert r.returncode == 1 and "Installing EDGE did not work" in r.stdout
    assert "ERROR: pip could not do it" in r.stderr                       # pip's own reason is not hidden
    assert len(pips) == 1 and not any("edge.git[all]" in p for p in pips)  # no malformed '<url>[all]' retry


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_installer_says_how_to_get_git(tmp_path):
    utils = tmp_path / "utils"
    utils.mkdir()
    for tool in ("dirname", "basename", "grep"):
        found = shutil.which(tool)
        if found:
            (utils / tool).symlink_to(found)
    r, pips, _ = run_installer(tmp_path, ROOT / "install" / "install_edge.sh", path_extra=str(utils),
                               EDGE_SOURCE="git+https://github.com/hfelabs-boop/EDGE.git")
    assert r.returncode == 1 and "git, which is not installed" in r.stdout and "xcode-select --install" in r.stdout
    assert pips == []


@pytest.mark.skipif(not HAVE_SH, reason="needs /bin/sh")
def test_installer_gives_a_working_command_when_local_bin_is_not_on_path(tmp_path):
    r, pips, home = run_installer(tmp_path, ROOT / "install" / "install_edge.sh",
                                  EDGE_SOURCE="git+https://github.com/hfelabs-boop/EDGE.git")
    assert r.returncode == 0, r.stdout + r.stderr
    full = f"{home}/.edge/venv/bin/edge"
    assert f"""echo 'export PATH="$HOME/.local/bin:$PATH"' >> "{home}/.zshrc\"""" in r.stdout
    assert f"or type:  {full}" in r.stdout and f"run:  {full} doctor" in r.stdout
    # run again (EDGE now installed): EDGE itself is reinstalled, whatever its version number (install#1)
    r, pips, _ = run_installer(tmp_path, ROOT / "install" / "install_edge.sh",
                               EDGE_SOURCE="git+https://github.com/hfelabs-boop/EDGE.git")
    assert r.returncode == 0 and any("--force-reinstall --no-deps edge-experiments @ git+https" in p for p in pips)


# ============================================================================ install#2: mcp 2.x
def test_mcp_is_pinned_below_2_in_every_extra():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    reqs = re.findall(r'"mcp[<>=!~][^"]*"', text)
    assert len(reqs) == 3 and all("<2" in r for r in reqs)        # the mcp, all and dev extras


def test_mcp_command_explains_a_wrong_mcp_version(monkeypatch, capsys, tmp_path):
    from importlib import metadata
    from edge.cli import main
    monkeypatch.setitem(sys.modules, "edge.mcp_server", None)    # importing it fails, as with mcp 2.x
    monkeypatch.setattr(metadata, "version", lambda name: "2.3.0" if name == "mcp" else "1")
    assert main(["mcp", "--root", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "needs version 1 of the 'mcp' package, but version 2.3.0 is installed" in err and 'mcp>=1.2,<2' in err

    def missing(name):
        raise metadata.PackageNotFoundError(name)
    monkeypatch.setattr(metadata, "version", missing)
    assert main(["mcp", "--root", str(tmp_path)]) == 2
    assert "which is not installed" in capsys.readouterr().err


# ============================================================================ install#3: docs in the wheel
def test_wheel_ships_the_guides_and_edge_help_finds_them(tmp_path):
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
    src = tmp_path / "src"                      # a copy, so the build doesn't write into the checkout
    src.mkdir()
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "LICENSE"):
        if (ROOT / name).exists():
            shutil.copy(ROOT / name, src / name)
    shutil.copytree(ROOT / "edge", src / "edge", ignore=shutil.ignore_patterns("__pycache__", "docs"))
    shutil.copytree(ROOT / "docs", src / "docs")
    for isolation in (["--no-build-isolation"], []):   # offline first; else pip fetches setuptools itself
        r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", *isolation, "-q",
                            "-w", str(tmp_path / "dist"), str(src)], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            break
    else:
        pytest.skip("could not build a wheel here: " + r.stderr[-300:])
    whl = next((tmp_path / "dist").glob("*.whl"))
    names = zipfile.ZipFile(whl).namelist()
    for guide in ("GETTING_STARTED.md", "README.md", "FAQ.md", "reference/components.md", "builder.png"):
        assert f"edge/docs/{guide}" in names
    site = tmp_path / "site"
    zipfile.ZipFile(whl).extractall(site)
    probe = ("import sys; from edge import help; t = [x['id'] for x in help.topics()]; "
             "print(len(t)); print(help.read_topic('GETTING_STARTED').splitlines()[0])")
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
                       env={**os.environ, "PYTHONPATH": str(site)})
    assert r.returncode == 0, r.stderr
    count, first = r.stdout.splitlines()
    assert int(count) >= 15 and first == "# Getting started"


# ============================================================================ install#10: the stand-alone app
def test_main_module_runs_as_a_plain_script():
    # PyInstaller runs edge/__main__.py as a script, outside the package: a relative import fails there
    r = subprocess.run([sys.executable, str(ROOT / "edge" / "__main__.py"), "--version"], capture_output=True, text=True,
                       timeout=60, env={**os.environ, "PYTHONPATH": str(ROOT)}, cwd=str(ROOT / "tests"))
    assert r.returncode == 0 and r.stdout.startswith("edge "), r.stderr


def test_app_recipe_bundles_every_data_folder_of_the_package():
    spec = (ROOT / "install" / "edge.spec").read_text(encoding="utf-8")
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = re.search(r'^"edge" = \[(.*?)\]', text, re.M).group(1)
    for pattern in re.findall(r'"([^"]+)"', data):
        assert f'"{pattern}"' in spec, pattern
    assert '"builder/static/*"' in spec and "edge/docs" in spec


# ============================================================================ install#11: which EDGE code
def test_version_names_the_commit(tmp_path, capsys):
    from edge import _git_commit, build_version
    top = tmp_path / "repo"
    sh(tmp_path, "git", "init", "-q", "-b", "main", str(top))
    (top / "f").write_text("x")
    sh(top, *GIT, "add", "-A")
    sh(top, *GIT, "commit", "-q", "-m", "x")
    head = sh(top, "git", "rev-parse", "HEAD").strip()
    assert _git_commit(top) == head
    sh(top, "git", "pack-refs", "--all")                                  # refs only in packed-refs
    assert _git_commit(top) == head
    sh(top, "git", "worktree", "add", "-q", str(tmp_path / "wt"))         # .git is a file in a worktree
    assert _git_commit(tmp_path / "wt") == head
    sh(top, "git", "checkout", "-q", "--detach")
    assert _git_commit(top) == head
    assert _git_commit(tmp_path) is None
    if (ROOT / ".git").exists():
        real = sh(ROOT, "git", "rev-parse", "HEAD").strip()
        assert edge.__version__ == build_version() == f"{edge.__release__}+g{real[:7]}"
        from edge.cli import main
        with pytest.raises(SystemExit):
            main(["--version"])
        assert capsys.readouterr().out.strip() == f"edge {edge.__version__}"
    assert re.search(r'^version = "' + re.escape(edge.__release__) + '"', (ROOT / "pyproject.toml").read_text(), re.M)


def test_locks_and_sessions_record_the_build():
    from edge import launcher, reproduce
    assert reproduce.environment()["edge"] == edge.__version__          # what lock / verify compare
    assert launcher._version() == edge.__release__                       # macOS bundle version: numbers only


# ============================================================================ data#21: edge.run from Python
def _tiny(tmp_path):
    p = tmp_path / "quick.yaml"
    p.write_text(yaml.safe_dump({"name": "quick", "routines": {"a": {"components": [
        {"id": "t", "type": "text", "text": "x", "duration": 0.1}]}}, "flow": ["a"]}))
    return p


def test_edge_run_accepts_a_participant_id(tmp_path):
    p = _tiny(tmp_path)
    s = edge.run(p, participant="012", dry_run=True, data_dir=str(tmp_path / "d1"), log=lambda *a: None)
    meta = json.loads((Path(s["data_dir"]) / "session.json").read_text())
    assert meta["participant"]["participant"] == "012"
    assert meta["environment"]["edge"] == edge.__version__              # the session names the exact EDGE build (install#11)
    s = edge.run(p, participant={"participant": 9, "session": 2, "age": 30}, dry_run=True,
                 data_dir=str(tmp_path / "d2"), log=lambda *a: None)
    meta = json.loads((Path(s["data_dir"]) / "session.json").read_text())["participant"]
    assert meta["participant"] == "9" and meta["session"] == "2" and meta["age"] == 30   # IDs as text, like the CLI
    with pytest.raises(TypeError, match="participant must be a participant ID such as '012'"):
        edge.run(p, participant=["012"], dry_run=True)


# ============================================================================ docs#13: anchors on GitHub and in the app
def _github_slug(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _app_slug(s: str) -> str:                     # edge.help.slug and the builder's slugify
    s = re.sub(r"[`*_]", "", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _doc_files():
    return [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "docs" / "reference").glob("*.md"))]


def _headings(path: Path) -> list[str]:
    out, fence = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
        elif not fence and re.match(r"#{1,6} ", line):
            out.append(line.lstrip("#").strip())
    return out


def test_every_doc_anchor_works_on_github_and_in_the_app():
    bad = []
    for f in _doc_files():
        for target, anchor in re.findall(r"\]\(([^)#\s]*\.md)?#([^)\s]+)\)", f.read_text(encoding="utf-8")):
            dest = (f.parent / target) if target else f
            if not dest.exists():
                continue
            heads = _headings(dest)
            github = {_github_slug(h) for h in heads}
            app = {_app_slug(h) for h in heads}
            in_app = anchor in app or any(_app_slug(anchor) in a for a in app)   # the builder's fallback
            if anchor not in github or not in_app:
                bad.append(f"{f.name}: {target}#{anchor}")
    assert not bad, bad


# ============================================================================ docs#22, wizard#15: docs match the product
def test_docs_list_every_mcp_tool(tmp_path):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio
    from edge.mcp_server import create_server
    names = {t.name for t in asyncio.run(create_server(str(tmp_path)).list_tools())}
    mcp_md = (ROOT / "docs" / "MCP.md").read_text(encoding="utf-8")
    table = mcp_md[mcp_md.index("## Tools"):mcp_md.index("**Resources:**")]
    documented = set(re.findall(r"`([a-z_]+)`", table))
    assert names - documented == set(), "add to docs/MCP.md: " + ", ".join(sorted(names - documented))
    assert f"The {len(names)} tools" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_architecture_lists_every_module():
    arch = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    pkg = ROOT / "edge"
    names = [p.name for p in pkg.glob("*.py") if p.stem not in ("__init__", "__main__")]
    names += [p.name + "/" for p in pkg.iterdir() if p.is_dir() and not p.name.startswith("__")]
    missing = [n for n in names if not re.search(r"^\s+" + re.escape(n) + r"\s", arch, re.M)]
    assert not missing, "describe in docs/ARCHITECTURE.md: " + ", ".join(sorted(missing))


def test_component_table_lists_every_component_type():
    from edge.components import component_registry
    fmt = (ROOT / "docs" / "EXPERIMENT_FORMAT.md").read_text(encoding="utf-8")
    table = fmt[fmt.index("### Component types"):]
    table = table[:table.index("\n\n", table.index("| category"))]
    missing = [t for t in component_registry() if f"`{t}`" not in table]
    assert not missing, missing


def test_docs_describe_the_terminal_wizard_and_tutorials_as_they_are():
    from edge import help
    gs = (ROOT / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
    assert "asks the same questions" not in gs and "It does not ask about devices" in gs
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"edge wizard .*tested experiment", readme)
    words = {8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
    n = len(help.tutorials())
    line = next(l for l in (ROOT / "docs" / "README.md").read_text(encoding="utf-8").splitlines() if "(TUTORIALS.md)" in l)
    assert words.get(n, str(n)) in line
