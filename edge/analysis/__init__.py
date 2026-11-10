"""Analyses of recorded signals: epochs/ERPs (EEG, pupil), fixations and saccades, AOI reports.

    from edge.analysis import epochs, fixations, aoi_report
    epochs("data/001_1_oddball_...", stream="eeg", markers=["standard", "deviant"], tmin=-0.2, tmax=0.8)
    fixations("data/001_1_freeview_...", method="ivt")
    aoi_report("data/001_1_freeview_...", aois=["centre:circle:0,0,100"])

Results go to ``<session>/analysis/``; each function also returns what it found (counts, notes, files).
No extra packages are needed; plots need matplotlib (``pip install edge-experiments[plots]``).
See docs/DATA.md, "Analyses".
"""

from .common import AnalysisError, Session
from .epochs import baseline_correct, cut, epochs, interpolate_blinks
from .gaze import aoi_report, detect_fixations, experiment_aois, fixations, gaze_samples, user_aoi

__all__ = ["AnalysisError", "Session", "aoi_report", "baseline_correct", "cut", "detect_fixations", "epochs",
           "experiment_aois", "fixations", "gaze_samples", "interpolate_blinks", "user_aoi"]


def analysis_info(session: str) -> dict:
    """What can be analysed in a session: its streams, marker labels, AOIs and condition columns (for the
    builder's Data page)."""
    sess = Session(session)
    streams = sess.streams()
    gaze = [s["name"] for s in streams if s["kind"].lower() == "gaze" or {"x", "y"} <= set(s["channels"])
            or "BPOGX" in s["channels"] or "left_x" in s["channels"]]
    signals = [{"name": s["name"], "kind": s["kind"], "srate": s["srate"],
                "channels": [c for c in s["channels"] if c.lower() not in _TRIG]}
               for s in streams if s["srate"] and s["name"] not in gaze]
    aois = {r: [c.get("id") for c in cs] for r, cs in experiment_aois(sess).items()}
    files = sorted(p.name for p in (sess.root / "analysis").glob("*")) if (sess.root / "analysis").is_dir() else []
    return {"gaze": gaze, "signals": signals, "pupil": bool(gaze), "markers": sess.marker_labels(), "aois": aois,
            "conditions": sess.condition_columns(), "columns": sess.cols, "analysis_files": files}


from .common import TRIGGER_CHANNELS as _TRIG  # noqa: E402
