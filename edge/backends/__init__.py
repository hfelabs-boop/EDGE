from .base import Backend, InputEvent, Stim, parse_color
from .headless import HeadlessBackend


def create_backend(name: str, **kw) -> Backend:
    if name == "headless":
        return HeadlessBackend(**kw)
    if name == "pyglet":
        from .pyglet_backend import PygletBackend
        return PygletBackend()
    raise ValueError(f"unknown backend '{name}' (available: pyglet, headless)")


__all__ = ["Backend", "InputEvent", "Stim", "parse_color", "HeadlessBackend", "create_backend"]
