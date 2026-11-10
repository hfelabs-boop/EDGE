"""Gorilla importer (Task Builder 1 and 2, Experiment Builder downloads).

A Gorilla task is a **spreadsheet** (CSV or XLSX: one row per trial, a ``display`` column naming what to show,
``randomise_trials``/``randomise_blocks`` columns, and your own columns) plus the **task structure**: displays
made of screens made of zones. The structure can be given as a JSON file (``task.json``); it is read tolerantly,
so both Task Builder 1 zone names (``content_text``, ``response_keyboard``, ``timelimit_screen`` …) and Task
Builder 2 names (``Text``, ``KeyboardResponse``, ``TimeLimitScreen`` …) are understood, and spreadsheet bindings
written ``$${Column}``, ``${spreadsheet:Column}`` or ``{"spreadsheet": "Column"}``.

* each display's screens become screens (routines); zones become items: text and rich text, image, audio,
  fixation, keyboard response (keys, correct answer), button response and continue button (clickable buttons),
  time limits (screen and response), feedback (approximated);
* spreadsheet rows become trial lists in their order: consecutive rows with the same ``randomise_trials`` number
  are shuffled together, blocks with ``randomise_blocks`` numbers are shuffled as blocks;
* without a structure file, one screen per display is built from the spreadsheet columns (approximate).

Unsupported zones (video, sliders, rating scales, scripts …) are listed in the report.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from .base import (
    Ids,
    ImportError_,
    ImportResult,
    avoid_column_clashes,
    html_to_text,
    ident,
    inside,
    key_name,
    ms,
    num,
    read_text,
)

W, H = 1024, 768
META = {"randomise_blocks", "randomise_trials", "display", "showprogressbar"}
IMG = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp")
AUD = (".wav", ".mp3", ".ogg", ".m4a", ".flac")
BIND = re.compile(r"\$\$\{\s*([^}]+?)\s*\}|\$\{\s*spreadsheet\s*:\s*([^}]+?)\s*\}", re.I)


# ------------------------------------------------------------------ reading files
def read_sheet(path: Path) -> list[dict[str, Any]]:
    """Rows of a Gorilla spreadsheet (CSV or XLSX) as {column: text}."""
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError as e:
            raise ImportError_("reading a Gorilla .xlsx spreadsheet needs 'openpyxl' (pip install openpyxl), or "
                               "download the spreadsheet from Gorilla as CSV and import that") from e
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:      # a damaged or cut-short workbook (zip) file
            raise ImportError_(f"{path.name} could not be read as an Excel workbook ({type(e).__name__}): the file "
                               "may be damaged or cut short. Download the spreadsheet from Gorilla again") from e
        ws = wb.worksheets[0]
        cells = [["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                  for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = read_text(path)
        delim = "\t" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else ","
        cells = list(csv.reader(io.StringIO(text, newline=""), delimiter=delim))
    cells = [r for r in cells if any(str(c).strip() for c in r)]
    if not cells:
        return []
    header = [str(h).strip() for h in cells[0]]
    rows = []
    for r in cells[1:]:
        rows.append({h: (str(r[i]).strip() if i < len(r) else "") for i, h in enumerate(header) if h})
    return rows


def header_of(path: Path) -> list[str]:
    try:
        if path.suffix.lower() == ".xlsx":
            rows = read_sheet(path)
            return list(rows[0]) if rows else []
    except ImportError_:
        import importlib.util
        import zipfile
        if not zipfile.is_zipfile(path) or importlib.util.find_spec("openpyxl") is None:
            return ["display", "randomise_trials"]     # damaged, or openpyxl missing: the import explains it
        return []
    except Exception:
        return []
    try:
        first = read_text(path).split("\n", 1)[0]
    except Exception:
        return []
    delim = "\t" if first.count("\t") > first.count(",") else ","
    return [c.strip().strip('"') for c in first.split(delim)]


def is_gorilla_sheet(path: Path) -> bool:
    cols = {c.lower() for c in header_of(path)}
    return "display" in cols and bool(cols & {"randomise_trials", "randomise_blocks", "showprogressbar"})


def read_structure(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def find_displays(data: Any) -> list[dict[str, Any]]:
    """Displays anywhere in the structure: a 'displays' list or {name: display}."""
    if isinstance(data, dict):
        d = data.get("displays") or data.get("Displays")
        if isinstance(d, list):
            return [x for x in d if isinstance(x, dict)]
        if isinstance(d, dict):
            return [{"name": k, **v} for k, v in d.items() if isinstance(v, dict)]
        for v in data.values():
            found = find_displays(v)
            if found:
                return found
    elif isinstance(data, list):
        for v in data:
            found = find_displays(v)
            if found:
                return found
    return []


def looks_like_structure(data: Any) -> bool:
    disp = find_displays(data)
    return bool(disp) and any(isinstance(s, dict) and ("zones" in s or "Zones" in s)
                              for d in disp for s in (d.get("screens") or d.get("Screens") or []))


# ------------------------------------------------------------------ the converter
class Converter:
    def __init__(self, path: Path):
        self.path = path
        self.folder = path.parent
        self.res = ImportResult({}, path, "Gorilla")
        self.ids = Ids()
        self.routines: dict[str, Any] = {}
        self.display_nodes: dict[str, list[Any]] = {}
        self.columns: set[str] = set()
        self.file_cols: dict[str, str] = {}             # spreadsheet column -> "image"/"sound"
        self.key_cols: set[str] = set()
        self.structure: dict[str, Any] | None = None

    # ------------------------------------------------------------- values
    def bound(self, v: Any) -> Any:
        """A zone setting: a literal, or $column when it is bound to the spreadsheet."""
        if isinstance(v, dict):
            col = v.get("spreadsheet") or (v.get("column") if str(v.get("binding", "")).lower() == "spreadsheet" else None)
            if col:
                return self.col(str(col))
            if "value" in v:
                return self.bound(v["value"])
            return None
        if isinstance(v, str):
            m = BIND.fullmatch(v.strip())
            if m:
                return self.col(m.group(1) or m.group(2))
            if BIND.search(v):
                parts, last = [], 0
                for mm in BIND.finditer(v):
                    parts.append(v[last:mm.start()].replace("{", "{{").replace("}", "}}"))
                    col = ident(mm.group(1) or mm.group(2))
                    self.columns.add(col)
                    parts.append("{" + col + "}")
                    last = mm.end()
                parts.append(v[last:].replace("{", "{{").replace("}", "}}"))
                return "$f" + repr("".join(parts))
        return v

    def col(self, name: str) -> str:
        self.columns.add(ident(name))
        return "$" + ident(name)

    def file_ref(self, v: Any, kind: str) -> Any:
        """A stimulus file: a column (whose values are checked when the rows are read) or a file name."""
        if isinstance(v, str) and v.startswith("$") and re.fullmatch(r"\$\w+", v):
            self.file_cols[v[1:]] = kind
            return v
        if isinstance(v, str) and v:
            return self.locate(v)
        return v

    def locate(self, name: str) -> str:
        """Gorilla stimuli are named without folders: find the file next to the import or in a stimuli folder."""
        for cand in (name, f"stimuli/{name}", f"Stimuli/{name}", f"resources/{name}"):
            p = inside(self.folder, cand)
            if p is not None and p.is_file():
                self.res.assets.add(cand)
                return cand
        self.res.assets.add(name)          # reported as missing by finalize
        return name

    # ------------------------------------------------------------- zones -> items
    def screen(self, display: str, screen: dict[str, Any]) -> str:
        sname = str(screen.get("name") or screen.get("Name") or "screen")
        rid = self.ids.make(f"{display}_{sname}" if display else sname, "screen")
        where = f"displays.{display}.{sname}"
        comps: list[dict[str, Any]] = []
        cids = Ids()
        routine: dict[str, Any] = {"components": comps}
        zones = [z for z in (screen.get("zones") or screen.get("Zones") or []) if isinstance(z, dict)]
        response = None
        buttons: list[tuple[str, Any]] = []
        response_limit = None
        for z in zones:
            ztype = str(z.get("type") or z.get("zoneType") or z.get("kind") or z.get("Type") or "")
            key = re.sub(r"[^a-z]", "", ztype.lower())
            zname = str(z.get("name") or z.get("Name") or key or "zone")
            settings = {**z, **(z.get("settings") if isinstance(z.get("settings"), dict) else {})}
            pos = self.layout(settings)
            if "timelimit" in key or key in ("timelimitscreen", "timelimitresponse"):
                d = self.bound(settings.get("duration", settings.get("time", settings.get("timeLimit"))))
                d = ms(d) if isinstance(d, (int, float)) else (f"$({d[1:]}) / 1000" if isinstance(d, str) and d.startswith("$") else None)
                if d is None:
                    self.res.note("approx", f"{where}.{zname}", "time limit without a duration: not converted")
                elif "response" in key:
                    response_limit = d
                else:
                    routine["duration"] = d
            elif "keyboard" in key:
                keys = settings.get("keys") or settings.get("allowed") or settings.get("responses") or []
                if isinstance(keys, str):
                    keys = [k for k in re.split(r"[,\s]+", keys) if k]
                keys = [key_name(k) for k in keys if isinstance(k, str)]
                response = {"id": cids.make("resp"), "type": "keyboard", "end_routine": True}
                if keys:
                    response["keys"] = keys
                ans = self.bound(settings.get("correctAnswer", settings.get("answer", settings.get("correct"))))
                if isinstance(ans, str) and ans:
                    response["correct"] = ans if ans.startswith("$") else key_name(ans)
                    if ans.startswith("$"):
                        self.key_cols.add(ans[1:])
            elif "continue" in key or ("button" in key and "response" in key) or key in ("button", "buttons",
                                                                                          "responsebuttontext"):
                labels = settings.get("buttons") or settings.get("options") or [settings.get("text") or
                                                                                  settings.get("label") or "Continue"]
                if isinstance(labels, str):
                    labels = [x.strip() for x in labels.split("\n") if x.strip()]
                for lab in labels:
                    buttons.append((zname if len(labels) == 1 else f"{zname}_{lab}", self.bound(lab)))
            elif "fixation" in key:
                comps.append({"id": cids.make(zname, "fixation"), "type": "fixation", "pos": pos})
            elif "feedback" in key:
                good = str(settings.get("correct") or "Correct")
                bad = str(settings.get("incorrect") or "Incorrect")
                comps.append({"id": cids.make(zname, "feedback"), "type": "text", "pos": pos, "color": "black",
                              "text": f"$({good!r} if resp.corr else {bad!r})", "height": 36})
                fd = settings.get("duration")
                if isinstance(fd, (int, float)) and "duration" not in routine:
                    routine["duration"] = ms(fd)
                self.res.note("approx", f"{where}.{zname}", "the feedback zone became a text that shows "
                              f"'{good}' or '{bad}' depending on the last response called 'resp'; check it")
            elif "audio" in key or "sound" in key:
                f = self.file_ref(self.bound(settings.get("audio") or settings.get("file") or settings.get("content")
                                             or settings.get("src") or ""), "sound")
                comps.append({"id": cids.make(zname, "sound"), "type": "sound", "sound": f})
            elif "image" in key or "picture" in key:
                f = self.file_ref(self.bound(settings.get("image") or settings.get("file") or settings.get("content")
                                             or settings.get("src") or ""), "image")
                c = {"id": cids.make(zname, "image"), "type": "image", "image": f, "pos": pos}
                if pos != [0, 0] and settings.get("layout"):
                    lay = settings["layout"]
                    if isinstance(lay, dict) and isinstance(lay.get("w"), (int, float)) and isinstance(lay.get("h"), (int, float)):
                        c["size"] = [round(lay["w"] / 100 * W), round(lay["h"] / 100 * H)]
                comps.append(c)
            elif "text" in key or "markdown" in key or "html" == key or "instructions" in key:
                raw = self.bound(settings.get("content") or settings.get("text") or settings.get("html") or "")
                c = {"id": cids.make(zname, "text"), "type": "text", "pos": pos, "color": "black",
                     "height": 28 if len(str(raw)) > 20 else 48, "wrap_width": round(W * 0.8)}
                if isinstance(raw, str) and not raw.startswith("$"):
                    text, style, dropped = html_to_text(raw)
                    c["text"] = text
                    c.update(style)
                    if dropped:
                        self.res.note("approx", f"{where}.{zname}", f"text styling not kept: {', '.join(dropped)}")
                else:
                    c["text"] = raw
                comps.append(c)
            else:
                self.res.note("unsupported", f"{where}.{zname}", f"the '{ztype or 'unnamed'}' zone was not converted;"
                              " add it by hand (video: a html item; ratings and sliders: a slider or survey item)")
        if buttons:
            n = len(buttons)
            ids = []
            for i, (bname, label) in enumerate(buttons):
                x = round((i - (n - 1) / 2) * 220)
                bid = cids.make(f"{bname}_button", "button")
                comps.append({"id": bid, "type": "shape", "shape": "rect", "size": [200, 60], "fill": "#e8e8e8",
                              "line_color": "#888888", "pos": [x, -round(H * 0.35)]})
                comps.append({"id": cids.make(f"{bname}_label", "label"), "type": "text", "text": label,
                              "color": "black", "height": 24, "pos": [x, -round(H * 0.35)]})
                ids.append(bid)
            comps.append({"id": cids.make("click", "click"), "type": "mouse", "clickable": ids, "end_routine": True})
        if response is not None:
            if response_limit is not None:
                response["duration"] = response_limit
            comps.append(response)
        elif response_limit is not None and "duration" not in routine:
            routine["duration"] = response_limit
        if not response and not buttons and "duration" not in routine:
            if any(c["type"] in ("text", "image", "fixation") for c in comps):
                routine["duration"] = 2.0
                self.res.note("approx", where, "the screen has no response, button or time limit (Gorilla would "
                              "wait for one): it was set to 2 s")
            else:
                routine["duration"] = 0.5
        if not comps:
            comps.append({"id": "blank", "type": "wait"})
        self.routines[rid] = routine
        self.res.count("screens")
        return rid

    def layout(self, z: dict[str, Any]) -> list[float]:
        lay = z.get("layout") or z.get("position")
        if isinstance(lay, dict) and isinstance(lay.get("x"), (int, float)) and isinstance(lay.get("y"), (int, float)):
            return [round((lay["x"] / 100 - 0.5) * W), round((0.5 - lay["y"] / 100) * H)]
        return [0, 0]

    # ------------------------------------------------------------- displays
    def displays(self, structure: dict[str, Any]) -> None:
        for d in find_displays(structure):
            name = str(d.get("name") or d.get("Name") or "display")
            screens = [s for s in (d.get("screens") or d.get("Screens") or []) if isinstance(s, dict)]
            self.display_nodes[name] = [self.screen(name, s) for s in screens]
            self.res.count("displays")

    def inferred_display(self, name: str, rows: list[dict[str, Any]]) -> None:
        """Without the task structure: one screen from the columns this display's rows fill in."""
        cols = [c for c in rows[0] if c.lower() not in META and any(r.get(c) for r in rows)]
        comps: list[dict[str, Any]] = []
        answer = next((c for c in cols if re.fullmatch(r"(?i)answer|correct\w*|correct_?answer|key|response", c)), None)
        for c in cols:
            if c == answer:
                continue
            vals = [r[c] for r in rows if r.get(c)]
            if all(v.lower().endswith(IMG) for v in vals):
                comps.append({"id": ident(c), "type": "image", "image": self.file_ref(f"${ident(c)}", "image")})
                self.columns.add(ident(c))
            elif all(v.lower().endswith(AUD) for v in vals):
                comps.append({"id": ident(c), "type": "sound", "sound": self.file_ref(f"${ident(c)}", "sound")})
                self.columns.add(ident(c))
            elif re.fullmatch(r"(?i)stim\w*|word|text|target|item|question|instructions?|message", c):
                comps.append({"id": ident(c), "type": "text", "text": f"${ident(c)}", "color": "black", "height": 40})
                self.columns.add(ident(c))
        if answer:
            keys = sorted({key_name(r[answer]) for r in rows if r.get(answer)})
            comps.append({"id": "resp", "type": "keyboard", "keys": keys, "correct": f"${ident(answer)}",
                          "end_routine": True})
            self.columns.add(ident(answer))
            self.key_cols.add(ident(answer))
        else:
            if not comps:
                comps.append({"id": "text", "type": "text", "text": f"({name})", "color": "black", "height": 40})
            comps.append({"id": "resp", "type": "keyboard", "keys": ["space"], "end_routine": True})
        rid = self.ids.make(name, "screen")
        self.routines[rid] = {"components": comps}
        self.res.count("screens")
        self.display_nodes[name] = [rid]
        self.res.note("approx", f"displays.{name}", f"no task structure: the '{name}' screen was built from the "
                      f"spreadsheet columns ({', '.join(cols) or 'none'}). Download the task structure from Gorilla "
                      "too, or check the screen against your task")

    # ------------------------------------------------------------- rows -> flow
    def flow(self, rows: list[dict[str, Any]]) -> list[Any]:
        cols = {c.lower(): c for c in (rows[0] if rows else {})}
        dcol, tcol, bcol = cols.get("display"), cols.get("randomise_trials"), cols.get("randomise_blocks")
        for r in rows:
            r["_display"] = r.get(dcol, "") if dcol else ""
            r["_trials"] = r.get(tcol, "") if tcol else ""
            r["_block"] = r.get(bcol, "") if bcol else ""
        out: list[Any] = []
        i = 0
        while i < len(rows):
            if rows[i]["_block"]:
                j = i
                while j < len(rows) and rows[j]["_block"]:
                    j += 1
                out.append(self.block_loop(rows[i:j]))
                i = j
            else:
                j = i
                while j < len(rows) and not rows[j]["_block"]:
                    j += 1
                out += self.segments(rows[i:j])
                i = j
        return out

    def block_loop(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        blocks: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            blocks.setdefault(r["_block"], []).append(r)
        children = [{"if": f"$randomise_blocks == {num(b)!r}", "then": self.segments(rs)} for b, rs in blocks.items()]
        self.res.count("trial lists")
        self.res.note("info", "spreadsheet", f"randomise_blocks: the {len(blocks)} blocks ({', '.join(blocks)}) run "
                      "in random order")
        return {"loop": self.ids.make("blocks", "loop"), "conditions": [{"randomise_blocks": num(b)} for b in blocks],
                "order": "random", "children": children}

    def segments(self, rows: list[dict[str, Any]]) -> list[Any]:
        out: list[Any] = []
        i = 0
        while i < len(rows):
            r = rows[i]
            j = i + 1
            if r["_trials"]:
                while j < len(rows) and rows[j]["_trials"] == r["_trials"]:
                    j += 1
            else:
                while j < len(rows) and not rows[j]["_trials"] and rows[j]["_display"] == r["_display"]:
                    j += 1
            out += self.segment(rows[i:j])
            i = j
        return out

    def segment(self, rows: list[dict[str, Any]]) -> list[Any]:
        displays = list(dict.fromkeys(r["_display"] for r in rows))
        for d in displays:
            if d not in self.display_nodes:
                if self.structure is not None:
                    self.res.note("unsupported", f"displays.{d or '(empty)'}", f"the spreadsheet shows display "
                                  f"'{d}', which the task structure does not have")
                    self.display_nodes[d] = []
                else:
                    self.inferred_display(d, [r for r in rows if r["_display"] == d])
        data = [{ident(k): v for k, v in r.items() if not k.startswith("_") and k.lower() not in META} for r in rows]
        needs_rows = any(any(v not in ("", None) for v in row.values()) for row in data)
        random = bool(rows[0]["_trials"]) and len(rows) > 1
        if len(rows) == 1 and not needs_rows:
            return list(self.display_nodes.get(displays[0], []))
        if len(displays) == 1:
            children = list(self.display_nodes.get(displays[0], []))
        else:
            children = [{"if": f"$display == {d!r}", "then": list(self.display_nodes.get(d, []))} for d in displays]
            for row, r in zip(data, rows):
                row["display"] = r["_display"]
        if not children:
            return []
        conds = [{k: self.cell(k, v) for k, v in row.items()} for row in data]
        self.res.count("trial lists")
        return [{"loop": self.ids.make(displays[0] if len(displays) == 1 else "trials", "loop"),
                 "conditions": conds, "order": "random" if random else "sequential", "children": children}]

    def cell(self, col: str, v: Any) -> Any:
        if col in self.file_cols and isinstance(v, str) and v:
            return self.locate(v)
        if col in self.key_cols and isinstance(v, str) and v:
            return key_name(v)
        return num(v) if isinstance(v, str) and v != "" else (None if v == "" else v)

    # ------------------------------------------------------------- whole task
    def run(self, sheet: Path | None, structure: dict[str, Any] | None) -> ImportResult:
        res = self.res
        self.structure = structure
        if structure is not None:
            self.displays(structure)
        rows = read_sheet(sheet) if sheet else []
        if sheet and not rows:
            res.note("unsupported", "spreadsheet", f"{sheet.name} has no rows")
        if sheet:
            res.note("info", "spreadsheet", f"trials read from {sheet.name} ({len(rows)} rows)")
        if rows:
            flow = self.flow(rows)
        else:
            flow = [n for nodes in self.display_nodes.values() for n in nodes]
            if structure is not None:
                res.note("approx", "spreadsheet", "no spreadsheet was found next to the task structure: every "
                         "display runs once, in the order of the structure. Download the spreadsheet from Gorilla "
                         "and import both files together")
        if rows and any(c.lower() == "showprogressbar" for c in rows[0]):
            res.note("info", "spreadsheet", "ShowProgressBar is not converted (EDGE shows no progress bar)")
        if rows:
            res.note("info", "spreadsheet", "every spreadsheet column is kept in the trial lists, so it is saved with "
                     "each trial as in Gorilla's data")
        if not flow:
            res.note("unsupported", "flow", "no displays or spreadsheet rows were found")
        name = ident(str((structure or {}).get("name") or (sheet or self.path).stem))
        res.doc = {"name": name, "description": f"Imported from Gorilla ({self.path.name})",
                   "settings": {"window": {"size": [W, H], "background": "#ffffff", "units": "px"}},
                   "devices": [], "variables": {}, "routines": self.routines, "flow": flow}
        avoid_column_clashes(res.doc)
        return res


def _sheet_for(structure: dict[str, Any] | None, folder: Path, res: ImportResult) -> Path | None:
    named = None
    if structure:
        for key in ("spreadsheet", "spreadsheets", "Spreadsheet"):
            v = structure.get(key)
            if isinstance(v, list) and v:
                if len(v) > 1:
                    res.note("approx", "spreadsheet", f"the task has {len(v)} spreadsheets: the first one was used. "
                             "Import again with another one to convert it")
                v = v[0]
            if isinstance(v, dict):
                v = v.get("file") or v.get("name")
            if isinstance(v, str):
                named = v
                break
    if named:
        p = inside(folder, named)
        if p is not None and p.is_file():
            return p
        for ext in (".csv", ".xlsx"):
            p = inside(folder, Path(named).stem + ext)
            if p is not None and p.is_file():
                return p
    cands = sorted(f for f in folder.iterdir() if f.suffix.lower() in (".csv", ".xlsx") and is_gorilla_sheet(f))
    if len(cands) > 1:
        res.note("approx", "spreadsheet", f"several spreadsheets were found ({', '.join(c.name for c in cands)}): "
                 f"{cands[0].name} was used")
    return cands[0] if cands else None


def import_gorilla(path: Path) -> ImportResult:
    if path.suffix.lower() == ".json":
        structure = read_structure(path)
        if structure is None or not looks_like_structure(structure):
            raise ImportError_(f"{path.name} is not a Gorilla task structure (no displays with screens and zones "
                               "were found): the file may be damaged or cut short")
        conv = Converter(path)
        sheet = _sheet_for(structure, path.parent, conv.res)
        return conv.run(sheet, structure)
    conv = Converter(path)
    structure = None
    for j in sorted(path.parent.glob("*.json")):
        s = read_structure(j)
        if s is not None and looks_like_structure(s):
            named = str(s.get("spreadsheet") or "")
            if not named or Path(named).stem.lower() == path.stem.lower():
                structure = s
                conv.res.note("info", "structure", f"screens read from the task structure {j.name}")
                break
    if structure is None:
        conv.res.note("approx", "structure", "no task structure (JSON) was found next to the spreadsheet: the screens "
                      "were built from the spreadsheet columns alone")
    return conv.run(path, structure)


def looks_like_gorilla(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in (".csv", ".xlsx", ".tsv"):
        return is_gorilla_sheet(path)
    if suffix == ".json":
        s = read_structure(path)
        if s is not None:
            return looks_like_structure(s)
        try:            # a structure cut short is still recognised, so that the import can say what is wrong
            text = read_text(path)[:200000]
        except OSError:
            return False
        return '"zones"' in text.lower() and ('"displays"' in text.lower() or '"screens"' in text.lower())
    return False
