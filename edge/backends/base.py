"""Display/input backend interface.

Components never call a graphics library directly. They ask the backend for
stimulus objects (``make_text``, ``make_shape``, ``make_image``...) and call
``draw()`` on them each frame. This keeps experiments portable across
backends: real windows (pyglet/OpenGL today), the headless backend for
testing and virtual-participant dry runs, and future backends (browser,
VR headsets).

Coordinates handed to backends are always pixels, origin at the window centre,
y pointing up. Unit conversion happens in :meth:`Backend.to_px`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class InputEvent:
    kind: str                 # "key" | "mouse" | "button"
    name: str                 # key name ("space", "f", "left") or mouse button
    time: float               # master clock
    down: bool = True
    pos: tuple[float, float] | None = None
    device: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def parse_color(c: Any) -> tuple[int, int, int, int]:
    """Accepts '#rrggbb', '#rrggbbaa', named colors, (r,g,b[,a]) 0-255 or 0-1 floats, PsychoPy-style -1..1."""
    if c is None:
        return (0, 0, 0, 0)
    if isinstance(c, str) and c.strip().lstrip("$").startswith(("[", "(")):
        import ast
        try:
            c = list(ast.literal_eval(c.strip().lstrip("$")))   # "[1,-1,-1]" from a conditions file
        except (ValueError, SyntaxError):
            raise ValueError(f"unknown color '{c}'") from None
    if isinstance(c, str):
        s = c.strip().lower()
        if s in NAMED_COLORS:
            s = NAMED_COLORS[s]
        if s.startswith("#"):
            h = s[1:]
            if len(h) == 3:
                h = "".join(ch * 2 for ch in h)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            a = int(h[6:8], 16) if len(h) == 8 else 255
            return (r, g, b, a)
        raise ValueError(f"unknown color '{c}'")
    vals = list(c)
    if all(isinstance(v, (int, float)) for v in vals):
        if any(v < 0 for v in vals):  # PsychoPy rgb (-1..1)
            vals = [round((v + 1) * 127.5) for v in vals]
        elif all(v <= 1.0 for v in vals) and any(isinstance(v, float) for v in vals):
            vals = [round(v * 255) for v in vals]
        vals = [int(max(0, min(255, v))) for v in vals]
        if len(vals) == 3:
            vals.append(255)
        return tuple(vals[:4])  # type: ignore[return-value]
    raise ValueError(f"unknown color {c!r}")


NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#00c000", "lime": "#00ff00",
    "blue": "#0000ff", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff", "gray": "#808080",
    "grey": "#808080", "orange": "#ffa500", "purple": "#800080", "pink": "#ffc0cb", "brown": "#8b4513",
    "darkgray": "#404040", "lightgray": "#c0c0c0", "transparent": "#00000000",
}


class Stim:
    """A drawable stimulus owned by a backend."""

    def __init__(self, kind: str, props: dict[str, Any]):
        self.kind = kind
        self.props = dict(props)

    def set(self, **props: Any) -> None:
        self.props.update(props)

    def draw(self) -> None:  # pragma: no cover - backend specific
        raise NotImplementedError

    def contains(self, x: float, y: float) -> bool:
        """Hit test in px (used for mouse clicks / gaze ROIs)."""
        p = self.props
        cx, cy = p.get("pos", (0, 0))
        if self.kind == "circle":
            return math.hypot(x - cx, y - cy) <= p.get("radius", 0)
        w, h = p.get("size", (0, 0))
        return abs(x - cx) <= w / 2 and abs(y - cy) <= h / 2

    def release(self) -> None:
        pass


class Backend:
    name = "base"
    size: tuple[int, int] = (1280, 720)
    refresh_rate: float = 60.0
    clock: Callable[[], float]

    @property
    def frame_interval(self) -> float:
        return 1.0 / self.refresh_rate

    # -------------------------------------------------------- lifecycle
    def open(self, window: dict[str, Any]) -> None: ...
    def close(self) -> None: ...

    def flip(self) -> float:
        """Present the back buffer. Returns the master-clock time of the flip."""
        raise NotImplementedError

    def set_background(self, color: Any) -> None: ...

    # -------------------------------------------------------- stimuli
    def make_text(self, **props: Any) -> Stim: raise NotImplementedError
    def make_shape(self, shape: str, **props: Any) -> Stim: raise NotImplementedError
    def make_image(self, **props: Any) -> Stim: raise NotImplementedError
    def make_movie(self, **props: Any) -> Stim: raise NotImplementedError

    def draw_calibration_target(self, x: float, y: float, r: float) -> None:
        outer = self.make_shape("circle", pos=(x, y), radius=r, fill="white")
        inner = self.make_shape("circle", pos=(x, y), radius=max(2, r / 4), fill="black")
        outer.draw()
        inner.draw()

    # -------------------------------------------------------- sound
    def play_sound(self, source: Any, volume: float = 1.0, **kw: Any) -> Any: ...
    def stop_sound(self, handle: Any) -> None: ...

    # -------------------------------------------------------- input
    def poll_events(self) -> list[InputEvent]:
        return []

    def mouse_pos(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def mouse_buttons(self) -> tuple[bool, bool, bool]:
        return (False, False, False)

    def check_escape(self) -> bool:
        return False

    def wait_for_key(self, keys: list[str] | None = None) -> InputEvent: raise NotImplementedError

    # -------------------------------------------------------- units
    def to_px(self, value: Any, units: str, monitor: dict[str, Any] | None = None, axis: str = "both") -> Any:
        """Convert a scalar or (x, y) pair from experiment units to pixels."""
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            if len(value) == 2:
                return (self._conv(value[0], units, monitor, "x" if axis == "both" else axis),
                        self._conv(value[1], units, monitor, "y" if axis == "both" else axis))
            return tuple(self._conv(v, units, monitor, "y") for v in value)
        return self._conv(value, units, monitor, "y" if axis == "both" else axis)

    def _conv(self, v: float, units: str, monitor: dict[str, Any] | None, axis: str) -> float:
        w, h = self.size
        v = float(v)
        if units == "px":
            return v
        if units == "norm":
            return v * (w / 2 if axis == "x" else h / 2)
        if units == "height":
            return v * h
        if units == "deg":
            m = monitor or {}
            width_cm = float(m.get("width_cm", 53.0))
            dist = float(m.get("distance_cm", 60.0))
            px_per_cm = w / width_cm
            return 2 * dist * math.tan(math.radians(v) / 2) * px_per_cm
        raise ValueError(f"unknown units '{units}'")

    def from_px(self, value: tuple[float, float], units: str, monitor: dict[str, Any] | None = None) -> tuple[float, float]:
        sx = self._conv(1.0, units, monitor, "x")
        sy = self._conv(1.0, units, monitor, "y")
        return (value[0] / sx, value[1] / sy)
