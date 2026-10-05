"""Surveys: question model, validation, display logic, data columns, scoring, the questionnaire
library, the component in test runs, the builder endpoints, the wizard and MCP integration."""

import json
import random
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import survey as sv
from edge import survey_library as lib
from edge.engine import run_experiment
from edge.model import Experiment


def _run(doc, tmp_path, seed=1):
    from edge.participant import VirtualParticipant
    exp = Experiment.from_dict(doc, base_dir=tmp_path)
    errors = [str(i) for i in exp.validate() if i.level == "error"]
    assert errors == []
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "data"), log=lambda *a: None,
                       virtual_participant=VirtualParticipant(seed=seed))
    assert not s["errors"]
    rows = [json.loads(line) for line in (Path(s["data_dir"]) / "trials.jsonl").read_text().splitlines()]
    return s, rows


def _survey(questions, **kw):
    return {"name": "s", "routines": {"q": {"components": [
        {"id": "sv", "type": "survey", "end_routine": True, "questions": questions, **kw}]}}, "flow": ["q"]}


# ------------------------------------------------------------------ model
def test_scales_and_options_are_normalized():
    flat, _ = sv.expand([{"id": "a", "type": "likert", "scale": "agree5"},
                         {"id": "b", "type": "single", "options": ["x", {"value": 2, "label": "two"}]},
                         {"id": "c", "type": "nps"}, {"id": "d", "type": "scale", "points": 9}])
    assert flat[0]["options"][0] == {"value": 1, "label": "Strongly disagree"}
    assert flat[1]["options"] == [{"value": "x", "label": "x"}, {"value": 2, "label": "two"}]
    assert [o["value"] for o in flat[2]["options"]] == list(range(11))
    assert len(flat[3]["options"]) == 9


def test_instruments_expand_with_their_scores():
    flat, scores = sv.expand([{"instrument": "gad7"}, {"type": "page_break"}, {"instrument": "tipi"}])
    assert flat[0]["type"] == "matrix" and len(flat[0]["items"]) == 7
    assert "gad7_total" in scores and "tipi_openness" in scores
    assert len(sv.pages(flat)) == 2


@pytest.mark.parametrize("questions, needle", [
    ([{"id": "a", "type": "magic"}], "unknown question type"),
    ([{"type": "single", "text": "x", "options": ["a"]}], "needs an id"),
    ([{"id": "a", "type": "single"}], "needs options"),
    ([{"id": "a", "type": "matrix", "scale": "agree5"}], "needs items"),
    ([{"id": "a", "type": "text"}, {"id": "a", "type": "text"}], "used twice"),
    ([{"id": "a", "type": "text", "show_if": {"b": 1}}, {"id": "b", "type": "text"}], "not an earlier question"),
    ([{"id": "a", "type": "text"}, {"id": "b", "type": "text", "show_if": {"a": {"~": 1}}}], "unknown comparison"),
    ([{"instrument": "bdi2"}], "unknown questionnaire"),
    ([{"id": "a", "type": "likert", "scale": "agree99"}], "unknown scale"),
    ([{"id": "a", "type": "slider", "min": 5, "max": 5}], "max must be larger"),
    ([{"id": "bad id", "type": "text"}], "letters, digits"),
])
def test_validation_explains_problems(questions, needle):
    problems = sv.validate(questions)
    assert any(needle in p for p in problems), problems


def test_survey_problems_show_up_in_experiment_validation(tmp_path):
    exp = Experiment.from_dict(_survey([{"id": "a", "type": "single"}]), base_dir=tmp_path)
    assert any("needs options" in i.message for i in exp.validate() if i.level == "error")
    exp = Experiment.from_dict(_survey([]), base_dir=tmp_path)
    assert any("no questions" in i.message for i in exp.validate())


@pytest.mark.parametrize("cond, answers, expected", [
    ({"g": "Woman"}, {"g": "Woman"}, True),
    ({"g": "Woman"}, {"g": "Man"}, False),
    ({"g": ["A", "B"]}, {"g": "B"}, True),
    ({"age": {">=": 18}}, {"age": 30}, True),
    ({"age": {">=": 18}}, {"age": "12"}, False),
    ({"h": {"contains": "Music"}}, {"h": ["Sport", "Music"]}, True),
    ({"h": {"not_in": ["Music"]}}, {"h": ["Sport"]}, True),
    ({"e": {"answered": True}}, {"e": ""}, False),
    ({"e": {"!=": 0}}, {}, True),
    ({"a": 1, "b": 2}, {"a": 1, "b": 3}, False),
    ({"any": [{"a": 1}, {"b": 2}]}, {"a": 0, "b": 2}, True),
])
def test_display_logic(cond, answers, expected):
    assert sv.condition_holds(cond, answers) is expected


# ------------------------------------------------------------------ data and scoring
def test_process_makes_tidy_columns():
    flat, scores = sv.expand([
        {"id": "g", "type": "single", "options": ["W", "M", "Other"], "other_option": "Other"},
        {"id": "h", "type": "multiple", "options": ["Sport", "Music", "Arts & Crafts"]},
        {"id": "r", "type": "rank", "options": ["a", "b", "c"]},
        {"id": "cs", "type": "constant_sum", "options": ["x", "y"]},
        {"id": "n", "type": "number"},
        {"id": "f", "type": "text", "show_if": {"g": "W"}},
        {"id": "m", "type": "matrix", "scale": "agree5", "items": [{"id": "m1", "text": "a"}, {"id": "m2", "text": "b"}]}])
    out = sv.process(flat, scores, {"g": "Other", "g_other": "agender", "h": ["Sport", "Arts & Crafts"],
                                    "r": ["c", "a", "b"], "cs": {"x": 30, "y": 70}, "n": "7.5", "f": "ignored",
                                    "m1": 5, "m2": "2", "page1_time": 12.3})
    assert out["g"] == "Other" and out["g_other"] == "agender"
    assert out["h"] == "Sport; Arts & Crafts" and out["h_sport"] == 1 and out["h_music"] == 0 and out["h_arts_crafts"] == 1
    assert out["r"] == "c > a > b" and (out["r_a"], out["r_b"], out["r_c"]) == (2, 3, 1)
    assert (out["cs_x"], out["cs_y"]) == (30, 70)
    assert out["n"] == 7.5 and out["f"] is None          # hidden by display logic -> empty
    assert out["m1"] == 5 and out["m2"] == 2 and out["page1_time"] == 12.3


def _score(key, answers):
    flat, scores = sv.expand([{"instrument": key}])
    return sv.compute_scores(flat, scores, answers)


def test_phq9_scoring_bands_and_safety_flag():
    ans = {f"phq9_{i}": 1 for i in range(1, 10)} | {"phq9_9": 0}
    out = _score("phq9", ans)
    assert out["phq9_total"] == 8 and out["phq9_total_band"] == "mild" and out["phq9_item9_flag"] == 0
    out = _score("phq9", ans | {"phq9_9": 2, "phq9_1": 3})
    assert out["phq9_total"] == 12 and out["phq9_total_band"] == "moderate" and out["phq9_item9_flag"] == 1
    out = _score("phq9", {k: v for k, v in ans.items() if k != "phq9_4"})
    assert out["phq9_total"] is None and out["phq9_total_band"] is None   # incomplete -> no total


def test_reverse_scoring_uses_the_scales_range():
    # RSES 0-3: all "Strongly agree" (3) -> positive items 3 each, reversed items 0 each -> 5 x 3 = 15
    assert _score("rses", {f"rses_{i}": 3 for i in range(1, 11)})["rses_total"] == 15
    # TIPI extraversion = mean(item1, 8 - item6)
    assert _score("tipi", {f"tipi_{i}": 7 for i in range(1, 11)} | {"tipi_6": 1})["tipi_extraversion"] == 7
    # SUS: best answers (odd 4, even 0) -> 100; neutral (2) everywhere -> 50
    assert _score("sus", {f"sus_{i}": (4 if i % 2 else 0) for i in range(1, 11)})["sus_score"] == 100
    assert _score("sus", {f"sus_{i}": 2 for i in range(1, 11)})["sus_score"] == 50
    # PSS-10: reversed items 4, 5, 7, 8 on 0-4
    assert _score("pss10", {f"pss10_{i}": 4 for i in range(1, 11)})["pss10_total"] == 24


def test_other_scores():
    assert _score("who5", {f"who5_{i}": 3 for i in range(1, 6)})["who5_percent"] == 60
    assert _score("swls", {f"swls_{i}": 7 for i in range(1, 6)})["swls_total_band"] == "extremely satisfied"
    assert _score("ehi_sf", {f"ehi_{i}": 100 for i in range(1, 5)} | {"ehi_4": 50})["ehi_lq"] == 87.5
    assert _score("audit_c", {"audit_1": 0})["audit_c_total"] == 0          # skipped follow-ups count 0
    assert _score("attention_checks", {"attn1": 1, "attn2": "Red"})["attention_passed"] == 1
    assert _score("nasa_tlx", {f"tlx_{k}": 50 for k in ("mental", "physical", "temporal", "performance",
                                                        "effort", "frustration")})["tlx_raw"] == 50
    ipip = _score("mini_ipip", {f"ipip_{i}": 5 for i in range(1, 21)})
    assert ipip["ipip_extraversion"] == 5 + 5 + 1 + 1 and ipip["ipip_intellect_imagination"] == 5 + 1 + 1 + 1


def test_custom_scores():
    flat, _ = sv.expand([{"id": "m", "type": "matrix", "scale": "agree5",
                          "items": [{"id": "a", "text": "a"}, {"id": "b", "text": "b", "reverse": True}, {"id": "c", "text": "c"}]},
                         {"id": "k", "type": "single", "options": ["x", "y"], "correct": "y"}])
    scores = {"m_mean": {"items": ["a", "b", "c"], "method": "mean", "min_answered": 2},
              "m_sum": {"items": ["a", "b", "c"], "multiply": 2, "add": 1, "bands": [[10, "low"], [100, "high"]]},
              "knows": {"correct": ["k"]}}
    out = sv.compute_scores(flat, scores, {"a": 5, "b": 1, "k": "y"})
    assert out["m_mean"] == 5 and out["m_sum"] is None and out["knows"] == 1
    out = sv.compute_scores(flat, scores, {"a": 1, "b": 5, "c": 1})
    assert out["m_sum"] == 7 and out["m_sum_band"] == "low"


def test_auto_answers_respect_rules():
    flat, _ = sv.expand([
        {"id": "a", "type": "single", "options": ["yes", "no"], "required": True, "test_answer": "no"},
        {"id": "b", "type": "text", "show_if": {"a": "yes"}, "required": True},
        {"id": "m", "type": "multiple", "options": ["1", "2", "3", "4"], "min_choices": 2, "max_choices": 3,
         "exclusive": ["4"], "required": True},
        {"id": "cs", "type": "constant_sum", "options": ["x", "y", "z"], "total": 10, "required": True},
        {"id": "s", "type": "slider", "min": 0, "max": 1, "step": 0.25, "required": True}])
    for seed in range(20):
        ans = sv.auto_answer(flat, random.Random(seed))
        assert ans["a"] == "no" and "b" not in ans
        assert 2 <= len(ans["m"]) <= 3 and "4" not in ans["m"]
        assert sum(ans["cs"].values()) == 10
        assert ans["s"] in (0, 0.25, 0.5, 0.75, 1)


def test_randomization_is_saved_and_reproducible():
    q = [{"id": "o", "type": "single", "options": list("abcdef") + ["Other"], "other_option": "Other", "randomize": True}]
    f1, _ = sv.expand(q, random.Random(3))
    f2, _ = sv.expand(q, random.Random(3))
    assert f1[0]["shown_order"] == f2[0]["shown_order"] and f1[0]["shown_order"][-1] == "Other"
    out = sv.process(f1, {}, {"o": "c"})
    assert out["o_order"].split() == f1[0]["shown_order"]


def test_columns_describe_items_codes_and_scores():
    cols = sv.columns([{"instrument": "phq9"}, {"id": "h", "type": "multiple", "text": "Hobbies?", "options": ["Sport"]}])
    assert "Little interest" in cols["phq9_1"] and "0 = Not at all" in cols["phq9_1"]
    assert cols["phq9_total"].startswith("PHQ-9 total") and "≤4 minimal" in cols["phq9_total_band"]
    assert cols["h_sport"] == "Hobbies? – Sport: 1 if selected" and "page1_time" in cols


def test_page_is_self_contained_and_escapes_script_tags():
    page, flat, scores = sv.render_html({"title": "T", "questions": [
        {"id": "a", "type": "text", "text": "</script><script>alert(1)</script>"}, {"instrument": "kss"}]})
    assert page.count("<script") == 2 and "alert(1)" in page               # the text can't open or close a script block
    assert "edge.submit" in page and "kss" in json.dumps(flat)


# ------------------------------------------------------------------ library integrity
@pytest.mark.parametrize("key", list(lib.INSTRUMENTS))
def test_library_instruments_are_valid_and_cited(key, tmp_path):
    ins = lib.INSTRUMENTS[key]
    assert sv.validate(ins["questions"], ins.get("scores")) == []
    assert ins["citation"] and ins["licence"] and ins["category"] in lib.CATEGORY_ORDER
    flat, scores = sv.expand([{"instrument": key}])
    for name, sc in scores.items():
        out = sv.compute_scores(flat, scores, sv.auto_answer(flat, random.Random(0), attention=1.0))
        assert name in out


def test_item_counts_match_the_published_versions():
    expected = {"phq9": 10, "gad7": 7, "k6": 6, "pss10": 10, "who5": 5, "swls": 5, "rses": 10, "tipi": 10,
                "mini_ipip": 20, "ehi_sf": 4, "nasa_tlx": 6, "sus": 10, "audit_c": 3, "kss": 1}
    for key, n in expected.items():
        assert sv.count_items(lib.INSTRUMENTS[key]["questions"]) == n, key


# ------------------------------------------------------------------ in an experiment
def test_survey_in_a_test_run_saves_answers_scores_and_dictionary(tmp_path):
    from edge.export import SessionTables, data_dictionary, session_tables, summarize
    doc = _survey([{"instrument": "demographics"}, {"type": "page_break"}, {"instrument": "phq9"},
                   {"id": "hob", "type": "multiple", "text": "Hobbies", "options": ["Sport", "Music"]}],
                  title="About you")
    s, rows = _run(doc, tmp_path)
    r = rows[0]
    assert r["sv.submitted"] == 1 and isinstance(r["sv.age"], int) and r["sv.phq9_total_band"]
    assert "sv.hob_sport" in r and r["sv.page2_time"] > 0
    st = SessionTables(s["data_dir"])
    tables = session_tables(st)
    cols, trows = tables["dictionary"]
    desc = {d["column"]: d["description"] for d in trows}
    assert "How old are you" in desc["sv.age"] and "PHQ-9 total" in desc["sv.phq9_total"]
    _, _, info = summarize(st)
    assert info.get("rt") in (None, "") or "sv" not in str(info.get("rt"))     # page times aren't RTs


def test_survey_inside_a_loop_rates_each_stimulus(tmp_path):
    doc = {"name": "rate", "routines": {"rate": {"components": [
        {"id": "rating", "type": "survey", "end_routine": True, "questions": [
            {"id": "liking", "type": "scale", "points": 7, "required": True, "text": "How much do you like {{word}}?"}]}]}},
        "flow": [{"loop": "trials", "conditions": [{"word": "apple"}, {"word": "pear"}], "children": ["rate"]}]}
    s, rows = _run(doc, tmp_path)
    assert [r["word"] for r in rows] == ["apple", "pear"] and all(1 <= r["rating.liking"] <= 7 for r in rows)


def test_question_text_with_dollar_is_not_an_expression(tmp_path):
    s, rows = _run(_survey([{"id": "pay", "type": "single", "text": "$5 or $10?", "options": ["$5", "$10"]}]), tmp_path)
    assert rows[0]["sv.pay"] in ("$5", "$10", None)


def test_template_with_consent_workflow_runs_the_whole_study(tmp_path):
    from edge.templates import write_template
    exp = Experiment.load(write_template("online_questionnaire", tmp_path))
    assert [i for i in exp.validate() if i.level in ("error", "warning")] == []
    s = run_experiment(exp, dry_run=True, data_dir=str(tmp_path / "d"), log=lambda *a: None)
    rows = [json.loads(line) for line in (Path(s["data_dir"]) / "trials.jsonl").read_text().splitlines()]
    assert [r["routine"] for r in rows] == ["consent", "survey", "goodbye"]
    assert rows[1]["survey.swls_total"] is not None and "survey.priorities" in rows[1]


def test_wizard_adds_questionnaires_around_the_task(tmp_path):
    from edge.wizard import build_experiment, estimate
    doc = build_experiment({"questionnaires": ["consent", "demographics", "gad7", "sus"]})
    assert doc["flow"][:2] == ["consent", "about_you"] and doc["flow"][-2:] == ["questionnaires", "thanks"]
    assert estimate(doc, tmp_path)["minutes"] >= 4
    from edge.wizard import WizardError
    with pytest.raises(WizardError, match="unknown questionnaire"):
        build_experiment({"questionnaires": ["bdi2"]})
    _run(doc, tmp_path)


# ------------------------------------------------------------------ builder and MCP
def test_builder_survey_endpoints(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(tmp_path)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    try:
        with urllib.request.urlopen(url + "/api/schema") as r:
            schema = json.loads(r.read())["survey"]
        assert "matrix" in schema["question_types"] and "agree7" in schema["scales"]
        assert any(i["id"] == "phq9" and i["items"] == 10 for i in schema["library"])
        r = post("/api/survey/render", {"spec": {"questions": [{"instrument": "who5"}]}})
        assert r["problems"] == [] and "who5_1" in r["html"] and "window.edge=" in r["html"]
        r = post("/api/survey/render", {"spec": {"questions": [{"id": "x", "type": "single"}]}})
        assert r["problems"] and "needs options" in r["problems"][0]
        assert post("/api/survey/instrument", {"id": "gad7"})["scores"]["gad7_total"]
    finally:
        httpd.shutdown()


def test_mcp_add_survey(tmp_path):
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    from tests.test_mcp import call
    server = create_server(tmp_path)
    call(server, "create_experiment", path="study.yaml", template="blank")
    lib_info = call(server, "survey_library")
    assert "phq9" in {q["id"] for q in lib_info["questionnaires"]} and "rank" in lib_info["question_types"]
    r = call(server, "add_survey", path="study.yaml", questions=[{"instrument": "consent"}], routine="consent",
             position="start")
    assert r["ok"]
    r = call(server, "add_survey", path="study.yaml", questions=[{"instrument": "phq9"}, {"instrument": "gad7"}],
             title="After the task")
    assert r["ok"] and not [i for i in r.get("issues", []) if i["level"] == "error"]
    exp = Experiment.load(tmp_path / "study.yaml")
    assert [n.routine for n in exp.flow] == ["consent", "hello", "questionnaire"]
    dry = call(server, "dry_run", path="study.yaml")
    assert dry["ok"] and "questionnaire.gad7_total" in dry["columns"]


# ------------------------------------------------------------------ the full question catalogue
ALL_TYPES = [
    {"type": "text_block", "text": "<b>Hello</b>", "media": "shelf.png", "caption": "a shelf"},
    {"id": "lb", "type": "multiple", "text": "Listbox", "options": ["p", "q"], "layout": "listbox"},
    {"id": "mx", "type": "matrix", "multi": True, "text": "Days", "options": ["Mon", "Tue"], "items": ["Gym", "Run"]},
    {"id": "md", "type": "matrix", "display": "dropdown", "scale": "agree5", "text": "Dropdown matrix", "items": ["One"]},
    {"id": "ns", "type": "scale", "points": 5, "text": "Rate", "items": ["Price", "Taste"]},
    {"id": "nps", "type": "nps", "text": "Recommend?"},
    {"id": "sl", "type": "slider", "items": ["Fun", "Hard"], "min": 0, "max": 10, "text": "Sliders"},
    {"id": "gs", "type": "graphic_slider", "style": "stars", "points": 5, "text": "Stars"},
    {"id": "pw", "type": "text", "secret": True, "text": "Password"},
    {"id": "ac", "type": "autocomplete", "list": "countries", "text": "Country"},
    {"id": "dt", "type": "calendar", "min": "2020-01-01", "text": "Date"},
    {"id": "ff", "type": "form", "text": "Contact", "fields": [{"id": "name", "label": "Name"}, {"id": "mail", "type": "email"}]},
    {"id": "rk", "type": "rank", "method": "select", "options": ["a", "b"], "text": "Rank"},
    {"id": "sbs", "type": "side_by_side", "text": "Brands", "items": [{"id": "b1", "text": "Brand 1"}],
     "columns": [{"id": "aware", "label": "Aware?", "options": ["Yes", "No"]}, {"id": "q", "label": "Quality", "type": "dropdown", "scale": "quality5"},
                 {"id": "note", "label": "Note", "type": "text"}]},
    {"id": "cs", "type": "constant_sum", "options": ["x", "y"], "total": 100, "must_total": "at_most", "unit": "%", "text": "Split"},
    {"id": "grp", "type": "group", "items": ["apple", "carrot"], "groups": ["Fruit", "Vegetable"], "rank_within": True, "text": "Sort"},
    {"id": "hs", "type": "hot_spot", "image": "shelf.png", "mode": "rate", "text": "Spots",
     "regions": [{"id": "left", "x": 0, "y": 0, "w": 50, "h": 100}, {"id": "right", "x": 50, "y": 0, "w": 50, "h": 100}]},
    {"id": "hm", "type": "heat_map", "image": "shelf.png", "max_clicks": 2, "regions": [{"id": "top", "x": 0, "y": 0, "w": 100, "h": 50}], "text": "Heat"},
    {"id": "loc", "type": "location", "image": "shelf.png", "bounds": {"north": 60, "south": 40, "west": -10, "east": 30}, "text": "Where"},
    {"id": "dr", "type": "drill_down", "levels": ["Country", "City"], "rows": [["France", "Paris"], ["France", "Lyon"], ["Japan", "Tokyo"]], "text": "Place"},
    {"id": "hl", "type": "highlight", "passage": "The food was great but the service was slow", "text": "Highlight"},
    {"id": "sig", "type": "signature", "required": True, "text": "Sign"},
    {"id": "fu", "type": "file_upload", "required": True, "text": "Upload"},
    {"id": "cap", "type": "captcha", "text": "Code"},
    {"id": "tt", "type": "tree_test", "task": "Find returns", "text": "Tree",
     "rows": [["Shop", "Phones"], ["Help", "Returns"], ["Help", "Shipping"]], "correct": "Help > Returns"},
    {"id": "tm", "type": "timing", "min_seconds": 1},
    {"id": "mi", "type": "meta_info"},
    {"id": "vr", "type": "video_response", "audio_only": True, "required": True, "text": "Video"},
    {"id": "sc", "type": "screen_capture", "required": True, "text": "Screen"},
]


def _png(path):
    import struct
    import zlib
    raw = b"\x00\xff\xff\xff" * 1

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
                     chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_every_question_type_validates_and_round_trips(tmp_path):
    assert sv.validate(ALL_TYPES) == []
    assert set(sv.QUESTION_TYPES) >= {"form", "side_by_side", "group", "hot_spot", "heat_map", "graphic_slider", "drill_down",
                                       "highlight", "signature", "timing", "meta_info", "file_upload", "captcha", "autocomplete",
                                       "tree_test", "video_response", "screen_capture", "location"}
    _png(tmp_path / "shelf.png")
    s, rows = _run(_survey([dict(q, required=True) if "id" in q else q for q in ALL_TYPES]), tmp_path)
    r = {k[3:]: v for k, v in rows[0].items() if k.startswith("sv.")}
    assert r["lb_p"] in (0, 1) and r["mx_1_mon"] in (0, 1) and isinstance(r["md_1"], int)
    assert r["nps_group"] in ("promoter", "passive", "detractor") and 0 <= r["sl_2"] <= 10 and 1 <= r["gs"] <= 5
    assert r["ac"] in __import__("edge.survey_lists", fromlist=["x"]).COUNTRIES and r["dt"] == "2020-01-01"
    assert r["mail"] == "virtual.participant@example.org"
    assert r["b1_aware"] in ("Yes", "No") and 1 <= r["b1_q"] <= 5 and r["b1_note"]
    assert r["grp_apple"] in ("fruit", "vegetable", None) and r["hs_left"] in (-1, 0, 1)
    assert r["hm_clicks"] == 2 and 40 <= r["loc_lat"] <= 60 and r["dr_country"] in ("France", "Japan")
    assert r["sig_signed"] == 1 and r["sig"].startswith("survey_files/") and (Path(s["data_dir"]) / r["sig"]).exists()
    assert r["fu_name"] == "test_run.txt" and (Path(s["data_dir"]) / r["fu"]).read_text().startswith("Test run")
    assert r["cap_passed"] == 1 and r["tt"] and r["tt_correct"] in (0, 1) and r["tm_clicks"] >= 1
    assert r["mi_browser"] == "virtual participant" and r["vr_duration"] == 5 and r["sc"].endswith(".png")
    cols = sv.columns(ALL_TYPES)
    for c in ("hm_top", "loc_lat", "dr_city", "hl_like", "tt_direct", "tm_first_click", "mi_timezone", "grp_apple_rank", "b1_q"):
        assert c in cols, c


def test_new_type_validation_messages():
    cases = [
        ([{"id": "a", "type": "hot_spot", "image": "x.png", "regions": [{"x": 0, "y": 0, "w": 150, "h": 10}]}], "between 0 and 100"),
        ([{"id": "a", "type": "heat_map"}], "needs an image"),
        ([{"id": "a", "type": "tree_test", "tree": {"A": ["B"]}, "correct": "A > C"}], "not in the tree"),
        ([{"id": "a", "type": "form", "fields": [{"id": "x", "type": "colour"}]}], "type must be one of"),
        ([{"id": "a", "type": "side_by_side", "items": ["r"], "columns": [{"id": "c", "type": "single"}]}], "needs options"),
        ([{"id": "a", "type": "group", "items": ["x"]}], "needs items (to sort) and groups"),
        ([{"id": "a", "type": "location"}], "map image or allow_geolocation"),
        ([{"id": "a", "type": "highlight"}], "needs a passage"),
        ([{"id": "a", "type": "autocomplete", "list": "planets"}], "unknown list"),
        ([{"id": "a", "type": "rank", "options": ["x"], "method": "dice"}], "method must be"),
    ]
    for qs, needle in cases:
        assert any(needle in p for p in sv.validate(qs)), (needle, sv.validate(qs))


def test_missing_images_are_reported(tmp_path):
    exp = Experiment.from_dict(_survey([{"id": "h", "type": "heat_map", "image": "nope.png"}]), base_dir=tmp_path)
    assert any("file not found: nope.png" in i.message for i in exp.validate())


def test_tree_test_directness_and_success():
    flat, _ = sv.expand([{"id": "t", "type": "tree_test", "tree": {"Shop": {"Phones": [], "Help": {"Returns": []}}},
                          "correct": "Shop > Help > Returns"}])
    direct = sv.process(flat, {}, {"t": {"path": ["Shop", "Help", "Returns"], "visited": ["Shop", "Shop > Help", "Shop > Help > Returns"],
                                         "clicks": 3, "time": 4.2}})
    assert direct["t_correct"] == 1 and direct["t_direct"] == 1
    lost = sv.process(flat, {}, {"t": {"path": ["Shop", "Help", "Returns"], "visited": ["Shop", "Shop > Phones", "Shop > Help", "Shop > Help > Returns"]}})
    assert lost["t_correct"] == 1 and lost["t_direct"] == 0


def test_drill_down_rows_and_files(tmp_path):
    assert sv.rows_to_tree([["A", "x", "1"], ["A", "x", "2"], ["B", "y", "3"]]) == {"A": {"x": ["1", "2"]}, "B": {"y": ["3"]}}
    (tmp_path / "places.csv").write_text("Country,City\nFrance,Paris\nJapan,Tokyo\n")
    from edge.components.survey import load_drill_files
    qs = load_drill_files([{"id": "d", "type": "drill_down", "file": "places.csv"}], tmp_path)
    flat, _ = sv.expand(qs)
    assert flat[0]["levels"] == ["Country", "City"] and flat[0]["tree"] == {"France": ["Paris"], "Japan": ["Tokyo"]}


def test_extract_files_writes_and_replaces(tmp_path):
    import base64
    flat, _ = sv.expand([{"id": "up", "type": "file_upload"}, {"id": "sig", "type": "signature"}])
    data = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 test").decode()
    raw = sv.extract_files(flat, {"up": {"name": "cv.pdf", "size": 13, "data": data}, "sig": sv.PNG_1PX}, tmp_path / "survey_files", "p1_")
    assert raw["up"]["path"] == "survey_files/p1_up.pdf" and (tmp_path / "survey_files" / "p1_up.pdf").read_bytes().startswith(b"%PDF")
    assert raw["sig"]["path"] == "survey_files/p1_sig.png" and "data" not in raw["sig"]
    out = sv.process(flat, {}, raw)
    assert out["up_name"] == "cv.pdf" and out["sig_signed"] == 1


# ------------------------------------------------------------------ right to left
def test_rtl_direction_language_and_messages():
    he, _, _ = sv.render_html({"title": "שאלון", "questions": [{"id": "a", "type": "text", "text": "מה שמך?"}]})
    assert "dir='rtl'" in he and "lang='he'" in he and "נא לענות על שאלה זו." in he
    ar, _, _ = sv.render_html({"language": "ar", "questions": [{"id": "a", "type": "text", "text": "Name?"}]})
    assert "dir='rtl'" in ar and "يرجى الإجابة" in ar
    forced, _, _ = sv.render_html({"direction": "rtl", "language": "en", "questions": [{"id": "a", "type": "text", "text": "x"}]})
    assert "dir='rtl'" in forced and "Please answer" in forced
    de, _, _ = sv.render_html({"language": "de", "labels": {"submit": "Fertig"}, "questions": [{"id": "a", "type": "text", "text": "x"}]})
    assert "dir='ltr'" in de and "Bitte beantworten" in de and "Fertig" in de
    en, _, _ = sv.render_html({"questions": [{"id": "a", "type": "text", "text": "Hello"}]})
    assert "dir='ltr'" in en


def test_translations_cover_every_message():
    from edge import survey_i18n as i18n
    for lang, table in i18n.MESSAGES.items():
        missing = set(i18n.EN) - set(table)
        assert not missing, (lang, missing)
        for k, v in table.items():   # placeholders survive translation
            for ph in ("{n}", "{total}", "{mb}", "{name}", "{s}", "{d}", "{lat}", "{lon}"):
                assert (ph in v) == (ph in i18n.EN[k]), (lang, k, ph)
    import re
    js = (Path(sv.__file__).parent / "survey_page" / "survey.js").read_text()
    used = set(re.findall(r"\bT\.([a-z_]+)", js))
    assert used <= set(i18n.EN), used - set(i18n.EN)


def test_bidi_helpers():
    from edge import bidi
    assert bidi.has_rtl("שלום") and not bidi.has_rtl("hello")
    assert bidi.is_rtl_language("he-IL") and not bidi.is_rtl_language("de")
    assert bidi.guess_language("مرحبا") == "ar" and bidi.guess_language("سلام، چطوری؟") == "fa" and bidi.guess_language("שלום") == "he"
    assert bidi.visual("plain text") == "plain text"
    if bidi.available():
        assert bidi.visual("שלום world") == "world םולש"
        assert bidi.visual("مرحبا") != "مرحبا"          # letters joined into contextual forms


def test_text_component_has_a_direction():
    from edge.components import component_registry
    assert component_registry()["text"].props_schema["direction"]["choices"] == ["auto", "ltr", "rtl"]


def test_bundles_include_survey_media():
    from edge.storage import referenced_files
    doc = _survey([{"id": "h", "type": "heat_map", "image": "images/a.png"}, {"type": "text_block", "media": "clip.mp4"},
                   {"id": "d", "type": "drill_down", "levels": ["Country"], "file": "places.csv"},
                   {"id": "w", "type": "hot_spot", "image": "https://example.org/x.png", "regions": [{"x": 0, "y": 0, "w": 1, "h": 1}]}])
    assert referenced_files(doc) >= {"images/a.png", "clip.mp4", "places.csv"} and not any("example.org" in f for f in referenced_files(doc))
