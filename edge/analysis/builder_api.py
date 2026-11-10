"""The builder's Data page runs analyses through these (``/api/analysis_info``, ``/api/analyze``).

Options come from the browser, so each is checked here: only known keys, numbers that are numbers, lists of
text; results are written inside the session folder (``analysis/``), never anywhere the request names.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .common import AnalysisError

KINDS = ("epochs", "fixations", "aoi")
NUM = (int, float)
OPTIONS: dict[str, dict[str, Any]] = {
    "epochs": {"stream": str, "markers": list, "tmin": NUM, "tmax": NUM, "baseline": list, "reject": (str, int, float),
               "channels": list, "by": list},
    "fixations": {"method": str, "stream": str, "velocity_threshold": NUM, "dispersion_threshold": NUM,
                  "min_duration": NUM, "noise_filter": NUM},
    "aoi": {"method": str, "stream": str, "velocity_threshold": NUM, "dispersion_threshold": NUM,
            "min_duration": NUM, "noise_filter": NUM, "aois": list, "by": list, "include_experiment": bool},
}
ROWS = 200


def _check(kind: str, options: dict[str, Any]) -> dict[str, Any]:
    if kind not in KINDS:
        raise AnalysisError(f"unknown analysis '{kind}': choose {', '.join(KINDS)}")
    spec = OPTIONS[kind]
    out: dict[str, Any] = {}
    for k, v in (options or {}).items():
        if v is None or v == "":
            continue
        if k not in spec:
            raise AnalysisError(f"'{k}' is not an option of {kind}; options: {', '.join(spec)}")
        want = spec[k]
        if want is bool and not isinstance(v, bool) or want is not bool and isinstance(v, bool) \
                or not isinstance(v, want) or isinstance(v, float) and not math.isfinite(v):
            raise AnalysisError(f"'{k}' has the wrong type")
        if isinstance(v, list):
            if len(v) > 200 or any(not isinstance(x, (str, int, float, dict)) for x in v):
                raise AnalysisError(f"'{k}' must be a short list")
        out[k] = v
    if kind in ("fixations", "aoi") and out.get("method", "ivt") not in ("ivt", "idt"):
        raise AnalysisError("method must be ivt or idt")
    return out


def run(session: Path, root: Path, kind: str, options: dict[str, Any]) -> dict[str, Any]:
    """Run one analysis on a session folder; file paths in the answer are relative to the builder's folder."""
    from . import aoi_report, epochs, fixations
    o = _check(kind, options)
    rel = lambda p: str(Path(p).resolve().relative_to(root))      # noqa: E731
    if kind == "epochs":
        base = o.get("baseline")
        if base is not None and (len(base) != 2 or not all(isinstance(b, NUM) for b in base)):
            raise AnalysisError("baseline must be two numbers (from, to) in seconds")
        res = epochs(session, stream=o.get("stream", "eeg"), markers=[str(m) for m in o.get("markers", [])],
                     tmin=float(o.get("tmin", -0.2)), tmax=float(o.get("tmax", 0.8)),
                     baseline=tuple(base) if base else None, reject=o.get("reject", "auto"),
                     channels=[str(c) for c in o.get("channels", [])] or None, by=[str(c) for c in o.get("by", [])])
        conds = [{"condition": c, "epochs kept": n} for c, n in res["conditions"].items()]
        info = res["epoch_rows"][:ROWS]
        tables = {"conditions": conds, "epochs": info}
        summary = {k: res[k] for k in ("stream", "channels", "srate", "epochs", "kept", "rejected", "reject",
                                       "tmin", "tmax", "baseline")}
    else:
        fopts = {k: float(o[k]) for k in ("velocity_threshold", "dispersion_threshold", "min_duration", "noise_filter")
                 if k in o}
        method = o.get("method", "ivt")
        if kind == "fixations":
            res = fixations(session, method=method, stream=o.get("stream", ""), **fopts)
            tables = {"fixations": res["fixation_rows"][:ROWS], "saccades": res["saccade_rows"][:ROWS]}
        else:
            res = aoi_report(session, aois=o.get("aois", []), by=[str(c) for c in o["by"]] if "by" in o else None,
                             method=method, stream=o.get("stream", ""),
                             include_experiment=o.get("include_experiment", True), **fopts)
            tables = {"per condition": res["summary_rows"][:ROWS], "per trial": res["trial_rows"][:ROWS]}
        summary = {k: res[k] for k in ("stream", "method", "settings", "srate", "samples", "lost_samples",
                                       "fixations", "saccades", "mean_fixation_duration", "screen")}
    return {"kind": kind, "summary": summary, "tables": tables, "notes": res["notes"],
            "files": [rel(f) for f in res["files"]]}
