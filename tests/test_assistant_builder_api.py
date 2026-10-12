"""Every /api/assistant/* endpoint through a real builder server, with a fake model service; plus the small
additive builder endpoints (/api/runs, /api/files?status=1, /api/assets?kind=data, save labels)."""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from assistant_fakes import FakeAnthropic, FakeOllama, make_scenario, xlsx_bytes
from edge.assistant import http as H
from edge.assistant.providers import anthropic as A
from edge.builder.server import BuilderApp, make_handler

FIX = Path(__file__).parent / "fixtures" / "assistant"
KEY = "sk-ant-builder-test-000000000000000-B1LD"
EXP = "stroop_ai/stroop_ai.yaml"
BLANK = {"name": "stroop_ai", "settings": {"window": {"size": [1280, 720], "background": "#000000"}},
         "devices": [], "variables": {}, "routines": {}, "flow": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(H, "RETRY_BASE", 0.01)
    monkeypatch.setattr(A, "DISABLED_FEATURES", set())
    root = tmp_path / "ws"
    (root / "stroop_ai").mkdir(parents=True)
    from edge.storage import save_document
    save_document(root / EXP, BLANK)
    app = BuilderApp(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root, app
    httpd.shutdown()


def call(url, body=None, method=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def setup_claude(base, fake, consent=True):
    code, view = call(base + "/api/assistant/config", {"provider": "anthropic", "anthropic": {
        "base_url": fake.url, "api_key": KEY, "model": "claude-opus-5-5"}})
    assert code == 200, view
    if consent:
        assert call(base + "/api/assistant/consent", {"provider": "anthropic"})[0] == 200
    return view


def attach(base, name, data, exp=EXP):
    q = urllib.parse.urlencode({"exp": exp, "name": name})
    return call(f"{base}/api/assistant/attach?{q}", raw=data, headers={"Content-Type": "application/octet-stream"})


def wait_job(base, jid, until=("done", "incomplete", "failed", "cancelled"), timeout=30):
    since, events = 0, []
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        code, j = call(f"{base}/api/assistant/job?id={jid}&since={since}&wait=5")
        assert code == 200, j
        events += j["events"]
        since = j["next"]
        if j["status"] in until:
            return j, events
    raise AssertionError("the job did not finish")


def test_status_config_test_attach_ask_poll_apply(env):
    base, root, app = env
    fake = FakeAnthropic(make_scenario("anthropic", "stroop"))
    code, st = call(base + "/api/assistant/status")
    assert code == 200 and st["configured"] is False and st["running_jobs"] == 0
    view = setup_claude(base, fake, consent=False)
    assert view["configured"] and view["providers"]["anthropic"]["key_last4"] == "B1LD"
    code, t = call(base + "/api/assistant/test", {"provider": "anthropic"})
    assert code == 200 and t["ok"] and t["capabilities"]["tools"]
    code, t = call(base + "/api/assistant/test", {"provider": "anthropic", "settings": {"model": "claude-gone"}})
    assert t["ok"] is False and t["error"]["code"] == "model_not_found"
    code, m = call(base + "/api/assistant/models?provider=anthropic")
    assert code == 200 and m["models"][0]["id"] == "claude-opus-5-5" and m["error"] is None
    code, a = attach(base, "words.csv", (FIX / "words.csv").read_bytes())
    assert code == 200 and a["attachment"]["file"] == "conditions/words.csv" and a["stored"]["reused"] is False
    assert a["attachment"]["summary"].startswith("words.csv — 9 rows")
    code, pv = call(f"{base}/api/assistant/preview?exp={EXP}&file=conditions/words.csv")
    assert code == 200 and pv["attachment"]["table"]["rows"] == 9
    ask = {"experiment": BLANK, "path": EXP, "message": "Build a Stroop task from this list, 2 repeats",
           "attachments": ["conditions/words.csv"]}
    code, r = call(base + "/api/assistant/ask", ask)
    assert code == 409 and r["code"] == "consent_required" and "privacy" in r and r["provider"] == "anthropic"
    assert call(base + "/api/assistant/consent", {"provider": "anthropic"})[1]["ok"]
    code, r = call(base + "/api/assistant/ask", ask)
    assert code == 200 and r["status"] == "queued" and r["job_id"].startswith("j_") and not r["conversation_reset"]
    job, events = wait_job(base, r["job_id"])
    assert job["status"] == "done", job["error"]
    res = job["result"]
    assert res["valid"] and res["dry_run"]["trials"] == 18 and res["changed"]
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert events[0]["kind"] == "status" and any(e.get("tool") == "dry_run" for e in events)
    assert (root / EXP).read_text().count("routines: {}") == 1            # the server never edits the file
    code, conv = call(f"{base}/api/assistant/conversation?id={r['conversation_id']}")
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and conv["messages"][1]["job_id"] == r["job_id"]
    assert call(base + "/api/assistant/applied", {"id": r["job_id"]}) == (200, {"status": "applied"})
    hist = (root / "stroop_ai/.edge/assistant/history.jsonl").read_text().splitlines()
    line = json.loads(hist[0])
    assert line["request"].startswith("Build a Stroop") and line["changes"] and KEY not in hist[0]
    # a follow-up on the applied document keeps the conversation
    ask2 = {"experiment": res["experiment"], "path": EXP, "message": "make the words bigger",
            "conversation_id": r["conversation_id"]}
    code, r2 = call(base + "/api/assistant/ask", ask2)
    assert code == 200 and r2["conversation_id"] == r["conversation_id"]
    job2, _ = wait_job(base, r2["job_id"])
    assert job2["result"]["experiment"]["routines"]["trial"]["components"][1]["height"] == 120
    assert "Changes since your last turn: none" in json.dumps(fake.chat_requests[-3]["json"]["messages"])
    fake.close()


def test_long_poll_returns_early_on_a_new_event(env):
    base, root, app = env
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("hello"))])
    setup_claude(base, fake)
    fake.delay(0.3)
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "hi"})
    t0 = time.monotonic()
    code, j = call(f"{base}/api/assistant/job?id={r['job_id']}&since=0&wait=10")
    assert code == 200 and j["events"] and time.monotonic() - t0 < 5
    wait_job(base, r["job_id"])
    fake.close()


def test_cancel_mid_stream_removes_the_jobs_files(env):
    base, root, app = env
    data = xlsx_bytes({"info": [["x"], [1]], "trials": [["word"], ["RED"]]}, active=0)
    code, a = attach(base, "words.xlsx", data)

    def slow(req):
        fake.delay(0.4)
        return FakeAnthropic.turn(*[FakeAnthropic.text(f"part {i} ") for i in range(40)])
    doc = json.loads(json.dumps(BLANK))
    doc["routines"]["t"] = {"components": [{"id": "x", "type": "text", "text": "$word", "duration": 1}]}
    doc["flow"] = ["t"]
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("set_conditions_from_file", {
        "loop": "trials", "file": a["attachment"]["file"], "sheet": "trials", "create_loop": {"children": ["t"]}},
        id="s")), slow])
    setup_claude(base, fake)
    code, r = call(base + "/api/assistant/ask", {"experiment": doc, "path": EXP, "message": "use the trials sheet",
                                                 "attachments": [a["attachment"]["file"]]})
    created = root / "stroop_ai/conditions/words-trials.csv"
    t0 = time.monotonic()
    while not created.exists() and time.monotonic() - t0 < 10:
        time.sleep(0.05)
    assert created.exists()
    time.sleep(0.3)
    t0 = time.monotonic()
    code, c = call(base + "/api/assistant/cancel", {"id": r["job_id"]})
    assert code == 200 and c["status"] == "cancelled" and time.monotonic() - t0 < 1.0
    assert not created.exists()
    job, _ = wait_job(base, r["job_id"])
    assert job["status"] == "cancelled" and job["result"] is None
    assert (root / "stroop_ai/conditions/words.xlsx").exists()             # the researcher's attachment stays
    fake.close()


def test_discard_removes_created_files_and_busy_is_409(env):
    base, root, app = env
    data = xlsx_bytes({"info": [["x"], [1]], "trials": [["word"], ["RED"]]}, active=0)
    _, a = attach(base, "w.xlsx", data)
    doc = json.loads(json.dumps(BLANK))
    doc["routines"]["t"] = {"components": [{"id": "x", "type": "text", "text": "$word", "duration": 1}]}
    doc["flow"] = ["t"]
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("set_conditions_from_file", {
        "loop": "trials", "file": "conditions/w.xlsx", "sheet": "trials", "create_loop": {"children": ["t"]}}, id="s")),
        FakeAnthropic.turn(FakeAnthropic.text("Uses the trials sheet."))])
    setup_claude(base, fake)
    code, r = call(base + "/api/assistant/ask", {"experiment": doc, "path": EXP, "message": "x",
                                                 "attachments": ["conditions/w.xlsx"]})
    job, _ = wait_job(base, r["job_id"])
    assert job["result"]["files_created"] == ["conditions/w-trials.csv"]
    assert (root / "stroop_ai/conditions/w-trials.csv").exists()
    code, d = call(base + "/api/assistant/discard", {"id": r["job_id"]})
    assert code == 200 and d["status"] == "discarded" and d["removed_files"] == ["conditions/w-trials.csv"]
    assert not (root / "stroop_ai/conditions/w-trials.csv").exists()
    code, e = call(base + "/api/assistant/applied", {"id": r["job_id"]})
    assert code == 400 and "discarded" in e["error"]
    # busy: one running job per conversation
    fake2 = FakeAnthropic([FakeAnthropic.turn(*[FakeAnthropic.text("slow ") for _ in range(30)])])
    fake2.delay(0.2)
    code, view = call(base + "/api/assistant/config", {"anthropic": {"base_url": fake2.url}})
    # another address: the stored key is removed (it never follows an address change) and must be given again
    assert "api_key_cleared" in view["config_warnings"] and not view["providers"]["anthropic"]["has_key"]
    call(base + "/api/assistant/config", {"anthropic": {"base_url": fake2.url, "api_key": KEY}})
    code, r1 = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "one"})
    code, r2 = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "two",
                                                  "conversation_id": r1["conversation_id"]})
    assert code == 409 and r2["code"] == "busy"
    call(base + "/api/assistant/cancel", {"id": r1["job_id"]})
    fake.close()
    fake2.close()


def test_refusals_and_unknown_ids(env):
    base, root, app = env
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "x"})
    assert code == 400 and r["code"] == "not_configured" and r["hint"]
    assert call(base + "/api/assistant/job?id=j_nope")[0] == 400
    assert call(base + "/api/assistant/cancel", {"id": "j_nope"})[0] == 400
    assert call(base + "/api/assistant/conversation?id=c_nope")[0] == 400
    fake = FakeAnthropic([])
    setup_claude(base, fake)
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "x" * 8001})
    assert code == 400 and r["code"] == "message_too_long"
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "x",
                                                 "attachments": ["conditions/missing.csv"]})
    assert code == 400 and r["code"] == "bad_attachment"
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "message": "x", "attachments": ["a.csv"]})
    assert code == 400 and r["code"] == "needs_folder"
    code, r = call(base + "/api/assistant/config", {"ollama": {"num_ctx": 5}})
    assert code == 400 and r["field"] == "ollama.num_ctx"
    assert call(base + "/api/assistant/status", {"x": 1})[0] == 405
    fake.close()


def test_failed_jobs_report_the_provider_error(env):
    base, root, app = env
    fake = FakeAnthropic(make_scenario("anthropic", "fail"))
    setup_claude(base, fake)
    _, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "x"})
    job, _ = wait_job(base, r["job_id"])
    assert job["status"] == "failed" and job["error"]["code"] == "overloaded" and job["result"] is None
    fake.close()


def test_local_provider_without_consent_and_untitled_documents(env):
    base, root, app = env
    fake = FakeOllama(make_scenario("ollama", "stroop"))
    call(base + "/api/assistant/config", {"provider": "ollama", "ollama": {"base_url": fake.url, "model": "qwen2.5:14b"}})
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "message": "Build a Stroop task"})
    assert code == 200
    job, _ = wait_job(base, r["job_id"])
    assert job["status"] == "done", job["error"]
    loop = job["result"]["experiment"]["flow"][1]
    assert isinstance(loop["conditions"], list) and len(loop["conditions"]) == 9        # inline: no folder yet
    code, t = call(base + "/api/assistant/test", {"provider": "ollama"})
    assert t["ok"] and t["server"] == "Ollama 0.12.3"
    code, m = call(base + "/api/assistant/models?provider=ollama")
    assert m["models"][0]["id"] == "qwen2.5:14b"
    fake.close()


def test_detach_and_suggest_path(env):
    base, root, app = env
    _, a = attach(base, "words.csv", (FIX / "words.csv").read_bytes())
    code, d = call(base + "/api/assistant/detach", {"exp": EXP, "file": "conditions/words.csv"})
    assert code == 200 and d["removed"] and not (root / "stroop_ai/conditions/words.csv").exists()
    assert call(base + "/api/assistant/detach", {"exp": EXP, "file": "conditions/words.csv"})[1]["removed"] is False
    code, s = call(base + "/api/assistant/suggest_path?name=Stroop%20task")
    assert s == {"path": "stroop_task/stroop_task.yaml"}
    (root / "stroop_task").mkdir()
    assert call(base + "/api/assistant/suggest_path?name=Stroop%20task")[1]["path"] == "stroop_task_2/stroop_task_2.yaml"
    assert call(base + "/api/assistant/suggest_path?name=123")[1]["path"] == "exp_123/exp_123.yaml"


# ============================================================================ additive builder endpoints
def test_files_status_assets_data_runs_and_save_labels(env):
    base, root, app = env
    (root / "stroop_ai/data/001_1_x").mkdir(parents=True)
    (root / "stroop_ai/data/001_1_x/session.json").write_text(json.dumps({"experiment": "stroop_ai", "dry_run": False}))
    (root / "stroop_ai/data/dry_runs/t").mkdir(parents=True)
    (root / "stroop_ai/data/dry_runs/t/session.json").write_text(json.dumps({"experiment": "stroop_ai", "dry_run": True}))
    code, f = call(base + "/api/files?status=1")
    row = f["files"][0]
    assert row["path"] == EXP and row["sessions"] == {"real": 1, "test": 1} and row["last_session"] and not row["locked"]
    assert "modified" in row
    assert "sessions" not in call(base + "/api/files")[1]["files"][0]                     # unchanged without status
    attach(base, "words.csv", (FIX / "words.csv").read_bytes())
    (root / "stroop_ai/data/x.csv").write_text("a\n1\n")
    # a custom data folder (settings.data.dir) and any session folder are participant data too
    from edge.storage import save_document
    save_document(root / EXP, {**BLANK, "settings": {**BLANK["settings"], "data": {"dir": "results"}}})
    (root / "stroop_ai/results/P001").mkdir(parents=True)
    (root / "stroop_ai/results/P001/trials.csv").write_text("participant\nP001\n")
    (root / "stroop_ai/old/P002").mkdir(parents=True)
    (root / "stroop_ai/old/P002/trials.csv").write_text("participant\nP002\n")
    (root / "stroop_ai/old/P002/session.json").write_text("{}")
    code, a = call(f"{base}/api/assets?exp={EXP}&kind=data")
    assert code == 200 and a["folder"] == "conditions" and [x["path"] for x in a["assets"]] == ["conditions/words.csv"]
    code, e = call(f"{base}/api/assistant/preview?exp={EXP}&file=results/P001/trials.csv")
    assert code == 400 and e["code"] == "blocked"
    save_document(root / EXP, BLANK)
    assert call(base + "/api/runs")[1] == {"runs": []}
    doc = json.loads(json.dumps(BLANK))
    doc["description"] = "changed"
    code, s = call(f"{base}/api/experiment?path={EXP}&label=" + urllib.parse.quote("assistant: add practice"), doc)
    assert code == 200
    code, b = call(f"{base}/api/backups?path={EXP}")
    assert b["backups"][0]["label"].startswith("assistant") and "add practice" in b["backups"][0]["label"]


# ============================================================================ review findings (regressions)
def _user_texts(req):
    out = []
    for m in req["json"]["messages"]:
        if m["role"] == "user":
            texts = [p.get("text", "") for p in m["content"] if isinstance(p, dict) and p.get("type") == "text"]
            out.append(" ".join(texts))
    return out


def test_stop_before_the_model_answers_never_touches_the_next_request(env):
    """A job stopped while its request still waits for the answer's headers is woken at once; the next request in
    the same conversation starts immediately and the old thread can't change its history (append-only)."""
    base, root, app = env
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("first answer")),
                          FakeAnthropic.turn(FakeAnthropic.text("second answer")),
                          FakeAnthropic.turn(FakeAnthropic.text("third answer"))])
    fake.hold_headers(4.0)                                   # the first request: the model is "loading"
    setup_claude(base, fake)
    code, r1 = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "FIRST"})
    assert code == 200
    time.sleep(0.6)
    t0 = time.monotonic()
    code, c = call(base + "/api/assistant/cancel", {"id": r1["job_id"]})
    assert c["status"] == "cancelled"
    job1 = app.assistant.jobs.get(r1["job_id"])
    job1.thread.join(3)
    assert not job1.thread.is_alive() and time.monotonic() - t0 < 3     # the waiting socket was shut
    code, r2 = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "SECOND",
                                                  "conversation_id": r1["conversation_id"]})
    assert code == 200 and r2["conversation_id"] == r1["conversation_id"]
    j2, _ = wait_job(base, r2["job_id"])
    assert j2["status"] == "done"
    code, r3 = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "THIRD",
                                                  "conversation_id": r1["conversation_id"]})
    j3, _ = wait_job(base, r3["job_id"])
    assert j3["status"] == "done", j3
    msgs = [m for m in fake.chat_requests if m["json"]]
    second, third = msgs[-2], msgs[-1]
    assert not any("FIRST" in t for t in _user_texts(second))         # the stopped turn never reached history
    roles = [m["role"] for m in third["json"]["messages"]]
    assert roles == ["user", "assistant", "user"], roles
    assert "SECOND" in _user_texts(third)[0] and "THIRD" in _user_texts(third)[1]
    assert not fake.rejected
    code, conv = call(f"{base}/api/assistant/conversation?id={r1['conversation_id']}")
    assert [m["text"] for m in conv["messages"] if m["role"] == "assistant"][0] == "Stopped."
    fake.close()


def test_running_jobs_count_a_stopped_job_until_its_thread_ends(env):
    base, root, app = env
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("x"))] * 3)
    setup_claude(base, fake)
    svc_jobs = __import__("edge.assistant.api", fromlist=["service"]).service(app).jobs
    gate = threading.Event()

    class Stuck(threading.Thread):              # a thread that has not noticed Stop yet
        def __init__(self):
            super().__init__(daemon=True)

        def run(self):
            gate.wait(5)
    code, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "one"})
    wait_job(base, r["job_id"])
    job = svc_jobs.get(r["job_id"])
    job.status, job.thread = "cancelled", Stuck()
    job.thread.start()
    assert call(base + "/api/assistant/status")[1]["running_jobs"] == 1
    gate.set()
    job.thread.join(2)
    assert call(base + "/api/assistant/status")[1]["running_jobs"] == 0
    fake.close()


def test_stop_after_the_job_finished_changes_nothing(env):
    base, root, app = env
    data = xlsx_bytes({"info": [["x"], [1]], "trials": [["word"], ["RED"]]}, active=0)
    _, a = attach(base, "late.xlsx", data)
    doc = json.loads(json.dumps(BLANK))
    doc["routines"]["t"] = {"components": [{"id": "x", "type": "text", "text": "$word", "duration": 1}]}
    doc["flow"] = ["t"]
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("set_conditions_from_file", {
        "loop": "trials", "file": "conditions/late.xlsx", "sheet": "trials", "create_loop": {"children": ["t"]}},
        id="s")), FakeAnthropic.turn(FakeAnthropic.text("Uses the trials sheet."))])
    setup_claude(base, fake)
    _, r = call(base + "/api/assistant/ask", {"experiment": doc, "path": EXP, "message": "x",
                                              "attachments": ["conditions/late.xlsx"]})
    job, _ = wait_job(base, r["job_id"])
    made = root / "stroop_ai" / job["result"]["files_created"][0]
    assert job["status"] == "done" and made.exists()
    code, c = call(base + "/api/assistant/cancel", {"id": r["job_id"]})          # Stop pressed just too late
    assert code == 200 and c["status"] == "done" and made.exists()
    assert call(f"{base}/api/assistant/job?id={r['job_id']}")[1]["result"]["experiment"]
    assert call(base + "/api/assistant/applied", {"id": r["job_id"]})[1]["status"] == "applied"
    code, c = call(base + "/api/assistant/cancel", {"id": r["job_id"]})
    assert c["status"] == "applied" and made.exists()
    code, d = call(base + "/api/assistant/discard", {"id": r["job_id"]})       # applied: it's the researcher's now
    assert d == {"status": "applied", "removed_files": []} and made.exists()
    fake.close()


def test_discard_after_stop_reports_discarded(env):
    base, root, app = env
    fake = FakeAnthropic([FakeAnthropic.turn(*[FakeAnthropic.text("slow ") for _ in range(30)])])
    fake.delay(0.2)
    setup_claude(base, fake)
    _, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "one"})
    time.sleep(0.5)
    assert call(base + "/api/assistant/cancel", {"id": r["job_id"]})[1]["status"] == "cancelled"
    code, d = call(base + "/api/assistant/discard", {"id": r["job_id"]})
    assert code == 200 and d["status"] == "discarded"
    fake.close()


def test_redaction_never_rewrites_the_experiment(env):
    """'task-switching-…' contains 'sk-switching-…': it is the researcher's text, not a key."""
    base, root, app = env
    name = "task-switching-replication-2026"
    doc = json.loads(json.dumps(BLANK))
    doc["name"] = name
    doc["routines"]["intro"] = {"components": [
        {"id": "msg", "type": "text", "text": "This is the task-switching-practice-block.", "duration": 1}]}
    doc["flow"] = ["intro"]
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("apply_operations", {"operations": [
        {"op": "update_routine", "rid": "intro", "duration": 2}]}, id="u")),
        FakeAnthropic.turn(FakeAnthropic.text(f"Made the {name} intro longer."))])
    setup_claude(base, fake)
    _, r = call(base + "/api/assistant/ask", {"experiment": doc, "path": EXP, "message": "longer intro"})
    job, _ = wait_job(base, r["job_id"])
    exp = job["result"]["experiment"]
    assert exp["name"] == name and exp["routines"]["intro"]["components"][0]["text"] == \
        "This is the task-switching-practice-block."
    assert name in job["result"]["summary"]["message"]
    code, conv = call(f"{base}/api/assistant/conversation?id={r['conversation_id']}")
    assert name in conv["messages"][-1]["text"]
    fake.close()


def test_malformed_ask_options_and_documents_are_400s_without_a_trace(env):
    base, root, app = env
    fake = FakeAnthropic([])
    setup_claude(base, fake)
    for opts in ({"model": 123}, {"model": "bad model!"}, {"provider": ["anthropic"]}, {"auto_dry_run": "yes"},
                 {"reviewed_code": ["nothex"]}):
        code, e = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "x", "options": opts})
        assert code == 400 and "options." in e["error"] and "trace" not in e, (opts, e)
    for bad in ({**BLANK, "routines": "x"}, {**BLANK, "routines": {"r": "x"}}, {**BLANK, "settings": 3},
                {**BLANK, "devices": {"a": 1}}):
        code, e = call(base + "/api/assistant/ask", {"experiment": bad, "path": EXP, "message": "x"})
        assert code == 400 and "trace" not in e and "experiment" in e["error"], (bad, e)
    assert not fake.chat_requests
    fake.close()


def test_assistant_posts_must_be_json(env):
    base, root, app = env
    req = urllib.request.Request(base + "/api/assistant/config", data=b'{"provider": "ollama"}',
                                 headers={"Content-Type": "text/plain"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 415
    assert call(base + "/api/assistant/status")[1]["provider"] is None


def test_finished_jobs_are_bounded_and_drop_copies(env, monkeypatch):
    base, root, app = env
    from edge.assistant.jobs import JobManager
    monkeypatch.setattr(JobManager, "MAX_FINISHED", 3)
    fake = FakeAnthropic(lambda req: FakeAnthropic.turn(FakeAnthropic.text("ok")))
    setup_claude(base, fake)
    ids = []
    for i in range(5):
        _, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": f"q{i}"})
        wait_job(base, r["job_id"])
        ids.append(r["job_id"])
    jobs = app.assistant.jobs
    assert all(j.request.experiment == {} for j in jobs.jobs.values())        # no copy of the request kept
    call(base + "/api/assistant/applied", {"id": ids[-1]})
    assert jobs.get(ids[-1]).result["experiment"] is None                     # applied: the builder has it
    call(base + "/api/assistant/status")
    _, r = call(base + "/api/assistant/ask", {"experiment": BLANK, "path": EXP, "message": "last"})
    wait_job(base, r["job_id"])
    assert len(jobs.jobs) <= 4 and ids[0] not in jobs.jobs
    code, e = call(f"{base}/api/assistant/job?id={ids[0]}")
    assert code == 400 and "unknown job" in e["error"]
    fake.close()
