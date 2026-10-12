"""Attachments: storing (safe names, folders, dedup, encoding), previews for every type, table reading
(equal to what the experiment will load), and the frame that keeps file content from acting as instructions."""

from __future__ import annotations

import builtins
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from assistant_fakes import (bmp_bytes, gif_bytes, jpeg_bytes, png_bytes, svg_bytes, wav_bytes, webp_bytes,
                             xlsx_bytes)
from edge.assistant.attachments import (AttachmentError, AttachmentRegistry, preview, read_table, render_for_model,
                                        sanitize_name, store_attachment)
from edge.conditions import load_conditions

FIX = Path(__file__).parent / "fixtures" / "assistant"
EXP = "study/study.yaml"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "study").mkdir()
    return tmp_path


def attach(root, name, data=None):
    data = data if data is not None else (FIX / name).read_bytes()
    st = store_attachment(root, EXP, name, data)
    return st, preview(root, EXP, st.exp_path)


# ============================================================================ storing
def test_csv_preview_types_uniques_identifiers_first_rows(root):
    st, p = attach(root, "words.csv")
    assert st.exp_path == "conditions/words.csv" and st.path == "study/conditions/words.csv" and not st.reused
    t = p["table"]
    assert p["kind"] == "table" and t["rows"] == 9 and t["source"] == "csv" and t["delimiter"] == ","
    cols = {c["name"]: c for c in t["columns"]}
    assert cols["word"]["type"] == "text" and cols["word"]["unique"] == 3 and cols["word"]["identifier"]
    assert cols["congruent"]["type"] == "int" and cols["congruent"]["examples"] == [1, 0]
    assert t["first_rows"][0] == {"word": "RED", "ink": "red", "congruent": 1, "correct_key": "r"}
    assert t["loadable_as_is"] and t["needs_conversion"] is None
    assert p["summary"] == "words.csv — 9 rows × 4 columns: word, ink, congruent, correct_key"
    assert any("Factor-like" in n for n in t["notes"])


def test_tsv_and_tabular_txt_and_plain_txt(root):
    st, p = attach(root, "list.tsv", b"word\tink\nRED\tred\nBLUE\tblue\n")
    assert p["table"]["delimiter"] == "\t" and p["table"]["rows"] == 2 and st.exp_path == "conditions/list.tsv"
    st, p = attach(root, "elist.txt")
    assert st.exp_path == "conditions/elist.txt" and p["kind"] == "table" and p["table"]["rows"] == 3
    assert p["table"]["columns"][3]["files"] is True and p["table"]["missing_files"] == ["cat.png", "dog.png", "bird.png"]
    st, p = attach(root, "story.txt", b"Once upon a time.\n\nThe end.\n")
    assert st.exp_path == "materials/story.txt" and p["kind"] == "text" and p["text"]["lines"] == 4
    assert p["text"]["looks_like_instructions"]


def test_semicolons_and_decimal_commas_are_noted(root):
    _, p = attach(root, "semicolon_decimal_comma.csv")
    t = p["table"]
    assert t["delimiter"] == ";" and [c["name"] for c in t["columns"]] == ["stim", "contrast", "soa"]
    assert any("decimal commas" in n for n in t["notes"])


def test_cp1252_tables_become_utf8(root):
    st, p = attach(root, "words_cp1252.csv")
    assert st.converted == "cp1252 → UTF-8"
    text = (root / st.path).read_text(encoding="utf-8")
    assert "CAFÉ" in text and "ÉTÉ" in text
    assert load_conditions(st.exp_path, root / "study")[3]["word"] == "CAFÉ"


def test_bad_headers_need_a_converted_copy(root):
    _, p = attach(root, "bad_headers.csv")
    t = p["table"]
    assert not t["loadable_as_is"] and "names" in t["needs_conversion"]
    assert [c["identifier"] for c in t["columns"]] == [True, False, False, False]
    assert any("Correct Key" in n for n in t["notes"])


def test_markdown_json_rows_nested_and_yaml(root):
    st, p = attach(root, "notes.md")
    assert st.exp_path == "materials/notes.md" and p["kind"] == "text"
    st, p = attach(root, "rows.json")
    assert st.exp_path == "conditions/rows.json" and p["kind"] == "table" and p["table"]["rows"] == 3
    assert p["table"]["loadable_as_is"]
    st, p = attach(root, "nested.json")
    assert st.exp_path == "materials/nested.json" and p["kind"] == "json"
    cands = {c["json_path"]: c for c in p["json"]["row_candidates"]}
    assert cands["blocks[0].trials"]["rows"] == 2 and cands["blocks[0].trials"]["columns"] == ["word", "ink"]
    assert "blocks: array[2]" in p["json"]["structure"]
    t = read_table(root / "study" / st.exp_path, json_path="blocks[1].trials")
    assert t.rows == [{"word": "GREEN", "ink": "blue"}]
    st, p = attach(root, "rows.yaml")
    assert p["kind"] == "table" and p["table"]["source"] == "yaml" and p["table"]["rows"] == 2


def test_html_form_scripts_missing_refs_and_tables(root):
    st, p = attach(root, "consent.html")
    h = p["html"]
    assert st.exp_path == "pages/consent.html" and p["kind"] == "html"
    assert h["title"] == "Consent form" and h["headings"] == ["Informed consent", "Your rights"]
    fields = {f["name"]: f for f in h["forms"][0]["fields"]}
    assert fields["email"]["required"] and fields["email"]["type"] == "email"
    assert fields["age"]["min"] == "18" and fields["agree"]["options"] == ["yes", "no"]
    assert fields["hand"]["options"] == ["left", "right"]
    assert h["has_submit"] and h["scripts"] == {"inline": 1, "external": []}
    assert sorted(h["missing_refs"]) == ["consent.css", "logo.png"]
    assert "ignore previous instructions" not in h["text_excerpt"]          # script contents are never shown
    assert p["summary"].startswith("consent.html — form: email, age, agree")
    _, p = attach(root, "jspsych.html")
    assert p["html"]["looks_like_jspsych"] and any("File → Import" in w for w in p["warnings"])
    _, p = attach(root, "table.html")
    assert [t["columns"] for t in p["html"]["tables"]] == [["Word", "Ink Colour"], ["a", "b"]]
    t = read_table(root / "study/pages/table.html", table_index=0)
    assert t.rows == [{"Word": "RED", "Ink Colour": "red"}, {"Word": "BLUE", "Ink Colour": "green"}]


def test_xlsx_with_openpyxl_active_sheet_not_first(root):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "info"
    ws.append(["note", "x"])
    ws2 = wb.create_sheet("trials")
    ws2.append(["word", "ink", "congruent", "rt_ok"])
    for r in [("RED", "red", 1, True), ("GREEN", "red", 0, False), ("BLUE", "blue", 1, True)]:
        ws2.append(r)
    wb.active = 1
    buf = io.BytesIO()
    wb.save(buf)
    st, p = attach(root, "words.xlsx", buf.getvalue())
    t = p["table"]
    assert st.exp_path == "conditions/words.xlsx" and t["source"] == "xlsx" and t["sheet"] == "trials"
    assert t["sheets"] == [{"name": "info", "rows": 0, "active": False}, {"name": "trials", "rows": 3, "active": True}]
    assert t["rows"] == 3 and t["loadable_as_is"]
    path = root / "study" / st.exp_path
    assert read_table(path).rows == load_conditions(st.exp_path, root / "study")
    other = read_table(path, sheet="info")
    assert other.columns == ["note", "x"]


def test_xlsx_without_openpyxl(root, monkeypatch):
    data = xlsx_bytes({"Sheet1": [["word", "n"], ["RED", 1], ["BLUE", 2]], "Practice": [["word"], ["X"]]}, active=0)
    real_import = builtins.__import__

    def no_openpyxl(name, *a, **k):
        if name == "openpyxl":
            raise ImportError("no openpyxl here")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_openpyxl)
    st, p = attach(root, "list.xlsx", data)
    t = p["table"]
    assert t["rows"] == 2 and [c["name"] for c in t["columns"]] == ["word", "n"]
    assert not t["loadable_as_is"] and "openpyxl" in t["needs_conversion"]
    assert read_table(root / "study" / st.exp_path, sheet="Practice").rows == [{"word": "X"}]


def test_xlsx_zip_bomb_and_doctype_are_refused(root, monkeypatch):
    from edge.assistant import attachments as A
    monkeypatch.setattr(A, "XLSX_MAX_TOTAL", 200_000)           # the real limit is 200 MB unpacked
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", b"\0" * 300_000)     # compresses to almost nothing
    st = store_attachment(root, EXP, "bomb.xlsx", buf.getvalue())
    with pytest.raises(ValueError, match="too big"):
        read_table(root / "study" / st.exp_path)
    assert any("couldn't read" in w for w in preview(root, EXP, st.exp_path)["warnings"])
    data = xlsx_bytes({"S": [["a"], [1]]}, doctype=True)
    st = store_attachment(root, EXP, "doctype.xlsx", data)
    with pytest.raises(ValueError, match="DOCTYPE"):
        read_table(root / "study" / st.exp_path)


@pytest.mark.parametrize("name, data, size", [
    ("a.png", png_bytes(40, 30), (40, 30)), ("a.gif", gif_bytes(20, 10), (20, 10)), ("a.bmp", bmp_bytes(16, 8), (16, 8)),
    ("a.jpg", jpeg_bytes(64, 48), (64, 48)), ("a.webp", webp_bytes(200, 100), (200, 100)),
    ("a.svg", svg_bytes(300, 150), (300, 150)),
])
def test_image_sizes(root, name, data, size):
    st, p = attach(root, name, data)
    assert st.exp_path == f"images/{name}" and p["kind"] == "image"
    assert (p["image"]["width"], p["image"]["height"]) == size
    vision = p["image"]["vision"]
    assert vision == ("sent" if name.endswith((".png", ".jpg", ".gif", ".webp")) else "metadata_only")


def test_animated_pictures_and_sounds(root):
    _, p = attach(root, "anim.gif", gif_bytes(frames=3))
    assert p["image"]["animated"]
    _, p = attach(root, "anim.webp", webp_bytes(animated=True))
    assert p["image"]["animated"]
    st, p = attach(root, "beep.wav", wav_bytes(0.5, 8000))
    assert st.exp_path == "sounds/beep.wav" and p["audio"]["seconds"] == 0.5 and p["audio"]["rate"] == 8000
    _, p = attach(root, "song.mp3", b"ID3\x03\x00" + b"\x00" * 200)
    assert any("WAV" in w for w in p["warnings"])


@pytest.mark.parametrize("name, code", [
    ("old.xls", "unsupported_type"), ("macro.xlsm", "unsupported_type"), ("paper.docx", "unsupported_type"),
    ("paper.pdf", "unsupported_type"), ("evil.py", "blocked"), ("run.bat", "blocked"), ("x.exe", "blocked"),
    (".hidden.csv", "blocked"), ("data.xyz", "unsupported_type"), ("noext", "unsupported_type"),
])
def test_refused_types(root, name, code):
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, EXP, name, b"word\nRED\n")
    assert e.value.code == code and e.value.message
    if name.endswith(".docx"):
        assert "save it as .txt" in e.value.message


@pytest.mark.parametrize("name, data", [("photo.png", b"<html><body>hi</body></html>"), ("t.csv", b"PK\x03\x04zip"),
                                        ("w.xlsx", b"word,ink\n"), ("s.wav", b"not a wave"),
                                        ("b.json", b"{not json"), ("x.csv", b"\x00\x01\x02binary")])
def test_content_must_match_the_extension(root, name, data):
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, EXP, name, data)
    assert e.value.code == "content_mismatch"


def test_names_are_sanitized_and_never_overwrite(root):
    assert sanitize_name("../../x.csv") == "x.csv" and sanitize_name("..\\..\\y.csv") == "y.csv"
    assert sanitize_name("CON.csv") == "_CON.csv" and sanitize_name("my list (v2).csv") == "my_list__v2_.csv"
    assert sanitize_name("Liste_é.csv") == "Liste_é.csv"
    assert len(sanitize_name("a" * 300 + ".csv")) <= 100 and sanitize_name("a" * 300 + ".csv").endswith(".csv")
    st = store_attachment(root, EXP, "../../x.csv", b"a\n1\n")
    assert st.path == "study/conditions/x.csv" and (root / "study/conditions/x.csv").exists()
    again = store_attachment(root, EXP, "x.csv", b"a\n1\n")
    assert again.reused and again.path == st.path
    other = store_attachment(root, EXP, "x.csv", b"a\n2\n")
    assert other.exp_path == "conditions/x_2.csv" and (root / "study/conditions/x.csv").read_text() == "a\n1\n"


def test_never_under_data_or_outside(root):
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, "study/data/x.yaml", "a.csv", b"a\n1\n")
    assert e.value.code == "blocked"
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, "../outside/x.yaml", "a.csv", b"a\n1\n")
    assert e.value.code == "blocked"
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, None, "a.csv", b"a\n1\n")
    assert e.value.code == "needs_folder"
    with pytest.raises(AttachmentError) as e:
        preview(root, EXP, "data/001/trials.csv")
    assert e.value.code == "blocked"


def test_size_limits(root, monkeypatch):
    from edge.assistant import attachments as A
    monkeypatch.setitem(A.LIMITS, "table", 10)
    with pytest.raises(AttachmentError) as e:
        store_attachment(root, EXP, "big.csv", b"a\n" + b"1\n" * 20)
    assert e.value.code == "too_large"


def test_detach_only_removes_unsent_unchanged_uploads(root):
    reg = AttachmentRegistry()
    st = store_attachment(root, EXP, "a.csv", b"a\n1\n")
    reg.add(st)
    assert reg.detach(root, EXP, "conditions/a.csv") and not (root / st.path).exists()
    st = store_attachment(root, EXP, "b.csv", b"b\n1\n")
    reg.add(st)
    reg.mark_sent([st.path])
    assert not reg.detach(root, EXP, "conditions/b.csv") and (root / st.path).exists()
    (root / "study/conditions/c.csv").write_text("not ours\n")
    assert not reg.detach(root, EXP, "conditions/c.csv")


def test_rendering_escapes_and_frames_file_content(root):
    st, p = attach(root, "notes.md")
    r = render_for_model(p, budget_chars=3000)
    assert r.startswith('<attachment file="materials/notes.md" kind="text" note="data from the researcher')
    assert r.count("</attachment>") == 1 and r.endswith("</attachment>")
    assert "&lt;/attachment&gt;" in r and "&lt;request&gt;" in r
    big = "<b>" + "x" * 10000
    st = store_attachment(root, EXP, "big.txt", big.encode())
    r = render_for_model(preview(root, EXP, st.exp_path), budget_chars=1200)
    assert len(r) < 1500 and "read_attachment" in r and "<b>" not in r


@pytest.mark.parametrize("name", ["words.csv", "rows.json", "rows.yaml"])
def test_read_table_equals_load_conditions(root, name):
    st = store_attachment(root, EXP, name, (FIX / name).read_bytes())
    assert read_table(root / "study" / st.exp_path).rows == load_conditions(st.exp_path, root / "study")


def test_read_table_tsv_equals_load_conditions(root):
    st = store_attachment(root, EXP, "x.tsv", b"a\tb\n1\t2.5\nyes\t\n")
    assert read_table(root / "study" / st.exp_path).rows == load_conditions(st.exp_path, root / "study")


# ============================================================================ review findings (regressions)
def test_two_chips_for_the_same_file_keep_it_until_the_last_is_removed(root):
    reg = AttachmentRegistry()
    st1 = store_attachment(root, EXP, "twice.csv", b"a\n1\n")
    reg.add(st1)
    st2 = store_attachment(root, EXP, "twice.csv", b"a\n1\n")
    assert st2.reused and st2.path == st1.path
    reg.add(st2)
    assert not reg.detach(root, EXP, "conditions/twice.csv") and (root / st1.path).exists()   # chip 1 still uses it
    assert reg.detach(root, EXP, "conditions/twice.csv") and not (root / st1.path).exists()


def test_participant_data_in_a_custom_data_folder_is_never_previewed(root):
    from edge.storage import save_document
    save_document(root / EXP, {"name": "study", "settings": {"data": {"dir": "results"}}, "routines": {}, "flow": []})
    sess = root / "study/results/P042_1_study"
    sess.mkdir(parents=True)
    (sess / "trials.csv").write_text("participant,resp.rt\nP042,0.4\n")
    (sess / "session.json").write_text("{}")
    for f in ("results/P042_1_study/trials.csv", "results/P042_1_study/session.json"):
        with pytest.raises(AttachmentError) as e:
            preview(root, EXP, f)
        assert e.value.code in ("blocked", "unsupported_type")
    # a session folder anywhere (even one EDGE didn't name in data.dir) is participant data
    other = root / "study/old_sessions/P001"
    other.mkdir(parents=True)
    (other / "trials.csv").write_text("participant\nP001\n")
    (other / "trials.jsonl").write_text("{}\n")
    with pytest.raises(AttachmentError):
        preview(root, EXP, "old_sessions/P001/trials.csv")


def test_pictures_are_sent_with_the_type_their_bytes_have(root):
    from edge.assistant.attachments import VISION_MAX_BYTES, image_part
    (root / "study/images").mkdir()
    (root / "study/images/stim.png").write_bytes(jpeg_bytes())          # a JPEG saved as .png
    part = image_part(root / "study/images/stim.png")
    assert part is not None and part.media_type == "image/jpeg"
    (root / "study/images/fake.png").write_bytes(b"not a picture at all" * 10)
    assert image_part(root / "study/images/fake.png") is None
    p = preview(root, EXP, "images/fake.png")
    assert p["image"]["vision"] == "metadata_only"
    assert VISION_MAX_BYTES * 4 / 3 <= 5 * 1024 * 1024                  # base64 stays under the API's 5 MB
