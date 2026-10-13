"""The virtual participant: a simulated human for dry runs.

Before a single real participant is booked you can run the whole experiment,
end to end, with every device simulated, in seconds:

    edge run stroop.yaml --dry-run

The virtual participant answers every response window with realistic
ex-Gaussian reaction times and a configurable accuracy. The output folder is
identical to a real session, so analysis scripts, counterbalancing, branching,
staircases and device sync can all be verified up front.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class VirtualParticipant:
    """``seed=None`` (the default): a different but reproducible participant in every session, seeded from
    the session's seed (saved in session.json). Give a seed for exactly the same answers every time."""

    accuracy: float = 0.9
    respond_prob: float = 0.98
    rt_mu: float = 0.45       # ex-Gaussian parameters (s)
    rt_sigma: float = 0.05
    rt_tau: float = 0.12
    seed: int | None = None

    def __post_init__(self) -> None:
        self.used_seed = self.seed
        self.rng = random.Random(self.seed if self.seed is not None else 0)

    def reseed(self, seed: int) -> None:
        """Start a new simulated person (the session calls this with its own seed)."""
        self.used_seed = seed
        self.rng = random.Random(seed)

    def rt(self) -> float:
        return max(0.12, self.rng.gauss(self.rt_mu, self.rt_sigma) + self.rng.expovariate(1.0 / self.rt_tau))

    def respond(self, component: Any, allowed: Any, correct: Any, backend: Any) -> None:
        """Schedule simulated input on the headless backend for a response window."""
        open_ended = component.spec.duration is None and component.spec.duration_frames is None
        can_time_out = not open_ended or _routine_can_end_by_itself(component)
        if not open_ended and self.rng.random() > self.respond_prob:
            return  # a missed response; only possible when the window times out
        if correct is not None and str(correct).strip().lower() in ("none", "") and can_time_out \
                and component.type_name in ("keyboard", "device_response") and self.rng.random() < self.accuracy:
            return  # "no response" is the right answer (a no-go / standard trial): withhold, as people mostly do
        onset = component.t_start if component.t_start is not None else backend.clock()
        at = onset + self.rt()
        kind = component.type_name
        if kind == "keyboard":
            keys = list(allowed) if allowed else ["space"]
            if correct is not None and str(correct) in keys and self.rng.random() < self.accuracy:
                key = str(correct)
            else:
                wrong = [k for k in keys if str(k) != str(correct)] or keys
                key = self.rng.choice(wrong) if correct is not None else self.rng.choice(keys)
            backend.press(key, at)
        elif kind == "device_response":
            from .backends.base import InputEvent
            dev = component.session.devices.get(component.device_id) if component.device_id else None
            names = list(allowed) if allowed else \
                [str(v) for v in ((dev.options.get("inputs") or {}).values() if dev is not None else [])] or \
                list(component.keymap.values()) or ["1"]
            if correct is not None and str(correct) in names and self.rng.random() < self.accuracy:
                name = str(correct)
            else:
                wrong = [n for n in names if n != str(correct)] or names
                name = self.rng.choice(wrong)
            if component.device_id:
                backend.schedule(InputEvent("device", name, at, True, device=component.device_id))
                backend.schedule(InputEvent("device", name, at + 0.12, False, device=component.device_id))
                if dev is not None and "inputs" in dev.streams:      # the simulated box records it too
                    dev.emit("inputs", at, [name, 1, ""], sync=False)
                    dev.emit("inputs", at + 0.12, [name, 0, ""], sync=False)
            else:
                key = next((k for k, v in component.keymap.items() if v == name), None)
                if key:
                    backend.press(key, at)
        elif kind == "mouse":
            targets = [c for c in (component.p.get("clickable") or [])
                       if c in component.run.components and hasattr(component.run.components[c], "stim")]
            if targets:
                if correct in targets and self.rng.random() < self.accuracy:
                    tgt = correct
                else:
                    tgt = self.rng.choice([t for t in targets if t != correct] or targets)
                pos = component.run.components[tgt].stim.props.get("pos", (0, 0))
            else:
                w, h = backend.size
                pos = (self.rng.uniform(-w / 4, w / 4), self.rng.uniform(-h / 4, h / 4))
            backend.move_mouse(pos, at - 0.05)
            backend.click(pos, at, button=(component.p.get("buttons") or ["left"])[0])
        elif kind == "slider":
            x = component.cx + self.rng.uniform(-0.5, 0.5) * component.w
            backend.click((x, component.cy), at)
            if component.p.get("require_confirm"):
                backend.press("return", at + 0.4)


def _routine_can_end_by_itself(component: Any) -> bool:
    """Whether the screen ends without this response (a routine duration or end condition), so not
    answering can't leave the session waiting forever."""
    routine = getattr(getattr(component, "run", None), "routine", None)
    return routine is not None and (routine.duration is not None or bool(routine.end_if))
