"""Hardware discovery for ``edge scan``, the builder's Find devices and the MCP ``scan_hardware`` tool.

One look at everything connected (see :mod:`edge.hotplug` for the detection backends and :mod:`edge.hardware_db`
for how each device is recognised). ``scan_all`` groups the items by kind; each item says what it is
(``what``, ``certainty``), the ways it can be added (``offers``) and, for compatibility, the first suggested
device entry (``suggested``).
"""

from __future__ import annotations

from typing import Any

SECTIONS = {"serial": "serial_ports", "lsl": "lsl_streams", "tobii": "tobii", "gazepoint": "gazepoint",
            "labjack": "labjack", "parallel": "parallel_ports", "gamepad": "gamepads", "audio": "audio_inputs",
            "monitor": "monitors"}
_HIDE = {"identified", "label", "where", "kind", "channels", "units", "id"}


def summarize(it: dict[str, Any]) -> dict[str, Any]:
    """A flat, readable entry for one identified item."""
    ident = it.get("identified") or {}
    out: dict[str, Any] = {"what": ident.get("name") or it.get("name"), "certainty": ident.get("certainty")}
    for k, v in it.items():
        if k in _HIDE or v in (None, "", [], {}):
            continue
        out[k] = v
    if it.get("channels"):
        out["channel_names"] = it["channels"]
    out["identity"] = it.get("id")
    offers = ident.get("offers") or []
    first = next((o for o in offers if o.get("device")), None)
    if first:
        d = first["device"]
        out["suggested"] = {"id": d.get("id"), "type": d["type"], "options": d.get("options") or {}}
    if offers:
        out["offers"] = offers
    if ident.get("question"):
        out["question"] = ident["question"]
    return out


def scan_all(timeout: float = 2.0) -> dict[str, list[dict[str, Any]]]:
    from .hotplug import scan
    found: dict[str, list[dict[str, Any]]] = {name: [] for name in SECTIONS.values()}
    for it in scan(lsl_timeout=timeout):
        found.setdefault(SECTIONS.get(it.get("kind", ""), it.get("kind", "other")), []).append(summarize(it))
    return found


# the single-kind helpers of earlier versions
def _one(fn: Any, *args: Any) -> list[dict[str, Any]]:
    from .hotplug import describe, identity
    return [summarize(describe({**x, "id": identity(x)})) for x in fn(*args)]


def scan_lsl(timeout: float = 2.0) -> list[dict[str, Any]]:
    from .hotplug import list_lsl
    return _one(list_lsl, timeout)


def scan_serial() -> list[dict[str, Any]]:
    from .hotplug import list_serial
    return _one(list_serial)


def scan_tobii() -> list[dict[str, Any]]:
    from .hotplug import list_tobii
    return _one(list_tobii)


def scan_gazepoint(host: str = "127.0.0.1", port: int = 4242, timeout: float = 0.5) -> list[dict[str, Any]]:
    from .hotplug import list_gazepoint
    return _one(list_gazepoint, host, port, timeout)
