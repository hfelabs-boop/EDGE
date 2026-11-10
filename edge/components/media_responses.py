"""Response components for spoken answers and game controllers: ``microphone`` and ``gamepad``.

(Touchscreens are handled by the ``mouse`` item: taps are clicks, see edge/components/responses.py.)
"""

from __future__ import annotations

from typing import Any

from .. import expressions
from ..backends.base import InputEvent
from .base import Component
from .responses import _key_name_issues, _window_issues


def _routine_of(spec: Any, exp: Any) -> Any:
    for r in getattr(exp, "routines", {}).values():
        if any(c is spec for c in r.components):
            return r
    return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or expressions.is_expr(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================================ microphone
class Microphone(Component):
    type_name = "microphone"
    category = "response"
    description = ("Record a spoken answer: a WAV file per screen in the session folder (audio/…), with the moment "
                   "speech starts (rt) and stops, found by the same detector as the voice key. Records for its "
                   "duration, until the screen ends, or until the participant stops speaking.")
    outputs = {
        "file": {"desc": "The recording made by {who} (WAV file, relative to the session folder)", "type": "text",
                 "kind": "response"},
        "rt": {"desc": "Speech onset in {who}: seconds from its onset flip until speech started; empty = no speech",
               "units": "s", "type": "number", "kind": "rt"},
        "offset": {"desc": "Speech offset in {who}: seconds from its onset flip until speech ended", "units": "s",
                   "type": "number", "kind": "timing"},
        "duration": {"desc": "Length of the recording made by {who} (s)", "units": "s", "type": "number",
                     "kind": "timing"},
        "source": {"desc": "What timed the speech onset in {who}: voice_key (the voice key device), recording "
                           "(the detector on the recording), browser (Try it)", "type": "text", "kind": "other"},
    }
    props_schema = {
        "samplerate": {"type": "int", "default": 44100, "help": "samples per second (44100 or 48000 for speech; 16000 is enough for transcription)"},
        "channels": {"type": "choice", "choices": [1, 2], "default": 1, "help": "1 = mono (one microphone), 2 = stereo"},
        "device": {"type": "str", "default": "", "help": "microphone name or number (empty = the computer's default input)"},
        "voice_key": {"type": "device", "default": None,
                      "help": "a voice key device that times the speech onset (empty = the experiment's voice key, if it has one; "
                              "otherwise the onset is found in the recording)"},
        "stop_after_speech": {"type": "bool", "default": False,
                              "help": "stop recording (and finish this item) once the participant has spoken and then been quiet"},
        "threshold_db": {"type": "float", "default": -30.0, "help": "loudness (dB below full scale) that counts as speech"},
        "min_ms": {"type": "float", "default": 15.0, "help": "it must stay loud this long to count as speech (ignores clicks)"},
        "release_ms": {"type": "float", "default": 300.0, "help": "quiet this long after speech = they stopped speaking"},
        "response_marker": {"type": "str", "default": None, "help": "marker sent at the moment speech starts"},
    }

    # ------------------------------------------------------------------ validation
    @classmethod
    def validate_spec(cls, spec, where, exp):
        from ..model import Issue
        issues = super().validate_spec(spec, where, exp)
        p = spec.props
        sr = _num(p.get("samplerate", 44100))
        if sr is not None and not 8000 <= sr <= 192000:
            issues.append(Issue("error", f"{where}.samplerate", f"a sample rate of {p.get('samplerate')} isn't one a "
                                "microphone records at", hint="44100 or 48000 (16000 is enough for transcription)"))
        for k, lo, hi, what in (("threshold_db", -120, 0, "a loudness in dB below full scale, between -120 and 0"),
                                ("min_ms", 0, 2000, "milliseconds, between 0 and 2000"),
                                ("release_ms", 1, 10000, "milliseconds, between 1 and 10000")):
            v = _num(p.get(k)) if k in p else None
            if v is not None and not lo <= v <= hi:
                issues.append(Issue("error", f"{where}.{k}", f"'{k}' must be {what}"))
        vk = p.get("voice_key")
        if vk and isinstance(vk, str) and not expressions.is_expr(vk):
            d = next((x for x in exp.devices if x.id == vk), None)
            if d is None:
                issues.append(Issue("error", where, f"there is no device called '{vk}' to time the speech onset",
                                    hint=", ".join(x.id for x in exp.devices if x.type == "voice_key")
                                    or "add a voice key under Devices, or leave this empty to time it from the recording"))
            elif d.type != "voice_key":
                issues.append(Issue("error", where, f"'{vk}' is a {d.type}, not a voice key",
                                    hint="leave it empty to time the speech onset from the recording"))
        r = _routine_of(spec, exp)
        open_ended = spec.duration is None and spec.duration_frames is None and not spec.stop_if
        if open_ended and not p.get("stop_after_speech") and r is not None and r.duration is None and not r.end_if:
            enders = [c for c in r.components if c is not spec and c.end_routine]
            if spec.end_routine or not enders:
                issues.append(Issue("warning", where, "this recording has no length and doesn't stop after speech, so "
                                    "nothing ends the screen: it would record for ever",
                                    hint="give it a duration (e.g. 3 s), turn on 'stop after speech', or let another "
                                         "item end the screen"))
        return issues + _window_issues(spec, where)

    # ------------------------------------------------------------------ lifecycle
    def prepare(self) -> None:
        super().prepare()
        p = self.p
        self.sr = int(p["samplerate"] or 44100)
        self.ch = int(p["channels"] or 1)
        self.th_db, self.min_ms, self.rel_ms = float(p["threshold_db"]), float(p["min_ms"]), float(p["release_ms"])
        self.rel = (self.th_db, self.min_ms, self.rel_ms)
        index = getattr(self.run.runner, "routine_count", 0) + 1
        from ..audio import audio_filename
        self.file = audio_filename(index, self.run.routine.id, self.id)
        self.out.update(file=None, rt=None, offset=None, duration=None, source=None)
        self.speech_on: float | None = None       # from the simulated participant / the browser / the live detector
        self.speech_off: float | None = None
        self.vk_on: float | None = None
        self.vk_off: float | None = None
        self.marked = False
        self.vk_id, self.vk_input = self._voice_key()
        be = self.backend
        if be.name == "browser":
            self.mode = "browser"
        elif self.session.virtual_participant is not None or (be.name == "headless" and not getattr(be, "realtime", False)):
            self.mode = "simulated"
        else:
            self.mode = "live"
        self.rec: Any = None
        if self.mode == "live":          # pragma: no cover - needs a microphone
            from ..audio import INSTALL_HINT, MicRecorder, have_sounddevice
            if not have_sounddevice():
                raise RuntimeError(f"the microphone item '{self.id}' needs sounddevice and numpy to record: "
                                   f"{INSTALL_HINT} (a Test run simulates the recording without them)")
            # recording starts now, before the onset flip; the file is cut to the item's own start and stop
            self.rec = MicRecorder(self.sr, self.ch, p["device"], self.session.clock, *self.rel)
            self.rec.start()

    def _voice_key(self) -> tuple[str | None, str]:
        want = self.p.get("voice_key")
        for d in self.session.exp.devices:
            if (want and d.id == want) or (not want and d.type == "voice_key"):
                if d.id in self.session.devices:
                    return d.id, str((d.options or {}).get("input_name") or "voice")
        return None, "voice"

    def on_start(self, t: float) -> None:
        if self.mode == "browser":
            self.backend.start_recording(self.file, {"samplerate": self.sr, "channels": self.ch,
                                                     "threshold_db": self.th_db, "min_ms": self.min_ms,
                                                     "release_ms": self.rel_ms})
        self.session.notify_response_window(self, None, None)

    def on_event(self, ev: InputEvent) -> None:
        if ev.kind == "speech" and self.mode != "live":      # the virtual participant, or the browser's detector
            if ev.down and self.speech_on is None:
                self.speech_on = ev.time
            elif not ev.down and self.speech_on is not None:
                self.speech_off = ev.time
        elif ev.kind == "device" and self.vk_id and ev.device == self.vk_id and ev.name == self.vk_input:
            if self.t_start is not None and ev.time < self.t_start:
                return
            if ev.down and self.vk_on is None:
                self.vk_on = ev.time
            elif not ev.down and self.vk_on is not None:
                self.vk_off = ev.time

    def on_frame(self, t: float) -> None:
        if self.rec is not None:          # pragma: no cover - needs a microphone
            while self.rec.events:
                tt, down = self.rec.events.popleft()
                if self.t_start is not None and tt < self.t_start:
                    continue
                if down and self.speech_on is None:
                    self.speech_on = tt
                elif not down and self.speech_on is not None:
                    self.speech_off = tt
        onset = self.vk_on if self.vk_on is not None else self.speech_on
        if onset is not None and not self.marked:
            self.marked = True
            self.send_response_marker(onset)
        if self.p["stop_after_speech"]:
            off = self.vk_off if self.vk_on is not None else self.speech_off
            if off is not None and (self.mode == "live" or t >= off + self.rel_ms / 1e3):
                self.finished = True

    def on_stop(self, t: float) -> None:
        t0 = self.t_start if self.t_start is not None else t
        length = max(0.0, t - t0)
        onset = offset = None
        source = None
        root = self.session.data.root if self.session.data else None
        if self.mode == "browser":
            self.backend.stop_recording(self.file, str(root / self.file) if root else None)
            if self.speech_on is not None:
                onset, source = self.speech_on - t0, "browser"
                offset = self.speech_off - t0 if self.speech_off is not None else None
        else:
            from ..audio import detect_speech, simulate_recording, write_wav
            if self.mode == "simulated":
                sp = None if self.speech_on is None else self.speech_on - t0
                sp_len = (self.speech_off - self.speech_on) if self.speech_off is not None and sp is not None else length
                samples: Any = simulate_recording(length, self.sr, sp, sp_len,
                                                  seed=(self.session.seed + getattr(self.run.runner, "routine_count", 0)))
            else:                         # pragma: no cover - needs a microphone
                rec_obj, self.rec = self.rec, None
                t_first, rec = rec_obj.stop()
                if rec_obj.problems:
                    self.session.warnings.append(f"{self.file}: the microphone dropped audio {rec_obj.problems} time(s) "
                                                 "(the computer was too busy); the recording may have gaps")
                i0 = max(0, int(round((t0 - (t_first if t_first is not None else t0)) * self.sr)))
                samples = rec[i0:i0 + int(round(length * self.sr))]
            if root is not None:
                write_wav(root / self.file, samples, self.sr, self.ch)
            mono = samples[:, 0] if getattr(samples, "ndim", 1) == 2 else samples
            onset, offset = detect_speech(mono, self.sr, *self.rel)
            source = "recording" if onset is not None else None
        if self.vk_on is not None:
            onset, source = self.vk_on - t0, "voice_key"
            offset = self.vk_off - t0 if self.vk_off is not None else None
        self.out.update(file=self.file if root is not None else None, duration=round(length, 4),
                        rt=None if onset is None else round(onset, 4),
                        offset=None if offset is None else round(offset, 4), source=source)

    def release(self) -> None:
        if self.rec is not None:          # pragma: no cover - the routine stopped with an error mid-recording
            try:
                self.rec.stop()
            except Exception:
                pass
            self.rec = None


# ============================================================================ gamepad
# what EDGE calls the buttons of a standard game controller (pyglet's controller names and the browser's standard
# Gamepad mapping both map to these)
GAMEPAD_BUTTONS = ["a", "b", "x", "y", "lb", "rb", "lt", "rt", "back", "start", "ls", "rs", "up", "down", "left", "right",
                   "guide"]
STICK_DIRECTIONS = ["stick_left", "stick_right", "stick_up", "stick_down",
                    "rstick_left", "rstick_right", "rstick_up", "rstick_down"]
AXES = ["lx", "ly", "rx", "ry", "lt", "rt"]


def stick_direction(axis: str, value: float) -> str | None:
    """lx -0.8 -> stick_left; ry 0.9 -> rstick_up (up is +1)."""
    if axis not in ("lx", "ly", "rx", "ry"):
        return None
    pre = "stick" if axis[0] == "l" else "rstick"
    if axis[1] == "x":
        return f"{pre}_{'right' if value > 0 else 'left'}"
    return f"{pre}_{'up' if value > 0 else 'down'}"


def _gamepad_name_ok(name: str) -> bool:
    return name in GAMEPAD_BUTTONS or name in STICK_DIRECTIONS or \
        (name.startswith("button") and name[6:].isdigit())


class Gamepad(Component):
    type_name = "gamepad"
    category = "response"
    description = ("A response on a gamepad or joystick: which button (a, b, x, y, lb, rb, lt, rt, up, down …), its RT "
                   "from this item's onset, the stick positions at that moment; optionally pushing a stick past a "
                   "threshold counts as the response, and the stick positions can be saved on every frame.")
    outputs = {
        "button": {"desc": "Which button (or stick direction) of {who} responded; empty = no response", "type": "text",
                   "kind": "response"},
        "rt": {"desc": "Response time (s) of {who}, from its onset flip to the response", "units": "s", "type": "number",
               "kind": "rt"},
        "corr": {"desc": "Correctness of the {who} response: 1 = correct, 0 = incorrect", "type": "0/1",
                 "kind": "accuracy", "when": "correct"},
        "time": {"desc": "Master-clock time (s) of the {who} response", "units": "s", "type": "number", "kind": "timing"},
        "axes": {"desc": "Stick and trigger positions at the {who} response (lx, ly, rx, ry: -1..1, up and right "
                         "positive; lt, rt: 0..1)", "type": "dict", "kind": "response"},
        "gamepad": {"desc": "Which controller gave the {who} response", "type": "text", "kind": "other"},
        "path": {"desc": "Stick positions on every frame of {who} (time, lx, ly, rx, ry)", "type": "list",
                 "kind": "response", "when": "track"},
    }
    props_schema = {
        "buttons": {"type": "list", "default": None,
                    "help": "buttons that count, e.g. [a, b] or [lb, rb]; stick directions too (stick_left, stick_right …); empty = any"},
        "correct": {"type": "str", "default": None, "help": "the correct button (often a trial-list column: $correct_button)"},
        "axis_threshold": {"type": "float", "default": None,
                           "help": "pushing a stick this far (0..1) counts as a response (stick_left, stick_up …); empty = only buttons"},
        "deadzone": {"type": "float", "default": 0.1, "help": "stick positions closer to the centre than this count as 0"},
        "track": {"type": "bool", "default": False, "help": "save the stick positions on every frame"},
        "gamepad": {"type": "int", "default": None, "help": "which controller: 0 = the first; empty = any"},
        "keys": {"type": "dict", "default": {},
                 "help": "keyboard keys that also count, e.g. {f: lb, j: rb}: for Try it and piloting without a gamepad"},
        "response_marker": {"type": "str", "default": None, "help": "marker sent at the moment of the response"},
    }

    @classmethod
    def validate_spec(cls, spec, where, exp):
        from ..model import Issue
        import difflib
        issues = super().validate_spec(spec, where, exp)
        p = spec.props
        names = p.get("buttons")
        names = [names] if isinstance(names, str) and not expressions.is_expr(names) else names
        known = GAMEPAD_BUTTONS + STICK_DIRECTIONS
        vals = [str(n) for n in names or [] if not expressions.is_expr(n)] if isinstance(names, list) else []
        corr = p.get("correct")
        if isinstance(corr, str) and corr and not expressions.is_expr(corr) and corr.lower() != "none":
            vals.append(corr)
        for n in dict.fromkeys(vals):
            if not _gamepad_name_ok(n):
                close = difflib.get_close_matches(n.lower(), known, 1, 0.5)
                issues.append(Issue("warning", where, f"'{n}' isn't a gamepad button EDGE knows, so it never responds",
                                    hint=(f"did you mean '{close[0]}'? " if close else "") +
                                    "Buttons: a, b, x, y, lb, rb, lt, rt, back, start, up, down, left, right; a joystick's "
                                    "buttons are button1, button2 …; sticks: stick_left, stick_up …"))
            elif n in STICK_DIRECTIONS and p.get("axis_threshold") in (None, "") and n in [str(x) for x in names or []]:
                issues.append(Issue("warning", where, f"'{n}' is a stick direction, but sticks only count with an axis threshold",
                                    hint="set axis_threshold, e.g. 0.5"))
        for k, lo, hi in (("axis_threshold", 0.05, 1.0), ("deadzone", 0.0, 0.9)):
            v = _num(p.get(k)) if p.get(k) is not None else None
            if v is not None and not lo <= v <= hi:
                issues.append(Issue("error", f"{where}.{k}", f"'{k}' must be between {lo} and {hi} (a stick's position "
                                    "goes from -1 to 1)"))
        dz, th = _num(p.get("deadzone", 0.1)), _num(p.get("axis_threshold"))
        if dz is not None and th is not None and th <= dz:
            issues.append(Issue("error", f"{where}.axis_threshold", f"the axis threshold ({th}) must be beyond the "
                                f"deadzone ({dz}), or the stick can never reach it"))
        keys = p.get("keys")
        if isinstance(keys, dict):
            issues += _key_name_issues([str(k) for k in keys], None, where)
        return issues + _window_issues(spec, where)

    def prepare(self) -> None:
        super().prepare()
        from .responses import _key_list
        self.allowed = _key_list(self.p["buttons"])
        self.keymap = {str(k): str(v) for k, v in (self.p.get("keys") or {}).items()}
        self.th = float(self.p["axis_threshold"]) if self.p.get("axis_threshold") not in (None, "") else None
        self.dz = float(self.p["deadzone"] or 0.0)
        self.pad = self.p.get("gamepad")
        self.path: list[list[float]] = []
        self.pushed: set[str] = set()          # stick directions currently past the threshold
        self.out.update(button=None, rt=None, corr=None)
        try:
            self.names = self.backend.open_gamepads()
        except Exception as e:        # pragma: no cover - a driver problem: say it, keys still work
            self.names = []
            self.session.warnings.append(f"gamepad: {e}")

    def on_start(self, t: float) -> None:
        self.session.notify_response_window(self, self.allowed, self.p["correct"])

    def _axes(self) -> dict[str, float]:
        raw = self.backend.gamepad_axes(self.pad) or {}
        return {k: (0.0 if abs(float(v)) < self.dz else round(float(v), 4)) for k, v in raw.items()}

    def on_frame(self, t: float) -> None:
        if self.p["track"] and self.t_start is not None:
            a = self._axes()
            self.path.append([round(t - self.t_start, 4)] + [a.get(k, 0.0) for k in ("lx", "ly", "rx", "ry")])

    def on_event(self, ev: InputEvent) -> None:
        name = None
        pad = ev.meta.get("gamepad") if ev.meta else None
        if self.pad not in (None, "") and pad is not None and int(pad) != int(self.pad):
            return
        if ev.kind == "gamepad" and ev.down:
            name = ev.name
        elif ev.kind == "gamepad_axis" and self.th is not None:
            v = float(ev.meta.get("value", 0.0))
            d = stick_direction(ev.name, v)
            for other in [x for x in self.pushed if x.startswith(("rstick" if ev.name[0] == "r" else "stick") + "_")
                          and x.endswith(("left", "right") if ev.name[1] == "x" else ("up", "down"))]:
                if abs(v) < self.th or other != d:
                    self.pushed.discard(other)      # back towards the centre: it can count again
            if d is None or abs(v) < self.th or d in self.pushed:
                return
            self.pushed.add(d)
            name = d
        elif ev.kind == "key" and ev.down and ev.name in self.keymap:
            name = self.keymap[ev.name]
        if name is None or self.out["button"] is not None:
            return
        if self.allowed is not None and name not in self.allowed:
            return
        if self.t_start is not None and ev.time < self.t_start:
            return
        self.out.update(button=name, rt=self.rt(ev.time), time=ev.time, axes=self._axes(),
                        gamepad=(ev.meta or {}).get("name") or ("keyboard" if ev.kind == "key" else
                                                               (self.names[int(pad)] if pad is not None and int(pad) < len(self.names)
                                                                else "gamepad")))
        corr = self.p["correct"]
        if corr is not None:
            self.out["corr"] = int(str(name) == str(corr))
        self.finished = True
        self.send_response_marker(ev.time)

    def on_stop(self, t: float) -> None:
        if self.p["track"]:
            self.out["path"] = self.path
        if self.out["button"] is None and self.p["correct"] is not None:
            self.out["corr"] = int(str(self.p["correct"]).lower() in ("none", ""))


COMPONENTS = [Microphone, Gamepad]
