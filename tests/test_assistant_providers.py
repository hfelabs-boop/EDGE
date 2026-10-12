"""The four model services against scripted fakes: request shapes, streaming, tool calls, degradation, and
every error turned into a code with a hint."""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from assistant_fakes import FakeAnthropic, FakeLMStudio, FakeOllama, FakeOpenAI, closed_port, png_bytes
from edge.assistant import http as H
from edge.assistant.errors import AssistantError
from edge.assistant.providers import anthropic as A
from edge.assistant.providers.anthropic import AnthropicProvider
from edge.assistant.providers.base import ImagePart, ToolResult, ToolSpec
from edge.assistant.providers.lmstudio import LMStudioProvider
from edge.assistant.providers.ollama import _SHOW_CACHE, OllamaProvider
from edge.assistant.providers.openai_compat import OpenAICompatProvider

KEY = "sk-ant-test-key-abcdefghijklmnop-K3Y9"
TOOLS = [ToolSpec("validate", "Check the experiment.", {"type": "object", "properties": {}}),
         ToolSpec("read_attachment", "Read a file.", {"type": "object", "properties": {"file": {"type": "string"}},
                                                      "required": ["file"]})]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(H, "RETRY_BASE", 0.01)
    monkeypatch.setattr(A, "DISABLED_FEATURES", set())
    _SHOW_CACHE.clear()
    yield


def hdr(req, name):
    return {k.lower(): v for k, v in req["headers"].items()}.get(name.lower())


def events():
    out = []
    return out, out.append


def claude(fake, **kw):
    s = {"base_url": fake.url, "model": kw.pop("model", "claude-opus-5-5"), "effort": "high", "progress_notes": True,
         "fallbacks": True}
    return AnthropicProvider(s, key=kw.pop("key", KEY), **kw)


def transcript(p, tools=TOOLS):
    tr = p.new_transcript("You are a test.", tools)
    p.add_user(tr, "Hello", [])
    return tr


# ============================================================================ Anthropic
def test_anthropic_request_shape_and_stream():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("I'll check."), FakeAnthropic.tool("validate", {}, id="t1"))])
    p = claude(fake)
    tr = transcript(p)
    evs, on = events()
    turn = p.complete(tr, on_event=on, cancel=threading.Event())
    req = fake.chat_requests[0]
    body = req["json"]
    assert hdr(req, "x-api-key") == KEY and hdr(req, "anthropic-version") == "2023-06-01"
    assert hdr(req, "anthropic-beta") == "thinking-display-updates-2026-08-18"
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 64000 and body["stream"] is True
    assert body["thinking"] == {"type": "adaptive", "display": "updates"}
    assert body["output_config"] == {"effort": "high"}
    for banned in ("temperature", "top_p", "top_k", "tool_choice", "fallbacks"):
        assert banned not in body
    assert body["system"] == [{"type": "text", "text": "You are a test.", "cache_control": {"type": "ephemeral"}}]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert all("eager_input_streaming" not in t for t in body["tools"])         # not the official API
    assert turn.stop == "tool_use" and turn.tool_calls[0].name == "validate" and turn.tool_calls[0].input == {}
    assert turn.text == "I'll check." and turn.usage["cache_read_input_tokens"] == 900
    assert tr.native[-1]["role"] == "assistant"
    fake.close()


def test_official_api_features_per_model():
    p = AnthropicProvider({"base_url": "https://api.anthropic.com", "model": "claude-opus-5-5"}, key=KEY)
    tr = transcript(p)
    body, betas = p.body(tr, "claude-opus-5-5")
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in betas
    assert all(t["eager_input_streaming"] is True for t in body["tools"])
    body, betas = p.body(tr, "claude-haiku-5-5")
    assert "fallbacks" not in body and "server-side-fallback-2026-07-01" not in betas
    assert body["thinking"] == {"type": "adaptive"}                    # no progress notes on Haiku
    body, _ = p.body(tr, "claude-haiku-4-5")
    assert "thinking" not in body and "output_config" not in body
    body, _ = p.body(tr, "claude-sonnet-4-6", effort="xhigh")
    assert body["output_config"] == {"effort": "high"}                 # xhigh arrived with 4.7
    body, _ = p.body(tr, "claude-opus-7-0")                            # unknown future id: the newest traits
    assert body["thinking"]["type"] == "adaptive" and body["fallbacks"] == "default"
    off = AnthropicProvider({"base_url": "https://api.anthropic.com", "model": "claude-opus-5-5", "fallbacks": False,
                             "progress_notes": False}, key=KEY)
    body, betas = off.body(tr, "claude-opus-5-5")
    assert "fallbacks" not in body and betas == [] and body["thinking"] == {"type": "adaptive"}


def test_eager_streaming_reassembles_split_input():
    big = {"file": "conditions/words.csv"}
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("read_attachment", big, id="t1"))])
    p = claude(fake, force_eager=True)
    turn = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert all(t["eager_input_streaming"] for t in fake.chat_requests[0]["json"]["tools"])
    assert turn.tool_calls[0].input == big and turn.tool_calls[0].raw_input == json.dumps(big)
    fake.close()


def test_invalid_tool_json_is_reported_not_run():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("read_attachment", {}, id="t1", raw='{"file": "a.csv'))])
    p = claude(fake)
    turn = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    c = turn.tool_calls[0]
    assert c.parse_error and c.input is None and c.raw_input == '{"file": "a.csv'
    fake.close()


def test_thinking_blocks_echoed_unchanged_and_results_together():
    fake = FakeAnthropic([
        FakeAnthropic.turn(FakeAnthropic.thinking("sig-XYZ-123", "Checking both"), FakeAnthropic.tool("validate", {}, id="a"),
                           FakeAnthropic.tool("read_attachment", {"file": "x.csv"}, id="b")),
        FakeAnthropic.turn(FakeAnthropic.text("Done."))])
    p = claude(fake)
    tr = transcript(p)
    evs, on = events()
    turn = p.complete(tr, on_event=on, cancel=threading.Event())
    assert turn.notes == ["Checking both"] and any(e["kind"] == "note" for e in evs)
    p.add_tool_results(tr, [ToolResult("a", "validate", '{"valid": true}'),
                            ToolResult("b", "read_attachment", '{"error": "x"}', is_error=True,
                                       images=[ImagePart("image/png", base64.b64encode(png_bytes()).decode(),
                                                         "p.png")])])
    p.complete(tr, on_event=lambda e: None, cancel=threading.Event())
    msgs = fake.chat_requests[1]["json"]["messages"]
    assert msgs[1]["content"][0] == {"type": "thinking", "thinking": "Checking both", "signature": "sig-XYZ-123"}
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"] and results[1]["is_error"] is True
    assert results[1]["content"][1]["type"] == "image"
    from assistant_fakes import assert_append_only
    assert_append_only(fake.requests)
    fake.close()


def test_fallback_echo_rule():
    fake = FakeAnthropic([FakeAnthropic.turn(
        FakeAnthropic.thinking("sig-1"), FakeAnthropic.text("Partial "), FakeAnthropic.tool("validate", {}, id="before"),
        FakeAnthropic.fallback_block("claude-opus-5-5", "claude-opus-5"), FakeAnthropic.text("continued"),
        FakeAnthropic.tool("read_attachment", {"file": "a.csv"}, id="after"), model="claude-opus-5")])
    p = claude(fake)
    tr = transcript(p)
    turn = p.complete(tr, on_event=lambda e: None, cancel=threading.Event())
    assert [c.id for c in turn.tool_calls] == ["after"] and turn.model == "claude-opus-5"
    types = [b["type"] for b in tr.native[-1]["content"]]
    assert types == ["text", "fallback", "text", "tool_use"]
    fake.close()


def test_refusal_and_max_tokens_stops():
    fake = FakeAnthropic([FakeAnthropic.turn(stop="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                          "explanation": "no"}),
                          FakeAnthropic.turn(FakeAnthropic.tool("validate", {}, id="t"), stop="max_tokens")])
    p = claude(fake)
    t1 = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert t1.stop == "refusal" and t1.refusal == {"category": "cyber", "explanation": "no"}
    t2 = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert t2.stop == "max_tokens" and t2.tool_calls
    fake.close()


def test_overloaded_mid_stream_is_retried_once_from_scratch():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("a"), FakeAnthropic.text("b"), error_event="overloaded_error"),
                          FakeAnthropic.turn(FakeAnthropic.text("fine"))])
    p = claude(fake)
    tr = transcript(p)
    turn = p.complete(tr, on_event=lambda e: None, cancel=threading.Event())
    assert turn.text == "fine" and len(tr.native) == 2 and len(fake.chat_requests) == 2
    fake.close()


def test_degrade_once_on_a_beta_header_400():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    fake.fail_next(400, {"type": "error", "error": {"type": "invalid_request_error", "message":
                                                    "Unexpected value(s) `thinking-display-updates-2026-08-18` for the "
                                                    "`anthropic-beta` header"}})
    p = claude(fake)
    evs, on = events()
    turn = p.complete(transcript(p), on_event=on, cancel=threading.Event())
    assert turn.text == "ok" and "updates" in A.DISABLED_FEATURES
    assert "display" not in fake.chat_requests[0]["json"]["thinking"]
    assert hdr(fake.chat_requests[0], "anthropic-beta") is None
    assert any("progress notes" in e["text"] for e in evs)
    fake.close()


def test_anthropic_models_and_test():
    fake = FakeAnthropic([])
    p = claude(fake)
    models = p.list_models()
    assert [m.id for m in models][:4] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
    assert models[0].recommended and models[0].vision and models[0].note == "Best results (default)"
    assert not models[4].recommended
    res = p.test()
    assert res.ok and res.capabilities["tools"] and res.capabilities["vision"] and res.latency_ms is not None
    assert claude(fake, model="claude-nonexistent").test().error["code"] == "model_not_found"
    bad = claude(fake, key="sk-ant-wrong-key-000000000000")
    fake.api_key = KEY
    err = bad.test().error
    assert err["code"] == "bad_key" and "sk-ant-" in err["hint"]
    fake.close()


def test_anthropic_deep_test_uses_a_tool():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.tool("ping", {}, id="p"))])
    assert claude(fake).test(deep=True).ok
    assert fake.chat_requests[0]["json"]["output_config"] == {"effort": "low"}
    fake.close()


# ============================================================================ errors
@pytest.mark.parametrize("status, body, headers, code", [
    (401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, {}, "bad_key"),
    (402, {"type": "error", "error": {"type": "billing_error", "message": "credit"}}, {}, "billing"),
    (403, {"type": "error", "error": {"type": "permission_error", "message": "no"}}, {}, "forbidden"),
    (404, {"type": "error", "error": {"type": "not_found_error", "message": "model: x"}}, {}, "model_not_found"),
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "prompt is too long: 1200000 tokens"}},
     {}, "context_too_long"),
    (413, {"type": "error", "error": {"type": "request_too_large", "message": "too large"}}, {}, "context_too_long"),
    (429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, {"retry-after": "120"},
     "rate_limited"),
    (500, {"type": "error", "error": {"type": "api_error", "message": "boom"}}, {}, "service_error"),
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to "
           "access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}, {}, "billing"),
    (404, {"type": "error", "error": {"type": "not_found_error", "message": "Not Found"}}, {}, "wrong_address"),
    (418, {"type": "error", "error": {"type": "invalid_request_error", "message": "teapot"}}, {}, "provider_error"),
])
def test_anthropic_error_codes(status, body, headers, code):
    fake = FakeAnthropic([])
    fake.fail_next(status, body, headers, times=5)
    p = claude(fake)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == code and e.value.hint is not None
    if code == "rate_limited":
        assert len(fake.requests) == 1 and e.value.retry_after == 120          # no retry when told to wait long
    fake.close()


def test_retry_after_one_second_is_retried_then_succeeds():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    fake.fail_next(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "x"}}, {"retry-after": "0.05"})
    evs, on = events()
    p = claude(fake)
    assert p.complete(transcript(p), on_event=on, cancel=threading.Event()).text == "ok"
    assert any(e["kind"] == "retry" for e in evs)
    fake.close()


def test_overloaded_three_times():
    fake = FakeAnthropic([])
    fake.fail_next(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, times=3)
    p = claude(fake)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "overloaded" and len(fake.requests) == 3
    fake.close()


def test_slow_server_times_out():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("late"))])
    fake.delay(1.0)
    p = claude(fake, options={"timeout_s": 0.3})
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "timeout"
    fake.close()


def test_redirects_are_errors_and_the_key_is_not_forwarded():
    target = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("stolen"))])

    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", target.url + "/v1/messages")
            self.send_header("Content-Length", "0")
            self.end_headers()
        do_GET = do_POST
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    p = AnthropicProvider({"base_url": f"http://127.0.0.1:{httpd.server_address[1]}", "model": "claude-opus-5-5"}, key=KEY)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "redirected" and target.requests == []
    httpd.shutdown()
    target.close()


def test_provider_errors_echoing_the_key_are_redacted():
    fake = FakeAnthropic([])
    fake.fail_next(400, {"type": "error", "error": {"type": "invalid_request_error",
                                                    "message": f"something about {KEY} went wrong"}})
    p = claude(fake)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert KEY not in json.dumps(e.value.to_dict()) and "K3Y9" in json.dumps(e.value.to_dict())
    fake.close()


def test_local_server_not_running():
    port = closed_port()
    for prov, hint in ((OllamaProvider({"base_url": f"http://127.0.0.1:{port}", "model": "qwen2.5:14b"}), "ollama serve"),
                       (LMStudioProvider({"base_url": f"http://127.0.0.1:{port}/v1", "model": "m"}), "lms server start")):
        res = prov.test()
        assert not res.ok and res.error["code"] == "server_not_running" and hint in res.error["hint"]
    cloud = AnthropicProvider({"base_url": f"http://127.0.0.1:{port}", "model": "claude-opus-5-5"}, key=KEY)
    assert cloud.test().error["code"] == "connection_failed"


# ============================================================================ OpenAI-compatible
def gpt(fake, **kw):
    return OpenAICompatProvider({"preset": "custom", "base_url": fake.url + "/v1", "model": kw.pop("model", "gpt-5.1")},
                                key=kw.pop("key", "sk-test-0000000000000000000000"), **kw)


def test_openai_stream_tool_calls_assembled_by_index():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("Checking."), FakeOpenAI.tool("validate", {}, id="c1"),
                                       FakeOpenAI.tool("read_attachment", {"file": "conditions/words.csv"}, id="c2"))])
    p = gpt(fake)
    tr = transcript(p)
    turn = p.complete(tr, on_event=lambda e: None, cancel=threading.Event())
    body = fake.chat_requests[0]["json"]
    assert body["stream"] and body["stream_options"] == {"include_usage": True} and body["tool_choice"] == "auto"
    assert body["messages"][0] == {"role": "system", "content": "You are a test."}
    assert body["max_tokens"] == 16384 and "max_completion_tokens" not in body and "temperature" not in body
    assert body["tools"][1]["function"]["name"] == "read_attachment"
    assert [c.id for c in turn.tool_calls] == ["c1", "c2"] and turn.tool_calls[1].input == {"file": "conditions/words.csv"}
    assert turn.stop == "tool_use" and turn.text == "Checking." and turn.usage["input_tokens"] == 1500
    assert tr.native[-1]["tool_calls"][1]["function"]["arguments"] == json.dumps({"file": "conditions/words.csv"})
    assert hdr(fake.chat_requests[0], "authorization").startswith("Bearer sk-test")
    fake.close()


def test_openai_degrades_stream_options_and_streaming():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("ok"))], reject_stream_options=True)
    p = gpt(fake)
    assert p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event()).text == "ok"
    assert "stream_options" not in fake.chat_requests[-1]["json"] and fake.chat_requests[-1]["json"]["stream"]
    fake.close()
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.tool("validate", {}, id="c1"))])
    fake.fail_next(400, {"error": {"message": "streaming is not supported with tools for this model"}})
    p = gpt(fake)
    turn = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert turn.tool_calls[0].name == "validate" and fake.chat_requests[-1]["json"]["stream"] is False
    fake.close()


def test_max_completion_tokens_switch():
    official = OpenAICompatProvider({"preset": "openai", "model": "gpt-5.1"}, key="sk-x" * 5)
    assert "max_completion_tokens" in official.body(transcript(official), "gpt-5.1", True)
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("ok"))], reject_max_completion_tokens=True)
    p = gpt(fake)
    p.max_param = "max_completion_tokens"
    assert p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event()).text == "ok"
    assert "max_tokens" in fake.chat_requests[-1]["json"]
    fake.close()


def test_openai_images_and_image_tool_results():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("ok"))])
    p = gpt(fake)
    tr = p.new_transcript("sys", TOOLS)
    p.add_user(tr, "look", [ImagePart("image/png", "QUJD", "a.png")])
    assert tr.native[0]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}
    p.add_tool_results(tr, [ToolResult("c1", "read_attachment", "{}", images=[ImagePart("image/png", "QUJD", "a.png")])])
    assert tr.native[1]["role"] == "tool" and "image follows" in tr.native[1]["content"]
    assert tr.native[2]["role"] == "user" and tr.native[2]["content"][1]["type"] == "image_url"
    fake.close()


def test_openai_vision_rejected_strips_images():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("ok"))])
    fake.fail_next(400, {"error": {"message": "This model does not support image input"}})
    p = gpt(fake)
    tr = p.new_transcript("sys", TOOLS)
    p.add_user(tr, "look", [ImagePart("image/png", "QUJD", "a.png")])
    evs, on = events()
    assert p.complete(tr, on_event=on, cancel=threading.Event()).text == "ok"
    sent = json.dumps(fake.chat_requests[-1]["json"])
    assert "image_url" not in sent and "metadata only" in sent and "vision" in p.disabled
    fake.close()


def test_openai_models_test_and_headers():
    fake = FakeOpenAI([])
    p = gpt(fake)
    assert [m.id for m in p.list_models()] == ["gpt-5.1", "gpt-5.1-mini"]          # embeddings / whisper hidden
    res = p.test()
    assert res.ok and res.models == 4 and not res.warnings
    res = gpt(fake, model="gpt-unknown").test()
    assert res.ok and "not in the service's list" in res.warnings[0]
    fake.api_key = "sk-right-000000000000000000000000"
    assert gpt(fake).test().error["code"] == "bad_key"
    router = OpenAICompatProvider({"preset": "openrouter", "model": "x/y"}, key="sk-or-123456789012345678")
    assert router.base_url == "https://openrouter.ai/api/v1" and router.headers()["X-Title"] == "EDGE experiment builder"
    assert "HTTP-Referer" in router.headers()
    fake.close()


@pytest.mark.parametrize("message, code", [
    ({"error": {"message": "This model's maximum context length is 8192 tokens", "code": "context_length_exceeded"}},
     "context_too_long"),
    ({"error": {"message": "You exceeded your current quota", "type": "insufficient_quota"}}, "billing"),
    ({"error": {"message": "This model does not support tools"}}, "tools_unsupported"),
])
def test_openai_error_codes(message, code):
    fake = FakeOpenAI([])
    fake.fail_next(400 if code != "billing" else 429, message, times=4)
    p = gpt(fake)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == code
    fake.close()


# ============================================================================ Ollama
def llama(fake, model="qwen2.5:14b", **s):
    return OllamaProvider({"base_url": fake.url, "model": model, "num_ctx": s.pop("num_ctx", 16384), **s})


def test_ollama_ndjson_tool_calls_without_ids_and_num_ctx():
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("ok "), FakeOllama.tool("validate", {}),
                                       FakeOllama.tool("read_attachment", {"file": "a.csv"}), thinking="short thought")])
    p = llama(fake)
    tr = transcript(p)
    evs, on = events()
    turn = p.complete(tr, on_event=on, cancel=threading.Event())
    body = fake.chat_requests[0]["json"]
    assert body["options"] == {"num_ctx": 16384, "temperature": 0.2} and body["keep_alive"] == "15m"
    assert body["stream"] is True and body["tools"][0]["function"]["name"] == "validate"
    assert [c.name for c in turn.tool_calls] == ["validate", "read_attachment"]
    assert all(c.id.startswith("call_") for c in turn.tool_calls) and len({c.id for c in turn.tool_calls}) == 2
    assert turn.notes == ["short thought"]
    assert tr.native[-1]["tool_calls"][1] == {"function": {"name": "read_attachment", "arguments": {"file": "a.csv"}}}
    p.add_tool_results(tr, [ToolResult(c.id, c.name, "{}") for c in turn.tool_calls])
    assert tr.native[-1] == {"role": "tool", "content": "{}", "tool_name": "read_attachment"}
    fake.close()


def test_ollama_num_ctx_clamped_and_over_budget_refused():
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("ok"))],
                      models={"small:7b": {"tools": True, "context": 8192, "size": "7B"}})
    p = llama(fake, model="small:7b", num_ctx=32768)
    assert p.capabilities("small:7b").context_tokens == 8192
    tr = p.new_transcript("x" * 40000, TOOLS)                       # ~11 000 tokens for an 8192 context
    p.add_user(tr, "hi", [])
    with pytest.raises(AssistantError) as e:
        p.complete(tr, on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "context_too_long" and "Context" in e.value.hint and fake.chat_requests == []
    fake.close()


def test_ollama_truncation_warning():
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("ok"), prompt_eval_count=100)],
                      models={"m:14b": {"tools": True, "context": 8192, "size": "14B"}})
    p = llama(fake, model="m:14b", num_ctx=8192)
    tr = p.new_transcript("y" * 24500, [])                          # ~7000 tokens: above 80 % of 8192
    p.add_user(tr, "hi", [])
    evs, on = events()
    p.complete(tr, on_event=on, cancel=threading.Event())
    assert any("cut the request short" in e["text"] for e in evs)
    fake.close()


def test_ollama_images_without_data_prefix_and_capabilities():
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("ok"))],
                      models={"llava:13b": {"tools": False, "vision": True, "context": 4096, "size": "13B"}})
    p = llama(fake, model="llava:13b")
    caps = p.capabilities("llava:13b")
    assert caps.vision is True and caps.tools is False and caps.context_tokens == 4096
    tr = p.new_transcript("s", [])
    p.add_user(tr, "look", [ImagePart("image/png", "QUJD", "a.png")])
    assert tr.native[0]["images"] == ["QUJD"]
    fake.close()


def test_ollama_models_test_and_errors():
    fake = FakeOllama([])
    p = llama(fake)
    models = p.list_models()
    assert models[0].id == "qwen2.5:14b" and models[0].recommended and models[0].tools
    small = next(m for m in models if m.id == "llama3.2:3b")
    assert "14B+" in small.note and "(3.2B, Q4_K_M)" in small.label
    assert not next(m for m in models if m.id == "gemma2:9b").recommended
    res = p.test()
    assert res.ok and res.server == "Ollama 0.12.3" and res.models == 3 and res.capabilities["mode"] == "tools"
    res = llama(fake, model="mistral:7b").test()
    assert res.error["code"] == "model_not_pulled" and "ollama pull mistral:7b" in res.error["hint"]
    res = llama(fake, model="gemma2:9b").test()
    assert res.ok and res.capabilities["mode"] == "json" and any("JSON" in w for w in res.warnings)
    with pytest.raises(AssistantError) as e:
        llama(fake, model="gemma2:9b").complete(transcript(llama(fake, model="gemma2:9b")), on_event=lambda e: None,
                                                cancel=threading.Event())
    assert e.value.code == "tools_unsupported"
    with pytest.raises(AssistantError) as e:
        llama(fake, model="nothere:1b").complete(transcript(llama(fake)), on_event=lambda e: None,
                                                 cancel=threading.Event())
    assert e.value.code == "model_not_pulled"
    fake.close()


# ============================================================================ LM Studio
def test_lmstudio_probe_and_errors():
    fake = FakeLMStudio([FakeLMStudio.turn(FakeLMStudio.text("ok"))])
    p = LMStudioProvider({"base_url": fake.url + "/v1", "model": "qwen2.5-14b-instruct"})
    models = p.list_models()
    assert [m.id for m in models] == ["qwen2.5-14b-instruct", "llava-v1.6"]          # loaded first, no embeddings
    assert models[0].recommended and models[1].vision is True and models[0].context == 16384
    assert p.capabilities("llava-v1.6").vision is True
    res = p.test()
    assert res.ok and res.server == "LM Studio" and res.capabilities["context_tokens"] == 16384
    turn = p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    body = fake.chat_requests[0]["json"]
    assert turn.text == "ok" and body["temperature"] == 0.2 and "authorization" not in {k.lower() for k in fake.chat_requests[0]["headers"]}
    fake.close()
    fake = FakeLMStudio([], v0=False)
    p = LMStudioProvider({"base_url": fake.url + "/v1", "model": "qwen2.5-14b-instruct"})
    assert p.test().ok and p.capabilities("qwen2.5-14b-instruct").vision is None          # 404 probe ignored
    fake.close()
    fake = FakeLMStudio([], no_model_loaded=True)
    p = LMStudioProvider({"base_url": fake.url + "/v1", "model": "qwen2.5-14b-instruct"})
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "no_model_loaded" and "lms load" in e.value.hint
    fake.close()
    fake = FakeLMStudio([], models=[{"id": "x", "type": "llm", "state": "not-loaded"}])
    assert LMStudioProvider({"base_url": fake.url + "/v1", "model": "x"}).test().error["code"] == "no_model_loaded"
    p = LMStudioProvider({"base_url": fake.url + "/v1", "model": "x"})
    p.probe()
    fake.fail_next(400, {"error": {"message": "Trying to keep the first 9000 tokens when context the overflows. "
                                              "Try to load the model with a larger context length"}})
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "context_too_long" and "LM Studio" in e.value.hint
    fake.close()


def test_cancel_wakes_a_blocked_stream():
    fake = FakeAnthropic([FakeAnthropic.turn(*[FakeAnthropic.text(f"chunk {i}") for i in range(30)])])
    fake.delay(0.3)
    p = claude(fake)
    cancel = H.CancelEvent()
    threading.Timer(0.5, cancel.set).start()
    import time
    t0 = time.monotonic()
    with pytest.raises(H.Cancelled):
        p.complete(transcript(p), on_event=lambda e: None, cancel=cancel)
    assert time.monotonic() - t0 < 2.0
    fake.close()


def test_png_helper_is_a_real_png():
    assert png_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ============================================================================ review findings (regressions)
def test_cancel_wakes_a_request_still_waiting_for_the_headers():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("late"))])
    fake.hold_headers(5.0)                                     # the model is "loading"
    p = claude(fake)
    cancel = H.CancelEvent()
    threading.Timer(0.4, cancel.set).start()
    import time
    t0 = time.monotonic()
    with pytest.raises(H.Cancelled):
        p.complete(transcript(p), on_event=lambda e: None, cancel=cancel)
    assert time.monotonic() - t0 < 2.0
    llama_fake = FakeOllama([])
    llama_fake.hold_headers(5.0)
    o = llama(llama_fake)
    cancel = H.CancelEvent()
    threading.Timer(0.4, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(H.Cancelled):
        o.complete(transcript(o, tools=[]), on_event=lambda e: None, cancel=cancel)
    assert time.monotonic() - t0 < 2.0
    fake.close()
    llama_fake.close()


def test_connecting_is_bounded(monkeypatch):
    monkeypatch.setattr(H, "CONNECT_TIMEOUT", 0.3)
    import socket
    import time
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(0)                                   # nobody accepts: later connections wait in the backlog
    fillers = []
    for _ in range(8):
        s = socket.socket()
        s.setblocking(False)
        try:
            s.connect(srv.getsockname())
        except BlockingIOError:
            pass
        fillers.append(s)
    t0 = time.monotonic()
    with pytest.raises(H.HttpFailure):
        H.request_json("GET", f"http://127.0.0.1:{srv.getsockname()[1]}/x", timeout=60, local=True)
    assert time.monotonic() - t0 < 10
    for s in fillers:
        s.close()
    srv.close()


@pytest.mark.parametrize("provider, given, expected", [
    ("anthropic", "https://api.anthropic.com/v1", "https://api.anthropic.com"),
    ("anthropic", "https://api.anthropic.com/v1/messages/", "https://api.anthropic.com"),
    ("ollama", "http://localhost:11434/v1", "http://localhost:11434"),
    ("ollama", "http://localhost:11434/api", "http://localhost:11434"),
    ("ollama", "http://localhost:11434/api/chat", "http://localhost:11434"),
    ("lmstudio", "http://localhost:1234", "http://localhost:1234/v1"),
    ("lmstudio", "http://localhost:1234/v1/chat/completions", "http://localhost:1234/v1"),
    ("openai", "https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1"),
    ("openai", "https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1"),
])
def test_base_urls_are_normalized(provider, given, expected):
    from edge.assistant.config import check_base_url, normalize_base_url
    assert normalize_base_url(given, provider) == expected
    assert check_base_url(given, provider, "f") == expected


def test_a_pasted_v1_still_works_and_counts_as_official():
    assert AnthropicProvider({"base_url": "https://api.anthropic.com/v1", "model": "claude-opus-5-5"}, key=KEY).official
    fake = FakeOllama([FakeOllama.turn(FakeOllama.text("hi"))])
    p = OllamaProvider({"base_url": fake.url + "/v1", "model": "qwen2.5:14b"})
    assert p.test().ok and p.complete(transcript(p, tools=[]), on_event=lambda e: None,
                                      cancel=threading.Event()).text == "hi"
    fake.close()


def test_a_wrong_address_says_so():
    fake = FakeOllama([])
    p = OllamaProvider({"base_url": fake.url + "/somewhere", "model": "qwen2.5:14b"})
    err = p.test().error
    assert err["code"] == "wrong_address" and "11434" in err["hint"]
    afake = FakeAnthropic([])
    a = AnthropicProvider({"base_url": afake.url + "/proxy", "model": "claude-opus-5-5"}, key=KEY)
    err = a.test().error
    assert err["code"] == "wrong_address" and "without /v1" in err["hint"]
    assert claude(afake, model="claude-nonexistent").test().error["code"] == "model_not_found"
    lm = FakeLMStudio([("raw", 200, {"Content-Type": "application/json"},
                        {"error": "Unexpected endpoint or method. (POST /chat/completions)"})])
    g = OpenAICompatProvider({"preset": "custom", "base_url": lm.url + "/v1", "model": "qwen2.5-14b-instruct"},
                             key="sk-test-1234567890123456789")
    with pytest.raises(AssistantError) as e:
        g.complete(transcript(g), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "wrong_address"
    fake.close()
    afake.close()
    lm.close()


def test_an_openai_stream_that_stops_early_is_not_an_answer():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("The experiment has three screens"), truncate=True),
                       FakeOpenAI.turn(FakeOpenAI.text("partial"), finish="error"),
                       ("raw", 200, {"Content-Type": "application/json"},
                        {"id": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": "plain JSON"},
                                                 "finish_reason": "stop"}], "usage": {}})])
    p = gpt(fake)
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "bad_response" and "stopped early" in (e.value.detail or "")
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "provider_error"
    assert p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event()).text == "plain JSON"
    afake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("cut"), truncate=True)])
    with pytest.raises(AssistantError) as e:
        claude(afake).complete(transcript(claude(afake)), on_event=lambda e: None, cancel=threading.Event())
    assert e.value.code == "bad_response"
    fake.close()
    afake.close()


def test_older_claude_models_get_the_request_they_accept():
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("ok")), FakeAnthropic.turn(FakeAnthropic.text("ok"))])
    for model in ("claude-sonnet-4-5", "claude-sonnet-4-5-20250929", "claude-sonnet-4-0", "claude-opus-4-1"):
        body, betas = AnthropicProvider({"base_url": "https://api.anthropic.com", "model": model}, key=KEY).body(
            transcript(claude(fake)), model)
        assert "thinking" not in body and "output_config" not in body and "fallbacks" not in body and not betas
    body, _ = AnthropicProvider({"base_url": "https://api.anthropic.com", "model": "claude-opus-4-5"}, key=KEY).body(
        transcript(claude(fake)), "claude-opus-4-5", "max")
    assert "thinking" not in body and body["output_config"] == {"effort": "high"}
    p = claude(fake, model="claude-sonnet-4-5")
    models = {m.id: m for m in p.list_models()}
    assert models["claude-sonnet-4-5"].note == "Older model" and not models["claude-opus-5-5"].note.startswith("Older")
    assert p.complete(transcript(p), on_event=lambda e: None, cancel=threading.Event()).text == "ok"
    assert not fake.rejected
    res = p.test()
    assert res.ok and any("older model" in w for w in res.warnings)
    # an unknown id: the capabilities the Models API reports decide
    from edge.assistant.providers.anthropic import traits_for
    t = traits_for("claude-newer-9", {"capabilities": {"thinking": {"types": {"adaptive": {"supported": False}}},
                                                        "effort": {"supported": False}}})
    assert not t.thinking and t.efforts == () and not t.updates
    fake.close()


def test_no_credit_is_reported_at_once_not_retried():
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("never"))])
    fake.fail_next(429, {"error": {"message": "You exceeded your current quota, please check your plan and billing "
                                              "details.", "type": "insufficient_quota", "code": "insufficient_quota"}})
    p = gpt(fake)
    evs, on = events()
    with pytest.raises(AssistantError) as e:
        p.complete(transcript(p), on_event=on, cancel=threading.Event())
    assert e.value.code == "billing" and len(fake.chat_requests) + len(fake.requests) <= 1
    assert not [x for x in evs if x["kind"] == "retry"]
    fake.close()


def test_openrouter_without_tool_routes_switches_to_json_mode():
    from edge.assistant.errors import map_failure
    f = H.HttpFailure(404, {}, json.dumps({"error": {"message": "No endpoints found that support tool use. To learn "
                                                                "more about provider routing, visit: https://x", "code": 404}}))
    assert map_failure(f, provider="openai", model="m", base_url="https://openrouter.ai/api/v1").code == "tools_unsupported"


@pytest.mark.parametrize("status, body, provider, code, hint", [
    (500, {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}, "anthropic",
     "service_error", "status.anthropic.com"),
    (504, {"type": "error", "error": {"type": "timeout_error", "message": "Request timeout"}}, "anthropic",
     "service_error", "few minutes"),
    (500, {"error": "llama runner process has terminated: error loading model: unable to allocate CUDA0 buffer"},
     "ollama", "out_of_memory", "smaller model"),
])
def test_server_side_failures_have_a_hint(status, body, provider, code, hint):
    from edge.assistant.errors import map_failure
    e = map_failure(H.HttpFailure(status, {}, json.dumps(body)), provider=provider, model="m", base_url="http://x")
    assert e.code == code and hint in e.hint


def test_an_untrusted_certificate_gets_the_certificate_hint():
    from edge.assistant.errors import map_failure
    f = H.HttpFailure(None, {}, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate",
                      reason="tls")
    e = map_failure(f, provider="anthropic", model="m", base_url="https://api.anthropic.com")
    assert e.code == "tls_failed" and "SSL_CERT_FILE" in e.hint
    other = map_failure(H.HttpFailure(None, {}, "[SSL] handshake failure", reason="tls"), provider="anthropic",
                        model="m", base_url="https://api.anthropic.com")
    assert "date and time" in other.hint


def test_overloaded_mid_stream_waits_before_trying_again(monkeypatch):
    monkeypatch.setattr(H, "RETRY_BASE", 0.3)
    fake = FakeAnthropic([FakeAnthropic.turn(FakeAnthropic.text("a"), FakeAnthropic.text("b"), error_event="overloaded_error"),
                          FakeAnthropic.turn(FakeAnthropic.text("a"), FakeAnthropic.text("b"), error_event="overloaded_error"),
                          FakeAnthropic.turn(FakeAnthropic.text("fine"))])
    p = claude(fake)
    evs, on = events()
    import time
    t0 = time.monotonic()
    assert p.complete(transcript(p), on_event=on, cancel=threading.Event()).text == "fine"
    assert time.monotonic() - t0 >= 0.6 and len(fake.chat_requests) == 3
    assert [e["text"] for e in evs if e["kind"] == "retry"][0].startswith("Claude is busy — trying again in")
    fake.close()


def test_a_custom_service_starts_sentences_with_a_capital():
    from edge.assistant.errors import error
    assert error("billing", provider="openai", label="the service").message == "The service says the account has " \
                                                                              "no credit left."
    fake = FakeOpenAI([FakeOpenAI.turn(FakeOpenAI.text("ok"))])
    fake.fail_next(503, {"error": {"message": "busy"}})
    p = OpenAICompatProvider({"preset": "custom", "base_url": fake.url + "/v1", "model": "gpt-5.1"},
                             key="sk-test-1234567890123456789", label="the service")
    evs, on = events()
    p.complete(transcript(p), on_event=on, cancel=threading.Event())
    assert [e["text"] for e in evs if e["kind"] == "retry"][0].startswith("The service is busy")
    fake.close()


def test_ollama_through_the_openai_option_is_steered_to_the_ollama_option():
    fake = FakeOllama([])
    p = OpenAICompatProvider({"preset": "custom", "base_url": fake.url + "/v1", "model": "qwen2.5:14b"})
    res = p.test()
    assert res.ok and any("choose “Ollama”" in w for w in res.warnings)
    local = OpenAICompatProvider({"preset": "custom", "base_url": "http://127.0.0.1:11434/v1", "model": "m"})
    assert local.looks_like_ollama() and local.capabilities("m").context_tokens == 8192
    other = OpenAICompatProvider({"preset": "custom", "base_url": "http://127.0.0.1:8000/v1", "model": "m"})
    assert other.capabilities("m").context_tokens == 32768
    tr = local.new_transcript("s" * 40000, [])
    local.add_user(tr, "hi", [])
    with pytest.raises(AssistantError) as e:
        local.prepare(tr, local.capabilities("m"), lambda e: None)
    assert e.value.code == "context_too_long" and "Ollama" in e.value.hint
    fake.close()
