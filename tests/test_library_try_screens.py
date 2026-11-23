"""Try this screen on library tasks whose screens use values an earlier screen prepares (Corsi sequences,
operation-span letter sets, a score shown on the thanks screen) explains itself instead of crashing."""
from __future__ import annotations

import time

import pytest
import yaml

import edge.library as L
from edge.play import PlayManager


def _try(tmp_path, task, routine):
    path = L.copy_task(task, tmp_path / task)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    pm = PlayManager(tmp_path)
    try:
        pm.start(doc, path.parent, routine, 3, data_root=tmp_path / "try")
    except ValueError as e:
        return str(e)
    end = time.time() + 5
    while time.time() < end:
        f = pm.frame()
        if not f.get("running"):
            return f.get("error")
        pm.input({"kind": "key", "name": "space", "down": True})
        time.sleep(0.05)
    pm.stop()
    return None


@pytest.mark.parametrize("task, routine", [("corsi", "light"), ("corsi", "echo"), ("corsi2", "light"),
                                           ("aospan", "letter"), ("digit_substitution", "thanks")])
def test_try_this_screen_says_to_use_the_whole_experiment(tmp_path, task, routine):
    err = _try(tmp_path, task, routine)
    assert err is None or "can only be tried as part of the whole experiment" in err, err
    assert "IndexError" not in str(err) and "isn't defined here" not in str(err)
