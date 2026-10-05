"""The frame-locked engine: walks the flow, runs routines frame by frame.

Timing model
------------
* Routine time ``t = 0`` is the first screen flip of the routine.
* Before each flip the engine predicts its time (``last_flip + frame_interval``)
  and decides which components start/stop *on that flip*, so a stimulus with
  ``start: 0.5, duration: 0.2`` is drawn on exactly round(0.2 * Hz) frames.
* After the flip, onsets/offsets are stamped with the *measured* flip time and
  markers are sent immediately (TTL lines go high within microseconds of the
  frame being handed to the display).
* Input events carry their own OS timestamps; RT = event time - onset flip time.
"""

from __future__ import annotations

from typing import Any, Iterable

from . import expressions
from .components import component_registry
from .components.base import FINISHED, NOT_STARTED, STARTED, Component, Results
from .conditions import Staircase, load_conditions, order_trials, select_rows
from .model import Branch, Experiment, Loop, Routine, RoutineRef, StateMachine
from .runtime import ExperimentAborted, Session


class LoopState(Results):
    """Exposed to expressions under the loop id: ``trials.n``, ``trials.total``, and live performance:
    ``trials.accuracy``, ``trials.n_correct``, ``trials.n_responses``, ``trials.mean_rt`` (so far in this loop run)."""


class StateJump(Exception):
    """Raised by a routine rule ``goto`` to leave the current state of a state machine immediately."""

    def __init__(self, target: str):
        super().__init__(target)
        self.target = target


def _perf(acc: dict[str, list[float]]) -> dict[str, Any]:
    corr, rts = acc["corr"], acc["rt"]
    return {"n_responses": len(corr), "n_correct": int(sum(corr)),
            "accuracy": round(sum(corr) / len(corr), 4) if corr else None,
            "mean_rt": round(sum(rts) / len(rts), 5) if rts else None}


class RoutineRun:
    def __init__(self, routine: Routine, session: Session, runner: "Runner"):
        self.routine = routine
        self.session = session
        self.runner = runner
        self.components: dict[str, Component] = {}
        self.t0: float | None = None
        self.frame = 0
        self._end = False
        self._ns_cache: dict[str, Any] | None = None
        self.goto: str | None = None
        self.fired_rules: list[str] = []

    # ----------------------------------------------------------- namespace
    def namespace(self) -> dict[str, Any]:
        ns: dict[str, Any] = {}
        ns.update(self.session.participant)
        ns.update(self.session.vars)
        for frame in self.runner.stack:
            ns.update(frame["row"])
            ns[frame["loop"]] = frame["state"]
        ns.update(self.runner.results)
        for cid, c in self.components.items():
            ns[cid] = c.out
        # trial-list values win over component results with the same name ("text: $word" in a
        # component called "word" must show the word, not the component's results)
        for frame in self.runner.stack:
            ns.update(frame["row"])
        if self.session.devices:
            ns.setdefault("devices", self.session.live_devices())
        ns["t"] = 0.0 if self.t0 is None or self.session.last_flip is None else self.session.last_flip - self.t0
        ns["frame"] = self.frame
        ns["vars"] = self.session.vars
        return ns

    def request_end(self) -> None:
        self._end = True

    # ----------------------------------------------------------- scheduling
    def _val(self, v: Any) -> Any:
        if isinstance(v, str):
            src = v[1:] if v.startswith("$") else v
            return expressions.evaluate(src, self.namespace())
        return v

    def _should_start(self, c: Component, t_next: float) -> bool:
        if getattr(c, "_force_start", False):
            return True
        s = c.spec
        if s.start_after:
            other = self.components.get(s.start_after)
            if other is None or other.status != FINISHED:
                return False
            # optional extra delay after the other component stops
            delay = self._val(s.start) if s.start not in (None, 0, 0.0) else 0.0
            return t_next - (other.t_stop - self.t0 if other.t_stop is not None else t_next) >= float(delay) - self._half
        if s.start_frame is not None:
            return self.frame >= int(s.start_frame)
        if s.start_if:
            return bool(self._val(s.start_if))
        start = self._val(s.start)
        return start is not None and t_next >= float(start) - self._half

    def _should_stop(self, c: Component, t_next: float) -> bool:
        if getattr(c, "_force_stop", False):
            return True
        s = c.spec
        if c.finished and not c.visual:
            return True
        if s.duration_frames is not None and self.frame - c.frame_start >= int(s.duration_frames):
            return True
        if c._duration is not None and c.t_start is not None and self.t0 is not None:
            if t_next - (c.t_start - self.t0) >= c._duration - self._half:
                return True
        if s.stop_if and bool(self._val(s.stop_if)):
            return True
        return False

    # ----------------------------------------------------------- main loop
    def run(self) -> dict[str, Any]:
        """Run the routine; any failure becomes an ExperimentError saying where, when and in what state."""
        from .diagnostics import ExperimentError, build_report
        self._where: tuple[str, Any] = ("prepare", None)
        try:
            return self._run()
        except (ExperimentAborted, StateJump, ExperimentError):
            raise
        except Exception as e:
            phase, comp = self._where
            raise ExperimentError(build_report(e, phase=phase, routine=self.routine.id, component=comp, run=self)) from e

    def _run(self) -> dict[str, Any]:
        session, backend = self.session, self.session.backend
        registry = component_registry()
        self._half = backend.frame_interval / 2
        for spec in self.routine.components:
            if spec.disabled is True or (isinstance(spec.disabled, str) and self._val(spec.disabled)):
                continue
            if spec.only_if and not self._val(spec.only_if):
                continue
            comp = registry[spec.type](spec, self)
            comp._duration = None
            comp._started_called = False
            self.components[spec.id] = comp
        for comp in self.components.values():
            self._where = ("prepare", comp)
            comp.prepare()
        comps = list(self.components.values())
        self._where = ("timing", None)
        self._rule_prev = [False] * len(self.routine.rules)
        self._rule_fired = [0] * len(self.routine.rules)
        max_dur = self._val(self.routine.duration) if self.routine.duration is not None else None
        dry_limit = float(session.settings["timing"].get("dry_run_routine_limit", 600)) \
            if session.virtual_participant is not None else None

        while True:
            interval = backend.frame_interval
            t_pred_abs = (session.last_flip + interval) if session.last_flip is not None else backend.clock()
            t_next = 0.0 if self.t0 is None else t_pred_abs - self.t0
            starting, stopping = [], []
            for c in comps:
                self._where = ("timing", c)
                if c.status == NOT_STARTED and self._should_start(c, t_next):
                    c.status = STARTED
                    c.frame_start = self.frame
                    c.t_start = t_pred_abs
                    d = self._val(c.spec.duration) if c.spec.duration is not None else None
                    c._duration = float(d) if d is not None else None
                    starting.append(c)
                elif c.status == STARTED and self._should_stop(c, t_next):
                    c.status = FINISHED
                    c.frame_stop = self.frame
                    stopping.append(c)

            # non-visual logic first (so e.g. gaze_follow moves a stimulus before it is drawn), then draw in order
            for c in comps:
                if c.status == STARTED and not c.visual and c._started_called:
                    self._where = ("frame", c)
                    c.on_frame(t_pred_abs)
            for c in comps:
                if c.status == STARTED and c.visual:
                    self._where = ("frame", c)
                    c.on_frame(t_pred_abs)

            self._where = ("frame", None)
            t_flip = session.flip(self.routine.id)
            if self.t0 is None:
                self.t0 = t_flip

            for c in starting:
                self._where = ("start", c)
                c.t_start = t_flip
                c._started_called = True
                c.on_start(t_flip)
                self._component_marker(c, "onset", t_flip)
            for c in stopping:
                self._where = ("stop", c)
                c.t_stop = t_flip
                c.on_stop(t_flip)
                self._component_marker(c, "offset", t_flip)

            for ev in backend.poll_events() + session.poll_inputs():
                for c in comps:
                    if c.status == STARTED and c._started_called:
                        self._where = ("event", c)
                        c.on_event(ev)
            self._where = ("frame", None)
            session.poll_devices()
            session.check_abort()
            if self.routine.rules:
                self._where = ("rule", None)
                self._run_rules(t_flip)
            self.frame += 1

            t_now = t_flip - self.t0
            if self._end:
                break
            # end_routine: the routine ends when this component responds *or* times out
            if any(c.spec.end_routine and (c.finished or c.status == FINISHED) for c in comps):
                break
            if dry_limit is not None and t_now > dry_limit:
                raise RuntimeError(f"dry run: routine '{self.routine.id}' did not end after {dry_limit:.0f} s; "
                                   "add a duration, end_if, or an end_routine component")
            if max_dur is not None and t_now + interval >= float(max_dur) - self._half:
                break
            self._where = ("end_if", None)
            if self.routine.end_if and self._val(self.routine.end_if):
                break
            # helpers (code/variable/marker) don't hold the routine open, unless they are still scheduled to start
            alive = [c for c in comps if c.keeps_routine_alive or c.status == NOT_STARTED]
            if alive and all(c.status == FINISHED for c in alive):
                break
            if not comps:
                break

        t_end = session.last_flip + backend.frame_interval  # next flip replaces this routine's display
        for c in comps:
            self._where = ("stop", c)
            if c.status == STARTED:
                c.status = FINISHED
                c.t_stop = t_end
                c.on_stop(t_end)
                self._component_marker(c, "offset", t_end)
            c.release()
        return self._collect(t_end)

    def _run_rules(self, t: float) -> None:
        """Edge-triggered "when <condition> do <actions>" rules. A rule fires when its condition
        becomes true; with ``repeat: true`` it can fire again after the condition was false."""
        for i, rule in enumerate(self.routine.rules):
            now = bool(self._val(str(rule["when"])))
            rising = now and not self._rule_prev[i]
            self._rule_prev[i] = now
            if not rising or (self._rule_fired[i] and not rule.get("repeat")):
                continue
            self._rule_fired[i] += 1
            self.fired_rules.append(rule.get("name") or f"rule{i}")
            acts = rule.get("do") or []
            for a in acts if isinstance(acts, list) else [acts]:
                if isinstance(a, str):
                    a = {a: True}
                if "set" in a:
                    for k, v in a["set"].items():
                        self.session.vars[k] = expressions.resolve(v, self.namespace())
                if "start" in a and a["start"] in self.components:
                    self.components[a["start"]]._force_start = True
                if "stop" in a and a["stop"] in self.components:
                    self.components[a["stop"]]._force_stop = True
                if "marker" in a:
                    label = expressions.resolve(a["marker"], self.namespace())
                    self.session.marker(str(label), source=f"{self.routine.id}.rule", time=t)
                if "log" in a:
                    self.session.log(f"[rule] {expressions.resolve(a['log'], self.namespace())}")
                if "goto" in a:
                    self.goto = str(a["goto"])
                    self._end = True
                if a.get("end_routine"):
                    self._end = True

    def _component_marker(self, c: Component, which: str, t: float) -> None:
        m = c.spec.props.get("marker")
        if not m or c.type_name == "marker":
            return
        ns = self.namespace()
        if isinstance(m, dict):
            label = m.get(which)
            code = m.get("code") if which == "onset" else m.get("offset_code")
        else:
            label = m if which == "onset" else None
            code = None
        if label:
            label = expressions.resolve(label, ns)
            self.session.marker(str(label), code=code, source=f"{self.routine.id}.{c.id}", time=t, on_flip=True)

    def _collect(self, t_end: float) -> dict[str, Any]:
        row: dict[str, Any] = {"routine": self.routine.id,
                               "routine_start": self.t0,
                               "routine_duration": (t_end - self.t0) if self.t0 is not None else None}
        if self.fired_rules:
            row["rules_fired"] = self.fired_rules
        for c in self.components.values():
            if not c.spec.save:
                continue
            for k, v in c.results().items():
                row[f"{c.id}.{k}"] = v
            self.runner.results[c.id] = c.out
        return row


class Runner:
    def __init__(self, session: Session):
        self.session = session
        self.exp: Experiment = session.exp
        self.stack: list[dict[str, Any]] = []
        self.results: dict[str, Results] = {}
        self.routine_count = 0
        self.machines: list[dict[str, Any]] = []   # active state machines (innermost last)

    def run(self) -> dict[str, Any]:
        s = self.session
        try:
            s.open()
            self.run_nodes(self.exp.flow)
        except ExperimentAborted:
            s.aborted = True
            s.log("[edge] aborted by user; data saved")
        except StateJump as j:
            s.errors.append(f"goto '{j.target}' used outside a state machine that has that state")
        except BaseException as e:
            from .diagnostics import ExperimentError, build_report
            s.aborted = True
            if isinstance(e, Exception):
                rep = build_report(e, phase="setup" if s.data is None or s.last_flip is None and not self.routine_count
                                   else "flow", runner=self)
                s.crash = rep
                s.errors.append(rep["what"])
                if not isinstance(e, ExperimentError):
                    raise ExperimentError(rep) from e
            else:
                s.errors.append(f"{type(e).__name__}: {e}")
            raise
        finally:
            summary = s.close()
            summary["data_dir"] = str(s.data.root) if s.data else None
        return summary

    def run_nodes(self, nodes: Iterable[Any]) -> None:
        for node in nodes:
            if isinstance(node, RoutineRef):
                if node.if_ and not self._eval(node.if_):
                    continue
                self.run_routine(self.exp.routines[node.routine])
            elif isinstance(node, Loop):
                self.run_loop(node)
            elif isinstance(node, Branch):
                self.run_nodes(node.then if self._eval(node.condition) else node.else_)
            elif isinstance(node, StateMachine):
                self.run_statemachine(node)

    def _eval(self, src: str) -> Any:
        ns: dict[str, Any] = {**self.session.participant, **self.session.vars}
        for f in self.stack:
            ns.update(f["row"])
            ns[f["loop"]] = f["state"]
        ns.update(self.results)
        for f in self.stack:
            ns.update(f["row"])
        ns["vars"] = self.session.vars
        return expressions.evaluate(src[1:] if src.startswith("$") else src, ns)

    def run_routine(self, routine: Routine) -> None:
        run = RoutineRun(routine, self.session, self)
        row = run.run()
        self.routine_count += 1
        key = [f"{m['id']}:{m['state']}#{m['visit']}" for m in self.machines]
        key += [f"{f['loop']}={f['state']['n']}" for f in self.stack]
        full: dict[str, Any] = {"experiment": self.exp.name, **self.session.participant, "routine_index": self.routine_count,
                                "trial_key": "|".join(key) if self.stack else "",
                                "loop": self.stack[-1]["loop"] if self.stack else ""}
        for m in self.machines:
            full[f"{m['id']}.state"] = m["state"]
            full[f"{m['id']}.visit"] = m["visit"]
        # live performance per enclosing loop (for adaptive logic: $practice.accuracy >= 0.8)
        corr = [v for k, v in row.items() if k.endswith(".corr") and isinstance(v, (int, float, bool))]
        rts = [v for k, v in row.items() if k.endswith(".rt") and isinstance(v, (int, float)) and not isinstance(v, bool)]
        for f in self.stack:
            f["acc"]["corr"] += [float(c) for c in corr]
            f["acc"]["rt"] += [float(r) for r in rts]
            f["state"].update(_perf(f["acc"]))
        for f in self.stack:
            st = f["state"]
            full[f"{f['loop']}.n"] = st["n"]
            full[f"{f['loop']}.repeat"] = st.get("repeat")
            full.update({k: v for k, v in f["row"].items() if k != "_row"})
            full[f"{f['loop']}.row"] = f["row"].get("_row")
        full.update(row)
        for k, v in self.session.vars.items():
            if isinstance(v, (int, float, str, bool)) and k not in full:
                full[k] = v
        if self.session.data:
            self.session.data.add_trial(full)
        if self.session.monitor:
            try:
                self.session.monitor.trial(full)
            except Exception:   # the monitor is for the experimenter; it must never stop a session
                pass
        if run.goto:
            raise StateJump(run.goto)

    def run_statemachine(self, m: StateMachine) -> None:
        s = self.session
        visits: dict[str, int] = {}
        path: list[str] = []
        info = LoopState(state=m.start, steps=0, visits=visits, previous=None)
        self.results[m.id] = info
        frame = {"id": m.id, "state": m.start, "visit": 0}
        self.machines.append(frame)
        cur, steps = m.start, 0
        try:
            while cur != "end":
                if cur not in m.states:
                    raise RuntimeError(f"state machine '{m.id}': unknown state '{cur}'")
                steps += 1
                if steps > m.max_steps:
                    s.errors.append(f"state machine '{m.id}' stopped after max_steps={m.max_steps}")
                    break
                st = m.states[cur]
                visits[cur] = visits.get(cur, 0) + 1
                frame.update(state=cur, visit=visits[cur])
                info.update(state=cur, steps=steps, visit=visits[cur], visits=dict(visits))
                path.append(cur)
                jumped = None
                try:
                    self.run_nodes(st.run)
                except StateJump as j:
                    if j.target != "end" and j.target not in m.states:
                        raise
                    jumped = j.target
                if jumped is not None:
                    nxt = jumped
                else:
                    nxt = "end"
                    forced = bool(st.max_visits and visits[cur] >= st.max_visits)
                    cands = [t for t in st.next if t.goto != cur] if forced else st.next
                    chosen = next((t for t in cands if t.condition is None or self._eval(t.condition)), None)
                    if chosen is None and forced and cands:
                        chosen = cands[0]  # visit limit reached: leave by the first route to another state
                    if chosen is not None:
                        for k, v in chosen.set.items():
                            s.vars[k] = expressions.resolve(v, {**s.vars, **self.results})
                        nxt = chosen.goto
                info["previous"] = cur
                cur = nxt
        finally:
            self.machines.pop()
            s.loop_summaries[m.id] = {"type": "statemachine", "path": path, "visits": visits, "columns": []}
            info.update(state="end", steps=steps, visits=dict(visits))

    def run_loop(self, loop: Loop) -> None:
        s = self.session
        acc: dict[str, list[float]] = {"corr": [], "rt": []}
        if loop.staircase:
            sc = Staircase(loop.staircase)
            for row in sc:
                state = LoopState(n=row["_row"], total=sc.max_trials, repeat=0, staircase=sc.level, **_perf(acc))
                self.stack.append({"loop": loop.id, "row": row, "state": state, "acc": acc})
                try:
                    self.run_nodes(loop.children)
                    sc.update(bool(self._eval(str(sc.correct_expr))))
                finally:
                    self.stack.pop()
                if loop.stop_if and self._eval(loop.stop_if):
                    break
            s.loop_summaries[loop.id] = {"type": "staircase", "threshold": sc.threshold,
                                         "columns": [sc.variable, "staircase_trial"], "source": "staircase",
                                         "reversals": sc.reversal_levels, "trials": len(sc.history),
                                         "history": sc.history}
            s.vars[f"{loop.id}_threshold"] = sc.threshold
            self.results[loop.id] = LoopState(n=len(sc.history) - 1, total=len(sc.history), threshold=sc.threshold,
                                              **_perf(acc))
            return

        cond = loop.conditions
        if isinstance(cond, str) and cond.startswith("$"):   # e.g. conditions: $block_file (set by an outer loop)
            cond = self._eval(cond)
        rows = select_rows(load_conditions(cond, self.exp.base_dir), loop.select)
        repeats = int(self._eval(loop.repeats) if isinstance(loop.repeats, str) else loop.repeats)
        if repeats < 0 or repeats * max(len(rows), 1) > 10_000_000:
            raise ValueError(f"loop '{loop.id}': {repeats} repetitions of {len(rows)} rows is not a session anyone can run")
        p_index = _participant_index(s.participant)
        trials = order_trials(rows, loop.order, repeats, s.rng, loop.max_repeat, p_index)
        n_per_rep = max(len(rows), 1)
        columns: list[str] = []
        for r in rows:
            columns += [k for k in r if k not in columns]
        s.loop_summaries[loop.id] = {"type": "trials", "order": loop.order, "n_trials": len(trials),
                                     "columns": columns,
                                     "source": loop.conditions if isinstance(loop.conditions, str) else
                                     ("factorial" if isinstance(loop.conditions, dict) else
                                      ("inline table" if loop.conditions else None)),
                                     "sequence": [t.get("_row") for t in trials]}
        for i, row in enumerate(trials):
            state = LoopState(n=i, total=len(trials), remaining=len(trials) - i - 1, repeat=i // n_per_rep,
                              first=i == 0, last=i == len(trials) - 1, **_perf(acc))
            self.stack.append({"loop": loop.id, "row": row, "state": state, "acc": acc})
            try:
                self.run_nodes(loop.children)
                stop = bool(loop.stop_if and self._eval(loop.stop_if))
            finally:
                self.stack.pop()
            if stop:
                s.loop_summaries[loop.id]["stopped_at"] = i
                break
        # keep the final loop state visible to later routines (e.g. "$trials.total")
        if trials:
            self.results[loop.id] = state


def _participant_index(participant: dict[str, Any]) -> int:
    """Participant number used for counterbalancing (digits in the participant id)."""
    pid = str(participant.get("participant", "0"))
    digits = "".join(ch for ch in pid if ch.isdigit())
    return int(digits) if digits else sum(map(ord, pid))


def run_experiment(exp: Experiment, backend: str = "pyglet", participant: dict[str, Any] | None = None,
                   dry_run: bool = False, data_dir: str | None = None, simulate_devices: bool | None = None,
                   virtual_participant: Any = None, log=print, **backend_kw: Any) -> dict[str, Any]:
    """Run an experiment end to end and return the session summary."""
    from .backends import create_backend
    from .participant import VirtualParticipant

    if dry_run:
        backend = "headless"
        if virtual_participant is None:
            virtual_participant = VirtualParticipant()
        if simulate_devices is None:
            simulate_devices = True
    if backend == "headless-realtime":
        backend, backend_kw["realtime"] = "headless", True
    if backend == "headless" and "size" not in backend_kw:
        from .model import window_size
        backend_kw["size"] = window_size(exp.settings)
    be = create_backend(backend, **backend_kw)
    session = Session(exp, be, participant=participant, data_dir=data_dir, virtual_participant=virtual_participant,
                      simulate_devices=bool(simulate_devices), log=log)
    return Runner(session).run()
