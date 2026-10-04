import json

import pytest

from edge.participant import VirtualParticipant

HZ = 60.0
FRAME = 1 / HZ


def text_frames(be, text):
    return be.frames_showing(lambda k, p: k == "text" and p.get("text") == text)


def test_frame_exact_durations(run):
    d = {"routines": {"r": {"components": [
        {"id": "a", "type": "text", "text": "A", "duration": 0.5},
        {"id": "b", "type": "text", "text": "B", "start": 0.5, "duration": 0.25},
        {"id": "c", "type": "text", "text": "C", "start_frame": 3, "duration_frames": 2},
    ]}}, "flow": ["r"]}
    summary, session, be = run(d)
    fa, fb, fc = text_frames(be, "A"), text_frames(be, "B"), text_frames(be, "C")
    assert len(fa) == 30 and fa[0] == 0          # 0.5 s at 60 Hz, on the routine's first flip
    assert len(fb) == 15 and fb[0] == 30          # starts exactly when A ends, no gap/overlap
    assert fc == [3, 4]
    assert summary["timing"]["dropped_frames"] == 0


def test_rt_measured_from_onset_flip(run):
    d = {"routines": {"r": {"components": [
        {"id": "stim", "type": "text", "text": "X", "start": 0.5},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "start": 0.5, "end_routine": True, "correct": "j"},
    ]}}, "flow": ["r"]}
    t0 = 1000.0 + FRAME  # first flip of the session on the virtual clock
    onset = t0 + 0.5

    def script(be):
        be.press("x", onset + 0.1)      # not allowed: ignored
        be.press("j", onset + 0.4321)

    summary, session, be = run(d, script=script)
    row = session.data.trial_rows[0]
    assert row["resp.keys"] == "j" and row["resp.corr"] == 1
    assert row["resp.rt"] == pytest.approx(0.4321, abs=1e-9)
    # routine ended on the frame after the response
    assert row["routine_duration"] < 0.5 + 0.4321 + 3 * FRAME


def test_keys_before_onset_are_discarded(run):
    d = {"routines": {"r": {"components": [
        {"id": "resp", "type": "keyboard", "keys": ["space"], "start": 1.0, "end_routine": True}]}},
        "flow": ["r"]}

    def script(be):
        be.press("space", 1000.2)
        be.press("space", 1001.5)

    _, session, _ = run(d, script=script)
    assert session.data.trial_rows[0]["resp.rt"] == pytest.approx(1001.5 - (1000 + FRAME + 1.0), abs=1e-9)


def test_markers_time_locked_to_flips(run):
    d = {"devices": [{"id": "ttl", "type": "ttl_loopback"}],
         "settings": {"markers": {"codes": {"stim": 42}}},
         "routines": {"r": {"duration": 1, "components": [
             {"id": "s", "type": "shape", "start": 0.25, "duration": 0.25, "marker": {"onset": "stim", "offset": "stim_off"}},
             {"id": "m", "type": "marker", "label": "$f'cond_{3 * 2}'", "start": 0.6}]}},
         "flow": ["r"]}
    summary, session, be = run(d)
    flips = [f["t"] for f in be.frame_log]
    sent = session.devices["ttl"].sent
    codes = [c for _, c in sent]
    assert 42 in codes
    stim_t = next(t for t, c in sent if c == 42)
    assert stim_t == flips[15]  # 0.25 s * 60 Hz
    assert summary["marker_codebook"]["stim"] == 42
    assert "cond_6" in summary["marker_codebook"] and "stim_off" in summary["marker_codebook"]
    events = [json.loads(l) for l in (session.data.root / "events.jsonl").read_text().splitlines()]
    stim = next(e for e in events if e["label"] == "stim")
    assert stim["on_flip"] and stim["time"] == flips[15] and "ttl" in stim["delivered"]


def test_loops_branching_and_variables(run):
    d = {"variables": {"score": 0},
         "routines": {
             "trial": {"components": [
                 {"id": "t", "type": "text", "text": "$word", "duration": 0.1},
                 {"id": "v", "type": "variable", "set": {"score": "$score + n"}}]},
             "good": {"duration": 0.1, "components": [{"id": "g", "type": "text", "text": "good"}]},
             "bad": {"duration": 0.1, "components": [{"id": "b", "type": "text", "text": "bad"}]},
         },
         "flow": [{"loop": "trials", "conditions": [{"word": "a", "n": 1}, {"word": "b", "n": 2}], "repeats": 3,
                   "order": "random", "children": ["trial"]},
                  {"if": "$score == 9", "then": ["good"], "else": ["bad"]},
                  {"routine": "bad", "if": "$trials.total != 6"}]}
    summary, session, be = run(d)
    rows = session.data.trial_rows
    assert [r["routine"] for r in rows][-1] == "good"
    assert len([r for r in rows if r["routine"] == "trial"]) == 6
    assert summary["variables"]["score"] == 9
    assert rows[0]["trials.n"] == 0 and "word" in rows[0]


def test_loop_stop_if(run):
    d = {"variables": {"k": 0},
         "routines": {"r": {"duration": 0.05, "components": [{"id": "v", "type": "variable", "set": {"k": "$k + 1"}}]}},
         "flow": [{"loop": "L", "repeats": 100, "stop_if": "$k >= 4", "children": ["r"]}]}
    summary, session, _ = run(d)
    assert summary["variables"]["k"] == 4 and summary["loops"]["L"]["stopped_at"] == 3


def test_code_component_sets_variables_before_others_prepare(run):
    d = {"routines": {"r": {"duration": 0.1, "components": [
        {"id": "c", "type": "code", "on_begin": "label = 'hi ' + str(trials.n)", "on_end": "done = True"},
        {"id": "t", "type": "text", "text": "$label"}]}},
         "flow": [{"loop": "trials", "repeats": 2, "children": ["r"]}]}
    summary, session, be = run(d)
    assert text_frames(be, "hi 0") and text_frames(be, "hi 1")
    assert session.vars["done"] is True


def test_dynamic_properties_update_every_frame(run):
    d = {"routines": {"r": {"duration": 0.2, "components": [
        {"id": "s", "type": "shape", "pos": "$[frame * 10, 0]"}]}}, "flow": ["r"]}
    _, _, be = run(d)
    xs = [p["pos"][0] for f in be.frame_log for k, p in f["drawn"] if k == "rect"]
    assert xs[:4] == [0, 10, 20, 30]


def test_mouse_clicks_on_targets(run):
    d = {"routines": {"r": {"components": [
        {"id": "left", "type": "shape", "pos": [-200, 0], "size": [100, 100]},
        {"id": "right", "type": "shape", "pos": [200, 0], "size": [100, 100]},
        {"id": "m", "type": "mouse", "clickable": ["left", "right"], "correct": "right", "end_routine": True}]}},
        "flow": ["r"]}

    def script(be):
        be.click((0, 0), 1000.3)          # misses both targets
        be.click((210, -20), 1000.6)

    _, session, _ = run(d, script=script)
    row = session.data.trial_rows[0]
    assert row["m.clicked"] == "right" and row["m.corr"] == 1 and row["m.x"] == 210


def test_gaze_roi_with_mouse_gaze(run):
    d = {"devices": [{"id": "g", "type": "mouse_gaze"}],
         "routines": {"r": {"duration": 3, "components": [
             {"id": "roi", "type": "gaze_roi", "pos": [300, 0], "radius": 50, "dwell": 0.5, "end_routine": True}]}},
         "flow": ["r"]}

    def script(be):
        be.move_mouse((300, 10), 1001.0)

    _, session, _ = run(d, script=script)
    row = session.data.trial_rows[0]
    assert row["roi.entered"] == 1 and row["roi.completed"] == 1
    assert row["roi.first_entry"] == pytest.approx(1.0, abs=2 * FRAME)
    assert row["routine_duration"] == pytest.approx(1.5, abs=3 * FRAME)


def test_escape_aborts_and_saves(run):
    d = {"routines": {"r": {"components": [{"id": "t", "type": "text", "text": "forever"}]}}, "flow": ["r"]}

    def script(be):
        be.escape_at = 1000.5

    summary, session, _ = run(d, script=script)
    assert summary["aborted"] is True
    assert (session.data.root / "session.json").exists()


def test_dry_run_detects_routines_that_never_end(run):
    d = {"routines": {"r": {"components": [{"id": "t", "type": "text", "text": "forever"}]}}, "flow": ["r"]}
    with pytest.raises(RuntimeError, match="did not end"):
        run(d, vp=VirtualParticipant())


def test_staircase_loop_runs_with_virtual_participant(run):
    d = {"routines": {"trial": {"components": [
        {"id": "s", "type": "shape", "opacity": "$contrast", "duration": 0.1},
        {"id": "resp", "type": "keyboard", "keys": ["y", "n"], "correct": "y", "end_routine": True}]}},
        "flow": [{"loop": "stairs", "staircase": {"variable": "contrast", "start": 0.5, "step": 0.05,
                                                  "reversals": 6, "max_trials": 40, "correct": "resp.corr"},
                  "children": ["trial"]}]}
    summary, _, _ = run(d, vp=VirtualParticipant(accuracy=0.8, seed=2))
    st = summary["loops"]["stairs"]
    assert st["trials"] > 6 and st["threshold"] is not None


def test_full_session_files(run, tmp_path):
    d = {"devices": [{"id": "eeg", "type": "sim_eeg"}],
         "routines": {"r": {"duration": 0.5, "components": [
             {"id": "t", "type": "text", "text": "x", "marker": "go"}]}},
         "flow": [{"loop": "L", "repeats": 4, "children": ["r"]}]}
    summary, session, _ = run(d)
    root = session.data.root
    for f in ("session.json", "trials.csv", "trials.jsonl", "events.jsonl", "frames.csv", "streams/eeg.eeg.csv"):
        assert (root / f).exists(), f
    assert not list((root / "streams").glob("*.raw.csv"))
    header = (root / "streams/eeg.eeg.csv").read_text().splitlines()[0]
    assert header.startswith("time,device_time,arrival_time,Fz")
