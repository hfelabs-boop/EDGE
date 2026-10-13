""""Try it": play an experiment (or one screen of it) inside the builder.

A :class:`BrowserBackend` runs the real engine on the real clock without opening a window. On every
flip it publishes what was drawn; the builder polls that and paints it on a canvas, and sends the
keys and clicks back. Devices are simulated and the data goes to ``data/dry_runs/try``. Timing in
a browser tab is approximate (a few frames), which is fine for checking that a task makes sense,
but sessions with participants use ``edge run`` (the experiment window).
"""

from __future__ import annotations

import copy
import itertools
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from .backends.base import InputEvent
from .backends.headless import HeadlessBackend
from .clock import now as master_now


class BrowserBackend(HeadlessBackend):
    name = "browser"

    def __init__(self, size=(1280, 720), refresh_rate: float = 60.0):
        super().__init__(size=size, refresh_rate=refresh_rate, keep_frame_log=False, realtime=True)
        self.lock = threading.Lock()
        self.frame: dict[str, Any] = {"seq": 0, "drawn": [], "background": "#000000"}
        self.background: Any = "#000000"
        self.page_url: str | None = None
        self._sound_seq = itertools.count(1)
        self.sound_events: list[dict[str, Any]] = []
        self.last_seen = master_now()

    def set_background(self, color: Any) -> None:
        self.background = color

    def open(self, window: dict[str, Any]) -> None:
        super().open(window)
        self.background = window.get("background", "#000000")

    def flip(self) -> float:
        drawn = self._drawn
        t = super().flip()
        with self.lock:
            self.frame = {"seq": self.n_flips, "t": t, "drawn": [[k, _jsonable(p)] for k, p in drawn],
                          "background": self.background, "page": self.page_url}
        return t

    def play_sound(self, source: Any, volume: float = 1.0, **kw: Any) -> Any:
        rec = super().play_sound(source, volume, **kw)
        with self.lock:
            self.sound_events.append({"id": next(self._sound_seq), "source": _jsonable(source), "volume": volume,
                                      **{k: _jsonable(v) for k, v in kw.items()}})
            self.sound_events = self.sound_events[-20:]
        return rec

    def show_url(self, url: str | None) -> None:
        """Called by the HTML component instead of opening a browser window."""
        self.page_url = url

    # ------------------------------------------------------------ input from the browser
    def push(self, kind: str, name: str, down: bool = True, pos: tuple[float, float] | None = None) -> None:
        now = master_now()
        if kind == "key" and name == "escape":
            self.escape_at = now
            return
        self.schedule(InputEvent(kind, name, now, down, tuple(pos) if pos is not None else None))

    def snapshot(self, since_sound: int = 0) -> dict[str, Any]:
        self.last_seen = master_now()
        with self.lock:
            out = dict(self.frame)
            out["sounds"] = [s for s in self.sound_events if s["id"] > since_sound]
        out["size"] = list(self.size)
        return out


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


# ---------------------------------------------------------------- one screen with real trial values
_BARE_KEYS = {"when", "end_if", "if", "start_if", "stop_if", "only_if", "start", "duration"}


def _routine_reads(routine: dict[str, Any]) -> set[str]:
    """Names the expressions of a routine read ($resp.corr → 'resp')."""
    from . import expressions
    out: set[str] = set()

    def walk(v: Any, key: str = "") -> None:
        if isinstance(v, str):
            if v.startswith("$$"):
                return
            if v.startswith("$"):
                out.update(expressions.names_in(v[1:]))
            elif key in _BARE_KEYS and v.strip():
                out.update(expressions.names_in(v))
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, str(k))
    walk(routine)
    return out


def _routine_defines(routine: dict[str, Any]) -> set[str]:
    """Names a routine gives a value: its components' results and the variables it sets."""
    out: set[str] = set()
    for c in (routine or {}).get("components") or []:
        if isinstance(c, dict):
            out.add(str(c.get("id")))
            if c.get("type") == "variable" and isinstance(c.get("set"), dict):
                out.update(str(k) for k in c["set"])
    for rule in (routine or {}).get("rules") or []:
        for a in (rule.get("do") or []) if isinstance(rule, dict) else []:
            if isinstance(a, dict) and isinstance(a.get("set"), dict):
                out.update(str(k) for k in a["set"])
    return out


def single_screen_plan(doc: dict[str, Any], routine_id: str) -> list[str]:
    """The screens "only this screen" really has to run: the screen itself, and the screens before it in the same
    trial (or the same part of the flow) whose results it reads. 'feedback' reads resp.corr from 'trial', so trying
    it alone would stop on a name that doesn't exist yet: it is tried together with 'trial'."""
    routines = doc.get("routines") or {}

    def find(nodes: list[Any]) -> list[Any] | None:
        for n in nodes or []:
            if n == routine_id or (isinstance(n, dict) and n.get("routine") == routine_id):
                return nodes
            if isinstance(n, dict):
                for kids in [n.get("children"), n.get("then"), n.get("else"),
                             *[(st or {}).get("run") for st in (n.get("states") or {}).values()]]:
                    r = find(kids or [])
                    if r is not None:
                        return r
        return None

    siblings = find(doc.get("flow") or []) or [routine_id]
    names = [n if isinstance(n, str) else n.get("routine") if isinstance(n, dict) else None for n in siblings]
    i = next(k for k, n in enumerate(names) if n == routine_id) if routine_id in names else 0
    reads = _routine_reads(routines.get(routine_id) or {}) - _routine_defines(routines.get(routine_id) or {})
    first = i
    for j in range(i - 1, -1, -1):
        rid = names[j]
        if not rid or rid not in routines:
            break         # a loop, a branch or a workflow in between: stop there
        if reads & _routine_defines(routines[rid]):
            first = j
    return [n for n in names[first:i + 1] if n]


def single_screen_experiment(doc: dict[str, Any], routine_id: str, max_trials: int = 5) -> dict[str, Any]:
    """A copy of the experiment whose flow runs just one screen, inside the loops it normally sits in
    (so trial-list values are real), for at most ``max_trials`` rows. A screen that reads the results of an earlier
    screen of the same trial ('feedback' reads resp.corr) runs together with it (:func:`single_screen_plan`)."""
    doc = copy.deepcopy(doc)
    if routine_id not in (doc.get("routines") or {}):
        raise KeyError(f"no screen called '{routine_id}'")

    def find(nodes: list[Any], path: list[dict]) -> list[dict] | None:
        for n in nodes or []:
            if n == routine_id or (isinstance(n, dict) and n.get("routine") == routine_id):
                return path
            if isinstance(n, dict):
                if "loop" in n:
                    r = find(n.get("children") or [], path + [n])
                    if r is not None:
                        return r
                for k in ("then", "else"):
                    r = find(n.get(k) or [], path)
                    if r is not None:
                        return r
                for st in (n.get("states") or {}).values():
                    r = find((st or {}).get("run") or [], path)
                    if r is not None:
                        return r
        return None

    loops = find(doc.get("flow") or [], []) or []
    screens = single_screen_plan(doc, routine_id)
    node: Any = screens if len(screens) > 1 else routine_id
    for i, lp in enumerate(reversed(loops)):
        lp = {k: v for k, v in lp.items() if k not in ("children", "stop_if")}
        lp["children"] = list(node) if isinstance(node, list) else [node]
        if i == 0:
            if lp.get("staircase"):
                lp["staircase"] = {**lp["staircase"], "max_trials": min(int(lp["staircase"].get("max_trials", 50)), max_trials)}
            else:
                lp["stop_if"] = f"${lp['loop']}.n >= {max(int(max_trials), 1) - 1}"
        else:
            lp["stop_if"] = "$True"
        node = lp
    doc["flow"] = list(node) if isinstance(node, list) else [node]
    doc.setdefault("settings", {}).setdefault("data", {})["exports"] = []
    # what the experiment measures is summarised per participant: a single screen never needs it, and a measure
    # of a trial list that isn't in this cut-down flow would stop it from starting
    doc.pop("measures", None)
    return doc


def _needs_the_rest(full: dict[str, Any], cut: dict[str, Any], routine: str, base_dir: Path, errors: list) -> list[str]:
    """Names the chosen screen reads that only exist in the whole experiment (the trial list before a 'thanks'
    screen: $trials.total): then the cut-down copy's errors are not the experiment's problems."""
    from .model import Experiment
    try:
        if any(i.level == "error" for i in Experiment.from_dict(copy.deepcopy(full), base_dir=base_dir).validate()):
            return []
    except Exception:
        return []
    reads = _routine_reads((cut.get("routines") or {}).get(routine) or {})
    return sorted(n for n in reads if any(f"'{n}'" in i.message for i in errors))


# ---------------------------------------------------------------- a playing session
class Player:
    """One "Try it" session running in a background thread."""

    def __init__(self, doc: dict[str, Any], base_dir: Path, data_root: Path, routine: str | None = None,
                 max_trials: int = 5):
        from .model import Experiment

        full = doc
        if routine:
            doc = single_screen_experiment(doc, routine, max_trials)
        else:
            doc = copy.deepcopy(doc)
            doc.setdefault("settings", {}).setdefault("data", {})["exports"] = []
        self.doc = doc
        self.problem: dict[str, Any] | None = None
        self.exp = Experiment.from_dict(doc, base_dir=base_dir)
        errors = [i for i in self.exp.validate() if i.level == "error"]
        if errors and routine:
            outside = _needs_the_rest(full, doc, routine, base_dir, errors)
            if outside:
                raise ValueError(f"“{routine}” uses {', '.join('“' + n + '”' for n in outside)} from earlier in the "
                                 "experiment, so it can only be tried as part of the whole experiment: use Try it "
                                 "(whole experiment)")
        if errors:
            msgs = list(dict.fromkeys(i.message for i in errors))     # plain sentences, not validator paths
            raise ValueError("; ".join(msgs[:3]) + (f" (and {len(msgs) - 3} more)" if len(msgs) > 3 else ""))
        from .model import window_size
        self.backend = BrowserBackend(size=window_size(self.exp.settings))
        self.data_root = data_root
        self.summary: dict[str, Any] | None = None
        self.error: str | None = None
        self.logs: list[str] = []
        self.started = time.time()
        self.runner: Any = None
        self.total: int | None = None           # expected trials, for "trial 3 of 18" in the Try-it bar
        self.screens = single_screen_plan(doc, routine) if routine else []
        try:
            from .wizard import estimate_experiment
            self.total = int(estimate_experiment(self.exp).get("trials") or 0) or None
            if routine and self.total:
                self.total = min(self.total, max(int(max_trials), 1))
        except Exception:
            self.total = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _run(self) -> None:
        from .engine import Runner
        from .runtime import Session
        try:
            session = Session(self.exp, self.backend, participant={"participant": "try", "session": "1"},
                              data_dir=str(self.data_root), simulate_devices=True,
                              log=lambda *a: self.logs.append(" ".join(map(str, a))))
            self.runner = Runner(session)
            self.summary = self.runner.run()
        except Exception as e:  # shown in the builder
            from .diagnostics import format_report, plain_error
            rep = getattr(e, "report", None)
            self.error = format_report(rep) if rep else f"{type(e).__name__}: {e}"
            try:
                self.problem = plain_error(rep or {"type": type(e).__name__, "message": str(e)}, self.doc)
            except Exception:
                self.problem = None
            self.logs.append(traceback.format_exc())

    def _watchdog(self) -> None:
        # stop sessions whose tab went away (nobody asked for a frame for 30 s)
        while self.thread.is_alive():
            time.sleep(1.0)
            if master_now() - self.backend.last_seen > 30:
                self.stop()
                return

    @property
    def running(self) -> bool:
        return self.thread.is_alive()

    def progress(self) -> dict[str, Any]:
        """Which trial is showing: {"trial": 3, "trials": 18} (``trial`` is 0 before the first trial, and
        ``in_trial`` is false on screens outside every trial list, such as instructions)."""
        r = self.runner
        out: dict[str, Any] = {"trial": 0, "trials": self.total, "in_trial": False}
        if r is None:
            return out
        try:     # read while the engine runs in its own thread: copies, and never fail the frame for it
            done = set(r.trial_keys)
            stack = list(r.stack)
            n = len(done)
            if stack:
                key = "|".join([f"{m['id']}:{m['state']}#{m['visit']}" for m in list(r.machines)]
                               + [f"{f['loop']}={f['state']['n']}" for f in stack])
                n += 0 if key in done else 1
            out.update(trial=n, in_trial=bool(stack))
        except Exception:
            pass
        return out

    def stop(self) -> None:
        self.backend.escape_at = master_now()

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"running": self.running, "error": self.error, "log": self.logs[-8:]}
        if self.error and getattr(self, "problem", None):
            out["problem"] = self.problem
        if self.summary is not None:
            out["result"] = results_summary(self.summary)
        return out


def results_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """What happened, in plain words: trials, accuracy, mean response time."""
    import json

    rows = []
    p = Path(summary.get("data_dir", ""))
    if (p / "trials.jsonl").exists():
        rows = [json.loads(line) for line in (p / "trials.jsonl").read_text().splitlines() if line.strip()]
    try:
        from .export import SessionTables, wide_trials
        trials = [r for r in wide_trials(SessionTables(p))[1] if r.get("loop")]
    except Exception:
        trials = []
    scored = trials or rows          # responses inside trials; instruction screens don't count
    corr = [v for r in scored for k, v in r.items() if k.endswith(".corr") and isinstance(v, (int, float))]
    rts = [v for r in scored for k, v in r.items() if k.endswith(".rt") and isinstance(v, (int, float))
           and not isinstance(v, bool)]
    n_trials = len(trials)
    out = {"screens": len(rows), "trials": n_trials, "responses": len(rts),
           "accuracy": round(sum(corr) / len(corr), 3) if corr else None,
           "mean_rt": round(sum(rts) / len(rts), 3) if rts else None,
           "aborted": bool(summary.get("aborted")), "data_dir": summary.get("data_dir"),
           "errors": summary.get("errors") or [],
           "note": "Times measured in a browser tab are approximate. Use 'Run with a participant' for real data."}
    return out


class PlayManager:
    """Keeps at most one Try-it session per builder."""

    def __init__(self, root: Path):
        self.root = root
        self.player: Player | None = None

    def start(self, doc: dict[str, Any], base_dir: Path, routine: str | None = None, max_trials: int = 5,
              data_root: Path | None = None) -> dict[str, Any]:
        if self.player is not None and self.player.running:
            self.player.stop()
            self.player.thread.join(timeout=3)
        self.player = Player(doc, base_dir, data_root or (self.root / "data" / "dry_runs" / "try"), routine, max_trials)
        return {"ok": True, "size": list(self.player.backend.size), "screens": self.player.screens}

    def frame(self, since_sound: int = 0) -> dict[str, Any]:
        if self.player is None:
            return {"running": False}
        snap = self.player.backend.snapshot(since_sound)
        snap["running"] = self.player.running
        snap.update(self.player.progress())
        if not self.player.running:
            snap.update(self.player.status())
        return snap

    def input(self, ev: dict[str, Any]) -> dict[str, Any]:
        if self.player is None or not self.player.running:
            return {"ok": False}
        self.player.backend.push(str(ev.get("kind", "key")), str(ev.get("name", "")), bool(ev.get("down", True)),
                                 ev.get("pos"))
        return {"ok": True}

    def stop(self) -> dict[str, Any]:
        if self.player is not None:
            self.player.stop()
            self.player.thread.join(timeout=5)
            return self.player.status()
        return {"running": False}
