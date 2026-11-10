"""Videos, procedural textures (gratings, Gabors, noise), random dots and the gamma ramp for the pyglet window.

Kept apart from pyglet_backend.py so the window code stays small; PygletBackend's make_movie / make_pattern /
make_dots / set_gamma call into here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..video import FFMPEG_HELP
from .base import Stim, parse_color


# ============================================================================ video
def _no_decoder_message(path: Path, err: Exception) -> str:
    try:
        import pyglet
        have = pyglet.media.have_ffmpeg()
    except Exception:
        have = False
    if not have:
        return f"can't play the video {path.name}: pyglet found no FFmpeg on this computer ({err}). To fix it, " + FFMPEG_HELP
    return f"can't play the video {path.name}: {err}. Convert it to MP4 (H.264) or WebM, e.g. with HandBrake or ffmpeg"


class PygletMovie:
    """Frame-locked video: the component asks for the frame that belongs on each refresh (:meth:`show`), this
    decodes up to it (at most a few frames per refresh) and keeps the last decoded frame in one texture.
    The sound track plays through a separate pyglet player started at the first frame."""

    kind = "movie"
    MAX_DECODE_PER_REFRESH = 4

    def __init__(self, backend: Any, props: dict[str, Any]):
        import pyglet
        self.b = backend
        self.props = dict(props)
        path = Path(str(props.get("movie") or ""))
        if not path.is_absolute():
            path = Path(backend.base_dir) / path
        self.path = path
        if not path.is_file():
            raise FileNotFoundError(f"video not found: {props.get('movie')}")
        try:
            self.src = pyglet.media.load(str(path), streaming=True)
        except Exception as e:
            raise RuntimeError(_no_decoder_message(path, e)) from None
        vf = getattr(self.src, "video_format", None)
        if not vf:
            raise RuntimeError(f"{path.name} has no picture (an audio-only file): use a Sound item for it")
        self.vf = vf
        self.has_audio = bool(getattr(self.src, "audio_format", None))
        try:
            self.src.audio_format = None     # this source decodes the picture only; the sound has its own
        except Exception:
            pass
        self._dur = getattr(self.src, "duration", None)
        self.tex = None
        self.sprite = None
        self.cur = -1                         # index of the frame in the texture
        self.ended = False
        self.player = None
        self.audio_src = None
        self.volume = float(props.get("volume", 1.0) or 0.0)
        self._decode_next()                   # the first frame is ready before the onset
        if self.has_audio and self.volume > 0:
            self._prepare_audio()

    # -------------------------------------------------------------- audio
    def _prepare_audio(self) -> None:
        import pyglet
        try:
            a = pyglet.media.load(str(self.path), streaming=True)
            if hasattr(a, "_video_stream_index"):
                a._video_stream_index = -1    # don't queue picture packets in the sound's source
            a.video_format = None
            dur = getattr(a, "duration", None) or 0
            self.audio_src = pyglet.media.StaticSource(a) if dur and dur <= 120 else a   # decoded ahead if short
        except Exception as e:
            self.audio_src = None
            self.b.warnings.append(f"the sound track of {self.path.name} can't be played ({e}); the picture still is")

    def start_audio(self, volume: float) -> None:
        if self.audio_src is None:
            return
        try:
            import pyglet
            self.player = pyglet.media.Player()
            self.player.queue(self.audio_src)
            self.player.volume = float(volume)
            self.player.play()
        except Exception:
            self.player = None

    def set_volume(self, volume: float) -> None:
        if self.player is not None:
            self.player.volume = float(volume)

    def stop_audio(self) -> None:
        if self.player is not None:
            try:
                self.player.pause()
                self.player.delete()
            except Exception:
                pass
            self.player = None

    # -------------------------------------------------------------- picture
    def duration(self) -> float | None:
        return float(self._dur) if self._dur else None

    def fps(self) -> float | None:
        r = getattr(self.vf, "frame_rate", None)
        return float(r) if r else None

    def frames(self) -> int | None:
        d, f = self.duration(), self.fps()
        return int(round(d * f)) if d and f else None

    def native_size(self) -> tuple[float, float]:
        w, h = self.vf.width, self.vf.height
        ar = getattr(self.vf, "sample_aspect", 1.0) or 1.0
        return (float(w) * ar if ar else float(w), float(h))

    def _decode_next(self) -> bool:
        try:
            ts = self.src.get_next_video_timestamp()
        except Exception:
            ts = None
        img = self.src.get_next_video_frame()
        if img is None:
            self.ended = True
            return False
        fps = self.fps()
        # the frame's own time says which frame it is (a decoder can skip frames: those count as dropped)
        k = int(round(ts * fps)) if ts is not None and fps else self.cur + 1
        self.cur = max(self.cur + 1, k)
        self._upload(img)
        return True

    def _upload(self, img: Any) -> None:
        import pyglet
        if self.tex is None or self.tex.width != img.width or self.tex.height != img.height:
            self.tex = pyglet.image.Texture.create(img.width, img.height)
            self.tex.anchor_x, self.tex.anchor_y = img.width // 2, img.height // 2
            self.sprite = pyglet.sprite.Sprite(self.tex)
        self.tex.blit_into(img, 0, 0, 0)

    def show(self, vt: float, k: int) -> int | None:
        n = 0
        while self.cur < k and n < self.MAX_DECODE_PER_REFRESH:
            if not self._decode_next():
                break
            n += 1
        if self.cur < 0:
            return None
        if self.ended and self.cur < k and self.duration() is None:
            return None
        return self.cur

    def rewind(self) -> None:
        try:
            self.src.seek(0.0)
        except Exception:
            self.src = __import__("pyglet").media.load(str(self.path), streaming=True)
            try:
                self.src.audio_format = None
            except Exception:
                pass
        self.cur = -1
        self.ended = False
        self._decode_next()
        if self.player is not None:
            try:
                self.player.seek(0.0)
            except Exception:
                pass

    def set(self, **props: Any) -> None:
        self.props.update(props)

    def draw(self) -> None:
        if self.sprite is None:
            return
        p = self.props
        cx, cy = self.b.size[0] / 2, self.b.size[1] / 2
        x, y = p.get("pos", (0, 0))
        w, h = p.get("size") or self.native_size()
        s = self.sprite
        s.update(x=cx + x, y=cy + y, rotation=float(p.get("ori", 0) or 0),
                 scale_x=w / self.tex.width, scale_y=h / self.tex.height)
        s.opacity = int(255 * max(0.0, min(1.0, float(p.get("opacity", 1.0)))))
        s.draw()

    def contains(self, x: float, y: float) -> bool:
        cx, cy = self.props.get("pos", (0, 0))
        w, h = self.props.get("size") or self.native_size()
        return abs(x - cx) <= w / 2 and abs(y - cy) <= h / 2

    def release(self) -> None:
        self.stop_audio()
        try:
            if self.sprite is not None:
                self.sprite.delete()
        except Exception:
            pass
        self.sprite = None


# ============================================================================ gratings, Gabors, noise
_TEX_KEYS = ("size", "sf", "phase", "wave", "contrast", "color", "mask", "sigma", "edge", "noise_type", "seed",
             "sample", "element")


class PygletPattern(Stim):
    """A procedural texture, recomputed (numpy) when one of its pattern properties changes; position, rotation and
    opacity only move the sprite."""

    def __init__(self, backend: Any, kind: str, props: dict[str, Any]):
        super().__init__(kind, props)
        self.b = backend
        self.tex = None
        self.sprite = None
        self._key: tuple | None = None

    def _pixels(self) -> tuple[int, int, bytes]:
        from .. import vision
        p = self.props
        w, h = vision.texture_size(*p["size"])
        mask = p.get("mask") or "none"
        if self.kind in ("grating", "gabor"):
            mod = vision.grating_array(w, h, float(p.get("sf") or 0.0), float(p.get("phase") or 0.0),
                                       p.get("wave") or "sin")
        else:
            seed = (int(p.get("seed") or 0) * 1000003 + int(p.get("sample") or 0)) & 0xFFFFFFFF
            mod = vision.noise_array(w, h, p.get("noise_type") or "white", seed, float(p.get("element") or 1.0))
        alpha = vision.mask_array(w, h, mask, p.get("sigma"), float(p.get("edge") or 0.2))
        data = vision.to_rgba(mod, alpha, float(p.get("contrast", 1.0)), vision.color01(p.get("color")),
                              linearize=self.b.linearize)
        return w, h, data

    def draw(self) -> None:
        import pyglet
        p = self.props
        key = tuple(_freeze(p.get(k)) for k in _TEX_KEYS)
        if key != self._key:
            w, h, data = self._pixels()
            img = pyglet.image.ImageData(w, h, "RGBA", data, pitch=w * 4)
            if self.tex is None or (self.tex.width, self.tex.height) != (w, h):
                self.tex = img.get_texture()
                self.tex.anchor_x, self.tex.anchor_y = w // 2, h // 2
                self.sprite = pyglet.sprite.Sprite(self.tex)
            else:
                self.tex.blit_into(img, 0, 0, 0)
            self._key = key
        cx, cy = self.b.size[0] / 2, self.b.size[1] / 2
        x, y = p.get("pos", (0, 0))
        sw, sh = p["size"]
        self.sprite.update(x=cx + x, y=cy + y, rotation=float(p.get("ori", 0) or 0),
                           scale_x=max(sw, 1e-6) / self.tex.width, scale_y=max(sh, 1e-6) / self.tex.height)
        self.sprite.opacity = int(255 * max(0.0, min(1.0, float(p.get("opacity", 1.0)))))
        self.sprite.draw()

    def release(self) -> None:
        try:
            if self.sprite is not None:
                self.sprite.delete()
        except Exception:
            pass


def _freeze(v: Any) -> Any:
    return tuple(_freeze(x) for x in v) if isinstance(v, (list, tuple)) else v


# ============================================================================ random dots
class PygletDots(Stim):
    """Dots as pyglet shapes in one batch, positions updated every refresh."""

    def __init__(self, backend: Any, props: dict[str, Any]):
        super().__init__("dots", props)
        self.b = backend
        self.batch = None
        self.shapes: list[Any] = []
        self._style: tuple | None = None

    def draw(self) -> None:
        import math

        import pyglet
        from pyglet import shapes
        p = self.props
        dots = p.get("dots") or []
        size = float(p.get("dot_size") or 4)
        rgba = parse_color(p.get("color") or "white")
        style = (len(dots), size, rgba)
        if style != self._style:
            self.batch = pyglet.graphics.Batch()
            self.shapes = [shapes.Circle(0, 0, size / 2, segments=max(6, min(24, int(size * 2))), color=rgba[:3],
                                         batch=self.batch) for _ in dots]
            self._style = style
        cx, cy = self.b.size[0] / 2, self.b.size[1] / 2
        x0, y0 = p.get("pos", (0, 0))
        a = math.radians(-float(p.get("ori", 0) or 0))      # ori: clockwise, like every other item
        ca, sa = math.cos(a), math.sin(a)
        op = int(rgba[3] * max(0.0, min(1.0, float(p.get("opacity", 1.0)))))
        for s, (dx, dy) in zip(self.shapes, dots):
            s.position = (cx + x0 + dx * ca - dy * sa, cy + y0 + dx * sa + dy * ca)
            s.opacity = op
        self.batch.draw()

    def contains(self, x: float, y: float) -> bool:
        cx, cy = self.props.get("pos", (0, 0))
        w, h = self.props.get("size") or (0, 0)
        return abs(x - cx) <= w / 2 and abs(y - cy) <= h / 2


# ============================================================================ gamma ramp
def set_gamma_ramp(backend: Any, cal: Any, method: str) -> tuple[str, str]:
    """Load the calibration into the graphics card's gamma table when the method allows it. Returns
    (applied method, note): 'ramp' when the table was set, otherwise 'stimuli' (the procedural stimuli and the
    background are corrected in their texture values instead)."""
    if method == "stimuli":
        return "stimuli", ""
    ramp = cal.ramp(256)
    try:
        if sys.platform.startswith("win"):
            ok, note = _ramp_windows(backend, ramp)
        elif sys.platform == "darwin":
            ok, note = _ramp_mac(backend, ramp)
        else:
            ok, note = _ramp_x11(backend, ramp)
    except Exception as e:
        ok, note = False, str(e)
    return ("ramp", "") if ok else ("stimuli", note or "this system does not allow setting the gamma table")


def restore_gamma_ramp(backend: Any) -> None:
    fn = getattr(backend, "_restore_ramp", None)
    if fn is not None:
        try:
            fn()
        except Exception:
            pass
        backend._restore_ramp = None


def _ramp_windows(backend: Any, ramp: list[list[int]]) -> tuple[bool, str]:  # pragma: no cover - Windows only
    import ctypes
    arr_t = (ctypes.c_ushort * 256) * 3
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hdc = user32.GetDC(None)
    old = arr_t()
    gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(old))
    new = arr_t()
    for ch in range(3):
        for i in range(256):
            new[ch][i] = ramp[ch][i]
    if not gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(new)):
        user32.ReleaseDC(None, hdc)
        return False, "Windows refused the gamma table (it limits how far it may be from the default)"

    def restore() -> None:
        gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(old))
        user32.ReleaseDC(None, hdc)
    backend._restore_ramp = restore
    return True, ""


def _ramp_mac(backend: Any, ramp: list[list[int]]) -> tuple[bool, str]:  # pragma: no cover - macOS only
    import ctypes
    import ctypes.util
    cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics") or
                                 "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    disp = cg.CGMainDisplayID()
    arr = ctypes.c_float * 256
    r, g, b = (arr(*[v / 65535 for v in ramp[ch]]) for ch in range(3))
    err = cg.CGSetDisplayTransferByTable(ctypes.c_uint32(disp), ctypes.c_uint32(256), r, g, b)
    if err != 0:
        return False, f"macOS refused the gamma table (error {err})"
    backend._restore_ramp = lambda: cg.CGDisplayRestoreColorSyncSettings()
    return True, ""


def _ramp_x11(backend: Any, ramp: list[list[int]]) -> tuple[bool, str]:
    import ctypes
    import ctypes.util
    name = ctypes.util.find_library("Xxf86vm")
    if not name:
        return False, "libXxf86vm is not installed (sudo apt install libxxf86vm1)"
    vm = ctypes.cdll.LoadLibrary(name)
    win = getattr(backend, "win", None)
    dpy = getattr(win, "_x_display", None)
    scr = int(getattr(win, "_x_screen_id", 0) or 0)
    if not dpy:
        return False, "not an X11 window (Wayland sessions don't allow setting the gamma table)"
    size = ctypes.c_int(0)
    if not vm.XF86VidModeGetGammaRampSize(dpy, scr, ctypes.byref(size)) or size.value <= 0:
        return False, "the X server has no gamma table (XF86VidMode extension missing)"
    n = size.value
    arr_t = ctypes.c_ushort * n
    old = [arr_t() for _ in range(3)]
    vm.XF86VidModeGetGammaRamp(dpy, scr, n, old[0], old[1], old[2])
    new = []
    for ch in range(3):
        a = arr_t()
        for i in range(n):
            a[i] = ramp[ch][min(255, round(i * 255 / max(1, n - 1)))]
        new.append(a)
    if not vm.XF86VidModeSetGammaRamp(dpy, scr, n, new[0], new[1], new[2]):
        return False, "the X server refused the gamma table"
    backend._restore_ramp = lambda: vm.XF86VidModeSetGammaRamp(dpy, scr, n, old[0], old[1], old[2])
    return True, ""
