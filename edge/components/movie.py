"""The ``movie`` component: a video file, frame-locked to the screen refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import expressions
from .stimuli import _VISUAL_COMMON, VisualComponent

FALLBACK_SECONDS = 5.0      # Test runs of a video whose length can't be read, without a duration


class Movie(VisualComponent):
    type_name = "movie"
    description = ("Video file, frame-locked to the screen. MP4, WebM, MOV …; the item ends with the video (or "
                   "loops); the data say when its first frame appeared and whether frames were dropped.")
    dynamic = {"pos", "opacity", "ori", "size", "volume"}
    props_schema = {
        "movie": {"type": "file", "default": "", "required": True, "accept": "video",
                  "help": "video file (mp4, webm, mov …) relative to the experiment, or $column"},
        "size": {"type": "vec2", "default": None, "aspect": True, "help": "width, height; empty = the video's own size"},
        "loop": {"type": "bool", "default": False, "help": "start again at the end (until the item's duration ends)"},
        "volume": {"type": "float", "default": 1.0, "min": 0, "max": 1, "step": 0.05,
                   "help": "sound track volume, 0 (muted) to 1"},
        **_VISUAL_COMMON,
    }
    outputs = {
        "onset": {"desc": "Onset of {who} (s from routine start, at the screen flip)", "units": "s", "type": "number",
                  "kind": "timing"},
        "first_frame": {"desc": "When the first video frame of {who} appeared (s from routine start, at the flip)",
                        "units": "s", "type": "number", "kind": "timing"},
        "duration": {"desc": "How long {who} was on the screen (s)", "units": "s", "type": "number", "kind": "timing"},
        "movie_duration": {"desc": "Length of the video file of {who} (s)", "units": "s", "type": "number",
                           "kind": "timing"},
        "frames_shown": {"desc": "Video frames of {who} that were shown", "units": "frames", "type": "number",
                         "kind": "timing"},
        "frames_dropped": {"desc": "Video frames of {who} that were never shown although their time came",
                           "units": "frames", "type": "number", "kind": "timing"},
        "frames_repeated": {"desc": "Screen refreshes on which {who} showed a frame longer than its time",
                            "units": "frames", "type": "number", "kind": "timing"},
        "ended": {"desc": "Whether {who} played to its end (1) or was stopped earlier (0)", "type": "number",
                  "kind": "timing"},
    }

    # ------------------------------------------------------------------ validation
    @classmethod
    def validate_spec(cls, spec, where, exp):
        from ..model import Issue
        from ..video import video_problems
        issues = super().validate_spec(spec, where, exp)
        v = spec.props.get("movie")
        files: list[str] = []
        column = None
        if isinstance(v, str) and v.startswith("$"):
            src = v[1:].strip()
            if src.isidentifier():
                from ..pitfalls import _column_values, _loops_around
                rid = where.split(".")[1] if where.count(".") >= 2 else ""
                vals = _column_values(exp, _loops_around(exp).get(rid, []), src)
                files = [str(x) for x in vals or [] if isinstance(x, str) and x.strip()]
                column = src
        elif isinstance(v, str) and v.strip():
            files = [v]
        elif v in (None, "") and "movie" in spec.props:
            issues.append(Issue("error", where, "no video chosen yet", hint="choose a video file (MP4 or WebM) next "
                                "to the experiment, or a trial-list column ($column)"))
        elif v not in (None, "") and not isinstance(v, str):
            issues.append(Issue("error", where, "movie must be a file name (or $column)"))
        base = Path(exp.base_dir)
        seen: set[tuple[str, str]] = set()
        for f in dict.fromkeys(files):
            p = Path(f) if Path(f).is_absolute() else base / f
            if not p.exists():
                continue                      # "video not found" comes from the file checks (pitfalls)
            for level, msg, hint in video_problems(p):
                key = (level, msg.replace(p.name, "{}"))
                if column and key in seen:
                    continue                  # one note per kind of problem for a whole trial-list column
                seen.add(key)
                if column:
                    msg = f"trial-list column '{column}': {msg}"
                issues.append(Issue(level, where, msg, hint=hint))
        if spec.end_routine is False and spec.props.get("loop") is True and spec.duration is None:
            issues.append(Issue("info", where, "a looping video without a duration keeps the screen going until "
                                "something else ends it", hint="give it a duration, or end the screen with a response"))
        return issues

    # ------------------------------------------------------------------ lifecycle
    def stim_props(self) -> dict[str, Any]:
        p = self.p
        return {"movie": str(p["movie"]), "size": self.px(p["size"]) if p["size"] else None,
                "pos": self.px(p["pos"]), "opacity": p["opacity"], "ori": p["ori"],
                "volume": float(p["volume"] if p["volume"] is not None else 1.0), "loop": bool(p["loop"])}

    def make_stim(self):
        return self.backend.make_movie(**self.stim_props())

    def prepare(self) -> None:
        super().prepare()
        from ..video import FrameLock
        st = self.stim
        dur = st.duration()
        self._known = dur is not None and dur > 0
        if not self._known:
            sched = self.spec.duration
            try:
                d = expressions.resolve(sched, self.run.namespace()) if sched is not None else None
                dur = float(d) if d is not None else None
            except Exception:
                dur = None
            dur = dur if dur and dur > 0 else (FALLBACK_SECONDS if self.backend.name in ("headless", "browser") else None)
        self.movie_len = dur
        fps = st.fps() or 30.0
        self.lock = FrameLock(fps, self.backend.refresh_rate, st.frames())
        self._loop_base = 0.0
        self._prev_vt = -1.0
        self._end_t: float | None = None
        self._first_pending = False
        self._first_done = False
        self.out.update(movie_duration=round(self.movie_len, 4) if self._known else None, ended=0)

    def on_frame(self, t: float) -> None:
        if self.finished:
            return
        if self._first_pending and not self._first_done and self.session.last_flip is not None:
            self._mark_first(self.session.last_flip)
        if self.refresh_dynamic():
            self.stim.set(**self.stim_props())
            vol = self.p.get("volume")
            if hasattr(self.stim, "set_volume") and vol is not None:
                self.stim.set_volume(float(vol))
        anchor = self.t_start if self.t_start is not None else t
        vt = t - anchor - self._loop_base
        half = self.backend.frame_interval / 2
        L = self.movie_len
        if L is not None and vt >= L - half:
            if self.p.get("loop"):
                while vt >= L - half:
                    self._loop_base += L
                    vt -= L
                self.stim.rewind()
                self.lock.loops += 1
            else:
                self._finish(t, ended=True)
                return
        k = self.lock.target(vt)
        shown = self.stim.show(vt, k)
        if shown is None:                       # the decoder reached the end before the header's length
            if self.p.get("loop") and getattr(self.stim, "can_rewind", True):
                self._loop_base += vt
                self.stim.rewind()
                shown = self.stim.show(0.0, 0)
            if shown is None:
                self._finish(t, ended=True)
                return
        self.lock.shown(shown, k)
        if not self._first_done:
            self._first_pending = True
        self.stim.draw()

    def _mark_first(self, flip: float) -> None:
        self._first_done = True
        self._first_pending = False
        self.out["first_frame"] = round(flip - self.run.t0, 6) if self.run.t0 is not None else None

    def _finish(self, t: float, ended: bool) -> None:
        self.finished = True
        self._force_stop = True               # the engine stops a finished visual item at the next refresh
        self._end_t = t
        self.out["ended"] = 1 if ended else 0
        self.stim.stop_audio()

    def on_start(self, t: float) -> None:
        super().on_start(t)
        if self._first_pending:
            self._mark_first(t)
        vol = float(self.p.get("volume") if self.p.get("volume") is not None else 1.0)
        if vol > 0:
            self.stim.start_audio(vol)

    def on_stop(self, t: float) -> None:
        if self._first_pending and not self._first_done:
            self._mark_first(t)
        end = min(t, self._end_t) if self._end_t is not None else t
        if self.t_start is not None:
            self.out["duration"] = round(end - self.t_start, 6)
        self.out.setdefault("first_frame", None)
        self.out.update(self.lock.stats())
        self.stim.stop_audio()

    def release(self) -> None:
        try:
            self.stim.release()
        except Exception:
            pass


COMPONENTS = [Movie]
