"""Malformed documents and bad input must give clear, located errors, never tracebacks.

A small mutation fuzzer: every field of a known-good experiment is replaced in turn by values of
the wrong shape (text, lists, mappings, booleans, None, numbers, huge values), and the loader,
the checker, the recording plan and a dry run are asked to cope. The only acceptable outcomes
are success, a ``DocumentError`` / ``ValueError`` naming where the problem is, validation issues,
or an ``ExperimentError`` that carries its structured report.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from edge.diagnostics import ExperimentError
from edge.engine import run_experiment
from edge.measures import recording_plan
from edge.model import Experiment, Issue, window_size
from edge.storage import DocumentError

BASE: dict[str, Any] = {
    "name": "fuzz",
    "settings": {"window": {"size": [640, 480], "units": "px"}, "data": {"dir": "data"}},
    "variables": {"score": 0},
    "devices": [{"id": "box", "type": "sim_inputs", "options": {"inputs": {1: "left", 2: "right"}}}],
    "routines": {
        "fix": {"components": [{"id": "cross", "type": "text", "text": "+", "duration": 0.1}]},
        "trial": {
            "components": [
                {"id": "word", "type": "text", "text": "$word", "duration": 1.0},
                {"id": "resp", "type": "keyboard", "keys": ["f", "j"], "correct": "$ans", "end_routine": True},
            ],
            "rules": [{"when": "$resp.corr == 1", "do": [{"set": {"score": "$score + 1"}}]}],
        },
        "end": {"components": [{"id": "bye", "type": "text", "text": "done", "duration": 0.1}]},
    },
    "flow": [
        "fix",
        {"loop": "trials", "conditions": [{"word": "red", "ans": "f"}, {"word": "blue", "ans": "j"}],
         "children": ["fix", "trial"], "repeats": 1},
        {"if": "$score > 0", "then": ["end"], "else": ["fix"]},
        {"statemachine": "sm", "start": "a",
         "states": {"a": {"run": ["fix"], "next": [{"goto": "end", "if": "$score >= 0"}]}}},
    ],
    "measures": [{"id": "rt", "column": "resp.rt"}, {"id": "acc", "column": "resp.corr", "role": "check"}],
}

BAD_VALUES: list[Any] = ["text", ["a", "list"], {"a": "mapping"}, True, None, 7, -1.5, [], {},
                         [[1, 2]], "x" * 5000, {"components": "nope"}, [None], [["fix"]], 10 ** 9]


def _paths(d: Any, prefix: tuple = ()) -> list[tuple]:
    out = [prefix] if prefix else []
    if isinstance(d, dict):
        for k, v in d.items():
            out += _paths(v, prefix + (k,))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out += _paths(v, prefix + (i,))
    return out


def _set(d: Any, path: tuple, value: Any) -> None:
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value


def mutations(seed: int = 0, count: int = 400) -> list[tuple[tuple, Any, dict]]:
    rng = random.Random(seed)
    paths = _paths(BASE)
    out = []
    for path in paths:
        for v in BAD_VALUES:
            doc = copy.deepcopy(BASE)
            _set(doc, path, copy.deepcopy(v))
            out.append((path, v, doc))
    rng.shuffle(out)
    # every path gets at least a few mutations, then a random sample of the rest
    return out[:count]


def exercise(doc: dict, tmp_path) -> str:
    """Load, check, plan and (when it checks out) dry-run a document. Returns what happened."""
    try:
        exp = Experiment.from_dict(doc, base_dir=tmp_path)
    except DocumentError as e:
        assert str(e), "a DocumentError must say what is wrong"
        return "document-error"
    issues = exp.validate()
    assert all(isinstance(i, Issue) for i in issues)
    exp.to_dict()
    recording_plan(exp)
    if any(i.level == "error" for i in issues):
        return "validation-error"
    try:
        run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None)
    except ExperimentError as e:
        assert isinstance(e.report, dict) and e.report.get("what"), "a runtime failure must carry its report"
        return "runtime-error"
    return "ok"


@pytest.mark.parametrize("seed", [1, 2])
def test_mutated_documents_fail_cleanly(seed, tmp_path):
    outcomes: dict[str, int] = {}
    crashes = []
    for i, (path, value, doc) in enumerate(mutations(seed, 220)):
        d = tmp_path / str(i)
        d.mkdir()
        try:
            outcomes[exercise(doc, d)] = outcomes.get(exercise.__name__, 0) + 1
        except (AssertionError, DocumentError, ExperimentError):
            raise
        except Exception as e:  # noqa: BLE001 - that's the point of the test
            crashes.append(f"{'.'.join(map(str, path))} = {value!r:.40} -> {type(e).__name__}: {str(e)[:100]}")
    assert not crashes, "unhandled exceptions for malformed documents:\n" + "\n".join(crashes[:30])


def test_good_document_runs(tmp_path):
    assert exercise(copy.deepcopy(BASE), tmp_path) == "ok"


@pytest.mark.parametrize("field, value, where", [
    ("routines", "text", "routines"),
    ("routines", ["a"], "routines"),
    ("flow", {"a": 1}, "flow"),
    ("devices", "box", "devices"),
    ("variables", [1, 2], "variables"),
    ("settings", "big", "settings"),
])
def test_wrong_top_level_shapes_name_the_place(field, value, where):
    doc = copy.deepcopy(BASE)
    doc[field] = value
    with pytest.raises(DocumentError) as e:
        Experiment.from_dict(doc)
    assert str(e.value).startswith(where + ":")
    assert "expected" in str(e.value)


def test_wrong_nested_shapes_name_the_place():
    doc = copy.deepcopy(BASE)
    doc["routines"]["trial"]["components"][1] = "keyboard"
    with pytest.raises(DocumentError, match=r"routines\.trial\.components\[1\]"):
        Experiment.from_dict(doc)
    doc = copy.deepcopy(BASE)
    doc["routines"]["trial"]["components"] = {"id": "x"}
    with pytest.raises(DocumentError, match=r"routines\.trial\.components: expected a list"):
        Experiment.from_dict(doc)
    doc = copy.deepcopy(BASE)
    doc["flow"][1]["children"] = [["fix"]]
    with pytest.raises(DocumentError, match=r"flow\[1\]\.children\[0\]"):
        Experiment.from_dict(doc)
    doc = copy.deepcopy(BASE)
    doc["flow"][3]["states"]["a"]["next"] = [5]
    with pytest.raises(DocumentError, match=r"flow\[3\]\.states\.a\.next"):
        Experiment.from_dict(doc)
    doc = copy.deepcopy(BASE)
    doc["devices"][0]["options"] = "fast"
    with pytest.raises(DocumentError, match=r"devices\[0\]\.options"):
        Experiment.from_dict(doc)


def test_null_sections_are_empty_not_errors():
    doc = copy.deepcopy(BASE)
    doc["variables"] = None
    doc["devices"] = None
    doc["routines"]["end"] = None
    exp = Experiment.from_dict(doc)
    assert exp.variables == {} and exp.devices == [] and exp.routines["end"].components == []


@pytest.mark.parametrize("size", ["big", [640], [640, 480, 2], [0, 480], [True, 480], None, {"w": 1}, [640, "480"]])
def test_window_size_is_checked_before_the_backend(size, tmp_path):
    doc = copy.deepcopy(BASE)
    doc["settings"]["window"]["size"] = size
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    issues = [i for i in exp.validate() if i.where == "settings.window.size"]
    assert issues and issues[0].level == "error" and "[width, height]" in issues[0].message
    with pytest.raises(DocumentError, match="settings.window.size"):
        window_size(exp.settings)
    with pytest.raises(DocumentError):
        run_experiment(exp, dry_run=True, data_dir=str(tmp_path), log=lambda *a: None)


def test_window_size_accepts_numbers():
    assert window_size({"window": {"size": [800.0, 600]}}) == (800, 600)


def test_measures_with_odd_ids_do_not_crash_validation():
    doc = copy.deepcopy(BASE)
    doc["measures"] = [{"id": ["rt"], "column": "resp.rt"}, {"id": {"a": 1}, "column": "resp.rt", "role": ["x"],
                                                              "summary": {"m": 1}, "loop": ["trials"]},
                       {"id": "ok", "column": ["resp.rt"]}]
    issues = Experiment.from_dict(doc).validate()
    msgs = [i.message for i in issues if i.where.startswith("measures")]
    assert any("must be a name" in m for m in msgs)
    assert any("unknown role" in m for m in msgs)
    assert any("column" in m for m in msgs)


def test_settings_shapes_are_reported():
    doc = copy.deepcopy(BASE)
    doc["settings"]["window"]["fullscreen"] = "yes"
    doc["settings"]["window"]["units"] = 3
    doc["settings"]["data"]["dir"] = ["data"]
    issues = {i.where: i for i in Experiment.from_dict(doc).validate()}
    assert issues["settings.window.fullscreen"].level == "error"
    assert issues["settings.window.units"].level == "error"
    assert issues["settings.data.dir"].level == "error"
    doc = copy.deepcopy(BASE)
    doc["settings"]["data"] = "data"
    with pytest.raises(DocumentError, match="settings.data: expected a mapping"):
        Experiment.from_dict(doc)
    doc = copy.deepcopy(BASE)
    doc["settings"]["window"] = "wide"
    with pytest.raises(DocumentError, match="settings.window"):
        Experiment.from_dict(doc)


# ----------------------------------------------------------------------------- builder API
@pytest.fixture
def api(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from edge.builder.server import BuilderApp, make_handler
    (tmp_path / "exp.yaml").write_text("name: e\nroutines:\n  a:\n    components:\n"
                                       "      - {id: t, type: text, text: hi, duration: 0.1}\nflow: [a]\n")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _post(base, path, data: bytes):
    import json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(base + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


API_ENDPOINTS = ["/api/import", "/api/experiment", "/api/experiment?path=exp.yaml", "/api/restore", "/api/export",
                 "/api/recording", "/api/validate", "/api/dryrun", "/api/device_test", "/api/preflight", "/api/lock",
                 "/api/system_fix", "/api/run_stop", "/api/run", "/api/wizard", "/api/estimate", "/api/play/start",
                 "/api/survey/render", "/api/survey/instrument", "/api/play/input", "/api/play/stop", "/api/to_yaml",
                 "/api/from_yaml", "/api/upload", "/api/upload?path=a.txt", "/api/nothing"]
API_BODIES = [b"[]", b'"text"', b"null", b"5", b"{}", b"{not json", b'{"path": 5}', b'{"experiment": "x"}',
              b'{"experiment": [1]}', b'{"experiment": {"routines": "x"}, "path": "exp.yaml"}', b'{"yaml": 5}',
              b'{"source": 5}', b'{"answers": "x"}', b'{"id": 5}', b'{"path": "exp.yaml", "participant": "x"}',
              b'{"path": "../x.yaml"}', b'{"spec": "x"}']


def test_bad_api_bodies_are_400_not_500(api):
    bad = []
    for ep in API_ENDPOINTS:
        for body in API_BODIES:
            code, res = _post(api, ep, body)
            if code >= 500:
                bad.append(f"{ep} {body[:40]!r} -> {code} {res.get('error')}")
            elif code == 400:
                assert res.get("error"), f"{ep} {body!r}: a 400 must say what is wrong"
    assert not bad, "\n".join(bad)


def test_bad_api_bodies_say_which_field(api):
    assert _post(api, "/api/validate", b"[]")[1]["error"] == "the request body must be a JSON object"
    assert _post(api, "/api/validate", b"{}")[1]["error"] == "the request needs 'experiment'"
    assert _post(api, "/api/validate", b'{"experiment": "x"}')[1]["error"] == "'experiment' must be an object"
    assert "not valid JSON" in _post(api, "/api/validate", b"{nope")[1]["error"]
    assert _post(api, "/api/experiment", b"{}")[1]["error"].startswith("the request needs ?path=")
    code, res = _post(api, "/api/validate", b'{"experiment": {"routines": "x"}}')
    assert code == 200 and res["issues"][0]["level"] == "error" and "routines" in res["issues"][0]["message"]


GET_ENDPOINTS = ["/api/schema", "/api/files", "/api/experiment", "/api/support_bundle", "/api/verify", "/api/assets",
                 "/api/fingerprint", "/api/backups", "/api/bundle", "/api/sessions", "/api/session_tables", "/api/file",
                 "/api/conditions", "/api/template", "/api/scan", "/api/run_status", "/api/next_participant",
                 "/api/play/frame", "/", "/static/app.js", "/static/../server.py", "/nothing"]
GET_QUERIES = ["", "?path=exp.yaml", "?path=5", "?path=", "?path=../../etc/passwd", "?path=nope.yaml", "?id=../x",
               "?name=zzz", "?spec=[1]", "?spec={\"a\":1}", "?path=exp.yaml&spec=xx", "?kind=zzz", "?path=" + "x" * 6000,
               "?path=%00", "?path=%ff%fe", "?path=exp.yaml/x"]


def test_bad_queries_are_400_not_500(api):
    import json
    import urllib.error
    import urllib.request
    bad = []
    for ep in GET_ENDPOINTS:
        for q in GET_QUERIES:
            try:
                with urllib.request.urlopen(api + ep + q, timeout=30) as r:
                    code, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                code, body = e.code, e.read()
            if code >= 500:
                bad.append(f"{ep}{q[:40]} -> {code} {json.loads(body).get('error')}")
    assert not bad, "\n".join(bad)
