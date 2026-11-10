"""Running a study day: the participant queue, session notes, the day's run log, pause/stop with a reason.

Everything is stored next to the experiment, in plain files a person can open:

* ``<experiment folder>/.edge/queue/<experiment>.json``: the planned participants (ID, session, group /
  counterbalancing condition, status planned / running / done / aborted / no-show), in order. It can be
  filled automatically (the next free IDs, groups in rotation), imported from and exported to CSV.
* ``<experiment folder>/.edge/runlog/<experiment>.jsonl``: one line per thing that happened (a session
  started, ended, was stopped with a reason, paused, a participant did not show up …), with the time.
* ``<session folder>/notes.json`` and ``notes.md``: the experimenter's notes on that session, each with the
  time it was written (and how far into the session). They can be written during the session and edited
  afterwards; the Data page shows them and exports add a ``notes`` column to the sessions table.

The builder's endpoints (``/api/studyday/...``, see :func:`handle`) use these functions; sessions started
from the Run page are linked to their queue entry and keep it up to date (running → done / aborted).
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

STATUSES = ("planned", "running", "done", "aborted", "no-show")
QUEUE_DIR = ".edge/queue"
LOG_DIR = ".edge/runlog"
CSV_COLUMNS = ["participant", "session", "group", "status", "comment", "data", "started", "ended", "reason"]
CSV_ALIASES = {"participant": ("participant", "participant_id", "id", "subject", "subject_id", "pid", "sub"),
               "session": ("session", "ses", "session_id"),
               "group": ("group", "condition", "counterbalance", "counterbalancing", "list", "version", "order"),
               "status": ("status",), "comment": ("comment", "comments", "remark")}
_lock = threading.RLock()


class StudyDayError(ValueError):
    """Something in the request can't be done (shown to the experimenter as is)."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic(path: Path, text: str) -> None:
    from .storage import atomic_write
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text)


def clean_id(value: Any, what: str = "participant ID") -> str:
    """A participant ID / session / group as text that is safe in a folder name."""
    s = str(value if value is not None else "").strip()
    if len(s) > 64:
        raise StudyDayError(f"the {what} is too long (64 characters at most)")
    if s in (".", "..") or re.search(r"[\\/:*?\"<>|\x00-\x1f]", s):
        raise StudyDayError(f"the {what} {s!r} can't be used: no slashes or : * ? \" < > |")
    return s


# --------------------------------------------------------------------------------------- the queue
def queue_file(exp_path: Path) -> Path:
    return exp_path.parent / QUEUE_DIR / f"{exp_path.stem}.json"


def load_queue(exp_path: Path) -> dict[str, Any]:
    p = queue_file(exp_path)
    try:
        q = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(q, dict) or not isinstance(q.get("entries"), list):
            raise ValueError
    except (OSError, ValueError):
        q = {"experiment": exp_path.name, "groups": [], "entries": []}
    q.setdefault("groups", [])
    for e in q["entries"]:
        e.setdefault("extra", {})
    return q


def save_queue(exp_path: Path, q: dict[str, Any]) -> None:
    q["experiment"] = exp_path.name
    q["updated"] = _now()
    _atomic(queue_file(exp_path), json.dumps(q, indent=1, ensure_ascii=False))


def _new_id(q: dict[str, Any]) -> str:
    n = max([int(e["id"][1:]) for e in q["entries"] if re.fullmatch(r"q\d+", str(e.get("id", "")))] + [0]) + 1
    return f"q{n}"


def _entry(q: dict[str, Any], eid: str) -> dict[str, Any]:
    for e in q["entries"]:
        if e.get("id") == eid:
            return e
    raise StudyDayError(f"no participant {eid!r} in the queue (it was removed?)")


def make_entry(q: dict[str, Any], participant: str, session: str = "1", group: str = "", **extra: Any) -> dict[str, Any]:
    e = {"id": _new_id(q), "participant": clean_id(participant), "session": clean_id(session or "1", "session"),
         "group": clean_id(group or "", "group"), "status": "planned", "comment": "", "run_id": None, "data": None,
         "started": None, "ended": None, "reason": None,
         "extra": {clean_id(k, "column name"): str(v) for k, v in extra.items() if k and v not in (None, "")}}
    if not e["participant"]:
        raise StudyDayError("every planned participant needs an ID")
    q["entries"].append(e)
    return e


def next_ids(taken: list[str], count: int, start: str | None = None) -> list[str]:
    """The next ``count`` participant IDs after every number in ``taken`` ('007' → '008', '009' …), keeping
    the zero-padding; from ``start`` when given."""
    nums = [t for t in taken if str(t).isdigit()]
    width = max([len(t) for t in nums] + [3])
    if start not in (None, ""):
        if not str(start).isdigit():
            raise StudyDayError("the first ID must be a number (e.g. 001) to count on from it")
        first, width = int(start), max(width if not nums else 0, len(str(start)))
    else:
        first = max([int(t) for t in nums] + [0]) + 1
    out, n, used = [], first, set(taken)
    while len(out) < count:
        s = str(n).zfill(width)
        if s not in used:
            out.append(s)
        n += 1
    return out


def add_planned(q: dict[str, Any], count: int, used: list[str], start: str | None = None, session: str = "1",
                groups: list[str] | None = None) -> list[dict[str, Any]]:
    """Plan ``count`` more participants with the next free IDs; groups (counterbalancing) in rotation,
    carrying on from the last planned one."""
    if not (1 <= int(count) <= 500):
        raise StudyDayError("plan between 1 and 500 participants at a time")
    groups = [clean_id(g, "group") for g in (groups if groups is not None else q.get("groups") or []) if str(g).strip()]
    if groups:
        q["groups"] = groups
    taken = [e["participant"] for e in q["entries"]] + list(used)
    ids = next_ids(taken, int(count), start)
    k = sum(1 for e in q["entries"] if e.get("group") in groups) if groups else 0
    out = []
    for i, pid in enumerate(ids):
        out.append(make_entry(q, pid, session, groups[(k + i) % len(groups)] if groups else ""))
    return out


def update_entry(q: dict[str, Any], eid: str, fields: dict[str, Any]) -> dict[str, Any]:
    e = _entry(q, eid)
    for k, v in fields.items():
        if k in ("participant", "session", "group"):
            v = clean_id(v, {"participant": "participant ID"}.get(k, k))
            if k == "participant" and not v:
                raise StudyDayError("every planned participant needs an ID")
            e[k] = v
        elif k == "status":
            if v not in STATUSES:
                raise StudyDayError(f"status must be one of {', '.join(STATUSES)}")
            if e["status"] == "running" and v != "running":
                raise StudyDayError("this participant's session is running: stop it on the Run page first")
            e["status"] = v
        elif k in ("comment", "reason"):
            e[k] = str(v or "")[:2000]
        elif k == "extra" and isinstance(v, dict):
            e["extra"] = {clean_id(a, "column name"): str(b) for a, b in v.items() if a}
        else:
            raise StudyDayError(f"'{k}' can't be changed here")
    return e


def delete_entry(q: dict[str, Any], eid: str) -> None:
    e = _entry(q, eid)
    if e["status"] == "running":
        raise StudyDayError("this participant's session is running: stop it first")
    q["entries"].remove(e)


def move_entry(q: dict[str, Any], eid: str, by: int) -> None:
    e = _entry(q, eid)
    i = q["entries"].index(e)
    j = max(0, min(len(q["entries"]) - 1, i + int(by)))
    q["entries"].insert(j, q["entries"].pop(i))


def next_planned(q: dict[str, Any]) -> dict[str, Any] | None:
    return next((e for e in q["entries"] if e["status"] == "planned"), None)


def import_csv(q: dict[str, Any], text: str, replace: bool = False) -> dict[str, Any]:
    """Planned participants from a CSV/TSV (columns participant, session, group, status, comment; other columns
    are passed to the session as participant fields). Rows of IDs already in the queue update them."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise StudyDayError("the file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise StudyDayError("no rows under the header line")
    header = {h.strip().lower(): h for h in (rows[0].keys() if rows else []) if h}
    col = {k: next((header[a] for a in names if a in header), None) for k, names in CSV_ALIASES.items()}
    if not col["participant"]:
        raise StudyDayError("the file needs a 'participant' column (or id / subject)")
    known = {c for c in col.values() if c} | {header.get(k) for k in ("data", "started", "ended", "reason", "run_id")}
    if replace:
        if any(e["status"] == "running" for e in q["entries"]):
            raise StudyDayError("a session is running: import after it has ended, or add to the queue")
        q["entries"] = []
    added = updated = 0
    groups: list[str] = list(q.get("groups") or [])
    for r in rows:
        pid = clean_id((r.get(col["participant"]) or "").strip())
        if not pid:
            continue
        ses = clean_id((r.get(col["session"]) or "1").strip() if col["session"] else "1", "session") or "1"
        grp = clean_id((r.get(col["group"]) or "").strip(), "group") if col["group"] else ""
        status = (r.get(col["status"]) or "").strip().lower().replace("noshow", "no-show").replace("no show", "no-show") \
            if col["status"] else ""
        extra = {k.strip(): (v or "").strip() for k, v in r.items() if k and k not in known and (v or "").strip()}
        hit = next((e for e in q["entries"] if e["participant"] == pid and e["session"] == ses), None)
        if hit is None:
            hit = make_entry(q, pid, ses, grp, **extra)
            added += 1
        else:
            if hit["status"] != "running":
                hit["group"] = grp or hit["group"]
                hit["extra"].update({clean_id(k, "column name"): v for k, v in extra.items()})
            updated += 1
        if status in STATUSES and status != "running" and hit["status"] != "running":
            hit["status"] = status
        if col["comment"] and (r.get(col["comment"]) or "").strip():
            hit["comment"] = r[col["comment"]].strip()[:2000]
        if grp and grp not in groups:
            groups.append(grp)
    q["groups"] = groups
    return {"added": added, "updated": updated}


def export_csv(q: dict[str, Any]) -> str:
    extra_cols: list[str] = []
    for e in q["entries"]:
        extra_cols += [k for k in e.get("extra", {}) if k not in extra_cols and k not in CSV_COLUMNS]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS + extra_cols)
    for e in q["entries"]:
        w.writerow([e.get(c) or "" for c in CSV_COLUMNS] + [e.get("extra", {}).get(c, "") for c in extra_cols])
    return buf.getvalue()


# --------------------------------------------------------------------------------------- the run log
def log_file(exp_path: Path) -> Path:
    return exp_path.parent / LOG_DIR / f"{exp_path.stem}.jsonl"


def log_event(exp_path: Path, kind: str, text: str = "", **fields: Any) -> dict[str, Any]:
    ev = {"time": _now(), "kind": kind, "text": text, **{k: v for k, v in fields.items() if v not in (None, "")}}
    p = log_file(exp_path)
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return ev


def read_log(exp_path: Path, day: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """The run log's lines of one day (YYYY-MM-DD, default today; 'all' for every day), oldest first."""
    day = day or datetime.now().date().isoformat()
    out = []
    try:
        lines = log_file(exp_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if day == "all" or str(ev.get("time", "")).startswith(day):
            out.append(ev)
    return out[-limit:]


# --------------------------------------------------------------------------------------- session notes
def read_notes(folder: Path) -> list[dict[str, Any]]:
    try:
        d = json.loads((folder / "notes.json").read_text(encoding="utf-8"))
        return [n for n in (d.get("notes") if isinstance(d, dict) else d) or [] if isinstance(n, dict)]
    except (OSError, ValueError):
        return []


def notes_markdown(notes: list[dict[str, Any]], title: str = "") -> str:
    lines = [f"# Notes{(': ' + title) if title else ''}", ""]
    for n in notes:
        t = str(n.get("time", ""))[11:16] or str(n.get("time", ""))
        el = n.get("elapsed")
        when = t + (f" (+{int(el // 60)}:{int(el % 60):02d})" if isinstance(el, (int, float)) else "")
        tag = " *(automatic)*" if n.get("auto") else ""
        edited = f" *(edited {str(n['edited'])[11:16]})*" if n.get("edited") else ""
        lines.append(f"- **{when}**{tag} {n.get('text', '')}{edited}")
    return "\n".join(lines) + "\n"


def write_notes(folder: Path, notes: list[dict[str, Any]], title: str = "") -> None:
    with _lock:
        _atomic(folder / "notes.json", json.dumps({"notes": notes, "updated": _now()}, indent=1, ensure_ascii=False))
        _atomic(folder / "notes.md", notes_markdown(notes, title))


def notes_text(folder: Path) -> str:
    """Every note of a session on one line, for tables: "10:42 electrode C4 re-gelled | 10:51 sneezed"."""
    return " | ".join(f"{str(n.get('time', ''))[11:16]} {n.get('text', '')}".strip() for n in read_notes(folder))


def edit_notes(notes: list[dict[str, Any]], op: str, text: str | None = None, index: int | None = None,
               elapsed: float | None = None, auto: bool = False) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if op == "add":
        if not text:
            raise StudyDayError("the note is empty")
        notes.append({"time": _now(), "elapsed": round(elapsed, 1) if isinstance(elapsed, (int, float)) else None,
                      "text": text[:5000], **({"auto": True} if auto else {})})
    elif op in ("edit", "delete"):
        if not isinstance(index, int) or not 0 <= index < len(notes):
            raise StudyDayError("that note doesn't exist (any more)")
        if op == "delete":
            notes.pop(index)
        else:
            if not text:
                raise StudyDayError("the note is empty: delete it instead")
            notes[index] = {**notes[index], "text": text[:5000], "edited": _now()}
    else:
        raise StudyDayError("op must be add, edit or delete")
    return notes


# --------------------------------------------------------------------------------------- linking runs
def _exp_of(app: Any, state: dict[str, Any]) -> Path:
    return app.safe_path(state["path"])


def run_title(state: dict[str, Any]) -> str:
    return f"participant {state.get('participant')}, session {state.get('session') or 1}"


def on_run_started(app: Any, rid: str, state: dict[str, Any], entry_id: str | None = None) -> None:
    """A session started from the builder: link it to its queue entry (the one asked for, or the planned
    entry with the same participant and session), write the run log, and follow its monitor events."""
    exp = _exp_of(app, state)
    state.setdefault("notes", [])
    with _lock:
        q = load_queue(exp)
        e = None
        if entry_id:
            e = _entry(q, entry_id)
        else:
            e = next((x for x in q["entries"] if x["participant"] == str(state.get("participant"))
                      and x["session"] == str(state.get("session") or "1") and x["status"] in ("planned", "no-show")),
                     None)
        if e is not None:
            e.update(status="running", run_id=rid, started=_now(), ended=None, reason=None)
            state["queue_entry"] = e["id"]
            save_queue(exp, q)
    log_event(exp, "start", f"started {run_title(state)}" + (" (simulated devices)" if state.get("simulate") else ""),
              participant=state.get("participant"), session=state.get("session"), run=rid,
              group=e.get("group") if e else None)
    state.setdefault("listeners", []).append(lambda ev: _on_event(app, state, ev))
    state.setdefault("on_exit", []).append(lambda: _on_exit(app, rid, state))


def _on_event(app: Any, state: dict[str, Any], ev: dict[str, Any]) -> None:
    kind = ev.get("type")
    if kind == "start" and ev.get("data_dir"):
        state["data_dir"] = ev["data_dir"]
        flush_notes(state)
    elif kind in ("paused", "resumed"):
        exp = _exp_of(app, state)
        words = "paused" if kind == "paused" else f"resumed after {ev.get('paused_s', 0):.0f} s"
        log_event(exp, kind, f"{words} ({run_title(state)})", participant=state.get("participant"),
                  session=state.get("session"))
        add_run_note(state, words.capitalize() + (f" before screen “{ev['before']}”" if ev.get("before") else ""), auto=True)


def _elapsed(state: dict[str, Any]) -> float | None:
    mon = state.get("monitor") or {}
    for k in ("end", "last", "devices"):
        if (mon.get(k) or {}).get("elapsed") is not None:
            return float(mon[k]["elapsed"])
    return None


def add_run_note(state: dict[str, Any], text: str, auto: bool = False) -> list[dict[str, Any]]:
    running = state.get("proc") is None or state["proc"].poll() is None
    edit_notes(state.setdefault("notes", []), "add", text,
               elapsed=(_elapsed(state) if state.get("data_dir") else 0.0) if running else None, auto=auto)
    flush_notes(state)
    return state["notes"]


def flush_notes(state: dict[str, Any]) -> None:
    """Write a running session's notes into its folder (once the session has made it)."""
    d = state.get("data_dir")
    if d and Path(d).is_dir() and (state.get("notes") or (Path(d) / "notes.json").exists()):
        write_notes(Path(d), state["notes"], run_title(state))


def _on_exit(app: Any, rid: str, state: dict[str, Any]) -> None:
    exp = _exp_of(app, state)
    mon = state.get("monitor") or {}
    end = mon.get("end") or {}
    rc = state["proc"].returncode if state.get("proc") is not None else None
    started = bool(state.get("data_dir"))
    if not started:
        status, words = "planned", "could not start (nothing recorded; the participant stays planned)"
    elif end.get("aborted") or state.get("stop_reason") or rc == 1:
        status = "aborted"
        why = state.get("stop_reason") or ("the experiment stopped with an error" if end.get("crash") else "stopped early")
        words = f"stopped: {why}"
    else:
        status, words = "done", "finished"
    data_rel = None
    if started:
        try:
            data_rel = str(Path(state["data_dir"]).resolve().relative_to(app.root)).replace("\\", "/")
        except ValueError:
            data_rel = state["data_dir"]
        flush_notes(state)
    with _lock:
        q = load_queue(exp)
        eid = state.get("queue_entry")
        e = next((x for x in q["entries"] if x.get("id") == eid), None) if eid else None
        if e is not None and e.get("run_id") == rid:
            e.update(status=status, ended=_now() if started else None, data=data_rel or e.get("data"),
                     reason=state.get("stop_reason") if status == "aborted" else None)
            if not started:
                e.update(run_id=None, started=None)
            save_queue(exp, q)
    log_event(exp, "end" if status == "done" else "abort" if status == "aborted" else "failed",
              f"{run_title(state)} {words}", participant=state.get("participant"), session=state.get("session"),
              run=rid, data=data_rel, trials=end.get("trials"))


# --------------------------------------------------------------------------------------- the builder's API
POST_FIELDS: dict[str, dict[str, tuple[Any, bool]]] = {
    "/api/studyday/queue": {"path": (str, True), "op": (str, True), "id": (str, False), "fields": (dict, False),
                            "count": ((int, float), False), "start": (str, False), "session": (str, False),
                            "groups": (list, False), "csv": (str, False), "replace": (bool, False),
                            "by": ((int, float), False)},
    "/api/studyday/start": {"path": (str, True), "id": (str, False), "simulate": (bool, False),
                            "fullscreen": (bool, False), "mirror": (bool, False)},
    "/api/studyday/pause": {"id": (str, True), "pause": (bool, True)},
    "/api/studyday/stop": {"id": (str, True), "reason": (str, False)},
    "/api/studyday/notes": {"op": (str, True), "run": (str, False), "session": (str, False), "text": (str, False),
                            "index": ((int, float), False)},
    "/api/studyday/noshow": {"path": (str, True), "id": (str, True), "reason": (str, False)},
}
QUERY_FIELDS: dict[str, list[str]] = {}     # GETs: a missing ?field= is a BadRequest when it is read (server.Query)


class Raw:
    """A non-JSON answer (a CSV download, a PNG)."""

    def __init__(self, data: bytes, ctype: str, filename: str | None = None):
        self.data, self.ctype, self.filename = data, ctype, filename


def _exp_path(app: Any, rel: str) -> Path:
    p = app.safe_path(rel)
    if not p.is_file() or p.suffix.lower() not in (".yaml", ".yml", ".json"):
        raise StudyDayError(f"{rel} is not an experiment file")
    return p


def _run(app: Any, rid: str) -> dict[str, Any]:
    st = app.runs.get(str(rid))
    if not st:
        raise StudyDayError("unknown run (the builder was restarted?)")
    return st


def queue_view(app: Any, exp: Path) -> dict[str, Any]:
    q = load_queue(exp)
    rel = str(exp.relative_to(app.root)).replace("\\", "/")
    for e in q["entries"]:          # a "running" entry whose session is gone (the builder was restarted)
        st = app.runs.get(str(e.get("run_id"))) if e.get("run_id") else None
        e["live"] = bool(st and st["proc"].poll() is None)
    nxt = next_planned(q)
    counts = {s: sum(1 for e in q["entries"] if e["status"] == s) for s in STATUSES}
    return {"path": rel, "groups": q.get("groups", []), "entries": q["entries"], "next": nxt["id"] if nxt else None,
            "counts": counts, "log": read_log(exp), "file": str(queue_file(exp).relative_to(app.root)).replace("\\", "/")}


def session_folder(app: Any, rel: str) -> Path:
    p = app.safe_path(rel)
    if not p.is_dir() or not ((p / "session.json").exists() or (p / "trials.jsonl").exists()):
        raise StudyDayError(f"{rel} is not a session folder")
    return p


def handle(app: Any, method: str, path: str, q: dict[str, Any], body: Any) -> Any:
    """Every /api/studyday/... request (the server has already applied its guard and checked the fields)."""
    from .builder.server import BadRequest
    try:
        return _handle(app, method, path, q, body)
    except StudyDayError as e:
        raise BadRequest(str(e)) from None


def _handle(app: Any, method: str, path: str, q: dict[str, Any], body: Any) -> Any:
    if method == "GET":
        if path == "/api/studyday/queue":
            return queue_view(app, _exp_path(app, q["path"]))
        if path == "/api/studyday/export":
            exp = _exp_path(app, q["path"])
            return Raw(("﻿" + export_csv(load_queue(exp))).encode("utf-8"), "text/csv; charset=utf-8",
                       f"{exp.stem}_participants.csv")
        if path == "/api/studyday/log":
            return {"log": read_log(_exp_path(app, q["path"]), q.get("day") or None)}
        if path == "/api/studyday/notes":
            if q.get("run"):
                st = _run(app, q["run"])
                if not st.get("notes") and st.get("data_dir"):
                    st["notes"] = read_notes(Path(st["data_dir"]))
                return {"notes": st.get("notes", []), "data_dir": st.get("data_dir")}
            if q.get("session"):
                return {"notes": read_notes(session_folder(app, q["session"]))}
            raise StudyDayError("the request needs ?run=… or ?session=…")
        if path == "/api/studyday/mirror":
            st = _run(app, q["id"])
            png = st.get("mirror_png")
            if not png:
                return {"error": "no picture of the participant's screen yet"}, 404
            return Raw(png, "image/png")
        if path == "/api/studyday/screens":
            from .syscheck import screens
            return {"screens": screens()}
        return {"error": "not found"}, 404
    # POST
    if path == "/api/studyday/queue":
        exp = _exp_path(app, body["path"])
        op = body["op"]
        res: dict[str, Any] = {}
        with _lock:
            qd = load_queue(exp)
            if op == "add":
                used = app.next_participant(str(exp.relative_to(app.root)))["used"]
                added = add_planned(qd, int(body.get("count") or 1), used, body.get("start"),
                                    body.get("session") or "1", body.get("groups"))
                res["added"] = [e["id"] for e in added]
            elif op == "update":
                update_entry(qd, body.get("id") or "", body.get("fields") or {})
            elif op == "delete":
                delete_entry(qd, body.get("id") or "")
            elif op == "move":
                move_entry(qd, body.get("id") or "", int(body.get("by") or 0))
            elif op == "import":
                res.update(import_csv(qd, body.get("csv") or "", bool(body.get("replace"))))
            elif op == "groups":
                qd["groups"] = [clean_id(g, "group") for g in body.get("groups") or [] if str(g).strip()]
            elif op == "clear_done":
                qd["entries"] = [e for e in qd["entries"] if e["status"] not in ("done", "no-show")]
            else:
                raise StudyDayError("op must be add, update, delete, move, import, groups or clear_done")
            save_queue(exp, qd)
        if op == "import":
            log_event(exp, "queue", f"imported {res['added']} planned participant(s), updated {res['updated']}")
        return {**queue_view(app, exp), **res}
    if path == "/api/studyday/noshow":
        exp = _exp_path(app, body["path"])
        with _lock:
            qd = load_queue(exp)
            e = update_entry(qd, body["id"], {"status": "no-show", "reason": body.get("reason") or ""})
            save_queue(exp, qd)
        log_event(exp, "no-show", f"participant {e['participant']} did not come" +
                  (f": {body['reason']}" if body.get("reason") else ""), participant=e["participant"], session=e["session"])
        return queue_view(app, exp)
    if path == "/api/studyday/start":
        exp = _exp_path(app, body["path"])
        rel = str(exp.relative_to(app.root)).replace("\\", "/")
        qd = load_queue(exp)
        e = _entry(qd, body["id"]) if body.get("id") else next_planned(qd)
        if e is None:
            raise StudyDayError("nobody is planned: add participants to the queue first")
        if e["status"] == "running":
            raise StudyDayError(f"participant {e['participant']} is already running")
        fields = {**e.get("extra", {}), "participant": e["participant"], "session": e["session"]}
        if e.get("group"):
            fields["group"] = e["group"]
        out = app.run_real(rel, fields, bool(body.get("simulate")), body.get("fullscreen"),
                           mirror=bool(body.get("mirror")), queue_entry=e["id"])
        return {**out, "entry": e["id"], "participant": e["participant"], "session": e["session"]}
    if path == "/api/studyday/pause":
        st = _run(app, body["id"])
        if st["proc"].poll() is not None:
            raise StudyDayError("the session has ended")
        pf = st.get("pause_file")
        if not pf:
            raise StudyDayError("this session can't be paused")
        if body["pause"]:
            Path(pf).touch()
        else:
            Path(pf).unlink(missing_ok=True)
        st["pausing"] = bool(body["pause"])
        return {"paused": bool(body["pause"])}
    if path == "/api/studyday/stop":
        st = _run(app, body["id"])
        reason = (body.get("reason") or "").strip()[:500]
        if st["proc"].poll() is None:
            st["stop_reason"] = reason or "stopped by the experimenter"
            add_run_note(st, "Stopped by the experimenter" + (f": {reason}" if reason else ""), auto=True)
            if st.get("pause_file"):
                Path(st["pause_file"]).unlink(missing_ok=True)
        return app.run_stop(body["id"])
    if path == "/api/studyday/notes":
        op = body["op"]
        idx = body.get("index")
        idx = int(idx) if isinstance(idx, (int, float)) else None
        if body.get("run"):
            st = _run(app, body["run"])
            if not st.get("notes") and st.get("data_dir"):
                st["notes"] = read_notes(Path(st["data_dir"]))
            if op == "add":
                add_run_note(st, body.get("text") or "")
            else:
                edit_notes(st.setdefault("notes", []), op, body.get("text"), idx)
                flush_notes(st)
            if op == "add":
                log_event(_exp_of(app, st), "note", body.get("text", "").strip()[:200],
                          participant=st.get("participant"), session=st.get("session"))
            return {"notes": st["notes"], "data_dir": st.get("data_dir")}
        if body.get("session"):
            folder = session_folder(app, body["session"])
            notes = edit_notes(read_notes(folder), op, body.get("text"), idx)
            info = {}
            try:
                info = json.loads((folder / "session.json").read_text(encoding="utf-8")).get("participant") or {}
            except (OSError, ValueError):
                pass
            write_notes(folder, notes, f"participant {info.get('participant', '?')}, session {info.get('session', 1)}"
                        if info else folder.name)
            return {"notes": notes}
        raise StudyDayError("say which session: run or session")
    return {"error": "not found"}, 404
