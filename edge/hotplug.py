"""Plug and play: notice hardware being plugged in and out, and say what it is.

``snapshot()`` asks every detection backend what is connected *now*; each answer is an item (a dict) with a
``kind`` (serial, lsl, gamepad, audio, monitor, tobii, gazepoint, labjack, parallel), a stable ``id`` and what the
device reports about itself. ``Watcher`` polls the snapshot every ~2 seconds in a background thread, compares it
with the previous one and keeps a numbered list of ``connected`` / ``disconnected`` events, each identified with
the knowledge base in :mod:`edge.hardware_db`.

Detection is passive. Serial ports are only *listed* (pyserial's list_ports reads what the operating system
knows about them); no port is opened or written to. LSL streams are found by listening for their announcements;
Gazepoint is looked for on this computer only (127.0.0.1:4242). The one exception is :func:`identify_cedrus`,
which runs only when the researcher clicks "Identify" on a device recognised as a Cedrus box, and asks it for its
name with the documented XID query commands (``_c1``, ``_d1``, ``_d2``, ``_d3``), which change nothing on the device.

Every backend is optional: a missing library (pyserial, pylsl, pyglet, sounddevice, tobii_research,
LabJackPython) just means that kind of device isn't looked for.

Testing aid: with ``EDGE_FAKE_HARDWARE=<file.json>`` the real backends are not used; the file is read on every
poll and lists the items that are "connected" (a list of items, or ``{"items": [...]}``). Changing the file plugs
and unplugs them.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import hardware_db

POLL_SECONDS = 2.0
FAKE_ENV = "EDGE_FAKE_HARDWARE"


# ============================================================================ detection backends
def _hex4(v: Any) -> str:
    return f"{int(v):04x}" if isinstance(v, int) else (str(v).lower() if v else "")


def list_serial() -> list[dict[str, Any]]:
    """USB and serial ports (pyserial's list_ports: no port is opened)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    try:
        ports = list(list_ports.comports())
    except Exception:
        return []
    for p in ports:
        if sys.platform.startswith("linux") and str(p.device).startswith("/dev/ttyS") and not p.vid:
            continue        # the motherboard's legacy ports exist whether or not something is connected
        it = {"kind": "serial", "port": p.device, "vid": _hex4(p.vid), "pid": _hex4(p.pid),
              "serial_number": getattr(p, "serial_number", None) or "", "manufacturer": getattr(p, "manufacturer", None) or "",
              "product": getattr(p, "product", None) or "", "description": p.description if p.description != "n/a" else "",
              "location": getattr(p, "location", None) or ""}
        out.append(it)
    return out


def list_lsl(timeout: float = 0.5) -> list[dict[str, Any]]:
    """LSL streams on the network, with their channel names, units and rate (from the stream's description)."""
    try:
        import pylsl
        streams = pylsl.resolve_streams(timeout)
    except Exception:
        return []
    out = []
    for s in streams:
        chans, units = [], []
        try:
            ch = s.desc().child("channels").child("channel")
            for _ in range(s.channel_count()):
                if ch.empty():
                    break
                chans.append(ch.child_value("label") or "")
                units.append(ch.child_value("unit") or "")
                ch = ch.next_sibling()
        except Exception:
            pass
        out.append({"kind": "lsl", "name": s.name(), "lsl_type": s.type(), "channel_count": s.channel_count(),
                    "srate": s.nominal_srate(), "source_id": s.source_id(), "host": s.hostname(),
                    "channels": chans if any(chans) else [], "units": units if any(units) else []})
    return out


def list_gamepads() -> list[dict[str, Any]]:
    try:
        import pyglet.input
    except Exception:
        return []
    out = []
    try:
        devs = list(pyglet.input.get_controllers())
    except Exception:
        devs = []
    try:
        taken = {id(getattr(c, "device", None)) for c in devs}
        devs += [j for j in pyglet.input.get_joysticks() if id(getattr(j, "device", None)) not in taken]
    except Exception:
        pass
    for i, d in enumerate(devs):
        dev = getattr(d, "device", d)
        name = getattr(d, "name", None) or getattr(dev, "name", None) or f"Gamepad {i + 1}"
        out.append({"kind": "gamepad", "name": str(name), "index": i, "guid": str(getattr(d, "guid", "") or "")})
    return out


def list_audio_inputs() -> list[dict[str, Any]]:
    try:
        import sounddevice as sd
        devs = sd.query_devices()
    except Exception:
        return []
    out = []
    for i, d in enumerate(devs):
        if int(d.get("max_input_channels") or 0) > 0:
            out.append({"kind": "audio", "name": str(d.get("name")), "index": i,
                        "channels_in": int(d["max_input_channels"]), "rate": d.get("default_samplerate")})
    return out


def list_monitors() -> list[dict[str, Any]]:
    try:
        from .syscheck import screens
    except Exception:
        return []
    return [{"kind": "monitor", "index": i, "name": f"Monitor {i + 1}", **s} for i, s in enumerate(screens())]


def list_tobii() -> list[dict[str, Any]]:
    try:
        import tobii_research as tr
        found = tr.find_all_eyetrackers()
    except Exception:
        return []
    return [{"kind": "tobii", "name": f"Tobii {e.model}", "model": e.model, "serial_number": e.serial_number,
             "address": e.address} for e in found]


def list_gazepoint(host: str = "127.0.0.1", port: int = 4242, timeout: float = 0.3) -> list[dict[str, Any]]:
    """Gazepoint Control's server, on this computer only (no network scanning)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return [{"kind": "gazepoint", "name": "Gazepoint Control", "host": host, "tcp_port": port}]
    except OSError:
        return []


LABJACK_VID = "0cd5"
LABJACK_MODELS = {"0003": "U3", "0006": "U6", "0009": "UE9"}


def list_labjack() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sysfs = Path("/sys/bus/usb/devices")
    if sys.platform.startswith("linux") and sysfs.is_dir():        # passive: what the kernel knows
        for d in sorted(sysfs.iterdir()):
            try:
                if (d / "idVendor").read_text().strip().lower() != LABJACK_VID:
                    continue
                pid = (d / "idProduct").read_text().strip().lower()
                sn = (d / "serial").read_text().strip() if (d / "serial").exists() else ""
            except OSError:
                continue
            model = LABJACK_MODELS.get(pid, "")
            out.append({"kind": "labjack", "name": f"LabJack {model}".strip(), "model": model or "U3", "vid": LABJACK_VID,
                        "pid": pid, "serial_number": sn, "port": d.name})
        return out
    try:
        import LabJackPython as ljp        # counts devices without opening them
    except Exception:
        return []
    for code, model in ((3, "U3"), (6, "U6")):
        try:
            n = int(ljp.deviceCount(code))
        except Exception:
            n = 0
        out += [{"kind": "labjack", "name": f"LabJack {model}", "model": model, "port": f"{model}#{i + 1}"} for i in range(n)]
    return out


def list_parallel() -> list[dict[str, Any]]:
    if sys.platform.startswith("linux"):
        return [{"kind": "parallel", "name": f"Parallel port {p}", "port": str(p)} for p in sorted(Path("/dev").glob("parport*"))]
    if sys.platform.startswith("win"):
        import ctypes.util
        if ctypes.util.find_library("inpoutx64") or ctypes.util.find_library("inpout32"):
            return [{"kind": "parallel", "name": "Parallel port (inpout driver)", "port": "0x378"}]
    return []


BACKENDS: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "serial": list_serial, "lsl": list_lsl, "gamepad": list_gamepads, "audio": list_audio_inputs,
    "monitor": list_monitors, "tobii": list_tobii, "gazepoint": list_gazepoint, "labjack": list_labjack,
    "parallel": list_parallel,
}
# Looked for in the background every poll: cheap and safe off the main thread. pyglet (gamepads, monitors) must run on
# the main thread on macOS, so there they are only listed by an explicit scan.
WATCHED = ("serial", "lsl", "gamepad", "audio", "monitor", "tobii", "gazepoint", "labjack", "parallel")
SLOW = {"tobii": 10.0, "monitor": 6.0, "audio": 6.0, "gamepad": 4.0, "labjack": 6.0, "lsl": 4.0}     # seconds between looks


def fake_items() -> list[dict[str, Any]] | None:
    """The items listed in the EDGE_FAKE_HARDWARE file (a testing aid), or None when it is not set."""
    path = os.environ.get(FAKE_ENV)
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("items") or []
    return [dict(x) for x in data if isinstance(x, dict) and x.get("kind")]


# ============================================================================ identity
def identity(item: dict[str, Any]) -> str:
    """A name for the device that stays the same when it is plugged into another USB socket (and gets another
    port name) where possible: the USB serial number, else the port."""
    k = item.get("kind")
    if item.get("id"):
        return str(item["id"])
    if k in ("serial", "labjack"):
        if item.get("serial_number"):
            return f"{k}:{item.get('vid', '')}:{item.get('pid', '')}:{item['serial_number']}"
        return f"{k}:{item.get('port')}"
    if k == "lsl":
        return f"lsl:{item.get('source_id') or item.get('name')}@{item.get('host', '')}"
    if k == "tobii":
        return f"tobii:{item.get('serial_number') or item.get('address')}"
    if k == "gazepoint":
        return f"gazepoint:{item.get('host')}:{item.get('tcp_port', 4242)}"
    if k == "monitor":
        return f"monitor:{item.get('index')}:{item.get('width')}x{item.get('height')}"
    if k == "gamepad":
        return f"gamepad:{item.get('guid') or item.get('name')}:{item.get('index')}"
    if k == "audio":
        return f"audio:{item.get('name')}"
    return f"{k}:{item.get('port') or item.get('name')}"


def snapshot(kinds: tuple[str, ...] | list[str] | None = None, lsl_timeout: float = 0.5,
             previous: dict[str, dict[str, Any]] | None = None, due: Callable[[str], bool] | None = None) -> dict[str, dict[str, Any]]:
    """What is connected now: {identity: item}. ``due(kind)`` False keeps that kind's items from ``previous``
    (slow backends are asked less often)."""
    fake = fake_items()
    kinds = tuple(kinds or BACKENDS)
    items: list[dict[str, Any]] = []
    if fake is not None:
        items = [x for x in fake if x.get("kind") in kinds]
    else:
        for k in kinds:
            if due is not None and previous is not None and not due(k):
                items += [x for x in previous.values() if x.get("kind") == k]
                continue
            fn = BACKENDS[k]
            try:
                got = fn(lsl_timeout) if k == "lsl" else fn()     # type: ignore[call-arg]
            except Exception:
                got = []
            items += got
    out: dict[str, dict[str, Any]] = {}
    for it in items:
        it = dict(it)
        it["id"] = identity(it)
        out[it["id"]] = it
    return out


def describe(item: dict[str, Any]) -> dict[str, Any]:
    """The item with what it is: {…item, identified: {name, certainty, offers, …}, label}."""
    try:
        ident = hardware_db.identify(item)
    except Exception as e:             # a broken user entry must not stop detection
        ident = {"entry": None, "name": item.get("name") or item.get("port") or "device", "certainty": "ask",
                 "offers": [], "error": f"{type(e).__name__}: {e}"}
    where = item.get("port") or (item.get("host") if item.get("kind") == "lsl" else "") or ""
    return {**item, "identified": ident, "label": ident["name"], "where": where}


def diff(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """[("connected" | "disconnected", item)] between two snapshots."""
    ev = [("disconnected", old[k]) for k in old if k not in new]
    ev += [("connected", new[k]) for k in new if k not in old]
    # the same device on another port (re-plugged into another socket between two polls): a disconnect + connect
    for k in old:
        if k in new and old[k].get("port") != new[k].get("port"):
            ev += [("disconnected", old[k]), ("connected", new[k])]
    return ev


# ============================================================================ the watcher
class Watcher:
    """Polls :func:`snapshot` in a background thread; keeps numbered events for ``wait(since)``."""

    def __init__(self, interval: float = POLL_SECONDS, kinds: tuple[str, ...] | None = None,
                 snap: Callable[..., dict[str, dict[str, Any]]] = snapshot, keep: int = 200, idle_stop: float = 0.0):
        self.interval = interval
        self.idle_stop = idle_stop
        if kinds is None:
            kinds = tuple(k for k in WATCHED if not (sys.platform == "darwin" and k in ("gamepad", "monitor")))
        self.kinds = kinds
        self.snap = snap
        self.keep = keep
        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self.current: dict[str, dict[str, Any]] = {}
        self.ports_seen: dict[str, list[str]] = {}       # identity -> ports it was on (to follow a renumbered port)
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[str, float] = {}
        self.started_at = 0.0
        self.last_poll = 0.0
        self.last_used = time.monotonic()
        self.ready = threading.Event()

    # ------------------------------------------------------------ polling
    def _due(self, kind: str) -> bool:
        now = time.monotonic()
        if now - self._last.get(kind, -1e9) >= SLOW.get(kind, 0.0):
            self._last[kind] = now
            return True
        return False

    def poll(self) -> list[dict[str, Any]]:
        """One look: update ``current`` and add the events. The first look only sets what is there."""
        try:
            new = self.snap(self.kinds, previous=self.current, due=self._due)
        except TypeError:
            new = self.snap(self.kinds)
        first = not self.ready.is_set()
        out: list[dict[str, Any]] = []
        with self._cond:
            described = {k: (self.current[k] if k in self.current and self.current[k].get("port") == v.get("port")
                             and _same(self.current[k], v) else describe(v)) for k, v in new.items()}
            changes = [] if first else diff(self.current, described)
            for kind, it in changes:
                ev = {"seq": 0, "event": kind, "time": time.time(), "item": it}
                if kind == "connected":
                    seen = [p for p in self.ports_seen.get(it["id"], []) if p and p != it.get("port")]
                    if seen:
                        ev["was_port"] = seen[-1]
                self.seq += 1
                ev["seq"] = self.seq
                out.append(ev)
            for k, v in described.items():
                p = v.get("port")
                if p:
                    lst = self.ports_seen.setdefault(k, [])
                    if p not in lst:
                        lst.append(p)
            self.current = described
            self.events = (self.events + out)[-self.keep:]
            self.last_poll = time.monotonic()
            self._cond.notify_all()
        self.ready.set()
        return out

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.idle_stop and time.monotonic() - self.last_used > self.idle_stop:
                self._stop.set()        # nobody has asked for a while (the builder page was closed): stop looking
                break
            try:
                self.poll()
            except Exception:       # detection must never take the builder down
                pass
            self._stop.wait(self.interval)

    def start(self) -> "Watcher":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self.started_at = self.last_used = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True, name="edge-hotplug")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    # ------------------------------------------------------------ reading
    def wait(self, since: int, timeout: float = 20.0) -> dict[str, Any]:
        """Events after ``since`` (waits up to ``timeout`` s for one), what is connected now, and the last number."""
        self.last_used = time.monotonic()
        self.ready.wait(min(timeout, 10.0))
        deadline = time.monotonic() + timeout
        with self._cond:
            if since > self.seq:            # the watcher was restarted: start again from its numbers
                since = 0
            while not any(e["seq"] > since for e in self.events) and not self._stop.is_set():
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            evs = [e for e in self.events if e["seq"] > since]
            return {"seq": self.seq, "events": evs, "connected": list(self.current.values()),
                    "ports_seen": {k: v for k, v in self.ports_seen.items() if len(v) > 1}}


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    skip = {"identified", "label", "where"}
    return {k: v for k, v in a.items() if k not in skip} == {k: v for k, v in b.items() if k not in skip}


# ============================================================================ is the experiment's hardware there?
NOT_PHYSICAL = {"sim_eyetracker", "sim_eeg", "sim_physio", "sim_inputs", "mouse_gaze", "ttl_loopback", "lsl_markers",
                "udp_messages"}


def _opt(d: dict[str, Any], k: str) -> str:
    return str((d.get("options") or {}).get(k) or d.get(k) or "").strip()


def presence(devices: list[dict[str, Any]], items: list[dict[str, Any]],
             ports_seen: dict[str, list[str]] | None = None) -> dict[str, dict[str, Any]]:
    """For each experiment device: {state: connected | missing | unknown, detail, item, port_now}.

    unknown = EDGE can't tell from here (simulated devices, network devices, a Windows parallel port address)."""
    ports_seen = ports_seen or {}
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_kind.setdefault(it.get("kind", ""), []).append(it)
    out: dict[str, dict[str, Any]] = {}
    for d in devices or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        t, did = str(d.get("type") or ""), str(d["id"])
        res: dict[str, Any] = {"state": "unknown", "detail": ""}
        if t in NOT_PHYSICAL:
            res["detail"] = "nothing to plug in"
        elif t in ("serial_inputs", "ttl_serial") or (t == "mindware" and _opt(d, "trigger") in ("", "serial")) \
                or (t == "trigger_adapter" and _conn(d) == "serial"):
            res = _serial_presence(_opt(d, "port"), by_kind.get("serial", []), ports_seen)
        elif t == "trigger_adapter" and _conn(d) == "lsl":
            res["detail"] = "a marker stream EDGE creates itself"
        elif t in ("parallel_port", "parallel_inputs") or (t == "trigger_adapter" and _conn(d) == "parallel"):
            addr = _opt(d, "address") or ("0x378" if t != "parallel_inputs" else "0x379")
            if addr.startswith("/dev/"):
                hit = next((x for x in by_kind.get("parallel", []) if x.get("port") == addr), None)
                res = _found(hit, addr) if hit else {"state": "missing", "detail": f"{addr} not found"}
            else:
                res["detail"] = "a port address: EDGE can't see whether a cable is plugged in"
        elif t == "lsl_inlet" or (t == "gtec" and _opt(d, "mode") in ("", "lsl")) or (t == "mindware" and _opt(d, "lsl_name")):
            name = _opt(d, "name") if t == "lsl_inlet" else _opt(d, "lsl_name")
            typ = _opt(d, "stream_type") if t == "lsl_inlet" else _opt(d, "lsl_type")
            src = _opt(d, "source_id") if t == "lsl_inlet" else ""
            cands = [x for x in by_kind.get("lsl", []) if (not name or x.get("name") == name)
                     and (not typ or str(x.get("lsl_type", "")).lower() == typ.lower()) and (not src or x.get("source_id") == src)]
            label = name or typ or "any"
            res = _found(cands[0], f"stream {label}") if cands else {"state": "missing", "detail": f"no LSL stream “{label}” right now"}
        elif t == "tobii":
            serial, addr = _opt(d, "serial"), _opt(d, "address")
            cands = [x for x in by_kind.get("tobii", []) if (not serial or x.get("serial_number") == serial)
                     and (not addr or x.get("address") == addr)]
            res = _found(cands[0], "") if cands else {"state": "missing", "detail": "no Tobii eye tracker found"}
        elif t == "gazepoint":
            host = _opt(d, "host") or "127.0.0.1"
            if host not in ("127.0.0.1", "localhost", "::1"):
                res["detail"] = "on another computer: EDGE only looks on this one"
            else:
                c = by_kind.get("gazepoint", [])
                res = _found(c[0], "") if c else {"state": "missing", "detail": "Gazepoint Control is not running"}
        elif t == "labjack":
            model = _opt(d, "model") or "U3"
            c = [x for x in by_kind.get("labjack", []) if str(x.get("model", "U3")).upper() == model.upper()]
            res = _found(c[0], "") if c else {"state": "missing", "detail": f"no LabJack {model} found"}
        elif t == "voice_key":
            want = _opt(d, "device")
            c = by_kind.get("audio", [])
            if not want:
                res = _found(c[0], "the default microphone") if c else ({"state": "missing", "detail": "no microphone found"}
                                                                         if "audio" in by_kind or not c else res)
            else:
                hit = next((x for x in c if want.isdigit() and str(x.get("index")) == want or want.lower() in str(x.get("name", "")).lower()), None)
                res = _found(hit, "") if hit else ({"state": "missing", "detail": f"no microphone “{want}”"} if c else res)
        elif t == "gtec" and _opt(d, "mode") == "unicorn":
            serial = _opt(d, "serial")
            c = [x for x in by_kind.get("serial", []) if serial and serial in _txt(x)]
            res = _found(c[0], serial) if c else res
        out[did] = res
    return out


def _conn(d: dict[str, Any]) -> str:
    try:
        from .devices.adapters import preset
        return preset(d.get("options") or {})["connection"]
    except Exception:
        return ""


def _txt(x: dict[str, Any]) -> str:
    return " ".join(str(x.get(k) or "") for k in ("description", "manufacturer", "product", "name"))


def _found(it: dict[str, Any] | None, detail: str) -> dict[str, Any]:
    if not it:
        return {"state": "missing", "detail": detail}
    ident = it.get("identified") or {}
    return {"state": "connected", "detail": detail or ident.get("name") or it.get("name") or "", "item": it.get("id"),
            "label": ident.get("name") or it.get("label") or it.get("name")}


def _serial_presence(port: str, serial: list[dict[str, Any]], ports_seen: dict[str, list[str]]) -> dict[str, Any]:
    if not port:
        if len(serial) == 1:
            return _found(serial[0], f"the only serial port, {serial[0].get('port')}")
        if not serial:
            return {"state": "missing", "detail": "no serial port found"}
        return {"state": "unknown", "detail": f"{len(serial)} serial ports: set the port"}
    norm = port.lower()
    hit = next((x for x in serial if str(x.get("port", "")).lower() == norm), None)
    if hit:
        return _found(hit, port)
    for x in serial:            # the same device, plugged into another socket: it got another port name
        if norm in [p.lower() for p in ports_seen.get(x.get("id", ""), [])]:
            r = _found(x, f"now on {x.get('port')}")
            r.update(state="moved", port_now=x.get("port"))
            return r
    return {"state": "missing", "detail": f"nothing on {port}"}


# ============================================================================ the optional "Identify" handshake (Cedrus XID only)
def identify_cedrus(port: str, timeout: float = 0.5) -> dict[str, Any]:  # pragma: no cover - needs hardware
    """Ask a Cedrus XID device what it is, with its read-only query commands (documented in Cedrus's XID protocol
    reference): ``_c1`` (protocol: '_xid0' = XID mode), ``_d1`` (device name), ``_d2`` (product id: 0 Lumina,
    1 SV-1, 2 RB pad, S StimTracker), ``_d3`` (model id). Nothing on the device is changed."""
    try:
        import serial
    except ImportError as e:
        raise RuntimeError("pyserial is required: pip install pyserial") from e
    products = {"0": "Lumina", "1": "SV-1 voice key", "2": "RB response pad", "S": "StimTracker", "4": "c-pod"}
    out: dict[str, Any] = {"port": port}
    with serial.Serial(port, 115200, timeout=timeout, write_timeout=timeout) as s:
        s.reset_input_buffer()
        for cmd, key in ((b"_c1", "protocol"), (b"_d1", "name"), (b"_d2", "product"), (b"_d3", "model")):
            s.write(cmd)
            time.sleep(0.05)
            out[key] = s.read(64).decode("ascii", errors="replace").strip()
    if not out.get("protocol", "").startswith("_xid"):
        out["note"] = "the device didn't answer like a Cedrus XID device"
    out["product_name"] = products.get(out.get("product", "")[:1], "")
    return out


def scan(lsl_timeout: float = 1.0) -> list[dict[str, Any]]:
    """Everything connected now, identified (one look, for ``edge scan`` and Find devices)."""
    return [describe(it) for it in snapshot(lsl_timeout=lsl_timeout).values()]


def format_item(it: dict[str, Any]) -> str:
    ident = it.get("identified") or {}
    sure = {"sure": "", "probably": "probably ", "ask": ""}.get(ident.get("certainty", ""), "")
    where = it.get("where") or ""
    bits = [f"{sure}{ident.get('name') or it.get('name')}"]
    if where and where not in bits[0]:
        bits.append(f"on {where}")
    if it.get("vid"):
        bits.append(f"USB {it['vid']}:{it.get('pid', '')}")
    if it.get("serial_number"):
        bits.append(f"serial {it['serial_number']}")
    return ", ".join(bits)
