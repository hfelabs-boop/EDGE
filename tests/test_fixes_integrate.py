"""Regression tests for problems found while integrating the audit fixes of all groups."""
import json
from pathlib import Path

from edge.report import analyze_session


def _gaze_session(tmp_path: Path, events: list[dict], codes: dict[int, int]) -> Path:
    """A session folder with a 120 Hz gaze stream whose trigger column carries ``codes`` (sample index -> code)."""
    root = tmp_path / "001_1_x_2026-01-01_000000"
    (root / "streams").mkdir(parents=True)
    (root / "session.json").write_text(json.dumps({
        "experiment": "x", "devices": {"et": {"streams": {"gaze": {"srate": 120.0}}}}}), encoding="utf-8")
    (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    period = 1 / 120
    lines = ["time,x,y,user"] + [f"{10 + i * period:.6f},0,0,{codes.get(i, 0)}" for i in range(240)]
    (root / "streams" / "et.gaze.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_two_markers_at_once_on_a_trigger_channel_are_not_a_wiring_problem(tmp_path):
    # a picture's onset (flip-locked) and a gaze event in the same frame: a trigger channel carries one code per
    # sample, so the second code lands one sample later. The freeview template's test runs reported this as
    # "marker alignment error ... check the device's trigger wiring" in about half of the runs.
    t = 10 + 60 / 120 + 0.0005
    events = [{"label": "view", "time": t, "code": 6, "on_flip": True, "delivered": {"et": t}},
              {"label": "aoi_right.enter", "time": t, "code": 3, "on_flip": False, "delivered": {"et": t}}]
    rep = analyze_session(_gaze_session(tmp_path, events, {61: 6, 62: 3}))
    tr = rep["streams"]["et.gaze"]["triggers"]
    assert tr["matched"] == 2 and tr["latency_max_abs_ms"] < 10
    assert rep["verdict"][0].startswith("OK"), rep["verdict"]


def test_a_marker_that_really_arrives_late_is_still_reported(tmp_path):
    t = 10 + 60 / 120 + 0.0005
    events = [{"label": "view", "time": t, "code": 6, "on_flip": True, "delivered": {"et": t}}]
    rep = analyze_session(_gaze_session(tmp_path, events, {63: 6}))     # three samples (25 ms) late, alone
    assert rep["verdict"][0].startswith("WARNING") and "view" in rep["verdict"][0], rep["verdict"]


# ---------------------------------------------------------------- one meaning of "trials" everywhere (cli#18)
EXP = {"name": "flank",
       "routines": {"intro": {"duration": 0.2, "components": []},
                    "trial": {"components": [{"id": "resp", "type": "keyboard", "keys": ["f", "j"],
                                              "correct": "$ans", "end_routine": True}]}},
       "flow": ["intro", {"loop": "trials", "conditions": [{"ans": "f"}, {"ans": "j"}], "repeats": 2,
                          "children": ["trial"]}]}


def _session(tmp_path, pid, seed):
    from conftest import run_headless
    from edge.participant import VirtualParticipant
    d = dict(EXP, settings={"participant": {"participant": pid}})
    summary, _, _ = run_headless(d, tmp_path, vp=VirtualParticipant(seed=seed))
    return Path(summary["data_dir"])


def test_export_counts_trials_as_the_report_does(tmp_path, capsys):
    from edge.cli import main
    from edge.export import export_many
    a, b = _session(tmp_path, "001", 1), _session(tmp_path, "002", 2)
    per_session = [analyze_session(s)["trials"] for s in (a, b)]
    assert per_session == [4, 4]
    wide = export_many(tmp_path / "data", ["csv"], tmp_path / "w", include_dry_runs=True)
    long = export_many(tmp_path / "data", ["csv"], tmp_path / "l", include_dry_runs=True, layout="long")
    assert wide["trials"] == long["trials"] == 8                 # loop iterations, not table rows
    assert wide["rows"] == 10 and long["rows"] == 10             # each session also has its intro row
    assert main(["export", str(tmp_path / "data"), "--include-dry-runs", "--formats", "csv",
                 "--out", str(tmp_path / "c")]) == 0
    assert "8 trials (10 rows in the trials table" in capsys.readouterr().out


def test_test_runs_saved_with_the_participants_are_pointed_out(tmp_path, capsys):
    from edge.cli import _check_participant
    from edge.export import export_many, find_sessions
    from edge.model import Experiment
    _session(tmp_path, "001", 1)                    # a virtual participant in data/ (as earlier EDGE versions did)
    res = export_many(tmp_path / "data", ["csv"], tmp_path / "o")
    assert any("test runs with a virtual participant" in n and "dry_runs" in n for n in res["notes"])
    # ... and they don't count as a participant who already has data
    exp = Experiment.from_dict(EXP, base_dir=tmp_path)
    assert _check_participant(exp, {"participant": "001", "session": "1"}, str(tmp_path / "data"))
    assert "already has data" not in capsys.readouterr().out
    # a folder called dry_runs *above* the data folder doesn't hide every session
    nested = tmp_path / "dry_runs" / "study"
    _session(nested, "003", 3)
    assert len(find_sessions(nested / "data")) == 1


# ---------------------------------------------------------------- imported experiments validate cleanly
def test_a_code_only_screen_may_last_0_s_but_a_shown_one_gets_a_warning(tmp_path):
    from edge.model import Experiment
    doc = {"routines": {"setup": {"duration": 0, "components": [{"id": "c", "type": "code", "on_begin": "x = 1"}]},
                        "flash": {"duration": 0, "components": [{"id": "t", "type": "text", "text": "hi"}]}},
           "flow": ["setup", "flash"]}
    warned = [i.where for i in Experiment.from_dict(doc, base_dir=tmp_path).validate() if i.level == "warning"]
    assert warned == ["routines.flash.duration"]


def test_every_importer_fixture_imports_validates_and_runs(tmp_path):
    # the PsychoPy import's 'Begin Experiment' code screen (duration 0) gave a warning, and the jsPsych
    # sample's pictures were 3-byte placeholders, so its import "won't run until fixed"
    import shutil
    from edge.engine import run_experiment
    from edge.importers import import_experiment
    from edge.model import Experiment
    fix = Path(__file__).resolve().parent / "fixtures"
    for rel in ("psychopy/stroop.psyexp", "eprime/Stroop.ebs3", "opensesame/flanker.opensesame",
                "jspsych/experiment.html"):
        src = tmp_path / rel.split("/")[0]
        shutil.copytree(fix / rel.split("/")[0], src)
        path, _ = import_experiment(src / rel.split("/")[1], src / "out")
        exp = Experiment.load(path)
        bad = [str(i) for i in exp.validate() if i.level in ("error", "warning")]
        assert bad == [], (rel, bad)
        s = run_experiment(exp, dry_run=True, log=lambda *a: None)
        assert not s["errors"], (rel, s["errors"])


def test_output_piped_into_a_program_that_stops_reading_is_not_an_error():
    # `edge help EXPERIMENT_FORMAT | head` printed "edge help: Broken pipe"
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-m", "edge", "help", "EXPERIMENT_FORMAT"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, cwd=str(Path(__file__).resolve().parent.parent))
    p.stdout.close()                    # stops reading before EDGE has printed anything
    err = p.stderr.read().decode()
    assert p.wait(timeout=60) == 0 and "Broken pipe" not in err and "Traceback" not in err, err


def test_another_packages_docs_folder_in_site_packages_does_not_replace_edges_guides(tmp_path, monkeypatch):
    import edge.help as hp
    site = tmp_path / "site-packages"
    (site / "docs").mkdir(parents=True)
    (site / "docs" / "README.md").write_text("# some other package\n")          # a stray top-level docs/
    (site / "edge" / "docs").mkdir(parents=True)
    (site / "edge" / "docs" / "EXPERIMENT_FORMAT.md").write_text("# Experiment format reference\n")
    monkeypatch.setattr(hp, "PACKAGE_DIR", site / "edge")
    assert hp.docs_dir() == site / "edge" / "docs"


def test_timing_test_says_when_it_left_an_existing_file_alone(tmp_path, capsys):
    from edge.cli import main
    assert main(["timing-test", str(tmp_path)]) == 0
    (tmp_path / "timing_test.yaml").write_text((tmp_path / "timing_test.yaml").read_text() + "# mine\n")
    capsys.readouterr()
    assert main(["timing-test", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "timing_test.yaml already exists there, so it was left as it is" in out and "timing_test_2.yaml" in out
    assert (tmp_path / "timing_test.yaml").read_text().endswith("# mine\n")
