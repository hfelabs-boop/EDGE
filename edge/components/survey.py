"""The survey component: professional questionnaires from structured questions (see edge/survey.py)."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from .. import survey as sv
from .html import Html


class Survey(Html):
    type_name = "survey"
    category = "stimulus"
    description = ("A questionnaire page: single and multiple choice, Likert items and matrices, sliders, text, "
                   "rank order, constant sum and more, plus validated scales (PHQ-9, GAD-7, Big Five, SUS …) "
                   "with automatic scoring. Every answer and score becomes a data column.")
    props_schema = {
        "questions": {"type": "survey", "default": [], "required": True,
                      "help": "the questions, in order; {instrument: phq9} adds a library questionnaire"},
        "title": {"type": "str", "default": "", "help": "heading on the first page"},
        "intro": {"type": "text", "default": "", "help": "instructions under the title (HTML allowed)"},
        "progress_bar": {"type": "bool", "default": True, "help": "show progress across pages"},
        "allow_back": {"type": "bool", "default": True, "help": "participants may go back to earlier pages"},
        "submit_label": {"type": "str", "default": "", "help": "text of the last button (default: Submit)"},
        "next_label": {"type": "str", "default": "", "help": "text of the Next button"},
        "back_label": {"type": "str", "default": "", "help": "text of the Back button"},
        "scores": {"type": "dict", "default": {},
                   "help": "extra scores: {name: {items: [...], method: sum|mean, reverse: [...], bands: [[max, label]]}}"},
        "labels": {"type": "dict", "default": {},
                   "help": "translate messages, e.g. {required: 'Bitte beantworten Sie diese Frage.'}"},
        "css": {"type": "text", "default": "", "help": "extra CSS for the page"},
        "display": Html.props_schema["display"],
        "fullscreen": Html.props_schema["fullscreen"],
    }

    @classmethod
    def validate_spec(cls, spec, where, exp):
        from ..model import Issue
        from .base import Component
        issues = Component.validate_spec.__func__(cls, spec, where, exp)
        qs = spec.props.get("questions")
        if not isinstance(qs, list) or not qs:
            issues.append(Issue("error", where, "the survey has no questions yet",
                                hint="add a question or a questionnaire from the library"))
            return issues
        for msg in sv.validate(qs, spec.props.get("scores") or {}):
            issues.append(Issue("error", where, msg))
        return issues

    def _source(self) -> tuple[str, Path]:
        spec = {k: self.p.get(k) for k in self.props_schema}
        rng = random.Random(self.session.rng.random())    # reproducible from the session seed
        page, self.flat, self.scores = sv.render_html(spec, rng)
        return page, Path(self.session.exp.base_dir)

    RAW = ("questions", "scores", "labels", "css")     # used as written (question text may contain '$')

    def resolve_all(self) -> dict[str, Any]:
        self.p = {k: (self.spec.props.get(k, self.props_schema[k]["default"]) if k in self.RAW else self.prop(k))
                  for k in self.all_props()}
        self.p["continue_button"] = "no"
        self.p["continue_label"] = ""
        return self.p

    def auto_answers(self, rng: random.Random) -> dict[str, Any]:
        return sv.auto_answer(self.flat, rng)

    def _accept(self, data: dict[str, Any], t: float) -> None:
        self.out.update(sv.process(self.flat, self.scores, data))
        self.out["submitted"] = 1
        self.out["rt"] = self.rt(t)
        self.finished = True


COMPONENTS = [Survey]
