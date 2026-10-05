"""Eye-tracking components. They work with any device exposing ``latest_gaze()``:
Tobii, Gazepoint, LSL gaze streams, the simulated tracker, or ``mouse_gaze``."""

from __future__ import annotations

import math
from ..devices.base import Device, DeviceError
from .base import Component


def find_gaze_device(session, device_id: str | None) -> Device:
    if device_id:
        dev = session.devices.get(device_id)
        if dev is None:
            raise DeviceError(f"device '{device_id}' not found")
        return dev
    for dev in session.devices.values():
        if "gaze" in dev.capabilities:
            return dev
    raise DeviceError("no gaze-capable device configured (add tobii, gazepoint, sim_eyetracker or mouse_gaze)")


class GazeROI(Component):
    type_name = "gaze_roi"
    category = "eyetracking"
    description = ("Area of interest. Tracks entries, first-entry latency and dwell time; can end the "
                   "routine after a continuous dwell (gaze-contingent triggers, fixation checks).")
    outputs = {
        "entered": {"desc": "1 if gaze entered {who}", "type": "0/1", "kind": "gaze"},
        "first_entry": {"desc": "Time (s) from onset until gaze first entered {who}", "units": "s", "type": "number", "kind": "gaze"},
        "dwell_time": {"desc": "Total gaze dwell time (s) in {who}", "units": "s", "type": "number", "kind": "gaze"},
        "entries": {"desc": "Number of gaze entries into {who}", "type": "integer", "kind": "gaze"},
        "completed": {"desc": "1 if the dwell criterion of {who} was met", "type": "0/1", "kind": "gaze"},
        "rt": {"desc": "Time (s) from onset until the dwell criterion of {who} was met", "units": "s",
               "type": "number", "kind": "rt"},
    }
    props_schema = {
        "device": {"type": "device", "default": None, "help": "gaze device id (default: first gaze device)"},
        "target": {"type": "component", "default": None, "help": "use another component's area (e.g. an image)"},
        "shape": {"type": "choice", "choices": ["circle", "rect"], "default": "circle", "help": "circle or rect (ignored when target is set)"},
        "pos": {"type": "vec2", "default": [0, 0], "help": "centre of the area"},
        "radius": {"type": "float", "default": 100, "help": "radius (shape: circle)"},
        "size": {"type": "vec2", "default": [200, 200], "help": "width, height (shape: rect)"},
        "units": {"type": "str", "default": "", "help": "empty = experiment default"},
        "dwell": {"type": "float", "default": None, "help": "seconds of continuous dwell that complete the ROI"},
        "show": {"type": "bool", "default": False, "help": "draw the ROI outline (debug)"},
    }

    def prepare(self) -> None:
        super().prepare()
        self.dev = find_gaze_device(self.session, self.p["device"])
        self._inside_since: float | None = None
        self._last_t: float | None = None
        self.out.update(entered=0, first_entry=None, dwell_time=0.0, entries=0, completed=0)
        if self.p["show"]:
            if self.p["shape"] == "circle":
                self._dbg = self.backend.make_shape("circle", pos=self.px(self.p["pos"]), radius=self.px(self.p["radius"], "y"),
                                                    fill="#00ff0030")
            else:
                self._dbg = self.backend.make_shape("rect", pos=self.px(self.p["pos"]), size=self.px(self.p["size"]),
                                                    fill="#00ff0030")

    def inside(self, x: float, y: float) -> bool:
        tgt = self.p["target"]
        if tgt:
            comp = self.run.components.get(tgt)
            return bool(comp is not None and hasattr(comp, "contains") and comp.status == 1 and comp.contains(x, y))
        cx, cy = self.px(self.p["pos"])
        if self.p["shape"] == "circle":
            return math.hypot(x - cx, y - cy) <= self.px(self.p["radius"], "y")
        w, h = self.px(self.p["size"])
        return abs(x - cx) <= w / 2 and abs(y - cy) <= h / 2

    def on_frame(self, t: float) -> None:
        if self.p["show"]:
            self._dbg.draw()
        g = self.dev.latest_gaze()
        dt = 0.0 if self._last_t is None else t - self._last_t
        self._last_t = t
        if g is not None and self.inside(*g):
            if self._inside_since is None:
                self._inside_since = t
                self.out["entries"] += 1
                if not self.out["entered"]:
                    self.out["entered"] = 1
                    self.out["first_entry"] = self.rt(t)
                    self.session.marker(f"{self.id}.enter", source=self.id)
            else:
                self.out["dwell_time"] = round(self.out["dwell_time"] + dt, 6)
            dwell = self.p["dwell"]
            if dwell is not None and t - self._inside_since >= float(dwell) and not self.finished:
                self.out["completed"] = 1
                self.out["rt"] = self.rt(t)
                self.finished = True
        else:
            self._inside_since = None


class GazeFollow(Component):
    type_name = "gaze_follow"
    category = "eyetracking"
    description = "Move another visual component to the current gaze position (moving windows, masks, gaze cursors)."
    props_schema = {
        "device": {"type": "device", "default": None, "help": "gaze device id (default: first gaze device)"},
        "target": {"type": "component", "default": None, "required": True, "help": "id of the visual component to move"},
        "offset": {"type": "vec2", "default": [0, 0], "help": "[x, y] added to the gaze position"},
        "smoothing": {"type": "float", "default": 0.0, "help": "0..1 exponential smoothing"},
    }

    def prepare(self) -> None:
        super().prepare()
        self.dev = find_gaze_device(self.session, self.p["device"])
        self._pos: tuple[float, float] | None = None

    def on_frame(self, t: float) -> None:
        g = self.dev.latest_gaze()
        comp = self.run.components.get(self.p["target"])
        if g is None or comp is None or not hasattr(comp, "stim"):
            return
        ox, oy = self.p["offset"]
        tx, ty = g[0] + ox, g[1] + oy
        a = float(self.p["smoothing"] or 0)
        if self._pos is not None and a > 0:
            tx, ty = a * self._pos[0] + (1 - a) * tx, a * self._pos[1] + (1 - a) * ty
        self._pos = (tx, ty)
        comp.stim.set(pos=(tx, ty))


class Calibrate(Component):
    type_name = "calibrate"
    category = "eyetracking"
    description = "Run the eye tracker's calibration (Tobii: drawn by EDGE; Gazepoint: native window)."
    outputs = {"result": {"desc": "Result of {who}", "type": "text", "kind": "other"}}
    props_schema = {"device": {"type": "device", "default": None, "help": "gaze device id (default: first gaze device)"}}

    def on_start(self, t: float) -> None:
        dev = find_gaze_device(self.session, self.p["device"])
        self.session.marker(f"{dev.id}.calibration_start", source=self.id)
        res = dev.calibrate(self.session)
        self.session.calibrations.append({"device": dev.id, "time": t, **res})
        self.out["result"] = res.get("result")
        self.finished = True


COMPONENTS = [GazeROI, GazeFollow, Calibrate]
