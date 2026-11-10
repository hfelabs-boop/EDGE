"""Vision-science stimuli: gratings, Gabors, noise and random-dot kinematograms, computed (not drawn).

Everything here works in pixels of the experiment window and in *linear* light: a pattern is a luminance
modulation ``m`` in [-1, 1] around the mean grey (``I = mean * (1 + contrast * m)``), plus an alpha mask. The
backend turns that into texture values, through the monitor's gamma correction when there is one
(:mod:`edge.gamma`), so a contrast of 0.5 really is 50 % Michelson contrast on a calibrated screen.

numpy does the work when it is installed (``pip install edge-experiments[vision]``); without it the patterns are
computed in plain Python (slower: keep them small) and pink/brown noise falls back to white noise.
Random-dot fields never need numpy, so a seed gives the same dots on every computer.
"""

from __future__ import annotations

import math
import random
from typing import Any

try:  # optional
    import numpy as np
except Exception:  # pragma: no cover - exercised by tests that hide numpy
    np = None  # type: ignore[assignment]

WAVES = ("sin", "sqr")
MASKS = ("none", "circle", "gauss", "raisedcos")
NOISE_TYPES = ("white", "pink", "brown", "binary")
DOT_NOISE = ("same", "random_walk", "random_position")
MAX_TEXTURE = 2048
NO_NUMPY = "numpy is not installed: patterns are computed in plain Python (slow); pip install edge-experiments[vision]"


def have_numpy() -> bool:
    return np is not None


# ============================================================================ masks
def _mask_value(r: float, mask: str, sigma_n: float, edge: float) -> float:
    """r: distance from the centre, 1 = the edge of the patch; sigma_n: sigma as a fraction of the half size."""
    if mask == "circle":
        return 1.0 if r <= 1.0 else 0.0
    if mask == "gauss":
        return math.exp(-(r * r) / (2 * sigma_n * sigma_n)) if sigma_n > 0 else 0.0
    if mask == "raisedcos":
        e = min(max(edge, 1e-6), 1.0)
        if r <= 1 - e:
            return 1.0
        if r >= 1:
            return 0.0
        return 0.5 * (1 + math.cos(math.pi * (r - (1 - e)) / e))
    return 1.0


def mask_array(w: int, h: int, mask: str = "none", sigma_px: float | None = None, edge: float = 0.2):
    """Alpha (0..1) for a w x h patch, rows bottom to top. sigma_px is the Gaussian's sigma in pixels (default
    w/6, so the patch holds ±3 sigma); edge is the raised-cosine ramp as a fraction of the radius."""
    half = max(w, h) / 2.0
    sig = (sigma_px if sigma_px else max(w, h) / 6.0) / half
    if np is None:
        s = sig * half
        out = []
        for j in range(h):
            py = (j + 0.5) - h / 2
            row = []
            for i in range(w):
                px = (i + 0.5) - w / 2
                if mask == "gauss":
                    row.append(math.exp(-(px * px + py * py) / (2 * s * s)) if s > 0 else 0.0)
                else:
                    row.append(_mask_value(math.hypot(px / (w / 2), py / (h / 2)), mask, 1.0, edge))
            out.append(row)
        return out
    x = ((np.arange(w) + 0.5) - w / 2) / (w / 2)
    y = ((np.arange(h) + 0.5) - h / 2) / (h / 2)
    xx, yy = np.meshgrid(x, y)
    r = np.hypot(xx, yy)                 # 1 at the edge of the (possibly elliptical) patch
    if mask == "circle":
        return (r <= 1.0).astype(np.float32)
    if mask == "gauss":
        # sigma is in pixels: measure the distance in pixels, not as a fraction of each axis
        px = np.hypot(xx * w / 2, yy * h / 2)
        s = sig * half
        return np.exp(-(px ** 2) / (2 * s * s)).astype(np.float32) if s > 0 else np.zeros_like(r, dtype=np.float32)
    if mask == "raisedcos":
        e = min(max(edge, 1e-6), 1.0)
        a = np.where(r <= 1 - e, 1.0, 0.5 * (1 + np.cos(np.pi * np.clip((r - (1 - e)) / e, 0, 1))))
        return np.where(r >= 1, 0.0, a).astype(np.float32)
    return np.ones((h, w), dtype=np.float32)


# ============================================================================ gratings
def grating_array(w: int, h: int, sf_cpp: float, phase: float = 0.0, wave: str = "sin"):
    """Luminance modulation in [-1, 1] of a vertical grating (bars vertical, varying along x) w x h px.
    sf_cpp: cycles per pixel; phase in cycles (0.25 = a quarter cycle). Increasing the phase moves the bars to
    the right, so drift goes to the right at orientation 0 (the backend rotates the patch for ``ori``)."""
    if np is None:
        row = []
        for i in range(w):
            x = (i + 0.5) - w / 2
            v = math.sin(2 * math.pi * (sf_cpp * x - phase))
            row.append((1.0 if v >= 0 else -1.0) if wave == "sqr" else v)
        return [list(row) for _ in range(h)]
    x = (np.arange(w, dtype=np.float64) + 0.5) - w / 2
    v = np.sin(2 * np.pi * (sf_cpp * x - phase))
    if wave == "sqr":
        v = np.where(v >= 0, 1.0, -1.0)
    return np.broadcast_to(v.astype(np.float32), (h, w))


# ============================================================================ noise
def noise_array(w: int, h: int, kind: str = "white", seed: int = 0, element_px: float = 1.0):
    """Noise in [-1, 1] for a w x h patch, rows bottom to top, reproducible from ``seed``. element_px: the size of
    one noise element (a 'check') in pixels. pink: 1/f amplitude spectrum (like natural images), brown: 1/f²,
    binary: -1 or 1, white: uniform."""
    e = max(1.0, float(element_px or 1.0))
    nw, nh = max(1, int(math.ceil(w / e))), max(1, int(math.ceil(h / e)))
    if np is None:
        rnd = random.Random(seed)
        if kind == "binary":
            small = [[1.0 if rnd.random() < 0.5 else -1.0 for _ in range(nw)] for _ in range(nh)]
        else:   # pink/brown need a Fourier transform: white noise without numpy
            small = [[rnd.uniform(-1, 1) for _ in range(nw)] for _ in range(nh)]
        return [[small[min(nh - 1, int(j / e))][min(nw - 1, int(i / e))] for i in range(w)] for j in range(h)]
    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    if kind == "binary":
        small = np.where(rng.random((nh, nw)) < 0.5, -1.0, 1.0)
    elif kind in ("pink", "brown"):
        white = rng.standard_normal((nh, nw))
        fy = np.fft.fftfreq(nh)[:, None]
        fx = np.fft.fftfreq(nw)[None, :]
        f = np.hypot(fx, fy)
        f[0, 0] = 1.0
        filt = 1.0 / f if kind == "pink" else 1.0 / (f * f)
        filt[0, 0] = 0.0                     # no DC: the mean stays at the mean grey
        small = np.real(np.fft.ifft2(np.fft.fft2(white) * filt))
        peak = np.max(np.abs(small))
        small = small / peak if peak > 0 else small
    else:
        small = rng.uniform(-1.0, 1.0, (nh, nw))
    if e > 1:
        iy = np.minimum((np.arange(h) / e).astype(int), nh - 1)
        ix = np.minimum((np.arange(w) / e).astype(int), nw - 1)
        small = small[iy][:, ix]
    return small[:h, :w].astype(np.float32)


# ============================================================================ texture values
def to_rgba(mod: Any, alpha: Any, contrast: float, color: tuple[float, float, float] = (1.0, 1.0, 1.0),
            mean: float = 0.5, linearize: Any = None) -> bytes:
    """RGBA bytes (rows bottom to top) for a modulation pattern: linear intensity ``mean * (1 + contrast * m)``
    times the colour, through ``linearize`` (intensity 0..1 -> device value 0..1 per channel, from the gamma
    calibration) when given. Alpha is the mask (opacity is applied by the backend)."""
    c = max(-1.0, min(1.0, float(contrast)))
    if np is None:
        out = bytearray()
        for row_m, row_a in zip(mod, alpha):
            for m, a in zip(row_m, row_a):
                i = min(1.0, max(0.0, mean * (1 + c * m)))
                for ch in range(3):
                    v = i * color[ch]
                    if linearize is not None:
                        v = linearize(v, ch)
                    out.append(int(round(min(1.0, max(0.0, v)) * 255)))
                out.append(int(round(min(1.0, max(0.0, a)) * 255)))
        return bytes(out)
    m = np.asarray(mod, dtype=np.float32)
    a = np.asarray(alpha, dtype=np.float32)
    inten = np.clip(mean * (1 + c * m), 0.0, 1.0)
    h, w = inten.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    for ch in range(3):
        v = inten * float(color[ch])
        if linearize is not None:
            v = linearize(v, ch)
        out[..., ch] = np.round(np.clip(v, 0.0, 1.0) * 255).astype(np.uint8)
    out[..., 3] = np.round(np.clip(np.broadcast_to(a, (h, w)), 0, 1) * 255).astype(np.uint8)
    return out.tobytes()


def color01(c: Any) -> tuple[float, float, float]:
    """A colour (name, hex, list) as linear 0..1 channel weights for a pattern (white = 1, 1, 1)."""
    from .backends.base import parse_color
    r, g, b, _ = parse_color(c if c not in (None, "") else "white")
    return (r / 255.0, g / 255.0, b / 255.0)


def texture_size(w: float, h: float) -> tuple[int, int]:
    """Whole pixels, at least 1 and at most MAX_TEXTURE (bigger patches are scaled up)."""
    return (max(1, min(MAX_TEXTURE, int(round(abs(w))))), max(1, min(MAX_TEXTURE, int(round(abs(h))))))


# ============================================================================ random dots
class DotField:
    """A random-dot kinematogram, one step per screen refresh.

    n dots in an aperture (circle or square, w x h px). Each dot is a signal dot (moves in ``direction``) with
    probability ``coherence``, assigned when it is (re)born; noise dots move as ``noise``:

    * ``same``: each noise dot keeps one random direction for its lifetime (Scase et al. 1996 "random direction"),
    * ``random_walk``: a new random direction every frame,
    * ``random_position``: re-plotted at a random place every frame.

    Dots that leave the aperture reappear on the opposite side; dots older than ``lifetime`` frames (0 = live
    forever) are re-plotted at a random place. ``direction`` is in degrees, 0 = right, 90 = up (counter-clockwise,
    like a compass rotated so 0 points right); ``speed`` is px per second. Plain Python and seeded: the same seed
    gives the same dots everywhere."""

    def __init__(self, n: int, size: tuple[float, float], coherence: float = 0.5, direction: float = 0.0,
                 speed: float = 100.0, lifetime: int = 0, noise: str = "same", shape: str = "circle",
                 seed: int = 0, refresh_rate: float = 60.0):
        self.n = max(0, int(n))
        self.w, self.h = float(size[0]), float(size[1])
        self.coherence = min(1.0, max(0.0, float(coherence)))
        self.direction = float(direction)
        self.step_px = float(speed) / float(refresh_rate or 60.0)
        self.lifetime = max(0, int(lifetime or 0))
        self.noise = noise if noise in DOT_NOISE else "same"
        self.shape = shape if shape in ("circle", "square") else "circle"
        self.rng = random.Random(int(seed))
        self.frame = 0
        self.x: list[float] = []
        self.y: list[float] = []
        self.age: list[int] = []
        self.signal: list[bool] = []
        self.dirs: list[float] = []
        for _ in range(self.n):
            x, y = self._place()
            self.x.append(x)
            self.y.append(y)
            self.age.append(self.rng.randrange(self.lifetime) if self.lifetime else 0)   # staggered deaths
            s = self.rng.random() < self.coherence
            self.signal.append(s)
            self.dirs.append(self.direction if s else self.rng.uniform(0, 360))

    def _inside(self, x: float, y: float) -> bool:
        if self.shape == "square":
            return abs(x) <= self.w / 2 and abs(y) <= self.h / 2
        return (x / (self.w / 2)) ** 2 + (y / (self.h / 2)) ** 2 <= 1.0 if self.w > 0 and self.h > 0 else False

    def _place(self) -> tuple[float, float]:
        if self.w <= 0 or self.h <= 0:
            return (0.0, 0.0)
        for _ in range(100):
            x = self.rng.uniform(-self.w / 2, self.w / 2)
            y = self.rng.uniform(-self.h / 2, self.h / 2)
            if self._inside(x, y):
                return (x, y)
        return (0.0, 0.0)

    def _rebirth(self, i: int) -> None:
        self.x[i], self.y[i] = self._place()
        self.age[i] = 0
        s = self.rng.random() < self.coherence
        self.signal[i] = s
        self.dirs[i] = self.direction if s else self.rng.uniform(0, 360)

    def set(self, coherence: float | None = None, direction: float | None = None, speed: float | None = None,
            refresh_rate: float = 60.0) -> None:
        """Change the motion while it runs (dynamic properties); dots are re-assigned as they are reborn."""
        if direction is not None and float(direction) != self.direction:
            self.direction = float(direction)
            self.dirs = [self.direction if s else d for s, d in zip(self.signal, self.dirs)]
        if coherence is not None:
            self.coherence = min(1.0, max(0.0, float(coherence)))
        if speed is not None:
            self.step_px = float(speed) / float(refresh_rate or 60.0)

    def step(self) -> None:
        """Advance one refresh."""
        self.frame += 1
        for i in range(self.n):
            self.age[i] += 1
            if self.lifetime and self.age[i] >= self.lifetime:
                self._rebirth(i)
                continue
            if not self.signal[i]:
                if self.noise == "random_position":
                    self.x[i], self.y[i] = self._place()
                    continue
                if self.noise == "random_walk":
                    self.dirs[i] = self.rng.uniform(0, 360)
            a = math.radians(self.dirs[i])
            x = self.x[i] + self.step_px * math.cos(a)
            y = self.y[i] + self.step_px * math.sin(a)
            if not self._inside(x, y):
                # wrap to the opposite side of the aperture along the direction of motion
                x, y = self._wrap(x, y, a)
            self.x[i], self.y[i] = x, y

    def _wrap(self, x: float, y: float, a: float) -> tuple[float, float]:
        if self.shape == "square":
            hw, hh = self.w / 2, self.h / 2
            x = (x + hw) % self.w - hw if self.w else 0.0
            y = (y + hh) % self.h - hh if self.h else 0.0
            return x, y
        # circle: move back along the motion until just inside the opposite edge
        dx, dy = math.cos(a), math.sin(a)
        rx, ry = self.w / 2, self.h / 2
        # the chord through (x, y) along (dx, dy): enter at the far side
        t = self._ray_exit(x, y, -dx, -dy, rx, ry)
        nx, ny = x - dx * t * 0.999, y - dy * t * 0.999
        if not self._inside(nx, ny):
            return self._place()
        return nx, ny

    @staticmethod
    def _ray_exit(x: float, y: float, dx: float, dy: float, rx: float, ry: float) -> float:
        """Distance from (x, y) along (dx, dy) to the far edge of the ellipse (x/rx)² + (y/ry)² = 1."""
        if rx <= 0 or ry <= 0:
            return 0.0
        a = (dx / rx) ** 2 + (dy / ry) ** 2
        b = 2 * (x * dx / rx ** 2 + y * dy / ry ** 2)
        c = (x / rx) ** 2 + (y / ry) ** 2 - 1
        disc = b * b - 4 * a * c
        if a == 0 or disc < 0:
            return 0.0
        return (-b + math.sqrt(disc)) / (2 * a)

    def positions(self, digits: int = 1) -> list[list[float]]:
        return [[round(x, digits), round(y, digits)] for x, y in zip(self.x, self.y)]

    def n_signal(self) -> int:
        return sum(1 for s in self.signal if s)
