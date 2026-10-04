"""Component base class.

A component lives inside a routine and has a lifecycle driven by the engine::

    prepare()          routine begins (resolve properties, build stimuli)
    on_start(t)        first frame it is active; t = flip time of that frame
    on_frame(t)        every frame while active (visual components draw here)
    on_event(ev)       input events while active
    on_stop(t)         last frame / routine end
    results()          values saved into the trial row as "<id>.<key>"

Scheduling (start/duration/start_after/start_if/stop_if/end_routine) is handled
by the engine from the :class:`~edge.model.ComponentSpec`, so components only
implement behaviour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from .. import expressions
from ..backends.base import InputEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..engine import RoutineRun
    from ..model import ComponentSpec, Experiment, Issue

NOT_STARTED, STARTED, FINISHED = 0, 1, 2

# Properties every component accepts.
COMMON_PROPS: dict[str, dict[str, Any]] = {
    "marker": {"type": "marker", "default": None,
               "help": "label (or {onset, offset, code}) broadcast to all devices when this component starts"},
}


class Results(dict):
    """Dict that also allows attribute access in expressions: ``resp.rt``.

    Stored values win over dict methods, so ``resp.keys`` is the pressed key, not ``dict.keys``.
    """

    def __getattribute__(self, k: str) -> Any:
        if k in self:
            return self[k]
        return super().__getattribute__(k)

    def __getattr__(self, k: str) -> Any:
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None


class Component:
    type_name: ClassVar[str] = ""
    category: ClassVar[str] = "other"   # stimulus | response | eyetracking | hardware | logic
    description: ClassVar[str] = ""
    visual: ClassVar[bool] = False
    # False for helpers (code, variable, marker) that should not keep a routine running on their own
    keeps_routine_alive: ClassVar[bool] = True
    props_schema: ClassVar[dict[str, dict[str, Any]]] = {}
    # properties that are re-evaluated every frame when given as expressions
    dynamic: ClassVar[set[str]] = set()

    def __init__(self, spec: "ComponentSpec", run: "RoutineRun"):
        self.spec = spec
        self.id = spec.id
        self.run = run
        self.session = run.session
        self.backend = run.session.backend
        self.status = NOT_STARTED
        self.t_start: float | None = None      # master clock (flip) time
        self.t_stop: float | None = None
        self.frame_start: int | None = None
        self.frame_stop: int | None = None
        self.finished = False                  # component considers its job done (e.g. response given)
        self.out = Results()
        self.p: dict[str, Any] = {}

    # ----------------------------------------------------------- schema
    @classmethod
    def all_props(cls) -> dict[str, dict[str, Any]]:
        return {**cls.props_schema, **COMMON_PROPS}

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {"type": cls.type_name, "category": cls.category, "description": cls.description,
                "visual": cls.visual, "props": cls.all_props()}

    @classmethod
    def validate_spec(cls, spec: "ComponentSpec", where: str, exp: "Experiment") -> list["Issue"]:
        from ..model import Issue
        issues = []
        known = set(cls.all_props())
        for k in spec.props:
            if k not in known and not k.startswith("x_"):
                issues.append(Issue("warning", where, f"unknown property '{k}' for {cls.type_name}",
                                    hint="prefix custom metadata with x_"))
        for k, meta in cls.props_schema.items():
            if meta.get("required") and k not in spec.props:
                issues.append(Issue("error", where, f"missing required property '{k}'"))
            if "choices" in meta and k in spec.props and not expressions.is_expr(spec.props[k]) \
                    and spec.props[k] not in meta["choices"]:
                issues.append(Issue("error", where, f"'{k}' must be one of {meta['choices']}"))
        return issues

    # ----------------------------------------------------------- helpers
    def prop(self, name: str, default: Any = None) -> Any:
        if name in self.spec.props:
            raw = self.spec.props[name]
        else:
            raw = self.all_props().get(name, {}).get("default", default)
        return expressions.resolve(raw, self.run.namespace())

    def resolve_all(self) -> dict[str, Any]:
        self.p = {k: self.prop(k) for k in self.all_props()}
        return self.p

    def refresh_dynamic(self) -> bool:
        changed = False
        for k in self.dynamic:
            raw = self.spec.props.get(k)
            if expressions.is_expr(raw):
                v = expressions.resolve(raw, self.run.namespace())
                if v != self.p.get(k):
                    self.p[k] = v
                    changed = True
        return changed

    def px(self, value: Any, axis: str = "both") -> Any:
        units = self.p.get("units") or self.session.settings["window"]["units"]
        return self.backend.to_px(value, units, self.session.settings["window"].get("monitor"), axis)

    def send_response_marker(self, t: float) -> None:
        raw = self.spec.props.get("response_marker")
        if raw:
            label = expressions.resolve(raw, self.run.namespace())
            self.session.marker(str(label), source=f"{self.run.routine.id}.{self.id}", time=t)

    def rt(self, t: float) -> float:
        """Response time relative to this component's onset."""
        return t - (self.t_start if self.t_start is not None else t)

    # ----------------------------------------------------------- lifecycle (override)
    def prepare(self) -> None:
        self.resolve_all()

    def on_start(self, t: float) -> None:
        pass

    def on_frame(self, t: float) -> None:
        pass

    def on_event(self, ev: InputEvent) -> None:
        pass

    def on_stop(self, t: float) -> None:
        pass

    def results(self) -> dict[str, Any]:
        return dict(self.out)

    def release(self) -> None:
        pass
