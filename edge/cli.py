"""Command line interface: ``edge <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _kv(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k] = v
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
        print(f"\n{len(errors)} error(s): fix them before running (edge validate {a.experiment})")
        return 2
    participant = _kv(a.field)
    if a.participant:
        participant["participant"] = a.participant
    if a.session:
        participant["session"] = a.session
    summary = run_experiment(exp, backend=a.backend, participant=participant, dry_run=a.dry_run,
                             data_dir=a.data_dir, simulate_devices=a.simulate_devices or None)
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
    for name, cls in sorted(reg.items(), key=lambda kv: (kv[1].category, kv[0])):
        print(f"{cls.category:12s} {name:12s} {cls.description}")
    return 0


def cmd_scan(a: argparse.Namespace) -> int:
    from .scan import scan_all

    found = scan_all(timeout=a.timeout)
    if a.json:
        print(json.dumps(found, indent=2, default=str))
        return 0
    for section, items in found.items():
        print(f"{section}:")
        if not items:
            print("  (none)")
        for it in items:
            print("  - " + ", ".join(f"{k}={v}" for k, v in it.items()))
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    from .report import analyze_session, format_report

    rep = analyze_session(a.session_dir)
    print(json.dumps(rep, indent=2, default=str) if a.json else format_report(rep))
    return 0


def cmd_align(a: argparse.Namespace) -> int:
    from .align import align

    res = align(a.session_dir, a.external, tolerance=a.tolerance)
    print(json.dumps(res, indent=2))
    return 0


def cmd_new(a: argparse.Namespace) -> int:
    from .templates import TEMPLATES, write_template

    if a.template not in TEMPLATES:
        print(f"unknown template; choose from: {', '.join(TEMPLATES)}")
        return 2
    path = write_template(a.template, Path(a.directory))
    print(f"created {path}\n  try:  edge run {path} --dry-run")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from .export import export_many, export_session

    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    p = Path(a.path)
    if (p / "session.json").exists():
        files = export_session(p, formats, a.out, a.layout)
        print("\n".join(str(f) for f in files))
    else:
        res = export_many(p, formats, a.out, a.include_dry_runs, a.name)
        print(f"{res['sessions']} session(s), {res['participants']} participant(s), {res['trials']} trials")
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
    for b in list_backups(a.experiment):
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
    print(f"imported {res.platform} experiment -> {path}")
    print("converted: " + ", ".join(f"{v} {k}" for k, v in sorted(res.stats.items())))
    print(f"{n_approx} item(s) converted approximately, {n_unsup} not converted: see {path.parent / 'IMPORT_REPORT.md'}")
    print(f"next:  edge run {path} --dry-run --report")
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    try:
        from .mcp_server import main as mcp_main
    except ImportError:
        print("the MCP server needs the 'mcp' package: pip install 'edge-experiments[mcp]'", file=sys.stderr)
        return 2
    mcp_main(a.root, a.transport)
    return 0


def cmd_builder(a: argparse.Namespace) -> int:
    from .builder.server import serve

    serve(Path(a.directory), host=a.host, port=a.port, open_browser=not a.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="edge", description="EDGE experiment builder and runtime")
    from . import __version__
    p.add_argument("--version", action="version", version=f"edge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run an experiment")
    r.add_argument("experiment")
    r.add_argument("-p", "--participant")
    r.add_argument("-s", "--session")
    r.add_argument("-f", "--field", action="append", help="extra participant field key=value")
    r.add_argument("--dry-run", action="store_true", help="headless, simulated devices, virtual participant")
    r.add_argument("--simulate-devices", action="store_true", help="replace hardware with simulators")
    r.add_argument("--backend", default="pyglet", choices=["pyglet", "headless", "headless-realtime"],
                   help="headless-realtime: no window, real clock (screenless tasks with real hardware)")
    r.add_argument("--data-dir")
    r.add_argument("--report", action="store_true", help="print the quality report afterwards")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("validate", help="check an experiment for errors")
    v.add_argument("experiment")
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_validate)

    d = sub.add_parser("devices", help="list device drivers")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_devices)

    c = sub.add_parser("components", help="list components")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_components)

    s = sub.add_parser("scan", help="discover connected hardware (LSL, serial, Tobii, Gazepoint)")
    s.add_argument("--timeout", type=float, default=2.0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scan)

    rp = sub.add_parser("report", help="timing / data / sync quality report for a session")
    rp.add_argument("session_dir")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(fn=cmd_report)

    al = sub.add_parser("align", help="align an external recording via shared TTL codes")
    al.add_argument("session_dir")
    al.add_argument("external", help="CSV with columns time,code (external clock)")
    al.add_argument("--tolerance", type=float, default=0.05)
    al.set_defaults(fn=cmd_align)

    n = sub.add_parser("new", help="create an experiment from a template")
    n.add_argument("template")
    n.add_argument("directory", nargs="?", default=".")
    n.set_defaults(fn=cmd_new)

    b = sub.add_parser("builder", help="open the visual experiment builder")
    b.add_argument("directory", nargs="?", default=".")
    b.add_argument("--host", default="127.0.0.1")
    b.add_argument("--port", type=int, default=8765)
    b.add_argument("--no-browser", action="store_true")
    b.set_defaults(fn=cmd_builder)

    ex = sub.add_parser("export", help="export analysis-ready tables (one session or a whole data folder)")
    ex.add_argument("path", help="session folder or data folder")
    ex.add_argument("--formats", default="csv,xlsx", help="csv,tsv,xlsx,json,jsonl,parquet,mat,bids")
    ex.add_argument("--layout", default="wide", choices=["wide", "long"])
    ex.add_argument("--out", help="output folder (default: <path>/exports)")
    ex.add_argument("--name", help="file name stem for merged exports")
    ex.add_argument("--include-dry-runs", action="store_true")
    ex.set_defaults(fn=cmd_export)

    bu = sub.add_parser("bundle", help="pack an experiment and its files into a .edgez archive")
    bu.add_argument("experiment")
    bu.add_argument("--out")
    bu.set_defaults(fn=cmd_bundle)

    ub = sub.add_parser("unbundle", help="extract a .edgez archive")
    ub.add_argument("bundle")
    ub.add_argument("directory", nargs="?", default=".")
    ub.set_defaults(fn=cmd_unbundle)

    bk = sub.add_parser("backups", help="list or restore automatic backups of an experiment")
    bk.add_argument("experiment")
    bk.add_argument("--restore", nargs="?", const="", help="restore the newest backup, or the given id")
    bk.set_defaults(fn=cmd_backups)

    im = sub.add_parser("import", help="import a PsychoPy, E-Prime, OpenSesame or jsPsych experiment")
    im.add_argument("source", help=".psyexp, .ebs3/.ebs2, .osexp/.opensesame, or jsPsych .html/.js")
    im.add_argument("--out", help="output folder (default: <source>_edge next to the source)")
    im.add_argument("--platform", choices=["psychopy", "eprime", "opensesame", "jspsych"])
    im.add_argument("--name", help="name for the imported experiment")
    im.set_defaults(fn=cmd_import)

    m = sub.add_parser("mcp", help="run the MCP server (natural-language control from Claude / VS Code)")
    m.add_argument("--root", default=".", help="workspace folder the server may read and write")
    m.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    m.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
