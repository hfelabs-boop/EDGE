"""Hardware discovery for ``edge scan`` and the builder's device panel."""

from __future__ import annotations

import socket
from typing import Any


def scan_lsl(timeout: float = 2.0) -> list[dict[str, Any]]:
    try:
        import pylsl
        streams = pylsl.resolve_streams(timeout)
    except Exception:
        return []
    return [{"name": s.name(), "type": s.type(), "channels": s.channel_count(), "srate": s.nominal_srate(),
             "source_id": s.source_id(), "host": s.hostname(), "suggested": {"type": "lsl_inlet",
                                                                              "options": {"name": s.name()}}}
            for s in streams]


def scan_serial() -> list[dict[str, Any]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        desc = f"{p.description} {p.manufacturer or ''}".lower()
        guess = "ttl_serial"
        proto = "cedrus" if "cedrus" in desc or "stimtracker" in desc else "byte"
        out.append({"port": p.device, "description": p.description, "vid_pid": f"{p.vid}:{p.pid}" if p.vid else "",
                    "suggested": {"type": guess, "options": {"port": p.device, "protocol": proto}}})
    return out


def scan_tobii() -> list[dict[str, Any]]:
    try:
        import tobii_research as tr
        return [{"model": e.model, "serial": e.serial_number, "address": e.address,
                 "suggested": {"type": "tobii", "options": {"address": e.address}}} for e in tr.find_all_eyetrackers()]
    except Exception:
        return []


def scan_gazepoint(host: str = "127.0.0.1", port: int = 4242, timeout: float = 0.5) -> list[dict[str, Any]]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return [{"host": host, "port": port, "suggested": {"type": "gazepoint", "options": {"host": host, "port": port}}}]
    except OSError:
        return []


def scan_all(timeout: float = 2.0) -> dict[str, list[dict[str, Any]]]:
    return {"lsl_streams": scan_lsl(timeout), "serial_ports": scan_serial(), "tobii": scan_tobii(),
            "gazepoint": scan_gazepoint()}
