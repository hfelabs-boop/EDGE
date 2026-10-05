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
