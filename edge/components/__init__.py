"""Component registry. Third-party components register via the ``edge.components`` entry point."""

from __future__ import annotations

from typing import Type

from .base import Component, Results

_REGISTRY: dict[str, Type[Component]] = {}
_eps_loaded = False


def register_component(cls: Type[Component]) -> Type[Component]:
    if not cls.type_name:
        raise ValueError(f"{cls.__name__} must define type_name")
    _REGISTRY[cls.type_name] = cls
    return cls


def component_registry() -> dict[str, Type[Component]]:
    global _eps_loaded
    if not _eps_loaded:
        _eps_loaded = True
        try:
            from importlib.metadata import entry_points
            for ep in entry_points(group="edge.components"):
                try:
                    register_component(ep.load())
                except Exception as e:  # pragma: no cover
                    print(f"[edge] failed to load component plugin {ep.name}: {e}")
        except Exception:  # pragma: no cover
            pass
    return dict(_REGISTRY)


from . import eyetracking, logic, responses, stimuli  # noqa: E402

for _mod in (stimuli, responses, eyetracking, logic):
    for _cls in _mod.COMPONENTS:
        register_component(_cls)

__all__ = ["Component", "Results", "register_component", "component_registry"]
