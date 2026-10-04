import json
import shutil
import threading
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge.builder.server import BuilderApp, make_handler
from edge.cli import main
from edge.templates import TEMPLATES, write_template


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_templates_validate_and_dry_run(name, tmp_path, capsys):
    path = write_template(name, tmp_path)
    assert main(["validate", str(path)]) == 0
    assert main(["run", str(path), "--dry-run", "--data-dir", str(tmp_path / "data")]) == 0
    out = capsys.readouterr().out
    assert "Saved to" in out


def test_example_stroop_dry_run_with_report(tmp_path, capsys):
    src = Path("examples/stroop")
    shutil.copytree(src, tmp_path / "stroop", ignore=shutil.ignore_patterns("data"))
    rc = main(["run", str(tmp_path / "stroop/stroop.yaml"), "--dry-run", "--report", "-p", "042"])
    out = capsys.readouterr().out
    assert rc == 0 and "Verdict" in out and "OK" in out
    assert list((tmp_path / "stroop/data").glob("042_1_stroop_*"))


def test_cli_lists(capsys):
    assert main(["devices"]) == 0
    assert "gazepoint" in capsys.readouterr().out
    assert main(["components", "--json"]) == 0
    assert "gaze_roi" in json.loads(capsys.readouterr().out)


@pytest.fixture
def server(tmp_path):
    shutil.copytree("examples/stroop", tmp_path / "stroop", ignore=shutil.ignore_patterns("data"))
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_builder_api(server):
    with urllib.request.urlopen(server + "/") as r:
        assert b"EDGE" in r.read()
    schema = _get(server + "/api/schema")
    assert "text" in schema["components"] and "tobii" in schema["devices"]
    files = _get(server + "/api/files")["files"]
    assert files == [{"path": "stroop/stroop.yaml", "name": "stroop"}]
    loaded = _get(server + "/api/experiment?path=stroop/stroop.yaml")
    exp, fp = loaded["experiment"], loaded["fingerprint"]
    assert _post(server + "/api/validate", {"experiment": exp, "path": "stroop/stroop.yaml"})["issues"] == []
    rows = _get(server + "/api/conditions?spec=%22stroop.csv%22&exp=stroop/stroop.yaml")["rows"]
    assert rows[0]["word"] == "RED"
    res = _post(server + "/api/dryrun", {"experiment": exp, "path": "stroop/stroop.yaml"})
    assert res["ok"] and res["trials"] and res["report"]["verdict"]
    exp["name"] = "stroop2"
    _post(server + "/api/experiment?path=stroop/copy.yaml", exp)
    assert _get(server + "/api/experiment?path=stroop/copy.yaml")["experiment"]["name"] == "stroop2"
    # saving with the fingerprint from load works; a stale fingerprint is a 409 conflict
    saved = _post(server + f"/api/experiment?path=stroop/stroop.yaml&fingerprint={fp}", exp)
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(server + f"/api/experiment?path=stroop/stroop.yaml&fingerprint={fp}", exp | {"name": "x"})
    assert e.value.code == 409
    assert _get(server + "/api/fingerprint?path=stroop/stroop.yaml")["fingerprint"] == saved["fingerprint"]
    assert _get(server + "/api/backups?path=stroop/stroop.yaml")["backups"]
    # data endpoints
    sessions = _get(server + "/api/sessions?dry_runs=1")["sessions"]
    assert sessions and sessions[0]["experiment"] == "stroop"
    tables = _get(server + "/api/session_tables?path=" + urllib.parse.quote(sessions[0]["path"]))
    assert tables["trials"]["total"] > 10 and tables["summary"]["rows"][0]["factor"] == "(all)"
    files = _post(server + "/api/export", {"path": sessions[0]["path"], "formats": ["xlsx"]})["files"]
    assert files[0].endswith(".xlsx")
    with urllib.request.urlopen(server + "/api/bundle?path=stroop/stroop.yaml") as r:
        assert r.read(2) == b"PK"


def test_builder_refuses_paths_outside_root(server):
    with pytest.raises(urllib.error.HTTPError):
        _get(server + "/api/experiment?path=../../etc/passwd")


def test_builder_upload_and_import(server):
    from pathlib import Path
    fx = Path(__file__).parent / "fixtures" / "opensesame" / "flanker.opensesame"
    req = urllib.request.Request(server + "/api/upload?path=imports/flanker/source/flanker.opensesame",
                                 data=fx.read_bytes(), method="POST")
    urllib.request.urlopen(req).read()
    r = _post(server + "/api/import", {"source": "imports/flanker/source/flanker.opensesame", "out": "imports/flanker"})
    assert r["path"] == "imports/flanker/Flanker_task.yaml" and r["platform"] == "OpenSesame"
    assert "# Import report" in r["report"]
    assert _get(server + "/api/experiment?path=" + r["path"])["experiment"]["name"] == "Flanker_task"
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(urllib.request.Request(server + "/api/upload?path=../evil.txt", data=b"x", method="POST"))
