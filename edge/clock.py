"""Master clock.

Every timestamp EDGE writes (frame flips, responses, markers, device samples
after alignment) is expressed on one monotonic master clock, in seconds.

When pylsl is available the master clock *is* ``pylsl.local_clock()`` so that
EDGE timestamps are directly comparable with any LSL stream recorded on the same
machine (LabRecorder, other apps, etc.). Otherwise ``time.perf_counter`` is used.
"""

from __future__ import annotations

import time
from typing import Callable

_clock_fn: Callable[[], float]
CLOCK_SOURCE: str

try:  # pragma: no cover - depends on the native liblsl being present
    from pylsl import local_clock as _lsl_clock

    _lsl_clock()
    _clock_fn = _lsl_clock
    CLOCK_SOURCE = "lsl.local_clock"
except Exception:  # ImportError, or liblsl shared library missing
    _clock_fn = time.perf_counter
    CLOCK_SOURCE = "time.perf_counter"


def now() -> float:
    """Current master-clock time in seconds."""
    return _clock_fn()


class Clock:
    """A resettable stopwatch on top of the master clock."""

    def __init__(self, source: Callable[[], float] | None = None):
        self._source = source or now
        self._t0 = self._source()

    def reset(self, to: float | None = None) -> None:
        """Make ``time()`` read zero now, or zero at master time ``to``."""
        self._t0 = self._source() if to is None else to

    @property
    def t0(self) -> float:
        return self._t0

    def time(self) -> float:
        return self._source() - self._t0


class VirtualClock:
    """A manually advanced clock used by the headless backend.

    Lets a full experiment run in milliseconds of wall time while every
    timestamp stays exactly reproducible.
    """

    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt
