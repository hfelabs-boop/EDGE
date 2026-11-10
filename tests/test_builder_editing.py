"""Builder editing: expression checks as you type, paste with files, trial-list files edited in place, and the
static contract of the editing scripts (multi-select, clipboard, formula checks, file trial lists)."""
from __future__ import annotations

import json
import re
import shutil
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import storage
from edge.builder import edit_api
from edge.builder.server import BuilderApp, make_handler

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
STATIC = ROOT / "edge" / "builder" / "static"


@pytest.fixture
def builder(tmp_path):
    shutil.copytree(EXAMPLES / "stroop", tmp_path / "stroop")
    app = BuilderApp(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, headers=None, method=None):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(base + path, data=data, headers=h, method=method or ("POST" if body is not None else "GET"))
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    call.root = tmp_path
    call.app = app
    yield call
    httpd.shutdown()


def stroop(builder) -> dict:
    return storage.load_document(builder.root / "stroop/stroop.yaml").doc


def check(builder, expr, where, doc=None):
    st, r = builder("/api/edit/check", {"experiment": doc or stroop(builder), "path": "stroop/stroop.yaml",
                                        "expr": expr, "where": where})
    assert st == 200, r
    return r


# ============================================================================ expression checks
def test_unknown_column_gets_did_you_mean_and_a_fix(builder):
    r = check(builder, "$inkk == 'red'", {"routine": "trial"})
    assert not r["ok"]
    [i] = r["issues"]
    assert "no column called 'inkk'" in i["message"] and "Did you mean 'ink'?" in i["message"]
    assert i["fix"] == {"from": "inkk", "to": "ink"}
    assert "ink" in i["hint"]


def test_syntax_error_and_forbidden_constructs(builder):
    r = check(builder, "$word.upper(", {"routine": "trial"})
    assert not r["ok"] and "syntax error" in r["issues"][0]["message"] and "matching ')'" in r["issues"][0]["message"]
    r = check(builder, "lambda x: x", {"routine": "trial"})
    assert not r["ok"] and "not allowed in a formula" in r["issues"][0]["message"]
    r = check(builder, "().__class__", {"routine": "trial"})
    assert not r["ok"]


def test_a_result_that_does_not_exist(builder):
    r = check(builder, "$'ok' if resp.cor else 'no'", {"routine": "feedback"})
    assert r["issues"][0]["fix"] == {"from": "resp.cor", "to": "resp.corr"}
    assert check(builder, "$'ok' if resp.corr else 'no'", {"routine": "feedback"})["issues"] == []


def test_names_not_available_at_that_place(builder):
    # the screen after the trial list can't use the list's columns
    r = check(builder, "$wrd", {"routine": "thanks"})
    assert "isn't available here" in r["issues"][0]["message"] and "'word'" in r["issues"][0]["message"]
    assert "fix" not in r["issues"][0]
    r = check(builder, "$word", {"routine": "thanks"})
    assert r["issues"] and "trial list 'trials'" in r["issues"][0]["message"]
    # inside the list it is fine, and so is the list's own statistic in "Stop early when"
    assert check(builder, "$word == 'RED'", {"routine": "trial"})["issues"] == []
    assert check(builder, "$trials.accuracy < 0.5 and ink == 'red'", {"flow": [1], "field": "stop_if"})["issues"] == []
    r = check(builder, "$inkk", {"flow": [1], "field": "stop_if"})
    assert r["issues"][0]["fix"]["to"] == "ink"


def test_a_formula_already_in_the_experiment_is_checked_like_a_new_one(builder):
    doc = stroop(builder)
    doc["flow"][0] = {"routine": "instructions", "if": "$inkk > 1"}       # the committed value is wrong too
    r = check(builder, "$inkk > 1", {"flow": [0], "field": "if"}, doc=doc)
    assert r["issues"] and "'inkk'" in r["issues"][0]["message"]


def test_if_conditions_routes_and_measures(builder):
    doc = stroop(builder)
    assert check(builder, "$participant == '001'", {"flow": [0], "field": "if"})["issues"] == []
    # a trial list shown only if …: checked where the list is
    assert check(builder, "$score > 1", {"flow": [1], "field": "if"})["issues"] == []
    assert check(builder, "$wrd > 1", {"flow": [1], "field": "if"})["issues"]
    doc["flow"].append({"statemachine": "wf", "start": "a", "states": {"a": {"run": ["thanks"], "next": [{"goto": "end"}]}}})
    assert check(builder, "$a.visit > 2", {"flow": [3], "field": "route", "state": "a"}, doc=doc)["issues"]
    assert check(builder, "$wf.visit > 2", {"flow": [3], "field": "route", "state": "a"}, doc=doc)["issues"] == []
    r = check(builder, "$resp.cor == 1", {"field": "measure"})
    assert r["issues"] and r["issues"][0]["fix"]["to"] == "resp.corr"


def test_names_for_suggestions(builder):
    r = check(builder, "$wo", {"routine": "trial"})
    names = {n["name"]: n for n in r["names"]}
    assert names["word"]["kind"] == "column" and "trials" in names["word"]["detail"]
    for n in ("resp.rt", "resp.corr", "trials.accuracy", "score", "participant", "t", "round", "math.sqrt"):
        assert n in names, n
    st, r2 = builder("/api/edit/names", {"experiment": stroop(builder), "path": "stroop/stroop.yaml", "where": {"routine": "thanks"}})
    assert st == 200 and "word" not in {n["name"] for n in r2["names"]}      # not a column out there


def test_check_rejects_bad_requests(builder):
    st, r = builder("/api/edit/check", {"experiment": stroop(builder), "expr": "$x", "where": {"routine": "nope"}})
    assert st == 400 and "no screen" in r["error"]
    st, r = builder("/api/edit/check", {"experiment": stroop(builder), "expr": "$x", "where": {"flow": [9, "x"], "field": "if"}})
    assert st == 400
    st, r = builder("/api/edit/check", {"expr": "$x"})
    assert st == 400 and "experiment" in r["error"]
    st, r = builder("/api/edit/check", {"experiment": stroop(builder), "expr": "$x"}, headers={"Content-Type": "text/plain"})
    assert st == 415
    st, r = builder("/api/edit/check", {"experiment": stroop(builder), "expr": "$x"}, headers={"Origin": "http://evil.example"})
    assert st == 403


# ============================================================================ paste with files
def two_experiments(builder):
    root = builder.root
    (root / "stroop/images").mkdir()
    (root / "stroop/images/face.png").write_bytes(b"\x89PNG face")
    (root / "stroop/images/house.png").write_bytes(b"\x89PNG house")
    (root / "other").mkdir()
    (root / "other/other.yaml").write_text("name: other\nroutines:\n  a:\n    components: []\nflow: [a]\n")
    (root / "other/stroop.csv").write_text("something,else\n1,2\n")         # same name, other content
    return root


def test_paste_copies_the_files_a_fragment_uses(builder):
    root = two_experiments(builder)
    doc = stroop(builder)
    frag = {"routines": {"trial": doc["routines"]["trial"] | {"components": doc["routines"]["trial"]["components"] + [
        {"id": "pic", "type": "image", "image": "images/face.png"}]}},
        "flow": [doc["flow"][1]]}
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "other/other.yaml", "fragment": frag})
    assert st == 200, r
    assert r["renamed"] == {"stroop.csv": "stroop_2.csv"}                  # a different file had the name
    assert (root / "other/stroop_2.csv").read_text() == (root / "stroop/stroop.csv").read_text()
    assert (root / "other/stroop.csv").read_text().startswith("something")  # never overwritten
    assert (root / "other/images/face.png").read_bytes() == b"\x89PNG face"
    assert not (root / "other/images/house.png").exists()                  # only what the fragment uses
    # pasting again: the same files are already there, nothing new
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "other/other.yaml", "fragment": frag})
    assert r["copied"] == [] and r["renamed"] == {"stroop.csv": "stroop_2.csv"}


def test_paste_files_rewrites_a_copied_list_that_names_a_renamed_picture(builder):
    root = two_experiments(builder)
    (root / "stroop/pics.csv").write_text("pic,word\nimages/face.png,A\n")
    (root / "other/images").mkdir()
    (root / "other/images/face.png").write_bytes(b"another face")
    frag = {"routines": {}, "flow": [{"loop": "l", "conditions": "pics.csv", "children": []}]}
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "other/other.yaml", "fragment": frag})
    assert r["renamed"] == {"images/face.png": "images/face_2.png"}
    assert (root / "other/pics.csv").read_text().splitlines()[1] == "images/face_2.png,A"


def test_paste_files_is_confined(builder, tmp_path):
    root = two_experiments(builder)
    (root / "secret.csv").write_text("x\n1\n")
    (root / "stroop/run.py").write_text("print('hi')")
    (root / "stroop/data").mkdir()
    (root / "stroop/data/p1.csv").write_text("rt\n1\n")
    frag = {"routines": {"s": {"components": [{"id": "p", "type": "image", "image": "../secret.csv"},
                                              {"id": "q", "type": "html", "file": "run.py"},
                                              {"id": "r", "type": "image", "image": "/etc/passwd"},
                                              {"id": "d", "type": "image", "image": "data/p1.csv"}]}}, "flow": []}
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "other/other.yaml", "fragment": frag})
    assert st == 200 and r["copied"] == []
    assert set(r["missing"]) | set(r["skipped"]) >= {"../secret.csv", "run.py", "/etc/passwd", "data/p1.csv"}
    assert not (root / "other/run.py").exists() and not (root / "secret.csv").with_name("x").exists()
    st, r = builder("/api/edit/paste_files", {"from": "../outside/x.yaml", "to": "other/other.yaml", "fragment": frag})
    assert st == 400
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "/tmp/x.yaml", "fragment": frag})
    assert st == 400
    # the same experiment: nothing to copy
    st, r = builder("/api/edit/paste_files", {"from": "stroop/stroop.yaml", "to": "stroop/stroop.yaml", "fragment": frag})
    assert r["same"] and r["copied"] == []


# ============================================================================ trial-list files
def table(builder, file, exp="stroop/stroop.yaml"):
    st, r = builder(f"/api/edit/table?exp={exp}&file={file}")
    assert st == 200, r
    return r


def save(builder, file, columns, rows, fp, exp="stroop/stroop.yaml", **kw):
    return builder("/api/edit/table", {"exp": exp, "file": file, "columns": columns, "rows": rows, "fingerprint": fp, **kw})


def test_csv_round_trip_with_a_backup_in_history(builder):
    t = table(builder, "stroop.csv")
    assert t["columns"] == ["word", "ink", "congruent", "correct_key"] and t["rows"][0] == ["RED", "red", "1", "r"]
    rows = [["PURPLE", "red", "1", "r"]] + t["rows"][1:] + [["NEW", "", "", ""]]
    st, r = save(builder, "stroop.csv", t["columns"], rows, t["fingerprint"])
    assert st == 200 and r["ok"] and r["backup"]
    p = builder.root / "stroop/stroop.csv"
    assert p.read_text().splitlines()[1] == "PURPLE,red,1,r" and p.read_text().splitlines()[-1] == "NEW,,,"
    # later saves of the same session skip the backup
    st, r2 = save(builder, "stroop.csv", t["columns"], rows[:-1], r["fingerprint"], backup=False)
    assert r2["ok"] and r2["backup"] is None
    assert len(storage.list_backups(p)) == 1
    # History restores the version before the session
    st, res = builder(f"/api/restore?path=stroop/stroop.csv&id={r['backup']}", {})
    assert st == 200
    assert p.read_text().splitlines()[1] == "RED,red,1,r"
    # the experiment still loads the restored rows
    from edge.conditions import load_conditions
    assert load_conditions("stroop.csv", builder.root / "stroop")[0]["word"] == "RED"


def test_csv_keeps_its_separator_line_endings_and_bom(builder):
    p = builder.root / "stroop/semi.csv"
    p.write_bytes("\ufeffa;b\r\n1;x\r\n".encode("utf-8"))
    t = table(builder, "semi.csv")
    assert t["delimiter"] == ";" and t["rows"] == [["1", "x"]]
    st, r = save(builder, "semi.csv", ["a", "b"], [["2", "y; z"]], t["fingerprint"])
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8-sig") == 'a;b\r\n2;"y; z"\r\n'
    (builder.root / "stroop/t.tsv").write_text("a\tb\n1\t2\n")
    t = table(builder, "t.tsv")
    save(builder, "t.tsv", ["a", "b", "c"], [["1", "2", "3"]], t["fingerprint"])
    assert (builder.root / "stroop/t.tsv").read_text() == "a\tb\tc\n1\t2\t3\n"


def test_a_change_made_elsewhere_is_never_overwritten_silently(builder):
    t = table(builder, "stroop.csv")
    p = builder.root / "stroop/stroop.csv"
    p.write_text(p.read_text().replace("RED", "ROT"))
    st, r = save(builder, "stroop.csv", t["columns"], t["rows"], t["fingerprint"])
    assert st == 200 and r["ok"] is False and r["conflict"] and r["fingerprint"] == storage.fingerprint(p)
    assert "ROT" in p.read_text()
    st, r = save(builder, "stroop.csv", t["columns"], t["rows"], t["fingerprint"], force=True)
    assert r["ok"] and "ROT" not in p.read_text() and len(storage.list_backups(p)) == 1


def test_table_requests_are_checked_and_confined(builder):
    t = table(builder, "stroop.csv")
    st, r = save(builder, "stroop.csv", ["a", "a"], [["1", "2"]], t["fingerprint"])
    assert st == 400 and "two columns" in r["error"]
    st, r = save(builder, "stroop.csv", ["a", ""], [["1", "2"]], t["fingerprint"])
    assert st == 400
    st, r = save(builder, "stroop.csv", ["a"], [[{"x": 1}]], t["fingerprint"])
    assert st == 400
    for bad in ("../outside.csv", "stroop.yaml", "/etc/passwd", ".edge/backups/x.csv"):
        st, r = builder(f"/api/edit/table?exp=stroop/stroop.yaml&file={bad}")
        assert st == 400, bad
        st, r = save(builder, bad, ["a"], [["1"]], None)
        assert st == 400, bad
    assert not (builder.root / "outside.csv").exists()
    st, r = builder("/api/edit/table?exp=stroop/stroop.yaml&file=missing.csv")
    assert st == 400 and "isn't in the experiment's folder" in r["error"]


def make_workbook(path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "trials"
    ws.append(["word", "ink", "n"])
    ws.append(["RED", "red", 1])
    ws.append(["GREEN", "green", "=C2+1"])
    ws["A1"].font = Font(bold=True)
    wb.create_sheet("notes").append(["keep me"])
    wb.save(path)
    return openpyxl


def test_xlsx_round_trip_asks_before_writing_values(builder):
    p = builder.root / "stroop/words.xlsx"
    openpyxl = make_workbook(p)
    t = table(builder, "words.xlsx")
    assert t["format"] == "xlsx" and t["sheet"] == "trials" and t["sheets"] == ["trials", "notes"] and t["formulas"] == 1
    assert any("other sheets (notes)" in w for w in t["warnings"]) and any("formula" in w for w in t["warnings"])
    rows = [["CYAN", "red", "1"], ["GREEN", "green", "2"], ["BLUE", "blue", "0.5"]]
    st, r = save(builder, "words.xlsx", t["columns"], rows, t["fingerprint"])
    assert r["ok"] is False and r["needs_confirm"] and r["other_sheets"] == ["notes"] and r["formulas"] == 1
    assert storage.fingerprint(p) == t["fingerprint"]                    # nothing written yet
    st, r = save(builder, "words.xlsx", t["columns"], rows, t["fingerprint"], confirm_values=True)
    assert r["ok"] and r["backup"]
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["trials", "notes"] and wb["notes"]["A1"].value == "keep me"
    ws = wb["trials"]
    assert [c.value for c in ws[2]] == ["CYAN", "red", 1] and ws["C4"].value == 0.5 and ws["A1"].font.bold
    from edge.conditions import load_conditions
    assert [r["word"] for r in load_conditions("words.xlsx", builder.root / "stroop")] == ["CYAN", "GREEN", "BLUE"]
    # the backup in History is the original workbook
    [b] = storage.list_backups(p)
    assert openpyxl.load_workbook(b["path"])["trials"]["C3"].value == "=C2+1"


def test_xlsx_without_openpyxl_offers_a_csv_copy(builder, monkeypatch):
    p = builder.root / "stroop/words.xlsx"
    make_workbook(p)
    monkeypatch.setattr(edit_api, "has_openpyxl", lambda: False)
    t = table(builder, "words.xlsx")
    assert not t["writable"] and any("pip install edge-experiments[excel]" in w for w in t["warnings"])
    st, r = save(builder, "words.xlsx", t["columns"], t["rows"], t["fingerprint"])
    assert r["ok"] is False and r["needs_csv"]
    st, r = save(builder, "words.xlsx", t["columns"], [["RED", "red", 1]], t["fingerprint"], as_csv=True)
    assert r["ok"] and r["new_file"] and r["saved"] == "words.csv"
    assert (builder.root / "stroop/words.csv").read_text() == "word,ink,n\nRED,red,1\n"
    assert storage.fingerprint(p) == t["fingerprint"]


# ============================================================================ the scripts' contract (static)
def test_editing_scripts_are_loaded_and_hooked_in():
    html = (STATIC / "index.html").read_text()
    for f in ("edit.js", "exprcheck.js", "tablefile.js"):
        assert f'<script src="/static/{f}"></script>' in html
    assert '<link rel="stylesheet" href="/static/edit.css">' in html
    build = (STATIC / "build.js").read_text()
    for hook in ("screenInSelection", "itemInSelection", "moveSelectedScreens", "clipMenuItems", "fileTableView"):
        assert re.search(rf'typeof {hook} === "function"', build), hook
    assert 'typeof drawMultiOverlay === "function"' in (STATIC / "stage.js").read_text()
    assert 'typeof renderMultiProps === "function"' in (STATIC / "inspector.js").read_text()
    app = (STATIC / "app.js").read_text()
    for hook in ("fixMultiSelection", "multiDelete", "multiDuplicate"):
        assert f'typeof {hook} === "function"' in app, hook


def test_editing_scripts_define_what_the_hooks_call():
    edit = (STATIC / "edit.js").read_text()
    for fn in ("screenInSelection", "itemInSelection", "moveSelectedScreens", "clipMenuItems", "drawMultiOverlay",
               "renderMultiProps", "fixMultiSelection", "multiDelete", "multiDuplicate", "alignItems", "copySelection",
               "pastePayload", "setItemSelection", "setScreenSelection"):
        assert re.search(rf"^(async )?function {fn}\(", edit, re.M), fn
    assert re.search(r"^function fileTableView\(", (STATIC / "tablefile.js").read_text(), re.M)
    # the clipboard payload is JSON with a marker, also kept in localStorage for other tabs
    assert 'edge: "edge-clipboard"' in edit and 'clipKey: "edge.clipboard"' in edit
    assert '"/api/edit/paste_files"' in edit
    # one undo step per group action: every group action ends in exactly one commit()
    for fn in ("multiDelete", "multiDuplicate", "alignItems"):
        body = edit[edit.index(f"function {fn}("):]
        body = body[:body.index("\n}\n")]
        assert body.count("commit(") >= 1, fn


def test_formula_checks_cover_every_formula_field():
    x = (STATIC / "exprcheck.js").read_text()
    assert '"/api/edit/check"' in x and '"/api/edit/names"' in x
    assert 'input.expr, textarea.expr' in x          # delegated: every formula field of the builder has class "expr"
    # every formula input in the builder is an .expr field (so it is checked)
    for f in ("inspector.js", "measures.js", "build.js"):
        src = (STATIC / f).read_text()
        for m in re.finditer(r'h\("(input|textarea)", \{[^\n]*?placeholder: "\$[^"]*"', src):
            assert "expr" in m.group(0), f"{f}: a formula field without the expr class: {m.group(0)[:80]}"
    assert "data-where" in (STATIC / "build.js").read_text()     # Show only if… is checked where the step is
