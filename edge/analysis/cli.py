"""``edge analyze epochs|fixations|aoi SESSION``: the command-line side of edge.analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _print(res: dict[str, Any], lines: list[str], as_json: bool) -> int:
    if as_json:
        print(json.dumps({k: v for k, v in res.items() if not k.endswith("_rows") and k not in ("times", "erp")},
                         indent=2, default=str))
        return 0
    for line in lines:
        print(line)
    for n in res.get("notes") or []:
        print(f"note: {n}")
    if res.get("files"):
        print("Saved:\n  " + "\n  ".join(str(f) for f in res["files"]))
    return 0


def _ms(v: Any) -> str:
    return "-" if v is None else f"{v * 1000:.0f} ms"


def cmd_epochs(a: argparse.Namespace) -> int:
    from . import epochs
    reject: Any = a.reject if a.reject is not None else "auto"
    res = epochs(a.session, stream=a.stream, markers=_split(a.markers), tmin=a.tmin, tmax=a.tmax,
                 baseline=None if a.no_baseline else tuple(a.baseline), reject=reject,
                 channels=_split(a.channels) or None, by=_split(a.by), out=a.out, plot=not a.no_plot)
    conds = ", ".join(f"{k}: {v}" for k, v in res["conditions"].items())
    lines = [f"{res['epochs']} epochs of {res['stream']} ({len(res['channels'])} channel(s), {res['srate']:g} Hz) "
             f"from {res['tmin']:g} to {res['tmax']:g} s around {', '.join(res['markers'])}",
             f"kept {res['kept']}, rejected {res['rejected']}"
             + (f" (peak-to-peak over {res['reject']:g})" if res["reject"] else "") + (f"; per condition: {conds}"
                                                                                     if conds else "")]
    return _print(res, lines, a.json)


def _fix_opts(a: argparse.Namespace) -> dict[str, float]:
    o = {"velocity_threshold": a.velocity, "dispersion_threshold": a.dispersion, "min_duration": a.min_duration,
         "noise_filter": a.noise_filter}
    allowed = ("velocity_threshold", "min_duration", "noise_filter") if a.method == "ivt" else \
        ("dispersion_threshold", "min_duration", "noise_filter")
    bad = [k for k, v in o.items() if v is not None and k not in allowed]
    if bad:
        from .common import AnalysisError
        flag = {"velocity_threshold": "--velocity", "dispersion_threshold": "--dispersion"}[bad[0]]
        raise AnalysisError(f"{flag} is a setting of the other method; use --method "
                            f"{'ivt' if bad[0] == 'velocity_threshold' else 'idt'}")
    return {k: v for k, v in o.items() if v is not None}


def cmd_fixations(a: argparse.Namespace) -> int:
    from . import fixations
    res = fixations(a.session, method=a.method, stream=a.stream, out=a.out, **_fix_opts(a))
    lines = [f"{res['fixations']} fixations (mean {_ms(res['mean_fixation_duration'])}) and {res['saccades']} "
             f"saccades in {res['stream']} ({res['method'].upper()}, {res['samples']} samples at {res['srate']:g} Hz, "
             f"{res['lost_samples']} without gaze; {res['screen']['px_per_deg']:g} px per degree)"]
    return _print(res, lines, a.json)


def cmd_aoi(a: argparse.Namespace) -> int:
    from . import aoi_report
    from .common import AnalysisError
    aois: list[Any] = list(a.aoi or [])
    if a.aoi_file:
        import yaml
        try:
            data = yaml.safe_load(Path(a.aoi_file).read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise AnalysisError(f"{a.aoi_file} is not valid YAML/JSON: {e}") from None
        data = data.get("aois", data) if isinstance(data, dict) else data
        if not isinstance(data, list):
            raise AnalysisError(f"{a.aoi_file} must hold a list of AOIs (or aois: [...])")
        aois += data
    res = aoi_report(a.session, aois=aois, by=_split(a.by) if a.by is not None else None, method=a.method,
                     stream=a.stream, out=a.out, include_experiment=not a.no_experiment_aois, **_fix_opts(a))
    lines = [f"{len(res['trial_rows'])} trial x AOI rows for {len(res['aois'])} AOI(s): {', '.join(res['aois'])}",
             f"{res['fixations']} fixations ({res['method'].upper()}); conditions: {', '.join(res['by']) or '(none)'}"]
    return _print(res, lines, a.json)


def add_parser(sub: Any) -> None:
    an = sub.add_parser("analyze", help="analyse recorded signals: EEG/pupil epochs, fixations, AOIs")
    asub = an.add_subparsers(dest="analysis", metavar="{epochs,fixations,aoi}",
                             help="epochs (EEG/pupil), fixations (and saccades) or aoi (areas of interest)")
    asub.required = True

    ep = asub.add_parser("epochs", help="cut EEG/pupil epochs around markers, baseline, reject, average per condition")
    ep.add_argument("session", help="session folder")
    ep.add_argument("--stream", default="eeg", help="device id, device.stream, kind (eeg), or 'pupil' (default: eeg)")
    ep.add_argument("--markers", required=True, help="marker labels, separated by commas (wildcards: view_*)")
    ep.add_argument("--tmin", type=float, default=-0.2, help="epoch start in s from the marker (default -0.2)")
    ep.add_argument("--tmax", type=float, default=0.8, help="epoch end in s from the marker (default 0.8)")
    ep.add_argument("--baseline", type=float, nargs=2, default=[-0.2, 0.0], metavar=("FROM", "TO"),
                    help="baseline window in s (default -0.2 0)")
    ep.add_argument("--no-baseline", action="store_true", help="no baseline correction")
    ep.add_argument("--reject", help="peak-to-peak limit in the channel's units (default: 150 for µV channels; "
                                     "'none' keeps every epoch)")
    ep.add_argument("--channels", help="channels, separated by commas (default: all but trigger channels)")
    ep.add_argument("--by", help="trial-list columns that define the conditions (default: the marker label)")
    ep.add_argument("--out", help="output folder (default: <session>/analysis)")
    ep.add_argument("--no-plot", action="store_true", help="don't draw the PNG")
    ep.add_argument("--json", action="store_true", help="print the result as JSON")
    ep.set_defaults(fn=cmd_epochs)

    def fix_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--method", choices=["ivt", "idt"], default="ivt",
                       help="ivt: velocity threshold (default); idt: dispersion threshold")
        p.add_argument("--stream", default="", help="gaze stream (default: the first one)")
        p.add_argument("--velocity", type=float, help="I-VT threshold in deg/s (default 30)")
        p.add_argument("--dispersion", type=float, help="I-DT threshold in degrees (default 1.0)")
        p.add_argument("--min-duration", type=float, help="shortest fixation in s (default 0.06 I-VT, 0.1 I-DT)")
        p.add_argument("--noise-filter", type=int, help="moving median over this many samples (default 3; 1 = off)")
        p.add_argument("--out", help="output folder (default: <session>/analysis)")
        p.add_argument("--json", action="store_true", help="print the result as JSON")

    fx = asub.add_parser("fixations", help="detect fixations and saccades (fixations.csv, saccades.csv)")
    fx.add_argument("session", help="session folder")
    fix_args(fx)
    fx.set_defaults(fn=cmd_fixations)

    ao = asub.add_parser("aoi", help="areas of interest per trial and condition (aoi_trials.csv, aoi_summary.csv)")
    ao.add_argument("session", help="session folder")
    ao.add_argument("--aoi", action="append", metavar="NAME:SHAPE:NUMBERS",
                    help="your own AOI, e.g. face:rect:0,100,300,200 or centre:circle:0,0,80 (px from the screen "
                         "centre, +y up), optionally :screen at the end; repeat for more")
    ao.add_argument("--aoi-file", help="YAML/JSON list of AOIs: {name, shape, pos, size | radius, units, routine}")
    ao.add_argument("--no-experiment-aois", action="store_true",
                    help="only your own AOIs, not the experiment's gaze areas, pictures and shapes")
    ao.add_argument("--by", help="trial-list columns for the per-condition table (default: the trial list's "
                                 "factors; '' for none)")
    fix_args(ao)
    ao.set_defaults(fn=cmd_aoi)
