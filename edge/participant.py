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
                and component.type_name in ("keyboard", "device_response", "gamepad") and self.rng.random() < self.accuracy:
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
        elif kind in ("microphone", "gamepad") or (kind == "mouse" and (component.swipes or component.p.get("record_touches"))):
            respond_media(self, component, allowed, correct, backend, at)
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


def respond_media(vp: VirtualParticipant, component: Any, allowed: Any, correct: Any, backend: Any, at: float) -> None:
    """Simulated speech, gamepad presses and touchscreen gestures (the microphone, gamepad and mouse items)."""
    from .backends.base import InputEvent
    rng = vp.rng
    kind = component.type_name
    if kind == "microphone":
        # speak at ``at`` for about half a second: the item builds its simulated recording from this, and a voice key
        # linked to it hears the same utterance a couple of milliseconds later
        length = rng.uniform(0.35, 0.8)
        backend.schedule(InputEvent("speech", "voice", at, True))
        backend.schedule(InputEvent("speech", "voice", at + length, False))
        if getattr(component, "vk_id", None):
            dev = component.session.devices.get(component.vk_id)
            t_on, t_off = at + rng.uniform(0.001, 0.004), at + length + 0.15
            backend.schedule(InputEvent("device", component.vk_input, t_on, True, device=component.vk_id))
            backend.schedule(InputEvent("device", component.vk_input, t_off, False, device=component.vk_id))
            if dev is not None and "inputs" in dev.streams:
                dev.emit("inputs", t_on, [component.vk_input, 1, ""], sync=False)
                dev.emit("inputs", t_off, [component.vk_input, 0, ""], sync=False)
    elif kind == "gamepad":
        from .components.media_responses import STICK_DIRECTIONS
        names = list(allowed) if allowed else (["stick_left", "stick_right"] if component.th is not None else ["a", "b"])
        if correct is not None and str(correct) in names and rng.random() < vp.accuracy:
            name = str(correct)
        else:
            name = rng.choice([n for n in names if n != str(correct)] or names)
        pad = int(component.pad) if component.pad not in (None, "") else 0
        if component.p.get("track"):         # the thumb rests on the stick and drifts a little
            for k in range(4):
                backend.move_stick("lx", round(rng.uniform(-0.3, 0.3), 3), at - 0.2 + 0.05 * k, index=pad)
        if name in STICK_DIRECTIONS:
            axis = ("r" if name.startswith("rstick") else "l") + ("x" if name.endswith(("left", "right")) else "y")
            value = 0.95 if name.endswith(("right", "up")) else -0.95
            backend.move_stick(axis, value * 0.5, at - 0.03, index=pad)
            backend.move_stick(axis, value, at, index=pad)
            backend.move_stick(axis, 0.0, at + 0.25, index=pad)
        else:
            backend.gamepad(name, at, index=pad)
    elif kind == "mouse":
        targets = [c for c in (component.p.get("clickable") or [])
                   if c in component.run.components and hasattr(component.run.components[c], "stim")]
        start = component.run.components[rng.choice(targets)].stim.props.get("pos", (0, 0)) if targets else (0.0, 0.0)
        if not component.swipes:            # a tap on a target (record_touches is on)
            if correct in targets and rng.random() < vp.accuracy:
                start = component.run.components[correct].stim.props.get("pos", (0, 0))
            if component.p.get("touch", True):
                backend.tap(start, at)
            else:
                backend.click(start, at, button=(component.p.get("buttons") or ["left"])[0])
            return
        swipes = component.swipes
        d = str(correct) if correct in swipes and rng.random() < vp.accuracy else \
            rng.choice([s for s in swipes if s != correct] or swipes)
        dist = float(component.p.get("swipe_distance") or 0.1) * backend.size[1] * 1.6
        dx, dy = {"left": (-dist, 0.0), "right": (dist, 0.0), "up": (0.0, dist), "down": (0.0, -dist)}[d]
        mid = (start[0] + dx / 2, start[1] + dy / 2)
        end = (start[0] + dx, start[1] + dy)
        if component.p.get("touch", True):
            backend.touch(start, at, "down")
            backend.touch(mid, at + 0.06, "move")
            backend.touch(end, at + 0.12, "up")
        else:
            button = (component.p.get("buttons") or ["left"])[0]
            backend.schedule(InputEvent("mouse", button, at, True, tuple(start)))
            backend.move_mouse(mid, at + 0.06)
            backend.schedule(InputEvent("mouse", button, at + 0.12, False, tuple(end)))
