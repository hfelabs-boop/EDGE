"""Starting EDGE without a terminal: default workspace, desktop shortcuts, guided questions.

* ``edge`` (no arguments) opens the builder on ``~/EDGE Experiments`` (created on first use).
* ``edge desktop-shortcut`` puts an "EDGE" icon on the desktop / in the app menu.
* ``edge wizard`` asks the design-wizard questions in the terminal.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path
from typing import Any, Callable

WELCOME = """# Your EDGE experiments

This folder is where EDGE keeps your experiments. Each experiment is a `.yaml` file
(plus its pictures, sounds and trial lists); the data from each session goes into a
`data/` folder next to it.

* Double-click the EDGE icon (or type `edge`) to open the builder here.
* Back up this folder like any other documents folder.
"""


def default_workspace() -> Path:
    env = os.environ.get("EDGE_HOME")
    if env:
        return Path(env).expanduser()
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "EDGE Experiments"


def ensure_workspace(path: Path | None = None) -> Path:
    ws = Path(path) if path else default_workspace()
    first = not ws.exists()
    ws.mkdir(parents=True, exist_ok=True)
    if first or not (ws / "README.md").exists():
        (ws / "README.md").write_text(WELCOME, encoding="utf-8")
    return ws


def launch(directory: str | None = None, port: int = 8765, open_browser: bool = True) -> int:
    from .builder.server import serve
    ws = ensure_workspace(Path(directory) if directory else None)
    serve(ws, port=port, open_browser=open_browser)
    return 0


# ---------------------------------------------------------------- desktop shortcuts
def edge_command() -> list[str]:
    """How to start EDGE again from here (the stand-alone app has no `python -m`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "edge"]


def desktop_shortcut(platform: str | None = None, desktop: Path | None = None, workspace: Path | None = None) -> list[Path]:
    """Create a launcher icon. Returns the files written."""
    plat = platform or sys.platform
    ws = workspace or default_workspace()
    cmd = edge_command() + ["start", str(ws)]
    home = Path.home()
    written: list[Path] = []
    if plat.startswith("linux"):
        entry = "\n".join([
            "[Desktop Entry]", "Type=Application", "Name=EDGE", "Comment=Build and run experiments",
            "Exec=" + " ".join(_desktop_quote(c) for c in cmd), "Terminal=false",
            "Categories=Education;Science;", "Icon=applications-science", ""])
        targets = [desktop or home / "Desktop", home / ".local" / "share" / "applications"] if desktop is None \
            else [desktop]
        for d in targets:
            if d.parent.exists() or d.exists():
                d.mkdir(parents=True, exist_ok=True)
                f = d / "edge.desktop"
                f.write_text(entry, encoding="utf-8")
                f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                written.append(f)
    elif plat == "darwin":
        d = desktop or home / "Desktop"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "EDGE.command"
        f.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(c) for c in cmd) + "\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(f)
    elif plat.startswith("win"):
        d = desktop or home / "Desktop"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "EDGE.bat"
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pyw if pyw.exists() else sys.executable)
        args = f'"{sys.executable}" start' if getattr(sys, "frozen", False) else f'"{exe}" -m edge start'
        f.write_text(f'@echo off\r\nstart "" {args} "{ws}"\r\n', encoding="utf-8")
        written.append(f)
    else:
        raise RuntimeError(f"don't know how to make a shortcut on '{plat}'")
    return written


def _desktop_quote(arg: str) -> str:
    """Quote an Exec argument the way the freedesktop Desktop Entry spec requires."""
    if not any(ch in arg for ch in ' \t"\'\\$`<>|&;*?#()'):
        return arg
    return '"' + "".join("\\" + ch if ch in '"`$\\' else ch for ch in arg) + '"'


# ---------------------------------------------------------------- terminal wizard
def ask_wizard(ask: Callable[[str, str], str] | None = None) -> dict[str, Any]:
    """Ask the design questions in the terminal and return wizard answers."""
    def default_ask(q: str, default: str) -> str:
        r = input(f"{q} [{default}]: ").strip()
        return r or default
    ask = ask or default_ask
    a: dict[str, Any] = {}
    a["name"] = ask("Name of the experiment", "my_experiment")
    kind = ask("What do participants see or hear? (word / picture / sound / shape)", "word")
    rkind = ask("How do they respond? (keys / mouse / rating / none)", "keys")
    items = []
    print("List the stimuli, one per line as: stimulus, correct key, condition  (empty line to finish)")
    while True:
        line = ask("  stimulus", "")
        if not line:
            break
        parts = [p.strip() for p in line.split(",")]
        items.append({"stimulus": parts[0], "correct": parts[1] if len(parts) > 1 else "",
                      "condition": parts[2] if len(parts) > 2 else ""})
    a["stimulus"] = {"kind": kind, "items": items or None}
    a["response"] = {"kind": rkind}
    if rkind == "keys":
        keys = ask("Response keys, separated by spaces (empty = the correct keys you gave)", "")
        if keys:
            a["response"]["keys"] = keys.split()
    a["timing"] = {"fixation": ask("Fixation cross before each stimulus, seconds (0 = none)", "0.5"),
                   "stimulus_duration": ask("Show the stimulus for how many seconds? (empty = until response)", "") or None,
                   "response_deadline": ask("Response deadline, seconds (empty = wait forever)", "2") or None}
    a["feedback"] = ask("Show correct / wrong feedback? (y/n)", "n").lower().startswith("y")
    a["practice"] = {"mode": ask("Practice block? (none / once / until)", "none")}
    if a["practice"]["mode"] == "until":
        a["practice"]["criterion"] = float(ask("Accuracy needed to pass (0-1)", "0.8"))
        a["practice"]["max_rounds"] = int(ask("At most how many practice rounds", "3"))
    a["blocks"] = {"count": int(ask("Number of blocks", "1")),
                   "repeats": int(ask("How many times each stimulus appears per block", "1"))}
    return a


def write_wizard_experiment(answers: dict[str, Any], directory: Path) -> tuple[Path, dict[str, Any]]:
    from .storage import save_document
    from .wizard import build_experiment, estimate
    doc = build_experiment(answers)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['name']}.yaml"
    n = 2
    while path.exists():
        path = directory / f"{doc['name']}_{n}.yaml"
        n += 1
    save_document(path, doc, label="wizard")
    return path, estimate(doc, directory)


def load_answers(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
