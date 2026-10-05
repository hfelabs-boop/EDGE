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
                           "aborted": meta.get("aborted"), "errors": meta.get("errors", []), "streams": {},
                           "warnings": meta.get("warnings", []), "display": meta.get("display") or {},
                           "computer": [c for c in meta.get("system_checks") or [] if c.get("level") in ("warning", "error")]}
    flip_events = [e for e in events if e.get("on_flip")]
    for f in sorted((root / "streams").glob("*.csv")):
        if f.name.endswith(".raw.csv"):
            continue
        rep["streams"][f.stem] = _analyze_stream(f, meta, events)
    rep["markers"] = {"total": len(events), "time_locked_to_flip": len(flip_events)}
    rep["measures"] = _measures(root)
    rep["display_latency"] = _light_sensor(root, flip_events)
    rep["audio_latency"] = _sound_sensor(root, events)
    rep["verdict"] = _verdict(rep)
    return rep


def _sound_sensor(root: Path, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A microphone at the speaker (an input named 'sound', or listed in a device's audio_inputs) against the
    markers of sound components: how long after its onset a sound is really heard."""
    import yaml
    try:
        exp = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        exp = {}
    sound_ids = {c.get("id") for r in (exp.get("routines") or {}).values() for c in (r or {}).get("components", []) or []
                 if c.get("type") == "sound"}
    names_by_dev: dict[str, set[str]] = {}
    for d in exp.get("devices") or []:
        o = {**(d.get("options") or {}), **{k: v for k, v in d.items() if k not in ("id", "type", "options")}}
        names_by_dev[str(d.get("id", d.get("type")))] = {str(x) for x in (o.get("audio_inputs") or ["sound"])}
    onsets = []
    for f in sorted((root / "streams").glob("*.inputs.csv")):
        names = names_by_dev.get(f.name.split(".")[0], {"sound"})
        with f.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("input") in names and r.get("down") == "1":
                    onsets.append(float(r["time"]))
    refs = sorted(float(e["time"]) for e in events if str(e.get("source", "")).split(".")[-1] in sound_ids)
    if not onsets or not refs:
        return None
    lat = []
    for t in onsets:
        prev = [x for x in refs if x <= t + 0.001]
        if prev and t - prev[-1] < 0.5:
            lat.append(t - prev[-1])
    if not lat:
        return {"sound_onsets": len(onsets), "matched": 0}
    return {"sound_onsets": len(onsets), "matched": len(lat), "mean_ms": round(statistics.fmean(lat) * 1e3, 2),
            "sd_ms": round(statistics.pstdev(lat) * 1e3, 2), "min_ms": round(min(lat) * 1e3, 2), "max_ms": round(max(lat) * 1e3, 2)}


def _light_sensor(root: Path, flip_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A light sensor on the screen (an input named in the device's light_inputs) against the flips: how long
    after EDGE's flip time the screen really changed (display latency) and how much that varies."""
    import yaml
    try:
        exp = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        exp = {}
    light: dict[str, set[str]] = {}
    for d in exp.get("devices") or []:
        o = {**(d.get("options") or {}), **{k: v for k, v in d.items() if k not in ("id", "type", "options")}}
        light[str(d.get("id", d.get("type")))] = {str(x) for x in (o.get("light_inputs") or ["light"])}
    onsets: list[float] = []
    for f in sorted((root / "streams").glob("*.inputs.csv")):
        names = light.get(f.name.split(".")[0], {"light"})
        with f.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("input") in names and r.get("down") == "1":
                    onsets.append(float(r["time"]))
    if not onsets or not flip_events:
        return None
    flips = sorted(float(e["time"]) for e in flip_events)
    lat = []
    for t in onsets:
        prev = [f for f in flips if f <= t + 0.001]
        if prev and t - prev[-1] < 0.15:
            lat.append(t - prev[-1])
    if not lat:
        return {"light_onsets": len(onsets), "matched": 0}
    return {"light_onsets": len(onsets), "matched": len(lat), "flips": len(flips),
            "mean_ms": round(statistics.fmean(lat) * 1e3, 2), "sd_ms": round(statistics.pstdev(lat) * 1e3, 2),
            "min_ms": round(min(lat) * 1e3, 2), "max_ms": round(max(lat) * 1e3, 2)}


def _measures(root: Path) -> dict[str, Any] | None:
    """The experiment's declared measures: their values in this session and anything wrong with them."""
    from .export import SessionTables, measures_table, wide_trials
    from .measures import declared, measure_checks
    try:
        st = SessionTables(root)
        if not declared(st.experiment):
            return None
        _, rows = wide_trials(st, drop_empty=False)
        _, table = measures_table(st, rows)
    except Exception as e:  # the report must still work on odd or partial sessions
        return {"error": f"{type(e).__name__}: {e}", "values": [], "checks": []}
    overall = [{k: r[k] for k in ("measure", "label", "role", "summary", "value", "n", "missing", "units")}
               for r in table if all(v == "(all)" for k, v in r.items() if k not in
                                     ("participant", "session", "measure", "label", "role", "column", "summary",
                                      "n", "missing", "value", "units"))]
    return {"values": overall, "checks": measure_checks(st.experiment, rows)}


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
    dl = rep.get("display_latency")
    if dl and dl.get("matched") == 0:
        notes.append(f"WARNING: the light sensor saw {dl['light_onsets']} changes but none within 150 ms of a screen flip")
    elif dl and dl.get("sd_ms", 0) > 4:
        notes.append(f"WARNING: display latency varies by {dl['sd_ms']} ms (light sensor); stimulus onsets are less precise than the flip times")
    al = rep.get("audio_latency")
    if al and al.get("sd_ms", 0) > 5:
        notes.append(f"WARNING: audio latency varies by {al['sd_ms']} ms (microphone); sound onsets are not precise")
    for c in (rep.get("measures") or {}).get("checks", []):
        notes.append(f"WARNING: {c['message']}")
    for w in rep.get("warnings") or []:
        notes.append(f"WARNING: {w}")
    for c in rep.get("computer") or []:
        notes.append(f"COMPUTER: {c['title']}" + (f" → {c['fix']}" if c.get("fix") else ""))
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
    d = rep.get("display") or {}
    if d.get("renderer") or d.get("audio_driver"):
        lines += ["Computer", f"  display {d.get('renderer', '?')}, measured {d.get('refresh_rate_measured', '?')} Hz "
                  f"(frame jitter {d.get('frame_jitter_ms', '?')} ms), sound {d.get('audio_driver', '?')}", ""]
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
    al = rep.get("audio_latency")
    if al and al.get("matched"):
        lines += ["Audio latency (microphone)",
                  f"  {al['mean_ms']} ± {al['sd_ms']} ms after the sound's onset (range {al['min_ms']}–{al['max_ms']}), "
                  f"{al['matched']} of {al['sound_onsets']} sounds matched", ""]
    dl = rep.get("display_latency")
    if dl and dl.get("matched"):
        lines += ["Display latency (light sensor)",
                  f"  {dl['mean_ms']} ± {dl['sd_ms']} ms after the flip (range {dl['min_ms']}–{dl['max_ms']}), "
                  f"{dl['matched']} of {dl['light_onsets']} light changes matched", ""]
    ms = rep.get("measures")
    if ms and ms.get("values"):
        lines.append("Measures")
        for v in ms["values"]:
            val = v["value"]
            shown = f"{val:.4g}" if isinstance(val, float) else ("—" if val is None else str(val))
            lines.append(f"  {v['label']}: {shown}{(' ' + v['units']) if v.get('units') and val is not None else ''}"
                         f" ({v['summary']}, {v['role']}, n={v['n']}" + (f", {v['missing']} missing" if v["missing"] else "") + ")")
        lines.append("")
    lines += ["Verdict"] + [f"  {v}" for v in rep["verdict"]]
    return "\n".join(lines)
