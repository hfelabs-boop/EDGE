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
    accuracy: float = 0.9
    respond_prob: float = 0.98
    rt_mu: float = 0.45       # ex-Gaussian parameters (s)
    rt_sigma: float = 0.05
    rt_tau: float = 0.12
    seed: int | None = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    def rt(self) -> float:
        return max(0.12, self.rng.gauss(self.rt_mu, self.rt_sigma) + self.rng.expovariate(1.0 / self.rt_tau))

    def respond(self, component: Any, allowed: Any, correct: Any, backend: Any) -> None:
        """Schedule simulated input on the headless backend for a response window."""
        open_ended = component.spec.duration is None and component.spec.duration_frames is None
        if not open_ended and self.rng.random() > self.respond_prob:
            return  # a missed response; only possible when the window times out
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
