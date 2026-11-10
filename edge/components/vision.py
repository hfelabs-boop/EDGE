"""Vision-science stimuli: ``grating``, ``gabor``, ``noise`` and ``dots`` (random-dot kinematogram).

Each is computed by :mod:`edge.vision` and handed to the backend in pixels: the experiment window draws textures
(through the gamma calibration), Test runs only keep the state (phase, noise seed, dot positions), Try it draws them
on a canvas in the browser, and the builder's preview draws a representative frame.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .. import expressions
from ..vision import DOT_NOISE, MASKS, NOISE_TYPES
from .stimuli import _VISUAL_COMMON, VisualComponent

MASK_ICONS = {"none": "▢", "circle": "◯", "gauss": "◌", "raisedcos": "◍"}

_TIMING = {
    "onset": {"desc": "Onset of {who} (s from routine start, at the screen flip)", "units": "s", "type": "number",
              "kind": "timing"},
    "duration": {"desc": "How long {who} was active (s)", "units": "s", "type": "number", "kind": "timing"},
    "frames": {"desc": "Screen refreshes {who} was drawn on", "units": "frames", "type": "number", "kind": "timing"},
}

_PATTERN = {
    "contrast": {"type": "float", "default": 1.0, "min": 0, "max": 1, "step": 0.01,
                 "help": "Michelson contrast, 0 (uniform grey) to 1 (full); linear on a gamma-calibrated monitor"},
    "mask": {"type": "choice", "choices": list(MASKS), "default": "none", "icons": MASK_ICONS,
             "help": "none (a square patch), circle, gauss (Gaussian), raisedcos (circle with soft edges)"},
    "sigma": {"type": "float", "default": None, "min": 0, "step": 1, "length": True,
              "help": "Gaussian mask's standard deviation (window units); empty = size / 6"},
    "edge": {"type": "float", "default": 0.2, "min": 0.01, "max": 1, "step": 0.05,
             "help": "raised-cosine mask: width of the soft edge, as a fraction of the radius"},
    "color": {"type": "color", "default": "white",
              "help": "colour of the bright parts (white = a grey-level pattern around mid grey)"},
}

_SF = {
    "sf": {"type": "float", "default": 2.0, "min": 0, "step": 0.1,
           "help": "spatial frequency (cycles per degree, or per pixel: see sf_units)"},
    "sf_units": {"type": "choice", "choices": ["cycles/deg", "cycles/px"], "default": "cycles/deg",
                 "help": "cycles/deg uses the monitor's width and viewing distance (Experiment settings → Screen)"},
    "phase": {"type": "float", "default": 0.0, "step": 0.05, "help": "phase in cycles (0.5 = half a cycle)"},
    "tf": {"type": "float", "default": 0.0, "step": 0.5,
           "help": "temporal frequency in Hz: drifts the bars (positive: towards the right at orientation 0)"},
    "wave": {"type": "choice", "choices": ["sin", "sqr"], "default": "sin", "help": "sine wave or square wave"},
}


def _monitor_note(spec, where, exp) -> list:
    """Degrees need the monitor's width and the viewing distance: say so when they are still the defaults."""
    from ..model import Issue
    win = exp.settings.get("window") or {}
    uses_deg = (spec.props.get("units") or win.get("units")) == "deg" or spec.props.get("sf_units", "cycles/deg") == "cycles/deg"
    if spec.type in ("noise", "dots") and (spec.props.get("units") or win.get("units")) != "deg":
        uses_deg = False
    src = ((exp.source or {}).get("settings") or {}).get("window") or {}
    mon = src.get("monitor") if isinstance(src.get("monitor"), dict) else {}
    if uses_deg and not (mon.get("width_cm") and mon.get("distance_cm")):
        return [Issue("info", where, "degrees are computed from the default monitor (53 cm wide, 60 cm away)",
                      hint="set the screen's visible width and the viewing distance in Experiment settings → Screen "
                           "(settings.window.monitor: {width_cm, distance_cm}); run full screen at the monitor's "
                           "native resolution, or add width_px")]
    return []


class _Procedural(VisualComponent):
    """Shared by the four: units, frame counting, seeds."""
    outputs = dict(_TIMING)
    dynamic = {"pos", "opacity", "ori", "size", "contrast", "phase", "sf", "tf", "color", "sigma", "coherence",
               "direction", "speed"}

    @classmethod
    def validate_spec(cls, spec, where, exp):
        from ..model import Issue
        issues = super().validate_spec(spec, where, exp)
        for k, meta in cls.props_schema.items():
            v = spec.props.get(k)
            if v is None or expressions.is_expr(v) or meta["type"] not in ("float", "int"):
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                issues.append(Issue("error", where, f"'{k}' must be a number (or a $formula), not {v!r}"))
                continue
            lo, hi = meta.get("min"), meta.get("max")
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                rng = f"between {lo} and {hi}" if lo is not None and hi is not None else f"at least {lo}" if lo is not None else f"at most {hi}"
                issues.append(Issue("error", where, f"'{k}' must be {rng}, not {v}"))
        seed = spec.props.get("seed")
        if seed is not None and not expressions.is_expr(seed) and (isinstance(seed, bool) or not isinstance(seed, int)):
            issues.append(Issue("error", where, "'seed' must be a whole number (or empty: a new one each time, "
                                "reproducible from the session's seed)"))
        issues += _monitor_note(spec, where, exp)
        return issues

    def ppd(self) -> float:
        """Pixels per degree at the screen centre, from settings.window.monitor."""
        return float(self.backend.to_px(1.0, "deg", self.session.settings["window"].get("monitor"), "x"))

    def derived_seed(self) -> int:
        """A seed for this showing: the given one, or one made from the session seed, the screen, the item and how
        many times it was shown (so a session with the same seed shows the same noise and dots)."""
        if self.p.get("seed") is not None:
            return int(self.p["seed"])
        counts = self.session.__dict__.setdefault("_stim_showings", {})
        key = f"{self.run.routine.id}.{self.id}"
        counts[key] = counts.get(key, 0) + 1
        h = hashlib.sha256(f"{self.session.seed}|{key}|{counts[key]}".encode()).hexdigest()
        return int(h[:8], 16) & 0x7FFFFFFF

    def size_px(self, default=(256, 256)) -> tuple[float, float]:
        s = self.p.get("size")
        if s is None:
            return default
        if isinstance(s, (list, tuple)):
            w, h = self.px(s)
        else:
            w = h = self.px(s, "y")
        return (abs(float(w)), abs(float(h)))

    def prepare(self) -> None:
        self.n_frames = 0
        super().prepare()

    def on_start(self, t: float) -> None:
        super().on_start(t)

    def on_stop(self, t: float) -> None:
        super().on_stop(t)
        self.out["frames"] = self.n_frames

    def elapsed(self, t: float) -> float:
        return t - self.t_start if self.t_start is not None else 0.0


class Grating(_Procedural):
    type_name = "grating"
    description = ("Sine/square grating (drifts with tf). Spatial frequency in cycles/deg or cycles/px, phase, "
                   "orientation, contrast and a mask (circle, gauss, raisedcos).")
    props_schema = {
        **_SF,
        **_PATTERN,
        "size": {"type": "vec2", "default": [256, 256], "help": "width, height of the patch (window units)"},
        **_VISUAL_COMMON,
    }
    outputs = {**_TIMING,
               "sf_cpd": {"desc": "Spatial frequency of {who} as shown (cycles per degree)", "units": "c/deg",
                          "type": "number", "kind": "other"},
               "phase": {"desc": "Phase of {who} at its onset (cycles)", "units": "cycles", "type": "number",
                         "kind": "other"}}
    fixed_mask: str | None = None

    def sf_cpp(self) -> float:
        sf = float(self.p.get("sf") or 0.0)
        if self.p.get("sf_units") == "cycles/px":
            return sf
        ppd = self.ppd()
        return sf / ppd if ppd > 0 else 0.0

    def phase_at(self, t: float) -> float:
        return float(self.p.get("phase") or 0.0) + float(self.p.get("tf") or 0.0) * self.elapsed(t)

    def mask_props(self, size: tuple[float, float]) -> dict[str, Any]:
        sig = self.p.get("sigma")
        return {"mask": self.fixed_mask or self.p.get("mask") or "none",
                "sigma": float(self.px(sig, "y")) if sig not in (None, "") else None,
                "edge": float(self.p.get("edge") or 0.2)}

    def stim_props(self, t: float | None = None) -> dict[str, Any]:
        p = self.p
        size = self.size_px()
        return {"size": list(size), "sf": self.sf_cpp(), "phase": round(self.phase_at(t) if t is not None
                                                                         else float(p.get("phase") or 0.0), 6),
                "wave": p.get("wave") or "sin", "contrast": float(p.get("contrast", 1.0)), "color": p.get("color"),
                **self.mask_props(size), "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def make_stim(self):
        return self.backend.make_pattern(self.type_name, **self.stim_props())

    def on_frame(self, t: float) -> None:
        self.refresh_dynamic()
        props = self.stim_props(t)
        if self.n_frames == 0:
            self.out["phase"] = props["phase"]
            cpp = props["sf"]
            self.out["sf_cpd"] = round(cpp * self.ppd(), 4)
        self.stim.set(**props)
        self.stim.draw()
        self.n_frames += 1


class Gabor(Grating):
    type_name = "gabor"
    description = "Gabor patch (grating in a Gaussian window). Sigma, phase, orientation, contrast and drift (tf)."
    props_schema = {
        **_SF,
        **{k: v for k, v in _PATTERN.items() if k not in ("mask", "edge", "sigma")},
        "sigma": {"type": "float", "default": 30, "min": 0, "step": 1, "length": True,
                  "help": "standard deviation of the Gaussian window (window units)"},
        "size": {"type": "vec2", "default": None,
                 "help": "width, height of the patch; empty = 6 × sigma (the window fades out inside it)"},
        **_VISUAL_COMMON,
    }
    fixed_mask = "gauss"

    def size_px(self, default=None) -> tuple[float, float]:
        if self.p.get("size") is None:
            s = 6 * float(self.px(self.p.get("sigma") or 30, "y"))
            return (s, s)
        return super().size_px()


class Noise(_Procedural):
    type_name = "noise"
    description = ("Visual noise (white, pink, brown, binary). Pink is 1/f, brown 1/f²; static or a new sample every "
                   "frame (dynamic), reproducible with a seed.")
    props_schema = {
        "noise_type": {"type": "choice", "choices": list(NOISE_TYPES), "default": "white",
                       "help": "white, pink (1/f, like natural images), brown (1/f²) or binary (black/white checks)"},
        "element_size": {"type": "float", "default": None, "min": 0, "step": 1, "length": True,
                         "help": "size of one noise element (window units); empty = one screen pixel"},
        "dynamic": {"type": "bool", "default": False, "help": "a new noise sample every update_frames refreshes"},
        "update_frames": {"type": "int", "default": 1, "min": 1, "max": 600, "step": 1,
                          "help": "dynamic noise: refreshes per noise sample (1 = every frame)"},
        "seed": {"type": "int", "default": None,
                 "help": "the same seed gives the same noise; empty = a new one each time (reproducible from the "
                         "session's seed)"},
        **_PATTERN,
        "size": {"type": "vec2", "default": [256, 256], "help": "width, height of the patch (window units)"},
        **_VISUAL_COMMON,
    }
    outputs = {**_TIMING,
               "seed": {"desc": "Noise seed used by {who}", "type": "number", "kind": "other"},
               "samples": {"desc": "Number of different noise samples {who} showed", "type": "number",
                           "kind": "other"}}

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        size = self.size_px()
        es = p.get("element_size")
        sig = p.get("sigma")
        return {"size": list(size), "noise_type": p.get("noise_type") or "white", "seed": self.seed,
                "sample": self.sample, "element": float(self.px(es, "y")) if es else 1.0,
                "contrast": float(p.get("contrast", 1.0)), "color": p.get("color"),
                "mask": p.get("mask") or "none", "sigma": float(self.px(sig, "y")) if sig not in (None, "") else None,
                "edge": float(p.get("edge") or 0.2), "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def make_stim(self):
        return self.backend.make_pattern("noise", **self.stim_props())

    def prepare(self) -> None:
        self.n_frames = 0
        self.sample = 0
        self.resolve_all()
        self.seed = self.derived_seed()
        self.stim = self.make_stim()
        self.out["seed"] = self.seed

    def on_frame(self, t: float) -> None:
        self.refresh_dynamic()
        every = max(1, int(self.p.get("update_frames") or 1))
        if self.p.get("dynamic") and self.n_frames and self.n_frames % every == 0:
            self.sample += 1
        self.stim.set(**self.stim_props())
        self.stim.draw()
        self.n_frames += 1

    def on_stop(self, t: float) -> None:
        super().on_stop(t)
        self.out["samples"] = self.sample + 1 if self.n_frames else 0


class Dots(_Procedural):
    type_name = "dots"
    description = ("Random-dot kinematogram (RDK). n dots in an aperture, a fraction (coherence) moving in one "
                   "direction, the others as noise; dot size, speed and lifetime; reproducible with a seed.")
    props_schema = {
        "n_dots": {"type": "int", "default": 100, "min": 1, "max": 5000, "step": 10, "help": "number of dots"},
        "coherence": {"type": "float", "default": 0.5, "min": 0, "max": 1, "step": 0.05,
                      "help": "fraction of dots moving in the signal direction"},
        "direction": {"type": "float", "default": 0.0, "min": -360, "max": 360, "step": 5,
                      "help": "signal direction in degrees: 0 = right, 90 = up, 180 = left, 270 = down"},
        "speed": {"type": "float", "default": 100, "min": 0, "step": 5, "length": True,
                  "help": "dot speed in window units per second"},
        "dot_size": {"type": "float", "default": 4, "min": 0.1, "step": 1, "length": True,
                     "help": "dot diameter (window units)"},
        "lifetime": {"type": "int", "default": 0, "min": 0, "step": 1,
                     "help": "frames a dot lives before it is re-plotted somewhere else; 0 = for ever"},
        "noise_dots": {"type": "choice", "choices": list(DOT_NOISE), "default": "same",
                       "help": "noise dots: same (each keeps a random direction), random_walk (new direction every "
                               "frame) or random_position (re-plotted every frame)"},
        "field_shape": {"type": "choice", "choices": ["circle", "square"], "default": "circle",
                        "help": "shape of the aperture"},
        "size": {"type": "vec2", "default": [300, 300], "help": "aperture width, height (window units)"},
        "color": {"type": "color", "default": "white", "help": "dot colour"},
        "seed": {"type": "int", "default": None,
                 "help": "the same seed gives the same dots; empty = new ones each time (reproducible from the "
                         "session's seed)"},
        **_VISUAL_COMMON,
    }
    outputs = {**_TIMING,
               "seed": {"desc": "Random seed of {who}", "type": "number", "kind": "other"},
               "n_signal": {"desc": "Number of signal (coherent) dots of {who} at its onset", "type": "number",
                            "kind": "other"}}

    def stim_props(self) -> dict[str, Any]:
        p = self.p
        return {"dots": self.field.positions(), "dot_size": float(self.px(p.get("dot_size") or 4, "y")),
                "color": p.get("color"), "size": list(self.size_px((300, 300))),
                "field_shape": p.get("field_shape") or "circle",
                "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"]}

    def prepare(self) -> None:
        from ..vision import DotField
        self.n_frames = 0
        self.resolve_all()
        p = self.p
        self.seed = self.derived_seed()
        self.field = DotField(int(p.get("n_dots") or 0), self.size_px((300, 300)), float(p.get("coherence") or 0.0),
                              float(p.get("direction") or 0.0), float(self.px(p.get("speed") or 0, "y")),
                              int(p.get("lifetime") or 0), p.get("noise_dots") or "same",
                              p.get("field_shape") or "circle", self.seed, self.backend.refresh_rate)
        self.stim = self.backend.make_dots(**self.stim_props())
        self.out.update(seed=self.seed, n_signal=self.field.n_signal())

    def on_frame(self, t: float) -> None:
        if self.refresh_dynamic():
            p = self.p
            self.field.set(coherence=p.get("coherence"), direction=p.get("direction"),
                           speed=float(self.px(p.get("speed") or 0, "y")), refresh_rate=self.backend.refresh_rate)
        if self.n_frames:
            self.field.step()
        self.stim.set(**self.stim_props())
        self.stim.draw()
        self.n_frames += 1


COMPONENTS = [Grating, Gabor, Noise, Dots]
