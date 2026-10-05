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


# ---------------------------------------------------------------- icon, desktop folder
def edge_home() -> Path:
    """EDGE's own small folder (icons, launch log): ~/.edge, or $EDGE_STATE."""
    return Path(os.environ.get("EDGE_STATE") or Path.home() / ".edge")


def assets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))      # stand-alone app or source
    for cand in (base / "edge" / "assets", Path(__file__).parent / "assets"):
        if cand.is_dir():
            return cand
    return Path(__file__).parent / "assets"


def install_icons(home: Path | None = None) -> dict[str, Path]:
    """Copy the icon files to a permanent place (shortcuts must keep working if the package moves)."""
    import shutil
    dest = (home or edge_home()) / "icons"
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name in ("edge.ico", "edge.icns", "edge-256.png", "edge-icon.svg"):
        src = assets_dir() / name
        if src.exists():
            shutil.copyfile(src, dest / name)
            out[name] = dest / name
    return out


def desktop_dir(plat: str | None = None, home: Path | None = None) -> Path:
    """The real Desktop folder: redirected to OneDrive on many Windows PCs, translated on Linux."""
    plat = plat or sys.platform
    home = home or Path.home()
    if plat.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                p = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
            if p.is_dir():
                return p
        except Exception:
            pass
        for cand in (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial")):
            if cand and (Path(cand) / "Desktop").is_dir():
                return Path(cand) / "Desktop"
    elif plat.startswith("linux"):
        try:
            for line in (home / ".config" / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
                if line.startswith("XDG_DESKTOP_DIR="):
                    p = Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home)))
                    if p.is_dir():
                        return p
        except OSError:
            pass
    return home / "Desktop"


def show_message(title: str, text: str, error: bool = True) -> None:
    """A native message box (shortcuts have no console to print to). Never raises."""
    import subprocess
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            lit = lambda v: json.dumps(v, ensure_ascii=False)
            subprocess.run(["osascript", "-e", f'display dialog {lit(text)} with title {lit(title)} buttons {{"OK"}} '
                            f'default button "OK" with icon {"stop" if error else "note"}'], timeout=600)
        else:
            for cmd in (["zenity", "--error" if error else "--info", "--title", title, "--text", text, "--no-markup"],
                        ["kdialog", "--error" if error else "--msgbox", text, "--title", title],
                        ["notify-send", title, text]):
                if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                    subprocess.run(cmd, timeout=600)
                    return
    except Exception:
        pass


def launch_from_shortcut(directory: str | None = None, port: int = 8765) -> int:
    """What the desktop icon runs. Like ``edge start``, but with no console to show problems in: output
    goes to ~/.edge/launch.log, and anything that stops EDGE from opening is shown in a message box."""
    from datetime import datetime
    home = edge_home()
    log_file = home / "launch.log"
    fh = None
    try:
        home.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > 200_000:
            log_file.replace(home / "launch.old.log")
        fh = open(log_file, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = fh
        if sys.stderr is None:
            sys.stderr = fh
        from . import __version__
        print(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}  EDGE {__version__}  {sys.executable}", file=fh)
    except OSError:
        pass
    try:
        from .builder.server import serve
        ws = ensure_workspace(Path(directory) if directory else None)
        serve(ws, port=port, open_browser=True, notify=lambda t, m: show_message(t, m, error=False))
        return 0
    except KeyboardInterrupt:
        return 0
    except BaseException as e:
        import traceback
        if fh:
            traceback.print_exc(file=fh)
        show_message("EDGE could not start",
                     f"{type(e).__name__}: {e}\n\nMore detail: {log_file}\n\n"
                     "To check this computer, open a terminal and run:  edge doctor\n"
                     "To reinstall, run the EDGE installer again.")
        return 1


# ---------------------------------------------------------------- desktop shortcuts
def edge_command() -> list[str]:
    """How to start EDGE again from here (the stand-alone app has no `python -m`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "edge"]


def _lnk_script(lnk: Path, target: str, args: str, workdir: str, icon: Path, description: str) -> str:
    q = lambda v: str(v).replace("'", "''")
    return ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='%s';"
            "$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Description='%s';$s.WindowStyle=7;$s.Save()"
            % (q(lnk), q(target), q(args), q(workdir), q(icon), q(description)))


def desktop_shortcut(platform: str | None = None, desktop: Path | None = None, workspace: Path | None = None,
                     run: Callable[..., Any] | None = None, home: Path | None = None) -> list[Path]:
    """Create the EDGE icon (a brain with a signal trace). Returns the files written."""
    import plistlib
    import shutil
    import subprocess
    plat = platform or sys.platform
    ws = workspace or default_workspace()
    user_home = home or Path.home()
    cmd = edge_command() + ["start", "--from-shortcut", str(ws)]
    icons = install_icons()
    written: list[Path] = []
    if plat.startswith("linux"):
        png = icons.get("edge-256.png") or assets_dir() / "edge-256.png"
        entry = "\n".join([
            "[Desktop Entry]", "Type=Application", "Name=EDGE", "Comment=Build and run experiments",
            "Exec=" + " ".join(_desktop_quote(c) for c in cmd), "Terminal=false", f"Icon={png}",
            "StartupWMClass=EDGE", "Categories=Education;Science;", ""])
        targets = [desktop or desktop_dir(plat, user_home), user_home / ".local" / "share" / "applications"] \
            if desktop is None else [desktop]
        for d in targets:
            d.mkdir(parents=True, exist_ok=True)
            f = d / "edge.desktop"
            f.write_text(entry, encoding="utf-8")
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            try:   # GNOME/Nautilus only runs desktop files marked as trusted
                subprocess.run(["gio", "set", str(f), "metadata::trusted", "true"], capture_output=True, timeout=5)
            except Exception:
                pass
            written.append(f)
        theme = user_home / ".local" / "share" / "icons" / "hicolor"
        if desktop is None:
            for n in (16, 32, 48, 64, 128, 256, 512):
                src = assets_dir() / f"edge-{n}.png"
                if src.exists():
                    (theme / f"{n}x{n}" / "apps").mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, theme / f"{n}x{n}" / "apps" / "edge.png")
    elif plat == "darwin":
        bundle_dirs = [desktop or desktop_dir(plat, user_home)]
        if desktop is None:
            bundle_dirs.append(user_home / "Applications")
        for d in bundle_dirs:
            app = d / "EDGE.app"
            (app / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
            (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
            exe = app / "Contents" / "MacOS" / "EDGE"
            exe.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(c) for c in cmd) + "\n", encoding="utf-8")
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if icons.get("edge.icns"):
                shutil.copyfile(icons["edge.icns"], app / "Contents" / "Resources" / "edge.icns")
            (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleName": "EDGE", "CFBundleDisplayName": "EDGE", "CFBundleExecutable": "EDGE",
                "CFBundleIconFile": "edge", "CFBundleIdentifier": "org.edge.builder", "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": _version(), "LSApplicationCategoryType": "public.app-category.education",
                "NSHighResolutionCapable": True}))
            written.append(app)
        old = (desktop or desktop_dir(plat, user_home)) / "EDGE.command"
        if old.exists() and "edge" in old.read_text(errors="ignore"):
            old.unlink()          # the plain script from earlier versions: replaced by the app
    elif plat.startswith("win"):
        d = desktop or desktop_dir(plat, user_home)
        d.mkdir(parents=True, exist_ok=True)
        pyw = Path(sys.executable).with_name("pythonw.exe")
        if getattr(sys, "frozen", False):
            target, args = sys.executable, f'start --from-shortcut "{ws}"'
        else:
            target, args = str(pyw if pyw.exists() else sys.executable), f'-m edge start --from-shortcut "{ws}"'
        icon = icons.get("edge.ico") or assets_dir() / "edge.ico"
        lnks = [d / "EDGE.lnk"]
        appdata = os.environ.get("APPDATA")
        if desktop is None and appdata:
            lnks.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "EDGE.lnk")
        runner = run or subprocess.run
        for lnk in lnks:
            lnk.parent.mkdir(parents=True, exist_ok=True)
            script = _lnk_script(lnk, target, args, str(ws), icon, "EDGE: build and run experiments")
            try:
                r = runner(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=30)
                ok = getattr(r, "returncode", 1) == 0
            except Exception:
                ok = False
            if ok:
                written.append(lnk)
        if not written:     # PowerShell blocked: a plain launcher (no custom icon possible)
            f = d / "EDGE.bat"
            f.write_text(f'@echo off\r\nstart "" "{target}" {args}\r\n', encoding="utf-8")
            written.append(f)
        else:
            old = d / "EDGE.bat"
            if old.exists() and "-m edge start" in old.read_text(errors="ignore"):
                old.unlink()      # the plain launcher from earlier versions
    else:
        raise RuntimeError(f"don't know how to make a shortcut on '{plat}'")
    return written


def _version() -> str:
    from . import __version__
    return __version__


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
    from .survey_library import INSTRUMENTS
    qs = ask("Questionnaires, separated by spaces (" + " ".join(INSTRUMENTS) + "; empty = none)", "")
    a["questionnaires"] = qs.split()
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
    from .wizard import write_placeholders
    write_placeholders(doc, directory)
    return path, estimate(doc, directory)


def load_answers(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
