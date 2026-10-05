"""Starter experiments for ``edge new <template>`` and the builder's "New" menu."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import copy

from .storage import save_document

_INSTR = lambda text: {  # noqa: E731
    "components": [
        {"id": "text", "type": "text", "text": text, "height": 30},
        {"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True},
    ]
}

TEMPLATES: dict[str, dict[str, Any]] = {
    "blank": {
        "name": "my_experiment",
        "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
        "devices": [],
        "routines": {"hello": _INSTR("Hello! Press SPACE to finish.")},
        "flow": ["hello"],
    },
    "freeview_eyetracking": {
        "name": "freeview",
        "description": "Free viewing of images with gaze AOIs. Swap sim_eyetracker for tobii or gazepoint.",
        "settings": {"window": {"size": [1280, 720], "background": "#808080"}},
        "devices": [{"id": "et", "type": "sim_eyetracker", "calibrate": True},
                    {"id": "lsl", "type": "lsl_markers", "required": False}],
        "routines": {
            "instructions": _INSTR("Look at the pictures freely.\n\nPress SPACE to start."),
            "fixcheck": {"description": "Gaze-contingent fixation check: look at the dot for 300 ms",
                         "duration": 5,
                         "components": [
                             {"id": "dot", "type": "shape", "shape": "circle", "radius": 8, "fill": "white"},
                             {"id": "roi", "type": "gaze_roi", "pos": [0, 0], "radius": 60, "dwell": 0.3,
                              "end_routine": True}]},
            "view": {"duration": 4, "components": [
                {"id": "left_img", "type": "shape", "shape": "rect", "pos": [-300, 0], "size": [400, 300],
                 "fill": "$left_color", "marker": "$f'view_{left_color}_{right_color}'"},
                {"id": "right_img", "type": "shape", "shape": "rect", "pos": [300, 0], "size": [400, 300],
                 "fill": "$right_color"},
                {"id": "aoi_left", "type": "gaze_roi", "target": "left_img"},
                {"id": "aoi_right", "type": "gaze_roi", "target": "right_img"}]},
        },
        "flow": ["instructions", {"loop": "trials", "order": "random",
                                  "conditions": [{"left_color": "#c04040", "right_color": "#4040c0"},
                                                 {"left_color": "#4040c0", "right_color": "#c04040"}],
                                  "repeats": 3, "children": ["fixcheck", "view"]}],
    },
    "eeg_oddball": {
        "name": "auditory_oddball",
        "description": "Auditory oddball with TTL + LSL markers. Swap sim_eeg for gtec / lsl_inlet.",
        "settings": {"window": {"size": [1280, 720], "background": "#000000"},
                     "markers": {"codes": {"standard": 1, "deviant": 2, "response": 10}}},
        "devices": [{"id": "eeg", "type": "sim_eeg"},
                    {"id": "ttl", "type": "ttl_loopback"},
                    {"id": "lsl", "type": "lsl_markers", "required": False}],
        "routines": {
            "instructions": _INSTR("Press SPACE whenever you hear the HIGH tone.\n\nPress SPACE to start."),
            "tone": {"duration": "$isi", "components": [
                {"id": "fix", "type": "fixation"},
                {"id": "beep", "type": "sound", "sound": "$freq", "tone_duration": 0.1, "marker": "$kind"},
                {"id": "resp", "type": "keyboard", "keys": ["space"], "correct": "$target",
                 "response_marker": "response"}]},
        },
        "flow": ["instructions", {"loop": "trials", "order": "fullrandom", "repeats": 10, "max_repeat": {"kind": {"deviant": 1}},
                                  "conditions": [{"kind": "standard", "freq": 1000, "target": "none", "isi": 1.0},
                                                 {"kind": "standard", "freq": 1000, "target": "none", "isi": 1.1},
                                                 {"kind": "standard", "freq": 1000, "target": "none", "isi": 1.2},
                                                 {"kind": "standard", "freq": 1000, "target": "none", "isi": 1.0},
                                                 {"kind": "deviant", "freq": 1500, "target": "space", "isi": 1.1}],
                                  "children": ["tone"]}],
    },
    "staircase": {
        "name": "contrast_staircase",
        "description": "3-down/1-up staircase on stimulus opacity (~79% correct threshold).",
        "settings": {"window": {"size": [1280, 720], "background": "#808080"}},
        "routines": {
            "trial": {"components": [
                {"id": "pick", "type": "code", "on_begin": "import random\nside = random.choice([-1, 1])"},
                {"id": "fix", "type": "fixation", "duration": 0.4},
                {"id": "target", "type": "shape", "shape": "rect", "size": [120, 120], "fill": "white",
                 "opacity": "$contrast", "pos": "$[side * 250, 0]", "start": 0.4, "duration": 0.2},
                {"id": "resp", "type": "keyboard", "keys": ["left", "right"], "start": 0.4, "end_routine": True,
                 "correct": "$'right' if side > 0 else 'left'"}]},
        },
        "flow": [{"loop": "stairs", "staircase": {"variable": "contrast", "start": 0.6, "step": [0.1, 0.05, 0.02],
                                                  "down": 3, "up": 1, "min": 0.01, "max": 1, "reversals": 8,
                                                  "max_trials": 60, "correct": "resp.corr"},
                  "children": ["trial"]}],
        "variables": {"side": 1},
    },
    "online_questionnaire": {
        "name": "wellbeing_survey",
        "description": "A complete questionnaire study: consent (declining ends the study), demographics, "
                       "SWLS + WHO-5 + TIPI with attention checks, a custom block with display logic, debriefing.",
        "settings": {"window": {"size": [1280, 720], "background": "#f7f8fa"}},
        "routines": {
            "consent": {"components": [{"id": "consent_form", "type": "survey", "end_routine": True,
                                        "questions": [{"instrument": "consent"}]}]},
            "survey": {"components": [{"id": "survey", "type": "survey", "end_routine": True,
                                       "title": "Well-being and personality",
                                       "intro": "There are no right or wrong answers. Please answer honestly.",
                                       "questions": [
                                           {"instrument": "demographics"}, {"type": "page_break"},
                                           {"instrument": "swls"}, {"instrument": "attention_checks"},
                                           {"type": "page_break"}, {"instrument": "who5"}, {"instrument": "tipi"},
                                           {"type": "page_break"},
                                           {"id": "exercise", "type": "single", "required": True, "layout": "horizontal",
                                            "text": "Do you exercise regularly?", "options": ["Yes", "No"]},
                                           {"id": "exercise_types", "type": "multiple", "min_choices": 1,
                                            "text": "Which kinds of exercise? Select all that apply.",
                                            "options": ["Running", "Cycling", "Swimming", "Team sports", "Gym", "Yoga",
                                                        "Other"],
                                            "show_if": {"exercise": "Yes"}, "randomize": True},
                                           {"id": "exercise_minutes", "type": "slider", "min": 0, "max": 600,
                                            "step": 10, "labels": ["0 min", "10 h"],
                                            "text": "About how many minutes per week do you spend on {{answer.exercise_types}}?",
                                            "show_if": {"exercise": "Yes"}},
                                           {"id": "priorities", "type": "rank",
                                            "text": "Rank what matters most for your well-being.",
                                            "options": ["Health", "Relationships", "Work", "Money", "Free time"]},
                                           {"instrument": "debrief"}]}]},
            "goodbye": {"duration": 4, "components": [{"id": "bye", "type": "text", "color": "#222222",
                                                       "text": "Thank you! Your answers have been saved."}]},
            "declined": {"duration": 4, "components": [{"id": "msg", "type": "text", "color": "#222222",
                                                        "text": "You chose not to take part. Thank you for your time."}]},
        },
        "flow": [{"statemachine": "study", "start": "consent", "states": {
            "consent": {"run": ["consent"], "next": [{"if": "$consent_form.consent == 'yes'", "goto": "questions"},
                                                     {"goto": "declined"}]},
            "questions": {"run": ["survey", "goodbye"]},
            "declined": {"run": ["declined"]}}}],
    },
}


# ---------------------------------------------------------------- starting points for the tutorials
# (hidden from template lists: names start with "tutorial_")
_TRIAL = {"components": [
    {"id": "fix", "type": "fixation", "duration": 0.5},
    {"id": "stimulus", "type": "text", "text": "$word", "color": "$ink", "start": 0.5, "height": 60},
    {"id": "resp", "type": "keyboard", "keys": ["r", "g", "b"], "start": 0.5, "duration": 2, "correct": "$key",
     "end_routine": True}]}
_STROOP_ROWS = [{"word": "RED", "ink": "red", "key": "r"}, {"word": "RED", "ink": "green", "key": "g"},
                {"word": "GREEN", "ink": "green", "key": "g"}, {"word": "GREEN", "ink": "blue", "key": "b"},
                {"word": "BLUE", "ink": "blue", "key": "b"}, {"word": "BLUE", "ink": "red", "key": "r"}]

TEMPLATES.update({
    "tutorial_empty": {"name": "my_first_experiment", "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
                       "devices": [], "variables": {}, "routines": {}, "flow": []},
    "tutorial_loops": {"name": "stroop_lists", "settings": {"window": {"size": [1280, 720], "background": "#111111"}},
                       "routines": {"trial": _TRIAL},
                       "flow": [{"loop": "trials", "conditions": _STROOP_ROWS, "children": ["trial"]}]},
    "tutorial_practice": {
        "name": "practice_until_criterion",
        "settings": {"window": {"size": [1280, 720], "background": "#111111"}},
        "routines": {
            "trial": {"components": _TRIAL["components"] + [
                {"id": "hint", "type": "text", "text": "r = red, g = green, b = blue", "pos": [0, -200],
                 "height": 24, "start_if": "$False"}]},
            "feedback": {"duration": 0.6, "components": [
                {"id": "fb", "type": "text", "text": "$'Correct!' if resp.corr else 'Wrong'",
                 "color": "$'#55dd55' if resp.corr else '#ff5555'"}]},
            "main_trial": _TRIAL},
        "flow": [{"loop": "practice", "conditions": _STROOP_ROWS, "order": "random", "children": ["trial", "feedback"]},
                 {"loop": "main", "conditions": _STROOP_ROWS, "order": "random", "repeats": 3,
                  "children": ["main_trial"]}]},
    "tutorial_gaze": {
        "name": "gaze_task", "settings": {"window": {"size": [1280, 720], "background": "#808080"}},
        "routines": {"look": {"duration": 4, "components": [
            {"id": "left_box", "type": "shape", "pos": [-300, 0], "size": [300, 300], "fill": "#c04040"},
            {"id": "right_box", "type": "shape", "pos": [300, 0], "size": [300, 300], "fill": "#4040c0"}]}},
        "flow": [{"loop": "trials", "repeats": 6, "children": ["look"]}]},
    "tutorial_survey": {
        "name": "my_survey", "settings": {"window": {"size": [1280, 720], "background": "#111111"}},
        "routines": {"task": {"duration": 2, "components": [
            {"id": "msg", "type": "text", "text": "(imagine a task here)\n\nThe questionnaire comes next."}]}},
        "flow": ["task"]},
    "tutorial_stroop": {
        "name": "stroop_data", "settings": {"window": {"size": [1280, 720], "background": "#111111"}},
        "routines": {"trial": _TRIAL},
        "flow": [{"loop": "trials", "conditions": _STROOP_ROWS, "order": "random", "repeats": 3, "children": ["trial"]}]},
})


def public_templates() -> dict[str, dict[str, Any]]:
    return {k: v for k, v in TEMPLATES.items() if not k.startswith("tutorial_")}


def write_template(name: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = TEMPLATES[name]
    path = directory / f"{data['name']}.yaml"
    save_document(path, copy.deepcopy(data))
    return path
