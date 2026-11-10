"""Epochs: stretches of a recorded signal (EEG, pupil size, physiology) around event markers.

``epochs(session, stream="eeg", markers=["deviant", "standard"], tmin=-0.2, tmax=0.8, baseline=(-0.2, 0))``

1. reads the stream and the markers; both are on EDGE's master clock (the stream's ``time`` column is the
   aligned time, events.jsonl holds when each marker happened), so no trigger channel is needed
2. pupil (``stream="pupil"`` or a gaze stream): blinks and lost samples are filled first by linear
   interpolation, padded before and after the gap (eyelid closure distorts the samples next to it)
3. cuts every epoch on a regular grid from ``tmin`` to ``tmax`` around each marker (linear interpolation
   between the two nearest samples, so the grid is exact whatever the sampling phase)
4. subtracts the mean of the baseline window, per epoch and channel
5. rejects epochs whose peak-to-peak range exceeds ``reject`` on any channel (default 150 for channels in
   microvolts) or that miss more than half their samples
6. averages the kept epochs per condition (the marker's label, or trial-list columns from ``by``)

Writes ``epochs_<stream>.npz`` (numpy.load), ``epochs_<stream>.csv`` (long: one row per epoch, channel and
time), ``epochs_<stream>_info.csv`` (one row per epoch), ``erp_<stream>.csv`` (mean, SD, SE and n per
condition, channel and time) and, with matplotlib installed, ``erp_<stream>.png``.
"""

from __future__ import annotations

import bisect
import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from .common import (NAN, PLOT_NOTE, TRIGGER_CHANNELS, AnalysisError, Session, isnan, plot_available, write_csv,
                     write_npz)

EEG_REJECT_UV = 150.0
BLINK_PAD = (0.05, 0.10)        # seconds filled before and after each blink / data loss in pupil data
BLINK_MAX = 1.0                 # longer losses are left missing (not a blink)
MAX_MISSING = 0.5               # an epoch missing more than this share of a channel is rejected


# ============================================================================ signal helpers
def interpolate_blinks(t: list[float], v: list[float], pad: tuple[float, float] = BLINK_PAD,
                       max_gap: float = BLINK_MAX) -> tuple[list[float], int, list[bool]]:
    """Fill blinks (runs of NaN or non-positive values) in a pupil trace. Each gap is widened by ``pad``
    (before, after), then filled linearly when it is at most ``max_gap`` long. Returns (values, blinks filled,
    which samples were filled)."""
    n = len(v)
    bad = [isnan(x) or x <= 0 for x in v]
    widened = list(bad)
    i = 0
    while i < n:
        if bad[i]:
            j = i
            while j < n and bad[j]:
                j += 1
            lo = bisect.bisect_left(t, t[i] - pad[0])
            hi = bisect.bisect_right(t, (t[j - 1] if j > 0 else t[i]) + pad[1])
            for k in range(lo, min(hi, n)):
                widened[k] = True
            i = j
        else:
            i += 1
    out = [NAN if w else x for x, w in zip(v, widened)]
    filled = [False] * n
    blinks = 0
    i = 0
    while i < n:
        if widened[i]:
            j = i
            while j < n and widened[j]:
                j += 1
            if i > 0 and j < n and t[j] - t[i - 1] <= max_gap + sum(pad):
                a, b = out[i - 1], out[j]
                for k in range(i, j):
                    out[k] = a + (t[k] - t[i - 1]) / (t[j] - t[i - 1]) * (b - a)
                    filled[k] = True
                blinks += 1
            i = j
        else:
            i += 1
    return out, blinks, filled


def cut(times: list[float], values: list[float], onset: float, grid: list[float], srate: float) -> list[float]:
    """``values`` at ``onset + grid`` (linear interpolation; NaN where the recording has no data within
    two samples)."""
    out = []
    n = len(times)
    i = bisect.bisect_left(times, onset + grid[0]) if grid else 0
    max_dt = 2.0 / srate if srate else math.inf
    for g in grid:
        tg = onset + g
        while i < n and times[i] < tg:
            i += 1
        if i < n and abs(times[i] - tg) < 1e-9:
            out.append(values[i])
            continue
        if i == 0 or i >= n or times[i] - times[i - 1] > max_dt:
            out.append(NAN)
            continue
        a, b = values[i - 1], values[i]
        if isnan(a) or isnan(b):
            out.append(NAN)
            continue
        f = (tg - times[i - 1]) / (times[i] - times[i - 1])
        out.append(a + f * (b - a))
    return out


def baseline_correct(epoch: list[float], grid: list[float], window: tuple[float, float] | None) -> list[float]:
    if window is None:
        return epoch
    b0, b1 = window
    base = [v for g, v in zip(grid, epoch) if b0 - 1e-9 <= g <= b1 + 1e-9 and not isnan(v)]
    if not base:
        return [NAN] * len(epoch)
    m = sum(base) / len(base)
    return [v - m for v in epoch]


def _grid(tmin: float, tmax: float, srate: float) -> list[float]:
    n0, n1 = round(tmin * srate), round(tmax * srate)
    return [k / srate for k in range(n0, n1 + 1)]


# ============================================================================ on a session
def epochs(session: str | Path | Session, stream: str = "eeg", markers: Iterable[str] | str = (),
           tmin: float = -0.2, tmax: float = 0.8, baseline: tuple[float, float] | None = (-0.2, 0.0),
           reject: float | str | None = "auto", channels: Iterable[str] | str | None = None,
           by: Iterable[str] | str | None = None, out: str | Path | None = None, plot: bool = True,
           blink_pad: tuple[float, float] = BLINK_PAD, write: bool = True) -> dict[str, Any]:
    """Cut, baseline-correct, reject and average epochs of one stream around markers (see the module text).

    ``stream``: device id, ``device.stream`` or kind (eeg), or ``pupil`` for the eye tracker's pupil size.
    ``markers``: marker labels (wildcards allowed: ``view_*``; a number matches the TTL code).
    ``reject``: peak-to-peak limit in the channel's units, ``"auto"`` (150 for µV channels, none otherwise) or
    None. ``by``: trial-list columns that define the conditions (default: the marker label)."""
    sess = session if isinstance(session, Session) else Session(session)
    markers = [m for m in (markers.split(",") if isinstance(markers, str) else list(markers)) if str(m).strip()]
    if not markers:
        labels = sess.marker_labels()
        raise AnalysisError("say which markers to cut epochs around (--markers)" +
                            (f"; this session has: {', '.join(f'{k} ({v}x)' for k, v in labels.items())}"
                             if labels else "; this session has no markers"))
    if not tmax > tmin:
        raise AnalysisError(f"the epoch must end after it starts (tmin {tmin}, tmax {tmax})")
    if baseline is not None:
        baseline = (float(baseline[0]), float(baseline[1]))
        if baseline[0] > baseline[1] or baseline[0] < tmin - 1e-9 or baseline[1] > tmax + 1e-9:
            raise AnalysisError(f"the baseline {baseline[0]} to {baseline[1]} s must lie inside the epoch "
                                f"({tmin} to {tmax} s)")
    by = [c for c in (by.split(",") if isinstance(by, str) else list(by or [])) if c]
    missing = [c for c in by if c not in sess.cols and c != "marker"]
    if missing:
        raise AnalysisError(f"no column {missing[0]} in the trial table; columns: {', '.join(sess.cols)}")
    notes: list[str] = []

    # ---------------------------------------------------------------- the signal
    pupil_mode = stream.lower() in ("pupil", "pupils")
    if not pupil_mode:
        s = sess.find_stream(stream, kinds=("eeg",))
        pupil_mode = s["kind"].lower() == "gaze"
    if pupil_mode:
        from .gaze import gaze_samples
        g = gaze_samples(sess, "" if stream.lower() in ("pupil", "pupils") else stream)
        times, srate = g["time"], g["srate"]
        values, n_blinks, filled = interpolate_blinks(times, g["pupil"], blink_pad)
        data = {"pupil": values}
        units = {"pupil": "mm"}
        name = "pupil"
        notes.append(f"{n_blinks} blink(s) or short data losses filled by linear interpolation "
                     f"({blink_pad[0] * 1000:.0f} ms before to {blink_pad[1] * 1000:.0f} ms after each)")
    else:
        all_ch = [c for c in s["channels"] if c.lower() not in TRIGGER_CHANNELS]
        if channels:
            want = channels.split(",") if isinstance(channels, str) else list(channels)
            unknown = [c for c in want if c not in s["channels"]]
            if unknown:
                raise AnalysisError(f"stream {s['name']} has no channel {unknown[0]}; channels: {', '.join(all_ch)}")
        else:
            want = all_ch
        times, data = sess.load(s, want)
        srate = s["srate"] or (1.0 / statistics.median([b - a for a, b in zip(times, times[1:]) if b > a])
                               if len(times) > 1 else 0.0)
        units = {c: (s["units"][s["channels"].index(c)] if len(s["units"]) == len(s["channels"]) else "")
                 for c in want}
        name = s["device"] if s["device"] == s["stream"] else s["name"]
        filled = None
    if not times or not srate:
        raise AnalysisError(f"the {name} recording of {sess.root.name} has no samples")
    chans = list(data)
    if reject == "auto":
        reject = EEG_REJECT_UV if chans and all(units.get(c, "").lower() in ("uv", "µv", "microvolts")
                                                 for c in chans) else None
    reject = None if reject in (None, "", "none", 0) else float(reject)

    # ---------------------------------------------------------------- the epochs
    evs = sess.markers(markers)
    if not evs:
        labels = sess.marker_labels()
        raise AnalysisError(f"no marker matches {', '.join(markers)} in {sess.root.name}"
                            + (f"; its markers: {', '.join(f'{k} ({v}x)' for k, v in labels.items())}" if labels
                               else ""))
    grid = _grid(tmin, tmax, srate)
    cond_cols = [c for c in sess.cols if c in sess.st.condition_cols]
    info_rows, data_eps = [], []
    for k, e in enumerate(evs, 1):
        t0 = float(e["time"])
        w = sess.window_at(t0)
        trow = w["trial_row"] if w else {}
        if by:
            cond = "/".join(str(e.get("label")) if c == "marker" else str(trow.get(c, "")) for c in by)
        else:
            cond = str(e.get("label"))
        ep = []
        reason = ""
        interp = 0.0
        for c in chans:
            seg = baseline_correct(cut(times, data[c], t0, grid, srate), grid, baseline)
            ep.append(seg)
            miss = sum(1 for v in seg if isnan(v)) / len(seg)
            if miss > MAX_MISSING and not reason:
                reason = f"{miss:.0%} of {c} missing"
            vals = [v for v in seg if not isnan(v)]
            if reject is not None and vals and not reason and max(vals) - min(vals) > reject:
                reason = f"peak-to-peak {max(vals) - min(vals):.1f} {units.get(c, '')} on {c}".replace("  ", " ")
        if filled is not None:
            fl = cut(times, [1.0 if f else 0.0 for f in filled], t0, grid, srate)
            interp = sum(1 for v in fl if not isnan(v) and v > 0) / len(fl)
        data_eps.append(ep)
        info_rows.append({"epoch": k, "trial": w["trial"] if w else None, "routine": w["routine"] if w else "",
                          "marker": e.get("label"), "code": e.get("code"), "event_time": t0, "condition": cond,
                          **{c: trow.get(c) for c in cond_cols},
                          "rejected": int(bool(reason)), "reason": reason,
                          **({"interpolated": interp} if filled is not None else {})})
    kept = [i for i, r in enumerate(info_rows) if not r["rejected"]]

    # ---------------------------------------------------------------- per condition
    conditions = list(dict.fromkeys(info_rows[i]["condition"] for i in range(len(info_rows))))
    erp_rows, erp_means = [], []
    for cond in conditions:
        idx = [i for i in kept if info_rows[i]["condition"] == cond]
        means_c = []
        for ci, c in enumerate(chans):
            mean_t = []
            for ti, g in enumerate(grid):
                vals = [data_eps[i][ci][ti] for i in idx if not isnan(data_eps[i][ci][ti])]
                m = statistics.fmean(vals) if vals else NAN
                sd = statistics.stdev(vals) if len(vals) > 1 else NAN
                mean_t.append(m)
                erp_rows.append({"condition": cond, "channel": c, "time": round(g, 6), "mean": m, "sd": sd,
                                 "se": sd / math.sqrt(len(vals)) if len(vals) > 1 else NAN, "n": len(vals),
                                 "units": units.get(c, "")})
            means_c.append(mean_t)
        erp_means.append(means_c)

    res: dict[str, Any] = {"session": sess.root.name, "stream": name, "channels": chans, "srate": srate,
                           "tmin": tmin, "tmax": tmax, "baseline": list(baseline) if baseline else None,
                           "reject": reject, "markers": markers, "by": by, "epochs": len(info_rows),
                           "kept": len(kept), "rejected": len(info_rows) - len(kept),
                           "conditions": {c: sum(1 for i in kept if info_rows[i]["condition"] == c)
                                          for c in conditions},
                           "times": grid, "erp": {c: dict(zip(chans, m)) for c, m in zip(conditions, erp_means)},
                           "epoch_rows": info_rows, "files": [], "notes": notes}
    if not kept:
        notes.append("every epoch was rejected: raise --reject, or check the recording (edge report)")
    if not write:
        return res
    d = sess.out_dir(out)
    stem = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    files = res["files"]
    files.append(str(write_npz(d / f"epochs_{stem}.npz", {
        "data": [[[v for v in seg] for seg in ep] for ep in data_eps] if data_eps else [],
        "times": grid, "channels": chans, "event_times": [r["event_time"] for r in info_rows],
        "markers": [str(r["marker"]) for r in info_rows], "conditions": [r["condition"] for r in info_rows],
        "trials": [int(r["trial"] or -1) for r in info_rows], "rejected": [bool(r["rejected"]) for r in info_rows],
        "srate": [float(srate)], "erp": erp_means, "erp_conditions": conditions})))
    long_rows = []
    for r, ep in zip(info_rows, data_eps):
        for c, seg in zip(chans, ep):
            for g, v in zip(grid, seg):
                long_rows.append({"epoch": r["epoch"], "trial": r["trial"], "condition": r["condition"],
                                  "marker": r["marker"], "rejected": r["rejected"], "channel": c,
                                  "time": round(g, 6), "value": v})
    files.append(str(write_csv(d / f"epochs_{stem}.csv", ["epoch", "trial", "condition", "marker", "rejected",
                                                           "channel", "time", "value"], long_rows)))
    files.append(str(write_csv(d / f"epochs_{stem}_info.csv", list(info_rows[0]), info_rows)))
    files.append(str(write_csv(d / f"erp_{stem}.csv", ["condition", "channel", "time", "mean", "sd", "se", "n",
                                                        "units"], erp_rows)))
    if plot:
        if plot_available():
            files.append(str(_plot(d / f"erp_{stem}.png", grid, chans, conditions, erp_means, units, name,
                                   res["conditions"])))
        else:
            notes.append(PLOT_NOTE)
    return res


def _plot(path: Path, grid, chans, conditions, means, units, name, counts) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(chans)
    cols = min(3, n)
    rows = -(-n // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 2.8 * rows), squeeze=False, sharex=True)
    palette = ["#2a6fdb", "#e0533d", "#2a9d6f", "#8a5cd1", "#d18a1f", "#4a4a4a"]
    ms = [g * 1000 for g in grid]
    for ci, c in enumerate(chans):
        ax = axes[ci // cols][ci % cols]
        for k, cond in enumerate(conditions):
            ax.plot(ms, means[k][ci], color=palette[k % len(palette)], lw=1.4,
                    label=f"{cond} (n={counts.get(cond, 0)})")
        ax.axvline(0, color="#999", lw=0.8)
        ax.axhline(0, color="#ccc", lw=0.8)
        ax.set_title(c, fontsize=10)
        ax.set_ylabel(units.get(c, ""), fontsize=8)
        ax.tick_params(labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    for k in range(n, rows * cols):
        axes[k // cols][k % cols].axis("off")
    for ax in axes[-1]:
        ax.set_xlabel("ms from marker", fontsize=8)
    axes[0][0].legend(fontsize=7, frameon=False)
    fig.suptitle(f"{name}: average per condition", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
