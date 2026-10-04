"""Visual and auditory stimulus components."""

from __future__ import annotations

from typing import Any

from .base import Component

_VISUAL_COMMON = {
    "pos": {"type": "vec2", "default": [0, 0], "help": "position (window units, origin centre)"},
    "opacity": {"type": "float", "default": 1.0},
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
        "text": {"type": "text", "default": "", "required": True},
        "color": {"type": "color", "default": "white"},
        "height": {"type": "float", "default": 40, "help": "letter height (window units)"},
        "font": {"type": "str", "default": ""},
        "bold": {"type": "bool", "default": False},
        "italic": {"type": "bool", "default": False},
        "wrap_width": {"type": "float", "default": None},
        **_VISUAL_COMMON,
    }

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        return {"text": str(p["text"]), "color": p["color"], "height": self.px(p["height"], "y"),
                "font": p["font"], "bold": p["bold"], "italic": p["italic"],
                "wrap_width": self.px(p["wrap_width"], "x") if p["wrap_width"] else None,
                "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def make_stim(self):
        return self.backend.make_text(**self.stim_props())


class Shape(VisualComponent):
    type_name = "shape"
    description = "Rectangle, circle, ellipse, polygon, line or cross."
    props_schema = {
        "shape": {"type": "choice", "choices": ["rect", "circle", "ellipse", "polygon", "line", "cross"], "default": "rect"},
        "size": {"type": "vec2", "default": [100, 100], "help": "width, height (rect/ellipse) or size (cross)"},
        "radius": {"type": "float", "default": 50, "help": "circle radius"},
        "vertices": {"type": "list", "default": [], "help": "polygon vertices [[x,y],...]"},
        "start": {"type": "vec2", "default": [-50, 0]},
        "end": {"type": "vec2", "default": [50, 0]},
        "fill": {"type": "color", "default": "white"},
        "line_color": {"type": "color", "default": None},
        "line_width": {"type": "float", "default": 2},
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
                    "shape": {"type": "choice", "choices": ["cross", "circle"], "default": "cross"},
                    "size": {"type": "float", "default": 40},
                    "line_width": {"type": "float", "default": 4},
                    "radius": {"type": "float", "default": 6}}


class Image(VisualComponent):
    type_name = "image"
    description = "Image file (png, jpg, bmp ...). Size defaults to the image's native size."
    props_schema = {
        "image": {"type": "file", "default": "", "required": True},
        "size": {"type": "vec2", "default": None},
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
        "volume": {"type": "float", "default": 1.0},
        "tone_duration": {"type": "float", "default": 0.2},
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
