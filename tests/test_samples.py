"""Every sample experiment (examples/ and the templates) through the whole researcher lifecycle.

validate -> dry run (several participants) -> report -> export (every common format, one session and
the whole folder) -> lock -> verify -> bundle -> unbundle elsewhere -> dry run again -> support bundle.
A sample that stops working anywhere along the way fails here, with the step named.
"""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from edge.cli import main
from edge.templates import public_templates, write_template

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted(p.relative_to(ROOT / "examples") for p in (ROOT / "examples").glob("*/*.yaml"))


def _samples() -> list[str]:
    return [f"example:{p}" for p in EXAMPLES] + [f"template:{t}" for t in public_templates()]


def _materialise(sample: str, tmp: Path) -> Path:
    kind, name = sample.split(":", 1)
    if kind == "example":
        src = ROOT / "examples" / Path(name).parent
        shutil.copytree(src, tmp / src.name, ignore=shutil.ignore_patterns("data", "exports", "*.edgez", "*.lock*"))
        return tmp / src.name / Path(name).name
    return write_template(name, tmp / name)


def _sessions(exp: Path) -> list[Path]:
    return sorted(p.parent for p in (exp.parent / "data").rglob("session.json"))


@pytest.mark.parametrize("sample", _samples())
def test_sample_lifecycle(sample, tmp_path, capsys):
    exp = _materialise(sample, tmp_path)

    assert main(["validate", str(exp)]) == 0, "validate"

    for pid in ("1", "2"):
        assert main(["run", str(exp), "--dry-run", "-p", pid]) == 0, f"dry run, participant {pid}"
    sessions = _sessions(exp)
    assert len(sessions) == 2, "each run makes one session folder"
    for s in sessions:
        info = json.loads((s / "session.json").read_text(encoding="utf-8"))
        assert not info.get("errors"), f"session errors: {info.get('errors')}"
        assert (s / "trials.jsonl").exists() and (s / "events.jsonl").exists()

    assert main(["report", str(sessions[0])]) == 0, "report"
    capsys.readouterr()
    assert main(["report", str(sessions[0]), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep.get("verdict"), "the report gives a verdict"

    out = tmp_path / "exports"
    assert main(["export", str(exp.parent / "data"), "--formats", "csv,xlsx,json", "--out", str(out),
                 "--include-dry-runs"]) == 0, "export the whole data folder"
    csvs = sorted(out.rglob("*.csv"))
    assert csvs, "export wrote csv files"
    rows = list(csv.DictReader(csvs[0].open(encoding="utf-8")))
    assert rows, "the merged table has rows"
    assert any(out.rglob("*.xlsx")), "export wrote xlsx"
    assert main(["export", str(sessions[0]), "--formats", "csv", "--layout", "long", "--out", str(tmp_path / "one")]) == 0

    assert main(["lock", str(exp)]) == 0, "lock"
    assert main(["verify", str(exp)]) == 0, "verify right after the lock"

    bundle = tmp_path / "pack.edgez"
    assert main(["bundle", str(exp), "--out", str(bundle)]) == 0, "bundle"
    other = tmp_path / "elsewhere"
    assert main(["unbundle", str(bundle), str(other)]) == 0, "unbundle"
    moved = [p for p in other.rglob(exp.name)]
    assert moved, "the bundle contains the experiment"
    assert main(["validate", str(moved[0])]) == 0, "the unbundled copy validates"
    assert main(["run", str(moved[0]), "--dry-run"]) == 0, "the unbundled copy runs"

    zip_out = tmp_path / "support.zip"
    assert main(["support-bundle", str(exp), "--out", str(zip_out)]) == 0, "support bundle"
    with zipfile.ZipFile(zip_out) as z:
        names = z.namelist()
        assert "experiment.yaml" in names, "the support bundle has the experiment"
        for n in names:
            if n.endswith("session.json"):
                info = json.loads(z.read(n))
                assert set((info.get("participant") or {}).values()) <= {"<removed>"}, "participant info removed"


def test_cli_explains_wrong_files(tmp_path, capsys):
    tut = ROOT / "edge" / "tutorials" / "01_first_experiment.yaml"
    assert main(["validate", str(tut)]) == 2
    assert "is a tutorial" in capsys.readouterr().err
    assert main(["run", str(tmp_path), "--dry-run"]) == 2
    assert "is a folder" in capsys.readouterr().err
    assert main(["validate", str(tmp_path / "nope.yaml")]) == 2
    assert "file not found" in capsys.readouterr().err
    (tmp_path / "list.yaml").write_text("- a\n- b\n")
    assert main(["validate", str(tmp_path / "list.yaml")]) == 2
    assert "must be a mapping" in capsys.readouterr().err
    (tmp_path / "bin.yaml").write_bytes(b"\xff\xfe\x00\x81")
    assert main(["validate", str(tmp_path / "bin.yaml")]) == 2
    assert main(["new", "oddbal", str(tmp_path)]) == 2
    assert "did you mean eeg_oddball" in capsys.readouterr().err
