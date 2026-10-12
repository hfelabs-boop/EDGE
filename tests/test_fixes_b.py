"""Regression tests for group B of the usability audit: data, export, conditions, validation."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

import pytest

from edge.conditions import load_conditions, order_trials
from edge.model import Experiment
from edge.participant import VirtualParticipant
from tests.conftest import run_headless

ROOT = Path(__file__).resolve().parent.parent


def issues_of(doc: dict, base: Path) -> list:
    return Experiment.from_dict(doc, base_dir=base).validate()


def errors(issues) -> list[str]:
    return [str(i) for i in issues if i.level == "error"]


# ------------------------------------------------------------------ docs#0: experiment variables
def test_experiment_variables_count_as_defined(tmp_path):
    doc = {"name": "v", "variables": {"is_practice": True, "greeting": "hello"},
           "routines": {"r": {"duration": 0.3, "components": [
               {"id": "fb", "type": "text", "text": "$greeting", "if": "$is_practice"}]}},
           "flow": ["r"]}
    assert errors(issues_of(doc, tmp_path)) == []


# ------------------------------------------------------------------ data#1: max_repeat across repeats
def test_max_repeat_holds_across_repeat_boundaries():
    rows = list(csv.DictReader((ROOT / "examples/stroop/stroop.csv").open(encoding="utf-8")))
    bad = 0
    for seed in range(300):
        seq = order_trials(rows, "random", 3, random.Random(seed), {"ink": 2})
        bad += any(a["ink"] == b["ink"] == c["ink"] for a, b, c in zip(seq, seq[1:], seq[2:]))
        assert sorted(r["_row"] for r in seq) == sorted(list(range(len(rows))) * 3)
    assert bad == 0


def test_max_repeat_block_that_cannot_follow_still_runs():
    seq = order_trials([{"c": "r"}, {"c": "r"}], "random", 3, random.Random(0), {"c": 2})
    assert len(seq) == 6          # impossible across blocks: each block is still valid on its own


# ------------------------------------------------------------------ data#9 / importers#7: unquoted commas
def test_unquoted_comma_in_conditions_is_an_error(tmp_path):
    (tmp_path / "cond.csv").write_text("sentence,correct_key\nThe cat sat,f\nHello, world,j\nShort one,f\n")
    with pytest.raises(ValueError, match=r"cond.csv row 3 has 3 values but only 2 column names.*double quotes"):
        load_conditions("cond.csv", tmp_path)
    doc = {"name": "b", "routines": {"trial": {"components": [
        {"id": "s", "type": "text", "text": "$sentence"},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$correct_key", "end_routine": True}]}},
        "flow": [{"loop": "trials", "conditions": "cond.csv", "children": ["trial"]}]}
    issues = issues_of(doc, tmp_path)
    errs = errors(issues)
    assert len(errs) == 1 and "row 3" in errs[0]
    assert not [i for i in issues if i.level == "warning"]       # no follow-on "not defined" noise


def test_quoted_commas_and_trailing_blanks_are_fine(tmp_path):
    (tmp_path / "c.csv").write_text('a,b,c\n"Hello, world",j,\nx,y\nq,r,s,,\n')
    rows = load_conditions("c.csv", tmp_path)
    assert rows == [{"a": "Hello, world", "b": "j", "c": None}, {"a": "x", "b": "y", "c": None},
                    {"a": "q", "b": "r", "c": "s"}]


def test_psychopy_fixture_reads_its_colour_column():
    rows = load_conditions("trialTypes.csv", ROOT / "tests/fixtures/psychopy")
    assert rows[0] == {"text": "red", "letterColor": "$[1,-1,-1]", "corrAns": "left", "congruent": 1}


# ------------------------------------------------------------------ data#20 / docs#9: conditions: $block_file
def _blocks(tmp_path: Path, text: str = "$word", cond: str = "$block_file") -> dict:
    for name, words in (("easy", ("cat", "dog")), ("hard", ("zephyr", "quixotic"))):
        (tmp_path / f"{name}.csv").write_text("word,correct_key,difficulty\n"
                                              + "".join(f"{w},f,{name}\n" for w in words))
    return {"name": "cb", "routines": {"trial": {"components": [
        {"id": "w", "type": "text", "text": text},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$correct_key", "end_routine": True,
         "duration": 2}]}},
        "flow": [{"loop": "blocks", "conditions": [{"block_file": "easy.csv"}, {"block_file": "hard.csv"}],
                  "order": "latin_square",
                  "children": [{"loop": "trials", "conditions": cond, "order": "random", "children": ["trial"]}]}]}


def test_counterbalanced_block_files_are_checked_through_the_outer_loop(tmp_path):
    issues = issues_of(_blocks(tmp_path), tmp_path)
    assert [i for i in issues if i.level in ("error", "warning")] == []
    typo = errors(issues_of(_blocks(tmp_path, text="$wrd"), tmp_path))
    assert len(typo) == 1 and "Did you mean 'word'" in typo[0]
    # a list chosen by an expression EDGE can't follow: an honest note, not a false "no column" warning
    issues = issues_of(_blocks(tmp_path, cond="$block_file + ''"), tmp_path)
    assert [i for i in issues if i.level in ("error", "warning")] == []
    notes = [i for i in issues if i.level == "info" and "can't be checked before running" in i.message]
    assert notes


def test_recording_plan_knows_block_file_columns(tmp_path):
    from edge.measures import recording_plan
    plan = recording_plan(Experiment.from_dict(_blocks(tmp_path), base_dir=tmp_path))
    trials = next(lp for lp in plan["loops"] if lp["loop"] == "trials")
    assert trials["columns"] == ["correct_key", "difficulty", "word"]


# ------------------------------------------------------------------ docs#10 / mcp#10: routine duration, end_if, repeats
def _routine_doc(**routine) -> dict:
    return {"name": "r", "routines": {"r": {**routine, "components": [{"id": "t", "type": "text", "text": "hi"}]}},
            "flow": ["r"]}


@pytest.mark.parametrize("value, needle", [("1 s", "'1 s' isn't a number"), (-3, "can't be negative"),
                                           ({"a": 1}, "must be a number of seconds")])
def test_routine_duration_is_checked(tmp_path, value, needle):
    errs = errors(issues_of(_routine_doc(duration=value), tmp_path))
    assert any("routines.r.duration" in e and needle in e for e in errs), errs


def test_bare_word_duration_has_no_dollar_hint(tmp_path):
    errs = errors(issues_of(_routine_doc(duration="abc"), tmp_path))
    assert len(errs) == 1 and "'abc' isn't defined" in errs[0] and "leading '$'" not in errs[0]


def test_routine_end_if_syntax_is_checked(tmp_path):
    errs = errors(issues_of(_routine_doc(end_if="$t >"), tmp_path))
    assert any("routines.r.end_if" in e and "isn't a valid expression" in e for e in errs)


def test_repeats_words_are_explained(tmp_path):
    doc = _routine_doc(duration=1)
    doc["flow"] = [{"loop": "L", "repeats": "two times", "children": ["r"]}]
    errs = errors(issues_of(doc, tmp_path))
    assert any("repeats must be a whole number" in e for e in errs)


# ------------------------------------------------------------------ docs#20: quoting hint, all problems in one pass
def test_unquoted_text_in_a_comparison_gets_the_quote_hint(tmp_path):
    doc = {"name": "q", "routines": {"r": {"components": [
        {"id": "a", "type": "text", "text": "$ink == red", "duration": 1},
        {"id": "b", "type": "text", "text": "$x = 1", "duration": 1}]}},
        "flow": [{"loop": "L", "conditions": [{"ink": "red"}, {"ink": "blue"}], "children": ["r"]}]}
    errs = errors(issues_of(doc, tmp_path))
    assert any("put it in quotes: 'red'" in e for e in errs)          # the name problem ...
    assert any("isn't a valid expression" in e for e in errs)         # ... next to the syntax error


# ------------------------------------------------------------------ mcp#15: rule goto targets
def _goto_doc(target: str, in_workflow: bool = True) -> dict:
    routines = {"a": {"duration": 1, "rules": [{"when": "$t > 0.5", "do": [{"goto": target}]}],
                      "components": [{"id": "t", "type": "text", "text": "a"}]},
                "b": {"duration": 1, "components": [{"id": "t", "type": "text", "text": "b"}]}}
    flow = [{"statemachine": "session", "start": "first",
             "states": {"first": {"run": ["a"], "next": "second"}, "second": {"run": ["b"]}}}] if in_workflow else ["a", "b"]
    return {"name": "g", "routines": routines, "flow": flow}


def test_goto_to_a_missing_state_is_an_error(tmp_path):
    errs = errors(issues_of(_goto_doc("nowhere"), tmp_path))
    assert any("goto 'nowhere'" in e and "no such state" in e and "first" in e for e in errs)
    assert errors(issues_of(_goto_doc("second"), tmp_path)) == []
    assert errors(issues_of(_goto_doc("end"), tmp_path)) == []
    assert any("isn't inside a workflow" in e for e in errors(issues_of(_goto_doc("second", False), tmp_path)))


# ------------------------------------------------------------------ docs#1: options [Yes, No] read by YAML as booleans
def test_yes_no_options_stay_words():
    from edge import survey as sv
    import yaml
    qs = yaml.safe_load("""
- {id: caffeine, type: single, text: "Caffeine today?", options: [Yes, No]}
- {id: cups, type: number, text: "How many?", show_if: {caffeine: Yes}}
""")
    assert qs[0]["options"] == [True, False]             # what YAML hands over
    flat, _ = sv.expand(qs)
    assert flat[0]["options"] == [{"value": "Yes", "label": "Yes"}, {"value": "No", "label": "No"}]
    assert flat[1]["show_if"] == {"caffeine": "Yes"}
    assert sv.condition_holds(flat[1]["show_if"], {"caffeine": "Yes"})
    assert not sv.condition_holds(flat[1]["show_if"], {"caffeine": "No"})


def test_bare_no_in_a_choice_property_gets_a_quoting_hint(tmp_path):
    doc = {"name": "h", "routines": {"r": {"components": [
        {"id": "h", "type": "html", "html": "<p>x</p>", "continue_button": False, "end_routine": True}]}}, "flow": ["r"]}
    issue = next(i for i in issues_of(doc, tmp_path) if "continue_button" in i.message)
    assert 'continue_button: "no"' in issue.hint


# ------------------------------------------------------------------ docs#3: clicking / looking at an image of native size
def _png(path: Path, w: int, h: int) -> None:
    import struct
    import zlib
    raw = b"".join(b"\x00" + b"\x80\x40\x40" * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_click_on_images_without_a_size(tmp_path):
    _png(tmp_path / "a.png", 200, 150)
    _png(tmp_path / "b.png", 200, 150)
    doc = {"name": "c", "devices": [{"id": "et", "type": "sim_eyetracker"}],
           "routines": {"trial": {"components": [
               {"id": "left", "type": "image", "image": "$left_img", "pos": [-300, 0]},
               {"id": "right", "type": "image", "image": "$right_img", "pos": [300, 0]},
               {"id": "click", "type": "mouse", "clickable": ["left", "right"], "correct": "$target", "end_routine": True},
               {"id": "aoi", "type": "gaze_roi", "target": "left"}]}},
           "flow": [{"loop": "trials", "conditions": [{"left_img": "a.png", "right_img": "b.png", "target": "left"},
                                                      {"left_img": "b.png", "right_img": "a.png", "target": "right"}],
                     "children": ["trial"]}]}
    assert errors(issues_of(doc, tmp_path)) == []
    summary, session, _ = run_headless(doc, tmp_path, vp=VirtualParticipant(seed=3), simulate=True)
    assert not summary.get("errors")
    rows = [r for r in session.data.trial_rows if r["routine"] == "trial"]
    assert len(rows) == 2 and all(r["click.clicked"] in ("left", "right") for r in rows)


def test_backend_hit_test_uses_the_native_size(tmp_path):
    from edge.backends.headless import HeadlessBackend
    _png(tmp_path / "a.png", 200, 150)
    be = HeadlessBackend()
    be.base_dir = tmp_path
    stim = be.make_image(image="a.png", size=None, pos=(100, 0))
    assert stim.contains(190, 70) and not stim.contains(210, 0)


# ------------------------------------------------------------------ importers#18: damaged picture files
def test_damaged_picture_is_an_error(tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "blue.png").write_bytes(b"PNG")
    _png(tmp_path / "img" / "ok.png", 4, 4)
    doc = {"name": "p", "routines": {"r": {"duration": 1, "components": [
        {"id": "stim", "type": "image", "image": "$stimulus"}]}},
        "flow": [{"loop": "L", "conditions": [{"stimulus": "img/blue.png"}, {"stimulus": "img/ok.png"}],
                  "children": ["r"]}]}
    errs = errors(issues_of(doc, tmp_path))
    assert len(errs) == 1 and "img/blue.png is not a readable picture" in errs[0]


# ------------------------------------------------------------------ docs#4: udp_messages variables exist from the start
def test_listed_udp_variables_exist_before_the_first_message():
    from types import SimpleNamespace
    from edge.devices import create_device
    dev = create_device("udp_messages", "bci", {"port": 0, "host": "127.0.0.1", "variables": ["alpha", "decision"]})
    dev.session = SimpleNamespace(vars={"decision": "start"}, participant={})
    dev.connect()
    try:
        assert dev.session.vars == {"alpha": None, "decision": "start"}     # experiment values are kept
        assert dict(dev.live()) == {"alpha": None, "decision": None}
    finally:
        dev.close()


# ------------------------------------------------------------------ docs#7: device_response inputs vs the device's names
def _box_doc(inputs: list) -> dict:
    return {"name": "box", "devices": [{"id": "box", "type": "serial_inputs",
                                        "options": {"port": "COM4", "inputs": {1: "left", 2: "right", 5: "trigger"}}}],
            "routines": {"r": {"components": [{"id": "press", "type": "device_response", "device": "box",
                                               "inputs": inputs, "end_routine": True}]}},
            "flow": ["r"]}


def test_device_response_inputs_are_checked(tmp_path):
    assert [i for i in issues_of(_box_doc(["left", "trigger"]), tmp_path) if i.level in ("error", "warning")
            and "routines.r.press" in i.where] == []
    warn = [i for i in issues_of(_box_doc(["lefft"]), tmp_path) if i.level == "warning" and "lefft" in i.message]
    assert warn and "Did you mean 'left'" in warn[0].message
    errs = errors(issues_of(_box_doc([5]), tmp_path))
    assert any("is called 'trigger'" in e for e in errs)


def test_devices_doc_button_box_snippet_names_its_trigger():
    text = (ROOT / "docs/DEVICES.md").read_text(encoding="utf-8")
    assert "5: trigger" in text and "variables: {alpha: 0}" in text


# ------------------------------------------------------------------ export
from edge import export as ex  # noqa: E402

TASK = {"name": "flank", "settings": {"participant": {"participant": "001", "session": "1"}},
        "routines": {
            "intro": {"components": [{"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
            "trial": {"components": [
                {"id": "stim", "type": "text", "text": "$s"},
                {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$ans", "duration": 2,
                 "end_routine": True}]}},
        "flow": ["intro", {"loop": "trials", "repeats": 3, "order": "random",
                           "conditions": [{"s": "<<<", "cong": "congruent", "ans": "f"},
                                          {"s": "<><", "cong": "incongruent", "ans": "j"}],
                           "children": ["trial"]}]}


def _run(tmp_path, doc=TASK, pid="001", seed=1, **kw):
    d = dict(doc, settings={"participant": {"participant": pid, "session": "1"}})
    summary, session, _ = run_headless(d, tmp_path, vp=VirtualParticipant(seed=seed), **kw)
    return session.data.root


def test_folder_with_several_experiments_is_exported_per_experiment(tmp_path):
    _run(tmp_path)
    _run(tmp_path, dict(TASK, name="other"), pid="002")
    res = ex.export_many(tmp_path / "data", ["csv"], tmp_path / "out")
    assert sorted(res["experiments"]) == ["flank", "other"]
    trials = sorted((tmp_path / "out").glob("*_trials.csv"))
    assert [f.name.split("_all_")[0] for f in trials] == ["flank", "other"]
    for f in trials:
        assert len({r["experiment"] for r in csv.DictReader(f.open(encoding="utf-8-sig"))}) == 1
    assert any("2 different experiments" in n for n in res["notes"])


def test_merged_tables_tell_sessions_apart_and_dictionary_covers_all_rows(tmp_path):
    a = _run(tmp_path, pid="001", seed=1)
    b = _run(tmp_path, pid="001", seed=2)          # the same participant and session id, twice
    c = _run(tmp_path, pid="002", seed=3)
    res = ex.export_many(tmp_path / "data", ["csv", "bids"], tmp_path / "out", name="all")
    sessions = list(csv.DictReader((tmp_path / "out" / "all_sessions.csv").open(encoding="utf-8-sig")))
    assert sorted(r["session_folder"] for r in sessions) == sorted(p.name for p in (a, b, c))
    assert {r["session"] for r in sessions} == {"1"}          # the participant's own field is kept
    summary = list(csv.DictReader((tmp_path / "out" / "all_summary.csv").open(encoding="utf-8-sig")))
    overall = [r for r in summary if r["factor"] == "(all)"]
    assert len(overall) == 3 and len({r["session_folder"] for r in overall}) == 3
    dd = {r["column"]: r for r in csv.DictReader((tmp_path / "out" / "all_dictionary.csv").open(encoding="utf-8-sig"))}
    n_rows = res["trials"]
    assert int(dd["participant"]["n"]) == n_rows and json.loads(dd["participant"]["levels"]) == ["001", "002"]
    # BIDS: the two folders of 001/1 become run-1 and run-2 instead of overwriting each other
    beh = sorted(p.name for p in (tmp_path / "out" / "bids").rglob("*_beh.tsv"))
    assert beh == ["sub-001_ses-1_task-flank_run-1_beh.tsv", "sub-001_ses-1_task-flank_run-2_beh.tsv",
                   "sub-002_ses-1_task-flank_beh.tsv"]
    assert any("run-1" in n for n in res["notes"])


def test_bids_labels_keep_people_apart():
    def st(pid, started):
        s = ex.SessionTables.__new__(ex.SessionTables)
        s.root, s.meta = Path(f"/x/{pid}_{started}"), {"participant": {"participant": pid, "session": "1"},
                                                         "experiment": "t", "started": started}
        return s
    names, notes = ex.bids_names([st("é01", "a"), st("e01", "b")])
    assert sorted(v[0] for v in names.values()) == ["e01", "e01x2"]
    assert any("'é01' is sub-e01" in n for n in notes)


def test_bids_times_share_the_session_start_and_tsv_has_no_bom(tmp_path):
    root = _run(tmp_path, dict(TASK, devices=[{"id": "et", "type": "sim_eyetracker"}]), simulate=True)
    files = ex.export_session(root, ["bids"], tmp_path / "o")
    events = next(f for f in files if f.name.endswith("_events.tsv"))
    assert events.read_bytes()[:5] == b"onset"
    beh = next(f for f in files if f.name.endswith("_beh.tsv"))
    rows = list(csv.DictReader(beh.open(encoding="utf-8"), delimiter="\t"))
    starts = [float(r["trial.start"]) for r in rows if r.get("trial.start")]
    assert starts and 0 < min(starts) < 60                 # seconds from session start, not the master clock
    physio = next(f for f in files if f.name.endswith("_physio.tsv.gz"))
    import gzip
    first = float(gzip.open(physio, "rt").readline().split("\t")[0])
    sidecar = json.loads(next(f for f in files if f.name.endswith("_physio.json")).read_text())
    assert abs(first - sidecar["StartTime"]) < 1e-6 and 0 <= first < 5
    assert sidecar["x"]["Units"] == "px" and sidecar["pupil_l"]["Units"] == "mm" and "centre" in sidecar["CoordinateSystem"]
    meta = json.loads((root / "session.json").read_text())
    assert meta["devices"]["et"]["streams"]["gaze"]["units"][:2] == ["px", "px"]


def test_summary_columns_must_exist(tmp_path):
    st = ex.SessionTables(_run(tmp_path))
    with pytest.raises(ValueError, match=r"no column 'resp\.reaction'.*did you mean resp\.rt"):
        ex.summarize(st, rt="resp.reaction")
    with pytest.raises(ValueError, match="no column 'colour'"):
        ex.summarize(st, by=["colour"])
    st.experiment["settings"] = {"data": {"summary": {"rt": "resp.rtt", "by": ["congruency"]}}}
    cols, rows, info = ex.summarize(st)
    assert info["rt_column"] == "resp.rt" and rows[0]["miss_rate"] < 1
    assert any("resp.rtt" in p for p in info["problems"]) and any("congruency" in p for p in info["problems"])


def test_summary_settings_are_validated(tmp_path):
    doc = dict(TASK, settings={"data": {"summary": {"rt": "resp.rtt", "by": ["congruency"]}}})
    warns = [i for i in issues_of(doc, tmp_path) if i.level == "warning" and "settings.data.summary" in i.where]
    assert any("resp.rtt" in i.message and "resp.rt" in i.hint for i in warns)


def test_summary_ignores_keys_that_only_continue(tmp_path):
    doc = {"name": "fv", "routines": {
        "intro": {"components": [{"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
        "view": {"duration": 1, "components": [{"id": "img", "type": "text", "text": "$pic"}]}},
        "flow": ["intro", {"loop": "trials", "conditions": [{"pic": "a.png", "side": "l"}, {"pic": "b.png", "side": "r"}],
                           "children": ["view"]}]}
    cols, rows, info = ex.summarize(ex.SessionTables(_run(tmp_path, doc)))
    assert info["rt_column"] is None and "miss_rate" not in cols
    assert info["factors"] == ["side"]                       # file names aren't conditions


def test_break_screen_in_blocks_is_not_the_response(tmp_path):
    doc = {"name": "bl", "routines": {
        "brk": {"components": [{"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
        "view": {"duration": 0.5, "components": [{"id": "s", "type": "text", "text": "$cond"}]}},
        "flow": [{"loop": "blocks", "repeats": 2, "children": [
            {"loop": "trials", "conditions": [{"cond": "a"}, {"cond": "b"}], "children": ["view"]}, "brk"]}]}
    cols, rows, info = ex.summarize(ex.SessionTables(_run(tmp_path, doc)))
    assert info["rt_column"] is None and rows[0]["n_trials"] == 4


def test_answer_key_column_is_not_a_factor(tmp_path):
    doc = dict(TASK, routines=dict(TASK["routines"], trial={"components": [
        {"id": "stim", "type": "text", "text": "$s"},
        {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$target", "duration": 2, "end_routine": True}]}),
        flow=["intro", {"loop": "trials", "conditions": [{"s": "x", "target": "f"}, {"s": "y", "target": "j"}],
                        "children": ["trial"]}])
    _, _, info = ex.summarize(ex.SessionTables(_run(tmp_path, doc)))
    assert "target" not in info["factors"]


def test_formats_and_packages_are_checked_before_writing(tmp_path, monkeypatch):
    root = _run(tmp_path)
    with pytest.raises(ValueError, match="unknown export format 'sav'"):
        ex.export_session(root, ["csv", "sav"], tmp_path / "a")
    assert not (tmp_path / "a").exists()
    monkeypatch.setattr(ex, "_have", lambda m: False)
    with pytest.raises(ValueError) as e:
        ex.export_session(root, ["csv", "parquet", "mat"], tmp_path / "b")
    msg = str(e.value)
    assert f'"{__import__("sys").executable}" -m pip install pyarrow' in msg and "scipy" in msg
    assert "Nothing was exported" in msg and not (tmp_path / "b").exists()
    with pytest.raises(ValueError, match="layout"):
        ex.export_session(root, ["csv"], tmp_path / "c", layout="tall")
    files = ex.export_session(root, ["excel"], tmp_path / "d")      # a common name for xlsx
    assert files[0].suffix == ".xlsx"


def test_damaged_session_is_skipped_and_named(tmp_path):
    _run(tmp_path)
    bad = tmp_path / "data" / "broken"
    bad.mkdir()
    (bad / "session.json").write_text('{"broken": ')
    res = ex.export_many(tmp_path / "data", ["csv"], tmp_path / "out")
    assert res["sessions"] == 1 and len(res["skipped"]) == 1
    assert "broken" in res["notes"][0] and "session.json is damaged" in res["notes"][0]
    with pytest.raises(ValueError, match="session.json is damaged"):
        ex.SessionTables(bad)


def test_no_sessions_mentions_test_runs(tmp_path):
    root = _run(tmp_path)
    (tmp_path / "d" / "dry_runs").mkdir(parents=True)
    root.rename(tmp_path / "d" / "dry_runs" / root.name)
    with pytest.raises(FileNotFoundError, match="only 1 test run.*--include-dry-runs"):
        ex.export_many(tmp_path / "d", ["csv"])


def test_dictionary_explains_loop_row_numbers(tmp_path):
    (tmp_path / "c.csv").write_text("s,cong,ans\n<<<,congruent,f\n<><,incongruent,j\n")
    st = ex.SessionTables(_run(tmp_path, dict(TASK, flow=["intro", {"loop": "trials", "conditions": "c.csv",
                                                                     "children": ["trial"]}])))
    text = ex.describe_column("trials.row", st)
    assert "counted from 0" in text and "spreadsheet row = this + 2" in text and "''" not in text


# ------------------------------------------------------------------ data#23 / wizard#26: simulated survey page times
def test_simulated_page_times_add_up_to_the_survey_time(tmp_path):
    doc = {"name": "sv", "routines": {"q": {"components": [
        {"id": "q", "type": "survey", "end_routine": True, "questions": [
            {"id": "a", "type": "single", "text": "A?", "options": ["x", "y"]}, {"type": "page_break"},
            {"id": "b", "type": "text", "text": "B?"}, {"type": "page_break"},
            {"id": "c", "type": "single", "text": "C?", "options": ["x", "y"]}]}]}},
        "flow": ["q"]}
    _, session, _ = run_headless(doc, tmp_path, vp=VirtualParticipant(seed=5))
    row = next(r for r in session.data.trial_rows if r["routine"] == "q")
    pages = [row[f"q.page{i}_time"] for i in (1, 2, 3)]
    assert sum(pages) <= row["q.rt"] + 1e-6 and row["q.rt"] - sum(pages) < 0.1


# ------------------------------------------------------------------ wizard#6: suggested measures
def test_suggested_measures_are_scores_not_items_or_break_keys(tmp_path):
    from edge.measures import suggest_measures
    doc = {"name": "w", "routines": {
        "brk": {"components": [{"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
        "trial": {"components": [{"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$ans",
                                  "end_routine": True}]},
        "qs": {"components": [{"id": "questionnaires", "type": "survey", "end_routine": True,
                               "questions": [{"instrument": "tipi"}, {"instrument": "pss10"}]}]}},
        "flow": [{"loop": "blocks", "repeats": 2, "children": [
            {"loop": "trials", "conditions": [{"ans": "f"}, {"ans": "j"}], "children": ["trial"]}, "brk"]}, "qs"]}
    ids = [m["id"] for m in suggest_measures(Experiment.from_dict(doc, base_dir=tmp_path))]
    assert "go_rt" not in ids and "rt" in ids and "accuracy" in ids
    assert {"tipi_extraversion", "tipi_openness", "pss10_total"} <= set(ids)
    assert not [i for i in ids if i.startswith(("tipi_", "pss10_")) and i[-1].isdigit()]


def test_export_settings_are_checked(tmp_path, monkeypatch):
    def exports(value):
        doc = dict(TASK, settings={"data": {"exports": value}})
        return [i for i in issues_of(doc, tmp_path) if i.where == "settings.data.exports"]
    assert [i.level for i in exports(["csv", "sav"])] == ["error"]
    assert exports(["csv", "xlsx"]) == []
    monkeypatch.setattr(ex, "_have", lambda m: False)
    warn = exports(["csv", "parquet"])
    assert [i.level for i in warn] == ["warning"] and "pip install pyarrow" in warn[0].message


def test_auto_export_writes_the_tables_and_names_what_is_missing(tmp_path, monkeypatch):
    root = _run(tmp_path)
    for f in ("trials_wide.csv", "summary.csv"):
        (root / f).unlink()
    monkeypatch.setattr(ex, "_have", lambda m: False)
    with pytest.raises(ValueError, match="pyarrow"):
        ex.auto_export(root, {"data": {"exports": ["csv", "xlsx", "parquet"]}})
    assert (root / "trials_wide.csv").exists() and (root / "exports" / f"{root.name}.xlsx").exists()
