"""Computer check (``edge doctor``): the known causes of bad timing and lost responses.

Each check looks for one condition that experiment software vendors document as a known issue on
lab computers, explains it in plain words, and where possible fixes it:

* laptop on battery / power-saving plan          -> slower, irregular frames (Windows 11 laptops)
* USB selective suspend                          -> a response box stops answering after a pause
* generic display driver / software rendering    -> no valid refresh rate, no real vsync
* several monitors with fullscreen optimizations -> freezes, "display too busy", first key presses lost
* display scaling (DPI) other than 100%          -> stimuli drawn at the wrong size
* FTDI USB-serial latency timer at 16 ms         -> responses and triggers late by up to 16 ms
* input method editors (Chinese/Japanese/Korean) -> key presses swallowed
* coarse system timer                            -> imprecise reaction times

The checks are cheap and never raise; anything that can't be determined is simply left out.
``run_checks`` is also called at the start of every real session, and the results are saved in
``session.json`` and listed in the session report.
"""

from __future__ import annotations

import glob
import platform
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

HIGH_PERF_PLANS = {"8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High performance",
                   "e9a42b02-d5df-448d-aa00-03f14749eb61": "Ultimate Performance"}
USB_SUB, USB_SUSPEND = "2a737441-1930-4402-8d77-b2bebba308a3", "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
SOFTWARE_RENDERERS = ("llvmpipe", "softpipe", "swrast", "microsoft basic render", "gdi generic", "swiftshader",
                      "microsoft basic display")
FSO_FLAG = "~ DISABLEDXMAXIMIZEDWINDOWEDMODE"
FSO_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"


@dataclass
class Check:
    id: str
    level: str            # ok | info | warning | error
    title: str
    detail: str = ""
    fix: str = ""         # what to do (plain words)
    fixable: bool = False  # edge doctor --fix / the builder's Fix button can do it

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=0x08000000 if IS_WIN else 0)   # CREATE_NO_WINDOW
        return r.stdout or ""
    except Exception:
        return ""


# ============================================================================ power
def on_battery() -> bool | None:
    if IS_WIN:
        import ctypes

        class SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
        s = SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):  # type: ignore[attr-defined]
            return None
        if s.BatteryFlag == -128 or s.BatteryFlag & 128:     # no system battery
            return False
        return s.ACLineStatus == 0
    if IS_MAC:
        out = _run(["pmset", "-g", "batt"])
        return ("Battery Power" in out) if out else None
    if IS_LINUX:
        supplies = glob.glob("/sys/class/power_supply/*")
        if not supplies:
            return None
        mains = [p for p in supplies if _read(p + "/type") in ("Mains", "USB_C", "USB")]
        if any(_read(p + "/online") == "1" for p in mains):
            return False
        bats = [p for p in supplies if _read(p + "/type") == "Battery"]
        if not bats:
            return False
        return any(_read(p + "/status") == "Discharging" for p in bats)
    return None


def _read(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def check_power() -> list[Check]:
    out = []
    b = on_battery()
    if b:
        out.append(Check("battery", "warning", "Running on battery",
                         "On battery, laptops (Windows 11 especially) slow the processor and graphics down to save "
                         "power: frames are dropped and reaction times get noisier.",
                         "Plug in the charger before running participants."))
    elif b is False:
        out.append(Check("battery", "ok", "On mains power"))
    if IS_WIN:
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\s+\((.+?)\)", _run(["powercfg", "/getactivescheme"]), re.I)
        if m:
            guid, name = m.group(1).lower(), m.group(2)
            if guid in HIGH_PERF_PLANS:
                out.append(Check("power_plan", "ok", f"Power plan: {name}"))
            else:
                out.append(Check("power_plan", "info", f"Power plan: {name}",
                                 "Balanced and power-saving plans let the processor slow down between trials.",
                                 "Choose 'High performance' in Control Panel → Power Options.", fixable=True))
    return out


def usb_selective_suspend() -> bool | None:
    if not IS_WIN:
        return None
    out = _run(["powercfg", "/query", "SCHEME_CURRENT", USB_SUB, USB_SUSPEND])
    m = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-f]+)", out, re.I)
    return None if not m else int(m.group(1), 16) == 1


def check_usb_suspend(uses_usb_devices: bool) -> list[Check]:
    s = usb_selective_suspend()
    if s is None:
        return []
    if not s:
        return [Check("usb_suspend", "ok", "USB selective suspend is off")]
    return [Check("usb_suspend", "warning" if uses_usb_devices else "info", "USB selective suspend is on",
                  "Windows may put a USB response box or trigger box to sleep during a pause (instructions, a "
                  "break): the first responses or triggers after it can be lost.",
                  "Turn off 'USB selective suspend' in Power Options → Advanced settings → USB settings.", fixable=True)]


# ============================================================================ display
def video_adapters() -> list[str]:
    if IS_WIN:
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"], timeout=8)
        return [line.strip() for line in out.splitlines() if line.strip()]
    if IS_LINUX:
        out = _run(["glxinfo", "-B"])
        m = re.search(r"OpenGL renderer string:\s*(.+)", out)
        return [m.group(1).strip()] if m else []
    if IS_MAC:
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=8)
        return [m.strip() for m in re.findall(r"Chipset Model:\s*(.+)", out)]
    return []


def is_software_renderer(name: str) -> bool:
    n = name.lower()
    return any(s in n for s in SOFTWARE_RENDERERS)


def check_display_driver(adapters: list[str] | None = None) -> list[Check]:
    adapters = video_adapters() if adapters is None else adapters
    if not adapters:
        return []
    bad = [a for a in adapters if is_software_renderer(a)]
    if bad:
        return [Check("display_driver", "error", f"Generic display driver: {bad[0]}",
                      "Without the graphics card's own driver the screen reports no valid refresh rate and there is "
                      "no real vsync: stimulus durations and onsets cannot be trusted.",
                      "Install the driver from NVIDIA, AMD or Intel (or the computer maker), then restart.")]
    return [Check("display_driver", "ok", "Display: " + ", ".join(adapters))]


def screens() -> list[dict[str, Any]]:
    try:
        import pyglet
        out = []
        for s in pyglet.display.get_display().get_screens():
            d: dict[str, Any] = {"width": s.width, "height": s.height, "x": s.x, "y": s.y}
            try:
                mode = s.get_mode()
                d["rate"] = getattr(mode, "rate", None)
            except Exception:
                pass
            out.append(d)
        return out
    except Exception:
        return []


def dpi_scale() -> float | None:
    if IS_WIN:
        try:
            import ctypes
            return ctypes.windll.user32.GetDpiForSystem() / 96.0  # type: ignore[attr-defined]
        except Exception:
            return None
    return None


def fullscreen_optimizations_disabled(exe: str | None = None) -> bool | None:
    if not IS_WIN:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, FSO_KEY) as k:
            val, _ = winreg.QueryValueEx(k, exe or sys.executable)
        return "DISABLEDXMAXIMIZEDWINDOWEDMODE" in str(val).upper()
    except OSError:
        return False
    except Exception:
        return None


def check_screens(window: dict[str, Any] | None = None, scr: list[dict[str, Any]] | None = None,
                  dpi: float | None = None, fso: bool | None = None) -> list[Check]:
    window = window or {}
    scr = screens() if scr is None else scr
    out: list[Check] = []
    if scr:
        idx = int(window.get("screen", 0) or 0)
        desc = ", ".join(f"{s['width']}×{s['height']}" + (f" @ {s['rate']} Hz" if s.get("rate") else "") for s in scr)
        if idx >= len(scr):
            out.append(Check("screen_index", "error", f"Screen {idx} does not exist",
                             f"This computer has {len(scr)} screen(s): {desc}. The experiment would open on screen 0.",
                             f"Set Settings → window → screen to 0–{len(scr) - 1}."))
        else:
            s = scr[idx]
            out.append(Check("screens", "ok", f"{len(scr)} screen(s): {desc}"))
            size = window.get("size")
            if window.get("fullscreen") and isinstance(size, (list, tuple)) and len(size) == 2 \
                    and (int(size[0]), int(size[1])) != (s["width"], s["height"]):
                out.append(Check("resolution", "warning", f"Window size {size[0]}×{size[1]} ≠ screen {s['width']}×{s['height']}",
                                 "Full screen at a size that isn't the screen's own resolution makes the display rescale "
                                 "or switch modes, which can add a frame of delay and change the refresh rate.",
                                 f"Set the window size to {s['width']}×{s['height']} (use units norm or height so "
                                 "stimuli keep their proportions)."))
        if len(scr) > 1 and IS_WIN and fso is not True:
            out.append(Check("fullscreen_optimizations", "warning",
                             "Several monitors with Windows fullscreen optimizations on",
                             "With more than one monitor, Windows 10/11 fullscreen optimizations can freeze full-screen "
                             "experiments or make them miss frames, and the first key presses after the window opens "
                             "can be lost.",
                             "Disable fullscreen optimizations for EDGE's Python (or unplug the second monitor).",
                             fixable=True))
    elif IS_WIN and fso is False:
        out.append(Check("fullscreen_optimizations", "info", "Windows fullscreen optimizations are on",
                         "On some Windows 11 computers they make the first key presses of a session go missing.",
                         "Disable fullscreen optimizations for EDGE's Python.", fixable=True))
    if dpi and abs(dpi - 1.0) > 0.01:
        out.append(Check("dpi", "info", f"Display scaling is {round(dpi * 100)}%",
                         "EDGE tells Windows it handles scaling itself, so stimuli are drawn in real screen pixels "
                         "(sizes in px are physical pixels, not scaled ones). Other programs' windows and dialogs may look small.",
                         "Nothing to do; set scaling to 100% if you want px to match what the Windows desktop shows."))
    return out


# ============================================================================ serial devices
def ftdi_ports() -> list[dict[str, Any]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        if getattr(p, "vid", None) == 0x0403:   # FTDI
            out.append({"port": p.device, "description": p.description, "latency_ms": ftdi_latency(p.device)})
    return out


def ftdi_latency(port: str) -> int | None:
    if IS_LINUX:
        v = _read(f"/sys/bus/usb-serial/devices/{Path(port).name}/latency_timer")
        return int(v) if v.isdigit() else None
    if IS_WIN:
        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Enum\FTDIBUS"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    dev = winreg.EnumKey(root, i)
                    try:
                        with winreg.OpenKey(root, dev + r"\0000\Device Parameters") as k:
                            if winreg.QueryValueEx(k, "PortName")[0] == port:
                                return int(winreg.QueryValueEx(k, "LatencyTimer")[0])
                    except OSError:
                        continue
        except Exception:
            return None
    return None


def check_serial(ports: list[dict[str, Any]] | None = None, used: set[str] | None = None) -> list[Check]:
    ports = ftdi_ports() if ports is None else ports
    out = []
    for p in ports:
        lat = p.get("latency_ms")
        if lat is not None and lat > 2:
            relevant = not used or p["port"] in used or "" in used
            out.append(Check(f"ftdi_latency:{p['port']}", "warning" if relevant else "info",
                             f"{p['port']}: USB-serial latency timer is {lat} ms",
                             "FTDI USB-serial adapters hold incoming bytes for up to this long: responses from a box on "
                             "this port arrive (and are timestamped) up to that much late.",
                             "Set it to 1 ms: Device Manager → Ports → USB Serial Port → Properties → Port Settings → "
                             "Advanced → Latency Timer." if IS_WIN else
                             f"Set it to 1 ms: echo 1 | sudo tee /sys/bus/usb-serial/devices/{Path(p['port']).name}/latency_timer",
                             fixable=IS_LINUX))
        elif lat is not None:
            out.append(Check(f"ftdi_latency:{p['port']}", "ok", f"{p['port']}: USB-serial latency timer {lat} ms"))
    return out


# ============================================================================ keyboard and timer
IME_LANGS = {0x04: "Chinese", 0x11: "Japanese", 0x12: "Korean"}


def keyboard_language() -> int | None:
    if IS_WIN:
        try:
            import ctypes
            return ctypes.windll.user32.GetKeyboardLayout(0) & 0x3FF  # type: ignore[attr-defined]
        except Exception:
            return None
    return None


def check_keyboard(lang: int | None = None) -> list[Check]:
    lang = keyboard_language() if lang is None else lang
    if lang in IME_LANGS:
        return [Check("ime", "warning", f"{IME_LANGS[lang]} input method is active",
                      "Input method editors catch key presses to compose characters, so letter keys can go missing.",
                      "Switch the keyboard to English (Win+Space) before starting the session.")]
    return []


def check_timer() -> list[Check]:
    res = time.get_clock_info("perf_counter").resolution
    if res > 1e-4:
        return [Check("timer", "warning", f"Coarse timer ({res * 1e3:.2f} ms)",
                      "Reaction times can't be more precise than the system timer.",
                      "Use a recent Windows/macOS/Linux; check that no virtual machine is used.")]
    return [Check("timer", "ok", f"High-resolution timer ({res * 1e9:.0f} ns)")]


# ============================================================================ all together
def run_checks(exp: Any = None, quick: bool = False) -> list[Check]:
    """All checks that apply to this computer (and, if given, to this experiment's settings and devices)."""
    window = dict((exp.settings.get("window") if exp is not None else None) or {})
    serial_types = {"serial_inputs", "ttl_serial", "trigger_adapter", "mindware", "labjack"}
    uses_usb = bool(exp is not None and any(d.type in serial_types for d in exp.devices))
    used_ports = {str(d.options.get("port") or "") for d in (exp.devices if exp is not None else []) if d.type in serial_types}
    out: list[Check] = []
    for fn in (check_power, lambda: check_usb_suspend(uses_usb), check_timer, check_keyboard,
               lambda: check_screens(window, dpi=dpi_scale(), fso=fullscreen_optimizations_disabled()),
               lambda: check_serial(used=used_ports or None),
               *(() if quick else (check_display_driver,))):
        try:
            out.extend(fn())
        except Exception:   # a check that can't run on this computer is simply skipped
            continue
    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}
    return sorted(out, key=lambda c: order.get(c.level, 9))


FIXES: dict[str, Callable[[str], str]] = {}


def _fix(prefix: str):
    def deco(fn):
        FIXES[prefix] = fn
        return fn
    return deco


@_fix("fullscreen_optimizations")
def _fix_fso(_: str) -> str:
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, FSO_KEY) as k:
        winreg.SetValueEx(k, sys.executable, 0, winreg.REG_SZ, FSO_FLAG)
    return f"fullscreen optimizations disabled for {sys.executable}"


@_fix("power_plan")
def _fix_plan(_: str) -> str:
    r = subprocess.run(["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stdout or r.stderr or "powercfg failed")
    return "power plan set to High performance"


@_fix("usb_suspend")
def _fix_usb(_: str) -> str:
    for args in (["/setacvalueindex", "SCHEME_CURRENT", USB_SUB, USB_SUSPEND, "0"],
                 ["/setdcvalueindex", "SCHEME_CURRENT", USB_SUB, USB_SUSPEND, "0"], ["/setactive", "SCHEME_CURRENT"]):
        r = subprocess.run(["powercfg", *args], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stdout or r.stderr or "powercfg failed")
    return "USB selective suspend turned off"


@_fix("ftdi_latency")
def _fix_ftdi(check_id: str) -> str:
    port = check_id.split(":", 1)[1]
    Path(f"/sys/bus/usb-serial/devices/{Path(port).name}/latency_timer").write_text("1")
    return f"{port}: latency timer set to 1 ms"


def apply_fix(check_id: str) -> str:
    """Fix one problem found by run_checks (only those marked fixable). Returns what was done."""
    fn = FIXES.get(check_id.split(":", 1)[0])
    if fn is None:
        raise ValueError(f"'{check_id}' can't be fixed automatically")
    try:
        return fn(check_id)
    except PermissionError as e:
        raise RuntimeError(f"needs administrator rights: {e}") from e


def format_checks(checks: list[Check]) -> str:
    mark = {"ok": "✓", "info": "·", "warning": "!", "error": "✗"}
    lines = [f"EDGE computer check ({platform.system()} {platform.release()}, Python {platform.python_version()})", ""]
    for c in checks:
        lines.append(f"  {mark.get(c.level, '?')} {c.title}")
        if c.level != "ok":
            if c.detail:
                lines.append(f"      {c.detail}")
            if c.fix:
                lines.append(f"      → {c.fix}" + ("  (edge doctor --fix can do this)" if c.fixable else ""))
    n = sum(c.level in ("warning", "error") for c in checks)
    lines += ["", "No problems found." if not n else f"{n} thing(s) to look at before running participants."]
    return "\n".join(lines)

