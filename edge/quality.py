"""Live signal quality: is every EEG channel usable, is the eye tracker tracking?

Computed from the last few seconds a device has sent (``Device.quality()`` keeps a short buffer of every
regularly sampled stream), so it works for every driver, real or simulated, with no extra hardware support.
Shown on the Run page during a session (the monitor sends it every few seconds) and by Test the device /
``edge test-device``.

EEG (and other signals), per channel:

* ``rms``: the signal's size after removing its offset (µV for EEG). Very large = noisy (muscle, movement,
  a loose electrode).
* ``line_uv`` / ``line_hz``: how much of it is mains hum at 50 or 60 Hz (whichever is stronger), and
  ``line_ratio``, that hum's share of the signal. High = poor contact or an unshielded cable.
* ``flat``: (almost) no change at all: a channel that is not connected, or switched off.
* ``clipped``: the share of samples stuck at the window's extreme value: the amplifier is saturated or the
  electrode is "railing" (off the scalp, a dry gel, a broken lead).
* ``impedance_kohm``: only when the amplifier measures it (see ``Device.impedance``); otherwise the stream
  says ``impedance: {available: false, note: ...}``.

Every channel gets ``status`` ok / warn / bad and ``reasons`` in plain words. Eye trackers get the share of
valid samples (each eye, pupil size) and how often / how long tracking was lost.

Pure Python (numpy is used when installed, for speed); thresholds are in :data:`THRESHOLDS`.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# Thresholds in µV (EEG). A device or experiment can pass its own (Device option ``quality``).
THRESHOLDS: dict[str, float] = {
    "flat_uv": 0.5,          # standard deviation below this: flat
    "noisy_warn_uv": 50.0,   # RMS above this: noisy (amber)
    "noisy_bad_uv": 150.0,   # RMS above this: very noisy (red)
    "line_warn_uv": 5.0,     # 50/60 Hz amplitude (RMS) above this and ...
    "line_warn_ratio": 0.25,  # ... more than this share of the power: line noise (amber)
    "line_bad_uv": 15.0,
    "line_bad_ratio": 0.5,
    "clip_bad": 0.05,        # 5 % of samples stuck at the extreme: saturated / railing
    "offset_bad_uv": 250_000.0,  # DC offset beyond this (e.g. +-250 mV): the amplifier is railing
    "imp_warn_kohm": 10.0,
    "imp_bad_kohm": 25.0,
    "gaze_warn_pct": 85.0,   # valid gaze samples below this: amber
    "gaze_bad_pct": 60.0,
    "loss_warn_s": 1.0,      # tracking lost for longer than this: amber
}
WINDOW_S = 2.0               # the seconds of signal the metrics use
TRIGGER_NAMES = {"trig", "trigger", "event", "user", "marker", "code", "markers", "status", "counter", "cnt",
                 "time", "time_tick", "timestamp", "device_time_stamp", "system_time_stamp"}
SCALE_TO_UV = {"uv": 1.0, "µv": 1.0, "microvolts": 1.0, "mv": 1e3, "millivolts": 1e3, "v": 1e6, "volts": 1e6,
               "nv": 1e-3}

try:     # optional, only for speed
    import numpy as _np
except Exception:   # pragma: no cover - numpy is optional
    _np = None


# ----------------------------------------------------------------------------- signal metrics
def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def goertzel_amplitude(x: Sequence[float], srate: float, freq: float) -> float:
    """The RMS amplitude of the ``freq`` Hz component of ``x`` (offset removed): a pure sine of amplitude A
    gives A/√2. Uses a Hann window, so nearby frequencies leak little."""
    n = len(x)
    if n < 8 or not srate or freq >= srate / 2:
        return 0.0
    if _np is not None:
        a = _np.asarray(x, dtype=float)
        a = a - a.mean()
        w = _np.hanning(n)
        t = _np.arange(n) / srate
        c = _np.sum(a * w * _np.cos(2 * _np.pi * freq * t))
        s = _np.sum(a * w * _np.sin(2 * _np.pi * freq * t))
        return float(_np.hypot(c, s) * 2 / w.sum() / math.sqrt(2))
    mean = sum(x) / n
    k = 2 * math.pi * freq / srate
    c = s = wsum = 0.0
    for i, v in enumerate(x):
        w = 0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))
        wsum += w
        c += (v - mean) * w * math.cos(k * i)
        s += (v - mean) * w * math.sin(k * i)
    return math.hypot(c, s) * 2 / wsum / math.sqrt(2)


def channel_metrics(x: Sequence[float], srate: float, scale: float = 1.0,
                    thresholds: dict[str, float] | None = None, signal: bool = True) -> dict[str, Any]:
    """Quality of one channel from its recent samples (already numbers). ``scale`` converts to µV.
    ``signal=False`` (physiology other than EEG): only flat / clipped / railing decide the status."""
    th = {**THRESHOLDS, **(thresholds or {})}
    n = len(x)
    out: dict[str, Any] = {"n": n, "status": "ok", "reasons": []}
    if n < max(8, int(0.25 * (srate or 0))):
        out.update(status="wait", reasons=["not enough data yet"])
        return out
    vals = [v * scale for v in x] if scale != 1.0 else list(x)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    sd = math.sqrt(var)
    lo, hi = min(vals), max(vals)
    at_hi = sum(1 for v in vals if v == hi)
    at_lo = sum(1 for v in vals if v == lo)
    clipped = (max(at_hi, at_lo) / n) if hi > lo else 0.0
    l50 = goertzel_amplitude(vals, srate, 50.0)
    l60 = goertzel_amplitude(vals, srate, 60.0)
    line_hz, line_uv = (50, l50) if l50 >= l60 else (60, l60)
    ratio = min(1.0, (line_uv ** 2) / var) if var > 0 else 0.0
    out.update(rms=round(sd, 2), offset=round(mean, 2), ptp=round(hi - lo, 2), line_hz=line_hz,
               line_uv=round(line_uv, 2), line_ratio=round(ratio, 3), clipped=round(clipped, 3),
               flat=sd < th["flat_uv"] if signal else (hi - lo) <= 1e-12)
    bad, warn = [], []
    if out["flat"]:
        bad.append("flat: no signal (not connected or switched off?)")
    elif clipped >= th["clip_bad"] and hi - lo > 0:
        bad.append(f"saturated: {round(clipped * 100)} % of the samples stuck at the limit (railing)")
    if signal and abs(mean) >= th["offset_bad_uv"]:
        bad.append("railing: a very large offset (electrode off or dry?)")
    if signal and not out["flat"]:
        if sd >= th["noisy_bad_uv"]:
            bad.append(f"very noisy ({sd:.0f} µV)")
        elif sd >= th["noisy_warn_uv"]:
            warn.append(f"noisy ({sd:.0f} µV)")
        if line_uv >= th["line_bad_uv"] and ratio >= th["line_bad_ratio"]:
            bad.append(f"strong {line_hz} Hz line noise ({line_uv:.0f} µV)")
        elif line_uv >= th["line_warn_uv"] and ratio >= th["line_warn_ratio"]:
            warn.append(f"{line_hz} Hz line noise ({line_uv:.1f} µV)")
    out["reasons"] = bad + warn
    out["status"] = "bad" if bad else "warn" if warn else "ok"
    return out


def impedance_status(kohm: float | None, thresholds: dict[str, float] | None = None) -> str:
    th = {**THRESHOLDS, **(thresholds or {})}
    if kohm is None:
        return "unknown"
    return "ok" if kohm < th["imp_warn_kohm"] else "warn" if kohm < th["imp_bad_kohm"] else "bad"


def _is_data_channel(name: str, unit: str) -> bool:
    return name.strip().lower() not in TRIGGER_NAMES and unit.strip().lower() not in ("code", "bool", "codes")


def _worst(statuses: Iterable[str]) -> str:
    s = set(statuses)
    return "bad" if "bad" in s else "warn" if "warn" in s else "ok" if "ok" in s else "wait"


def signal_quality(channels: list[str], units: list[str] | None, samples: list[list[Any]], srate: float,
                   kind: str = "EEG", impedance: dict[str, float] | None = None, impedance_note: str = "",
                   thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """Per-channel quality of a sampled stream (EEG, ECG, EMG …) from its recent ``samples`` (rows of values)."""
    units = list(units or [])
    eeg = kind.upper() in ("EEG", "EXG", "EMG", "ECOG", "MEG")
    keep = int(WINDOW_S * srate) if srate else len(samples)
    rows = samples[-keep:] if keep else samples
    chans = []
    for i, name in enumerate(channels):
        unit = units[i] if i < len(units) and units[i] else ""
        if not _is_data_channel(str(name), unit):
            continue
        x = [v for v in (_num(r[i]) if i < len(r) else None for r in rows) if v is not None]
        scale = SCALE_TO_UV.get(unit.strip().lower(), 1.0) if eeg else 1.0
        m = channel_metrics(x, srate, scale, thresholds, signal=eeg)
        m["name"] = str(name)
        if impedance and str(name) in impedance and impedance[str(name)] is not None:
            k = float(impedance[str(name)])
            m["impedance_kohm"] = round(k, 1)
            st = impedance_status(k, thresholds)
            if st in ("warn", "bad") and m["status"] != "wait":
                m["reasons"].append(f"impedance {k:.0f} kΩ")
                if st == "bad":
                    m["status"] = "bad"
                elif m["status"] == "ok":
                    m["status"] = "warn"
        chans.append(m)
    counts = {s: sum(1 for c in chans if c["status"] == s) for s in ("ok", "warn", "bad", "wait")}
    return {"kind": "signal", "stream_kind": kind, "units": "µV" if eeg else "", "window_s": WINDOW_S,
            "status": _worst(c["status"] for c in chans), "counts": counts, "channels": chans,
            "impedance": {"available": bool(impedance and eeg), "applies": eeg, "note": "" if impedance or not eeg else
                          (impedance_note or "not available from this device")}}


# ----------------------------------------------------------------------------- eye trackers
def _find(channels: list[str], *names: str) -> int | None:
    low = [c.lower() for c in channels]
    for n in names:
        if n.lower() in low:
            return low.index(n.lower())
    return None


def _truthy(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "1.0", "yes")
    f = _num(v)
    return None if f is None else f > 0


def gaze_quality(channels: list[str], samples: list[list[Any]], srate: float,
                 thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """Eye-tracker data quality from recent samples: valid gaze %, each eye %, pupil %, tracking losses."""
    th = {**THRESHOLDS, **(thresholds or {})}
    keep = int(max(WINDOW_S, 5.0) * srate) if srate else len(samples)
    rows = samples[-keep:] if keep else samples
    n = len(rows)
    out: dict[str, Any] = {"kind": "gaze", "window_s": round(n / srate, 1) if srate else None, "n": n,
                           "status": "wait", "reasons": []}
    if n < max(5, int(0.25 * (srate or 0))):
        out["reasons"] = ["not enough data yet"]
        return out
    left = _find(channels, "left_valid", "LPV", "valid_l", "left_validity")
    right = _find(channels, "right_valid", "RPV", "valid_r", "right_validity")
    both = _find(channels, "valid", "BPOGV", "FPOGV", "validity")
    xi, yi = _find(channels, "x", "gaze_x", "BPOGX", "FPOGX", "left_x"), _find(channels, "y", "gaze_y", "BPOGY", "FPOGY", "left_y")
    pupils = [i for i in (_find(channels, "pupil_l", "left_pupil", "LPMM", "LPD"),
                          _find(channels, "pupil_r", "right_pupil", "RPMM", "RPD")) if i is not None]

    def valid(r: list[Any]) -> bool:
        if both is not None:
            return bool(_truthy(r[both]))
        if left is not None or right is not None:
            return any(_truthy(r[i]) for i in (left, right) if i is not None)
        if xi is not None and yi is not None:
            return _num(r[xi]) is not None and _num(r[yi]) is not None
        return True

    flags = [valid(r) for r in rows]
    pct = 100.0 * sum(flags) / n
    out["validity_pct"] = round(pct, 1)
    for key, idx in (("left_pct", left), ("right_pct", right)):
        if idx is not None:
            out[key] = round(100.0 * sum(bool(_truthy(r[idx])) for r in rows) / n, 1)
    if pupils:
        ok = sum(1 for r in rows if any((_num(r[i]) or 0) > 0 for i in pupils))
        out["pupil_pct"] = round(100.0 * ok / n, 1)
        sizes = [_num(r[pupils[0]]) for r in rows]
        sizes = [s for s in sizes if s]
        if sizes:
            out["pupil_mean"] = round(sum(sizes) / len(sizes), 2)
    losses, run, longest = 0, 0, 0
    for f in flags:
        if not f:
            run += 1
            if run == 1:
                losses += 1
            longest = max(longest, run)
        else:
            run = 0
    out["losses"] = losses
    out["longest_loss_s"] = round(longest / srate, 2) if srate else None
    out["lost_now"] = not flags[-1]
    reasons_bad, reasons_warn = [], []
    if pct < th["gaze_bad_pct"]:
        reasons_bad.append(f"only {pct:.0f} % valid gaze samples")
    elif pct < th["gaze_warn_pct"]:
        reasons_warn.append(f"{pct:.0f} % valid gaze samples")
    if srate and longest / srate >= th["loss_warn_s"]:
        reasons_warn.append(f"tracking lost for {longest / srate:.1f} s")
    if flags[-int(min(n, max(1, srate * 0.5))):].count(True) == 0:
        reasons_bad.append("not tracking now (is the participant in view?)")
    out["reasons"] = reasons_bad + reasons_warn
    out["status"] = "bad" if reasons_bad else "warn" if reasons_warn else "ok"
    return out


def stream_quality(info: Any, samples: list[list[Any]], impedance: dict[str, float] | None = None,
                   impedance_note: str = "", thresholds: dict[str, float] | None = None) -> dict[str, Any] | None:
    """Quality of one device stream (a ``StreamInfo``), or None for streams without a regular rate (events)."""
    if not getattr(info, "srate", 0):
        return None
    kind = (info.kind or "").strip()
    if kind.lower() in ("gaze", "eyetracking", "eye", "pupil") or {"x", "y"} <= {c.lower() for c in info.channels} \
            and kind.lower() not in ("eeg", "physio"):
        return gaze_quality(info.channels, samples, float(info.srate), thresholds)
    if kind.lower() in ("audio", "events", "markers"):
        return None
    return signal_quality(info.channels, info.units, samples, float(info.srate), kind or "signal",
                          impedance, impedance_note, thresholds)


def summary_words(q: dict[str, Any]) -> str:
    """One line for a stream's quality: "6 good, 1 noisy, 1 bad: C4 50 Hz line noise; P4 flat"."""
    if not q:
        return ""
    if q.get("kind") == "gaze":
        if q.get("status") == "wait":
            return "waiting for data"
        bits = [f"{q.get('validity_pct', 0):.0f} % valid"]
        if "left_pct" in q and "right_pct" in q:
            bits.append(f"left {q['left_pct']:.0f} %, right {q['right_pct']:.0f} %")
        if q.get("pupil_pct") is not None:
            bits.append(f"pupil {q['pupil_pct']:.0f} %")
        bits.append(f"{q.get('losses', 0)} tracking loss(es), longest {q.get('longest_loss_s') or 0:.1f} s")
        return "; ".join(bits)
    c = q.get("counts") or {}
    bad = [ch for ch in q.get("channels", []) if ch["status"] in ("bad", "warn")]
    head = f"{c.get('ok', 0)} good, {c.get('warn', 0)} to check, {c.get('bad', 0)} bad"
    detail = "; ".join(f"{ch['name']} {ch['reasons'][0] if ch.get('reasons') else ch['status']}" for ch in bad[:6])
    imp = q.get("impedance") or {}
    tail = "" if imp.get("available") or imp.get("applies") is False else \
        f" (impedance {imp.get('note') or 'not available from this device'})"
    return head + (f": {detail}" if detail else "") + tail
