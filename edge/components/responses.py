"""Response components: keyboard, mouse, rating slider."""

from __future__ import annotations

from typing import Any

from ..backends.base import InputEvent
from .base import Component


def _key_list(v: Any) -> list[str] | None:
    if v in (None, "", [], "any"):
        return None
    if isinstance(v, str):
        return [k.strip() for k in v.split(",") if k.strip()]
    return [str(k) for k in v]


class Keyboard(Component):
    type_name = "keyboard"
    category = "response"
    description = "Collect key presses with RT measured from the component's onset flip."
    props_schema = {
        "keys": {"type": "list", "default": None, "help": "allowed keys, e.g. [f, j]; empty = any"},
        "store": {"type": "choice", "choices": ["first", "last", "all"], "default": "first", "help": "which key to keep when several are pressed: first, last or all"},
        "correct": {"type": "str", "default": None, "help": "correct key (often an expression: $corr_key)"},
        "discard_previous": {"type": "bool", "default": True, "help": "ignore keys pressed before onset"},
        "record_release": {"type": "bool", "default": False, "help": "also store key-up times (durations)"},
        "response_marker": {"type": "str", "default": None,
                            "help": "marker sent at the moment of the response, e.g. $f'resp_{resp.keys}'"},
    }

    def prepare(self) -> None:
        super().prepare()
        self.allowed = _key_list(self.p["keys"])
        self.presses: list[tuple[str, float]] = []
        self.releases: dict[str, float] = {}
        self.out.update(keys=None, rt=None, corr=None)

    def on_start(self, t: float) -> None:
        self.session.notify_response_window(self, self.allowed, self.p["correct"])

    def on_event(self, ev: InputEvent) -> None:
        if ev.kind != "key":
            return
        if self.allowed is not None and ev.name not in self.allowed:
            return
        if self.p["discard_previous"] and self.t_start is not None and ev.time < self.t_start:
            return
        if not ev.down:
            if self.p["record_release"]:
                self.releases.setdefault(ev.name, ev.time)
            return
        self.presses.append((ev.name, ev.time))
        store = self.p["store"]
        if store == "first" and len(self.presses) > 1:
            return
        if store == "all":
            self.out["keys"] = [k for k, _ in self.presses]
            self.out["rt"] = [self.rt(tt) for _, tt in self.presses]
        else:
            self.out["keys"] = ev.name
            self.out["rt"] = self.rt(ev.time)
        corr = self.p["correct"]
        if corr is not None:
            first = self.out["keys"][0] if store == "all" else self.out["keys"]
            self.out["corr"] = int(str(first) == str(corr))
        self.out["time"] = ev.time
        self.finished = True
        self.send_response_marker(ev.time)

    def on_stop(self, t: float) -> None:
        if self.p["record_release"] and self.presses:
            k, tt = self.presses[0]
            if k in self.releases:
                self.out["duration"] = self.releases[k] - tt
        if self.out["keys"] is None and self.p["correct"] is not None:
            # no response: correct only if the correct answer was "no response"
            self.out["corr"] = int(str(self.p["correct"]).lower() in ("none", ""))


class Mouse(Component):
    type_name = "mouse"
    category = "response"
    description = "Mouse clicks, optionally restricted to clickable components (e.g. images/shapes)."
    props_schema = {
        "buttons": {"type": "list", "default": ["left"], "help": "buttons that count as a response: left, middle, right"},
        "clickable": {"type": "list", "default": [], "help": "ids of components in this routine that can be clicked"},
        "correct": {"type": "str", "default": None, "help": "id of the correct clickable component"},
        "track": {"type": "bool", "default": False, "help": "save the full mouse trajectory"},
        "response_marker": {"type": "str", "default": None, "help": "marker sent at the moment of the click"},
    }

    def prepare(self) -> None:
        super().prepare()
        self.out.update(x=None, y=None, button=None, clicked=None, rt=None, corr=None)
        self.path: list[tuple[float, float, float]] = []

    def on_start(self, t: float) -> None:
        self.session.notify_response_window(self, self.p["clickable"] or self.p["buttons"], self.p["correct"])

    def on_frame(self, t: float) -> None:
        if self.p["track"]:
            x, y = self.backend.mouse_pos()
            self.path.append((round(t - self.t_start, 4), round(x, 1), round(y, 1)))

    def on_event(self, ev: InputEvent) -> None:
        if ev.kind != "mouse" or not ev.down or ev.name not in self.p["buttons"] or ev.pos is None:
            return
        hit = None
        if self.p["clickable"]:
            for cid in self.p["clickable"]:
                comp = self.run.components.get(cid)
                if comp is not None and comp.status == 1 and hasattr(comp, "contains") and comp.contains(*ev.pos):
                    hit = cid
            if hit is None:
                return
        units = self.session.settings["window"]["units"]
        x, y = self.backend.from_px(ev.pos, units, self.session.settings["window"].get("monitor"))
        self.out.update(x=x, y=y, button=ev.name, clicked=hit, rt=self.rt(ev.time))
        if self.p["correct"] is not None:
            self.out["corr"] = int(hit == self.p["correct"])
        self.finished = True
        self.send_response_marker(ev.time)

    def on_stop(self, t: float) -> None:
        if self.p["track"]:
            self.out["path"] = self.path


class Slider(Component):
    type_name = "slider"
    category = "response"
    visual = True
    description = "Rating scale / visual analogue scale answered with the mouse (or arrow keys + return)."
    props_schema = {
        "ticks": {"type": "list", "default": [1, 2, 3, 4, 5, 6, 7], "help": "tick values; the first and last are the ends of the scale"},
        "labels": {"type": "list", "default": [], "help": "labels spread along the scale"},
        "granularity": {"type": "float", "default": 1, "help": "0 = continuous"},
        "pos": {"type": "vec2", "default": [0, -150], "help": "centre of the scale"},
        "size": {"type": "vec2", "default": [800, 30], "help": "width and height of the scale"},
        "color": {"type": "color", "default": "white", "help": "colour of the bar, ticks and labels"},
        "marker_color": {"type": "color", "default": "#ff9900", "help": "colour of the selected-value marker"},
        "units": {"type": "str", "default": "", "help": "empty = experiment default"},
        "require_confirm": {"type": "bool", "default": False, "help": "press return/space to confirm"},
    }

    def prepare(self) -> None:
        super().prepare()
        p = self.p
        self.cx, self.cy = self.px(p["pos"])
        self.w, self.h = self.px(p["size"])
        self.lo, self.hi = float(min(p["ticks"])), float(max(p["ticks"]))
        self.value: float | None = None
        self.history: list[tuple[float, float]] = []
        b = self.backend
        self.bar = b.make_shape("rect", pos=(self.cx, self.cy), size=(self.w, 4), fill=p["color"])
        self.tick_stims = [b.make_shape("rect", pos=(self._x_of(t), self.cy), size=(3, self.h), fill=p["color"])
                           for t in p["ticks"]]
        labels = p["labels"] or []
        n = len(labels)
        self.label_stims = [b.make_text(text=str(lab), height=24, color=p["color"],
                                        pos=(self.cx - self.w / 2 + (i / max(n - 1, 1)) * self.w, self.cy - self.h - 20))
                            for i, lab in enumerate(labels)]
        self.marker = b.make_shape("circle", pos=(self.cx, self.cy), radius=self.h / 2, fill=p["marker_color"])
        self.out.update(rating=None, rt=None)

    def _x_of(self, v: float) -> float:
        return self.cx - self.w / 2 + (v - self.lo) / ((self.hi - self.lo) or 1) * self.w

    def _v_of(self, x: float) -> float:
        v = self.lo + (x - (self.cx - self.w / 2)) / self.w * (self.hi - self.lo)
        g = float(self.p["granularity"] or 0)
        if g:
            v = round((v - self.lo) / g) * g + self.lo
        return min(max(v, self.lo), self.hi)

    def on_start(self, t: float) -> None:
        self.session.notify_response_window(self, self.p["ticks"], None)

    def on_frame(self, t: float) -> None:
        self.bar.draw()
        for s in self.tick_stims + self.label_stims:
            s.draw()
        if self.value is not None:
            self.marker.set(pos=(self._x_of(self.value), self.cy))
            self.marker.draw()

    def on_event(self, ev: InputEvent) -> None:
        if ev.kind == "mouse" and ev.down and ev.pos is not None:
            x, y = ev.pos
            if abs(y - self.cy) <= self.h * 1.5 and abs(x - self.cx) <= self.w / 2 + self.h:
                self._set(self._v_of(x), ev.time)
        elif ev.kind == "key" and ev.down:
            step = float(self.p["granularity"] or (self.hi - self.lo) / 100)
            if ev.name in ("left", "right"):
                cur = self.value if self.value is not None else (self.lo + self.hi) / 2
                self._set(min(max(cur + (step if ev.name == "right" else -step), self.lo), self.hi), ev.time, final=False)
            elif ev.name in ("return", "space") and self.value is not None:
                self.out["rt"] = self.rt(ev.time)
                self.finished = True

    def _set(self, v: float, t: float, final: bool = True) -> None:
        self.value = v
        self.history.append((round(t - self.t_start, 4), v))
        self.out["rating"] = int(v) if float(v).is_integer() else round(v, 4)
        if final and not self.p["require_confirm"]:
            self.out["rt"] = self.rt(t)
            self.finished = True

    def on_stop(self, t: float) -> None:
        self.out["history"] = self.history

    def contains(self, x: float, y: float) -> bool:
        return abs(x - self.cx) <= self.w / 2 and abs(y - self.cy) <= self.h


COMPONENTS = [Keyboard, Mouse, Slider]
