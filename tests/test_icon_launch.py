"""The EDGE icon and the desktop launcher: files, per-platform shortcuts, and launch failures that explain themselves."""

import io
import json
import plistlib
import struct
import sys
import threading
import urllib.error
import urllib.request
import xml.dom.minidom
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import launcher

ASSETS = Path(__file__).resolve().parent.parent / "edge" / "assets"


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


# ============================================================================ the icon files
def test_icon_files_are_complete_and_valid():
    xml.dom.minidom.parse(str(ASSETS / "edge-icon.svg"))
    for n in (16, 32, 48, 64, 128, 256, 512):
        assert png_size((ASSETS / f"edge-{n}.png").read_bytes()) == (n, n)
    ico = (ASSETS / "edge.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, kind) == (0, 1) and count == 7
    sizes = []
    for i in range(count):
        w, h, _, _, planes, bpp, length, offset = struct.unpack("<BBBBHHII", ico[6 + 16 * i:22 + 16 * i])
        side = w or 256
        assert png_size(ico[offset:offset + length]) == (side, side) and planes == 1 and bpp == 32
        sizes.append(side)
    assert sizes == [16, 24, 32, 48, 64, 128, 256]
    icns = (ASSETS / "edge.icns").read_bytes()
    assert icns[:4] == b"icns" and struct.unpack(">I", icns[4:8])[0] == len(icns)
    pos, kinds = 8, []
    while pos < len(icns):
        kind, length = icns[pos:pos + 4], struct.unpack(">I", icns[pos + 4:pos + 8])[0]
        png_size(icns[pos + 8:pos + length])
        kinds.append(kind)
        pos += length
    assert kinds == [b"icp4", b"icp5", b"icp6", b"ic07", b"ic08", b"ic09", b"ic10"]


def test_icon_is_part_of_the_package_and_the_builder():
    root = ASSETS.parent.parent
    assert "assets/*" in (root / "pyproject.toml").read_text() and "assets/*" in (root / "install" / "edge.spec").read_text()
    html = (root / "edge" / "builder" / "static" / "index.html").read_text()
    assert "/assets/edge-icon.svg" in html and "/assets/edge-48.png" in html


def test_builder_serves_the_icon_and_favicon(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/favicon.ico") as r:
            assert r.headers["Content-Type"] == "image/png" and png_size(r.read()) == (32, 32)
        with urllib.request.urlopen(base + "/assets/edge-icon.svg") as r:
            assert r.headers["Content-Type"] == "image/svg+xml"
        for bad in ("/assets/..%2Fcli.py", "/assets/nothing.png", "/assets/edge.icns"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + bad)
            assert e.value.code == 404
    finally:
        httpd.shutdown()


# ============================================================================ desktop shortcuts
@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("EDGE_HOME", str(tmp_path / "EDGE Experiments"))
    return tmp_path


def test_desktop_folder_is_the_real_one(tmp_path):
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Bureau"\n')
    (tmp_path / "Bureau").mkdir()
    assert launcher.desktop_dir("linux", tmp_path) == tmp_path / "Bureau"
    assert launcher.desktop_dir("linux", tmp_path / "other") == tmp_path / "other" / "Desktop"
    assert launcher.desktop_dir("darwin", tmp_path) == tmp_path / "Desktop"


def test_linux_icon_is_installed_and_the_entry_points_at_it(state):
    home = state / "home"
    (home / "Desktop").mkdir(parents=True)
    files = launcher.desktop_shortcut("linux", home=home)
    names = {f.parent.name for f in files}
    assert names == {"Desktop", "applications"}
    text = files[0].read_text()
    icon = state / "state" / "icons" / "edge-256.png"
    assert f"Icon={icon}" in text and icon.exists() and "--from-shortcut" in text
    assert (home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "edge.png").exists()
    assert files[0].stat().st_mode & 0o100


def test_mac_gets_a_real_app_with_the_icon(state):
    home = state / "home"
    (home / "Desktop").mkdir(parents=True)
    old = home / "Desktop" / "EDGE.command"
    old.write_text("#!/bin/sh\nexec python -m edge start\n")
    apps = launcher.desktop_shortcut("darwin", home=home)
    assert [a.parent.name for a in apps] == ["Desktop", "Applications"] and not old.exists()
    app = apps[0]
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIconFile"] == "edge" and info["CFBundleExecutable"] == "EDGE"
    assert (app / "Contents" / "Resources" / "edge.icns").read_bytes()[:4] == b"icns"
    script = app / "Contents" / "MacOS" / "EDGE"
    assert script.read_text().startswith("#!/bin/sh") and "--from-shortcut" in script.read_text() and script.stat().st_mode & 0o100


def test_windows_gets_a_shortcut_with_the_icon(state, monkeypatch):
    monkeypatch.setenv("APPDATA", str(state / "appdata"))
    scripts = []

    def fake_powershell(cmd, **kw):
        scripts.append(cmd[-1])
        return type("R", (), {"returncode": 0})()
    home = state / "home"
    (home / "Desktop").mkdir(parents=True)
    (home / "Desktop" / "EDGE.bat").write_text('@echo off\r\nstart "" "x" -m edge start "y"\r\n')
    ws = Path("C:/Users/John O'Neil/Documents/EDGE Experiments")
    # the Windows branch builds the same script anywhere
    monkeypatch.setattr(launcher, "desktop_dir", lambda plat=None, home=None: (home or Path.home()) / "Desktop")
    out = launcher.desktop_shortcut("win32", workspace=ws, run=fake_powershell, home=home)
    assert [p.name for p in out] == ["EDGE.lnk", "EDGE.lnk"] and len(scripts) == 2
    s = scripts[0]
    assert "IconLocation='" + str(state / "state" / "icons" / "edge.ico") + ",0'" in s
    assert "-m edge start --from-shortcut" in s and "John O''Neil" in s          # quotes survive PowerShell
    assert "pythonw" in s.lower() or sys.executable.lower().replace("\\", "/") in s.lower().replace("\\", "/")
    assert not (home / "Desktop" / "EDGE.bat").exists()                           # the old plain launcher is replaced


def test_windows_falls_back_when_powershell_is_blocked(state):
    def blocked(cmd, **kw):
        return type("R", (), {"returncode": 1})()
    out = launcher.desktop_shortcut("win32", desktop=state / "d", run=blocked)
    assert out[0].name == "EDGE.bat" and "--from-shortcut" in out[0].read_text()


# ============================================================================ launches that explain themselves
def test_a_failed_launch_is_logged_and_shown(state, monkeypatch):
    shown = []
    monkeypatch.setattr(launcher, "show_message", lambda title, text, error=True: shown.append((title, text)))
    import edge.builder.server as server

    def boom(*a, **k):
        raise OSError("no free port between 8765 and 8784")
    monkeypatch.setattr(server, "serve", boom)
    assert launcher.launch_from_shortcut() == 1
    assert shown[0][0] == "EDGE could not start" and "no free port" in shown[0][1] and "launch.log" in shown[0][1]
    log = (state / "state" / "launch.log").read_text()
    assert "EDGE 0." in log and "OSError: no free port" in log and "Traceback" in log


def test_shortcut_launch_survives_having_no_console(state, monkeypatch):
    import edge.builder.server as server
    seen = {}

    def fake_serve(root, **kw):
        print("EDGE builder running")       # pythonw.exe: sys.stdout is None
        seen["root"], seen["open"] = root, kw["open_browser"]
    monkeypatch.setattr(server, "serve", fake_serve)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        assert launcher.launch_from_shortcut() == 0
        assert sys.stdout is not None
    finally:
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
    assert seen["open"] and seen["root"].name == "EDGE Experiments"
    assert "EDGE builder running" in (state / "state" / "launch.log").read_text()


def test_no_browser_means_the_address_is_shown(monkeypatch):
    import webbrowser
    from edge.builder.server import open_in_browser
    shown = []
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    assert open_in_browser("http://127.0.0.1:8765/", lambda t, m: shown.append((t, m))) is False
    assert "http://127.0.0.1:8765/" in shown[0][1] and "no web browser" in shown[0][1]
    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    shown.clear()
    assert open_in_browser("http://x/", lambda t, m: shown.append(1)) is True and not shown
    monkeypatch.setattr(webbrowser, "open", lambda url: (_ for _ in ()).throw(RuntimeError("no display")))
    assert open_in_browser("http://x/", lambda t, m: shown.append(1)) is False and shown


def test_message_box_never_raises(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    launcher.show_message("t", "m")
    launcher.show_message("t", "m", error=False)
    _ = json, io
