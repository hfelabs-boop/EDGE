import csv
import json
import zipfile

import pytest

from edge.export import (SessionTables, data_dictionary, export_many, export_session, summarize, wide_trials,
                         write_xlsx)
from edge.participant import VirtualParticipant
from tests.conftest import run_headless

EXP = {"name": "flank", "variables": {"score": 0},
       "settings": {"data": {"exports": ["csv", "xlsx", "json"]}},
       "devices": [{"id": "eeg", "type": "sim_eeg"}],
       "routines": {
           "intro": {"components": [{"id": "go", "type": "keyboard", "keys": ["space"], "end_routine": True}]},
           "trial": {"components": [
               {"id": "stim", "type": "text", "text": "$s", "marker": "$cong"},
               {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$ans", "duration": 2,
                "end_routine": True},
               {"id": "v", "type": "variable", "when": "end", "set": {"score": "$score + (resp.corr or 0)"}}]},
           "fb": {"duration": 0.3, "components": [{"id": "stim", "type": "text", "text": "ok"}]}},
       "flow": ["intro", {"loop": "trials", "repeats": 5, "order": "random",
                          "conditions": [{"s": "<<<", "cong": "congruent", "ans": "f"},
                                         {"s": "<><", "cong": "incongruent", "ans": "f"}],
                          "children": ["trial", "fb"]}]}


@pytest.fixture
def session(tmp_path):
    summary, sess, _ = run_headless(EXP, tmp_path, vp=VirtualParticipant(seed=4))
    return sess.data.root


def test_auto_export_files(session):
    for f in ("trials_wide.csv", "summary.csv", "data_dictionary.csv", "README.txt"):
        assert (session / f).exists(), f
    assert (session / "exports" / f"{session.name}.xlsx").exists()
    meta = json.loads((session / "session.json").read_text())
    assert meta["errors"] == []


def test_wide_table_one_row_per_trial(session):
    st = SessionTables(session)
    cols, rows = wide_trials(st)
    trials = [r for r in rows if r["loop"] == "trials"]
    assert len(trials) == 10 and len(rows) == 11          # 10 trials + the intro routine
    assert all(r["routines"] == "trial+fb" for r in trials)
    # the clashing 'stim' component of fb is disambiguated with the routine name
    assert "stim.onset" in cols and "fb.stim.onset" in cols
    # column order: ids, design, conditions, responses, timing, variables
    order = [cols.index(c) for c in ("participant", "trials.n", "s", "resp.keys", "resp.rt", "trial.start", "score")]
    assert order == sorted(order)
    assert "routine_index" not in cols and "trial_key" not in cols
    # empty columns are dropped (fb has no response)
    assert not any(c.endswith(".corr") and all(r.get(c) in (None, "") for r in rows) for c in cols)
    assert isinstance(trials[0]["resp.rt"], float) and len(str(trials[0]["resp.rt"]).split(".")[1]) <= 6


def test_summary_detects_measures_and_factors(session):
    st = SessionTables(session)
    cols, rows, info = summarize(st)
    assert info["rt_column"] == "resp.rt" and info["correct_column"] == "resp.corr"
    assert info["factors"] == ["s", "cong"]                # 'ans' is recognised as an answer key, not a factor
    overall = rows[0]
    assert overall["factor"] == "(all)" and overall["n_trials"] == 10
    by_cong = {r["level"]: r for r in rows if r["factor"] == "cong"}
    assert set(by_cong) == {"congruent", "incongruent"} and by_cong["congruent"]["n_trials"] == 5
    assert 0 <= overall["accuracy"] <= 1 and overall["rt_mean"] > 0.1


def test_summary_overrides(session):
    st = SessionTables(session)
    _, rows, info = summarize(st, by=["cong"], rt="resp.rt", correct="resp.corr", outlier_sd=0)
    assert {r["factor"] for r in rows} == {"(all)", "cong"}


def test_dictionary_describes_everything(session):
    st = SessionTables(session)
    cols, rows = wide_trials(st)
    dd = {e["column"]: e for e in data_dictionary(st, cols, rows)}
    assert set(dd) == set(cols)
    assert dd["resp.rt"]["units"] == "s" and "Response time" in dd["resp.rt"]["description"]
    assert set(dd["resp.corr"]["levels"]) <= {0, 1}
    assert dd["cong"]["group"] == "condition" and dd["cong"]["levels"] == ["congruent", "incongruent"]
    assert dd["score"]["group"] == "variable"
    assert all(e["description"] for e in dd.values())


def test_xlsx_is_valid(session, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    files = export_session(session, ["xlsx"], tmp_path / "x")
    wb = openpyxl.load_workbook(files[0])
    assert wb.sheetnames == ["trials", "summary", "dictionary", "events", "session"]
    ws = wb["trials"]
    header = [c.value for c in ws[1]]
    assert "resp.rt" in header and ws.freeze_panes == "A2"
    rt_col = header.index("resp.rt")
    values = [r[rt_col].value for r in ws.iter_rows(min_row=2) if r[rt_col].value is not None]
    assert values and all(isinstance(v, float) for v in values)   # numbers stay numbers


def test_xlsx_escaping(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    f = write_xlsx(tmp_path / "t.xlsx", {"a/b:c": (["x", "y"], [{"x": "<&>\"'\x01", "y": True}, {"x": None, "y": 2.5}])})
    ws = openpyxl.load_workbook(f).active
    assert ws.title == "a_b_c" and ws["A2"].value == "<&>\"'" and ws["B2"].value is True and ws["B3"].value == 2.5


def test_csv_json_and_bids(session, tmp_path):
    files = export_session(session, ["csv", "tsv", "json", "jsonl", "bids"], tmp_path / "o")
    names = {f.name for f in files}
    assert f"{session.name}_trials.csv" in names and f"{session.name}_summary.tsv" in names
    beh = next(f for f in files if f.name.endswith("_beh.tsv"))
    assert "sub-001" in str(beh) and "ses-1" in str(beh)
    events = next(f for f in files if f.name.endswith("_events.tsv"))
    rows = list(csv.DictReader(events.open(encoding="utf-8-sig"), delimiter="\t"))
    assert rows[0]["trial_type"] == "session_start" and float(rows[0]["onset"]) == 0.0
    assert any(f.name.endswith("_physio.tsv.gz") for f in files)
    sidecar = json.loads(next(f for f in files if f.name.endswith("_physio.json")).read_text())
    assert sidecar["SamplingFrequency"] == 250.0 and sidecar["Columns"][0] == "time"
    assert (tmp_path / "o" / "bids" / "dataset_description.json").exists()


def test_long_layout(session, tmp_path):
    files = export_session(session, ["csv"], tmp_path / "l", layout="long")
    rows = list(csv.DictReader(files[0].open(encoding="utf-8-sig")))
    assert len(rows) == 21 and {r["routine"] for r in rows} == {"intro", "trial", "fb"}


def test_merge_many_participants(tmp_path):
    for pid in ("001", "002", "003"):
        d = dict(EXP, settings={"participant": {"participant": pid}})
        run_headless(d, tmp_path, vp=VirtualParticipant(seed=int(pid)))
    res = export_many(tmp_path / "data", ["csv", "xlsx"], tmp_path / "merged", name="all")
    assert res["sessions"] == 3 and res["participants"] == 3 and res["trials"] == 33
    trials = list(csv.DictReader((tmp_path / "merged" / "all_trials.csv").open(encoding="utf-8-sig")))
    assert {r["participant"] for r in trials} == {"001", "002", "003"}
    assert list(trials[0])[:3] == ["experiment", "session_folder", "participant"]
    summary = list(csv.DictReader((tmp_path / "merged" / "all_summary.csv").open(encoding="utf-8-sig")))
    assert sum(r["factor"] == "(all)" for r in summary) == 3
    with zipfile.ZipFile(tmp_path / "merged" / "all.xlsx") as z:
        assert "xl/worksheets/sheet4.xml" in z.namelist()   # trials, summary, dictionary, sessions


def test_export_survives_crashed_session(session):
    # simulate a crash mid-write: truncated last line of trials.jsonl
    p = session / "trials.jsonl"
    p.write_text(p.read_text() + '{"routine": "tri')
    cols, rows = wide_trials(SessionTables(session))
    assert len(rows) == 11
