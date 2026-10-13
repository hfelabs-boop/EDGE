"""High-level, validated editing operations on experiment documents.

This is the API behind the MCP server (natural-language editing from Claude or
VS Code) and is usable from scripts. Every operation works on the plain
document (the same dict the YAML file and the builder use), checks its inputs
against the component/device registries, and raises :class:`EditError` with a
message that says how to fix the problem.

    doc = ExperimentDoc.open("study.yaml")
    doc.add_routine("trial")
    doc.add_component("trial", "text", {"text": "$word", "duration": 1})
    doc.add_loop("trials", children=["trial"], conditions="words.csv", order="random")
    doc.save("added trial loop")      # atomic, backed up, conflict-checked
"""

from __future__ import annotations

import copy
import csv
import difflib
import inspect
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .model import DEFAULT_SETTINGS, SCHEDULE_KEYS, Experiment, deep_merge
from .storage import FORMAT_VERSION, load_document, save_document

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FILE_EDITS_DIR = ".edge/file_edits"     # which data files (conditions CSVs) each save replaced, for undo

# operations that apply_operations (the MCP server's edit_experiment and the builder's assistant) may run
ALLOWED_OPS: frozenset[str] = frozenset({
    "add_routine", "update_routine", "rename_routine", "remove_routine", "duplicate_routine", "add_component",
    "update_component", "remove_component", "move_component", "insert_flow", "remove_from_flow", "move_in_flow",
    "add_loop", "update_loop", "set_conditions", "add_branch", "add_device", "update_device", "remove_device",
    "update_settings", "set_variables", "set_info", "add_state_machine", "update_state", "remove_state", "add_rule",
    "remove_rule", "set_measures", "add_survey"})


class EditError(ValueError):
    pass


def _unique(base: str, taken: set[str]) -> str:
    base = re.sub(r"\W", "_", base) or "item"
    if base[0].isdigit():
        base = "_" + base
    if base not in taken:
        return base
    i = 2
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"


class ExperimentDoc:
    def __init__(self, doc: dict[str, Any], path: Path | None = None, fingerprint: str | None = None):
        self.doc = doc
        self.path = path
        self.fingerprint = fingerprint
        self.changes: list[str] = []
        # who writes conditions files: None = written when the document is saved (MCP, scripts; undo puts the
        # old file back); the assistant sets a ledger that refuses to overwrite files and can take its own back
        self.file_writer: Callable[[Path, str], None] | None = None
        self._pending_files: dict[Path, str] = {}   # conditions files to write when the document is saved
        self.doc.setdefault("name", path.stem if path else "experiment")
        for key, default in (("settings", {}), ("devices", []), ("variables", {}), ("routines", {}), ("flow", [])):
            if self.doc.get(key) is None:
                self.doc[key] = copy.deepcopy(default)
        for r in self.doc["routines"].values():
            if r.get("components") is None:
                r["components"] = []

    # ------------------------------------------------------------------ files
    @classmethod
    def open(cls, path: str | Path) -> "ExperimentDoc":
        loaded = load_document(path)
        d = cls(loaded.doc, loaded.path, loaded.fingerprint)
        d.changes += [f"migrated: {m}" for m in loaded.migrations]
        return d

    @classmethod
    def new(cls, path: str | Path, name: str | None = None, template: str | None = None,
            description: str = "") -> "ExperimentDoc":
        from .templates import TEMPLATES
        p = Path(path)
        if p.exists():
            raise EditError(f"{p} already exists; open it instead or choose another name")
        if template:
            if template not in TEMPLATES:
                raise EditError(f"unknown template '{template}'; choose from {', '.join(TEMPLATES)}")
            doc = copy.deepcopy(TEMPLATES[template])
        else:
            doc = {"name": name or p.stem, "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
                   "devices": [], "variables": {}, "routines": {}, "flow": []}
        if name:
            doc["name"] = name
        if description:
            doc["description"] = description
        d = cls(doc, p, None)
        d.changes.append(f"created {p.name}" + (f" from template '{template}'" if template else ""))
        return d

    def save(self, label: str = "") -> str:
        """Save the document (atomic, backed up, conflict-checked), then the conditions files the edits wrote.
        A file that is replaced is backed up first, and :func:`undo_edit` puts it back with the document."""
        from .storage import list_backups
        if self.path is None:
            raise EditError("this document has no path")
        self.doc["edge_format"] = FORMAT_VERSION
        label = label or "; ".join(self.changes)[:40]
        before = {b["id"] for b in list_backups(self.path)} if self._pending_files else set()
        self.fingerprint = save_document(self.path, self.doc, expected_fingerprint=self.fingerprint, label=label)
        if self._pending_files:
            self._write_pending_files(label, before)
        return self.fingerprint

    def _write_pending_files(self, label: str, backups_before: set[str]) -> None:
        from .storage import _make_backup, atomic_write, list_backups
        assert self.path is not None
        base = self.path.parent.resolve()
        replaced: dict[str, str | None] = {}      # file -> its backup (paths relative to the experiment folder)
        for target, text in self._pending_files.items():
            old: str | None = None
            if target.exists():
                try:
                    if target.read_bytes() == text.encode("utf-8"):
                        continue
                except OSError:
                    pass
                old = _make_backup(target, f"before {label}").resolve().relative_to(base).as_posix()
            atomic_write(target, text)
            replaced[target.relative_to(base).as_posix()] = old
        self._pending_files.clear()
        if replaced:
            new = [b["id"] for b in list_backups(self.path) if b["id"] not in backups_before]
            jdir = _file_edits_dir(self.path)
            jdir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            (jdir / f"{stamp}.json").write_text(json.dumps({"doc_backup": new[0] if new else None,
                                                            "files": replaced}), encoding="utf-8")

    def experiment(self) -> Experiment:
        return Experiment.from_dict(copy.deepcopy(self.doc), base_dir=self.path.parent if self.path else None)

    def validate(self) -> list[dict[str, str]]:
        try:
            return [i.to_dict() for i in self.experiment().validate()]
        except Exception as e:
            return [{"level": "error", "where": "experiment", "message": str(e), "hint": ""}]

    # ------------------------------------------------------------------ lookup helpers
    @property
    def routines(self) -> dict[str, Any]:
        return self.doc["routines"]

    def routine(self, rid: str) -> dict[str, Any]:
        if rid not in self.routines:
            raise EditError(f"no routine '{rid}'. Existing routines: {', '.join(self.routines) or '(none)'}")
        return self.routines[rid]

    def component(self, rid: str, cid: str) -> dict[str, Any]:
        for c in self.routine(rid)["components"]:
            if c.get("id") == cid:
                return c
        ids = [c.get("id") for c in self.routine(rid)["components"]]
        raise EditError(f"routine '{rid}' has no component '{cid}'. Components: {', '.join(ids) or '(none)'}")

    def walk_flow(self) -> Iterator[tuple[Any, list[Any], int]]:
        """Yield (node, containing list, index) for every flow node, depth first."""
        def walk(nodes: list[Any]) -> Iterator[tuple[Any, list[Any], int]]:
            for i, n in enumerate(list(nodes)):
                yield n, nodes, i
                if isinstance(n, dict):
                    for key in ("children", "then", "else"):
                        if isinstance(n.get(key), list):
                            yield from walk(n[key])
                    for st in (n.get("states") or {}).values():
                        if isinstance(st, dict):
                            yield from walk(st.setdefault("run", []))
        yield from walk(self.doc["flow"])

    def loop(self, lid: str) -> dict[str, Any]:
        for n, _, _ in self.walk_flow():
            if isinstance(n, dict) and n.get("loop") == lid:
                return n
        raise EditError(f"no loop '{lid}'. Loops: {', '.join(self.loop_ids()) or '(none)'}")

    def machine(self, mid: str) -> dict[str, Any]:
        for n, _, _ in self.walk_flow():
            if isinstance(n, dict) and n.get("statemachine") == mid:
                return n
        ids = [n["statemachine"] for n, _, _ in self.walk_flow() if isinstance(n, dict) and "statemachine" in n]
        raise EditError(f"no workflow '{mid}'. Workflows: {', '.join(ids) or '(none)'}")

    def loop_ids(self) -> list[str]:
        return [n["loop"] for n, _, _ in self.walk_flow() if isinstance(n, dict) and "loop" in n]

    def branches(self) -> list[dict[str, Any]]:
        """The if/else nodes of the flow, in the order the outline lists them (``if:0``, ``if:1`` …)."""
        return [n for n, _, _ in self.walk_flow() if isinstance(n, dict) and "if" in n and "routine" not in n]

    def _branch(self, ref: str) -> dict[str, Any] | None:
        """A branch by "if:<n>" or as the outline shows it ("if $acc >= 0.8"); None if ``ref`` is neither."""
        bs = self.branches()
        m = re.match(r"^if:(\d+)$", ref.strip())
        if m:
            k = int(m.group(1))
            if k >= len(bs):
                raise EditError(f"there is no branch {ref}; " + (f"the flow has {len(bs)} (if:0 … if:{len(bs) - 1})"
                                                                  if bs else "the flow has no if/else branches"))
            return bs[k]
        if not ref.startswith("if "):
            return None
        cond = ref[3:].strip().rstrip(":").strip().lstrip("$").strip()
        hits = [i for i, b in enumerate(bs) if str(b.get("if", "")).strip().lstrip("$").strip() == cond]
        if len(hits) == 1:
            return bs[hits[0]]
        listed = "; ".join(f"if:{i} = if {b.get('if')}" for i, b in enumerate(bs)) or "(none)"
        if hits:
            raise EditError(f"{len(hits)} branches test '{cond}'; say which with if:<n> ({listed})")
        raise EditError(f"no branch '{ref}'. Branches: {listed}")

    def _container(self, parent: str | None, branch: str = "then") -> list[Any]:
        """Where to insert: None = top-level flow, a loop id, "machine.state" (a workflow state), or a branch as
        "if:<n>" or "if <condition>" (its then part; ``branch="else"`` for the else part)."""
        if not parent:
            return self.doc["flow"]
        if branch not in ("then", "else"):
            raise EditError("branch must be 'then' or 'else'")
        for n, _, _ in self.walk_flow():
            if isinstance(n, dict) and n.get("loop") == parent:
                return n.setdefault("children", [])
        b = self._branch(parent)
        if b is not None:
            return b.setdefault(branch, [])
        if "." in parent:
            mid, _, sname = parent.partition(".")
            m = self.machine(mid)
            if sname not in m["states"]:
                raise EditError(f"workflow '{mid}' has no state '{sname}'. States: {', '.join(m['states'])}")
            return m["states"][sname].setdefault("run", [])
        raise EditError(f"no loop or branch '{parent}' to insert into. Loops: {', '.join(self.loop_ids()) or '(none)'}; "
                        f"branches: {', '.join(f'if:{i}' for i in range(len(self.branches()))) or '(none)'}; "
                        "workflow states are written workflow.state")

    def _flow_hits(self, name: str) -> list[tuple[Any, list[Any], int]]:
        """Flow entries called ``name`` (a routine, loop or workflow id, "if:<n>" or "if <condition>")."""
        hits = [(n, lst, i) for n, lst, i in self.walk_flow() if self._node_name(n) == name]
        if not hits and (name.startswith("if ") or re.match(r"^if:\d+$", name)):
            b = self._branch(name)
            hits = [(n, lst, i) for n, lst, i in self.walk_flow() if n is b]
        return hits

    def _existing_block(self, item: Any) -> str | None:
        """The loop or workflow an entry of then/else/run refers to: 'trials' (when no routine has that name)
        or {"loop": "trials"}; None for a routine name or a new loop written out in full."""
        if isinstance(item, dict) and len(item) == 1 and isinstance(item.get("loop"), str):
            return item["loop"]
        if isinstance(item, str) and item not in self.routines:
            return item
        return None

    def _take_block(self, name: str, container: list[Any], where: str | None) -> tuple[Any, int]:
        """Remove the loop/workflow ``name`` from ``container`` (to move it into a branch or workflow state)."""
        idx = next((i for i, n in enumerate(container) if isinstance(n, dict) and "routine" not in n
                    and self._node_name(n) == name), None)
        if idx is not None:
            return container.pop(idx), idx
        blocks = [self._node_name(n) for n, _, _ in self.walk_flow() if isinstance(n, dict) and ("loop" in n or "statemachine" in n)]
        if name in blocks:
            raise EditError(f"'{name}' is not directly in {where or 'the top-level flow'}, so it can't be moved "
                            f"here; move it there first (modify_flow action=move)")
        raise EditError(f"no routine or loop '{name}'. Routines: {', '.join(self.routines) or '(none)'}; "
                        f"loops and workflows: {', '.join(blocks) or '(none)'}")

    @staticmethod
    def _node_name(n: Any) -> str:
        if isinstance(n, str):
            return n
        if "loop" in n:
            return n["loop"]
        if "statemachine" in n:
            return n["statemachine"]
        if "routine" in n:
            return n["routine"]
        return f"if {n.get('if')}"

    # ------------------------------------------------------------------ experiment-level
    def update_settings(self, patch: dict[str, Any]) -> None:
        """Deep-merge ``patch`` into settings; a value of null removes the key. Unknown sections and settings,
        units, colours and export formats are checked first, so a typo is refused instead of saved."""
        _check_settings_patch(patch)

        def prune(d: dict[str, Any], p: dict[str, Any]) -> None:
            for k, v in p.items():
                if v is None:
                    d.pop(k, None)
                elif isinstance(v, dict) and isinstance(d.get(k), dict):
                    prune(d[k], v)
        clean = {k: v for k, v in patch.items()}
        self.doc["settings"] = deep_merge(self.doc["settings"], _drop_none(clean))
        prune(self.doc["settings"], clean)
        self.changes.append(f"updated settings: {', '.join(patch)}")

    def set_info(self, name: str | None = None, description: str | None = None) -> None:
        if name:
            self.doc["name"] = name
        if description is not None:
            self.doc["description"] = description
        self.changes.append("updated experiment info")

    def set_variables(self, values: dict[str, Any], replace: bool = False) -> None:
        for k in values:
            if not IDENT.match(k):
                raise EditError(f"variable name '{k}' must be an identifier")
        self.doc["variables"] = dict(values) if replace else {**self.doc["variables"], **values}
        self.changes.append(f"set variables {', '.join(values)}")

    # ------------------------------------------------------------------ routines
    def add_routine(self, rid: str, description: str = "", duration: Any = None, end_if: str | None = None,
                    add_to_flow: bool = False, parent: str | None = None, position: int | None = None) -> str:
        if not IDENT.match(rid):
            raise EditError(f"routine name '{rid}' must be an identifier (letters, digits, _), e.g. 'trial'")
        if rid in self.routines:
            raise EditError(f"routine '{rid}' already exists")
        r: dict[str, Any] = {"components": []}
        if description:
            r["description"] = description
        if duration is not None:
            r["duration"] = duration
        if end_if:
            r["end_if"] = end_if
        self.routines[rid] = r
        self.changes.append(f"added routine {rid}")
        if add_to_flow:
            self.insert_flow(rid, parent=parent, position=position)
        return rid

    def update_routine(self, rid: str, duration: Any = "__keep__", end_if: Any = "__keep__",
                       description: Any = "__keep__") -> None:
        r = self.routine(rid)
        for k, v in (("duration", duration), ("end_if", end_if), ("description", description)):
            if v == "__keep__":
                continue
            if v in (None, ""):
                r.pop(k, None)
            else:
                r[k] = v
        self.changes.append(f"updated routine {rid}")

    def rename_routine(self, old: str, new: str) -> None:
        self.routine(old)
        if not IDENT.match(new):
            raise EditError(f"routine name '{new}' must be an identifier")
        if new in self.routines:
            raise EditError(f"routine '{new}' already exists")
        self.doc["routines"] = {(new if k == old else k): v for k, v in self.routines.items()}
        for n, lst, i in self.walk_flow():
            if n == old:
                lst[i] = new
            elif isinstance(n, dict) and n.get("routine") == old:
                n["routine"] = new
        self.changes.append(f"renamed routine {old} -> {new}")

    def remove_routine(self, rid: str) -> None:
        self.routine(rid)
        del self.routines[rid]

        def prune(nodes: list[Any]) -> None:
            for i in range(len(nodes) - 1, -1, -1):
                n = nodes[i]
                if n == rid or (isinstance(n, dict) and n.get("routine") == rid):
                    nodes.pop(i)
                elif isinstance(n, dict):
                    for key in ("children", "then", "else"):
                        if isinstance(n.get(key), list):
                            prune(n[key])
        prune(self.doc["flow"])
        self.changes.append(f"removed routine {rid}")

    def duplicate_routine(self, rid: str, new: str | None = None) -> str:
        src = self.routine(rid)
        new = new or _unique(rid + "_copy", set(self.routines))
        if new in self.routines:
            raise EditError(f"routine '{new}' already exists")
        self.routines[new] = copy.deepcopy(src)
        self.changes.append(f"duplicated routine {rid} as {new}")
        return new

    # ------------------------------------------------------------------ components
    def add_component(self, rid: str, ctype: str, properties: dict[str, Any] | None = None,
                      cid: str | None = None, position: int | None = None) -> str:
        from .components import component_registry
        reg = component_registry()
        if ctype not in reg:
            raise EditError(f"unknown component type '{ctype}'. Available: {', '.join(sorted(reg))}")
        r = self.routine(rid)
        props = dict(properties or {})
        props.pop("type", None)
        cid = cid or props.pop("id", None) or _unique({"keyboard": "resp", "fixation": "fix"}.get(ctype, ctype),
                                                       {c.get("id") for c in r["components"]})
        props.pop("id", None)
        if not IDENT.match(cid):
            raise EditError(f"component id '{cid}' must be an identifier (letters, digits, _)")
        if any(c.get("id") == cid for c in r["components"]):
            raise EditError(f"routine '{rid}' already has a component '{cid}'")
        self._check_props(ctype, props)
        comp = {"id": cid, "type": ctype, **props}
        if position is None or position >= len(r["components"]):
            r["components"].append(comp)
        else:
            r["components"].insert(max(0, position), comp)
        self.changes.append(f"added {ctype} '{cid}' to {rid}")
        return cid

    def _check_props(self, ctype: str, props: dict[str, Any]) -> None:
        from .components import component_registry
        cls = component_registry()[ctype]
        known = set(cls.all_props()) | SCHEDULE_KEYS
        unknown = [k for k in props if k not in known and not k.startswith("x_")]
        if unknown:
            raise EditError(f"{ctype} has no propert{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)}. "
                            f"Valid: {', '.join(sorted(known - {'id', 'type'}))}")

    def update_component(self, rid: str, cid: str, set_props: dict[str, Any] | None = None,
                         unset: list[str] | None = None, new_id: str | None = None) -> None:
        c = self.component(rid, cid)
        set_props = dict(set_props or {})
        set_props.pop("type", None)
        self._check_props(c["type"], {k: v for k, v in set_props.items() if k != "id"})
        for k, v in set_props.items():
            if k == "id":
                new_id = v
                continue
            if v is None:
                c.pop(k, None)
            else:
                c[k] = v
        for k in unset or []:
            c.pop(k, None)
        if new_id and new_id != cid:
            if not IDENT.match(new_id):
                raise EditError(f"component id '{new_id}' must be an identifier")
            if any(o.get("id") == new_id for o in self.routine(rid)["components"]):
                raise EditError(f"routine '{rid}' already has a component '{new_id}'")
            c["id"] = new_id
            r = self.routine(rid)
            for o in r["components"]:  # keep references working
                for k in ("start_after", "target"):
                    if o.get(k) == cid:
                        o[k] = new_id
                if isinstance(o.get("clickable"), list):
                    o["clickable"] = [new_id if x == cid else x for x in o["clickable"]]
            for rule in r.get("rules") or []:
                for a in (rule.get("do") or []) if isinstance(rule, dict) else []:
                    for k in ("start", "stop"):
                        if isinstance(a, dict) and a.get(k) == cid:
                            a[k] = new_id
            # $resp.corr in other screens, measures on resp.rt …; a routine with its own 'resp' keeps its own
            same_name = {o_rid for o_rid, o in self.routines.items() if o_rid != rid
                         and any(x.get("id") == cid for x in o.get("components") or [])}
            where = self._rename_references(cid, new_id, skip_routines=same_name, columns=not same_name)
            self.changes.append(f"renamed component {rid}.{cid} to {new_id}" +
                                (f"; updated the references in {', '.join(where)}" if where else ""))
            if same_name:
                self.changes.append(f"note: {', '.join(sorted(same_name))} also {'has' if len(same_name) == 1 else 'have'} "
                                    f"a component called '{cid}'; references there and in measures were left as they are")
            return
        self.changes.append(f"updated {rid}.{cid}")

    def _rename_references(self, old: str, new: str, skip_routines: set[str] = frozenset(),
                           columns: bool = True, loop: bool = False) -> list[str]:
        """After renaming a component or loop, rewrite ``old.x`` in expressions everywhere (screens, rules, the
        flow), measures' columns and loops, and the summary settings. Returns the places that changed."""
        where: list[str] = []
        for rid, r in self.routines.items():
            if rid in skip_routines or not isinstance(r, dict):
                continue
            for c in r.get("components") or []:
                if not isinstance(c, dict):
                    continue
                for k in list(c):
                    if k in ("id", "type"):
                        continue
                    c[k], n = _rename_refs(c[k], old, new)
                    if n:
                        where.append(f"{rid}.{c.get('id')}.{k}")
            for k in ("duration", "end_if", "rules"):
                if k in r:
                    r[k], n = _rename_refs(r[k], old, new)
                    if n:
                        where.append(f"{rid}.{k}")
        flow, n = _rename_refs(self.doc["flow"], old, new)
        if n:
            where.append("the flow")
        for m in self.doc.get("measures") or []:
            if not isinstance(m, dict):
                continue
            hit = False
            if columns and isinstance(m.get("column"), str) and m["column"].startswith(old + "."):
                m["column"] = new + m["column"][len(old):]
                hit = True
            if loop and m.get("loop") == old:
                m["loop"] = new
                hit = True
            if "trials" in m:
                t = m["trials"]
                m["trials"], n = _rename_refs(t if not isinstance(t, str) or t.startswith("$") else "$" + t, old, new)
                if n:
                    hit = True
                else:
                    m["trials"] = t
            if hit:
                where.append(f"measure {m.get('id') or m.get('column')}")
        summary = ((self.doc.get("settings") or {}).get("data") or {}).get("summary")
        if columns and isinstance(summary, dict):
            for k in ("rt", "correct"):
                if isinstance(summary.get(k), str) and summary[k].startswith(old + "."):
                    summary[k] = new + summary[k][len(old):]
                    where.append(f"settings.data.summary.{k}")
        return where

    def remove_component(self, rid: str, cid: str) -> None:
        r = self.routine(rid)
        self.component(rid, cid)
        r["components"] = [c for c in r["components"] if c.get("id") != cid]
        self.changes.append(f"removed {rid}.{cid}")

    def move_component(self, rid: str, cid: str, position: int) -> None:
        r = self.routine(rid)
        c = self.component(rid, cid)
        r["components"].remove(c)
        r["components"].insert(max(0, min(position, len(r["components"]))), c)
        self.changes.append(f"moved {rid}.{cid} to position {position}")

    # ------------------------------------------------------------------ flow
    def insert_flow(self, item: Any, parent: str | None = None, position: int | None = None,
                    branch: str = "then") -> None:
        """Insert a routine name (or a prepared loop/branch dict) into the flow or into a loop/branch."""
        if isinstance(item, str):
            self.routine(item)
        lst = self._container(parent, branch)
        if position is None or position >= len(lst):
            lst.append(item)
        else:
            lst.insert(max(0, position), item)
        self.changes.append(f"inserted {self._node_name(item)} into {parent or 'flow'}")

    def remove_from_flow(self, name: str, occurrence: int = 0, keep_children: bool = True) -> None:
        """Remove a routine reference, a loop, a workflow or a branch from the flow. Routine definitions are kept.
        With ``keep_children`` what was inside a loop / workflow / branch stays in its place."""
        hits = self._flow_hits(name)
        if not hits:
            raise EditError(f"'{name}' is not in the flow")
        if occurrence >= len(hits):
            raise EditError(f"'{name}' appears {len(hits)} time(s) in the flow")
        n, lst, i = hits[occurrence]
        lst.pop(i)
        inner: list[Any] = []
        if isinstance(n, dict) and "routine" not in n:
            if "loop" in n:
                inner = list(n.get("children") or [])
            elif "statemachine" in n:
                inner = [x for st in (n.get("states") or {}).values() if isinstance(st, dict) for x in st.get("run") or []]
            elif "if" in n:
                inner = list(n.get("then") or []) + list(n.get("else") or [])
        label = ("loop " if isinstance(n, dict) and "loop" in n else
                 "workflow " if isinstance(n, dict) and "statemachine" in n else "") + self._node_name(n)
        what = ", ".join(("loop " if isinstance(x, dict) and "loop" in x else "") + self._node_name(x) for x in inner)
        if inner and keep_children:
            lst[i:i] = inner
            self.changes.append(f"removed {label} from the flow; what was inside it stays in its place: {what}" +
                                (" (now without the condition)" if "loop" not in n and "statemachine" not in n else ""))
        elif inner:
            self.changes.append(f"removed {label} and everything inside it from the flow: {what}")
        else:
            self.changes.append(f"removed {label} from the flow")

    def move_in_flow(self, name: str, position: int, parent: str | None = None, branch: str = "then") -> None:
        hits = self._flow_hits(name)
        if not hits:
            raise EditError(f"'{name}' is not in the flow")
        n, lst, i = hits[0]
        if parent and isinstance(n, dict) and any(m is self._container(parent, branch) for m in self._inner_lists(n)):
            raise EditError(f"can't move '{name}' into itself")
        lst.pop(i)
        self.insert_flow(n, parent=parent, position=position, branch=branch)

    def _inner_lists(self, node: Any) -> Iterator[list[Any]]:
        """Every list nested inside a flow node (children, then/else, workflow states), at any depth."""
        if not isinstance(node, dict):
            return
        lists = [node[k] for k in ("children", "then", "else") if isinstance(node.get(k), list)]
        lists += [st["run"] for st in (node.get("states") or {}).values() if isinstance(st, dict) and isinstance(st.get("run"), list)]
        for lst in lists:
            yield lst
            for x in lst:
                yield from self._inner_lists(x)

    def add_loop(self, lid: str, children: list[Any] | None = None, conditions: Any = None,
                 order: str = "sequential", repeats: Any = 1, max_repeat: dict[str, Any] | None = None,
                 stop_if: str | None = None, staircase: dict[str, Any] | None = None,
                 parent: str | None = None, position: int | None = None, wrap: bool = False) -> str:
        """Create a loop. ``children`` are routine names (or loop ids when ``wrap`` is true).

        With ``wrap=True`` the named items are *moved* from the flow into the new loop
        (e.g. wrap 'trial' and 'feedback' that are already in the flow).
        """
        from .model import LOOP_ORDERS
        if not IDENT.match(lid):
            raise EditError(f"loop id '{lid}' must be an identifier, e.g. 'trials'")
        if lid in self.loop_ids() or lid in self.routines:
            raise EditError(f"'{lid}' is already used as a loop or routine name")
        if order not in LOOP_ORDERS:
            raise EditError(f"order must be one of {', '.join(LOOP_ORDERS)}")
        kids: list[Any] = []
        container = self._container(parent)
        insert_at = position
        if wrap:
            for name in children or []:
                idx = next((i for i, n in enumerate(container) if self._node_name(n) == name), None)
                if idx is None:
                    raise EditError(f"cannot wrap '{name}': it is not directly in {parent or 'the top-level flow'}")
                insert_at = idx if insert_at is None else min(insert_at, idx)
            for name in children or []:
                idx = next(i for i, n in enumerate(container) if self._node_name(n) == name)
                kids.append(container.pop(idx))
                if insert_at is not None and idx < insert_at:
                    insert_at -= 1
        else:
            for name in children or []:
                if isinstance(name, str):
                    self.routine(name)
                kids.append(name)
        node: dict[str, Any] = {"loop": lid}
        if staircase:
            node["staircase"] = staircase
        else:
            if conditions is not None:
                node["conditions"] = conditions
            if order != "sequential":
                node["order"] = order
            if repeats not in (1, None):
                node["repeats"] = repeats
            if max_repeat:
                node["max_repeat"] = max_repeat
        if stop_if:
            node["stop_if"] = stop_if
        node["children"] = kids
        if insert_at is None or insert_at >= len(container):
            container.append(node)
        else:
            container.insert(insert_at, node)
        self.changes.append(f"added loop {lid}")
        return lid

    def update_loop(self, lid: str, changes: dict[str, Any]) -> None:
        from .model import LOOP_ORDERS
        n = self.loop(lid)
        allowed = {"conditions", "order", "repeats", "max_repeat", "stop_if", "staircase", "select", "id"}
        bad = set(changes) - allowed
        if bad:
            raise EditError(f"loops have no setting {', '.join(bad)}; valid: {', '.join(sorted(allowed))}")
        if "order" in changes and changes["order"] not in LOOP_ORDERS:
            raise EditError(f"order must be one of {', '.join(LOOP_ORDERS)}")
        new_id = changes.get("id")
        if new_id is not None and new_id != lid:
            if not isinstance(new_id, str) or not IDENT.match(new_id):
                raise EditError(f"loop id '{new_id}' must be an identifier, e.g. 'trials'")
            if new_id in self.loop_ids() or new_id in self.routines:
                raise EditError(f"'{new_id}' is already used as a loop or routine name")
        for k, v in changes.items():
            if k == "id":
                continue
            if v is None:
                n.pop(k, None)
            else:
                n[k] = v
        if new_id is not None and new_id != lid:
            n["loop"] = new_id
            where = self._rename_references(lid, new_id, loop=True)
            self.changes.append(f"renamed loop {lid} to {new_id}" +
                                (f"; updated the references in {', '.join(where)}" if where else ""))
            if set(changes) == {"id"}:
                return
        self.changes.append(f"updated loop {lid}")

    def add_branch(self, condition: str, then: list[Any], otherwise: list[Any] | None = None,
                   parent: str | None = None, position: int | None = None) -> None:
        """An if/else in the flow. ``then``/``otherwise`` list routine names (run there) and loop or workflow ids
        (or {"loop": id}): those loops are moved into the branch from the same level of the flow."""
        container = self._container(parent)
        insert_at = position
        moved_from: int | None = None

        def resolve(items: list[Any]) -> list[Any]:
            nonlocal insert_at, moved_from
            out = []
            for item in items:
                block = self._existing_block(item)
                if block is None:
                    out.append(item)
                    continue
                node, idx = self._take_block(block, container, parent)
                if insert_at is not None and idx < insert_at:
                    insert_at -= 1
                moved_from = idx if moved_from is None else min(moved_from, idx)
                out.append(node)
            return out

        then_items, else_items = resolve(list(then)), resolve(list(otherwise or []))
        cond = condition if condition.startswith("$") else "$" + condition
        node: dict[str, Any] = {"if": cond, "then": then_items}
        if else_items:
            node["else"] = else_items
        self.insert_flow(node, parent=parent, position=insert_at if insert_at is not None else moved_from)

    # ------------------------------------------------------------------ workflows (state machines)
    @staticmethod
    def _routes(next_: Any) -> list[dict[str, Any]]:
        out = []
        for t in ([next_] if isinstance(next_, (str, dict)) else (next_ or [])):
            if isinstance(t, str):
                out.append({"goto": t})
            else:
                r = {}
                if t.get("if"):
                    r["if"] = t["if"] if str(t["if"]).startswith("$") else "$" + str(t["if"])
                r["goto"] = str(t.get("goto", "end"))
                if t.get("set"):
                    r["set"] = dict(t["set"])
                out.append(r)
        return out

    def add_state_machine(self, mid: str, states: dict[str, Any], start: str | None = None,
                          parent: str | None = None, position: int | None = None, max_steps: int | None = None) -> str:
        """states: {name: {"run": [routine or loop dict ...], "next": [{"if": "$expr", "goto": "other"}, "end"],
        "max_visits": 3}}. Routine names in "run" must exist; with wrap semantics, items already in the flow at
        the same level are *moved* into the state."""
        if not IDENT.match(mid):
            raise EditError(f"workflow id '{mid}' must be an identifier, e.g. 'session'")
        if mid in self.loop_ids() or mid in self.routines:
            raise EditError(f"'{mid}' is already used")
        if not states:
            raise EditError("a workflow needs at least one state")
        container = self._container(parent)
        node_states: dict[str, Any] = {}
        insert_at = position
        for name, sd in states.items():
            if not IDENT.match(name):
                raise EditError(f"state name '{name}' must be an identifier")
            sd = sd or {}
            run = []
            for item in sd.get("run", []) or []:
                block = self._existing_block(item)
                if block is not None:            # a loop ('trials' or {"loop": "trials"}): moved into the state
                    moved, idx = self._take_block(block, container, parent)
                    insert_at = idx if insert_at is None else min(insert_at, idx)
                    run.append(moved)
                    continue
                if isinstance(item, str):
                    self.routine(item)
                    idx = next((i for i, n in enumerate(container) if self._node_name(n) == item), None)
                    if idx is not None:          # move it from the flow into the state
                        moved = container.pop(idx)
                        insert_at = idx if insert_at is None else min(insert_at, idx)
                        run.append(moved)
                        continue
                run.append(item)
            st: dict[str, Any] = {"run": run}
            routes = self._routes(sd.get("next"))
            if routes:
                st["next"] = routes
            for k in ("max_visits", "description"):
                if sd.get(k):
                    st[k] = sd[k]
            node_states[name] = st
        for name, st in node_states.items():
            for r in st.get("next", []):
                if r["goto"] != "end" and r["goto"] not in node_states:
                    raise EditError(f"state '{name}' routes to unknown state '{r['goto']}' (use 'end' to finish)")
        node: dict[str, Any] = {"statemachine": mid, "start": start or next(iter(node_states)), "states": node_states}
        if max_steps:
            node["max_steps"] = max_steps
        if insert_at is None or insert_at >= len(container):
            container.append(node)
        else:
            container.insert(insert_at, node)
        self.changes.append(f"added workflow {mid} with states {', '.join(node_states)}")
        return mid

    def update_state(self, mid: str, state: str, run: list[Any] | None = None, next: Any = None,
                     max_visits: Any = "__keep__", description: str | None = None, rename_to: str | None = None,
                     make_start: bool = False) -> None:
        m = self.machine(mid)
        if state not in m["states"]:
            m["states"][state] = {"run": []}
            self.changes.append(f"added state {mid}.{state}")
        st = m["states"][state]
        if run is not None:
            items: list[Any] = []
            for item in run:
                block = self._existing_block(item)
                if block is None:
                    if isinstance(item, str):
                        self.routine(item)
                    items.append(item)
                    continue
                hit = next(((n, lst, i) for n, lst, i in self.walk_flow() if isinstance(n, dict)
                            and "routine" not in n and self._node_name(n) == block), None)
                if hit is None:
                    self._take_block(block, [], None)     # raises: says which routines and loops exist
                n, lst, i = hit
                if n is m or any(x is st.setdefault("run", []) for x in self._inner_lists(n)):
                    raise EditError(f"'{block}' contains this workflow, so it can't run inside it")
                lst.pop(i)                                # an existing loop is moved into the state
                items.append(n)
            st["run"] = items
        if next is not None:
            routes = self._routes(next)
            for r in routes:
                if r["goto"] != "end" and r["goto"] not in m["states"]:
                    raise EditError(f"route to unknown state '{r['goto']}'; states: {', '.join(m['states'])}, end")
            st["next"] = routes
        if max_visits != "__keep__":
            if max_visits:
                st["max_visits"] = int(max_visits)
            else:
                st.pop("max_visits", None)
        if description is not None:
            st["description"] = description
        if make_start:
            m["start"] = state
        if rename_to and rename_to != state:
            if not IDENT.match(rename_to) or rename_to in m["states"]:
                raise EditError(f"invalid or duplicate state name '{rename_to}'")
            m["states"] = {(rename_to if k == state else k): v for k, v in m["states"].items()}
            for s2 in m["states"].values():
                for r in s2.get("next", []) or []:
                    if isinstance(r, dict) and r.get("goto") == state:
                        r["goto"] = rename_to
            if m["start"] == state:
                m["start"] = rename_to
        self.changes.append(f"updated state {mid}.{state}")

    def remove_state(self, mid: str, state: str) -> None:
        m = self.machine(mid)
        if state not in m["states"]:
            raise EditError(f"no state '{state}'")
        del m["states"][state]
        for s2 in m["states"].values():
            s2["next"] = [r for r in s2.get("next", []) or [] if (r if isinstance(r, str) else r.get("goto")) != state]
        if m["start"] == state:
            m["start"] = next(iter(m["states"]), "")
        self.changes.append(f"removed state {mid}.{state}")

    # ------------------------------------------------------------------ routine rules
    def add_rule(self, rid: str, when: str, do: list[Any], repeat: bool = False, name: str | None = None) -> int:
        """do: actions like [{"end_routine": true}, {"start": "hint"}, {"stop": "stim"}, {"set": {"x": "$x+1"}},
        {"marker": "label"}, {"goto": "state"}, {"log": "text"}]."""
        from .model import RULE_ACTIONS
        r = self.routine(rid)
        acts = do if isinstance(do, list) else [do]
        comp_ids = {c.get("id") for c in r["components"]}
        for a in acts:
            keys = set(a) if isinstance(a, dict) else {a}
            bad = keys - RULE_ACTIONS
            if bad:
                raise EditError(f"unknown rule action {', '.join(map(str, bad))}; valid: {', '.join(sorted(RULE_ACTIONS))}")
            if isinstance(a, dict):
                for k in ("start", "stop"):
                    if k in a and a[k] not in comp_ids:
                        raise EditError(f"rule action {k}: routine '{rid}' has no component '{a[k]}'")
        rule: dict[str, Any] = {"when": when if str(when).startswith("$") else "$" + str(when), "do": acts}
        if name:
            rule["name"] = name
        if repeat:
            rule["repeat"] = True
        r.setdefault("rules", []).append(rule)
        self.changes.append(f"added rule to {rid}")
        return len(r["rules"]) - 1

    def remove_rule(self, rid: str, index: int) -> None:
        r = self.routine(rid)
        rules = r.get("rules") or []
        if not 0 <= index < len(rules):
            raise EditError(f"routine '{rid}' has {len(rules)} rule(s)")
        rules.pop(index)
        if not rules:
            r.pop("rules", None)
        self.changes.append(f"removed rule {index} from {rid}")

    # ------------------------------------------------------------------ conditions
    def set_conditions(self, lid: str, rows: list[dict[str, Any]] | None = None, file: str | None = None,
                       factorial: dict[str, list[Any]] | None = None, write_file: bool = False,
                       overwrite: bool = False) -> None:
        """Give a loop its trial list: inline rows, a file, or a factorial design.
        With ``write_file`` and ``rows``, the rows are written to ``file`` as CSV when the document is saved.
        A file that another loop also uses is only replaced with ``overwrite``."""
        n = self.loop(lid)
        if not factorial and rows is None and not file:
            raise EditError("provide rows, file or factorial")
        if not factorial and rows is not None and write_file:
            if not file:
                raise EditError("give a file name to write the conditions to, e.g. 'conditions.csv'")
            others = [m["loop"] for m, _, _ in self.walk_flow() if isinstance(m, dict) and "loop" in m
                      and m["loop"] != lid and _cond_file(m.get("conditions")) == Path(file).as_posix()]
            if others and not overwrite:
                raise EditError(f"{file} is also the trial list of loop {', '.join(others)}, so writing these rows "
                                f"would change {'that loop' if len(others) == 1 else 'those loops'} too. Give this loop "
                                f"its own file (e.g. file='{lid}.csv'), or set overwrite=true to change it everywhere")
            self.write_conditions_file(file, rows)
        n.pop("staircase", None)
        if factorial:
            n["conditions"] = {"factorial": factorial}
        elif rows is not None and write_file:
            n["conditions"] = file
        elif rows is not None:
            n["conditions"] = rows
        else:
            n["conditions"] = file
        self.changes.append(f"set conditions of loop {lid}")

    def write_conditions_file(self, filename: str, rows: list[dict[str, Any]]) -> Path:
        """Write ``rows`` to a CSV/TSV next to the experiment. The file is written when the document is saved
        (so a failed batch of edits leaves it alone); an existing file is backed up first, and undo restores it."""
        if self.path is None:
            raise EditError("save the experiment before writing conditions files")
        target = (self.path.parent / filename).resolve()
        if self.path.parent.resolve() not in target.parents:
            raise EditError("conditions files must be inside the experiment folder")
        cols: list[str] = []
        for r in rows:
            if not isinstance(r, dict):
                raise EditError("each row must be a mapping of column -> value, e.g. {\"word\": \"RED\"}")
            cols += [k for k in r if k not in cols]
        buf = io.StringIO(newline="")
        w = csv.DictWriter(buf, fieldnames=cols, delimiter="\t" if target.suffix.lower() == ".tsv" else ",")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})
        text = buf.getvalue()
        if self.file_writer is not None:          # the assistant: its ledger writes (and can take back) the file
            self.file_writer(target, text)
            self.changes.append(f"wrote {filename} ({len(rows)} rows)")
            return target
        try:
            replacing = target.is_file() and target.read_bytes() != text.encode("utf-8")
        except OSError:
            replacing = True
        self._pending_files[target] = text
        self.changes.append(f"wrote {filename} ({len(rows)} rows)" +
                            ("; the old version is kept and undo puts it back" if replacing else ""))
        return target

    # ------------------------------------------------------------------ measures and surveys
    def set_measures(self, measures: list[dict[str, Any]], replace: bool = True) -> int:
        """Declare what the experiment measures (see set_measures in the MCP docs). ``replace=False`` appends
        (a measure with the same id is replaced; without an id, the id is the column with _ for .). Invalid
        measures (no column, unknown role or summary …) are refused and nothing changes. Returns the count."""
        from .measures import normalize, validate_measures
        if not isinstance(measures, list) or not all(isinstance(m, dict) for m in measures):
            raise EditError("measures must be a list of objects like {\"id\": \"rt\", \"column\": \"resp.rt\"}")
        cur = [] if replace else list(self.doc.get("measures") or [])
        new_ids: set[str] = set()
        for m in measures:
            if not m.get("column"):
                raise EditError("each measure needs a 'column': the data column it is based on, e.g. resp.rt "
                                "(describe_recording lists them)")
            if not m.get("id"):
                m = {"id": normalize(m)["id"], **m}
            new_ids.add(str(m["id"]))
            cur = [x for x in cur if not (isinstance(x, dict) and normalize(x)["id"] == m["id"])] + [m]
        trial = copy.deepcopy(self.doc)
        if cur:
            trial["measures"] = cur
        else:
            trial.pop("measures", None)
        exp = Experiment.from_dict(trial, base_dir=self.path.parent if self.path else None)
        bad = [i for i in validate_measures(exp) if i.level == "error" and i.where.split(".", 1)[-1] in new_ids]
        if bad:
            raise EditError("; ".join(f"{i.where}: {i.message}" + (f" ({i.hint})" if i.hint else "") for i in bad)
                            + ". Nothing was saved")
        if cur:
            self.doc["measures"] = cur
        else:
            self.doc.pop("measures", None)
        self.changes.append(f"measures: {len(cur)} declared")
        return len(cur)

    def add_survey(self, questions: list[dict[str, Any]], routine: str = "questionnaire", title: str = "",
                   intro: str = "", position: str = "end", scores: dict[str, Any] | None = None,
                   language: str = "") -> str:
        """Add a questionnaire screen (library instruments like {"instrument": "phq9"} and/or own questions).
        ``position``: "end", "start" or "after:<routine>". Creates the routine if needed; if the routine already
        has a survey, the questions are added to it. Unknown questionnaires or question types are refused and
        nothing changes. Returns the survey's component id (its answers are columns <id>.<answer>)."""
        from .survey import validate as validate_survey
        from .survey_library import INSTRUMENTS
        if not isinstance(questions, list):
            raise EditError("questions must be a list")
        if not (position in ("start", "end") or (isinstance(position, str) and position.startswith("after:"))):
            raise EditError(f"position must be 'start', 'end' or 'after:<routine>', not '{position}'")
        for q in questions:
            ins = q.get("instrument") if isinstance(q, dict) else None
            if ins is not None and ins not in INSTRUMENTS:
                norm = {re.sub(r"[^a-z0-9]", "", k.lower()): k for k in INSTRUMENTS}
                close = norm.get(re.sub(r"[^a-z0-9]", "", str(ins).lower())) or \
                    next(iter(difflib.get_close_matches(str(ins), list(INSTRUMENTS), 1)), None)
                raise EditError(f"unknown questionnaire '{ins}'" + (f" (did you mean '{close}'?)" if close else "") +
                                f"; available: {', '.join(INSTRUMENTS)}. Nothing was saved")
        existing = next((c for c in self.routines[routine]["components"] if c.get("type") == "survey"), None) \
            if routine in self.routines else None
        all_questions = list(existing.get("questions") or []) + list(questions) if existing else list(questions)
        problems = validate_survey(all_questions, {**((existing or {}).get("scores") or {}), **(scores or {})})
        if problems:
            raise EditError("; ".join(problems) + ". Nothing was saved")
        if existing is not None:      # one survey per screen: add the questions to it
            existing["questions"] = all_questions
            for k, v in (("title", title), ("intro", intro), ("language", language)):
                if v:
                    existing[k] = v
            if scores:
                existing["scores"] = {**(existing.get("scores") or {}), **scores}
            self.changes.append(f"added {len(questions)} question(s) to survey '{existing.get('id')}' in {routine}")
            return str(existing.get("id"))
        if routine not in self.routines:
            self.add_routine(routine, description="questionnaire")
            if position == "start":
                self.insert_flow(routine, position=0)
            elif position.startswith("after:"):
                target = position.split(":", 1)[1]
                idx = next((i for i, n in enumerate(self.doc["flow"]) if self._node_name(n) == target), None)
                if idx is None:
                    top = [self._node_name(n) for n in self.doc["flow"]]
                    raise EditError(f"'{target}' is not in the top level of the flow, so the survey can't go "
                                    f"after it. Top level: {', '.join(top) or '(empty)'}")
                self.insert_flow(routine, position=idx + 1)
            else:
                self.insert_flow(routine)
        props: dict[str, Any] = {"questions": questions, "end_routine": True}
        if title:
            props["title"] = title
        if intro:
            props["intro"] = intro
        if scores:
            props["scores"] = scores
        if language:
            props["language"] = language
        taken = {c.get("id") for c in self.routine(routine)["components"]}
        return self.add_component(routine, "survey", props, routine if routine not in taken else None)

    # ------------------------------------------------------------------ devices
    def add_device(self, dtype: str, did: str | None = None, options: dict[str, Any] | None = None,
                   required: bool | None = None, record: bool | None = None, markers: bool | None = None,
                   calibrate: bool | None = None) -> str:
        from .devices import device_registry
        reg = device_registry()
        if dtype not in reg:
            raise EditError(f"unknown device type '{dtype}'. Available: {', '.join(sorted(reg))}")
        ids = {d.get("id") for d in self.doc["devices"]}
        did = did or _unique(dtype.split("_")[0], ids)
        if did in ids:
            raise EditError(f"a device with id '{did}' already exists")
        opts = dict(options or {})
        _check_device_options(dtype, opts)
        dev: dict[str, Any] = {"id": did, "type": dtype}
        if opts:
            dev["options"] = opts
        for k, v in (("required", required), ("record", record), ("markers", markers), ("calibrate", calibrate)):
            if v is not None:
                dev[k] = v
        self.doc["devices"].append(dev)
        self.changes.append(f"added device {did} ({dtype})")
        return did

    def device(self, did: str) -> dict[str, Any]:
        for d in self.doc["devices"]:
            if d.get("id") == did:
                return d
        raise EditError(f"no device '{did}'. Devices: {', '.join(d.get('id') for d in self.doc['devices']) or '(none)'}")

    def update_device(self, did: str, options: dict[str, Any] | None = None, **flags: Any) -> None:
        from .devices import device_registry
        d = self.device(did)
        for k, v in flags.items():
            if k not in ("required", "record", "markers", "calibrate", "type"):
                raise EditError(f"unknown device setting '{k}'")
        dtype = flags.get("type") or d.get("type")
        if (options or flags.get("type")) and dtype not in device_registry():
            raise EditError(f"unknown device type '{dtype}'. Available: {', '.join(sorted(device_registry()))}")
        if options:
            merged = {**(d.get("options") or {}), **options}
            _check_device_options(dtype, {k: v for k, v in options.items() if v is not None})
            d["options"] = {k: v for k, v in merged.items() if v is not None}
        elif flags.get("type") and d.get("options"):
            _check_device_options(dtype, d["options"])
        for k, v in flags.items():
            if v is not None:
                d[k] = v
        self.changes.append(f"updated device {did}")

    def remove_device(self, did: str) -> None:
        self.device(did)
        self.doc["devices"] = [d for d in self.doc["devices"] if d.get("id") != did]
        self.changes.append(f"removed device {did}")

    # ------------------------------------------------------------------ description
    def outline(self) -> str:
        """Human-readable summary: devices, flow tree and routine timelines."""
        d = self.doc
        lines = [f"Experiment '{d.get('name')}'" + (f": {d['description']}" if d.get("description") else "")]
        w = (d.get("settings") or {}).get("window", {})
        if w:
            lines.append(f"Window {w.get('size', [1280, 720])} bg {w.get('background', '#000000')} units "
                         f"{w.get('units', 'px')}{' fullscreen' if w.get('fullscreen') else ''}")
        if d["devices"]:
            lines.append("Devices: " + ", ".join(f"{x['id']} ({x['type']}{'' if x.get('required', True) else ', optional'})"
                                                 for x in d["devices"]))
        if d["variables"]:
            lines.append("Variables: " + ", ".join(f"{k}={v!r}" for k, v in d["variables"].items()))
        lines.append("Flow:")
        n_branch = [0]

        def flow(nodes: list[Any], depth: int) -> None:
            pad = "  " * depth
            for n in nodes:
                if isinstance(n, str):
                    lines.append(f"{pad}- {n}")
                elif "routine" in n:
                    lines.append(f"{pad}- {n['routine']}  (only if {n.get('if')})")
                elif "loop" in n:
                    if n.get("staircase"):
                        desc = f"staircase on {n['staircase'].get('variable', 'level')}"
                    else:
                        c = n.get("conditions")
                        src = c if isinstance(c, str) else ("factorial " + str(list(c.get("factorial", {}))) if isinstance(c, dict)
                                                            else (f"{len(c)} inline rows" if c else "no conditions"))
                        desc = f"{src}, {n.get('order', 'sequential')}, repeats {n.get('repeats', 1)}"
                    lines.append(f"{pad}- loop {n['loop']} [{desc}]")
                    flow(n.get("children", []), depth + 1)
                elif "statemachine" in n:
                    lines.append(f"{pad}- workflow {n['statemachine']} (start: {n.get('start')})")
                    for sname, st in (n.get("states") or {}).items():
                        routes = []
                        for r in st.get("next") or []:
                            r = {"goto": r} if isinstance(r, str) else r
                            routes.append(f"{r.get('goto')} if {r['if']}" if r.get("if") else f"{r.get('goto')}")
                        extra = f", max {st['max_visits']} visits" if st.get("max_visits") else ""
                        lines.append(f"{pad}  state {sname}{extra} -> {' | '.join(routes) or 'end'}:")
                        flow(st.get("run") or [], depth + 2)
                elif "if" in n:
                    lines.append(f"{pad}- if {n['if']}:   [branch if:{n_branch[0]}]")
                    n_branch[0] += 1
                    flow(n.get("then", []), depth + 1)
                    if n.get("else"):
                        lines.append(f"{pad}  else:")
                        flow(n["else"], depth + 1)

        flow(d["flow"], 1)
        lines.append("Routines:")
        for rid, r in d["routines"].items():
            extra = []
            if r.get("duration") is not None:
                extra.append(f"duration {r['duration']}")
            if r.get("end_if"):
                extra.append(f"ends if {r['end_if']}")
            lines.append(f"  {rid}" + (f" ({', '.join(extra)})" if extra else "") + ":")
            for rule in r.get("rules") or []:
                lines.append(f"    rule: when {rule.get('when')} do {rule.get('do')}")
            if not r["components"]:
                lines.append("    (empty)")
            for c in r["components"]:
                timing = f"start {c.get('start', 0)}"
                if c.get("start_after"):
                    timing = f"after {c['start_after']}"
                timing += f", dur {c['duration']}" if c.get("duration") is not None else ", until end"
                key = {k: v for k, v in c.items() if k not in SCHEDULE_KEYS}
                summary = ", ".join(f"{k}={_short(v)}" for k, v in list(key.items())[:5])
                flags = " [ends routine]" if c.get("end_routine") else ""
                if c.get("if"):
                    flags += f" [only if {c['if']}]"
                lines.append(f"    - {c['id']} ({c['type']}; {timing}){flags} {summary}")
        return "\n".join(lines)


SETTINGS_KEYS: dict[str, set[str] | None] = {      # None: any names (participant fields) or a plain value
    "window": set(DEFAULT_SETTINGS["window"]) | {"mouse_visible"},
    "data": set(DEFAULT_SETTINGS["data"]),
    "participant": None,
    "markers": {"codes"},
    "timing": set(DEFAULT_SETTINGS["timing"]) | {"dry_run_routine_limit", "end_grace"},
    "seed": None,
}
UNITS = ("px", "norm", "height", "deg")


def _did_you_mean(word: Any, choices: Any) -> str:
    close = difflib.get_close_matches(str(word), [str(c) for c in choices], 1)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _check_settings_patch(patch: Any) -> None:
    """Refuse settings an experiment can't run with, before they are saved: unknown sections or settings
    (typos), unknown units, colours that aren't colours, and export formats that don't exist."""
    from .backends.base import parse_color
    from .export import FORMATS
    if not isinstance(patch, dict):
        raise EditError("settings must be a mapping, e.g. {\"window\": {\"fullscreen\": true}}")
    for sec, val in patch.items():
        if sec not in SETTINGS_KEYS:
            raise EditError(f"settings have no section '{sec}'{_did_you_mean(sec, SETTINGS_KEYS)}. "
                            f"Sections: {', '.join(SETTINGS_KEYS)}")
        keys = SETTINGS_KEYS[sec]
        if val is None or keys is None:
            continue
        if not isinstance(val, dict):
            raise EditError(f"settings.{sec} must be a mapping of settings: {', '.join(sorted(keys))}")
        for k in val:
            if k not in keys:
                raise EditError(f"settings.{sec} has no setting '{k}'{_did_you_mean(k, keys)}. "
                                f"Valid: {', '.join(sorted(keys))}")
    win = patch.get("window") if isinstance(patch.get("window"), dict) else {}
    units = win.get("units")
    if units is not None and units not in UNITS:
        raise EditError(f"settings.window.units must be one of {', '.join(UNITS)}, not '{units}' "
                        "(deg also needs window.monitor: width_cm and distance_cm)")
    bg = win.get("background")
    if bg is not None and not (isinstance(bg, str) and bg.startswith("$")):
        try:
            parse_color(bg)
        except (ValueError, TypeError, IndexError):
            raise EditError(f"settings.window.background: '{bg}' is not a colour; use #rrggbb (e.g. #808080), "
                            "a name such as gray, or [r, g, b]") from None
    data = patch.get("data") if isinstance(patch.get("data"), dict) else {}
    exports = data.get("exports")
    if exports is not None:
        if not isinstance(exports, (list, str)):
            raise EditError(f"settings.data.exports must be a list, e.g. [\"csv\", \"xlsx\"] (formats: {', '.join(FORMATS)})")
        bad = [str(f) for f in ([exports] if isinstance(exports, str) else exports) if f not in FORMATS]
        if bad:
            raise EditError(f"settings.data.exports: unknown format {', '.join(bad)}"
                            f"{_did_you_mean(bad[0], FORMATS)}; choose from {', '.join(FORMATS)}")


def _check_device_options(dtype: str, options: dict[str, Any]) -> None:
    """Option names and value types against the driver's options, e.g. srate must be a number."""
    from .devices import device_registry
    schema = device_registry()[dtype].options_schema
    unknown = [k for k in options if k not in schema and k not in ("latency", "screen_size")]
    if unknown:
        raise EditError(f"{dtype} has no option {', '.join(unknown)}{_did_you_mean(unknown[0], schema)}; "
                        f"valid: {', '.join(schema) or '(none)'}")
    for k, v in options.items():
        meta = schema.get(k) or {}
        t = meta.get("type")
        if v is None or (isinstance(v, str) and v.startswith("$")):
            continue
        ok = True
        if t in ("float", "int"):
            if isinstance(v, bool):
                ok = False
            elif isinstance(v, str):
                try:
                    float(v)
                except ValueError:
                    ok = False
            elif not isinstance(v, (int, float)):
                ok = False
            elif t == "int" and float(v) != int(v):
                ok = False
        elif t == "bool":
            ok = isinstance(v, bool)
        elif t == "choice":
            ok = v in (meta.get("choices") or [])
        elif t == "list":
            ok = isinstance(v, list)
        elif t == "dict":
            ok = isinstance(v, dict)
        if not ok:
            want = {"float": "a number", "int": "a whole number", "bool": "true or false", "list": "a list",
                    "dict": "a mapping", "choice": "one of " + ", ".join(map(str, meta.get("choices") or []))}[t]
            raise EditError(f"{dtype} option {k} must be {want}, not {v!r:.60}"
                            + (f" ({meta['help']})" if meta.get("help") else ""))


def _file_edits_dir(path: Path) -> Path:
    return path.parent / FILE_EDITS_DIR / path.name


def undo_edit(path: str | Path) -> dict[str, Any]:
    """Undo the newest edit of an experiment: restore its previous version and put back any conditions
    files that edit replaced. Returns {"restored": backup id or None, "files": [names put back]}."""
    from .storage import DocumentError, _make_backup, atomic_write, list_backups, restore_backup
    p = Path(path)
    backups = list_backups(p)
    ids = {b["id"] for b in backups}
    newest = next((b for b in backups if "before restore" not in b["label"]), None)
    jdir = _file_edits_dir(p)
    journals = sorted(jdir.glob("*.json")) if jdir.is_dir() else []
    entry, jfile = None, None
    while journals:
        jfile = journals[-1]
        try:
            entry = json.loads(jfile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entry = None
        doc_id = entry.get("doc_backup") if isinstance(entry, dict) else None
        if isinstance(entry, dict) and (doc_id is None or doc_id in ids):
            break
        jfile.unlink(missing_ok=True)       # its document version was already restored elsewhere
        journals.pop()
        entry, jfile = None, None
    if entry is not None:
        doc_id = entry.get("doc_backup")
        newest_stamp = newest["id"].split("_")[0].rsplit(".", 1)[0] if newest else ""
        if doc_id is None and newest_stamp > jfile.stem:      # an edit of the document came after it
            entry = None
        elif doc_id is not None and (newest is None or doc_id != newest["id"]):
            entry = None                                       # it belongs to an older edit
    restored = None
    if entry is None or entry.get("doc_backup"):
        try:
            restored = restore_backup(p)
        except DocumentError:
            if entry is None:
                raise
    files = []
    if entry is not None:
        base = p.parent.resolve()
        for target, old in (entry.get("files") or {}).items():
            t, b = (base / target).resolve(), (base / old).resolve() if old else None
            if b is None or base not in t.parents or base not in b.parents or not b.is_file():
                continue          # a new file (nothing to put back), or one whose backup is gone
            if t.exists():
                _make_backup(t, "before-restore")
            atomic_write(t, b.read_bytes())
            files.append(target)
        jfile.unlink(missing_ok=True)
    return {"restored": restored, "files": files}


def _cond_file(cond: Any) -> str | None:
    if isinstance(cond, dict):
        cond = cond.get("file")
    return Path(cond).as_posix() if isinstance(cond, str) and cond and not cond.startswith("$") else None


def _rename_refs(value: Any, old: str, new: str) -> tuple[Any, int]:
    """Rewrite ``old.x`` to ``new.x`` in every expression (strings starting with $) inside ``value``."""
    pat = re.compile(r"(?<![\w.])" + re.escape(old) + r"(?=\s*\.)")
    if isinstance(value, str):
        if value.startswith("$") and not value.startswith("$$"):
            out, n = pat.subn(new, value)
            return out, n
        return value, 0
    if isinstance(value, list):
        total = 0
        for i, v in enumerate(value):
            value[i], n = _rename_refs(v, old, new)
            total += n
        return value, total
    if isinstance(value, dict):
        total = 0
        for k in list(value):
            value[k], n = _rename_refs(value[k], old, new)
            total += n
        return value, total
    return value, 0


def _short(v: Any, n: int = 40) -> str:
    s = repr(v) if not isinstance(v, str) else v.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (_drop_none(v) if isinstance(v, dict) else v) for k, v in d.items() if v is not None}


def op_signature(name: str, fn: Callable | None = None) -> str:
    fn = fn or getattr(ExperimentDoc, name, None)
    if fn is None:
        return f"{name}(…)"
    params = [p for p in inspect.signature(fn).parameters.values() if p.name not in ("self", "doc")]
    return f"{name}(" + ", ".join(p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}"
                                  for p in params) + ")"


def apply_operations(doc: ExperimentDoc, operations: list[dict[str, Any]], *,
                     extra: dict[str, Callable[..., Any]] | None = None, ledger: Any = None) -> dict[str, Any]:
    """Apply ``[{"op": name, ...arguments}]`` all-or-nothing.

    On any failure the document, ``doc.changes`` and the files written by these operations (through
    ``ledger``) are restored, and the result names the failing operation:
    ``{"ok": False, "failed_index": 3, "op": "add_component", "error": "operation 3 (add_component): …"}``.
    ``extra`` adds operations ``fn(doc, **arguments)`` (the assistant's add_image_component)."""
    extra = extra or {}
    if not isinstance(operations, list):
        return {"ok": False, "failed_index": None, "op": None, "applied": 0,
                "error": "operations must be a list like [{\"op\": \"add_routine\", \"rid\": \"trial\"}]"}
    snapshot = copy.deepcopy(doc.doc)
    n_changes = len(doc.changes)
    pending = dict(doc._pending_files)
    cp = ledger.checkpoint() if ledger is not None else None

    def fail(i: int, name: Any, msg: str, **more: Any) -> dict[str, Any]:
        doc.doc.clear()
        doc.doc.update(snapshot)
        del doc.changes[n_changes:]
        doc._pending_files.clear()
        doc._pending_files.update(pending)
        if ledger is not None:
            ledger.rollback_to(cp)
        return {"ok": False, "failed_index": i, "op": name, "error": msg, "applied": 0, **more}

    results = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            return fail(i, None, f"operation {i}: must be an object like {{\"op\": \"add_routine\", \"rid\": \"trial\"}}")
        args = dict(op)
        name = args.pop("op", None)
        if name in extra:
            fn: Callable[..., Any] = extra[name]
            call = (lambda f=fn, a=args: f(doc, **a))
        elif name in ALLOWED_OPS:
            fn = getattr(doc, name)
            sig = inspect.signature(fn)
            try:
                sig.bind(**args)
            except TypeError:
                params = [k for k in sig.parameters if k != "flags"]
                unknown = [k for k in args if k not in params]
                if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()) or not unknown:
                    return fail(i, name, f"operation {i} ({name}): bad arguments: " +
                                (f"unknown argument {', '.join(unknown)}; " if unknown else "missing arguments; ") +
                                f"{name} takes {', '.join(params)}. Use {op_signature(name, None)}")
            call = (lambda f=fn, a=args: f(**a))
        else:
            return fail(i, name, f"operation {i}: unknown op '{name}'", allowed=sorted(ALLOWED_OPS | set(extra)))
        try:
            results.append(call())
        except TypeError as e:
            return fail(i, name, f"operation {i} ({name}): bad arguments: {e}. Use {op_signature(name, extra.get(name))}")
        except EditError as e:
            return fail(i, name, f"operation {i} ({name}): {e}")
        except Exception as e:  # noqa: BLE001 - any failure must leave the document as it was
            return fail(i, name, f"operation {i} ({name}): {type(e).__name__}: {e}")
    return {"ok": True, "applied": len(operations), "changes": doc.changes[n_changes:],
            "results": [r for r in results if r is not None]}
