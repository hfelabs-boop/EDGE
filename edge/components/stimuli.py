"""Visual and auditory stimulus components."""

from __future__ import annotations

from typing import Any

from .base import Component

_VISUAL_COMMON = {
    "pos": {"type": "vec2", "default": [0, 0], "help": "position (window units, origin centre)"},
    "opacity": {"type": "float", "default": 1.0, "help": "0 (invisible) to 1 (opaque)"},
    "ori": {"type": "float", "default": 0.0, "help": "rotation, degrees clockwise"},
    "units": {"type": "choice", "choices": ["", "px", "norm", "height", "deg"], "default": "",
              "help": "empty = experiment default"},
}


class VisualComponent(Component):
    visual = True
    category = "stimulus"
    dynamic = {"pos", "opacity", "ori", "size", "color", "fill", "text", "radius", "line_color", "image"}
    stim_kind = "rect"

    def stim_props(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def make_stim(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def prepare(self) -> None:
        super().prepare()
        self.stim = self.make_stim()

    def on_frame(self, t: float) -> None:
        if self.refresh_dynamic():
            self.stim.set(**self.stim_props())
        self.stim.draw()

    def on_start(self, t: float) -> None:
        self.out["onset"] = t - self.run.t0 if self.run.t0 is not None else None

    def on_stop(self, t: float) -> None:
        if self.t_start is not None:
            self.out["duration"] = t - self.t_start

    def contains(self, x: float, y: float) -> bool:
        return self.stim.contains(x, y)


class Text(VisualComponent):
    type_name = "text"
    description = "Text: instructions, words, feedback. Supports expressions, e.g. \"$f'Score: {score}'\"."
    props_schema = {
        "text": {"type": "text", "default": "", "required": True, "help": "what to show; use $column for trial values or an f-string: $f'Score: {score}'"},
        "color": {"type": "color", "default": "white", "help": "name (red), hex (#ff8800), or $expression"},
        "height": {"type": "float", "default": 40, "help": "letter height (window units)"},
        "font": {"type": "str", "default": "", "help": "font family; empty = system default"},
        "bold": {"type": "bool", "default": False, "help": "bold text"},
        "italic": {"type": "bool", "default": False, "help": "italic text"},
        "wrap_width": {"type": "float", "default": None, "help": "maximum line width before wrapping (window units)"},
        "direction": {"type": "choice", "choices": ["auto", "ltr", "rtl"], "default": "auto",
                      "help": "text direction; auto detects Hebrew (right-to-left)"},
        **_VISUAL_COMMON,
    }

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        return {"text": str(p["text"]), "color": p["color"], "height": self.px(p["height"], "y"),
                "font": p["font"], "bold": p["bold"], "italic": p["italic"],
                "wrap_width": self.px(p["wrap_width"], "x") if p["wrap_width"] else None,
                "direction": p.get("direction") or "auto",
                "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def make_stim(self):
        return self.backend.make_text(**self.stim_props())


class Shape(VisualComponent):
    type_name = "shape"
    description = "Rectangle, circle, ellipse, polygon, line or cross."
    props_schema = {
        "shape": {"type": "choice", "choices": ["rect", "circle", "ellipse", "polygon", "line", "cross"], "default": "rect", "help": "rect, circle, ellipse, polygon, line or cross"},
        "size": {"type": "vec2", "default": [100, 100], "help": "width, height (rect/ellipse) or size (cross)"},
        "radius": {"type": "float", "default": 50, "help": "circle radius"},
        "vertices": {"type": "list", "default": [], "help": "polygon vertices [[x,y],...]"},
        "start": {"type": "vec2", "default": [-50, 0], "help": "line start point [x, y] (shape: line)"},
        "end": {"type": "vec2", "default": [50, 0], "help": "line end point [x, y] (shape: line)"},
        "fill": {"type": "color", "default": "white", "help": "fill colour; 'transparent' for outlines only"},
        "line_color": {"type": "color", "default": None, "help": "outline colour (empty = no outline)"},
        "line_width": {"type": "float", "default": 2, "help": "outline / line thickness"},
        **_VISUAL_COMMON,
    }

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        size = p["size"]
        d = {"pos": self.px(p["pos"]), "fill": p["fill"], "line_color": p["line_color"],
             "line_width": p["line_width"], "opacity": p["opacity"], "ori": p["ori"],
             "radius": self.px(p["radius"], "y"),
             "vertices": [self.px(v) for v in p["vertices"]],
             "start": self.px(p["start"]), "end": self.px(p["end"])}
        d["size"] = self.px(size) if isinstance(size, (list, tuple)) else self.px(size, "y")
        return d

    def make_stim(self):
        return self.backend.make_shape(self.p["shape"], **self.stim_props())


class Fixation(Shape):
    type_name = "fixation"
    description = "Fixation cross."
    props_schema = {**Shape.props_schema,
                    "shape": {"type": "choice", "choices": ["cross", "circle"], "default": "cross", "help": "cross or a dot (circle)"},
                    "size": {"type": "float", "default": 40, "help": "cross width and height"},
                    "line_width": {"type": "float", "default": 4, "help": "thickness of the cross lines"},
                    "radius": {"type": "float", "default": 6, "help": "dot radius (shape: circle)"}}


class Image(VisualComponent):
    type_name = "image"
    description = "Image file (png, jpg, bmp ...). Size defaults to the image's native size."
    props_schema = {
        "image": {"type": "file", "default": "", "required": True, "help": "image file (png, jpg …) relative to the experiment, or $column"},
        "size": {"type": "vec2", "default": None, "help": "width, height; empty = native size"},
        **_VISUAL_COMMON,
    }

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        return {"image": p["image"], "size": self.px(p["size"]) if p["size"] else None,
                "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def make_stim(self):
        return self.backend.make_image(**self.stim_props())


class Sound(Component):
    type_name = "sound"
    category = "stimulus"
    description = "Play a sound file or a pure tone (number = frequency in Hz)."
    props_schema = {
        "sound": {"type": "file", "default": 440, "help": "file path or tone frequency in Hz"},
        "volume": {"type": "float", "default": 1.0, "help": "0 to 1"},
        "tone_duration": {"type": "float", "default": 0.2, "help": "length of a pure tone in seconds (for numeric sounds)"},
    }

    def on_start(self, t: float) -> None:
        self.handle = self.backend.play_sound(self.p["sound"], self.p["volume"], duration=self.p["tone_duration"])
        self.out["onset"] = t - self.run.t0

    def on_frame(self, t: float) -> None:
        # a tone without an explicit duration is finished once it has played
        if self.spec.duration is None and isinstance(self.p["sound"], (int, float)) \
                and t - self.t_start >= float(self.p["tone_duration"]):
            self.finished = True

    def on_stop(self, t: float) -> None:
        if self.spec.duration is not None:
            self.backend.stop_sound(getattr(self, "handle", None))


COMPONENTS = [Text, Shape, Fixation, Image, Sound]
