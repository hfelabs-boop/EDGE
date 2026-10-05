"""edge update: a clone is fast-forwarded without losing the user's own changes; installed copies use pip."""

import subprocess
import sys
from pathlib import Path

import pytest

from edge import updater

GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def sh(cwd, *cmd):
    r = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def repos(tmp_path):
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(work))
    (work / "pyproject.toml").write_text("[project]\nname='x'\n")
    (work / "a.txt").write_text("one\n")
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


def runner(calls):
    def run(cmd, cwd=None):
        if cmd[:3] == [sys.executable, "-m", "pip"]:       # never really install in tests
            calls.append(cmd)
            return 0, ""
        return updater.run_cmd(cmd, cwd)
    return run


def test_up_to_date_and_check(repos):
    clone, upstream = repos
    out, calls = [], []
    r = updater.update(root=clone, run=runner(calls), say=out.append)
    assert r["ok"] and not r["updated"] and "already the newest" in out[0] and calls == []
    upstream("b.txt", "new\n", "add b")
    out.clear()
    r = updater.update(check_only=True, root=clone, run=runner(calls), say=out.append)
    assert r["behind"] == 1 and "1 new change available on main" in out[0] and "add b" in out[1]
    assert not (clone / "b.txt").exists()                  # only looked


def test_update_applies_new_commits_and_reinstalls(repos):
    clone, upstream = repos
    upstream("b.txt", "new\n", "add b")
    upstream("c.txt", "newer\n", "add c")
    out, calls = [], []
    r = updater.update(root=clone, run=runner(calls), say=out.append)
    assert r["ok"] and r["updated"] and r["behind"] == 2
    assert (clone / "b.txt").exists() and (clone / "c.txt").exists()
    assert "2 new changes on main" in out[0] and any("add c" in line for line in out)
    assert calls and calls[0][-2:] == ["-e", ".[all]"]


def test_local_changes_are_never_overwritten(repos):
    clone, upstream = repos
    (clone / "a.txt").write_text("my edit\n")
    upstream("b.txt", "new\n", "add b")
    out = []
    r = updater.update(root=clone, run=runner([]), say=out.append)
    assert not r["ok"] and r["reason"] == "local changes"
    assert (clone / "a.txt").read_text() == "my edit\n" and not (clone / "b.txt").exists()
    assert any("edge update --stash" in line for line in out)
    # --stash: set aside, update, put back
    out.clear()
    r = updater.update(root=clone, stash=True, run=runner([]), say=out.append)
    assert r["ok"] and r["updated"] and (clone / "b.txt").exists()
    assert (clone / "a.txt").read_text() == "my edit\n" and "Your own changes were put back." in out


def test_stash_conflict_keeps_the_user_changes_safe(repos):
    clone, upstream = repos
    (clone / "a.txt").write_text("mine\n")
    upstream("a.txt", "theirs\n", "change a")
    out = []
    r = updater.update(root=clone, stash=True, run=runner([]), say=out.append)
    assert r["updated"] and r["stash_conflict"] and any("git stash list" in line for line in out)
    assert "mine" in sh(clone, "git", "stash", "show", "-p")


def test_diverged_copy_is_explained(repos):
    clone, upstream = repos
    (clone / "own.txt").write_text("x\n")
    sh(clone, *GIT, "add", "-A")
    sh(clone, *GIT, "commit", "-q", "-m", "own commit")
    upstream("b.txt", "new\n", "add b")
    out = []
    r = updater.update(root=clone, run=runner([]), say=out.append)
    assert not r["ok"] and "can't be fast-forwarded" in r["reason"] and not (clone / "b.txt").exists()


def test_no_connection_is_explained(tmp_path):
    work = tmp_path / "w"
    sh(tmp_path, "git", "init", "-q", "-b", "main", str(work))
    sh(work, "git", "remote", "add", "origin", str(tmp_path / "gone.git"))
    (work / "pyproject.toml").write_text("x")
    sh(work, *GIT, "add", "-A")
    sh(work, *GIT, "commit", "-q", "-m", "x")
    r = updater.update(check_only=True, root=work, say=lambda s: None)
    assert not r["ok"] and "could not reach the repository" in r["error"]


def test_installed_copies_use_pip_and_explain_missing_git():
    calls = []

    def run(cmd, cwd=None):
        calls.append(cmd)
        return 0, ""
    r = updater.update_installed(run, say=lambda s: None)
    assert r["ok"] and "edge-experiments[all] @ git+https://github.com/hfelabs-boop/EDGE.git" in calls[0][-1]

    def no_git(cmd, cwd=None):
        return 1, "ERROR: Cannot find command 'git' - do you have 'git' installed and in your PATH?"
    r = updater.update_installed(no_git, say=lambda s: None)
    assert not r["ok"] and "git is not installed" in r["reason"]
    assert updater.update(check_only=True, root=None, run=run, say=lambda s: None) is not None


def test_cli_and_scripts_exist():
    from edge.cli import main
    root = Path(__file__).resolve().parent.parent
    assert (root / "update.sh").read_text().startswith("#!/bin/sh") and "-m edge update" in (root / "update.sh").read_text()
    assert "-m edge update" in (root / "update.bat").read_text()
    assert main(["update", "--check"]) in (0, 1)
