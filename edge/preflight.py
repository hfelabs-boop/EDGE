"""Preflight: can I start collecting data? One go / no-go before the first participant.

``edge preflight study.yaml`` (and **Run with a participant** in the builder) runs, in order:

1. **Experiment**: every check of ``edge validate`` (names, files, frames, measures, devices …)
2. **Software**: the Python packages the experiment's devices and window need are installed
3. **Test run**: a virtual participant does the whole experiment with simulated hardware; any error,
   timing problem or measure that is never recorded shows up here, not with participant 37
4. **Measures**: what the experiment measures is declared
5. **Lock**: the experiment, its files and this computer still match what was piloted
6. **Computer**: power, display driver, monitors, USB, serial latency … (``edge doctor``)

The verdict is **go**, **go with warnings** or **no-go**. It is saved next to the experiment
(``<name>.preflight.json``), and every real session records the last verdict in ``session.json``.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PIP_NAMES = {"tobii_research": "tobii-research", "serial": "pyserial", "u3": "LabJackPython", "u6": "LabJackPython",
             "pylsl": "pylsl", "sounddevice": "sounddevice", "numpy": "numpy", "pygds": "pygds (from g.tec's g.NEEDaccess SDK)"}
ORDER = {"error": 0, "warning": 1, "info": 2, "ok": 3}


def preflight_path(exp_path: str | Path) -> Path:
    p = Path(exp_path)
    return p.with_name(p.stem + ".preflight.json")


def _section(sid: str, title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    items = sorted(items, key=lambda i: ORDER.get(i["level"], 9))
    worst = items[0]["level"] if items else "ok"
    return {"id": sid, "title": title, "status": worst, "items": items}


def _item(level: str, text: str, hint: str = "", **kw: Any) -> dict[str, Any]:
    return {"level": level, "text": text, "hint": hint, **kw}


def software_items(exp) -> list[dict[str, Any]]:
    from importlib.util import find_spec
    from .devices import device_registry
    reg = device_registry()
    items = []
    if find_spec("pyglet") is None:
        items.append(_item("error", "the window library (pyglet) is not installed", 'pip install "edge-experiments[display]"'))
    for d in exp.devices:
        cls = reg.get(d.type)
        if cls is None:
            continue
        ok, why = cls.available()
        if not ok:
            pkg = " ".join(PIP_NAMES.get(r, r) for r in cls.requires) or d.type
            items.append(_item("error" if d.required else "warning",
                               f"device '{d.id}' ({d.type}) can't be used here: {why or 'missing ' + pkg}",
                               f"pip install {pkg}  (see Devices in the docs)" + ("" if d.required else "; it is optional, so the session would run without it")))
    if not items:
        items.append(_item("ok", "everything the window and devices need is installed"))
    return items


def run_preflight(path: str | Path, golden: bool = True, computer: bool = True, save: bool = True) -> dict[str, Any]:
    from .model import Experiment
    t0 = time.monotonic()
    p = Path(path)
    exp = Experiment.load(p)
    sections = []

    issues = exp.validate()
    items = [_item(i.level, f"{i.where}: {i.message}", i.hint) for i in issues if i.level in ("error", "warning")]
    n_info = sum(i.level == "info" for i in issues)
    if not items:
        items.append(_item("ok", "no problems found" + (f" ({n_info} note{'s' if n_info > 1 else ''})" if n_info else "")))
    sections.append(_section("experiment", "Experiment", items))
    errors = any(i.level == "error" for i in issues)

    sections.append(_section("software", "Software", software_items(exp)))

    if errors:
        sections.append(_section("test_run", "Test run", [_item("info", "skipped until the experiment's errors are fixed")]))
    else:
        sections.append(_section("test_run", "Test run (virtual participant)", test_run_items(exp)))

    from .measures import declared
    ms = declared({"measures": exp.measures})
    if not ms:
        sections.append(_section("measures", "Measures", [_item(
            "warning", "nothing is declared as what this experiment measures",
            "say which columns are your outcomes and factors (Measures & data): they are summarised, shown live and checked")]))
    else:
        sections.append(_section("measures", "Measures", [_item("ok", f"{len(ms)} declared: " +
                                                                ", ".join(m.get("label") or m["id"] for m in ms))]))

    from .reproduce import verify
    v = verify(p, golden=golden)
    if not v["locked"]:
        sections.append(_section("lock", "Lock", [_item("info", "not locked yet",
                                                        "after piloting, lock it (edge lock / Lock in the builder): later "
                                                        "updates or edited files are then caught here")]))
    else:
        sections.append(_section("lock", "Lock", [_item(f["level"], f["what"], f.get("detail", "")) for f in v["findings"]]))

    if computer:
        from .syscheck import run_checks
        checks = run_checks(exp)
        items = [_item(c.level, c.title, c.fix, detail=c.detail, fixable=c.fixable, check_id=c.id)
                 for c in checks if c.level != "ok"]
        if not items:
            items.append(_item("ok", "nothing on this computer that would affect timing"))
        sections.append(_section("computer", "Computer", items))

    worst = min((ORDER[s["status"]] for s in sections), default=3)
    verdict = "no-go" if worst == 0 else "go with warnings" if worst == 1 else "go"
    res = {"verdict": verdict, "experiment": exp.name, "time": datetime.now().isoformat(timespec="seconds"),
           "seconds": round(time.monotonic() - t0, 1), "sections": sections}
    if save:
        from .reproduce import experiment_hash
        from .storage import load_document
        res["experiment_sha256"] = experiment_hash(load_document(p).doc)
        preflight_path(p).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return res


def test_run_items(exp) -> list[dict[str, Any]]:
    import tempfile
    from .engine import run_experiment
    from .report import analyze_session
    items = []
    with tempfile.TemporaryDirectory() as td:
        try:
            s = run_experiment(exp, dry_run=True, data_dir=td, log=lambda *a: None)
        except Exception as e:
            rep = getattr(e, "report", None)
            from .diagnostics import summary_line
            return [_item("error", "the test run stopped: " + (summary_line(rep) if rep else f"{type(e).__name__}: {e}"),
                          (rep or {}).get("hint", ""), crash=rep)]
        rep = analyze_session(s["data_dir"])
        n = None
        try:
            from .export import SessionTables, wide_trials
            n = sum(1 for r in wide_trials(SessionTables(s["data_dir"]))[1] if r.get("loop"))
        except Exception:
            pass
    items.append(_item("ok", f"a virtual participant finished the whole experiment" + (f" ({n} trials)" if n else "")))
    for v in rep.get("verdict", []):
        if v.startswith("WARNING"):
            items.append(_item("warning", v.removeprefix("WARNING: ")))
    for m in (rep.get("measures") or {}).get("values", []):
        if m.get("value") is None and m.get("role") != "factor":
            items.append(_item("warning", f"measure {m['label']} got no value in the test run",
                               "check its column and its trials filter"))
    return items


def last_preflight(exp_path: str | Path, doc: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The saved verdict, if it was made for exactly this version of the experiment."""
    pf = preflight_path(exp_path)
    if not pf.exists():
        return None
    try:
        res = json.loads(pf.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if doc is not None:
        from .reproduce import experiment_hash
        if res.get("experiment_sha256") != experiment_hash(doc):
            return {"verdict": "outdated", "time": res.get("time"), "note": "the experiment changed after this preflight"}
    return {"verdict": res.get("verdict"), "time": res.get("time")}


def format_preflight(res: dict[str, Any]) -> str:
    mark = {"ok": "✓", "info": "·", "warning": "!", "error": "✗"}
    lines = [f"Preflight for {res['experiment']} ({res['seconds']} s)", ""]
    for s in res["sections"]:
        lines.append(f"{mark[s['status']]} {s['title']}")
        all_ok = all(it["level"] == "ok" for it in s["items"])
        for i, it in enumerate(s["items"]):
            if it["level"] == "ok" and not (all_ok and i == 0):
                continue
            lines.append(f"    {mark[it['level']]} {it['text']}")
            if it.get("hint") and it["level"] != "ok":
                lines.append(f"        → {it['hint']}")
    word = {"go": "GO: ready for participants", "go with warnings": "GO WITH WARNINGS: read the ! items first",
            "no-go": "NO-GO: fix the ✗ items before running participants"}[res["verdict"]]
    lines += ["", word]
    return "\n".join(lines)
