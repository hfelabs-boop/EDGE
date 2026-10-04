"""Post-session quality report: timing, data integrity and synchronization.

``edge report <session_dir>`` answers the questions reviewers ask:
were frames dropped, did every device record at its nominal rate without gaps,
how well were device clocks aligned, and did every marker actually arrive in
each device's trigger channel at the right time?
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

TRIGGER_COLUMNS = ("TRIG", "trigger", "event", "user", "USER", "marker", "code", "Trigger")


def analyze_session(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    meta = json.loads((root / "session.json").read_text())
    events = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines() if l.strip()]
    rep: dict[str, Any] = {"session": root.name, "experiment": meta.get("experiment"), "timing": meta.get("timing"),
                           "aborted": meta.get("aborted"), "errors": meta.get("errors", []), "streams": {}}
    flip_events = [e for e in events if e.get("on_flip")]
    for f in sorted((root / "streams").glob("*.csv")):
        if f.name.endswith(".raw.csv"):
            continue
        rep["streams"][f.stem] = _analyze_stream(f, meta, events)
    rep["markers"] = {"total": len(events), "time_locked_to_flip": len(flip_events)}
    rep["verdict"] = _verdict(rep)
    return rep


def _analyze_stream(path: Path, meta: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    device, stream = path.stem.split(".", 1)
    dmeta = meta.get("devices", {}).get(device, {})
    nominal = dmeta.get("streams", {}).get(stream, {}).get("srate") or 0
    times: list[float] = []
    trig: list[tuple[float, str]] = []
    with path.open(newline="") as f:
        r = csv.reader(f)
        header = next(r)
        tcol = next((header.index(c) for c in TRIGGER_COLUMNS if c in header), None)
        for row in r:
            t = float(row[0])
            times.append(t)
            if tcol is not None and row[tcol] not in ("", "0", "0.0", "None"):
                trig.append((t, row[tcol]))
    out: dict[str, Any] = {"samples": len(times), "nominal_srate": nominal,
                           "clock_model": dmeta.get("clock_model")}
    if len(times) > 2:
        dur = times[-1] - times[0]
        out["duration_s"] = round(dur, 3)
        out["effective_srate"] = round((len(times) - 1) / dur, 3) if dur > 0 else None
        if nominal:
            iv = [b - a for a, b in zip(times, times[1:])]
            gaps = [x for x in iv if x > 2.5 / nominal]
            out["gaps"] = len(gaps)
            out["longest_gap_ms"] = round(max(gaps) * 1e3, 2) if gaps else 0.0
    if trig:
        # match each device trigger to the closest EDGE marker with the same code/label
        res = []
        t_first, t_last = (times[0], times[-1]) if times else (0.0, 0.0)
        # a trigger lands on the first sample at/after the event, so events after the last sample can't appear
        period = 1.0 / nominal if nominal else 0.0
        delivered = [e for e in events if device in e.get("delivered", {})
                     and t_first - period <= e["time"] <= t_last - period]
        for t, val in trig:
            cands = [e for e in delivered if str(e.get("code")) == str(val) or e.get("label") == val]
            if not cands:
                continue
            best = min(cands, key=lambda e: abs(e["time"] - t))
            if abs(best["time"] - t) < 0.5:
                res.append(t - best["time"])
        expected = len(delivered)
        out["sample_period_ms"] = round(1e3 / nominal, 3) if nominal else None
        out["triggers"] = {
            "found": len(trig), "expected": expected, "matched": len(res),
            "latency_mean_ms": round(statistics.fmean(res) * 1e3, 3) if res else None,
            "latency_sd_ms": round(statistics.pstdev(res) * 1e3, 3) if len(res) > 1 else None,
            "latency_max_abs_ms": round(max(abs(x) for x in res) * 1e3, 3) if res else None,
        }
    return out


def _verdict(rep: dict[str, Any]) -> list[str]:
    notes = []
    t = rep.get("timing") or {}
    if t.get("dropped_pct", 0) > 1:
        notes.append(f"WARNING: {t['dropped_pct']:.1f}% dropped frames")
    for name, s in rep["streams"].items():
        if s.get("gaps"):
            notes.append(f"WARNING: {name} has {s['gaps']} gaps (longest {s['longest_gap_ms']} ms)")
        tr = s.get("triggers")
        if tr and tr["matched"] < tr["expected"]:
            notes.append(f"WARNING: {name}: {tr['expected'] - tr['matched']} markers missing from the trigger channel")
        # a trigger can only land on the next sample, so allow one sample period on top of 5 ms
        allowed = 5.0 + (s.get("sample_period_ms") or 0.0)
        if tr and tr.get("latency_max_abs_ms") is not None and tr["latency_max_abs_ms"] > allowed:
            notes.append(f"WARNING: {name}: marker alignment error up to {tr['latency_max_abs_ms']} ms")
    if rep.get("errors"):
        notes.append(f"{len(rep['errors'])} runtime error(s) logged")
    return notes or ["OK: no timing, data or synchronization problems detected"]


def format_report(rep: dict[str, Any]) -> str:
    lines = [f"EDGE session report: {rep['session']}  ({rep['experiment']})", ""]
    t = rep.get("timing") or {}
    if t.get("mean_interval_ms"):
        lines += ["Display timing",
                  f"  frames {t['frames']}, refresh {t['refresh_rate_hz']} Hz, "
                  f"interval {t['mean_interval_ms']:.3f} ± {t['sd_interval_ms']:.3f} ms (max {t['max_interval_ms']:.2f}), "
                  f"dropped {t['dropped_frames']} ({t['dropped_pct']:.2f}%)", ""]
    lines.append("Streams")
    for name, s in rep["streams"].items():
        cm = s.get("clock_model") or {}
        line = f"  {name}: {s['samples']} samples"
        if s.get("effective_srate"):
            line += f", {s['effective_srate']} Hz (nominal {s['nominal_srate']})"
        if "gaps" in s:
            line += f", gaps {s['gaps']}"
        if cm and cm.get("method") != "identity":
            sd = cm.get("residual_sd_ms")
            line += f", clock {cm['method']} drift {(cm['slope'] - 1) * 1e6:+.1f} ppm" + (f" (residual {sd:.3f} ms)" if sd else "")
        lines.append(line)
        tr = s.get("triggers")
        if tr:
            lines.append(f"      triggers {tr['matched']}/{tr['expected']} matched; alignment "
                         f"{tr['latency_mean_ms']} ± {tr['latency_sd_ms']} ms (max |err| {tr['latency_max_abs_ms']} ms)")
    lines += ["", f"Markers: {rep['markers']['total']} ({rep['markers']['time_locked_to_flip']} time-locked to screen flips)", ""]
    lines += ["Verdict"] + [f"  {v}" for v in rep["verdict"]]
    return "\n".join(lines)
