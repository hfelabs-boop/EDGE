"""Operations the assistant may apply, the assistant-only ones, and the file ledger.

The ledger is the only way the assistant writes files: inside the experiment's folder, trial lists only
(``.csv`` / ``.tsv``), never over a file it didn't create, and every file it wrote can be taken back
(when a job fails, is stopped, or the researcher presses Discard) as long as nobody changed it since.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Callable

from ..editing import ALLOWED_OPS, EditError, ExperimentDoc

LEDGER_SUFFIXES = (".csv", ".tsv")


class FileLedger:
    def __init__(self, folder: Path | None):
        self.folder = Path(folder).resolve() if folder else None
        self.entries: list[tuple[Path, str, bytes | None]] = []    # (path, sha256 written, previous content)
        self.lock = threading.Lock()
        self.closed = False
        # the experiment's participant-data folders (data/, settings.data.dir before and after the changes); set
        # by the job once the documents are known
        self.data_roots: Callable[[], list[Path]] | None = None

    def _check(self, path: Path) -> Path:
        if self.folder is None:
            raise EditError("this experiment has no folder yet, so trial-list files can't be written: keep the rows "
                            "inline (set_conditions with rows, without write_file)")
        p = Path(path).resolve()
        if self.folder not in p.parents:
            raise EditError("files must be inside the experiment's folder")
        parts = p.relative_to(self.folder).parts
        from .attachments import data_roots, is_data_path
        roots = self.data_roots() if self.data_roots else data_roots(self.folder)
        if "data" in parts[:-1] or any(x.startswith(".") for x in parts) or is_data_path(self.folder, p, roots):
            raise EditError("files can't be written into data/ (or the experiment's own data folder), a session "
                            "folder or a hidden folder")
        if p.suffix.lower() not in LEDGER_SUFFIXES:
            raise EditError("the assistant can only write trial lists (.csv or .tsv)")
        return p

    def ours(self, p: Path) -> bool:
        return any(e[0] == p for e in self.entries)

    def write(self, path: Path, text: str | bytes) -> None:
        from ..storage import atomic_write
        data = text.encode("utf-8") if isinstance(text, str) else text
        with self.lock:
            if self.closed:
                raise EditError("the assistant was stopped")
            p = self._check(path)
            previous = None
            if p.exists():
                if not self.ours(p):
                    raise EditError(f"{p.relative_to(self.folder).as_posix()} already exists; EDGE never overwrites "
                                    "files: use another file name")
                previous = p.read_bytes()
            atomic_write(p, data)
            self.entries.append((p, hashlib.sha256(data).hexdigest(), previous))

    def checkpoint(self) -> int:
        return len(self.entries)

    def rollback_to(self, cp: int | None) -> list[str]:
        removed: list[str] = []
        with self.lock:
            cp = cp or 0
            for p, sha, prev in reversed(self.entries[cp:]):
                try:
                    if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == sha:
                        if prev is None:
                            p.unlink()
                            removed.append(p.relative_to(self.folder).as_posix())   # type: ignore[arg-type]
                            try:
                                p.parent.rmdir()
                            except OSError:
                                pass
                        else:
                            p.write_bytes(prev)
                except OSError:
                    continue
            del self.entries[cp:]
        return removed

    def rollback_all(self) -> list[str]:
        return self.rollback_to(0)

    def close(self) -> None:
        with self.lock:
            self.closed = True

    def files(self) -> list[str]:
        out: list[str] = []
        for p, _, _ in self.entries:
            if self.folder is not None and p.exists():
                rel = p.relative_to(self.folder).as_posix()
                if rel not in out:
                    out.append(rel)
        return out


# ============================================================================ assistant-only operations
def add_image_component(doc: ExperimentDoc, rid: str, file: str, cid: str | None = None, fit: str = "screen",
                        height: float | None = None, pos: list | None = None, start: float | None = None,
                        duration: float | None = None, position: int | None = None) -> dict[str, Any]:
    """Add a picture. ``file``: a picture in the experiment's folder (images/cat.png) or "$column" (a picture per
    trial). ``fit``: "native" (no size), "screen" (shrink to 90 % of the window if larger, aspect kept) or
    "height" (size = [height*w/h, height]). Sizes are computed from the file only with pixel units."""
    from ..pitfalls import image_size
    if not isinstance(file, str) or not file:
        raise EditError("file must be a picture path (images/cat.png) or a trial-list column ($picture)")
    if fit not in ("native", "screen", "height"):
        raise EditError("fit must be native, screen or height")
    win = (doc.doc.get("settings") or {}).get("window") or {}
    units = win.get("units") or "px"
    size_win = win.get("size") or [1280, 720]
    props: dict[str, Any] = {"image": file}
    note = ""
    dims = None
    if not file.startswith("$"):
        if doc.path is None:
            raise EditError("the experiment has no folder yet, so pictures can't be found: save it first")
        p = (doc.path.parent / file).resolve()
        if doc.path.parent.resolve() not in p.parents or not p.is_file():
            raise EditError(f"no picture {file} in the experiment's folder")
        dims = image_size(p)
    if fit != "native":
        if units != "px":
            note = f"the experiment measures sizes in {units}, so the picture keeps its own size"
        elif dims is None and fit == "screen":
            note = "the picture's size can't be known before it runs (a trial-list column): it keeps its own size"
        elif fit == "height":
            if not height:
                raise EditError("fit 'height' needs height (pixels)")
            if dims:
                props["size"] = [round(float(height) * dims[0] / dims[1]), float(height)]
            else:
                note = "the width can't be known before it runs; give the size yourself if all pictures share it"
        elif dims and (dims[0] > 0.9 * size_win[0] or dims[1] > 0.9 * size_win[1]):
            scale = min(0.9 * size_win[0] / dims[0], 0.9 * size_win[1] / dims[1])
            props["size"] = [round(dims[0] * scale), round(dims[1] * scale)]
    if pos is not None:
        props["pos"] = pos
    if start is not None:
        props["start"] = start
    if duration is not None:
        props["duration"] = duration
    new_id = doc.add_component(rid, "image", props, cid, position)
    out: dict[str, Any] = {"id": new_id, "size": props.get("size")}
    if note:
        out["note"] = note
    return out


EXTRA_OPS: dict[str, Callable[..., Any]] = {"add_image_component": add_image_component}

OP_DOCS: dict[str, str] = {
    "add_routine": "a screen (instructions, trial, feedback…); add_to_flow puts it in the experiment's order",
    "update_routine": "change a screen's duration cap, end_if or description ('' or null removes)",
    "rename_routine": "rename a screen everywhere",
    "remove_routine": "delete a screen and its uses in the flow",
    "duplicate_routine": "copy a screen under a new name (not added to the flow)",
    "add_component": "add an item to a screen; properties hold its settings and timing (start, duration, end_routine…)",
    "update_component": "change an item: set_props (null removes a key), unset, new_id",
    "remove_component": "delete an item",
    "move_component": "change an item's drawing order (0 = back)",
    "insert_flow": "put a screen (or a prepared loop/branch dict) into the flow, a loop (parent=loop id) or a workflow state (parent='workflow.state')",
    "remove_from_flow": "take a screen or loop out of the flow (definitions stay; a loop's children stay unless keep_children=false)",
    "move_in_flow": "move a screen or loop to another position (or into parent)",
    "add_loop": "a trial list repeating children once per row: conditions = file path, rows, or {factorial: …}; order, repeats; wrap=true moves existing flow items into it",
    "update_loop": "change a loop: changes = {conditions, order, repeats, max_repeat, stop_if, staircase, select, id}",
    "set_conditions": "give a loop its trial list: rows (inline), file, or factorial; write_file=true with rows writes a CSV",
    "add_branch": "if / otherwise in the flow: condition '$expr', then [screens], otherwise [screens]",
    "add_device": "hardware (only when the researcher mentions it); test runs simulate every device",
    "update_device": "change a device's options or flags (required, record, markers, calibrate)",
    "remove_device": "remove a device",
    "update_settings": "deep-merge settings (window, data, markers, participant…); null removes a key",
    "set_variables": "set experiment variables (initial values)",
    "set_info": "the experiment's name and description",
    "add_state_machine": "a workflow: states {name: {run: [...], next: [{if, goto}], max_visits}} (practice until good, screening)",
    "update_state": "add or change a workflow phase (run, next routes, max_visits, rename_to, make_start)",
    "remove_state": "delete a workflow phase",
    "add_rule": "a routine rule: when '$expr' do [{end_routine: true} | {start: id} | {stop: id} | {set: {...}} | {marker: name} | {goto: state} | {log: text}]",
    "remove_rule": "delete a routine rule by index",
    "set_measures": "declare measures: [{id, label, role: outcome|factor|covariate|check|info, column, summary, trials, loop, expect, units}]",
    "add_survey": "a questionnaire screen: questions mix library instruments ({instrument: phq9}) and own questions",
    "add_image_component": "a picture item from an attached image (file) or a trial-list column ($picture), sized to fit the screen",
}


def allowed_ops() -> list[str]:
    return sorted(ALLOWED_OPS | set(EXTRA_OPS))
