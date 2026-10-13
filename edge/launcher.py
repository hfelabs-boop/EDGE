"""Starting EDGE without a terminal: default workspace, desktop shortcuts, guided questions.

* ``edge`` (no arguments) opens the builder on "EDGE Experiments" in your Documents folder (in your
  home folder if there is none), created on first use.
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


WORKSPACE_HELP = "'EDGE Experiments' in your Documents folder, or in your home folder if there is none"
EXPERIMENT_SUFFIXES = (".yaml", ".yml", ".json")


def default_workspace(plat: str | None = None, home: Path | None = None) -> Path:
    env = os.environ.get("EDGE_HOME")
    if env:
        return Path(env).expanduser()
    home = home or Path.home()
    preferred = (documents_dir(plat, home) or home) / "EDGE Experiments"
    if not preferred.is_dir():
        # the folder an earlier EDGE made stays in use: an update must never seem to lose experiments
        for old in (home / "Documents" / "EDGE Experiments", home / "EDGE Experiments"):
            if old.is_dir():
                return old
    return preferred


def ensure_workspace(path: Path | None = None) -> Path:
    ws = Path(path) if path else default_workspace()
    first = not ws.exists()
    ws.mkdir(parents=True, exist_ok=True)
    if first or not (ws / "README.md").exists():
        (ws / "README.md").write_text(WELCOME, encoding="utf-8")
    return ws


def workspace_for(directory: str | Path | None) -> tuple[Path | None, str | None]:
    """The folder to open for what was given, and the experiment's file name when it was an experiment
    file (``edge start study.yaml`` opens the folder it is in)."""
    if not directory:
        return None, None
    p = Path(directory).expanduser()
    if p.is_file():
        if p.suffix.lower() in EXPERIMENT_SUFFIXES:
            return p.parent, p.name
        raise NotADirectoryError(20, "this is a file, not a folder: give the folder your experiments are in", str(p))
    return p, None


def open_query(name: str | None) -> str:
    from urllib.parse import quote
    return f"?open={quote(name)}" if name else ""


def launch(directory: str | None = None, port: int = 8765, open_browser: bool = True) -> int:
    from .builder.server import serve
    folder, name = workspace_for(directory)
    ws = ensure_workspace(folder)
    if name:
        print(f"{name} is an experiment file: opening the folder it is in, {ws}")
    serve(ws, port=port, open_browser=open_browser, path_query=open_query(name))
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
        p = _xdg_dir("XDG_DESKTOP_DIR", home)
        if p:
            return p
    return home / "Desktop"


def _xdg_dir(key: str, home: Path) -> Path | None:
    """A folder named in ~/.config/user-dirs.dirs (translated: ~/Bureau, ~/Dokumente …), if it exists."""
    try:
        for line in (home / ".config" / "user-dirs.dirs").read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                p = Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home)))
                if p.is_dir() and p != home:        # "$HOME" itself means the folder is switched off
                    return p
    except OSError:
        pass
    return None


def documents_dir(plat: str | None = None, home: Path | None = None) -> Path | None:
    """The real Documents folder: redirected to OneDrive on many Windows PCs, translated on Linux
    (~/Dokumente, ~/Documenti …). None if there is none."""
    plat = plat or sys.platform
    home = home or Path.home()
    if plat.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
                p = Path(os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0]))
            if p.is_dir():
                return p
        except Exception:
            pass
        for cand in (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial")):
            if cand and (Path(cand) / "Documents").is_dir():
                return Path(cand) / "Documents"
    elif plat.startswith("linux"):
        p = _xdg_dir("XDG_DOCUMENTS_DIR", home)
        if p:
            return p
    docs = home / "Documents"
    return docs if docs.is_dir() else None


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
        folder, name = workspace_for(directory)
        ws = ensure_workspace(folder)
        serve(ws, port=port, open_browser=True, notify=lambda t, m: show_message(t, m, error=False),
              path_query=open_query(name))
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
    user_home = home or Path.home()
    ws = workspace or default_workspace(plat, user_home)
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
    from . import __release__
    return __release__        # macOS wants plain numbers here: no "+g<commit>"


def _desktop_quote(arg: str) -> str:
    """Quote an Exec argument the way the freedesktop Desktop Entry spec requires."""
    if not any(ch in arg for ch in ' \t"\'\\$`<>|&;*?#()'):
        return arg
    return '"' + "".join("\\" + ch if ch in '"`$\\' else ch for ch in arg) + '"'


# ---------------------------------------------------------------- terminal wizard
def _choice(options: tuple[str, ...]) -> Callable[[str], str]:
    def check(text: str) -> str:
        t = text.strip().lower()
        for cand in (t, t[:-1] if t.endswith("s") else t, t + "s"):     # "words" -> word, "key" -> keys
            if cand in options:
                return cand
        import difflib
        close = difflib.get_close_matches(t, options, 1)
        raise ValueError((f"did you mean {close[0]}? " if close else "") + "Please type one of: " + ", ".join(options))
    return check


def _seconds(blank: Any) -> Callable[[str], Any]:
    """A number of seconds ('0.5', '0,5', '500 ms'); 'none' (or nothing) gives ``blank``."""
    def check(text: str) -> Any:
        t = text.strip().lower().replace(",", ".")
        if t in ("", "none", "no", "-", "never", "forever"):
            return blank
        ms = t.endswith("ms")
        t = t.removesuffix("ms").removesuffix("seconds").removesuffix("second").removesuffix("secs") \
            .removesuffix("sec").removesuffix("s").strip()
        try:
            v = float(t)
        except ValueError:
            raise ValueError("please type a number of seconds, e.g. 0.5" + (", or none" if blank != 0.0 else "")) from None
        if v < 0:
            raise ValueError("please type a number of seconds that is 0 or more")
        return v / 1000 if ms else v
    return check


def _whole(text: str) -> int:
    try:
        v = float(text.strip())
    except ValueError:
        raise ValueError("please type a whole number, e.g. 2") from None
    if v != int(v) or v < 1:
        raise ValueError("please type a whole number of 1 or more, e.g. 2")
    return int(v)


def _proportion(text: str) -> float:
    """'0.8', '80%' and '80' all mean 80 % correct."""
    t = text.strip().replace(",", ".")
    try:
        v = float(t.rstrip("%").strip())
    except ValueError:
        raise ValueError("please type the accuracy as a proportion or a percentage, e.g. 0.8 or 80%") from None
    if t.endswith("%") or 1 < v <= 100:
        v /= 100
    if not 0 < v <= 1:
        raise ValueError("please type an accuracy between 0 and 1 (or a percentage), e.g. 0.8 or 80%")
    return v


def _yes_no(text: str) -> bool:
    t = text.strip().lower()
    if t in ("y", "yes", "j", "ja", "o", "oui", "s", "si", "sí"):
        return True
    if t in ("n", "no", "nein", "non"):
        return False
    raise ValueError("please answer y (yes) or n (no)")


def ask_wizard(ask: Callable[[str, str], str] | None = None) -> dict[str, Any]:
    """Ask the design questions in the terminal and return wizard answers. Every answer is checked as it is
    given: a typo is explained and the question asked again, so nothing typed so far is lost."""
    from .survey_library import INSTRUMENTS
    from .wizard import PRACTICE_MODES, RESPONSE_KINDS, STIMULUS_KINDS

    def default_ask(q: str, default: str) -> str:
        r = input(f"{q} [{default}]: ").strip()
        return r or default
    raw = ask or default_ask

    def get(q: str, default: str, check: Callable[[str], Any] | None = None) -> Any:
        for _ in range(20):          # a person retypes; a script that keeps giving a wrong answer must still stop
            r = raw(q, default)
            r = default if not str(r).strip() else str(r)
            if check is None:
                return r
            try:
                return check(r)
            except ValueError as e:
                print(f"  {e}")
        raise ValueError(f"no valid answer to '{q}'")

    def questionnaires(text: str) -> list[str]:
        chosen = text.replace(",", " ").split()
        unknown = [x for x in chosen if x not in INSTRUMENTS]
        if unknown:
            raise ValueError(f"there is no questionnaire called {', '.join(unknown)}; choose from: {' '.join(INSTRUMENTS)}")
        return chosen

    a: dict[str, Any] = {}
    a["name"] = get("Name of the experiment", "my_experiment")
    kind = get("What do participants see or hear? (word / picture / sound / shape)", "word", _choice(STIMULUS_KINDS))
    rkind = get(f"How do they respond? ({' / '.join(RESPONSE_KINDS)})", "keys", _choice(RESPONSE_KINDS))
    items = []
    answer = "correct button" if rkind == "buttons" else "correct key"
    print(f"List the stimuli, one per line as: stimulus, {answer}, condition  (empty line to finish)")
    while True:
        line = get("  stimulus", "")
        if not line:
            break
        parts = [p.strip() for p in line.split(",")]
        items.append({"stimulus": parts[0], "correct": parts[1] if len(parts) > 1 else "",
                      "condition": parts[2] if len(parts) > 2 else ""})
    a["stimulus"] = {"kind": kind, "items": items or None}
    a["response"] = {"kind": rkind}
    if rkind == "keys":
        correct = sorted({i["correct"] for i in items if i["correct"]})

        def keys_check(text: str) -> list[str]:
            keys = text.split()
            missing = [c for c in correct if keys and c not in keys]
            if missing:
                raise ValueError(f"the correct key(s) you gave ({', '.join(missing)}) must be among the response keys; "
                                 f"add them, e.g. {' '.join(sorted(set(keys) | set(correct)))}")
            return keys
        keys = get("Response keys, separated by spaces (empty = the correct keys you gave)", "", keys_check)
        if keys:
            a["response"]["keys"] = keys
    a["timing"] = {"fixation": get("Fixation cross before each stimulus, seconds (0 = none)", "0.5", _seconds(0.0)),
                   "stimulus_duration": get("Show the stimulus for how many seconds? (empty = until response)", "",
                                            _seconds(None))}
    if rkind != "none":
        # 'none' (not an empty answer, which takes the default) means no deadline: wait for the answer
        a["timing"]["response_deadline"] = get("Response deadline in seconds (none = wait for the answer)",
                                               "2" if rkind == "keys" else "none", _seconds("none"))
    a["feedback"] = get("Show correct / wrong feedback? (y/n)", "n", _yes_no)
    a["practice"] = {"mode": get("Practice block? (none / once / until)", "none", _choice(PRACTICE_MODES))}
    if a["practice"]["mode"] == "until":
        a["practice"]["criterion"] = get("Accuracy needed to pass (e.g. 0.8 or 80%)", "0.8", _proportion)
        a["practice"]["max_rounds"] = get("At most how many practice rounds", "3", _whole)
    a["blocks"] = {"count": get("Number of blocks", "1", _whole),
                   "repeats": get("How many times each stimulus appears per block", "1", _whole)}
    a["questionnaires"] = get("Questionnaires, separated by spaces (" + " ".join(INSTRUMENTS) + "; empty = none)", "",
                              questionnaires)
    return a


def write_wizard_experiment(answers: dict[str, Any], directory: Path) -> tuple[Path, dict[str, Any]]:
    from .storage import save_document
    from .wizard import build_experiment, estimate, prepare_files
    notes: list[str] = []          # answers the wizard filled in, adjusted or left out; files still to provide
    doc = build_experiment(answers, notes)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc['name']}.yaml"
    n = 2
    while path.exists():
        path = directory / f"{doc['name']}_{n}.yaml"
        n += 1
    save_document(path, doc, label="wizard")
    notes += prepare_files(doc, directory)
    est = estimate(doc, directory)
    est["notes"] = notes
    return path, est


def load_answers(path: str) -> dict[str, Any]:
    """Wizard answers from a JSON or YAML file (a mistake in it is a WizardError that says where)."""
    from .wizard import read_answers
    return read_answers(path)
