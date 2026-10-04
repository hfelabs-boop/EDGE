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
import re
from pathlib import Path
from typing import Any, Iterator

from .model import SCHEDULE_KEYS, Experiment, deep_merge
from .storage import FORMAT_VERSION, load_document, save_document

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
        if self.path is None:
            raise EditError("this document has no path")
        self.doc["edge_format"] = FORMAT_VERSION
        self.fingerprint = save_document(self.path, self.doc, expected_fingerprint=self.fingerprint,
                                         label=label or "; ".join(self.changes)[:40])
        return self.fingerprint

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
        yield from walk(self.doc["flow"])

    def loop(self, lid: str) -> dict[str, Any]:
        for n, _, _ in self.walk_flow():
            if isinstance(n, dict) and n.get("loop") == lid:
                return n
        raise EditError(f"no loop '{lid}'. Loops: {', '.join(self.loop_ids()) or '(none)'}")

    def loop_ids(self) -> list[str]:
        return [n["loop"] for n, _, _ in self.walk_flow() if isinstance(n, dict) and "loop" in n]

    def _container(self, parent: str | None, branch: str = "then") -> list[Any]:
        if not parent:
            return self.doc["flow"]
        for n, _, _ in self.walk_flow():
            if isinstance(n, dict) and n.get("loop") == parent:
                return n.setdefault("children", [])
        # branches are addressed as "if:<index>" of their position in a flat walk
        m = re.match(r"^if:(\d+)$", parent)
        if m:
            branches = [n for n, _, _ in self.walk_flow() if isinstance(n, dict) and "if" in n]
            k = int(m.group(1))
            if k < len(branches):
                return branches[k].setdefault("else" if branch == "else" else "then", [])
        raise EditError(f"no loop or branch '{parent}' to insert into")

    @staticmethod
    def _node_name(n: Any) -> str:
        if isinstance(n, str):
            return n
        if "loop" in n:
            return n["loop"]
        if "routine" in n:
            return n["routine"]
        return f"if {n.get('if')}"

    # ------------------------------------------------------------------ experiment-level
    def update_settings(self, patch: dict[str, Any]) -> None:
        """Deep-merge ``patch`` into settings; a value of null removes the key."""
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
            for o in self.routine(rid)["components"]:  # keep references working
                for k in ("start_after", "target"):
                    if o.get(k) == cid:
                        o[k] = new_id
                if isinstance(o.get("clickable"), list):
                    o["clickable"] = [new_id if x == cid else x for x in o["clickable"]]
        self.changes.append(f"updated {rid}.{cid}")

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
        """Remove a routine reference or a loop (by id) from the flow. Routine definitions are kept."""
        hits = [(n, lst, i) for n, lst, i in self.walk_flow() if self._node_name(n) == name]
        if not hits:
            raise EditError(f"'{name}' is not in the flow")
        if occurrence >= len(hits):
            raise EditError(f"'{name}' appears {len(hits)} time(s) in the flow")
        n, lst, i = hits[occurrence]
        lst.pop(i)
        if keep_children and isinstance(n, dict) and "loop" in n:
            lst[i:i] = n.get("children", [])
        self.changes.append(f"removed {name} from the flow")

    def move_in_flow(self, name: str, position: int, parent: str | None = None) -> None:
        hits = [(n, lst, i) for n, lst, i in self.walk_flow() if self._node_name(n) == name]
        if not hits:
            raise EditError(f"'{name}' is not in the flow")
        n, lst, i = hits[0]
        lst.pop(i)
        self.insert_flow(n, parent=parent, position=position)

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
        for k, v in changes.items():
            if k == "id":
                if v in self.loop_ids():
                    raise EditError(f"loop '{v}' already exists")
                n["loop"] = v
            elif v is None:
                n.pop(k, None)
            else:
                n[k] = v
        self.changes.append(f"updated loop {lid}")

    def add_branch(self, condition: str, then: list[Any], otherwise: list[Any] | None = None,
                   parent: str | None = None, position: int | None = None) -> None:
        for name in list(then) + list(otherwise or []):
            if isinstance(name, str):
                self.routine(name)
        cond = condition if condition.startswith("$") else "$" + condition
        node: dict[str, Any] = {"if": cond, "then": list(then)}
        if otherwise:
            node["else"] = list(otherwise)
        self.insert_flow(node, parent=parent, position=position)

    # ------------------------------------------------------------------ conditions
    def set_conditions(self, lid: str, rows: list[dict[str, Any]] | None = None, file: str | None = None,
                       factorial: dict[str, list[Any]] | None = None, write_file: bool = False) -> None:
        """Give a loop its trial list: inline rows, a file, or a factorial design.
        With ``write_file`` and ``rows``, the rows are written to ``file`` as CSV."""
        n = self.loop(lid)
        n.pop("staircase", None)
        if factorial:
            n["conditions"] = {"factorial": factorial}
        elif rows is not None and write_file:
            if not file:
                raise EditError("give a file name to write the conditions to, e.g. 'conditions.csv'")
            self.write_conditions_file(file, rows)
            n["conditions"] = file
        elif rows is not None:
            n["conditions"] = rows
        elif file:
            n["conditions"] = file
        else:
            raise EditError("provide rows, file or factorial")
        self.changes.append(f"set conditions of loop {lid}")

    def write_conditions_file(self, filename: str, rows: list[dict[str, Any]]) -> Path:
        if self.path is None:
            raise EditError("save the experiment before writing conditions files")
        target = (self.path.parent / filename).resolve()
        if self.path.parent.resolve() not in target.parents:
            raise EditError("conditions files must be inside the experiment folder")
        cols: list[str] = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        target.parent.mkdir(parents=True, exist_ok=True)
        delim = "\t" if target.suffix.lower() == ".tsv" else ","
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=delim)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in cols})
        self.changes.append(f"wrote {filename} ({len(rows)} rows)")
        return target

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
        unknown = set(opts) - set(reg[dtype].options_schema) - {"latency", "screen_size"}
        if unknown:
            raise EditError(f"{dtype} has no option {', '.join(unknown)}; valid: {', '.join(reg[dtype].options_schema)}")
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
        d = self.device(did)
        if options:
            merged = {**d.get("options", {}), **options}
            d["options"] = {k: v for k, v in merged.items() if v is not None}
        for k, v in flags.items():
            if k not in ("required", "record", "markers", "calibrate", "type"):
                raise EditError(f"unknown device setting '{k}'")
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
                elif "if" in n:
                    lines.append(f"{pad}- if {n['if']}:")
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
                lines.append(f"    - {c['id']} ({c['type']}; {timing}){flags} {summary}")
        return "\n".join(lines)


def _short(v: Any, n: int = 40) -> str:
    s = repr(v) if not isinstance(v, str) else v.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (_drop_none(v) if isinstance(v, dict) else v) for k, v in d.items() if v is not None}
