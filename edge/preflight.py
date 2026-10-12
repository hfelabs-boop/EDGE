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

from .syscheck import PIP_NAMES  # noqa: E402,F401  (kept importable from here)

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
    """The same check as ``edge doctor``'s software check (syscheck.check_software), as preflight items."""
    from .syscheck import check_software
    items = []
    for c in check_software(exp):
        text = c.title[:1].lower() + c.title[1:]
        hint = c.fix + ("; it is optional, so the session would run without it" if c.level == "warning" else "")
        items.append(_item(c.level, text, hint if c.level != "ok" else ""))
    return items


def measures_hint(exp) -> str:
    """How to declare measures, with this experiment's own columns, for people working in the YAML file."""
    try:
        from .measures import recording_plan, suggest_measures
        sugg = suggest_measures(exp, recording_plan(exp))[:2]
    except Exception:
        sugg = []
    keys = ("id", "column", "role", "summary")
    if sugg:
        example = ", ".join("{" + ", ".join(f"{k}: {m[k]}" for k in keys if m.get(k) is not None) + "}" for m in sugg)
    else:
        example = "{id: rt, column: resp.rt, role: outcome, summary: median}"
    return ("say which recorded columns are your outcomes and factors, so they are summarised per participant, shown "
            f"live and checked: in the experiment file add  measures: [{example}]  (edge help --first measures "
            "explains it), or use Measures & data in the builder")


def device_items(exp, timeout: float = 6.0) -> list[dict[str, Any]]:
    """Connect each device briefly, as the session will: is it switched on and reachable right now?"""
    from concurrent.futures import ThreadPoolExecutor
    from .devtest import SIMULATORS, test_device

    def one(d) -> dict[str, Any]:
        if d.type in SIMULATORS:
            return _item("warning", f"device '{d.id}' is EDGE's simulator ({d.type}), not real hardware: "
                                    "its data would be made up",
                         "replace it with your device's driver (edge devices lists them) before running participants")
        try:
            r = test_device(d.type, d.id, dict(d.options), seconds=0.3, connect_timeout=timeout, marker=False)
        except Exception as e:     # a broken driver must not stop the preflight
            r = {"connected": False, "error": f"{type(e).__name__}: {e}"}
        if r.get("connected"):
            return _item("ok", f"device '{d.id}' ({d.type}) answers")
        why = r.get("error") or "it did not answer"
        if d.required:
            return _item("error", f"device '{d.id}' ({d.type}) is not reachable: {why}",
                         "switch it on, check its cable/port/address (edge test-device shows the details); "
                         "the session can't start without it" + (f". {r['hint']}" if r.get("hint") else ""))
        return _item("warning", f"device '{d.id}' ({d.type}) is not reachable: {why}",
                     "it is optional, so the session would run WITHOUT recording it: switch it on and check its "
                     "cable/port/address (edge test-device shows the details)" + (f". {r['hint']}" if r.get("hint") else ""))

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(exp.devices)))) as pool:
        items = list(pool.map(one, exp.devices))
    return items


def run_preflight(path: str | Path, golden: bool = True, computer: bool = True, save: bool = True,
                  devices: bool | None = None) -> dict[str, Any]:
    """``devices`` (default: the same as ``computer``): briefly connect every device of the experiment."""
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
            "warning", "nothing is declared as what this experiment measures", measures_hint(exp))]))
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

    if devices is None:
        devices = computer
    if devices and exp.devices:
        sections.append(_section("devices", "Devices (connected now?)", device_items(exp)))

    if computer:
        from .syscheck import run_checks
        checks = run_checks(exp, software=False)        # the software is its own section above
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
        n = rep.get("trials")        # loop iterations, counted as everywhere else
    items.append(_item("ok", f"a virtual participant finished the whole experiment" + (f" ({n} trials)" if n else "")))
    for v in rep.get("verdict", []):
        if v.startswith(("WARNING", "ERROR")):
            items.append(_item("warning", v.removeprefix("WARNING: ").removeprefix("ERROR: ")))
    unstable = _unplanned_trigger_codes(exp, s.get("marker_codebook") or {})
    if unstable:
        shown = ", ".join(unstable[:4]) + (" …" if len(unstable) > 4 else "")
        example = ", ".join(f"{lab}: {s['marker_codebook'][lab]}" for lab in unstable[:3])
        items.append(_item("warning", f"the trigger codes of {shown} are given in the order they first happen, so "
                                      "the same event can get a different code for different participants",
                           f"fix them in the experiment file: settings: {{markers: {{codes: {{{example}}}}}}} "
                           "(marker_codebook in session.json lists all of them)"))
    for m in (rep.get("measures") or {}).get("values", []):
        if m.get("value") is None and m.get("role") != "factor":
            items.append(_item("warning", f"measure {m['label']} got no value in the test run",
                               "check its column and its trials filter"))
    return items


def _unplanned_trigger_codes(exp, codebook: dict[str, int]) -> list[str]:
    """Marker labels sent in the test run whose code isn't fixed before the session (they depend on a response,
    a variable …), in an experiment that sends codes to a trigger/EEG/physiology device."""
    from .devices import device_registry
    from .runtime import planned_marker_labels
    reg = device_registry()
    if not any(d.markers and "markers" in getattr(reg.get(d.type), "capabilities", ()) for d in exp.devices):
        return []
    fixed = set(((exp.settings.get("markers") or {}).get("codes") or {})) | set(planned_marker_labels(exp))
    return sorted(lab for lab in codebook if lab not in fixed)


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
