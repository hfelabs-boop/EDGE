"""Clock synchronization between EDGE's master clock and device clocks.

Every device that timestamps its own samples (Tobii: microseconds on the
tracker's system clock; Gazepoint: seconds since its server started; g.tec:
sample counter; LSL: remote ``local_clock`` + offset) gets a
:class:`ClockModel` mapping its time base onto the master clock::

    master = offset + slope * device_time

The model is fitted from (device_time, master_time) pairs gathered during the
session. Pairs come from either NTP-style round-trip probes (the midpoint of the
request/response window, keeping the tightest windows) or from sample arrival
times (each sample arrives *no earlier* than it was taken, so the lower envelope
of arrival-minus-device-time estimates the offset). Drift (slope != 1) is
modelled, so hour-long recordings stay aligned to the millisecond.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass
class ClockModel:
    offset: float = 0.0
    slope: float = 1.0
    n: int = 0
    residual_sd: float = math.nan   # seconds
    method: str = "identity"

    def to_master(self, device_time: float) -> float:
        return self.offset + self.slope * device_time

    def to_device(self, master_time: float) -> float:
        return (master_time - self.offset) / self.slope

    def to_dict(self) -> dict:
        return {"offset": self.offset, "slope": self.slope, "n": self.n,
                "residual_sd_ms": None if math.isnan(self.residual_sd) else self.residual_sd * 1e3,
                "method": self.method}


def fit_linear(pairs: Iterable[tuple[float, float]], fit_drift: bool = True) -> ClockModel:
    """Least-squares fit of master = offset + slope * device."""
    pts = list(pairs)
    n = len(pts)
    if n == 0:
        return ClockModel()
    if n == 1 or not fit_drift:
        off = sum(m - d for d, m in pts) / n
        res = [m - d - off for d, m in pts]
        sd = math.sqrt(sum(r * r for r in res) / n) if n > 1 else math.nan
        return ClockModel(off, 1.0, n, sd, "offset")
    # centre for numerical stability (device clocks can be ~1e12 microseconds)
    md = sum(d for d, _ in pts) / n
    mm = sum(m for _, m in pts) / n
    sxx = sum((d - md) ** 2 for d, _ in pts)
    if sxx == 0:
        return fit_linear(pts, fit_drift=False)
    sxy = sum((d - md) * (m - mm) for d, m in pts)
    slope = sxy / sxx
    offset = mm - slope * md
    res = [m - (offset + slope * d) for d, m in pts]
    sd = math.sqrt(sum(r * r for r in res) / max(n - 2, 1))
    return ClockModel(offset, slope, n, sd, "linear")


@dataclass
class RoundTripSync:
    """NTP-style estimation for devices that can be queried for their time.

    ``probe()`` must return the device's current time. We record the master time
    before and after; the device time is assumed to correspond to the midpoint.
    Only the fastest ``keep`` fraction of round trips is used, which rejects
    probes delayed by OS scheduling or network jitter.
    """

    query_device_time: Callable[[], float]
    master_clock: Callable[[], float]
    keep: float = 0.3
    samples: list[tuple[float, float, float]] = field(default_factory=list)  # (rtt, device, master_mid)

    def probe(self, n: int = 1) -> None:
        for _ in range(n):
            t0 = self.master_clock()
            dev = self.query_device_time()
            t1 = self.master_clock()
            self.samples.append((t1 - t0, dev, (t0 + t1) / 2))

    def model(self, fit_drift: bool = True) -> ClockModel:
        if not self.samples:
            return ClockModel()
        best = sorted(self.samples)[: max(1, int(len(self.samples) * self.keep))]
        m = fit_linear([(d, mm) for _, d, mm in best], fit_drift=fit_drift and len(best) >= 10)
        m.method = "roundtrip-" + m.method
        return m


class ArrivalSync:
    """Estimate a device clock from sample arrival times (lower-envelope method).

    For each sample ``arrival - device_time = offset + transport_delay`` with
    ``transport_delay >= 0``. Within time bins we take the minimum, which
    approximates the true offset, then fit a line through the minima to get drift.
    ``latency`` (known fixed device latency, seconds) is subtracted afterwards.
    """

    def __init__(self, bin_seconds: float = 2.0, latency: float = 0.0):
        self.bin_seconds = bin_seconds
        self.latency = latency
        self._bins: dict[int, tuple[float, float]] = {}  # bin -> (min diff, device time)
        self._first_dev: float | None = None

    def add(self, device_time: float, arrival_master: float) -> None:
        if self._first_dev is None:
            self._first_dev = device_time
        b = int((device_time - self._first_dev) // self.bin_seconds) if self.bin_seconds > 0 else 0
        diff = arrival_master - device_time
        cur = self._bins.get(b)
        if cur is None or diff < cur[0]:
            self._bins[b] = (diff, device_time)

    def model(self) -> ClockModel:
        if not self._bins:
            return ClockModel()
        pts = [(dev, dev + diff - self.latency) for diff, dev in self._bins.values()]
        m = fit_linear(pts, fit_drift=len(pts) >= 5)
        m.method = "arrival-" + m.method
        return m
