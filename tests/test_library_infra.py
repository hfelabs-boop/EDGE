"""The task library's infrastructure: loader and meta.yaml schema, copies, CLI, builder endpoints, MCP tools, primer,
packaging. Uses three small sample tasks in tests/fixtures/library_sample (the real tasks are tested by their own
test files)."""
import json
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from edge import library
from edge.cli import main
from edge.model import Experiment

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).parent / "fixtures" / "library_sample"


@pytest.fixture
def sample(monkeypatch):
    monkeypatch.setenv("EDGE_LIBRARY_DIR", str(SAMPLE))
    return SAMPLE


def _meta(folder: Path) -> dict:
    return yaml.safe_load((folder / "meta.yaml").read_text(encoding="utf-8"))


def _broken_copy(tmp_path, task="simple_rt", **changes) -> Path:
    root = tmp_path / "lib"
    shutil.copytree(SAMPLE / task, root / task)
    meta = _meta(root / task)
    for k, v in changes.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    (root / task / "meta.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    return root


# ---------------------------------------------------------------- loader
def test_discover_and_filter(sample):
    tasks, problems = library.discover()
    assert [t.id for t in tasks] == ["colour_choice", "colour_choice_touch", "simple_rt"] and problems == []
    t = library.get_task("colour-choice")                       # PsyToolkit's spelling works too
    assert t.experiment_path.is_file() and t.languages == ["en", "de"] and t.psytoolkit is None
    assert [x.id for x in library.list_tasks(category="decision")] == ["colour_choice", "colour_choice_touch"]
    assert [x.id for x in library.list_tasks(category="Attention")] == ["simple_rt"]
    assert [x.id for x in library.list_tasks(search="tap screen")] == ["colour_choice_touch"]
    assert [x.id for x in library.list_tasks(search="Hick 1952")] == ["colour_choice", "colour_choice_touch"]
    assert [x.id for x in library.list_tasks(input="touch")] == ["colour_choice_touch"]
    assert [x.id for x in library.list_tasks(language="de")] == ["colour_choice"]
    assert {c["name"]: c["count"] for c in library.categories()}["Decision making"] == 2
    assert len(library.categories()) == len(library.CATEGORIES)
    with pytest.raises(library.LibraryError, match="unknown category 'xyz'"):
        library.list_tasks(category="xyz")
    with pytest.raises(library.LibraryError, match="did you mean 'simple_rt'"):
        library.get_task("simple_tr")
    d = library.get_task("colour_choice_touch").to_dict()
    assert d["variant_of"] == "colour_choice" and d["psytoolkit"].startswith("https://www.psytoolkit.org/")
    assert "Hick, W. E. (1952)" in d["citation"] and "EDGE's own implementation" in d["citation"]


def test_every_sample_is_a_valid_experiment(sample):
    for t in library.list_tasks():
        assert library.validate_meta(_meta(t.folder), t.folder) == []
        issues = Experiment.load(t.experiment_path).validate()
        assert [i.message for i in issues if i.level == "error"] == [], t.id


def test_empty_or_missing_library(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_LIBRARY_DIR", str(tmp_path / "nothing"))
    assert library.discover() == ([], [])
    with pytest.raises(library.LibraryError, match="the library is empty"):
        library.get_task("stroop")


# ---------------------------------------------------------------- the schema
@pytest.mark.parametrize("changes, message", [
    ({"category": "Memory"}, "category 'Memory' is not one of"),
    ({"category": "Atention"}, "did you mean 'Attention'"),
    ({"input": "keys"}, "input 'keys' is not one of"),
    ({"duration_min": "five"}, "duration_min must be the number of minutes"),
    ({"duration_min": 0}, "duration_min must be"),
    ({"references": "Donders 1869"}, "'references' must be a list of texts"),
    ({"measures": []}, "'measures' must be a list of texts"),
    ({"languages": ["english"]}, "not a language code"),
    ({"see_also": {"psytoolkit": "www.psytoolkit.org"}}, "see_also.psytoolkit must be a web address"),
    ({"id": "other_name"}, "must be the name of its folder"),
    ({"id": "Simple-RT"}, "must be lower-case letters"),
    ({"summary": None}, "'summary' is missing"),
    ({"references": None, "refrences": ["x"]}, "'references' is missing ('refrences' is spelled differently)"),
    ({"variant_of": 3}, "'variant_of' must be text"),
])
def test_schema_errors_are_clear(tmp_path, monkeypatch, changes, message):
    root = _broken_copy(tmp_path, **changes)
    with pytest.raises(library.LibraryError) as e:
        library.load_task(root / "simple_rt")
    assert message in str(e.value) and str(e.value).startswith("simple_rt/meta.yaml: ")
    tasks, problems = library.discover(root)                  # a broken task is left out, with the reason
    assert tasks == [] and message in problems[0]
    with pytest.raises(library.LibraryError, match="can't be used"):
        library.get_task("simple_rt", root)


def test_schema_file_problems(tmp_path):
    root = tmp_path / "lib"
    (root / "a_task").mkdir(parents=True)
    (root / "a_task" / "meta.yaml").write_text("id: a_task\ntitle: [unclosed\n")
    tasks, problems = library.discover(root)
    assert not tasks and "meta.yaml could not be read (line" in problems[0]
    (root / "a_task" / "meta.yaml").write_text("- just\n- a list\n")
    assert "must be a set of 'key: value' lines" in library.discover(root)[1][0]
    # the experiment file must be there; a variant of a task that is not in the library is reported
    root2 = _broken_copy(tmp_path / "x", "colour_choice_touch")
    assert library.discover(root2)[1] == ["colour_choice_touch/meta.yaml: variant_of 'colour_choice' is not a task "
                                          "in the library"]
    (root2 / "colour_choice_touch" / "colour_choice_touch.yaml").unlink()
    assert "the experiment file colour_choice_touch.yaml is missing" in library.discover(root2)[1][0]
    # extra keys are kept, not refused (a later version of the schema)
    root3 = _broken_copy(tmp_path / "y", keywords=["rt"])
    assert library.get_task("simple_rt", root3).extra == {"keywords": ["rt"]}


# ---------------------------------------------------------------- copies
def test_copy_task_never_overwrites(sample, tmp_path):
    ws = tmp_path / "ws"
    (ws / "colour_choice").mkdir(parents=True)                   # someone's own folder of that name
    (ws / "colour_choice" / "mine.txt").write_text("keep me")
    # a test run left data in the library folder: it must not travel
    src = tmp_path / "lib"
    shutil.copytree(SAMPLE, src)
    (src / "colour_choice" / "data" / "dry_runs").mkdir(parents=True)
    (src / "colour_choice" / "data" / "dry_runs" / "x.csv").write_text("x")
    (src / "colour_choice" / "__pycache__").mkdir()
    (src / "colour_choice" / ".DS_Store").write_text("x")
    p = library.copy_task("colour_choice", ws, root=src)
    assert p == ws / "colour_choice_2" / "colour_choice_2.yaml"
    assert (ws / "colour_choice" / "mine.txt").read_text() == "keep me"
    files = sorted(f.relative_to(p.parent).as_posix() for f in p.parent.rglob("*") if f.is_file())
    assert files == ["CITATION.md", "colour_choice_2.yaml", "conditions.csv", "stimuli/blue.png", "stimuli/red.png"]
    text = p.read_text()
    assert text.startswith("# From the EDGE task library: Colour choice (sample) (colour_choice).")
    exp = Experiment.load(p)
    assert exp.name == "colour_choice_2" and [i for i in exp.validate() if i.level == "error"] == []
    cite = (p.parent / "CITATION.md").read_text()
    assert cite.startswith("# Colour choice (sample)") and "Hick, W. E. (1952)" in cite
    # named copies, and names that are not folder names
    q = library.copy_task("simple_rt", ws, "My pilot", root=src)
    assert q == ws / "My_pilot" / "My_pilot.yaml"
    with pytest.raises(library.LibraryError, match="give the new experiment a name"):
        library.copy_task("simple_rt", ws, "///", root=src)
    (tmp_path / "afile").write_text("x")
    with pytest.raises(library.LibraryError, match="is a file, not a folder"):
        library.copy_task("simple_rt", tmp_path / "afile", root=src)


def test_copy_runs(sample, tmp_path):
    from tests.conftest import run_headless
    from edge.participant import VirtualParticipant
    p = library.copy_task("colour_choice", tmp_path)
    exp = Experiment.load(p)
    summary, session, _ = run_headless(exp.source, p.parent, vp=VirtualParticipant(seed=1))
    rows = session.data.trial_rows
    assert sum(1 for r in rows if r.get("colour")) == 4 and {r["colour"] for r in rows if r.get("colour")} == {"red", "blue"}


# ---------------------------------------------------------------- CLI
def test_cli(sample, tmp_path, capsys):
    assert main(["library", "list"]) == 0
    out = capsys.readouterr().out
    assert "Decision making\n  colour_choice " in out and "3 task(s)" in out and "(about 1 min, keyboard)" in out
    assert main(["library"]) == 0 and "simple_rt" in capsys.readouterr().out
    assert main(["library", "list", "--category", "attention", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [t["id"] for t in data["tasks"]] == ["simple_rt"] and data["problems"] == []
    assert main(["library", "list", "--search", "nothing like this"]) == 0
    assert "No task matches." in capsys.readouterr().out
    assert main(["library", "show", "colour_choice_touch"]) == 0
    out = capsys.readouterr().out
    assert "a version of colour_choice" in out and "PsyToolkit: https://www.psytoolkit.org/" in out
    assert "References (please cite them)" in out and "edge library new colour_choice_touch" in out
    assert main(["library", "new", "simple_rt", str(tmp_path)]) == 0
    assert "created " in capsys.readouterr().out and (tmp_path / "simple_rt" / "simple_rt.yaml").is_file()
    assert main(["library", "new", "simple_rt", str(tmp_path), "--name", "rt2"]) == 0
    assert (tmp_path / "rt2" / "rt2.yaml").is_file()
    assert main(["library", "new", "simple_rt", str(tmp_path)]) == 0
    assert "already exists there, so it was left as it is" in capsys.readouterr().out
    assert (tmp_path / "simple_rt_2" / "simple_rt_2.yaml").is_file()
    assert main(["library", "new", "stroopp", str(tmp_path)]) == 2
    assert "there is no task 'stroopp' in the library" in capsys.readouterr().err
    assert main(["library", "list", "--category", "nope"]) == 2
    assert "unknown category 'nope'" in capsys.readouterr().err


def test_cli_warns_about_broken_tasks(tmp_path, monkeypatch, capsys):
    root = _broken_copy(tmp_path, input="voice")
    monkeypatch.setenv("EDGE_LIBRARY_DIR", str(root))
    assert main(["library", "list"]) == 0
    captured = capsys.readouterr()
    assert "The task library is empty." in captured.out
    assert "warning: left out of the library: simple_rt/meta.yaml: input 'voice'" in captured.err


# ---------------------------------------------------------------- builder endpoints
@pytest.fixture
def server(tmp_path, sample):
    from edge.builder.server import BuilderApp, make_handler
    root = tmp_path / "ws"
    root.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def _req(url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoints(server):
    base, root = server
    code, r = _req(base + "/api/library")
    assert code == 200 and [t["id"] for t in r["tasks"]] == ["colour_choice", "colour_choice_touch", "simple_rt"]
    t = r["tasks"][0]
    for k in ("title", "summary", "description", "measures", "duration_min", "input", "references", "citation",
              "psytoolkit", "languages"):
        assert k in t
    assert {c["name"] for c in r["categories"]} == set(library.CATEGORIES) and r["problems"] == []
    assert [t["id"] for t in _req(base + "/api/library?category=attention")[1]["tasks"]] == ["simple_rt"]
    assert [t["id"] for t in _req(base + "/api/library?search=tap")[1]["tasks"]] == ["colour_choice_touch"]
    code, r = _req(base + "/api/library/new", {"id": "colour_choice", "name": "pilot"})
    assert code == 200 and r["path"] == "pilot/pilot.yaml" and "Hick" in r["citation"]
    assert (root / "pilot" / "stimuli" / "red.png").is_file()
    assert _req(base + "/api/library/new", {"id": "colour_choice", "name": "pilot"})[1]["path"] == "pilot_2/pilot_2.yaml"
    assert _req(base + "/api/library/new", {"id": "simple_rt"})[1]["path"] == "simple_rt/simple_rt.yaml"
    # the copy opens like any experiment of the folder
    assert _req(base + "/api/experiment?path=pilot/pilot.yaml")[0] == 200
    # bad requests say why, and nothing is written outside the folder
    code, r = _req(base + "/api/library/new", {"id": "nope"})
    assert code == 400 and "there is no task 'nope'" in r["error"]
    for name in ("../outside", "a/b", ".."):
        code, r = _req(base + "/api/library/new", {"id": "simple_rt", "name": name})
        assert code == 400 and "must be the name of a new folder" in r["error"]
    assert not (root.parent / "outside").exists()
    assert _req(base + "/api/library/new", {"name": "x"})[0] == 400
    assert _req(base + "/api/library?category=zzz")[0] == 400
    assert _req(base + "/api/library/nothing")[0] == 404


def test_endpoints_are_behind_the_guard(server):
    base, root = server
    code, r = _req(base + "/api/library", headers={"Host": "evil.example"})
    assert code == 403
    code, r = _req(base + "/api/library/new", {"id": "simple_rt"}, headers={"Origin": "http://evil.example"})
    assert code == 403 and not (root / "simple_rt").exists()
    code, r = _req(base + "/api/library/new", {"id": "simple_rt"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert code == 403 and not (root / "simple_rt").exists()
    req = urllib.request.Request(base + "/api/library/new", data=b'{"id": "simple_rt"}', method="POST",
                                 headers={"Content-Type": "text/plain"})       # a form post from another page
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 415 and not (root / "simple_rt").exists()


def test_builder_ui_has_the_library():
    static = ROOT / "edge" / "builder" / "static"
    app = (static / "app.js").read_text()
    lib = (static / "library.js").read_text()
    assert 'card("home-library", "book", "neutral", "Task library"' in app and 'chip("home-library"' in app
    assert "openTaskLibrary()" in app.split("async function examplesGallery")[1].split("async function createFromTemplate")[0]
    for words in ("Use this task", "Use and try it", "See also PsyToolkit", "/api/library/new", "/api/library"):
        assert words in lib
    assert '<script src="/static/library.js"></script>' in (static / "index.html").read_text()


# ---------------------------------------------------------------- MCP and the assistant
def test_mcp_tools(sample, tmp_path):
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    from tests.test_mcp import call
    srv = create_server(tmp_path)
    r = call(srv, "list_library", category="decision", input="touch")
    assert [t["id"] for t in r["tasks"]] == ["colour_choice_touch"] and r["tasks"][0]["references"]
    assert {c["name"] for c in call(srv, "list_library")["categories"]} == {"Attention", "Decision making"}
    r = call(srv, "create_from_library", task="colour_choice", directory="studies", name="cc")
    assert r["ok"] and r["path"] == "studies/cc/cc.yaml" and r["errors"] == [] and "Hick" in r["citation"]
    assert (tmp_path / "studies" / "cc" / "stimuli" / "blue.png").is_file()
    r = call(srv, "create_from_library", task="nope")
    assert r["ok"] is False and "no task 'nope'" in r["error"]
    r = call(srv, "create_from_library", task="simple_rt", directory="../outside")
    assert r["ok"] is False and "outside the workspace" in r["error"]


def test_primer_mentions_the_library_and_stays_small():
    from edge.assistant.primer import build_primer
    for level in ("full", "compact"):
        assert "Task library" in build_primer(level)
    assert len(build_primer("compact", tool_mode="json")) <= 20000


# ---------------------------------------------------------------- packaging
def test_package_data_names_the_library():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"edge.library" = ["tasks/**/*"]' in text
    assert "recursive-include edge/library/tasks *" in (ROOT / "MANIFEST.in").read_text()
    assert "library/tasks/**/*" in (ROOT / "install" / "edge.spec").read_text()


def test_wheel_ships_the_task_folders(tmp_path):
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
    src = tmp_path / "src"
    src.mkdir()
    for name in ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "LICENSE"):
        if (ROOT / name).exists():
            shutil.copy(ROOT / name, src / name)
    shutil.copytree(ROOT / "edge", src / "edge", ignore=shutil.ignore_patterns("__pycache__", "docs", "tasks"))
    shutil.copytree(ROOT / "docs", src / "docs")
    tasks = src / "edge" / "library" / "tasks"
    shutil.copytree(SAMPLE / "colour_choice", tasks / "colour_choice")       # a task with stimuli and a trial list
    (tasks / "colour_choice" / "data" / "dry_runs").mkdir(parents=True)     # what a test run leaves behind
    (tasks / "colour_choice" / "data" / "dry_runs" / "s.csv").write_text("x")
    for isolation in (["--no-build-isolation"], []):
        r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", *isolation, "-q",
                            "-w", str(tmp_path / "dist"), str(src)], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            break
    else:
        pytest.skip("could not build a wheel here: " + r.stderr[-300:])
    names = zipfile.ZipFile(next((tmp_path / "dist").glob("*.whl"))).namelist()
    base = "edge/library/tasks/colour_choice/"
    for f in ("meta.yaml", "colour_choice.yaml", "conditions.csv", "stimuli/red.png", "stimuli/blue.png"):
        assert base + f in names
    assert "edge/library/__init__.py" in names and "edge/library/cli.py" in names
    assert not [n for n in names if "/data/" in n and n.startswith("edge/library/")]
