"""Align externally recorded data (e.g. MindWare BioLab, BIOPAC AcqKnowledge, BrainVision
Recorder exports) to an EDGE session using the TTL event codes both sides recorded.

The external file only needs event times on its own clock and the codes::

    time,code
    12.5034,1
    13.5371,2

Comma, semicolon or tab separated files work, and so do common headers (``Time (s),Event``,
``latency;type``, BrainVision ``S  1`` codes); times in milliseconds are recognised.

``edge align session_dir external_events.csv`` matches the code sequences
(robust to missing or extra events), fits ``master = offset + slope * external``
and writes ``alignment.json`` into the session folder. Apply it to any column
of the external recording to put it on the EDGE master clock.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .sync import fit_linear


def match_sequences(ext: list[tuple[float, int]], edge: list[tuple[float, int]], tolerance: float = 0.05
                    ) -> list[tuple[float, float]]:
    """Return (external_time, edge_time) pairs of corresponding events.

    Tries every pairing of equal codes as an anchor for the offset, keeps the
    anchor that explains the most events (consensus), then pairs events whose
    predicted times agree within ``tolerance`` seconds.
    """
    best: list[tuple[float, float]] = []
    by_code: dict[int, list[float]] = {}
    for t, c in edge:
        by_code.setdefault(c, []).append(t)
    anchors = ext[: min(len(ext), 50)]
    for te, ce in anchors:
        for tm in by_code.get(ce, [])[:200]:
            off = tm - te
            pairs = []
            for t2, c2 in ext:
                target = t2 + off
                cands = by_code.get(c2, [])
                # nearest edge event with the same code
                k = min(cands, key=lambda x: abs(x - target)) if cands else None
                if k is not None and abs(k - target) <= tolerance:
                    pairs.append((t2, k))
            if len(pairs) > len(best):
                best = pairs
    return best


class AlignError(ValueError):
    """A problem with the files given to ``edge align``, in words a researcher can act on."""


TIME_NAMES = ("time", "times", "timestamp", "onset", "latency", "seconds", "sec", "secs", "t", "time_s", "time_ms",
              "ms", "milliseconds")
CODE_NAMES = ("code", "codes", "event", "events", "value", "trigger", "triggers", "marker", "markers", "ttl", "type",
              "description", "stimulus", "label")


def _norm(name: str) -> tuple[str, str | None]:
    """'Time (s)' -> ('time', 's'); 'Latency [ms]' -> ('latency', 'ms')."""
    n = name.strip().strip('"').strip().lower().lstrip("﻿")
    unit = None
    m = re.search(r"[(\[]\s*(ms|msec|milliseconds?|s|sec|secs|seconds?)\s*[)\]]", n)
    if m:
        unit = "ms" if m.group(1).startswith("m") else "s"
        n = (n[:m.start()] + n[m.end():]).strip()
    n = re.sub(r"[\s\-]+", "_", n)
    if n in ("time_ms", "ms", "milliseconds"):
        unit = "ms"
    return n, unit


def _code(v: str) -> int | None:
    """'12' -> 12, '12.0' -> 12, BrainVision 'S 12' / 'Stimulus/S  12' -> 12; anything else -> None."""
    v = (v or "").strip()
    try:
        c = int(float(v))
    except ValueError:
        m = re.search(r"(\d+)\s*$", v)
        if not m:
            return None
        c = int(m.group(1))
    return c or None


def read_external(path: str | Path) -> tuple[list[tuple[float, int]], dict[str, Any]]:
    """Event times and codes from an external recording's event export, whatever the usual layout:
    comma, semicolon or tab separated, decimal commas, headers such as 'Time (s),Event' or 'latency;type'."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = p.read_text(encoding="latin-1")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise AlignError(f"{p.name} is empty")
    try:
        delim = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t").delimiter
    except csv.Error:
        delim = ";" if lines[0].count(";") > lines[0].count(",") else ("\t" if "\t" in lines[0] else ",")
    rows = list(csv.reader(lines, delimiter=delim))
    header = rows[0]
    names = [_norm(h) for h in header]
    t_col = next((i for i, (n, _) in enumerate(names) if n in TIME_NAMES), None)
    c_col = next((i for i, (n, _) in enumerate(names) if n in CODE_NAMES and i != t_col), None)
    if t_col is None or c_col is None:
        raise AlignError(f"{p.name} needs a column with the event times and one with the event codes (for example "
                         f"a first line 'time,code'); its columns are: {', '.join(h.strip() for h in header) or '(none)'}. "
                         "Rename the two columns to time and code")
    unit = names[t_col][1]
    events: list[tuple[float, int]] = []
    bad = 0
    for r in rows[1:]:
        if len(r) <= max(t_col, c_col):
            bad += 1
            continue
        raw_t = r[t_col].strip()
        if delim != "," and "," in raw_t and "." not in raw_t:
            raw_t = raw_t.replace(",", ".")          # decimal comma (European spreadsheet exports)
        try:
            t = float(raw_t)
        except ValueError:
            bad += 1
            continue
        c = _code(r[c_col])
        if c is not None:
            events.append((t, c))
    if not events:
        raise AlignError(f"no events could be read from {p.name}: the '{header[c_col].strip()}' column has no "
                         f"numeric codes (and {bad} line(s) could not be read). Export the event times and TTL codes "
                         "as two columns, time and code")
    return events, {"time_column": header[t_col].strip(), "code_column": header[c_col].strip(),
                    "unit": unit, "delimiter": delim}


def _median_gap(times: list[float]) -> float | None:
    gaps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
    return gaps[len(gaps) // 2] if gaps else None


def align(session_dir: str | Path, external_csv: str | Path, tolerance: float = 0.05) -> dict[str, Any]:
    root = Path(session_dir)
    if not (root / "events.jsonl").is_file():
        raise AlignError(f"{root} is not an EDGE session folder (it has no events.jsonl): give one of the folders "
                         "inside data/, e.g. data/001_1_study_2026-01-31_101500")
    if not Path(external_csv).is_file():
        raise AlignError(f"{external_csv}: file not found")
    events = []
    for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    edge_ev = [(float(e["time"]), int(e["code"])) for e in events if e.get("code") is not None]
    if not edge_ev:
        raise AlignError("this session sent no event codes, so there is nothing to align the external file with")
    ext, info = read_external(external_csv)
    scale = 1.0
    if info["unit"] == "ms":
        scale = 1e-3
    elif info["unit"] is None:
        # times in milliseconds without saying so: events ~1000x further apart than in the session
        ge, gx = _median_gap([t for t, _ in edge_ev]), _median_gap([t for t, _ in ext])
        if ge and gx and 300 < gx / ge < 3000:
            scale, info["unit"] = 1e-3, "ms (detected: the events are about 1000 times further apart than in the session)"
    if scale != 1.0:
        ext = [(t * scale, c) for t, c in ext]
    pairs = match_sequences(ext, edge_ev, tolerance)
    if len(pairs) < 2:
        codes_ext = sorted({c for _, c in ext})[:10]
        codes_edge = sorted({c for _, c in edge_ev})[:10]
        raise AlignError(f"could not match the events of {Path(external_csv).name} ({len(ext)} events, codes "
                         f"{codes_ext}) with the session's markers ({len(edge_ev)} events, codes {codes_edge}): check that "
                         "the file belongs to this session and that its codes are the TTL codes EDGE sent "
                         "(marker_codebook in session.json)")
    model = fit_linear(pairs, fit_drift=len(pairs) >= 5)
    # refine: re-match every event against the drift-aware model (long sessions drift past the tolerance)
    by_code: dict[int, list[float]] = {}
    for t, c in edge_ev:
        by_code.setdefault(c, []).append(t)
    refined = []
    for te, ce in ext:
        target = model.to_master(te)
        cands = by_code.get(ce, [])
        if cands:
            k = min(cands, key=lambda x: abs(x - target))
            if abs(k - target) <= tolerance:
                refined.append((te, k))
    if len(refined) >= len(pairs):
        pairs = refined
        model = fit_linear(pairs, fit_drift=len(pairs) >= 5)
    result = {"external_file": str(external_csv), "matched": len(pairs), "external_events": len(ext),
              "edge_events": len(edge_ev), "model": model.to_dict(),
              "external_columns": {"time": info["time_column"], "code": info["code_column"]},
              "external_time_unit": "s" if scale == 1.0 else info["unit"],
              "usage": "master_time = offset + slope * external_time" if scale == 1.0 else
                       "master_time = offset + slope * (external_time / 1000)   (the external times are in ms)"}
    (root / "alignment.json").write_text(json.dumps(result, indent=2))
    return result
