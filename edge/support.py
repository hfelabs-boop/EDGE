"""Support bundle: one zip with everything needed to understand a problem, without participant data.

``edge support-bundle study.yaml`` (or a session folder; also a button in the builder) collects:

* the experiment (and its lock, if any), validation results and the recording plan;
* the environment: EDGE, Python, OS, package versions, plugins, device drivers and whether they load;
* the computer check (``edge doctor``);
* for the session (or the experiment's most recent one): its settings and timing summary, the error
  report if it crashed, the session report, the event log and the first lines of the frame log;
* never the participant information (replaced by "<removed>"), and no trial data unless asked
  (``--include-data``; participant columns are removed from it).
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

REMOVED = "<removed>"


def _sanitize_session(meta: dict[str, Any]) -> dict[str, Any]:
    meta = json.loads(json.dumps(meta, default=str))
    fields = list((meta.get("participant") or {}).keys())
    meta["participant"] = {k: REMOVED for k in fields}
    crash = meta.get("crash") or {}
    if crash.get("variables"):
        crash["variables"] = {k: (REMOVED if k in fields else v) for k, v in crash["variables"].items()}
    return meta


def _latest_session(exp_path: Path) -> Path | None:
    from .export import find_sessions
    from .model import Experiment
    try:
        exp = Experiment.load(exp_path)
        root = (exp_path.parent / exp.settings["data"].get("dir", "data"))
        sessions = [Path(s) for s in find_sessions(root, True)]
    except Exception:
        return None
    sessions = [s for s in sessions if (s / "session.json").exists()]
    return max(sessions, key=lambda s: (s / "session.json").stat().st_mtime) if sessions else None


def make_bundle(path: str | Path, out: str | Path | None = None, include_data: bool = False) -> dict[str, Any]:
    from .reproduce import environment, lock_path
    from .storage import dumps, load_document
    p = Path(path)
    session: Path | None = None
    exp_doc: dict[str, Any] | None = None
    exp_path: Path | None = None
    if p.is_dir() and (p / "session.json").exists():
        session = p
        exp_file = p / "experiment.yaml"
        if exp_file.exists():
            exp_doc = load_document(exp_file).doc
    else:
        exp_path = p
        exp_doc = load_document(p).doc
        session = _latest_session(p)
    name = (exp_doc or {}).get("name", "edge")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(out) if out else (exp_path.parent if exp_path else p.parent) / f"support_{name}_{stamp}.zip"
    contents: list[str] = []
    secrets: list[str] = []
    if session is not None:
        try:
            meta0 = json.loads((session / "session.json").read_text(encoding="utf-8"))
            vals = [str(v) for v in (meta0.get("participant") or {}).values() if v not in (None, "")]
            secrets = [session.name] + [v for v in vals if len(v) >= 3 and not v.replace(".", "").isdigit()]
        except (OSError, ValueError):
            secrets = [session.name]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def put(arc: str, data: str | bytes) -> None:
            if secrets:      # the session folder is named after the participant; never let it out
                text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
                for sec in sorted(secrets, key=len, reverse=True):
                    text = text.replace(sec, "<session>" if sec == session.name else REMOVED)
                data = text
            z.writestr(arc, data)
            contents.append(arc)

        env = environment()
        put("environment.json", json.dumps(env, indent=2))
        try:
            from .devices import device_registry
            put("drivers.json", json.dumps({k: {"available": c.available()[0], "why": c.available()[1]}
                                             for k, c in device_registry().items()}, indent=2))
        except Exception:
            pass
        exp = None
        if exp_doc is not None:
            put("experiment.yaml", dumps(exp_doc))
            try:
                from .measures import recording_plan
                from .model import Experiment
                exp = Experiment.from_dict(exp_doc, base_dir=exp_path.parent if exp_path else p)
                put("validation.txt", "\n".join(str(i) for i in exp.validate()) or "no issues")
                plan = recording_plan(exp)
                put("recording_plan.json", json.dumps({k: plan[k] for k in ("participant", "loops", "devices", "always")},
                                                      indent=2, default=str))
            except Exception as e:
                put("validation.txt", f"could not validate: {type(e).__name__}: {e}")
        if exp_path is not None and lock_path(exp_path).exists():
            put("experiment.lock.json", lock_path(exp_path).read_bytes())
            try:
                from .reproduce import verify
                put("verify.json", json.dumps(verify(exp_path, golden=False), indent=2))
            except Exception:
                pass
        try:
            from .syscheck import format_checks, run_checks
            put("computer_check.txt", format_checks(run_checks(exp)))
        except Exception:
            pass
        if session is not None:
            meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
            clean = _sanitize_session(meta)
            put("session/session.json", json.dumps(clean, indent=2))
            if clean.get("crash"):
                from .diagnostics import format_report
                put("session/error.txt", format_report(clean["crash"]))
            try:
                from .report import analyze_session, format_report as fmt
                put("session/report.txt", fmt(analyze_session(session)))
            except Exception as e:
                put("session/report.txt", f"report failed: {type(e).__name__}: {e}")
            for fname, limit in (("events.jsonl", None), ("frames.csv", 3000)):
                f = session / fname
                if f.exists():
                    text = f.read_text(encoding="utf-8", errors="replace")
                    if limit:
                        text = "\n".join(text.splitlines()[:limit])
                    if fname == "events.jsonl":
                        text = _scrub_events(text, set((meta.get("participant") or {}).keys()))
                    put(f"session/{fname}", text)
            if include_data and (session / "trials_wide.csv").exists():
                fields = set((meta.get("participant") or {}).keys())
                with (session / "trials_wide.csv").open(encoding="utf-8-sig") as fh:
                    rows = list(csv.DictReader(fh))
                if rows:
                    cols = [c for c in rows[0] if c not in fields]
                    buf = io.StringIO()
                    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(rows)
                    put("session/trials_wide.csv", buf.getvalue())
        put("README.txt", f"EDGE support bundle made {stamp}\n\n" + "\n".join(f"  {c}" for c in contents) +
            "\n\nParticipant information has been replaced by <removed>. "
            + ("Trial data is included without participant columns." if include_data else "No trial data is included."))
    return {"bundle": str(out), "contents": contents, "session": str(session) if session else None}


def _scrub_events(text: str, fields: set[str]) -> str:
    out = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev.get("fields"), dict):
            ev["fields"] = {k: (REMOVED if k in fields else v) for k, v in ev["fields"].items()}
        out.append(json.dumps(ev))
    return "\n".join(out)
