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
}


def write_template(name: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = TEMPLATES[name]
    path = directory / f"{data['name']}.yaml"
    save_document(path, copy.deepcopy(data))
    return path
