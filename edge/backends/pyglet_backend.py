"""OpenGL window backend built on pyglet 2.x.

* vsync-locked flips, timestamped right after ``glFinish`` so the reported time
  is when the frame was actually handed to the display;
* refresh rate measured at startup (not trusted from the OS);
* keyboard events timestamped as early as the OS delivers them;
* text, shapes, images and sounds through pyglet.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from typing import Any

from ..clock import now
from .base import Backend, InputEvent, Stim, parse_color

_KEYMAP_CACHE: dict[int, str] = {}


def _keyname(symbol: int) -> str:
    if symbol not in _KEYMAP_CACHE:
        from pyglet.window import key
        name = key.symbol_string(symbol).lower()
        name = {"_1": "1", "_2": "2", "_3": "3", "_4": "4", "_5": "5", "_6": "6", "_7": "7", "_8": "8", "_9": "9",
                "_0": "0", "enter": "return"}.get(name, name)
        _KEYMAP_CACHE[symbol] = name
    return _KEYMAP_CACHE[symbol]


class PygletStim(Stim):
    def __init__(self, backend: "PygletBackend", kind: str, props: dict[str, Any]):
        super().__init__(kind, props)
        self.b = backend
        self.obj: Any = None
        self._dirty = True

    def set(self, **props: Any) -> None:
        if any(self.props.get(k) != v for k, v in props.items()):
            self.props.update(props)
            self._dirty = True

    def _build(self) -> None:
        import pyglet
        p = self.props
        cx, cy = self.b.size[0] / 2, self.b.size[1] / 2
        x, y = p.get("pos", (0, 0))
        X, Y = cx + x, cy + y
        opacity = float(p.get("opacity", 1.0))
        k = self.kind
        if k == "text":
            r, g, b_, a = parse_color(p.get("color", "white"))
            if self.obj is None:
                self.obj = pyglet.text.Label("", anchor_x="center", anchor_y="center", multiline=True,
                                             align="center", width=int(p.get("wrap_width") or self.b.size[0] * 0.8))
            o = self.obj
            from ..bidi import visual
            o.text = visual(str(p.get("text", "")), str(p.get("direction") or "auto"))   # right-to-left scripts
            o.font_name = p.get("font") or None
            o.font_size = float(p.get("height", 32)) * 0.75  # px -> pt
            o.bold = bool(p.get("bold", False))
            o.italic = bool(p.get("italic", False))
            o.width = int(p.get("wrap_width") or self.b.size[0] * 0.8)
            o.color = (r, g, b_, int(a * opacity))
            o.x, o.y = X, Y
            o.rotation = float(p.get("ori", 0))
        elif k in ("rect", "circle", "polygon", "line", "cross", "ellipse"):
            self.obj = self._shape(pyglet, X, Y, opacity)
        elif k == "image":
            src = p["image"]
            img = self.b.load_image(src)
            spr = pyglet.sprite.Sprite(img, x=X, y=Y)
            w, h = p.get("size") or (img.width, img.height)
            spr.scale_x, spr.scale_y = w / img.width, h / img.height
            spr.rotation = float(p.get("ori", 0))
            spr.opacity = int(255 * opacity)
            self.obj = spr
        self._dirty = False

    def _shape(self, pyglet, X: float, Y: float, opacity: float):
        from pyglet import shapes
        p = self.props
        fill = parse_color(p.get("fill", "white"))
        line = p.get("line_color")
        lw = float(p.get("line_width", 2))
        alpha = lambda c: int(c[3] * opacity)  # noqa: E731
        k = self.kind
        objs = []
        if k == "rect":
            w, h = p.get("size", (100, 100))
            if fill[3]:
                r = shapes.Rectangle(X, Y, w, h, color=fill[:3])
                r.anchor_x, r.anchor_y = w / 2, h / 2
                r.rotation = float(p.get("ori", 0))
                r.opacity = alpha(fill)
                objs.append(r)
            if line:
                lc = parse_color(line)
                bx = shapes.Box(X - w / 2, Y - h / 2, w, h, thickness=lw, color=lc[:3])
                bx.opacity = alpha(lc)
                objs.append(bx)
        elif k in ("circle", "ellipse"):
            if k == "circle":
                c = shapes.Circle(X, Y, float(p.get("radius", 50)), color=fill[:3])
            else:
                w, h = p.get("size", (100, 60))
                c = shapes.Ellipse(X, Y, w / 2, h / 2, color=fill[:3])
            c.opacity = alpha(fill)
            objs.append(c)
            if line and k == "circle":
                lc = parse_color(line)
                arc = shapes.Arc(X, Y, float(p.get("radius", 50)), thickness=lw, color=lc[:3])
                objs.append(arc)
        elif k == "polygon":
            pts = [(X + vx, Y + vy) for vx, vy in p.get("vertices", [])]
            pg = shapes.Polygon(*pts, color=fill[:3])
            pg.opacity = alpha(fill)
            objs.append(pg)
        elif k == "line":
            (x1, y1), (x2, y2) = p.get("start", (-50, 0)), p.get("end", (50, 0))
            lc = parse_color(p.get("line_color") or p.get("fill", "white"))
            ln = shapes.Line(X + x1, Y + y1, X + x2, Y + y2, thickness=lw, color=lc[:3])
            ln.opacity = alpha(lc)
            objs.append(ln)
        elif k == "cross":
            s = float(p.get("size", 40)) / 2
            lc = parse_color(p.get("line_color") or p.get("fill", "white"))
            th = float(p.get("line_width", 4))
            objs += [shapes.Line(X - s, Y, X + s, Y, thickness=th, color=lc[:3]),
                     shapes.Line(X, Y - s, X, Y + s, thickness=th, color=lc[:3])]
        return objs

    def draw(self) -> None:
        if self._dirty or self.obj is None:
            self._build()
        if isinstance(self.obj, list):
            for o in self.obj:
                o.draw()
        elif self.obj is not None:
            self.obj.draw()


class PygletBackend(Backend):
    name = "pyglet"

    def __init__(self) -> None:
        self.clock = now
        self._events: list[InputEvent] = []
        self._images: dict[str, Any] = {}
        self._mouse = (0.0, 0.0)
        self._buttons = [False, False, False]
        self._escape = False
        self.base_dir = Path.cwd()

    def open(self, window: dict[str, Any]) -> None:
        import pyglet
        self.warnings: list[str] = []
        self.diagnostics: dict[str, Any] = {}
        self.focus_events: list[tuple[float, bool]] = []
        self._refocus = False
        self._sounds: dict[str, Any] = {}
        if sys.platform.startswith("win"):
            _dpi_aware()   # draw in real pixels even with display scaling (Windows would stretch the window)
            # DirectSound adds latency and clips; XAudio2 (Windows 10+) first
            pyglet.options["audio"] = ("xaudio2", "directsound", "openal", "silent")
        pyglet.options["vsync"] = bool(window.get("vsync", True))
        display = pyglet.display.get_display()
        screens = display.get_screens()
        screen = screens[min(int(window.get("screen", 0)), len(screens) - 1)]
        config = pyglet.gl.Config(double_buffer=True, sample_buffers=1, samples=4)
        try:
            config = screen.get_best_config(config)
        except pyglet.window.NoSuchConfigException:
            config = None
        kw: dict[str, Any] = {"vsync": bool(window.get("vsync", True)), "caption": "EDGE"}
        if window.get("fullscreen"):
            self.win = pyglet.window.Window(fullscreen=True, screen=screen, config=config, **kw)
        else:
            w, h = window.get("size", (1280, 720))
            self.win = pyglet.window.Window(int(w), int(h), screen=screen, config=config, **kw)
        self.size = (self.win.width, self.win.height)
        self.win.set_mouse_visible(bool(window.get("mouse_visible", False)))
        self.set_background(window.get("background", "#000000"))
        self._install_handlers()
        try:   # take keyboard focus now: otherwise the first key presses can go to another window
            self.win.activate()
        except Exception:
            pass
        self.diagnostics.update(screens=len(screens), screen=screens.index(screen) if screen in screens else 0,
                                screen_size=[screen.width, screen.height])
        self._check_renderer()
        measured, jitter_ms = self.measure_refresh()
        self.refresh_rate = measured
        self.diagnostics.update(refresh_rate_measured=measured, frame_jitter_ms=jitter_ms)
        self.warnings += refresh_warnings(measured, jitter_ms, window.get("refresh_rate"))
        self._check_audio()

    def _check_renderer(self) -> None:
        try:
            from pyglet import gl
            renderer = gl.glGetString(gl.GL_RENDERER)
            renderer = _gl_str(renderer)
        except Exception:
            return
        self.diagnostics["renderer"] = renderer
        from ..syscheck import is_software_renderer
        if is_software_renderer(renderer):
            self.warnings.append(f"software rendering ({renderer}): the graphics card's driver is not in use, so there is "
                                 "no reliable vsync and stimulus timing cannot be trusted; install the GPU driver")

    def _check_audio(self) -> None:
        try:
            import pyglet
            drv = type(pyglet.media.get_audio_driver()).__name__
        except Exception:
            return
        self.diagnostics["audio_driver"] = drv
        if "Silent" in drv:
            self.warnings.append("no sound device: sounds will not play")
        elif "DirectSound" in drv:
            self.warnings.append("sound uses DirectSound, which adds latency and can clip; XAudio2 was not available")

    def _install_handlers(self) -> None:
        from pyglet.window import key, mouse
        win = self.win
        h = self.size[1]
        w = self.size[0]

        @win.event
        def on_key_press(symbol, modifiers):
            t = now()
            if symbol == key.ESCAPE:
                self._escape = True
            self._events.append(InputEvent("key", _keyname(symbol), t, True, meta={"modifiers": modifiers}))
            return True  # stop pyglet closing the window on ESC

        @win.event
        def on_deactivate():
            self.focus_events.append((now(), False))
            self._refocus = True

        @win.event
        def on_activate():
            self.focus_events.append((now(), True))

        @win.event
        def on_key_release(symbol, modifiers):
            self._events.append(InputEvent("key", _keyname(symbol), now(), False))

        def btn(b):
            return {mouse.LEFT: "left", mouse.MIDDLE: "middle", mouse.RIGHT: "right"}.get(b, "left")

        @win.event
        def on_mouse_motion(x, y, dx, dy):
            self._mouse = (x - w / 2, y - h / 2)

        @win.event
        def on_mouse_drag(x, y, dx, dy, buttons, modifiers):
            self._mouse = (x - w / 2, y - h / 2)

        @win.event
        def on_mouse_press(x, y, button, modifiers):
            self._mouse = (x - w / 2, y - h / 2)
            self._buttons[{"left": 0, "middle": 1, "right": 2}[btn(button)]] = True
            self._events.append(InputEvent("mouse", btn(button), now(), True, self._mouse))

        @win.event
        def on_mouse_release(x, y, button, modifiers):
            self._buttons[{"left": 0, "middle": 1, "right": 2}[btn(button)]] = False
            self._events.append(InputEvent("mouse", btn(button), now(), False, (x - w / 2, y - h / 2)))

    def measure_refresh(self, n: int = 90) -> tuple[float, float]:
        """Refresh rate from the flips themselves (the OS's figure is often wrong), and how much the
        frame intervals vary (variable refresh such as G-Sync/FreeSync, or a compositor)."""
        times = []
        for _ in range(n + 10):
            times.append(self.flip())
        iv = [b - a for a, b in zip(times[10:], times[11:])]
        med = statistics.median(iv) if iv else 1 / 60
        rate = round(1.0 / med, 2) if med > 0 else 60.0
        good = [x for x in iv if x < 1.5 * med]          # dropped frames aren't jitter
        jitter = round(statistics.pstdev(good) * 1e3, 3) if len(good) > 2 else 0.0
        return rate, jitter

    def measure_refresh_rate(self, n: int = 60) -> float:
        return self.measure_refresh(n)[0]

    def set_background(self, color: Any) -> None:
        from pyglet import gl
        r, g, b, a = parse_color(color)
        gl.glClearColor(r / 255, g / 255, b / 255, 1.0)

    def flip(self) -> float:
        from pyglet import gl
        self.win.flip()
        gl.glFinish()
        t = now()
        self.win.dispatch_events()
        self.win.clear()
        if self._refocus:          # the window lost focus (a notification, another program): take it back
            self._refocus = False
            try:
                self.win.activate()
            except Exception:
                pass
        return t

    def close(self) -> None:
        try:
            self.win.close()
        except Exception:
            pass

    def make_text(self, **props: Any) -> Stim:
        return PygletStim(self, "text", props)

    def make_shape(self, shape: str, **props: Any) -> Stim:
        return PygletStim(self, shape, props)

    def make_image(self, **props: Any) -> Stim:
        return PygletStim(self, "image", props)

    def load_image(self, src: str):
        import pyglet
        if src not in self._images:
            path = Path(src)
            if not path.is_absolute():
                path = self.base_dir / path
            img = pyglet.image.load(str(path))
            img.anchor_x, img.anchor_y = img.width // 2, img.height // 2
            self._images[src] = img
        return self._images[src]

    def preload_sound(self, source: Any, **kw: Any) -> Any:
        """Decode a sound before it is needed: loading at the moment of playing delays (and can clip) the onset."""
        import pyglet
        key = f"{source}|{kw.get('duration')}"
        if key not in self._sounds:
            if isinstance(source, (int, float)):  # tone in Hz
                self._sounds[key] = pyglet.media.StaticSource(
                    pyglet.media.synthesis.Sine(float(kw.get("duration", 0.2)), frequency=float(source)))
            else:
                path = Path(source)
                if not path.is_absolute():
                    path = self.base_dir / path
                self._sounds[key] = pyglet.media.load(str(path), streaming=False)
        return self._sounds[key]

    def play_sound(self, source: Any, volume: float = 1.0, **kw: Any) -> Any:
        snd = source if hasattr(source, "play") else self.preload_sound(source, **kw)
        player = snd.play()
        player.volume = volume
        return player

    def stop_sound(self, handle: Any) -> None:
        try:
            handle.pause()
            handle.delete()
        except Exception:
            pass

    def poll_events(self) -> list[InputEvent]:
        self.win.dispatch_events()
        ev, self._events = self._events, []
        return ev

    def mouse_pos(self) -> tuple[float, float]:
        return self._mouse

    def mouse_buttons(self) -> tuple[bool, bool, bool]:
        return tuple(self._buttons)  # type: ignore[return-value]

    def check_escape(self) -> bool:
        return self._escape

    def wait_for_key(self, keys: list[str] | None = None) -> InputEvent:
        while True:
            for ev in self.poll_events():
                if ev.kind == "key" and ev.down and (not keys or ev.name in keys):
                    return ev
            time.sleep(0.001)


def _gl_str(v: Any) -> str:
    import ctypes
    if isinstance(v, bytes):
        return v.decode(errors="replace")
    try:
        return ctypes.cast(v, ctypes.c_char_p).value.decode(errors="replace")
    except Exception:
        return str(v)


def _dpi_aware() -> None:  # pragma: no cover - Windows only
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # per-monitor v2
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def refresh_warnings(measured: float, jitter_ms: float, requested: Any = None) -> list[str]:
    """What's worth knowing about the measured refresh rate before trusting frame timing."""
    out = []
    if requested and measured < 300:            # above 300 Hz vsync is off: that warning says it all
        try:
            req = float(requested)
            if req > 0 and abs(measured - req) / req > 0.02:
                out.append(f"the screen runs at {measured:g} Hz, not the {req:g} Hz in the settings: durations are "
                           f"timed with {measured:g} Hz (set the monitor's refresh rate in the display settings)")
        except (TypeError, ValueError):
            pass
    if measured < 300 and jitter_ms > 1.0:
        out.append(f"frame intervals vary by {jitter_ms:.1f} ms: variable refresh (G-Sync / FreeSync / Adaptive Sync) "
                   "or a desktop compositor seems to be on; turn it off for fixed frame timing")
    if 200 <= measured < 300:
        out.append(f"{measured:g} Hz monitor: many of these show each frame one refresh later than reported; "
                   "measure the real delay with a light sensor (input named 'light')")
    return out
