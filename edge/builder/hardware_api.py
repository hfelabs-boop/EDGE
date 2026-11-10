"""Plug and play in the builder: /api/hardware/… (behind the server's guard like every other route).

* ``GET /api/hardware/events``            what is connected now and the latest event number (starts the watcher)
* ``GET /api/hardware/events?since=N``    waits (up to ``wait`` s, default 20) for connect/disconnect events after N
* ``GET /api/hardware/now``               everything connected now, identified (Find devices)
* ``POST /api/hardware/status``           {devices: [...]} -> whether each of the experiment's devices is connected
* ``POST /api/hardware/identify``         {id}: the optional Cedrus "Identify" query (only for a device recognised as
                                          Cedrus; the only time EDGE writes to a port it wasn't told to use)

The watcher (edge/hotplug.py) runs while a builder page asks for events, and stops a minute after the last one.
"""

from __future__ import annotations

import threading
from typing import Any

IDLE_STOP = 60.0
_lock = threading.Lock()


def watcher(app: Any):
    from ..hotplug import Watcher
    with _lock:
        w = getattr(app, "hardware_watcher", None)
        if w is None:
            w = app.hardware_watcher = Watcher(idle_stop=IDLE_STOP)
        if not w.running:
            w.start()
        return w


def _num(query: dict[str, str], key: str, default: float, lo: float, hi: float) -> float:
    from .server import BadRequest
    v = query.get(key)
    if v in (None, ""):
        return default
    try:
        x = float(v)
    except ValueError:
        raise BadRequest(f"?{key}= must be a number") from None
    if x != x:
        raise BadRequest(f"?{key}= must be a number")
    return max(lo, min(hi, x))


def handle(app: Any, method: str, path: str, query: dict[str, str], body: Any) -> tuple[dict[str, Any], int]:
    from .server import BadRequest
    from .. import hotplug
    if method == "GET" and path == "/api/hardware/events":
        w = watcher(app)
        if query.get("since") in (None, ""):
            w.ready.wait(5.0)
            r = w.wait(w.seq, timeout=0)
            return {**r, "events": []}, 200
        since = int(_num(query, "since", 0, 0, 1e12))
        return w.wait(since, timeout=_num(query, "wait", 20.0, 0.0, 25.0)), 200
    if method == "GET" and path == "/api/hardware/now":
        w = watcher(app)
        w.ready.wait(5.0)
        r = w.wait(w.seq, timeout=0)
        return {"seq": r["seq"], "connected": r["connected"], "ports_seen": r["ports_seen"], "fake": bool(hotplug.fake_items() is not None)}, 200
    if method == "POST" and path == "/api/hardware/status":
        if not isinstance(body, dict) or not isinstance(body.get("devices"), list):
            raise BadRequest("the request needs 'devices' (a list)")
        w = watcher(app)
        w.ready.wait(5.0)
        return {"seq": w.seq, "status": hotplug.presence(body["devices"], list(w.current.values()), w.ports_seen)}, 200
    if method == "POST" and path == "/api/hardware/identify":
        if not isinstance(body, dict) or not isinstance(body.get("id"), str):
            raise BadRequest("the request needs 'id'")
        w = watcher(app)
        it = w.current.get(body["id"])
        if not it:
            raise BadRequest("that device is not connected now")
        if (it.get("identified") or {}).get("identify") != "cedrus" or it.get("kind") != "serial":
            raise BadRequest("only devices recognised as Cedrus can be asked what they are")
        if hotplug.fake_items() is not None:
            return {"ok": True, "port": it.get("port"), "protocol": "_xid0", "product_name": "RB response pad",
                    "name": it.get("description") or "", "fake": True}, 200
        try:
            return {"ok": True, **hotplug.identify_cedrus(str(it["port"]))}, 200
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}, 200
    return {"error": "not found"}, 404
