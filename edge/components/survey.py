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
        "language": {"type": "str", "default": "",
                     "help": "page language, e.g. en, de, es, fr, he: translates buttons and messages; "
                             "he switches to right-to-left"},
        "direction": {"type": "choice", "choices": ["auto", "ltr", "rtl"], "default": "auto",
                      "help": "auto follows the language, or the first letters of the title and questions"},
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
        problems = sv.validate(qs, spec.props.get("scores") or {})
        for msg in problems:
            issues.append(Issue("error", where, msg))
        if not problems:
            for f in sv.media_files(qs):
                if "$" not in f and "{{" not in f and not (Path(exp.base_dir) / f).exists():
                    issues.append(Issue("error", where, f"file not found: {f}",
                                        hint="put it next to the experiment file (paths are relative to it)"))
            for q in qs:
                if isinstance(q, dict) and q.get("type") == "drill_down" and isinstance(q.get("file"), str):
                    if not (Path(exp.base_dir) / q["file"]).exists():
                        issues.append(Issue("error", where, f"drill-down file not found: {q['file']}"))
        return issues

    def _source(self) -> tuple[str, Path]:
        spec = {k: self.p.get(k) for k in self.props_schema}
        spec["questions"] = load_drill_files(spec.get("questions") or [], Path(self.session.exp.base_dir))
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
        # signatures, uploads, recordings and screenshots become files in the session folder
        folder = Path(self.session.data.root) / "survey_files" if self.session.data is not None else None
        n = self.run.runner.routine_count if hasattr(self.run.runner, "routine_count") else 0
        data = sv.extract_files(self.flat, data, folder, prefix=f"{self.id}_{n}_")
        self.out.update(sv.process(self.flat, self.scores, data))
        self.out["submitted"] = 1
        self.out["rt"] = self.rt(t)
        self.finished = True


def load_drill_files(questions: list[Any], base: Path) -> list[Any]:
    """drill_down questions may take their tree from a CSV/XLSX file (one column per level)."""
    out = []
    for q in questions:
        if isinstance(q, dict) and q.get("type") == "drill_down" and isinstance(q.get("file"), str) and not q.get("tree"):
            from ..conditions import load_conditions
            rows = load_conditions(q["file"], base)
            levels = q.get("levels") or [k for k in (rows[0] if rows else {}) if not str(k).startswith("_")]
            q = {**q, "levels": levels, "rows": [[r.get(lv, "") for lv in levels] for r in rows]}
        out.append(q)
    return out


COMPONENTS = [Survey]
