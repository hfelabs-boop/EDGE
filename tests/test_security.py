"""Security regression tests: the expression sandbox, the builder's local server, the HTML page bridge,
importers, network devices, exports and file writes. Each test pins a fix; none should ever be relaxed."""

import io
import json
import tarfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge.expressions import ExpressionError, evaluate
from edge.model import Experiment


# ============================================================================ $expressions
REJECTED = [
    # reaching modules, classes, frames, code objects or string-based attribute lookup
    "statistics.sys", "math.__dict__", "random.SystemRandom", "str.mro()", "().__class__",
    "'{0.__class__}'.format(1)", "str.format('{0}', 1)", "math.sqrt.__globals__", "len.__self__",
    "(x for x in [1]).gi_frame", "__import__('os')", "_ga(1, 'x')", "[x for x in [1]].__len__()",
    "dict.fromkeys.__doc__", "random.choice.__self__",
]
ALLOWED = {
    "resp.rt < 0.5": True, "math.sqrt(16)": 4.0, "statistics.mean([1, 2, 3])": 2, "random.randint(3, 3)": 3,
    "f'Score: {score}'": "Score: 3", "word.upper()": "RED", "[x * 2 for x in [1, 2]]": [2, 4],
    "trials.accuracy >= 0.8": True, "'a' in keys": True, "devices.eeg.Cz > 1": True, "mean([2, 4])": 3.0,
    "max(1, 2)": 2, "round(math.pi, 2)": 3.14, "word.startswith('r')": True, "keys[0]": "a",
}


@pytest.fixture
def ns():
    from edge.components.base import Results
    return {"resp": Results(rt=0.3), "score": 3, "word": "red", "trials": Results(accuracy=0.9), "keys": ["a"],
            "devices": Results(eeg=Results(Cz=2.0)), "_secret": "hidden"}


@pytest.mark.parametrize("src", REJECTED)
def test_expressions_cannot_reach_python_internals(src, ns):
    with pytest.raises(ExpressionError):
        evaluate(src, ns)


@pytest.mark.parametrize("src,expected", list(ALLOWED.items()))
def test_ordinary_expressions_still_work(src, expected, ns):
    assert evaluate(src, ns) == expected


def test_expression_helpers_are_not_modules(ns):
    import types
    assert not isinstance(evaluate("math", ns), types.ModuleType)
    assert evaluate("sorted(dir(math))[0]", {**ns, "dir": dir})[0].isalpha()
    with pytest.raises(ExpressionError):
        evaluate("_secret", ns)                       # underscore names from the namespace are not exposed
    with pytest.raises(ExpressionError):
        evaluate("'x' * 1 if ('a' + 'b' * 200000) else 1", ns) if False else evaluate("'" + "a" * 100_001 + "'", ns)


def test_experiment_files_with_hostile_expressions_do_not_run_code(tmp_path):
    from edge.engine import run_experiment
    from edge.diagnostics import ExperimentError
    doc = {"name": "x", "routines": {"t": {"components": [
        {"id": "s", "type": "text", "text": "$statistics.sys.modules['os'].getcwd()", "duration": 0.1}]}}, "flow": ["t"]}
    with pytest.raises(ExperimentError) as e:
        run_experiment(Experiment.from_dict(doc, base_dir=tmp_path), dry_run=True, data_dir=str(tmp_path / "d"),
                       log=lambda *a: None)
    msg = e.value.report["message"]
    assert "has no 'sys'" in msg or "not allowed" in msg          # the helper is not the real module


# ============================================================================ the builder's local server
@pytest.fixture
def server(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    (tmp_path / "root" / "s").mkdir(parents=True)
    (tmp_path / "outside.csv").write_text("a\n1\n")            # outside the builder's folder
    tmp_path = tmp_path / "root"
    (tmp_path / "s" / "exp.yaml").write_text("name: e\nroutines:\n  a:\n    components:\n      - {id: t, type: text, text: hi, duration: 0.1}\nflow: [a]\n")
    (tmp_path / "s" / "page.html").write_text("<html><body>hi</body></html>")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", tmp_path
    httpd.shutdown()


def _req(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_request_allowed_rules():
    from edge.builder.server import request_allowed
    ok = lambda h, m="GET": request_allowed(h, m) is None
    assert ok({"Host": "127.0.0.1:8765"}) and ok({"Host": "localhost:8765"}) and ok({"Host": "[::1]:8765"})
    assert ok({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"}, "POST")
    assert ok({"Host": "127.0.0.1:8765", "Origin": "http://localhost:8765"}, "POST")
    assert ok({}, "POST")                                                     # scripts and tests: no browser headers
    assert not ok({"Host": "evil.example:8765"})                              # DNS rebinding
    assert not ok({"Host": "127.0.0.1.evil.example"})
    assert not ok({"Host": "127.0.0.1:8765", "Origin": "http://evil.example"}, "POST")   # CSRF
    assert not ok({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1.evil.example"}, "POST")
    assert not ok({"Host": "127.0.0.1:8765", "Sec-Fetch-Site": "cross-site"}, "POST")
    assert not ok({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:9999"}, "POST")   # another local program's page
    assert ok({"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}, "POST")
    assert not ok({"Host": "127.0.0.1:8765", "Origin": "null"}, "POST")
    assert not ok({"Host": "127.0.0.1:8765", "Sec-Fetch-Site": "cross-site"}, "GET")


def test_server_refuses_other_hosts_and_cross_site_posts(server):
    base, root = server
    assert _req(base + "/api/files")[0] == 200
    code, _, body = _req(base + "/api/files", headers={"Host": "evil.example"})
    assert code == 403 and b"this computer" in body
    hostile = {"Origin": "http://evil.example", "Content-Type": "text/plain"}
    code, _, body = _req(base + "/api/validate", headers=hostile, data=b'{"experiment": {}}')
    assert code == 403 and b"cross-site" in body
    code, _, _ = _req(base + "/api/upload?path=s/x.png", headers={"Sec-Fetch-Site": "cross-site"}, data=b"x")
    assert code == 403 and not (root / "s" / "x.png").exists()
    # the builder's own page is allowed
    same = {"Origin": base, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}
    code, _, body = _req(base + "/api/validate", headers=same, data=b'{"experiment": {"routines": {}, "flow": []}}')
    assert code == 200 and b"issues" in body


def test_served_user_files_cannot_script_against_the_api(server):
    base, _ = server
    code, headers, _ = _req(base + "/api/file?path=s/page.html")
    assert code == 200 and headers["Content-Security-Policy"].startswith("sandbox") and headers["X-Content-Type-Options"] == "nosniff"
    code, headers, _ = _req(base + "/api/file?path=s/exp.yaml")
    assert code == 200 and "Content-Security-Policy" not in headers        # plain data: no sandbox needed
    code, headers, _ = _req(base + "/api/files")
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_uploads_cannot_plant_code_and_conditions_stay_inside(server):
    base, root = server
    for name in ("s/evil.py", "s/edge/__main__.py", "s/x.pyw", "s/go.cmd", "s/.hidden", "s/a.pth"):
        code, _, body = _req(base + f"/api/upload?path={name}", data=b"print(1)")
        assert code == 400, name
        assert not (root / name).exists()
    assert _req(base + "/api/upload?path=s/images/ok.png", data=b"png")[0] == 200
    code, _, body = _req(base + "/api/conditions?exp=s/exp.yaml&spec=%22../../outside.csv%22")
    assert code == 400 and b"inside the experiments folder" in body
    (root / "s" / "c.csv").write_text("a\n1\n")
    assert json.loads(_req(base + "/api/conditions?exp=s/exp.yaml&spec=%22c.csv%22")[2])["rows"] == [{"a": 1}]


def test_next_participant_never_crawls_outside_the_folder(tmp_path):
    from edge.builder.server import BuilderApp
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "e.yaml").write_text("name: e\nsettings: {data: {dir: ../../..}}\nroutines:\n  a:\n    components: []\nflow: [a]\n")
    r = BuilderApp(tmp_path).next_participant("s/e.yaml")
    assert r["used"] == [] and r["data_dir"] == "s/data"


def test_real_runs_do_not_import_from_the_experiments_folder(tmp_path, monkeypatch):
    from edge.builder import server as srv
    seen = {}

    class P:
        pid = 1
        stdout = io.StringIO("")

        def poll(self):
            return 0
    monkeypatch.setattr(srv.subprocess, "Popen", lambda cmd, **kw: seen.update(kw) or P())
    (tmp_path / "e.yaml").write_text("name: e\nroutines: {}\nflow: []\n")
    srv.BuilderApp(tmp_path).run_real("e.yaml", {}, True)
    assert seen["env"]["PYTHONSAFEPATH"] == "1"


# ============================================================================ the HTML page bridge
def test_page_variables_cannot_break_out_of_the_bridge_script():
    from edge.components.html import render_page
    page = render_page("<html><body><p>{{word}}</p></body></html>",
                       {"word": "</script><script>alert(1)</script>", "n": 1}, None, "Go", token="abc")
    assert "</script><script>alert" not in page            # neither in the placeholder nor in the JSON bridge
    assert "&lt;/script&gt;" in page and "<\\/script>" in page
    assert "'X-Edge-Token': 'abc'" in page


def test_page_server_needs_the_token_and_limits_bodies(tmp_path):
    from edge.components.html import PageServer
    srv = PageServer("<html></html>", tmp_path, token="tok")
    try:
        bad = urllib.request.Request(srv.url + "__edge/marker", data=b'{"label": "x"}', headers={"X-Edge-Token": "wrong"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 403 and srv.markers.empty()
        big = urllib.request.Request(srv.url + "__edge/submit", data=b"{}", headers={"X-Edge-Token": "tok",
                                                                                     "Content-Length": str(30 * 1024 * 1024)})
        with pytest.raises(Exception):
            urllib.request.urlopen(big, timeout=2)
        good = urllib.request.Request(srv.url + "__edge/marker", data=b'{"label": "x"}', headers={"X-Edge-Token": "tok"})
        urllib.request.urlopen(good)
        assert srv.markers.get(timeout=1) == "x"
    finally:
        srv.close()


# ============================================================================ importers and bundles
def test_imported_files_stay_inside_the_experiment_folder(tmp_path):
    from edge.importers.base import ImportResult, finalize, inside
    out = tmp_path / "out"
    out.mkdir()
    assert inside(out, "images/a.png") == (out / "images" / "a.png").resolve()
    for bad in ("../x.txt", "/etc/x", "C:/x", "a/../../x", ""):
        assert inside(out, bad) is None, bad
    res = ImportResult(doc={}, source=tmp_path / "src.osexp", platform="t")
    res.generated_files = {"../evil.txt": "x", "ok.txt": "y"}
    res.assets = {"../../etc/passwd"}
    finalize(res, out)
    assert (out / "ok.txt").exists() and not (tmp_path / "evil.txt").exists()
    assert any("outside the experiment folder" in n["message"] for n in res.notes)


def test_opensesame_pool_names_are_sanitised(tmp_path):
    from edge.importers.base import ImportResult
    from edge.importers.opensesame import _read
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in (("exp/script.opensesame", b"set foo 1"), ("exp/pool/good.png", b"g"),
                           ("exp/pool//abs/evil.png", b"e"), ("exp/pool/../evil2.png", b"e"), ("exp/pool/sub/./x.png", b"s")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    p = tmp_path / "e.osexp"
    p.write_bytes(buf.getvalue())
    script, pool = _read(p, ImportResult(doc={}, source=p, platform="OpenSesame"))
    assert script == "set foo 1" and set(pool) == {"good.png", "sub/x.png", "abs/evil.png"}   # relative, inside
    assert not any(k.startswith("/") or ".." in k.split("/") for k in pool)


# ============================================================================ network devices
def test_udp_messages_cannot_overwrite_reserved_or_unlisted_names():
    from edge.devices import create_device
    from edge.devices.messages import parse_message

    class Sess:
        vars = {}
        participant = {"participant": "007"}
    dev = create_device("udp_messages", "bci", {"port": 0, "variables": ["alpha"]})
    dev.session = Sess()
    dev.connect()
    try:
        dev._pending.append((1.0, {"alpha": 0.5, "beta": 1, "participant": "999", "devices": {}, "_x": 1, "bad name": 2, "event": "go"}))
        evs = dev.drain()
        assert Sess.vars == {"alpha": 0.5} and dev.values == {"alpha": 0.5}
        assert [e.name for e in evs] == ["go"]
    finally:
        dev.close()
    dev2 = create_device("udp_messages", "any", {"port": 0})
    dev2.session = Sess()
    dev2.connect()
    try:
        dev2._pending.append((1.0, {"beta": 1, "participant": "999", "vars": 3, "t": 9}))
        dev2.drain()
        assert Sess.vars == {"alpha": 0.5, "beta": 1}           # unlisted fields are fine, reserved names never
        assert dev2._pending.maxlen == 10_000
    finally:
        dev2.close()
    assert parse_message(b"x" * 70_000) == {}


def test_listening_on_every_network_is_flagged():
    doc = {"name": "n", "devices": [{"id": "bci", "type": "udp_messages", "options": {"host": "0.0.0.0", "port": 5005}}],
           "routines": {"a": {"components": [{"id": "t", "type": "text", "text": "x", "duration": 1}]}}, "flow": ["a"]}
    msgs = [str(i) for i in Experiment.from_dict(doc).validate()]
    assert any("every network" in m for m in msgs) and any("becomes a variable" in m for m in msgs)


def test_gazepoint_commands_escape_attribute_values():
    from edge.devices.gazepoint import Gazepoint
    sent = []
    g = Gazepoint.__new__(Gazepoint)
    g.sock = type("S", (), {"sendall": lambda self, b: sent.append(b)})()
    g.command("SET", 'ENABLE_SEND_DATA', STATE='1" EVIL="x')
    assert sent[0] == b'<SET ID="ENABLE_SEND_DATA" STATE=\'1" EVIL="x\' />\r\n'


# ============================================================================ exports, file writes, settings
def test_csv_cells_cannot_become_spreadsheet_formulas(tmp_path):
    from edge.export import _cell, write_delimited
    assert _cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert _cell("+1 more") == "'+1 more" and _cell("@me") == "'@me" and _cell("-x") == "'-x"
    assert _cell("-5") == "-5" and _cell(-5) == -5 and _cell("ok") == "ok" and _cell(None) == ""
    write_delimited(tmp_path / "t.csv", ["a"], [{"a": "=1+1"}])
    assert "'=1+1" in (tmp_path / "t.csv").read_text(encoding="utf-8-sig")


def test_mcp_write_file_refuses_scripts_and_hidden_files(tmp_path):
    pytest.importorskip("mcp")
    import asyncio
    from edge.mcp_server import create_server
    mcp = create_server(tmp_path)

    def call(**kw):
        r = asyncio.run(mcp.call_tool("write_file", kw))
        content = r[0] if isinstance(r, tuple) else r
        return json.loads(content[0].text)
    for name in ("a.pyw", "b.cmd", ".env", "c.pth", "d.desktop"):
        assert call(path=name, content="x")["ok"] is False and not (tmp_path / name).exists()
    assert call(path="notes.txt", content="x")["ok"] is True


def test_data_outside_the_experiment_folder_is_flagged(tmp_path):
    doc = {"name": "n", "settings": {"data": {"dir": "../elsewhere"}},
           "routines": {"a": {"components": [{"id": "t", "type": "text", "text": "x", "duration": 1}]}}, "flow": ["a"]}
    assert any("outside the experiment's folder" in str(i) for i in Experiment.from_dict(doc, base_dir=tmp_path).validate())
    doc["settings"]["data"]["dir"] = "data"
    assert not any("outside" in str(i) for i in Experiment.from_dict(doc, base_dir=tmp_path).validate())


def test_no_shell_true_anywhere():
    root = Path(__file__).resolve().parent.parent / "edge"
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "shell=True" not in text and "os.system(" not in text and "yaml.load(" not in text, p
        assert "pickle" not in text or p.name == "export.py" and "pickle" not in text, p
