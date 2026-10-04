"""Markers and the event bus that routes them to every connected device."""

from __future__ import annotations

import itertools
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

_ids = itertools.count(1)


@dataclass
class Marker:
    """One event in the experiment, timestamped on the master clock.

    ``code`` is the small integer sent over TTL lines (1-255); ``label`` is the
    human-readable string sent to devices that accept text (LSL, Gazepoint
    USER_DATA, Tobii Pro Lab events, logs).
    """

    label: str
    time: float
    code: int | None = None
    source: str = ""                 # component / routine that generated it
    fields: dict[str, Any] = field(default_factory=dict)  # trial context
    id: int = field(default_factory=lambda: next(_ids))
    on_flip: bool = False            # time is the measured screen flip time
    delivered: dict[str, float] = field(default_factory=dict)  # device id -> master time sent

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    """Thread-safe publish/subscribe for markers and runtime events."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str, fn: Callable[[Any], None]) -> None:
        with self._lock:
            self._subs.setdefault(topic, []).append(fn)

    def publish(self, topic: str, payload: Any) -> None:
        with self._lock:
            subs = list(self._subs.get(topic, ())) + list(self._subs.get("*", ()))
        for fn in subs:
            fn(payload)
