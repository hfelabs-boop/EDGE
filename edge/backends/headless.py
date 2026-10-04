"""Headless backend: a perfect, virtual display.

* Runs on a :class:`~edge.clock.VirtualClock` advancing exactly one frame per
  flip, so a 40-minute experiment completes in seconds and timing is exact.
* Records what was drawn on every frame (``frame_log``) for assertions in
  tests and for timing audits.
* Accepts scheduled input events, which is how the virtual participant
  "presses keys" during dry runs.
"""

from __future__ import annotations

import heapq
import itertools
from typing import Any

import time

from ..clock import VirtualClock
from ..clock import now as master_now
from .base import Backend, InputEvent, Stim


class HeadlessStim(Stim):
    def __init__(self, backend: "HeadlessBackend", kind: str, props: dict[str, Any]):
        super().__init__(kind, props)
        self.backend = backend

    def draw(self) -> None:
        self.backend._drawn.append((self.kind, dict(self.props)))


class HeadlessBackend(Backend):
    name = "headless"

    def __init__(self, size: tuple[int, int] = (1280, 720), refresh_rate: float = 60.0,
                 clock: VirtualClock | None = None, keep_frame_log: bool = True,
                 frame_jitter: list[float] | None = None, realtime: bool = False):
        self.size = tuple(size)  # type: ignore[assignment]
        self.refresh_rate = refresh_rate
        # realtime=True: no display, but frames are paced on the real master clock, so real
        # hardware (LSL, triggers, physiology) can be used in screenless experiments.
        self.realtime = realtime
        self.vclock = clock or VirtualClock(start=1000.0)
        self.clock = master_now if realtime else self.vclock
        self._next_flip: float | None = None
        self.keep_frame_log = keep_frame_log
        self.frame_log: list[dict[str, Any]] = []
        self._drawn: list[tuple[str, dict[str, Any]]] = []
        self._queue: list[tuple[float, int, InputEvent]] = []
        self._seq = itertools.count()
        self._mouse = (0.0, 0.0)
        self._buttons = [False, False, False]
        self.sounds: list[dict[str, Any]] = []
        self.frame_jitter = list(frame_jitter or [])  # extra seconds added to given frame indices (tests)
        self.n_flips = 0
        self.escape_at: float | None = None

    def open(self, window: dict[str, Any]) -> None:
        if window.get("size"):
            self.size = tuple(window["size"])  # type: ignore[assignment]
        if window.get("refresh_rate"):
            self.refresh_rate = float(window["refresh_rate"])

    def flip(self) -> float:
        if self.realtime:
            now = master_now()
            self._next_flip = now if self._next_flip is None else max(self._next_flip + self.frame_interval, now)
            while master_now() < self._next_flip:
                time.sleep(min(0.001, max(0.0, self._next_flip - master_now())))
            t = master_now()
        else:
            extra = self.frame_jitter[self.n_flips] if self.n_flips < len(self.frame_jitter) else 0.0
            self.vclock.advance(self.frame_interval + extra)
            t = self.vclock()
        if self.keep_frame_log:
            self.frame_log.append({"t": t, "drawn": self._drawn})
        self._drawn = []
        self.n_flips += 1
        return t

    def make_text(self, **props: Any) -> Stim:
        return HeadlessStim(self, "text", props)

    def make_shape(self, shape: str, **props: Any) -> Stim:
        return HeadlessStim(self, shape, props)

    def make_image(self, **props: Any) -> Stim:
        return HeadlessStim(self, "image", props)

    def make_movie(self, **props: Any) -> Stim:
        return HeadlessStim(self, "movie", props)

    def play_sound(self, source: Any, volume: float = 1.0, **kw: Any) -> Any:
        rec = {"t": self.clock(), "source": source, "volume": volume, **kw}
        self.sounds.append(rec)
        return rec

    # ------------------------------------------------------------ input
    def schedule(self, event: InputEvent) -> None:
        heapq.heappush(self._queue, (event.time, next(self._seq), event))

    def press(self, key: str, at: float, release_after: float | None = 0.1) -> None:
        self.schedule(InputEvent("key", key, at, True))
        if release_after is not None:
            self.schedule(InputEvent("key", key, at + release_after, False))

    def click(self, pos: tuple[float, float], at: float, button: str = "left") -> None:
        self.schedule(InputEvent("mouse", button, at, True, pos))
        self.schedule(InputEvent("mouse", button, at + 0.08, False, pos))

    def move_mouse(self, pos: tuple[float, float], at: float) -> None:
        self.schedule(InputEvent("mouse", "move", at, True, pos))

    def poll_events(self) -> list[InputEvent]:
        now = self.clock()
        out = []
        while self._queue and self._queue[0][0] <= now:
            ev = heapq.heappop(self._queue)[2]
            if ev.kind == "mouse":
                if ev.pos is not None:
                    self._mouse = ev.pos
                if ev.name == "move":
                    continue
                idx = {"left": 0, "middle": 1, "right": 2}.get(ev.name, 0)
                self._buttons[idx] = ev.down
            out.append(ev)
        return out

    def mouse_pos(self) -> tuple[float, float]:
        return self._mouse

    def mouse_buttons(self) -> tuple[bool, bool, bool]:
        return tuple(self._buttons)  # type: ignore[return-value]

    def check_escape(self) -> bool:
        return self.escape_at is not None and self.clock() >= self.escape_at

    def wait_for_key(self, keys: list[str] | None = None) -> InputEvent:
        while True:
            for ev in self.poll_events():
                if ev.kind == "key" and ev.down and (not keys or ev.name in keys):
                    return ev
            if not self._queue:
                return InputEvent("key", (keys or ["space"])[0], self.clock())
            self.flip()

    # ------------------------------------------------------------ test helpers
    def frames_showing(self, predicate) -> list[int]:
        return [i for i, f in enumerate(self.frame_log) if any(predicate(k, p) for k, p in f["drawn"])]
