"""Hardware and logic components: markers, variables, code, waits."""

from __future__ import annotations

from typing import Any

from .. import expressions
from .base import Component


class MarkerComp(Component):
    type_name = "marker"
    category = "hardware"
    description = ("Send an event marker at this component's onset (time-locked to the screen flip) to all "
                   "devices or a chosen subset: TTL codes, LSL markers, Gazepoint USER_DATA, Tobii sample tags.")
    props_schema = {
        "label": {"type": "str", "default": "", "required": True, "help": "e.g. $f'stim_{condition}'"},
        "code": {"type": "int", "default": None, "help": "TTL code 1-255 (auto-assigned from the label if empty)"},
        "devices": {"type": "list", "default": None, "help": "device ids; empty = all marker-capable devices"},
        "offset_label": {"type": "str", "default": None, "help": "optional marker sent when the component stops"},
    }

    def on_start(self, t: float) -> None:
        m = self.session.marker(str(self.p["label"]), code=self.p["code"], source=self.id, time=t,
                                devices=self.p["devices"], on_flip=True)
        self.out.update(label=m.label, code=m.code)

    def on_stop(self, t: float) -> None:
        if self.p["offset_label"]:
            self.session.marker(str(self.p["offset_label"]), source=self.id, time=t, devices=self.p["devices"], on_flip=True)


class Variable(Component):
    type_name = "variable"
    category = "logic"
    description = "Set experiment variables from expressions, e.g. set: {score: '$score + resp.corr'}."
    props_schema = {
        "set": {"type": "dict", "default": {}, "required": True},
        "when": {"type": "choice", "choices": ["start", "end"], "default": "start"},
    }

    def prepare(self) -> None:
        # 'start' assignments happen during routine preparation, in component order, so that
        # components listed after this one already see the new values.
        self.p = {"when": self.prop("when")}
        if self.p["when"] == "start":
            self._apply()

    def _apply(self) -> None:
        for name, expr in (self.spec.props.get("set") or {}).items():
            val = expressions.resolve(expr, self.run.namespace())
            self.session.vars[name] = val
            self.out[name] = val

    def on_start(self, t: float) -> None:
        if self.p["when"] == "start":
            self.finished = True

    def on_stop(self, t: float) -> None:
        if self.p["when"] == "end":
            self._apply()


class Code(Component):
    type_name = "code"
    category = "logic"
    description = ("Full Python for anything the builder can't express. Snippets run when the routine begins "
                   "(on_begin), every frame (on_frame) and when it ends (on_end), with access to trial variables, "
                   "component results, `vars`, `session`, `marker(label)` and `end_routine()`. "
                   "Assigned names persist as variables.")
    props_schema = {
        "on_begin": {"type": "code", "default": "", "help": "runs while the routine is prepared (before stimuli resolve)"},
        "on_frame": {"type": "code", "default": "", "help": "runs every frame (`t` = predicted flip time)"},
        "on_end": {"type": "code", "default": "", "help": "runs when the routine ends"},
    }

    def prepare(self) -> None:
        self.p = {k: self.spec.props.get(k, "") or "" for k in self.props_schema}
        self._compiled = {k: compile(v, f"<{self.run.routine.id}.{self.id}.{k}>", "exec")
                          for k, v in self.p.items() if v.strip()}
        # on_begin runs while the routine is being prepared (in component order), so
        # variables it sets are visible to every component listed after it.
        self._exec("on_begin", None)

    def _exec(self, which: str, t: float | None = None) -> None:
        code = self._compiled.get(which)
        if code is None:
            return
        g = self.session.code_globals
        ns = self.run.namespace()
        g.update(ns)
        g.update(vars=self.session.vars, session=self.session, t=t, routine=self.run,
                 marker=lambda label, code=None: self.session.marker(label, code=code, source=self.id),
                 end_routine=self.run.request_end)
        before = {k: id(v) for k, v in g.items()}
        exec(code, g)  # noqa: S102 - user code component, explicit by design
        for k, v in g.items():
            if k.startswith("_") or k in ("vars", "session", "t", "routine", "marker", "end_routine", "__builtins__"):
                continue
            if before.get(k) != id(v) and (k not in ns or ns[k] is not v):
                self.session.vars[k] = v

    def on_frame(self, t: float) -> None:
        self._exec("on_frame", t)

    def on_stop(self, t: float) -> None:
        self._exec("on_end", t)


class Wait(Component):
    type_name = "wait"
    category = "logic"
    description = "Does nothing; use with a duration to hold the routine (ISI, blank screen)."
    props_schema: dict[str, Any] = {}


COMPONENTS = [MarkerComp, Variable, Code, Wait]
