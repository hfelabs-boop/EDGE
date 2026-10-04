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
from .model import Branch, Experiment, Loop, Routine, RoutineRef
from .runtime import ExperimentAborted, Session


class LoopState(Results):
    """Exposed to expressions under the loop id: ``trials.n``, ``trials.total`` ..."""


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
        session, backend = self.session, self.session.backend
        registry = component_registry()
        self._half = backend.frame_interval / 2
        for spec in self.routine.components:
            if spec.disabled is True or (isinstance(spec.disabled, str) and self._val(spec.disabled)):
                continue
            comp = registry[spec.type](spec, self)
            comp._duration = None
            comp._started_called = False
            self.components[spec.id] = comp
        for comp in self.components.values():
            try:
                comp.prepare()
            except Exception as e:
                raise RuntimeError(f"routine '{self.routine.id}', component '{comp.id}': {e}") from e
        comps = list(self.components.values())
        max_dur = self._val(self.routine.duration) if self.routine.duration is not None else None
        dry_limit = float(session.settings["timing"].get("dry_run_routine_limit", 600)) \
            if session.virtual_participant is not None else None

        while True:
            interval = backend.frame_interval
            t_pred_abs = (session.last_flip + interval) if session.last_flip is not None else backend.clock()
            t_next = 0.0 if self.t0 is None else t_pred_abs - self.t0
            starting, stopping = [], []
            for c in comps:
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
                    c.on_frame(t_pred_abs)
            for c in comps:
                if c.status == STARTED and c.visual:
                    c.on_frame(t_pred_abs)

            t_flip = session.flip(self.routine.id)
            if self.t0 is None:
                self.t0 = t_flip

            for c in starting:
                c.t_start = t_flip
                c._started_called = True
                c.on_start(t_flip)
                self._component_marker(c, "onset", t_flip)
            for c in stopping:
                c.t_stop = t_flip
                c.on_stop(t_flip)
                self._component_marker(c, "offset", t_flip)

            for ev in backend.poll_events():
                for c in comps:
                    if c.status == STARTED and c._started_called:
                        c.on_event(ev)
            session.poll_devices()
            session.check_abort()
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
            if self.routine.end_if and self._val(self.routine.end_if):
                break
            if comps and all(c.status == FINISHED for c in comps):
                break
            if not comps:
                break

        t_end = session.last_flip + backend.frame_interval  # next flip replaces this routine's display
        for c in comps:
            if c.status == STARTED:
                c.status = FINISHED
                c.t_stop = t_end
                c.on_stop(t_end)
                self._component_marker(c, "offset", t_end)
            c.release()
        return self._collect(t_end)

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

    def run(self) -> dict[str, Any]:
        s = self.session
        try:
            s.open()
            self.run_nodes(self.exp.flow)
        except ExperimentAborted:
            s.aborted = True
            s.log("[edge] aborted by user; data saved")
        except BaseException as e:
            s.aborted = True
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

    def _eval(self, src: str) -> Any:
        ns: dict[str, Any] = {**self.session.participant, **self.session.vars}
        for f in self.stack:
            ns.update(f["row"])
            ns[f["loop"]] = f["state"]
        ns.update(self.results)
        ns["vars"] = self.session.vars
        return expressions.evaluate(src[1:] if src.startswith("$") else src, ns)

    def run_routine(self, routine: Routine) -> None:
        run = RoutineRun(routine, self.session, self)
        row = run.run()
        self.routine_count += 1
        full: dict[str, Any] = {"experiment": self.exp.name, **self.session.participant, "routine_index": self.routine_count}
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

    def run_loop(self, loop: Loop) -> None:
        s = self.session
        if loop.staircase:
            sc = Staircase(loop.staircase)
            for row in sc:
                state = LoopState(n=row["_row"], total=sc.max_trials, repeat=0, staircase=sc.level)
                self.stack.append({"loop": loop.id, "row": row, "state": state})
                try:
                    self.run_nodes(loop.children)
                    sc.update(bool(self._eval(str(sc.correct_expr))))
                finally:
                    self.stack.pop()
                if loop.stop_if and self._eval(loop.stop_if):
                    break
            s.loop_summaries[loop.id] = {"type": "staircase", "threshold": sc.threshold,
                                         "reversals": sc.reversal_levels, "trials": len(sc.history),
                                         "history": sc.history}
            s.vars[f"{loop.id}_threshold"] = sc.threshold
            self.results[loop.id] = LoopState(n=len(sc.history) - 1, total=len(sc.history), threshold=sc.threshold)
            return

        rows = select_rows(load_conditions(loop.conditions, self.exp.base_dir), loop.select)
        repeats = int(self._eval(loop.repeats) if isinstance(loop.repeats, str) else loop.repeats)
        p_index = _participant_index(s.participant)
        trials = order_trials(rows, loop.order, repeats, s.rng, loop.max_repeat, p_index)
        n_per_rep = max(len(rows), 1)
        s.loop_summaries[loop.id] = {"type": "trials", "order": loop.order, "n_trials": len(trials),
                                     "sequence": [t.get("_row") for t in trials]}
        for i, row in enumerate(trials):
            state = LoopState(n=i, total=len(trials), remaining=len(trials) - i - 1, repeat=i // n_per_rep,
                              first=i == 0, last=i == len(trials) - 1)
            self.stack.append({"loop": loop.id, "row": row, "state": state})
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
        backend_kw["size"] = tuple(exp.settings["window"]["size"])
    be = create_backend(backend, **backend_kw)
    session = Session(exp, be, participant=participant, data_dir=data_dir, virtual_participant=virtual_participant,
                      simulate_devices=bool(simulate_devices), log=log)
    return Runner(session).run()
