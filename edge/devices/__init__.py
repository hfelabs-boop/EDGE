"""Hardware drivers and the driver registry.

Built-in drivers are registered on import. Third-party packages can add drivers
through the ``edge.devices`` entry-point group (see pyproject.toml) or by calling
:func:`register` at import time.
"""

from __future__ import annotations

from typing import Type

from .base import Device, DeviceError, StreamInfo

_REGISTRY: dict[str, Type[Device]] = {}
_entry_points_loaded = False


def register(cls: Type[Device]) -> Type[Device]:
    if not cls.type_name or cls.type_name == "base":
        raise ValueError(f"{cls.__name__} must define a unique type_name")
    _REGISTRY[cls.type_name] = cls
    return cls


def _load_entry_points() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group="edge.devices"):
            try:
                register(ep.load())
            except Exception as e:  # pragma: no cover - plugin bugs must not break EDGE
                print(f"[edge] failed to load device plugin {ep.name}: {e}")
    except Exception:  # pragma: no cover
        pass


def device_registry() -> dict[str, Type[Device]]:
    _load_entry_points()
    return dict(_REGISTRY)


def create_device(type_name: str, id: str, options: dict | None = None, **kw) -> Device:
    reg = device_registry()
    if type_name not in reg:
        raise DeviceError(f"unknown device type '{type_name}'. Available: {', '.join(sorted(reg))}")
    return reg[type_name](id, options or {}, **kw)


# Built-in drivers (each module registers itself; none import optional deps at module level).
from . import simulated, lsl, gazepoint, tobii, gtec, mindware, triggers, inputs, adapters, messages  # noqa: E402,F401

__all__ = ["Device", "DeviceError", "StreamInfo", "register", "device_registry", "create_device"]
