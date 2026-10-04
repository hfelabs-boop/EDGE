"""Align externally recorded data (e.g. MindWare BioLab, BIOPAC AcqKnowledge, BrainVision
Recorder exports) to an EDGE session using the TTL event codes both sides recorded.

The external file only needs event times on its own clock and the codes::

    time,code
    12.5034,1
    13.5371,2

``edge align session_dir external_events.csv`` matches the code sequences
(robust to missing or extra events), fits ``master = offset + slope * external``
and writes ``alignment.json`` into the session folder. Apply it to any column
of the external recording to put it on the EDGE master clock.
"""

from __future__ import annotations

import csv
import json
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


def align(session_dir: str | Path, external_csv: str | Path, tolerance: float = 0.05) -> dict[str, Any]:
    root = Path(session_dir)
    events = [json.loads(l) for l in (root / "events.jsonl").read_text().splitlines() if l.strip()]
    edge_ev = [(e["time"], int(e["code"])) for e in events if e.get("code") is not None]
    with Path(external_csv).open(newline="") as f:
        rows = list(csv.DictReader(f))
    ext = [(float(r["time"]), int(float(r["code"]))) for r in rows if r.get("code") not in (None, "", "0")]
    pairs = match_sequences(ext, edge_ev, tolerance)
    if len(pairs) < 2:
        raise ValueError("could not match enough events between the external file and the session")
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
              "usage": "master_time = offset + slope * external_time"}
    (root / "alignment.json").write_text(json.dumps(result, indent=2))
    return result
