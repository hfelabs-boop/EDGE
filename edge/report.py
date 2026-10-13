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
SIMULATORS = ("sim_eyetracker", "sim_eeg", "sim_physio", "sim_inputs", "ttl_loopback")


def analyze_session(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    if not (root / "session.json").exists() and not (root / "events.jsonl").exists():
        raise FileNotFoundError(2, "not an EDGE session folder (it has no session.json); give one of the folders "
                                   "inside data/", str(root))
    meta, incomplete = _read_meta(root)
    events = _jsonl(root / "events.jsonl")
    rep: dict[str, Any] = {"session": root.name, "experiment": meta.get("experiment"), "timing": meta.get("timing"),
                           "aborted": meta.get("aborted"), "errors": meta.get("errors", []), "streams": {},
                           "warnings": meta.get("warnings", []), "display": meta.get("display") or {},
                           "computer": [c for c in meta.get("system_checks") or [] if c.get("level") in ("warning", "error")],
                           "incomplete": incomplete, "stop_reason": _stop_reason(meta),
                           "crash": (meta.get("crash") or {}).get("what"),
                           "dry_run": bool(meta.get("dry_run")), "simulated_devices": _simulated(meta),
                           "trials": _trials_done(root), "trials_planned": _trials_planned(root, meta),
                           "loops": {k: v for k, v in (meta.get("loops") or {}).items()
                                     if isinstance(v, dict) and v.get("type") == "staircase"}}
    flip_events = [e for e in events if e.get("on_flip")]
    for f in sorted((root / "streams").glob("*.csv")):
        if f.name.endswith(".raw.csv"):
            continue
        rep["streams"][f.stem] = _analyze_stream(f, meta, events)
    rep["markers"] = {"total": len(events), "time_locked_to_flip": len(flip_events),
                      "sent_after_event_ms": _sent_after_event(events)}
    rep["measures"] = _measures(root) if not incomplete else None
    rep["display_latency"] = _light_sensor(root, flip_events)
    rep["audio_latency"] = _sound_sensor(root, events)
    rep["verdict"] = _verdict(rep)
    return rep


def _jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue        # a line cut off when EDGE was stopped
    return out


def _read_meta(root: Path) -> tuple[dict[str, Any], str | None]:
    """session.json, or, for a session EDGE could not finish (power cut, killed), what can be pieced together.
    The second value says what is wrong with session.json: None, 'missing' or 'damaged'."""
    try:
        meta = json.loads((root / "session.json").read_text(encoding="utf-8"))
        if isinstance(meta, dict):
            return meta, None
        problem = "damaged"
    except FileNotFoundError:
        problem = "missing"
    except (ValueError, UnicodeDecodeError):
        problem = "damaged"
    import yaml
    try:
        exp = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        exp = {}
    name = exp.get("name") if isinstance(exp, dict) else None
    return {"experiment": name or root.name, "aborted": True, "errors": [], "loops": {}}, problem


def _stop_reason(meta: dict[str, Any]) -> str | None:
    if meta.get("stop_reason"):
        return str(meta["stop_reason"])
    if any(str(e).startswith("KeyboardInterrupt") for e in meta.get("errors") or []):
        return "Ctrl+C was pressed"            # sessions saved by older EDGE versions
    return None


def _simulated(meta: dict[str, Any]) -> list[str]:
    sim = meta.get("simulated_devices")
    stood_in = set(sim) if isinstance(sim, dict) else set()      # --simulate-devices / test runs
    declared = {d for d, info in (meta.get("devices") or {}).items()  # simulators named in the experiment itself
                if isinstance(info, dict) and info.get("type") in SIMULATORS}
    return sorted(stood_in | declared)


def _trials_done(root: Path) -> int | None:
    """Trials = loop iterations (one row of trials_wide), the same count as preflight, lock and export."""
    try:
        from .export import SessionTables, wide_trials
        return sum(1 for r in wide_trials(SessionTables(root))[1] if r.get("loop"))
    except Exception:
        rows = _jsonl(root / "trials.jsonl")
        keys = {r.get("trial_key") for r in rows if r.get("loop")}
        return len(keys) if rows else None


def _trials_planned(root: Path, meta: dict[str, Any]) -> int | None:
    """The planned number of trials when the flow makes it certain: only top-level trial lists, all started."""
    import yaml
    try:
        exp = yaml.safe_load((root / "experiment.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    flow = exp.get("flow") if isinstance(exp, dict) else None
    if not isinstance(flow, list):
        return None
    loops = meta.get("loops") or {}
    total = 0
    for node in flow:
        if isinstance(node, str) or (isinstance(node, dict) and "routine" in node):
            continue
        if not isinstance(node, dict) or "loop" not in node:
            return None                          # branches / workflows: how many run depends on the session
        if node.get("staircase") or any(isinstance(c, dict) and "routine" not in c
                                        for c in node.get("children") or []):
            return None                          # nested loops, branches inside: not certain
        info = loops.get(str(node["loop"]))
        if not isinstance(info, dict) or info.get("type") != "trials" or not isinstance(info.get("n_trials"), int):
            return None
        total += info["n_trials"]
    return total or None


def _sent_after_event(events: list[dict[str, Any]]) -> dict[str, float]:
    """Markers of input events (a key press, a click …): how long after the event itself they could be sent.
    Inputs are read once per screen refresh, so a response trigger leaves up to one frame after the press."""
    out: dict[str, float] = {}
    for e in events:
        if e.get("on_flip") or not e.get("delivered"):
            continue
        lag = max(float(t) for t in e["delivered"].values()) - float(e["time"])
        if lag > 0.002:
            lab = str(e.get("label"))
            out[lab] = round(max(out.get(lab, 0.0), lag * 1e3), 2)
    return out


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
            try:
                t = float(row[0])
            except (ValueError, IndexError):
                continue        # a line cut off when EDGE was stopped
            times.append(t)
            if tcol is not None and tcol < len(row) and row[tcol] not in ("", "0", "0.0", "None"):
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
        by_label: dict[str, float] = {}
        prev_t: float | None = None
        for t, val in trig:
            busy_until, prev_t = prev_t, t
            cands = [e for e in delivered if str(e.get("code")) == str(val) or e.get("label") == val]
            if not cands:
                continue
            best = min(cands, key=lambda e: abs(_marker_error(e, t, device)))
            err = _marker_error(best, t, device)
            if err > 0 and busy_until is not None and period and t - busy_until <= 1.5 * period:
                # a trigger channel carries one code per sample: a marker sent together with the one before it
                # (e.g. a gaze event on a stimulus onset) lands on the next sample; count from when it was free
                err = min(err, t - busy_until)
            if abs(err) < 0.5:
                res.append(err)
                lab = str(best.get("label"))
                by_label[lab] = max(by_label.get(lab, 0.0), abs(err) * 1e3)
        expected = len(delivered)
        out["sample_period_ms"] = round(1e3 / nominal, 3) if nominal else None
        out["triggers"] = {
            "found": len(trig), "expected": expected, "matched": len(res),
            "latency_mean_ms": round(statistics.fmean(res) * 1e3, 3) if res else None,
            "latency_sd_ms": round(statistics.pstdev(res) * 1e3, 3) if len(res) > 1 else None,
            "latency_max_abs_ms": round(max(abs(x) for x in res) * 1e3, 3) if res else None,
            "max_abs_ms_by_label": {k: round(v, 3) for k, v in sorted(by_label.items(), key=lambda kv: -kv[1])},
        }
    return out


def _marker_error(e: dict[str, Any], t: float, device: str) -> float:
    """How far a trigger seen at ``t`` is from where its marker belongs (s). A flip-locked marker belongs at its
    flip; a marker of an input event (key press, click) can only leave once EDGE has read the input, so it
    belongs anywhere between the event and the moment it was sent to this device."""
    t0 = float(e["time"])
    if e.get("on_flip"):
        return t - t0
    t1 = float((e.get("delivered") or {}).get(device, t0))
    lo, hi = min(t0, t1), max(t0, t1)
    return 0.0 if lo <= t <= hi else (t - lo if t < lo else t - hi)


def _verdict(rep: dict[str, Any]) -> list[str]:
    notes = []
    if rep.get("incomplete") == "damaged":
        notes.append("INCOMPLETE: session.json is damaged (cut off or edited), so the session's settings, timing "
                     f"summary and device clock alignment can't be read. The {rep.get('trials') or 0} trial(s) are in "
                     "trials.jsonl")
    elif rep.get("incomplete"):
        notes.append("INCOMPLETE: EDGE was closed before it could finish this session (power cut, crash or killed), "
                     f"so session.json is missing. The {rep.get('trials') or 0} trial(s) recorded until then are in "
                     "trials.jsonl; the timing summary and device clock alignment were never written")
    elif rep.get("aborted"):
        n, planned = rep.get("trials"), rep.get("trials_planned")
        why = rep.get("stop_reason") or ("because of an error: " + rep["crash"] if rep.get("crash") else None)
        count = "" if n is None else f" after {n} of {planned} trials" if planned and n < planned else f" after {n} trials"
        notes.append(f"STOPPED EARLY{f' ({why})' if why else ''}{count}: the data up to then is saved"
                     + ("" if rep.get("dry_run") else " and is included in merged exports (aborted = True in the "
                                                       "sessions table)"))
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
            worst = [f"{k} {v:g} ms" for k, v in (tr.get("max_abs_ms_by_label") or {}).items() if v > allowed][:4]
            notes.append(f"WARNING: {name}: marker alignment error up to {tr['latency_max_abs_ms']} ms"
                         + (f" ({', '.join(worst)}); these markers reached the device's trigger channel later or earlier "
                            "than the moment they mark: check the device's trigger wiring and clock settings" if worst else ""))
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
    errors = [e for e in rep.get("errors") or [] if not str(e).startswith("KeyboardInterrupt")]
    for e in errors[:5]:
        notes.append(f"ERROR: {e}")
    if len(errors) > 5:
        notes.append(f"ERROR: … and {len(errors) - 5} more (all are listed under errors in session.json)")
    if not notes:
        return ["OK: no timing, data or synchronization problems detected"
                + ((" (test run: simulated participant" + (" and devices)" if rep.get("simulated_devices") else ")"))
                   if rep.get("dry_run") else "")]
    return notes


def _pm(mean: Any, sd: Any) -> str:
    return f"{mean}" + (f" ± {sd}" if sd is not None else "")


def format_report(rep: dict[str, Any]) -> str:
    lines = [f"EDGE session report: {rep['session']}  ({rep['experiment']})"]
    sim = rep.get("simulated_devices") or []
    if rep.get("dry_run"):
        lines.append("TEST RUN: a virtual participant" + (f" and simulated devices ({', '.join(sim)})" if sim else "")
                     + " on simulated time. The timing, latency and synchronization numbers come from the "
                       "simulation, not from this computer or real hardware.")
    elif sim:
        lines.append(f"SIMULATED DEVICES: {', '.join(sim)} were EDGE's simulators, not the real hardware: their "
                     "data is not real.")
    if rep.get("trials") or rep.get("aborted"):
        planned = rep.get("trials_planned")
        lines.append(f"Trials: {rep['trials']}" + (f" of {planned} planned" if planned and planned != rep["trials"] else ""))
    lines.append("")
    t = rep.get("timing") or {}
    if t.get("mean_interval_ms"):
        lines += ["Display timing" + (" (simulated)" if rep.get("dry_run") else ""),
                  f"  frames {t['frames']}, refresh {t['refresh_rate_hz']} Hz, "
                  f"interval {t['mean_interval_ms']:.3f} ± {t['sd_interval_ms']:.3f} ms (max {t['max_interval_ms']:.2f}), "
                  f"dropped {t['dropped_frames']} ({t['dropped_pct']:.2f}%)", ""]
    d = rep.get("display") or {}
    if d.get("renderer") or d.get("audio_driver"):
        lines += ["Computer", f"  display {d.get('renderer', '?')}, measured {d.get('refresh_rate_measured', '?')} Hz "
                  f"(frame jitter {d.get('frame_jitter_ms', '?')} ms), sound {d.get('audio_driver', '?')}", ""]
    if not rep["streams"]:
        lines.append("Streams: none (this session recorded no devices)")
    else:
        lines.append("Streams" + (" (simulated devices)" if sim else ""))
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
            if tr.get("latency_mean_ms") is None:
                lines.append(f"      triggers {tr['matched']}/{tr['expected']} matched")
            else:
                lines.append(f"      triggers {tr['matched']}/{tr['expected']} matched; alignment "
                             f"{_pm(tr['latency_mean_ms'], tr['latency_sd_ms'])} ms (max |err| {tr['latency_max_abs_ms']} ms)")
    mk = rep["markers"]
    lines += ["", f"Markers: {mk['total']} ({mk['time_locked_to_flip']} time-locked to screen flips)"]
    late = mk.get("sent_after_event_ms") or {}
    if late:
        labels = ", ".join(f"{k} up to {v:g} ms" for k, v in sorted(late.items(), key=lambda kv: -kv[1])[:4])
        lines.append(f"  markers of responses ({labels}) were sent after the response itself, because inputs are read "
                     "once per screen refresh. Their times in events.jsonl and the reaction times are the response's own; "
                     "a TTL/LSL trigger for them can be up to one frame later.")
    lines.append("")
    for lid, lp in (rep.get("loops") or {}).items():
        thr = lp.get("threshold")
        lines += [f"Staircase {lid}: threshold {f'{thr:.4g}' if isinstance(thr, (int, float)) else '—'} "
                  f"(mean of the last reversals; {len(lp.get('reversals') or [])} reversals, {lp.get('trials')} trials). "
                  f"Also in session.json (variables.{lid}_threshold).", ""]
    what = " (simulated)" if rep.get("dry_run") else ""
    al = rep.get("audio_latency")
    if al and al.get("matched"):
        lines += [f"Audio latency (microphone){what}",
                  f"  {_pm(al['mean_ms'], al['sd_ms'])} ms after the sound's onset (range {al['min_ms']}–{al['max_ms']}), "
                  f"{al['matched']} of {al['sound_onsets']} sounds matched", ""]
    dl = rep.get("display_latency")
    if dl and dl.get("matched"):
        lines += [f"Display latency (light sensor){what}",
                  f"  {_pm(dl['mean_ms'], dl['sd_ms'])} ms after the flip (range {dl['min_ms']}–{dl['max_ms']}), "
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
