"""EDGE MCP server: build, run and analyze experiments in natural language.

Connect it to Claude Code, Claude Desktop or VS Code (Copilot agent mode / any MCP
client) and ask things like *"make a Stroop task with 3 blocks, Gazepoint eye tracking
and LSL markers, then dry-run it"*. The client's model turns the request into calls
to the tools below; every edit is validated, saved atomically with a backup (so
``undo`` always works) and appears live in an open EDGE builder.

    edge mcp --root /path/to/experiments        # stdio transport (default)

All paths are relative to the workspace root and cannot escape it.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from . import __version__
from .editing import EditError, ExperimentDoc
from .storage import (ConflictError, DocumentError, dumps, export_bundle, fingerprint, import_bundle,
                      list_backups, loads, restore_backup, save_document)

INSTRUCTIONS = """\
EDGE builds and runs behavioral / eye-tracking / EEG / physiology experiments.
An experiment is a YAML document: settings, devices, routines (screens/events made of
components with timing) and a flow (sequence of routines, loops over condition tables,
if/else branches). String values starting with $ are expressions (e.g. "$word",
"$f'Score: {score}'", "$resp.corr == 1").

Recommended workflow:
1. list_experiments / describe_experiment to see what exists (or create_experiment).
2. Use list_component_types / list_device_types to learn valid properties.
3. Edit with the specific tools, or edit_experiment to apply many operations at once.
   Each edit returns validation issues; fix errors before running.
4. dry_run to test the whole experiment with simulated devices and a virtual participant;
   read the verdict and the data preview.
5. After real sessions: list_sessions, analyze_session, export_data.
Edits are saved immediately with backups; use undo if something went wrong.
Timing is in seconds; routine t=0 is its first screen flip. A routine needs something that ends it
(a duration, an end_routine response, or end_if).
"""


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.builder_url: str | None = None
        self.runs: dict[str, subprocess.Popen] = {}

    def path(self, rel: str, must_exist: bool = True) -> Path:
        if not rel:
            raise EditError("a path is required")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise EditError(f"'{rel}' is outside the workspace ({self.root})")
        if must_exist and not p.exists():
            raise EditError(f"'{rel}' does not exist in {self.root}")
        return p

    def rel(self, p: Path) -> str:
        try:
            return str(Path(p).resolve().relative_to(self.root))
        except ValueError:
            return str(p)


def _issues(doc: ExperimentDoc) -> dict[str, Any]:
    issues = doc.validate()
    errors = [f"{i['where']}: {i['message']}" + (f" ({i['hint']})" if i.get("hint") else "")
              for i in issues if i["level"] == "error"]
    warnings = [f"{i['where']}: {i['message']}" for i in issues if i["level"] == "warning"]
    return {"errors": errors, "warnings": warnings, "valid": not errors}


def create_server(root: str | Path = ".") -> FastMCP:
    ws = Workspace(Path(root))
    mcp = FastMCP("edge", instructions=INSTRUCTIONS)

    def tool(fn: Callable) -> Callable:
        """Register a tool; keep stdout clean (stdio transport) and turn errors into messages."""
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with contextlib.redirect_stdout(sys.stderr):
                try:
                    return fn(*args, **kwargs)
                except (EditError, DocumentError, ConflictError, FileNotFoundError, ValueError) as e:
                    return {"ok": False, "error": str(e)}
                except Exception as e:  # unexpected: give the model enough to report it
                    return {"ok": False, "error": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc(limit=3)}
        return mcp.tool()(wrapper)

    def edit(path: str, fn: Callable[[ExperimentDoc], Any], label: str) -> dict[str, Any]:
        doc = ExperimentDoc.open(ws.path(path))
        result = fn(doc)
        doc.save(label)
        out: dict[str, Any] = {"ok": True, "changes": doc.changes, **_issues(doc)}
        if result is not None and not isinstance(result, ExperimentDoc):
            out["result"] = result
        return out

    # ================================================================ discovery
    @tool
    def list_experiments(directory: str = ".") -> dict[str, Any]:
        """List EDGE experiment files (YAML/JSON) in the workspace (or a sub-directory)."""
        base = ws.path(directory)
        found = []
        for p in sorted(base.rglob("*")):
            parts = p.relative_to(ws.root).parts
            if p.suffix.lower() not in (".yaml", ".yml", ".json") or any(x.startswith(".") for x in parts) \
                    or "data" in parts[:-1] or (p.parent / "session.json").exists():
                continue
            try:
                d = loads(p.read_text(encoding="utf-8"), "json" if p.suffix == ".json" else "yaml")
            except Exception:
                continue
            if "routines" in d or "flow" in d:
                found.append({"path": ws.rel(p), "name": d.get("name"), "description": d.get("description", ""),
                              "routines": len(d.get("routines") or {}), "devices": [x.get("type") for x in d.get("devices") or []]})
        return {"workspace": str(ws.root), "experiments": found}

    @tool
    def list_component_types(type: str = "", category: str = "") -> dict[str, Any]:
        """List component types (stimulus, response, eyetracking, hardware, logic) or show every property
        of one type. Scheduling properties available on all components: start, duration, start_after,
        start_if, stop_if, start_frame, duration_frames, end_routine, disabled, save, marker."""
        from .components import component_registry
        reg = component_registry()
        if type:
            if type not in reg:
                raise EditError(f"unknown component type '{type}'; available: {', '.join(sorted(reg))}")
            return reg[type].describe()
        return {"components": [{"type": k, "category": v.category, "description": v.description}
                               for k, v in sorted(reg.items(), key=lambda kv: (kv[1].category, kv[0]))
                               if not category or v.category == category]}

    @tool
    def list_device_types(type: str = "") -> dict[str, Any]:
        """List hardware drivers (eye trackers, EEG, physiology, LSL, TTL, simulators) or show the options of one."""
        from .devices import device_registry
        reg = device_registry()
        if type:
            if type not in reg:
                raise EditError(f"unknown device type '{type}'; available: {', '.join(sorted(reg))}")
            return reg[type].describe()
        return {"devices": [{"type": k, "capabilities": sorted(v.capabilities), "description": v.description,
                             "available_here": v.available()[0]} for k, v in sorted(reg.items())]}

    @tool
    def list_templates() -> dict[str, Any]:
        """Starter experiments that create_experiment can copy."""
        from .templates import public_templates
        return {k: v.get("description", v["name"]) for k, v in public_templates().items()}

    # ================================================================ whole documents
    @tool
    def create_experiment(path: str, name: str = "", template: str = "", description: str = "") -> dict[str, Any]:
        """Create a new experiment file (e.g. path='stroop/stroop.yaml'), empty or from a template
        (blank, freeview_eyetracking, eeg_oddball, staircase)."""
        p = ws.path(path, must_exist=False)
        doc = ExperimentDoc.new(p, name=name or None, template=template or None, description=description)
        doc.save("created")
        return {"ok": True, "path": ws.rel(p), "changes": doc.changes, "outline": doc.outline(), **_issues(doc)}

    @tool
    def describe_experiment(path: str) -> dict[str, Any]:
        """Readable outline of an experiment (devices, flow tree, routines with component timing) plus
        validation issues. Call this before editing."""
        doc = ExperimentDoc.open(ws.path(path))
        return {"outline": doc.outline(), **_issues(doc), "migrated": doc.changes}

    @tool
    def get_experiment_source(path: str) -> dict[str, Any]:
        """Full YAML source of an experiment (for detailed inspection or a complete rewrite)."""
        p = ws.path(path)
        doc = ExperimentDoc.open(p)
        return {"yaml": dumps(doc.doc), "fingerprint": fingerprint(p)}

    @tool
    def replace_experiment_source(path: str, yaml_text: str) -> dict[str, Any]:
        """Replace the whole experiment with new YAML (validated; the old version is backed up)."""
        p = ws.path(path, must_exist=False)
        data = loads(yaml_text, "yaml", path)
        doc = ExperimentDoc(data, p)
        save_document(p, doc.doc, label="replaced source")
        return {"ok": True, "outline": doc.outline(), **_issues(doc)}

    @tool
    def edit_experiment(path: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply several edits at once, all-or-nothing. Each operation is {"op": <name>, ...arguments}.
        Ops and their arguments:
          add_routine(rid, description, duration, end_if, add_to_flow, parent, position)
          update_routine(rid, duration, end_if, description) · rename_routine(old, new) · remove_routine(rid)
          duplicate_routine(rid, new)
          add_component(rid, ctype, properties, cid, position) · update_component(rid, cid, set_props, unset, new_id)
          remove_component(rid, cid) · move_component(rid, cid, position)
          insert_flow(item, parent, position, branch) · remove_from_flow(name, occurrence, keep_children)
          move_in_flow(name, position, parent)
          add_loop(lid, children, conditions, order, repeats, max_repeat, stop_if, staircase, parent, position, wrap)
          update_loop(lid, changes) · set_conditions(lid, rows, file, factorial, write_file)
          add_branch(condition, then, otherwise, parent, position)
          add_device(dtype, did, options, required, record, markers, calibrate) · update_device(did, options, ...)
          remove_device(did) · update_settings(patch) · set_variables(values, replace) · set_info(name, description)
          add_state_machine(mid, states, start, parent, position, max_steps)
          update_state(mid, state, run, next, max_visits, description, rename_to, make_start) · remove_state(mid, state)
          add_rule(rid, when, do, repeat, name) · remove_rule(rid, index)
        Example: [{"op":"add_routine","rid":"trial"},{"op":"add_component","rid":"trial","ctype":"text",
                   "properties":{"text":"$word","duration":1}}]"""
        allowed = {"add_routine", "update_routine", "rename_routine", "remove_routine", "duplicate_routine",
                   "add_component", "update_component", "remove_component", "move_component", "insert_flow",
                   "remove_from_flow", "move_in_flow", "add_loop", "update_loop", "set_conditions", "add_branch",
                   "add_device", "update_device", "remove_device", "update_settings", "set_variables", "set_info",
                   "add_state_machine", "update_state", "remove_state", "add_rule", "remove_rule"}
        p = ws.path(path)
        doc = ExperimentDoc.open(p)
        snapshot = copy.deepcopy(doc.doc)
        results = []
        for i, op in enumerate(operations):
            args = dict(op)
            name = args.pop("op", None)
            if name not in allowed:
                return {"ok": False, "error": f"operation {i}: unknown op '{name}'", "allowed": sorted(allowed)}
            try:
                results.append(getattr(doc, name)(**args))
            except TypeError as e:
                doc.doc = snapshot
                return {"ok": False, "error": f"operation {i} ({name}): bad arguments: {e}", "applied": 0}
            except EditError as e:
                doc.doc = snapshot
                return {"ok": False, "error": f"operation {i} ({name}): {e}", "applied": 0}
        doc.save(f"{len(operations)} edits")
        return {"ok": True, "applied": len(operations), "changes": doc.changes,
                "results": [r for r in results if r is not None], **_issues(doc)}

    # ================================================================ routines & components
    @tool
    def add_routine(path: str, routine: str, description: str = "", duration: float | str | None = None,
                    end_if: str = "", add_to_flow: bool = True, loop: str = "",
                    position: int | None = None) -> dict[str, Any]:
        """Add a routine (a trial screen, instructions, feedback ...). By default it is also appended to the
        flow (or to `loop` if given). Then add components to it."""
        return edit(path, lambda d: d.add_routine(routine, description, duration, end_if or None, add_to_flow,
                                                  loop or None, position), f"add routine {routine}")

    @tool
    def update_routine(path: str, routine: str, duration: float | str | None = None, end_if: str | None = None,
                       description: str | None = None, rename_to: str = "", clear_duration: bool = False) -> dict[str, Any]:
        """Change a routine's duration cap, end_if expression, description, or name."""
        def op(d: ExperimentDoc) -> None:
            d.update_routine(routine,
                             duration=None if clear_duration else (duration if duration is not None else "__keep__"),
                             end_if=end_if if end_if is not None else "__keep__",
                             description=description if description is not None else "__keep__")
            if rename_to:
                d.rename_routine(routine, rename_to)
        return edit(path, op, f"update routine {routine}")

    @tool
    def remove_routine(path: str, routine: str) -> dict[str, Any]:
        """Delete a routine and every reference to it in the flow."""
        return edit(path, lambda d: d.remove_routine(routine), f"remove routine {routine}")

    @tool
    def add_component(path: str, routine: str, type: str, properties: dict[str, Any] | None = None,
                      id: str = "", position: int | None = None) -> dict[str, Any]:
        """Add a component to a routine. `properties` holds both component properties and timing,
        e.g. type='text', properties={"text": "$word", "color": "$ink", "start": 0.5, "duration": 1,
        "marker": "word_onset"}; type='keyboard', properties={"keys": ["f","j"], "correct": "$answer",
        "end_routine": true}. Later components draw on top."""
        return edit(path, lambda d: d.add_component(routine, type, properties, id or None, position),
                    f"add {type} to {routine}")

    @tool
    def update_component(path: str, routine: str, id: str, properties: dict[str, Any] | None = None,
                         remove: list[str] | None = None, rename_to: str = "") -> dict[str, Any]:
        """Change component properties/timing (null value = remove), remove properties, or rename it."""
        return edit(path, lambda d: d.update_component(routine, id, properties, remove, rename_to or None),
                    f"update {routine}.{id}")

    @tool
    def remove_component(path: str, routine: str, id: str) -> dict[str, Any]:
        """Delete a component from a routine."""
        return edit(path, lambda d: d.remove_component(routine, id), f"remove {routine}.{id}")

    @tool
    def move_component(path: str, routine: str, id: str, position: int) -> dict[str, Any]:
        """Change a component's position (= drawing order; 0 is drawn first / at the back)."""
        return edit(path, lambda d: d.move_component(routine, id, position), f"move {routine}.{id}")

    # ================================================================ flow
    @tool
    def add_loop(path: str, loop: str, children: list[str], conditions: Any = None, order: str = "sequential",
                 repeats: int | str = 1, max_repeat: dict[str, Any] | None = None, stop_if: str = "",
                 staircase: dict[str, Any] | None = None, wrap_existing: bool = False, parent: str = "",
                 position: int | None = None) -> dict[str, Any]:
        """Add a loop that repeats `children` (routine names) once per condition row.
        conditions: list of row dicts, a file name ('trials.csv'), or {"factorial": {"color": [...], ...}}.
        order: sequential | random | fullrandom | latin_square | counterbalance.
        max_repeat: e.g. {"color": 2} or {"kind": {"deviant": 1}}.
        staircase: {"variable","start","step","down","up","min","max","reversals","max_trials","correct"}.
        wrap_existing=true moves routines that are already in the flow into the loop."""
        return edit(path, lambda d: d.add_loop(loop, children, conditions, order, repeats, max_repeat,
                                               stop_if or None, staircase, parent or None, position, wrap_existing),
                    f"add loop {loop}")

    @tool
    def update_loop(path: str, loop: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Change loop settings: conditions, order, repeats, max_repeat, stop_if, staircase, select, id."""
        return edit(path, lambda d: d.update_loop(loop, changes), f"update loop {loop}")

    @tool
    def set_conditions(path: str, loop: str, rows: list[dict[str, Any]] | None = None, file: str = "",
                       factorial: dict[str, list[Any]] | None = None, write_file: bool = False) -> dict[str, Any]:
        """Set a loop's trial list. rows = [{"word": "RED", "ink": "blue", "answer": "b"}, ...];
        with write_file=true and file='stroop.csv' the rows are saved as a CSV next to the experiment
        (editable in Excel). Or reference an existing file, or give a factorial design."""
        return edit(path, lambda d: d.set_conditions(loop, rows, file or None, factorial, write_file),
                    f"conditions {loop}")

    @tool
    def add_branch(path: str, condition: str, then: list[str], otherwise: list[str] | None = None,
                   parent: str = "", position: int | None = None) -> dict[str, Any]:
        """Add an if/else to the flow, e.g. condition='$practice.n_correct >= 8', then=['main_block'],
        otherwise=['more_practice']."""
        return edit(path, lambda d: d.add_branch(condition, then, otherwise, parent or None, position), "add branch")

    @tool
    def modify_flow(path: str, action: str, name: str, parent: str = "", position: int | None = None,
                    keep_children: bool = True) -> dict[str, Any]:
        """Edit the flow: action='insert' adds routine `name` (at `position`, inside loop `parent`);
        'remove' takes a routine/loop out of the flow (routine definitions stay; a removed loop's children
        stay unless keep_children=false); 'move' repositions it."""
        def op(d: ExperimentDoc) -> None:
            if action == "insert":
                d.insert_flow(name, parent or None, position)
            elif action == "remove":
                d.remove_from_flow(name, keep_children=keep_children)
            elif action == "move":
                d.move_in_flow(name, position if position is not None else 10**6, parent or None)
            else:
                raise EditError("action must be insert, remove or move")
        return edit(path, op, f"flow {action} {name}")

    @tool
    def add_workflow(path: str, workflow: str, states: dict[str, Any], start: str = "", parent: str = "",
                     position: int | None = None) -> dict[str, Any]:
        """Add a state machine (workflow) to the flow for if/else logic between blocks, repeat-until-criterion,
        adaptive paths, screening. states = {"practice": {"run": ["prac_loop_or_routine"], "max_visits": 3,
        "next": [{"if": "$practice.accuracy >= 0.8", "goto": "main"}, {"goto": "practice"}]},
        "main": {"run": ["main_block"], "next": ["end"]}}. Routes are checked in order; one without "if" is the
        default; "end" finishes. Routines/loops already in the flow are moved into the state. Loop results usable in
        conditions: $loopid.accuracy, .n_correct, .mean_rt, .total; workflow: $workflow.state, $workflow.visit."""
        return edit(path, lambda d: d.add_state_machine(workflow, states, start or None, parent or None, position),
                    f"add workflow {workflow}")

    @tool
    def update_workflow_state(path: str, workflow: str, state: str, run: list[Any] | None = None,
                              routes: list[Any] | None = None, max_visits: int | None = None, rename_to: str = "",
                              make_start: bool = False, remove: bool = False) -> dict[str, Any]:
        """Add or change one state of a workflow: its contents (`run`), its `routes` ([{"if": ..., "goto": ...,
        "set": {...}}, ...]), max_visits, name, or make it the start state; remove=true deletes it."""
        def op(d: ExperimentDoc) -> None:
            if remove:
                d.remove_state(workflow, state)
            else:
                d.update_state(workflow, state, run, routes, max_visits if max_visits is not None else "__keep__",
                               None, rename_to or None, make_start)
        return edit(path, op, f"workflow {workflow}.{state}")

    @tool
    def add_routine_rule(path: str, routine: str, when: str, do: list[Any], repeat: bool = False,
                         name: str = "") -> dict[str, Any]:
        """Add a "when → do" rule to a routine, checked every frame. when: expression ("$t > 3",
        "$resp.keys == 'q'", "$roi.completed"). do: [{"end_routine": true}, {"start": "hint"}, {"stop": "stim"},
        {"set": {"score": "$score + 1"}}, {"marker": "hint_shown"}, {"goto": "debrief"}]. repeat=true lets it
        fire again each time the condition becomes true."""
        return edit(path, lambda d: d.add_rule(routine, when, do, repeat, name or None), f"rule in {routine}")

    @tool
    def import_experiment(source: str, out_dir: str = "", platform: str = "") -> dict[str, Any]:
        """Import a PsychoPy (.psyexp), E-Prime (generated .ebs3/.ebs2 script, plus List .txt exports next to it),
        OpenSesame (.osexp/.opensesame) or jsPsych (.html/.js) experiment from the workspace. Returns the new EDGE
        experiment path, what was converted, and items that need manual work. Follow with dry_run."""
        from .importers import ImportError_, import_experiment as do_import
        try:
            path, res = do_import(ws.path(source), ws.path(out_dir, must_exist=False) if out_dir else None,
                                  platform or None)
        except ImportError_ as e:
            raise EditError(str(e)) from None
        doc = ExperimentDoc.open(path)
        return {"ok": True, "path": ws.rel(path), "platform": res.platform, "converted": res.stats,
                "needs_manual_work": [f"{n['where']}: {n['message'][:300]}" for n in res.notes if n["level"] == "unsupported"],
                "approximate": [f"{n['where']}: {n['message'][:200]}" for n in res.notes if n["level"] == "approx"],
                "report": ws.rel(path.parent / "IMPORT_REPORT.md"), "outline": doc.outline(), **_issues(doc)}

    # ================================================================ devices & settings
    @tool
    def add_device(path: str, type: str, id: str = "", options: dict[str, Any] | None = None,
                   required: bool | None = None, calibrate: bool | None = None,
                   markers: bool | None = None) -> dict[str, Any]:
        """Add hardware: tobii, gazepoint, gtec, mindware, lsl_markers, lsl_inlet, ttl_serial, parallel_port,
        or simulators (sim_eyetracker, sim_eeg, sim_physio, mouse_gaze). See list_device_types(type) for options."""
        return edit(path, lambda d: d.add_device(type, id or None, options, required, None, markers, calibrate),
                    f"add device {type}")

    @tool
    def update_device(path: str, id: str, options: dict[str, Any] | None = None, required: bool | None = None,
                      calibrate: bool | None = None, markers: bool | None = None, record: bool | None = None) -> dict[str, Any]:
        """Change a device's options or flags."""
        return edit(path, lambda d: d.update_device(id, options, required=required, calibrate=calibrate,
                                                    markers=markers, record=record), f"update device {id}")

    @tool
    def remove_device(path: str, id: str) -> dict[str, Any]:
        """Remove a device from the experiment."""
        return edit(path, lambda d: d.remove_device(id), f"remove device {id}")

    @tool
    def update_settings(path: str, settings: dict[str, Any] | None = None, variables: dict[str, Any] | None = None,
                        name: str = "", description: str | None = None) -> dict[str, Any]:
        """Change settings (deep-merged; null removes a key), e.g. {"window": {"fullscreen": true,
        "background": "#808080", "units": "deg"}, "data": {"exports": ["csv", "xlsx", "bids"]},
        "markers": {"codes": {"stim": 10}}, "participant": {"participant": "001", "group": "A"}};
        set initial experiment variables; rename or describe the experiment."""
        def op(d: ExperimentDoc) -> None:
            if settings:
                d.update_settings(settings)
            if variables:
                d.set_variables(variables)
            if name or description is not None:
                d.set_info(name or None, description)
        return edit(path, op, "settings")

    # ================================================================ checking & running
    @tool
    def validate_experiment(path: str) -> dict[str, Any]:
        """Check an experiment for errors and warnings without running it."""
        return _issues(ExperimentDoc.open(ws.path(path)))

    @tool
    def dry_run(path: str, participant: str = "", accuracy: float = 0.9) -> dict[str, Any]:
        """Run the whole experiment headless in seconds: hardware replaced by simulators on drifting clocks,
        a virtual participant responding (ex-Gaussian RTs, given accuracy). Returns the quality verdict,
        timing, per-device sync results, the summary table and a preview of the trial data."""
        from .engine import run_experiment
        from .export import SessionTables, summarize, wide_trials
        from .model import Experiment
        from .participant import VirtualParticipant
        from .report import analyze_session

        p = ws.path(path)
        exp = Experiment.load(p)
        errors = [str(i) for i in exp.validate() if i.level == "error"]
        if errors:
            return {"ok": False, "errors": errors}
        logs: list[str] = []
        summary = run_experiment(exp, dry_run=True, participant={"participant": participant} if participant else None,
                                 data_dir=str(p.parent / "data" / "dry_runs"),
                                 virtual_participant=VirtualParticipant(accuracy=accuracy),
                                 log=lambda *a: logs.append(" ".join(map(str, a))))
        rep = analyze_session(summary["data_dir"])
        st = SessionTables(summary["data_dir"])
        cols, rows = wide_trials(st)
        scols, srows, info = summarize(st)
        t = summary.get("timing", {})
        return {"ok": True, "verdict": rep["verdict"], "data_dir": ws.rel(Path(summary["data_dir"])),
                "session_minutes": round(t.get("frames", 0) / max(t.get("refresh_rate_hz") or 60, 1) / 60, 2),
                "trials": len(rows), "errors": summary["errors"],
                "streams": {k: {"samples": v["samples"], "triggers": v.get("triggers")} for k, v in rep["streams"].items()},
                "summary": srows[:20], "summary_detected": info,
                "columns": cols, "first_trials": rows[:5], "log": logs[-10:]}

    @tool
    def run_experiment(path: str, participant: str = "", session: str = "", simulate_devices: bool = False,
                       fields: dict[str, str] | None = None) -> dict[str, Any]:
        """Start a REAL session (opens the experiment window on this computer, uses real hardware unless
        simulate_devices). Only call this when the user explicitly asks to run with a participant."""
        p = ws.path(path)
        cmd = [sys.executable, "-m", "edge", "run", str(p), "--report"]
        if participant:
            cmd += ["-p", participant]
        if session:
            cmd += ["-s", session]
        for k, v in (fields or {}).items():
            cmd += ["-f", f"{k}={v}"]
        if simulate_devices:
            cmd.append("--simulate-devices")
        log = p.parent / "data" / f"run_{participant or 'session'}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(cmd, cwd=str(p.parent), stdout=log.open("w"), stderr=subprocess.STDOUT)
        ws.runs[str(proc.pid)] = proc
        return {"ok": True, "pid": proc.pid, "log": ws.rel(log), "note": "check progress with run_status"}

    @tool
    def run_status(pid: int) -> dict[str, Any]:
        """Status and output of a session started with run_experiment."""
        proc = ws.runs.get(str(pid))
        if proc is None:
            raise EditError("unknown run id")
        args = proc.args if isinstance(proc.args, list) else []
        exp_dir = Path(args[4]).parent if len(args) > 4 else ws.root
        logs = sorted((exp_dir / "data").glob("run_*.log"), key=lambda f: f.stat().st_mtime)
        return {"running": proc.poll() is None, "returncode": proc.returncode,
                "output": logs[-1].read_text()[-4000:] if logs else ""}

    # ================================================================ data
    @tool
    def list_sessions(directory: str = ".", include_dry_runs: bool = False) -> dict[str, Any]:
        """List recorded sessions (data folders) with participant, date, trials and status."""
        from .export import SessionTables, find_sessions, timing_row
        out = []
        for root in find_sessions(ws.path(directory), include_dry_runs):
            try:
                st = SessionTables(root)
                row = timing_row(st)
                row["path"] = ws.rel(root)
                row["routine_runs"] = len(st.rows)
                out.append(row)
            except Exception as e:
                out.append({"path": ws.rel(root), "error": str(e)})
        return {"sessions": out}

    @tool
    def analyze_session(session: str, by: list[str] | None = None, rt: str = "", correct: str = "") -> dict[str, Any]:
        """Quality report (frames, gaps, trigger alignment per device) and a per-condition summary
        (accuracy, RT mean/median/SD on correct trials, outliers removed) for one session folder.
        Optionally choose grouping factors and the rt/correct columns (e.g. rt='resp.rt')."""
        from .export import SessionTables, summarize
        from .report import analyze_session as quality
        root = ws.path(session)
        st = SessionTables(root)
        cols, rows, info = summarize(st, by=by, rt=rt or None, correct=correct or None)
        rep = quality(root)
        return {"verdict": rep["verdict"], "timing": rep["timing"], "streams": rep["streams"],
                "summary_columns": cols, "summary": rows, "detected": info}

    @tool
    def export_data(path: str, formats: list[str] | None = None, layout: str = "wide", out: str = "",
                    include_dry_runs: bool = False) -> dict[str, Any]:
        """Export analysis-ready tables. `path` = one session folder or a data folder (all sessions merged).
        formats: csv, tsv, xlsx (sheets: trials, summary, dictionary, events/sessions), json, jsonl, parquet,
        mat, bids. layout: wide (one row per trial) or long (one row per routine)."""
        from .export import export_many, export_session, find_sessions
        p = ws.path(path)
        fmts = formats or ["csv", "xlsx"]
        out_dir = ws.path(out, must_exist=False) if out else None
        if (p / "session.json").exists():
            files = export_session(p, fmts, out_dir, layout)
            return {"ok": True, "files": [ws.rel(f) for f in files]}
        if not find_sessions(p, include_dry_runs):
            raise EditError(f"no sessions under {path}")
        res = export_many(p, fmts, out_dir, include_dry_runs)
        res["files"] = [ws.rel(Path(f)) for f in res["files"]]
        return {"ok": True, **res}

    # ================================================================ files, history, tools
    @tool
    def undo(path: str, steps: int = 1) -> dict[str, Any]:
        """Undo the last edit(s) to an experiment by restoring automatic backups."""
        p = ws.path(path)
        restored = []
        for _ in range(max(1, steps)):
            try:
                restored.append(restore_backup(p))
            except DocumentError:
                break
        if not restored:
            raise EditError("nothing to undo")
        doc = ExperimentDoc.open(p)
        return {"ok": True, "restored": restored, "outline": doc.outline(), **_issues(doc)}

    @tool
    def list_versions(path: str) -> dict[str, Any]:
        """Saved versions (automatic backups) of an experiment; restore one with restore_version."""
        return {"versions": [{k: v for k, v in b.items() if k != "path"} for b in list_backups(ws.path(path))]}

    @tool
    def restore_version(path: str, version_id: str) -> dict[str, Any]:
        """Restore a specific saved version (the current one is backed up first)."""
        p = ws.path(path)
        restore_backup(p, version_id)
        return {"ok": True, **_issues(ExperimentDoc.open(p))}

    @tool
    def bundle_experiment(path: str, out: str = "") -> dict[str, Any]:
        """Pack an experiment and all files it uses (conditions, images, sounds) into a shareable .edgez file."""
        res = export_bundle(ws.path(path), ws.path(out, must_exist=False) if out else None)
        res["bundle"] = ws.rel(Path(res["bundle"]))
        return {"ok": True, **res}

    @tool
    def import_experiment_bundle(bundle: str, directory: str) -> dict[str, Any]:
        """Unpack a .edgez bundle into a workspace directory."""
        p = import_bundle(ws.path(bundle), ws.path(directory, must_exist=False))
        return {"ok": True, "path": ws.rel(p)}

    @tool
    def write_file(path: str, content: str) -> dict[str, Any]:
        """Write a text file in the workspace (e.g. a conditions CSV or instructions text)."""
        from .storage import atomic_write
        p = ws.path(path, must_exist=False)
        if p.suffix.lower() in (".py", ".sh", ".bat", ".exe", ".ps1"):
            raise EditError("refusing to write executable/script files")
        atomic_write(p, content)
        return {"ok": True, "path": ws.rel(p), "bytes": len(content.encode())}

    @tool
    def scan_hardware(timeout: float = 2.0) -> dict[str, Any]:
        """Find connected hardware: LSL streams, serial ports (trigger boxes), Tobii trackers, Gazepoint Control.
        Each result includes a suggested device configuration for add_device."""
        from .scan import scan_all
        return scan_all(timeout=timeout)

    @tool
    def open_builder(port: int = 8765) -> dict[str, Any]:
        """Start the EDGE visual builder for this workspace and return its URL. Edits made through these
        tools appear live in the builder."""
        if ws.builder_url:
            return {"url": ws.builder_url}
        from http.server import ThreadingHTTPServer
        from .builder.server import BuilderApp, make_handler
        httpd = None
        for candidate in range(port, port + 20):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", candidate), make_handler(BuilderApp(ws.root)))
                break
            except OSError:
                continue
        if httpd is None:
            raise EditError("no free port for the builder")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        ws.builder_url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        return {"url": ws.builder_url}

    # ================================================================ resources & prompts
    def _doc(name: str) -> str:
        from . import help as hp
        f = hp.docs_dir() / name
        return f.read_text(encoding="utf-8") if f.exists() else f"(documentation {name} not installed)"

    @tool
    def search_help(query: str, limit: int = 6) -> dict[str, Any]:
        """Search EDGE's documentation (guides, cookbook recipes, reference, tutorials). Use it before
        guessing how to do something; then read_help for the full section."""
        from . import help as hp
        return {"results": hp.search(query, limit)}

    @tool
    def read_help(topic: str, section: str = "") -> dict[str, Any]:
        """Read a documentation page (e.g. COOKBOOK, EXPERIMENT_FORMAT, DATA, reference/components) or one
        section of it (the anchor from search_help results)."""
        from . import help as hp
        try:
            text = hp.section_text(topic, section) if section else hp.read_topic(topic)
        except KeyError as e:
            raise EditError(str(e.args[0])) from None
        return {"topic": topic, "markdown": text[:60000]}

    @tool
    def list_tutorials() -> dict[str, Any]:
        """Hands-on tutorials (interactive in the builder: `edge tutorial <id>`). Useful when the user wants to learn."""
        from . import help as hp
        return {"tutorials": [{k: t.get(k) for k in ("id", "title", "level", "minutes", "learn")} for t in hp.tutorials()]}

    @mcp.resource("edge://docs/{name}", mime_type="text/markdown")
    def any_doc(name: str) -> str:
        """Any documentation page by name (README, GETTING_STARTED, COOKBOOK, FAQ, BUILDER_GUIDE ...)."""
        from . import help as hp
        return hp.read_topic(name)

    @mcp.resource("edge://docs/experiment-format", mime_type="text/markdown")
    def doc_format() -> str:
        """Full reference of the EDGE experiment format."""
        return _doc("EXPERIMENT_FORMAT.md")

    @mcp.resource("edge://docs/devices", mime_type="text/markdown")
    def doc_devices() -> str:
        """Hardware drivers and synchronization."""
        return _doc("DEVICES.md")

    @mcp.resource("edge://docs/data", mime_type="text/markdown")
    def doc_data() -> str:
        """Data files, tables and exports."""
        return _doc("DATA.md")

    @mcp.resource("edge://templates/{name}", mime_type="application/yaml")
    def template_resource(name: str) -> str:
        """A starter experiment as YAML."""
        from .templates import TEMPLATES
        return dumps(TEMPLATES[name])

    @mcp.prompt()
    def design_experiment(paradigm: str, hardware: str = "none", path: str = "experiment.yaml") -> str:
        """Design and build a complete experiment from a description."""
        return (f"Build an EDGE experiment at '{path}' for this paradigm: {paradigm}.\n"
                f"Hardware: {hardware}.\n"
                "Steps: create_experiment; add devices; add routines (instructions, trial, feedback, end) with "
                "components and precise timing; put trials in a loop with a conditions table (write it as a CSV "
                "with set_conditions write_file=true); add markers on stimulus onsets; set data exports; "
                "validate; dry_run and check the verdict and the summary table; report the design to me "
                "(flow, timing per trial, number of trials, estimated duration).")

    @mcp.prompt()
    def prepare_for_data_collection(path: str) -> str:
        """Checklist before running real participants."""
        return (f"Review '{path}' for real data collection: describe_experiment and validate_experiment; "
                "check fullscreen, monitor/units, devices required/calibrate flags, LSL wait_for_consumers, "
                "marker codes and TTL collisions, response timeouts, counterbalancing, data exports; "
                "dry_run twice with different participant ids and compare trial orders; list concrete fixes.")

    @mcp.prompt()
    def analyze_my_data(directory: str = "data") -> str:
        """Analyze collected sessions."""
        return (f"List the sessions in '{directory}', run analyze_session on each to check data quality, "
                "then export_data for the whole folder as csv and xlsx and summarize accuracy and RTs per "
                "condition across participants, flagging sessions with quality problems.")

    mcp.workspace = ws  # type: ignore[attr-defined]  # for tests
    return mcp


def main(root: str = ".", transport: str = "stdio") -> None:
    server = create_server(root)
    print(f"EDGE {__version__} MCP server, workspace {Path(root).resolve()}", file=sys.stderr)
    server.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":  # pragma: no cover
    main(*(sys.argv[1:2] or ["."]))
