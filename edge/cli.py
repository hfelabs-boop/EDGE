"""Command line interface: ``edge <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class CLIError(Exception):
    """A mistake on the command line, said in words (``edge <command>: <message>``, exit code 2)."""


def _kv(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, eq, v = it.partition("=")
        if not eq or not k.strip():
            raise CLIError(f"-f {it}: use key=value, e.g. -f age=30")
        out[k.strip()] = v.strip()
    return out


def cmd_run(a: argparse.Namespace) -> int:
    from .engine import run_experiment
    from .model import Experiment

    exp = Experiment.load(a.experiment)
    issues = exp.validate()
    errors = [i for i in issues if i.level == "error"]
    for i in issues:
        if i.level != "info":
            print(i)
    if errors:
        print(f"\n{len(errors)} error(s): fix them before running (edge validate {shlex_quote(a.experiment)})")
        return 2
    if getattr(a, "fullscreen", None) is not None:
        exp.settings["window"]["fullscreen"] = a.fullscreen
    participant = _kv(a.field)
    if a.participant:
        participant["participant"] = a.participant
    if a.session:
        participant["session"] = a.session
    lock_state = None
    if not a.dry_run:          # a real session: the checks the builder's run dialog makes
        lock_state = _check_lock(a.experiment)
        if lock_state is None or not _check_participant(exp, participant, a.data_dir):
            print("Nothing was run.")
            return 2
    try:
        summary = run_experiment(exp, backend=a.backend, participant=participant, dry_run=a.dry_run,
                                 data_dir=a.data_dir, simulate_devices=a.simulate_devices or None)
    except Exception as e:
        rep = getattr(e, "report", None)
        if rep and rep.get("phase") != "setup":
            from .diagnostics import format_report
            print("\n" + format_report(rep))
            return 3
        cause = e.__cause__ or e
        print(f"\nEDGE could not run the experiment: {friendly_run_error(cause)}")
        print(f"(details: {type(cause).__name__}: {cause})")
        return 3
    if lock_state is not None and summary.get("data_dir"):
        _add_to_session(summary["data_dir"], "lock", lock_state)
    t = summary.get("timing", {})
    print(f"\nSaved to {summary.get('data_dir')}")
    if t.get("mean_interval_ms"):
        print(f"Frames: {t['frames']}, dropped {t['dropped_frames']} ({t['dropped_pct']:.2f}%)")
    if summary.get("errors"):
        print("Errors:\n  " + "\n  ".join(summary["errors"]))
    if a.report and summary.get("data_dir"):
        from .report import analyze_session, format_report
        print("\n" + format_report(analyze_session(summary["data_dir"])))
    return 1 if summary.get("aborted") else 0


def _interactive() -> bool:
    """Someone at a terminal who can answer (not the builder, the MCP server or a script)."""
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _go_ahead(question: str) -> bool:
    """Ask in the terminal (Enter means no). With nobody to ask, go ahead: the warning above is in the log."""
    if not _interactive():
        return True
    try:
        return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _check_lock(path: str) -> dict | None:
    """Before a real session: does the experiment still match its lock (edge lock)? The quick part of
    'edge verify' (no golden participant). Returns what to record with the session, or None to stop."""
    from .reproduce import verify
    try:
        r = verify(path, golden=False)
    except Exception as e:       # a damaged lock file
        r = {"locked": True, "findings": [{"level": "error", "what": "the lock file could not be read",
                                           "detail": f"{type(e).__name__}: {e}"}]}
    if not r.get("locked"):
        return {"locked": False}
    problems = [f for f in r["findings"] if f["level"] in ("warning", "error")]
    state = {"locked": True, "lock": r.get("lock"), "created": r.get("created"), "matches": not problems,
             "findings": problems}
    if problems:
        q = shlex_quote(path)
        print(f"This experiment was locked{' on ' + str(r['created']).replace('T', ' ') if r.get('created') else ''}, "
              "but since then:")
        for f in problems:
            print(f"  ! {f['what']}" + (f"\n      {f['detail']}" if f.get("detail") else ""))
        print(f"Check everything (with a test run of the golden participant):  edge verify {q}\n"
              f"If the change is intended, lock it again:  edge lock {q}")
        if not _go_ahead("Run the session anyway?"):
            return None
        state["run_anyway"] = True
    return state


def _check_participant(exp, participant: dict, data_dir: str | None) -> bool:
    """Say which participant id is used, and warn before a second session under the same participant and session
    numbers (EDGE keeps both, but they are easy to mix up in the analysis). False to stop."""
    from .export import find_sessions
    given = {**(exp.settings.get("participant") or {}), **participant}
    pid, ses = str(given.get("participant", "")), str(given.get("session", ""))
    root = Path(data_dir) if data_dir else exp.base_dir / exp.settings["data"]["dir"]
    used, same = [], []
    for s in find_sessions(root) if root.is_dir() else []:          # real sessions only, not test runs
        try:
            meta = json.loads((s / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        p = meta.get("participant") or {}
        if meta.get("experiment") != exp.name or not isinstance(p, dict) or meta.get("dry_run"):
            continue        # (earlier EDGE versions saved test runs next to the participants' data)
        used.append((str(p.get("participant", "")), str(p.get("session", ""))))
        if used[-1] == (pid, ses):
            same.append(s)
    nums = [int(u) for u, _ in used if u.isdigit()]
    width = max([len(u) for u, _ in used if u.isdigit()] + [3])
    free = str(max(nums) + 1 if nums else 1).zfill(width)
    if "participant" not in participant:
        print(f"Participant: {pid} (the default; give each participant their own id with -p"
              + (f", e.g. -p {free})" if free != pid else ")"))
    if not same:
        return True
    sessions = [int(x) for u, x in used if u == pid and x.isdigit()]
    shown = ", ".join(str(s) for s in same[:3]) + (f" and {len(same) - 3} more" if len(same) > 3 else "")
    print(f"Participant {pid}, session {ses} already has data from this experiment: {shown}")
    print(f"A new session is saved separately (nothing is overwritten), but the two are easy to mix up. "
          f"For this participant's next session use -s {max(sessions, default=1) + 1}; for a new participant "
          f"use -p {free} (the next free number).")
    return _go_ahead(f"Run participant {pid}, session {ses} again anyway?")


def _add_to_session(data_dir: str | Path, key: str, value) -> None:
    sj = Path(data_dir) / "session.json"
    try:
        meta = json.loads(sj.read_text(encoding="utf-8"))
        meta[key] = value
        tmp = sj.with_name("session.json.tmp")
        tmp.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        tmp.replace(sj)
    except (OSError, ValueError):
        pass


def friendly_run_error(e: Exception) -> str:
    text = f"{type(e).__name__}: {e}".lower()
    if "display" in text or "xlib" in text or "nosuchdisplay" in text:
        return ("no screen is available to open the experiment window on (for example over SSH or in a "
                "container). Run it on the computer with the monitor, or use 'edge run --dry-run' to test.")
    if "pyglet" in text and ("no module" in text or "import" in text):
        return "the window library is missing. Install it with:  pip install \"edge-experiments[display]\""
    if "connect" in text or "device" in text or "timeout" in text:
        return ("a device could not be reached. Check that it is switched on and connected, or start with "
                "simulated hardware (--simulate-devices / 'Simulated' in the builder).")
    return "see the details below. 'edge validate' and the FAQ explain most problems."


def cmd_validate(a: argparse.Namespace) -> int:
    from .model import Experiment

    exp = Experiment.load(a.experiment)
    issues = exp.validate()
    if a.json:
        print(json.dumps([i.to_dict() for i in issues], indent=2))
    else:
        for i in issues:
            print(i)
        n_err = sum(i.level == "error" for i in issues)
        print(f"{exp.name}: {n_err} error(s), {sum(i.level == 'warning' for i in issues)} warning(s)")
    return 1 if any(i.level == "error" for i in issues) else 0


def cmd_devices(a: argparse.Namespace) -> int:
    from .devices import device_registry

    reg = device_registry()
    if a.json:
        print(json.dumps({k: v.describe() for k, v in reg.items()}, indent=2, default=str))
        return 0
    for name, cls in sorted(reg.items()):
        ok, why = cls.available()
        flag = "ok " if ok else "-- "
        print(f"{flag}{name:16s} [{', '.join(sorted(cls.capabilities))}]  {cls.description}")
        if not ok:
            print(f"    {'':16s} unavailable: {why}")
    return 0


def cmd_components(a: argparse.Namespace) -> int:
    from .components import component_registry

    reg = component_registry()
    if a.json:
        print(json.dumps({k: v.describe() for k, v in reg.items()}, indent=2, default=str))
        return 0
    width = max((len(n) for n in reg), default=12)
    for name, cls in sorted(reg.items(), key=lambda kv: (kv[1].category, kv[0])):
        print(f"{cls.category:12s} {name:{width}s} {cls.description}")
    return 0


def cmd_scan(a: argparse.Namespace) -> int:
    from .scan import scan_all

    found = scan_all(timeout=a.timeout)
    if a.json:
        print(json.dumps(found, indent=2, default=str))
        return 0
    import yaml
    for section, items in found.items():
        print(f"{section.replace('_', ' ')}:")
        if not items:
            print("  (none)")
        for it in items:
            print("  - " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in it.items()
                                     if k != "suggested" and v not in (None, "", "n/a")))
            if it.get("suggested"):
                sug = dict(it["suggested"])
                ids = {"tobii": "eyetracker", "gazepoint": "eyetracker", "ttl_serial": "triggers", "lsl_inlet": "stream"}
                dev = {"id": ids.get(sug.get("type"), sug.get("type") or "device"), **sug}
                line = yaml.safe_dump(dev, default_flow_style=True, sort_keys=False, width=1000).strip()
                print(f"    in the experiment's devices:  {line}")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    from .syscheck import apply_fix, format_checks, run_checks
    exp = None
    if a.experiment:
        from .model import Experiment
        exp = Experiment.load(a.experiment)
    checks = run_checks(exp)
    if a.fix:
        for c in [c for c in checks if c.fixable and c.level in ("warning", "info", "error")]:
            try:
                print(f"fixed: {apply_fix(c.id)}")
            except Exception as e:
                print(f"could not fix {c.id}: {e}")
        checks = run_checks(exp)
    if a.json:
        print(json.dumps([c.to_dict() for c in checks], indent=2))
    else:
        print(format_checks(checks))
    return 1 if any(c.level == "error" for c in checks) else 0


def cmd_preflight(a: argparse.Namespace) -> int:
    from .preflight import format_preflight, run_preflight
    res = run_preflight(a.experiment, golden=not a.no_golden, computer=not a.no_computer)
    if a.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        print(format_preflight(res))
    return {"go": 0, "go with warnings": 1, "no-go": 2}[res["verdict"]]


def cmd_test_device(a: argparse.Namespace) -> int:
    from .devtest import test_experiment_device
    from .model import Experiment
    exp = Experiment.load(a.experiment)
    ids = [a.device] if a.device else [d.id for d in exp.devices]
    if not ids:
        print("This experiment has no devices.")
        return 0
    known = [d.id for d in exp.devices]
    if a.device and a.device not in known:
        import difflib
        close = difflib.get_close_matches(a.device, known, 1)
        raise CLIError(f"there is no device '{a.device}' in this experiment" + (f"; did you mean {close[0]}?" if close else "")
                       + f" (its devices: {', '.join(known)})")
    from .devices import device_registry
    reg = device_registry()
    bad = 0
    for did in ids:
        dtype = next(d.type for d in exp.devices if d.id == did)
        caps = getattr(reg.get(dtype), "capabilities", ()) or ()
        what = ("speak into the microphone now" if dtype == "voice_key" else "press the buttons now" if "input" in caps
                else "look at the screen now" if "gaze" in caps else "")
        print(f"{did}: testing for {a.seconds:g} s" + (f" ({what})" if what and a.seconds >= 3 else ""))
        r = test_experiment_device(exp, did, a.seconds, a.simulate)
        if not r["connected"]:
            bad += 1
            print(f"  ✗ not connected: {r.get('error')}" + (f"\n    {r['hint']}" if r.get("hint") else ""))
            continue
        for m in r["messages"]:
            print(f"  · {m}")
    return 1 if bad else 0


def cmd_timing_test(a: argparse.Namespace) -> int:
    from .templates import write_template
    path = write_template("timing_test", Path(a.directory))
    if path.stem != "timing_test":      # never over an existing file
        print("timing_test.yaml already exists there, so it was left as it is")
    print(f"Created {path}.")
    print("1. Tape a light sensor over the top-left corner of the screen and put a microphone at the speaker.")
    print("2. Replace the 'sensors' device with your hardware (serial_inputs, labjack, voice_key …), naming its")
    print("   inputs 'light' and 'sound' (and keep your trigger device).")
    q = shlex_quote(str(path))
    print(f"3. edge run {q} --report   → display latency, audio latency and trigger alignment.")
    print(f"   (Try it first without hardware: edge run {q} --dry-run --report)")
    return 0


def cmd_update(a: argparse.Namespace) -> int:
    from .updater import update
    res = update(check_only=a.check, stash=a.stash, branch=a.branch)   # says what happened, once
    return 0 if res.get("ok") else 1


def cmd_lock(a: argparse.Namespace) -> int:
    from .model import Experiment
    from .reproduce import lock
    errors = [i for i in Experiment.load(a.experiment).validate() if i.level == "error"]
    if errors:           # the golden participant can't go through an experiment with errors
        for i in errors:
            print(i)
        print(f"\n{len(errors)} error(s): fix them before locking (edge validate {shlex_quote(a.experiment)})")
        return 2
    r = lock(a.experiment, golden=not a.no_golden)
    print(f"Locked {r['experiment']}: {r['lock']} ({r['files']} file(s) fingerprinted"
          + (f", golden participant: {r['trials']} trials" if r.get("trials") is not None else "") + ")")
    print("From now on 'edge run' and the builder warn before a session if the experiment or its files change; "
          f"check it in full any time with:  edge verify {shlex_quote(a.experiment)}")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    from .reproduce import format_verify, verify
    r = verify(a.experiment, golden=not a.no_golden)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(format_verify(r))
    return 1 if any(f["level"] in ("warning", "error") for f in r["findings"]) else 0


def cmd_support(a: argparse.Namespace) -> int:
    from .support import make_bundle
    r = make_bundle(a.path, a.out, include_data=a.include_data)
    print(f"Support bundle: {r['bundle']}")
    print("It has the experiment, versions, computer check, devices, the last session's report and error "
          "(participant information removed" + ("" if a.include_data else ", no trial data") + ").")
    return 0


def _is_session(p: Path) -> bool:
    return p.is_dir() and ((p / "session.json").exists() or (p / "events.jsonl").exists())


def _started(p: Path) -> str:
    try:
        return str(json.loads((p / "session.json").read_text(encoding="utf-8")).get("started") or "")
    except (OSError, ValueError, AttributeError):
        from datetime import datetime
        return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")


def _sessions_for(path: str) -> list[Path]:
    """The session folders meant by a session folder, a data folder or an experiment file (its data folder)."""
    p = Path(path)
    if _is_session(p):
        return [p]
    if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".json"):
        from .model import Experiment
        try:
            exp = Experiment.load(p)
            name, data = exp.name, exp.base_dir / exp.settings["data"]["dir"]
        except Exception:
            name, data = None, p.parent / "data"
        found = _sessions_in(data)
        mine = [s for s in found if _experiment_of(s) == name]
        return mine or found
    if p.is_dir():
        return _sessions_in(p)
    if any(c in str(p) for c in "*?["):        # a pattern the shell found nothing for
        raise CLIError(f"no folder matches {p}: session folders are named participant_session_name_date, where name "
                       "is the experiment's name (its 'name:'), not its file name. Copy the folder 'edge run' printed "
                       "after 'Saved to', or give the data folder to see the newest session")
    raise FileNotFoundError(2, "no such session folder, data folder or experiment file", str(p))


def _sessions_in(folder: Path) -> list[Path]:
    from .export import find_sessions
    if not folder.is_dir():
        return []
    return find_sessions(folder) or find_sessions(folder, include_dry_runs=True)     # test runs if there is nothing else


def _experiment_of(p: Path) -> str | None:
    try:
        return json.loads((p / "session.json").read_text(encoding="utf-8")).get("experiment")
    except (OSError, ValueError, AttributeError):
        return None


def _one_session(paths: list[str], cmd: str) -> tuple[Path, str | None]:
    """The session to look at, and a note when it was chosen among several (the newest)."""
    found: list[Path] = []
    for p in paths:
        found += [s for s in _sessions_for(p) if s not in found]
    if not found:
        raise CLIError(f"no sessions in {', '.join(paths)} yet: give a session folder (they are inside data/; "
                       "'edge run' prints 'Saved to …' with its name)")
    if len(found) == 1:
        return found[0], None
    found.sort(key=lambda s: (_started(s), s.name))
    others = ", ".join(s.name for s in found[-4:-1][::-1]) + (" …" if len(found) > 4 else "")
    return found[-1], (f"{len(found)} sessions match; this is the newest, {found[-1]}. To see another, give its folder: "
                       f"edge {cmd} {shlex_quote(str(found[-1].parent))}/<folder>  (others: {others})")


def cmd_report(a: argparse.Namespace) -> int:
    from .report import analyze_session, format_report

    session, note = _one_session(a.session_dir, "report")
    rep = analyze_session(session)
    if note:
        print(note + "\n", file=sys.stderr if a.json else sys.stdout)
    print(json.dumps(rep, indent=2, default=str) if a.json else format_report(rep))
    return 0


def cmd_align(a: argparse.Namespace) -> int:
    from .align import AlignError, align

    if len(a.session_dir) > 1:      # e.g. a pattern that matched several folders: never guess which one
        raise CLIError(f"{len(a.session_dir)} session folders were given ({', '.join(Path(s).name for s in a.session_dir[:4])}"
                       f"{' …' if len(a.session_dir) > 4 else ''}): give the one the external recording belongs to")
    try:
        res = align(a.session_dir[0], a.external, tolerance=a.tolerance)
    except AlignError as e:
        print(f"edge align: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    m = res["model"]
    drift = (m["slope"] - 1) * 1e6
    print(f"Matched {res['matched']} of {res['external_events']} events in {Path(res['external_file']).name} "
          f"with the session's {res['edge_events']} markers.")
    print(f"External clock: offset {m['offset']:.4f} s" + (f", drift {drift:+.1f} ppm" if m.get("method") != "offset" else "")
          + (f", residual {m['residual_sd_ms']:.2f} ms" if m.get("residual_sd_ms") is not None else "") + ".")
    print(f"Saved to {Path(a.session_dir[0]) / 'alignment.json'}: convert external times with  {res['usage']}")
    return 0


def cmd_new(a: argparse.Namespace) -> int:
    from .templates import TEMPLATES, public_templates, write_template

    if a.template not in TEMPLATES:
        import difflib
        close = difflib.get_close_matches(a.template, list(public_templates()), 1)
        print(f"unknown template '{a.template}'" + (f"; did you mean {close[0]}?" if close else "")
              + f"\n  choose from: {', '.join(public_templates())}", file=sys.stderr)
        return 2
    path = write_template(a.template, Path(a.directory))
    if path.stem != TEMPLATES[a.template]["name"]:     # never over an existing experiment
        print(f"{TEMPLATES[a.template]['name']}.yaml already exists there, so it was left as it is")
    print(f"created {path}\n  try:  edge run {shlex_quote(str(path))} --dry-run")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from .export import export_many, export_session

    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    p = Path(a.path)
    if (p / "session.json").exists():
        files = export_session(p, formats, a.out, a.layout, name=a.name)
        print("\n".join(str(f) for f in files))
    else:
        res = export_many(p, formats, a.out, a.include_dry_runs, a.name, layout=a.layout)
        rows = res.get("rows", res["trials"])
        print(f"{res['sessions']} session(s), {res['participants']} participant(s), {res['trials']} trials"
              + ("" if rows == res["trials"] else
                 f" ({rows} rows in the trials table: {'one per screen' if a.layout == 'long' else 'screens outside the trial loops, such as instructions, have rows too'})"))
        for note in res.get("notes") or []:       # several experiments, unreadable folders, BIDS renames
            print(f"note: {note}")
        print("\n".join(res["files"]))
    return 0


def cmd_bundle(a: argparse.Namespace) -> int:
    from .storage import export_bundle

    res = export_bundle(a.experiment, a.out)
    print(f"wrote {res['bundle']} ({len(res['files'])} files)")
    if res["missing"]:
        print("missing (not included): " + ", ".join(res["missing"]))
    return 1 if res["missing"] else 0


def cmd_unbundle(a: argparse.Namespace) -> int:
    from .storage import import_bundle

    print(f"extracted {import_bundle(a.bundle, a.directory)}")
    return 0


def cmd_backups(a: argparse.Namespace) -> int:
    from .storage import list_backups, restore_backup

    if a.restore is not None:
        rid = restore_backup(a.experiment, a.restore or None)
        print(f"restored {rid}")
        return 0
    backups = list_backups(a.experiment)
    if not Path(a.experiment).is_file() and not backups:
        raise FileNotFoundError(2, "file not found", a.experiment)
    if not backups:
        print(f"No backups yet for {a.experiment} (EDGE keeps one each time it saves the file).")
        return 0
    if not Path(a.experiment).is_file():
        print(f"{a.experiment} itself is missing; bring back the newest version with:  "
              f"edge backups {shlex_quote(a.experiment)} --restore")
    for b in backups:
        print(f"{b['id']:40s} {b['time']}  {b['label']}")
    return 0


def cmd_import(a: argparse.Namespace) -> int:
    from .importers import ImportError_, import_experiment

    try:
        path, res = import_experiment(a.source, a.out, a.platform, a.name)
    except ImportError_ as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    n_unsup = sum(n["level"] == "unsupported" for n in res.notes)
    n_approx = sum(n["level"] == "approx" for n in res.notes)
    errors = [n for n in res.notes if n["level"] == "error"]
    print(f"imported {res.platform} experiment -> {path}")
    for n in res.notes:
        if n["where"] == "output":            # saved next to an earlier import, which was left untouched
            print(f"note: {n['message']}")
    print("converted: " + ", ".join(f"{v} {k}" for k, v in sorted(res.stats.items())))
    print(f"{n_approx} item(s) converted approximately, {n_unsup} not converted: see {path.parent / 'IMPORT_REPORT.md'}")
    if errors:
        print(f"it won't run until {len(errors)} problem(s) are fixed, first: {errors[0]['where']}: "
              f"{errors[0]['message']} (all are listed in the report)")
        print(f"next:  fix them, then  edge validate {shlex_quote(str(path))}")
        return 1
    print(f"next:  edge run {shlex_quote(str(path))} --dry-run --report")
    return 0


def cmd_help(a: argparse.Namespace) -> int:
    from . import help as hp

    words = " ".join(a.query).strip()
    if not words:
        print("EDGE help: pick a guide (edge help <name>) or search (edge help <words>)\n")
        group = None
        for t in hp.topics():
            if t["group"] != group:
                group = t["group"]
                print(f"{group}:")
            print(f"  {t['id']:24s} {t['title']}")
        print("\nInteractive tutorials: edge tutorial")
        return 0
    try:
        text = hp.read_topic(words)
        print(hp.to_terminal(text) if not a.raw else text)
        return 0
    except KeyError:
        pass
    results = hp.search(words, limit=a.limit)
    if not results:
        print(f"nothing found for '{words}'. Try other words, or 'edge help' for the list of guides.")
        return 1
    if a.first or len(results) == 1:
        r = results[0]
        if r["topic"] == "tutorial":
            print(hp.to_terminal(hp.tutorial_markdown(hp.tutorial(r["anchor"]))))
        else:
            print(hp.to_terminal(hp.section_text(r["topic"], r["anchor"])))
            print(f"(from: edge help {r['topic']})")
        return 0
    print(f"Results for '{words}':\n")
    for i, r in enumerate(results, 1):
        where = "tutorial" if r["topic"] == "tutorial" else r["topic"]
        print(f"{i}. {r['section']}  [{where}]\n   {r['snippet']}\n")
    print("Show the best match in full with:  edge help --first " + words)
    return 0


def cmd_tutorial(a: argparse.Namespace) -> int:
    from . import help as hp

    if not a.name or a.name == "list":
        print("Interactive tutorials (they run inside the builder):\n")
        for t in hp.tutorials():
            print(f"  {t['id']:22s} {t['title']}  ({t.get('level', '')}, {t.get('minutes', '?')} min)")
        print("\nStart one:  edge tutorial <name>      Read it:  edge tutorial <name> --print")
        return 0
    try:
        t = hp.tutorial(a.name)
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    if a.print:
        print(hp.to_terminal(hp.tutorial_markdown(t)))
        return 0
    folder = Path(a.directory or f"tutorial_{t['id']}")
    folder.mkdir(parents=True, exist_ok=True)
    print(f"Starting '{t['title']}' in {folder.resolve()}")
    print("The builder opens with the tutorial coach in the corner. Ctrl+C here to stop.")
    from .builder.server import serve
    serve(folder, port=a.port, open_browser=not a.no_browser, path_query=f"?tutorial={t['id']}")
    return 0


def cmd_docs(a: argparse.Namespace) -> int:
    from . import help as hp

    if a.action is None and not a.check:    # `edge docs` alone: most people want to read, not rebuild
        print("To read the documentation:  edge help        (or search it:  edge help <words>)\n"
              "'edge docs build' is for EDGE developers: it regenerates the reference pages from the code.")
        return 0
    stale = hp.build_docs(check=a.check)
    if a.check:
        if stale:
            print("out of date (run 'edge docs build'): " + ", ".join(stale))
            return 1
        print("generated documentation is up to date")
        return 0
    print("updated: " + (", ".join(stale) if stale else "nothing (already up to date)"))
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    try:
        from .mcp_server import main as mcp_main
    except ImportError as e:
        from importlib import metadata
        try:
            have = metadata.version("mcp")
        except metadata.PackageNotFoundError:
            have = None
        fix = f'"{sys.executable}" -m pip install "mcp>=1.2,<2"'
        if have is None:
            print(f"The MCP server needs the 'mcp' package, which is not installed. Install it with:\n  {fix}", file=sys.stderr)
        elif not have.startswith("1."):
            print(f"The MCP server needs version 1 of the 'mcp' package, but version {have} is installed. "
                  f"Install version 1 with:\n  {fix}", file=sys.stderr)
        else:
            print(f"The MCP server could not start ({e}). Reinstalling the 'mcp' package may help:\n  {fix} --force-reinstall",
                  file=sys.stderr)
        return 2
    mcp_main(a.directory or a.root, a.transport)
    return 0


def cmd_builder(a: argparse.Namespace) -> int:
    from .builder.server import serve
    from .launcher import open_query, workspace_for

    folder, name = workspace_for(a.directory)        # an experiment file opens the folder it is in
    if not folder.is_dir():
        raise CLIError(f"there is no folder '{a.directory}'. Check the name, or create it and open it with:  "
                       f"edge start {shlex_quote(a.directory)}")
    if name:
        print(f"{name} is an experiment file: opening the folder it is in, {folder}")
    serve(folder, host=a.host, port=a.port, open_browser=not a.no_browser, path_query=open_query(name))
    return 0


def cmd_start(a: argparse.Namespace) -> int:
    from .launcher import launch, launch_from_shortcut
    if a.from_shortcut:
        return launch_from_shortcut(a.directory, port=a.port)
    return launch(a.directory, port=a.port, open_browser=not a.no_browser)


def cmd_shortcut(a: argparse.Namespace) -> int:
    from .launcher import default_workspace, desktop_shortcut, workspace_for
    ws = None
    if a.workspace:     # the icon starts in another folder: a relative path must not depend on where that is
        folder, _ = workspace_for(a.workspace)
        ws = folder.resolve()
    files = desktop_shortcut(workspace=ws)
    for f in files:
        print(f"created {f}")
    print(f"The icon opens the builder on {ws or default_workspace()}")
    return 0 if files else 1


def cmd_wizard(a: argparse.Namespace) -> int:
    from .launcher import ask_wizard, load_answers, write_wizard_experiment
    from .wizard import WizardError
    try:
        answers = load_answers(a.answers) if a.answers else ask_wizard()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled: nothing was created.")
        return 1
    except WizardError as e:          # the answers file can't be read
        print(f"Can't use those answers: {e}")
        return 2
    try:
        path, est = write_wizard_experiment(answers, Path(a.directory))
    except WizardError as e:
        print(f"Can't build that: {e}")
        return 2
    print(f"\nCreated {path}: {est['text']}")
    for note in est.get("notes") or []:       # answers filled in, adjusted or left out; files still to provide
        print(f"Note: {note}")
    print(f"Try it:   edge run {shlex_quote(str(path))} --dry-run")
    print(f"Edit it:  edge builder {shlex_quote(str(path.parent))}")
    return 0


def shlex_quote(s: str) -> str:
    """A path as it must be typed in this computer's terminal (names with spaces in quotes), so a command EDGE
    suggests works when copied."""
    if sys.platform.startswith("win"):        # cmd.exe and PowerShell: double quotes
        return f'"{s}"' if any(c in s for c in ' \t&()[]{}^=;!\'+,`~') else s
    import shlex
    return shlex.quote(s)


class _Parser(argparse.ArgumentParser):
    """A mistake after a command is explained by that command (its own usage and a did-you-mean), not with the
    list of every command."""

    def _commands(self) -> dict[str, argparse.ArgumentParser]:
        subs = [x for x in self._actions if isinstance(x, argparse._SubParsersAction)]
        return dict(subs[0].choices) if subs else {}

    def parse_known_args(self, args=None, namespace=None):
        ns, extra = super().parse_known_args(args, namespace)
        cmd = getattr(ns, "cmd", None)
        if extra and cmd in self._commands():
            self._commands()[cmd].error(_unrecognized(self._commands()[cmd], extra))
        return ns, extra

    def error(self, message):
        import re
        m = re.search(r"invalid choice: '([^']*)'", message)
        if m and self._commands() and "<command>" in message:
            import difflib
            close = difflib.get_close_matches(m.group(1), list(self._commands()), 1)
            message = (f"there is no command '{m.group(1)}'" + (f"; did you mean {close[0]}?" if close else "")
                       + f" (all commands: {self.prog} --help)")
        super().error(message)


def _unrecognized(parser: argparse.ArgumentParser, extra: list[str]) -> str:
    import difflib
    options = [o for act in parser._actions for o in act.option_strings]
    words = []
    for x in extra:
        close = difflib.get_close_matches(x.split("=")[0], options, 1, 0.6) if x.startswith("-") else []
        words.append(f"{x} (did you mean {close[0]}?)" if close else x)
    msg = "unrecognized arguments: " + " ".join(words)
    if any(not x.startswith("-") for x in extra):
        msg += "\n  (a file or folder name with spaces must be in quotes, e.g. \"my study/study.yaml\")"
    return msg


def main(argv: list[str] | None = None) -> int:
    p = _Parser(prog="edge", description="EDGE experiment builder and runtime")
    from . import __version__
    from .launcher import WORKSPACE_HELP
    p.add_argument("--version", action="version", version=f"edge {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    st = sub.add_parser("start", help="open the builder on your experiments folder (what `edge` alone does)")
    st.add_argument("directory", nargs="?", help=f"experiments folder, or an experiment file to open the folder it is in "
                                                 f"(default: {WORKSPACE_HELP})")
    st.add_argument("--port", type=int, default=8765, help="local port for the builder (default: 8765)")
    st.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    st.add_argument("--from-shortcut", action="store_true", help=argparse.SUPPRESS)
    st.set_defaults(fn=cmd_start)

    sc = sub.add_parser("desktop-shortcut", help="put an EDGE icon on the desktop / in the app menu")
    sc.add_argument("--workspace", help=f"folder the icon opens (default: {WORKSPACE_HELP})")
    sc.set_defaults(fn=cmd_shortcut)

    wz = sub.add_parser("wizard", help="answer a few questions and get a finished experiment")
    wz.add_argument("directory", nargs="?", default=".", help="where to create it (default: the current folder)")
    wz.add_argument("--answers", help="JSON or YAML file with the answers instead of asking")
    wz.set_defaults(fn=cmd_wizard)

    r = sub.add_parser("run", help="run an experiment")
    r.add_argument("experiment", help="experiment file (.yaml or .json)")
    r.add_argument("-p", "--participant", help="participant id (also used for counterbalancing; default: the "
                                               "experiment's, usually 001). EDGE warns if it already has data")
    r.add_argument("-s", "--session", help="session number (default: 1)")
    r.add_argument("-f", "--field", action="append", metavar="KEY=VALUE",
                   help="another participant field, e.g. -f age=30 (repeat for more)")
    r.add_argument("--dry-run", action="store_true", help="test run: no window, simulated devices, a virtual "
                                                         "participant; saved under data/dry_runs")
    r.add_argument("--simulate-devices", action="store_true", help="replace hardware with simulators")
    r.add_argument("--backend", default="pyglet", choices=["pyglet", "headless", "headless-realtime"],
                   help="pyglet (default): the experiment window; headless-realtime: no window, real clock "
                        "(screenless tasks with real hardware); headless: no window, simulated clock, for automated "
                        "tests (to test an experiment use --dry-run)")
    r.add_argument("--data-dir", help="where to write data (default: data/ next to the experiment)")
    r.add_argument("--report", action="store_true", help="print the quality report afterwards")
    fs = r.add_mutually_exclusive_group()
    fs.add_argument("--fullscreen", dest="fullscreen", action="store_true", default=None,
                    help="full screen (overrides the experiment setting)")
    fs.add_argument("--windowed", dest="fullscreen", action="store_false", help="in a window")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("validate", help="check an experiment for errors")
    v.add_argument("experiment", help="experiment file")
    v.add_argument("--json", action="store_true", help="machine-readable output")
    v.set_defaults(fn=cmd_validate)

    d = sub.add_parser("devices", help="list device drivers")
    d.add_argument("--json", action="store_true", help="full driver descriptions as JSON")
    d.set_defaults(fn=cmd_devices)

    c = sub.add_parser("components", help="list components")
    c.add_argument("--json", action="store_true", help="full component descriptions as JSON")
    c.set_defaults(fn=cmd_components)

    s = sub.add_parser("scan", help="discover connected hardware (LSL, serial, Tobii, Gazepoint)")
    s.add_argument("--timeout", type=float, default=2.0, help="seconds to listen for LSL streams")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_scan)

    dr = sub.add_parser("doctor", help="check this computer for known causes of bad timing and lost responses")
    dr.add_argument("experiment", nargs="?", help="also check against this experiment's screen and devices")
    dr.add_argument("--fix", action="store_true", help="fix what can be fixed automatically")
    dr.add_argument("--json", action="store_true", help="machine-readable output")
    dr.set_defaults(fn=cmd_doctor)

    pf = sub.add_parser("preflight", help="go / no-go before collecting data: checks, test run, lock, computer")
    pf.add_argument("experiment", help="experiment file")
    pf.add_argument("--no-golden", action="store_true", help="don't re-run the golden participant of the lock")
    pf.add_argument("--no-computer", action="store_true", help="skip the computer check")
    pf.add_argument("--json", action="store_true", help="machine-readable output")
    pf.set_defaults(fn=cmd_preflight)

    td = sub.add_parser("test-device", help="connect an experiment's device(s): data rate, inputs, a test marker")
    td.add_argument("experiment", help="experiment file whose devices to test")
    td.add_argument("device", nargs="?", help="device id (default: all of the experiment's devices)")
    td.add_argument("--seconds", type=float, default=3.0, help="how long to record from each device (default: 3)")
    td.add_argument("--simulate", action="store_true", help="test with the device's simulator")
    td.set_defaults(fn=cmd_test_device)

    tt = sub.add_parser("timing-test", help="create a timing test: real display, audio and trigger latency on this computer")
    tt.add_argument("directory", nargs="?", default=".", help="where to create it (default: the current folder)")
    tt.set_defaults(fn=cmd_timing_test)

    up = sub.add_parser("update", help="download and install the newest EDGE")
    up.add_argument("--check", action="store_true", help="only look whether there is something new")
    up.add_argument("--stash", action="store_true", help="set your own uncommitted changes aside and put them back after")
    up.add_argument("--branch", help="git branch to update from (default: the one you are on)")
    up.set_defaults(fn=cmd_update)

    lk = sub.add_parser("lock", help="record versions, file fingerprints and a golden participant after piloting")
    lk.add_argument("experiment", help="experiment file")
    lk.add_argument("--no-golden", action="store_true", help="skip the golden-participant dry run")
    lk.set_defaults(fn=cmd_lock)

    vf = sub.add_parser("verify", help="check that the experiment, its files and this computer still match the lock")
    vf.add_argument("experiment", help="experiment file (its lock is the .lock.json next to it)")
    vf.add_argument("--no-golden", action="store_true", help="skip the golden-participant dry run")
    vf.add_argument("--json", action="store_true", help="machine-readable output")
    vf.set_defaults(fn=cmd_verify)

    sb = sub.add_parser("support-bundle", help="pack everything needed to ask for help (no participant data)")
    sb.add_argument("path", help="an experiment file or a session folder")
    sb.add_argument("--out", help="where to write the .zip")
    sb.add_argument("--include-data", action="store_true", help="also include the trial data (participant fields removed)")
    sb.set_defaults(fn=cmd_support)

    rp = sub.add_parser("report", help="timing / data / sync quality report for a session")
    rp.add_argument("session_dir", nargs="+", help="a session folder in data/ (a data folder or an experiment file "
                                                   "means its newest session)")
    rp.add_argument("--json", action="store_true", help="machine-readable output")
    rp.set_defaults(fn=cmd_report)

    al = sub.add_parser("align", help="align an external recording via shared TTL codes")
    al.add_argument("session_dir", nargs="+", help="the EDGE session folder")
    al.add_argument("external", help="CSV with columns time,code (external clock)")
    al.add_argument("--tolerance", type=float, default=0.05,
                    help="maximum timing mismatch (s) when pairing events (default: 0.05)")
    al.add_argument("--json", action="store_true", help="machine-readable output")
    al.set_defaults(fn=cmd_align)

    n = sub.add_parser("new", help="create an experiment from a template")
    from .templates import public_templates
    n.add_argument("template", help=", ".join(public_templates()))
    n.add_argument("directory", nargs="?", default=".", help="where to create it")
    n.set_defaults(fn=cmd_new)

    b = sub.add_parser("builder", help="open the visual experiment builder")
    b.add_argument("directory", nargs="?", default=".", help="folder with your experiments, or an experiment file to open "
                                                            "the folder it is in (default: the current folder)")
    b.add_argument("--host", default="127.0.0.1", help="interface to listen on (keep the default for safety)")
    b.add_argument("--port", type=int, default=8765, help="local port for the builder")
    b.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    b.set_defaults(fn=cmd_builder)

    ex = sub.add_parser("export", help="export analysis-ready tables (one session or a whole data folder)")
    ex.add_argument("path", help="session folder or data folder")
    ex.add_argument("--formats", default="csv,xlsx",
                    help="one or more of csv,tsv,xlsx,json,jsonl,parquet,mat,bids, separated by commas (default: csv,xlsx)")
    ex.add_argument("--layout", default="wide", choices=["wide", "long"],
                    help="wide (default): one row per trial; long: one row per routine")
    ex.add_argument("--out", help="output folder (default: <path>/exports)")
    ex.add_argument("--name", help="start of the file names (default: the session folder's name, or "
                                   "<experiment>_all_<date> for a data folder)")
    ex.add_argument("--include-dry-runs", action="store_true", help="also include dry-run sessions")
    ex.set_defaults(fn=cmd_export)

    bu = sub.add_parser("bundle", help="pack an experiment and its files into a .edgez archive")
    bu.add_argument("experiment", help="experiment file")
    bu.add_argument("--out", help="bundle path (default: <experiment>.edgez)")
    bu.set_defaults(fn=cmd_bundle)

    ub = sub.add_parser("unbundle", help="extract a .edgez archive")
    ub.add_argument("bundle", help=".edgez file")
    ub.add_argument("directory", nargs="?", default=".", help="folder with your experiments (default: current)")
    ub.set_defaults(fn=cmd_unbundle)

    bk = sub.add_parser("backups", help="list or restore automatic backups of an experiment")
    bk.add_argument("experiment", help="experiment file")
    bk.add_argument("--restore", nargs="?", const="", help="restore the newest backup, or the given id")
    bk.set_defaults(fn=cmd_backups)

    im = sub.add_parser("import", help="import a PsychoPy, E-Prime, OpenSesame or jsPsych experiment")
    im.add_argument("source", help=".psyexp, .ebs3/.ebs2, .osexp/.opensesame, or jsPsych .html/.js")
    im.add_argument("--out", help="output folder (default: <source>_edge next to the source)")
    im.add_argument("--platform", choices=["psychopy", "eprime", "opensesame", "jspsych"], help="force the source platform (normally detected)")
    im.add_argument("--name", help="name for the imported experiment")
    im.set_defaults(fn=cmd_import)

    hl = sub.add_parser("help", help="read the documentation or search it")
    hl.add_argument("query", nargs="*", help="a guide name (e.g. cookbook) or search words (e.g. jitter isi)")
    hl.add_argument("--first", action="store_true", help="show the best search match in full")
    hl.add_argument("--raw", action="store_true", help="print Markdown as is")
    hl.add_argument("--limit", type=int, default=8, help="number of search results")
    hl.set_defaults(fn=cmd_help)

    tu = sub.add_parser("tutorial", help="list or start the interactive tutorials")
    tu.add_argument("name", nargs="?", help="tutorial id (omit to list)")
    tu.add_argument("directory", nargs="?", help="folder to work in (default: tutorial_<name>)")
    tu.add_argument("--print", action="store_true", help="print the tutorial instead of starting it")
    tu.add_argument("--port", type=int, default=8765, help="local port for the builder")
    tu.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    tu.set_defaults(fn=cmd_tutorial)

    dc = sub.add_parser("docs", help="for EDGE developers: regenerate the reference pages (to read the docs: edge help)")
    dc.add_argument("action", choices=["build"], nargs="?", default=None, help="build: regenerate reference pages and TUTORIALS.md")
    dc.add_argument("--check", action="store_true", help="only report whether generated pages are up to date")
    dc.set_defaults(fn=cmd_docs)

    m = sub.add_parser("mcp", help="run the MCP server (natural-language control from Claude / VS Code)")
    m.add_argument("directory", nargs="?", default=None, help="workspace folder (the same as --root)")
    m.add_argument("--root", default=".", help="workspace folder the server may read and write")
    m.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"], help="stdio for Claude/VS Code; http transports for remote clients")
    m.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    if a.cmd is None:          # plain `edge`, e.g. from the desktop icon
        from .launcher import launch
        a.cmd, a.fn = "start", lambda _a: launch()
    from .diagnostics import ExperimentError
    from .export import ExportError
    from .storage import ConflictError, DocumentError
    try:
        return a.fn(a)
    except (DocumentError, ConflictError, ExportError, CLIError) as e:
        print(f"edge {a.cmd}: {e}", file=sys.stderr)
        return 2
    except FileExistsError as e:        # e.g. a folder was asked for where a file of that name is
        name = e.filename or ""
        print(f"edge {a.cmd}: '{name}' already exists" + (" and is a file, not a folder: give the name of a folder "
                                                           "(a new one, or one that exists)" if Path(name).is_file() else ""),
              file=sys.stderr)
        return 2
    except BrokenPipeError:             # the output went to a program that stopped reading (edge help | head)
        try:
            import os
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())   # no second error at exit
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    except OSError as e:                # file not found, not a folder, no permission, no free port …
        where = f" ({e.filename})" if getattr(e, "filename", None) else ""
        print(f"edge {a.cmd}: {e.strerror or e}{where}", file=sys.stderr)
        return 2
    except (ValueError, ImportError, ExperimentError) as e:     # said in words by the code that raised it
        print(f"edge {a.cmd}: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"edge {a.cmd}: stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
