"""Gamepads and joysticks in the experiment window (pyglet.input), for the ``gamepad`` item.

Game controllers that SDL's mapping database knows (Xbox, PlayStation, Switch Pro, most USB pads) are opened as
pyglet *controllers*, with named buttons; other joysticks (flight sticks, custom USB boxes) as pyglet *joysticks*,
whose buttons are button1, button2 … Everything becomes InputEvents on the master clock::

    InputEvent("gamepad", "a", t, down, meta={"gamepad": 0, "name": "Xbox Controller"})
    InputEvent("gamepad_axis", "lx", t, meta={"gamepad": 0, "value": -0.73})

Names follow EDGE's (and the browser's standard Gamepad mapping): a b x y lb rb lt rt back start guide ls rs and
the d-pad up down left right; sticks lx ly rx ry from -1 to 1 with up and right positive, triggers lt rt from 0 to 1.

pyglet reports controller input when its event loop runs, which EDGE does once per frame, so a gamepad's response
time has the resolution of one frame (about 17 ms at 60 Hz), unlike the keyboard's OS timestamps.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from ..backends.base import InputEvent
from ..clock import now

CONTROLLER_BUTTONS = {"leftshoulder": "lb", "rightshoulder": "rb", "leftstick": "ls", "rightstick": "rs",
                      "dpup": "up", "dpdown": "down", "dpleft": "left", "dpright": "right"}
JOY_AXES = {"x": "lx", "y": "ly", "rx": "rx", "ry": "ry", "z": "lt", "rz": "rt"}
_TRIGGER_DOWN = 0.5          # a trigger pressed this far also counts as the button lt / rt


class GamepadHub:
    """Listens to every connected controller/joystick and turns their events into InputEvents (``push``)."""

    def __init__(self, push: Callable[[InputEvent], None], clock: Callable[[], float] = now):
        self.push = push
        self.clock = clock
        self.devices: list[Any] = []          # index = the gamepad number
        self.names: list[str] = []
        self.axes: dict[int, dict[str, float]] = {}
        self._held: dict[tuple[int, str], bool] = {}

    # ------------------------------------------------------------------ opening (needs pyglet and a display)
    def open(self, window: Any = None) -> list[str]:  # pragma: no cover - needs hardware
        import pyglet.input
        try:
            controllers = list(pyglet.input.get_controllers())
        except Exception:
            controllers = []
        taken = {id(getattr(c, "device", None)) for c in controllers}
        try:
            joysticks = [j for j in pyglet.input.get_joysticks() if id(getattr(j, "device", None)) not in taken]
        except Exception:
            joysticks = []
        for c in controllers:
            try:
                c.open(window=window)
            except TypeError:
                c.open()
            except Exception:
                continue
            c.push_handlers(on_button_press=self.on_button_press, on_button_release=self.on_button_release,
                            on_stick_motion=self.on_stick_motion, on_trigger_motion=self.on_trigger_motion,
                            on_dpad_motion=self.on_dpad_motion)
            self._add(c, getattr(c, "name", "") or "controller")
        for j in joysticks:
            try:
                j.open(window=window)
            except TypeError:
                j.open()
            except Exception:
                continue
            j.push_handlers(on_joybutton_press=self.on_joybutton_press, on_joybutton_release=self.on_joybutton_release,
                            on_joyaxis_motion=self.on_joyaxis_motion, on_joyhat_motion=self.on_joyhat_motion)
            self._add(j, getattr(getattr(j, "device", None), "name", "") or "joystick")
        return list(self.names)

    def poll(self) -> None:  # pragma: no cover - needs hardware
        """Let pyglet deliver what the controllers sent since the last frame."""
        if not self.devices:
            return
        try:
            import pyglet.app
            loop = pyglet.app.platform_event_loop
            loop.dispatch_posted_events()           # XInput (Windows) posts its events from a thread
            if sys.platform.startswith("linux"):
                loop.step(0)                        # evdev devices are read by the event loop's select()
        except Exception:
            pass

    def close(self) -> None:  # pragma: no cover - needs hardware
        for d in self.devices:
            try:
                d.close()
            except Exception:
                pass
        self.devices, self.names = [], []

    # ------------------------------------------------------------------ events (plain methods: testable without pyglet)
    def _add(self, dev: Any, name: str) -> None:
        self.devices.append(dev)
        self.names.append(str(name))
        self.axes[len(self.devices) - 1] = {}

    def _index(self, dev: Any) -> int:
        for i, d in enumerate(self.devices):
            if d is dev:
                return i
        self._add(dev, getattr(dev, "name", "") or "gamepad")
        return len(self.devices) - 1

    def _button(self, dev: Any, name: str, down: bool) -> None:
        i = self._index(dev)
        if self._held.get((i, name), False) == down:
            return
        self._held[(i, name)] = down
        self.push(InputEvent("gamepad", name, self.clock(), down, meta={"gamepad": i, "name": self.names[i]}))

    def _axis(self, dev: Any, axis: str, value: float) -> None:
        i = self._index(dev)
        value = max(-1.0, min(1.0, float(value)))
        if self.axes[i].get(axis) == value:
            return
        self.axes[i][axis] = value
        self.push(InputEvent("gamepad_axis", axis, self.clock(), True,
                             meta={"gamepad": i, "name": self.names[i], "value": value}))

    def on_button_press(self, controller: Any, button: str) -> None:
        self._button(controller, CONTROLLER_BUTTONS.get(button, button), True)

    def on_button_release(self, controller: Any, button: str) -> None:
        self._button(controller, CONTROLLER_BUTTONS.get(button, button), False)

    def on_stick_motion(self, controller: Any, stick: str, *xy: Any) -> None:
        # pyglet 2.1: (controller, stick, Vec2); 2.0: (controller, stick, x, y). Up is already positive.
        x, y = (xy[0].x, xy[0].y) if len(xy) == 1 else (xy[0], xy[1])
        pre = "l" if "left" in stick else "r"
        self._axis(controller, f"{pre}x", x)
        self._axis(controller, f"{pre}y", y)

    def on_trigger_motion(self, controller: Any, trigger: str, value: float) -> None:
        name = "lt" if "left" in trigger else "rt"
        v = (float(value) + 1) / 2 if float(value) < 0 else float(value)     # some drivers report -1..1
        self._axis(controller, name, v)
        self._button(controller, name, v >= _TRIGGER_DOWN)

    def on_dpad_motion(self, controller: Any, *v: Any) -> None:
        # pyglet 2.1: (controller, Vec2); 2.0: (controller, left, right, up, down)
        if len(v) == 1:
            x, y = v[0].x, v[0].y
            left, right, up, down = x < 0, x > 0, y > 0, y < 0
        else:
            left, right, up, down = (bool(b) for b in v[:4])
        for name, on in (("left", left), ("right", right), ("up", up), ("down", down)):
            self._button(controller, name, on)

    def on_joybutton_press(self, joystick: Any, button: int) -> None:
        self._button(joystick, f"button{int(button) + 1}", True)

    def on_joybutton_release(self, joystick: Any, button: int) -> None:
        self._button(joystick, f"button{int(button) + 1}", False)

    def on_joyaxis_motion(self, joystick: Any, axis: str, value: float) -> None:
        name = JOY_AXES.get(axis, axis)
        v = float(value)
        if name in ("ly", "ry"):
            v = -v             # joysticks report down as positive; EDGE's up is positive
        elif name in ("lt", "rt"):
            v = (v + 1) / 2
        self._axis(joystick, name, v)

    def on_joyhat_motion(self, joystick: Any, hat_x: float, hat_y: float) -> None:
        for name, on in (("left", hat_x < 0), ("right", hat_x > 0), ("up", hat_y > 0), ("down", hat_y < 0)):
            self._button(joystick, name, on)
