import json
import threading
import time
import urllib.request

from edge.components.html import FormFields, PageServer, auto_answer, render_page
from edge.participant import VirtualParticipant

PAGE = """<html><body><h1>Hi {{participant}} &amp; {{word}}</h1>
<form><input type="checkbox" name="agree" value="yes" required>
<select name="hand"><option value="">-</option><option value="L">L</option><option value="R">R</option></select>
<input type="number" name="age" min="18" max="20"><input type="radio" name="q" value="1"><input type="radio" name="q" value="2">
<textarea name="txt"></textarea><input type="submit" value="Go"></form></body></html>"""


def test_render_inserts_variables_and_bridge():
    out = render_page(PAGE, {"participant": "007", "word": "<b>x</b>"}, None, "Continue")
    assert "Hi 007 &amp; &lt;b&gt;x&lt;/b&gt;" in out
    assert "window.edge" in out and "edge.submit({})" not in out   # page has a form: no extra button
    bare = render_page("<p>Read this</p>", {}, None, "Next")
    assert "<!doctype html>" in bare and "edge.submit({})" in bare and ">Next<" in bare


def test_auto_answer_respects_form():
    import random
    ans = auto_answer(PAGE, random.Random(1))
    assert ans["agree"] == "yes" and ans["hand"] in ("L", "R") and 18 <= int(ans["age"]) <= 20
    assert ans["q"] in ("1", "2") and ans["txt"] == "virtual participant"
    p = FormFields()
    p.feed(PAGE)
    assert set(p.fields) == {"agree", "hand", "age", "q", "txt"}


def test_page_server_round_trip(tmp_path):
    (tmp_path / "img.png").write_bytes(b"PNG")
    srv = PageServer("<html><body>ok</body></html>", tmp_path)
    try:
        assert b"ok" in urllib.request.urlopen(srv.url).read()
        assert urllib.request.urlopen(srv.url + "img.png").read() == b"PNG"
        req = urllib.request.Request(srv.url + "__edge/submit", data=json.dumps({"agree": "yes"}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req).read()
        assert srv.submissions.get(timeout=1)[1] == {"agree": "yes"}
        try:
            urllib.request.urlopen(srv.url + "../../etc/passwd")
            raise AssertionError("path escape allowed")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.close()


def test_html_component_dry_run(run, tmp_path):
    (tmp_path / "form.html").write_text(PAGE)
    d = {"routines": {"r": {"components": [{"id": "f", "type": "html", "file": "form.html", "end_routine": True}]}},
         "flow": [{"loop": "L", "conditions": [{"word": "sun"}], "children": ["r"]}]}
    summary, session, _ = run(d, vp=VirtualParticipant(seed=3))
    row = session.data.trial_rows[0]
    assert row["f.submitted"] == 1 and row["f.agree"] == "yes" and isinstance(row["f.age"], int)
    assert row["f.rt"] > 1


def test_html_component_real_submission(tmp_path):
    """Real-time run: the page is served over HTTP and a 'browser' (this test) submits the form."""
    from tests.conftest import run_headless
    import edge.components.html as h
    opened = []
    h.webbrowser.open = lambda url, new=0: opened.append(url) or True   # don't launch a browser in tests
    (tmp_path / "p.html").write_text("<form><input name='mood'></form>")
    d = {"routines": {"r": {"duration": 10, "components": [
        {"id": "page", "type": "html", "file": "p.html", "display": "browser", "end_routine": True}]}},
        "flow": ["r"]}

    def browser():
        while not opened:
            time.sleep(0.01)
        html = urllib.request.urlopen(opened[0]).read().decode()
        assert "window.edge" in html
        time.sleep(0.2)
        req = urllib.request.Request(opened[0] + "__edge/submit", data=b'{"mood": "7"}',
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)

    t = threading.Thread(target=browser, daemon=True)
    t.start()
    summary, session, _ = run_headless(d, tmp_path, realtime=True)
    row = session.data.trial_rows[0]
    assert row["page.mood"] == 7 and 0.15 < row["page.rt"] < 5 and row["routine_duration"] < 5


def test_bundle_includes_page_assets(tmp_path):
    from edge.storage import export_bundle, save_document
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages/a.html").write_text('<img src="pic.png"><link href="s.css"><script src="https://x/y.js"></script>')
    (tmp_path / "pages/pic.png").write_bytes(b"P")
    (tmp_path / "pages/s.css").write_text("body{}")
    save_document(tmp_path / "e.yaml", {"name": "e", "routines": {"r": {"components": [
        {"id": "h", "type": "html", "file": "pages/a.html"}]}}, "flow": ["r"]})
    res = export_bundle(tmp_path / "e.yaml")
    assert sorted(res["files"]) == ["pages/a.html", "pages/pic.png", "pages/s.css"]
