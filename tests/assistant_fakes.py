"""Scripted fake model services for testing the assistant without any real LLM.

* ``FakeAnthropic``  — ``/v1/models``, ``/v1/models/{id}``, ``/v1/messages`` (SSE or JSON)
* ``FakeOpenAI``     — ``/v1/models``, ``/v1/chat/completions`` (SSE chunks + ``[DONE]``, or JSON)
* ``FakeOllama``     — ``/api/version``, ``/api/tags``, ``/api/show``, ``/api/chat`` (NDJSON)
* ``FakeLMStudio``   — FakeOpenAI + ``/api/v0/models`` and LM Studio's "No models loaded" error

Each server answers the chat requests from a *script*: a list (one item per request) or a function of the
request. Items are turns built with the helpers (``FakeAnthropic.turn(FakeAnthropic.text("…"),
FakeAnthropic.tool("validate", {}))``), ``("error", status, body)`` tuples, or functions.

For checking the builder by hand or with Playwright (frontend packages), start one from the repository root::

    python -m tests.assistant_fakes --kind anthropic --port 9310 --scenario stroop
    # then point EDGE at it (any key works with the fake):
    EDGE_CONFIG_DIR=/tmp/edge-cfg python -m edge assistant config --provider anthropic \\
        --base-url http://127.0.0.1:9310 --model claude-opus-5-5
    printf %s sk-ant-fake-key-123456 | EDGE_CONFIG_DIR=/tmp/edge-cfg python -m edge assistant config --set-key
    EDGE_CONFIG_DIR=/tmp/edge-cfg python -m edge builder /tmp/ws --port 9311 --no-browser

The fakes are *strict* by default: they refuse (400, in the real APIs' words) what the real services refuse —
Anthropic: the version header, a beta header for every beta feature, the first message from the user, empty
messages or empty text blocks, tool_use/tool_result pairing (results first, in the next message), image media
types that don't match the bytes, adaptive thinking or effort sent to an older model; OpenAI: tool messages that
don't answer the previous assistant message's tool_calls, arguments that aren't strings. Ollama answers unknown
routes like its router does (404, text/plain ``404 page not found``). ``strict=False`` turns the checks off.

Script items may also be ``("raw", status, headers, body)`` (any answer, e.g. a 200 JSON body where a stream was
expected) and turns may be ``truncate=True`` (the stream stops without its end: no stop event / [DONE]).

Scenarios: ``stroop`` (reads the attached table if any, builds a Stroop task, validates, test-runs; a follow-up
on an experiment that has the trial screen makes the word bigger), ``code`` (adds a Python code item: review
chip, no test run), ``answer`` (answers without changing anything), ``slow`` (streams slowly: Stop button),
``refuse`` (declines), ``fail`` (the service answers 529 overloaded).
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable

GOLDEN_OPS: list[dict[str, Any]] = [
    {"op": "set_info", "name": "Stroop", "description": "Colour-word Stroop built by the assistant"},
    {"op": "add_routine", "rid": "instructions", "add_to_flow": True},
    {"op": "add_component", "rid": "instructions", "ctype": "text", "cid": "msg",
     "properties": {"text": "Name the INK colour.\n r = red, g = green, b = blue\nPress SPACE", "height": 30}},
    {"op": "add_component", "rid": "instructions", "ctype": "keyboard", "cid": "go",
     "properties": {"keys": ["space"], "end_routine": True}},
    {"op": "add_routine", "rid": "trial"},
    {"op": "add_component", "rid": "trial", "ctype": "fixation", "cid": "fix", "properties": {"duration": 0.5}},
    {"op": "add_component", "rid": "trial", "ctype": "text", "cid": "word",
     "properties": {"text": "$word", "color": "$ink", "height": 80, "start": 0.5, "marker": "word_onset"}},
    {"op": "add_component", "rid": "trial", "ctype": "keyboard", "cid": "resp",
     "properties": {"keys": ["r", "g", "b"], "start": 0.5, "duration": 2.0, "correct": "$correct_key",
                    "end_routine": True}},
    {"op": "add_loop", "lid": "trials", "children": ["trial"], "conditions": "conditions/words.csv",
     "order": "random", "repeats": 2},
    {"op": "add_routine", "rid": "thanks", "duration": 2, "add_to_flow": True},
    {"op": "add_component", "rid": "thanks", "ctype": "text", "cid": "bye", "properties": {"text": "Thank you!"}},
]
STROOP_ROWS = [{"word": w, "ink": i, "congruent": int(w.lower() == i), "correct_key": i[0]}
               for w in ("RED", "GREEN", "BLUE") for i in ("red", "green", "blue")]
FINAL_TEXT = ("This builds a colour-word Stroop task: instructions, then 18 trials (your 9 rows, shuffled, twice) "
              "with a 0.5 s fixation and the word until a key press (r, g or b, at most 2 s), then a thank-you "
              "screen. Check the instructions text and the response keys.")
ANTHROPIC_MODELS = [
    {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5", "created_at": "2026-09-01T00:00:00Z"},
    {"id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5", "created_at": "2026-09-01T00:00:00Z"},
    {"id": "claude-haiku-5-5", "display_name": "Claude Haiku 5.5", "created_at": "2026-08-01T00:00:00Z"},
    {"id": "claude-fable-5-1", "display_name": "Claude Fable 5.1", "created_at": "2026-07-01T00:00:00Z"},
    {"id": "claude-opus-4-8", "display_name": "Claude Opus 4.8", "created_at": "2026-01-01T00:00:00Z"},
    {"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5", "created_at": "2025-09-29T00:00:00Z"},
]
# what each model accepts (the Models API's capabilities tree, and what the strict fake enforces)
ALL_EFFORTS = ("low", "medium", "high", "xhigh", "max")
NO_ADAPTIVE = ("claude-sonnet-4-5", "claude-opus-4-5", "claude-opus-4-1", "claude-sonnet-4-0", "claude-opus-4-0",
               "claude-haiku-4-5")
NO_EFFORT = ("claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1", "claude-sonnet-4-0", "claude-opus-4-0")
UPDATES_OK = ("claude-opus-5-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5")
MEDIA_MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff", "image/gif": b"GIF8",
               "image/webp": b"RIFF"}


def model_capabilities(mid: str) -> dict[str, Any]:
    adaptive = mid not in NO_ADAPTIVE
    effort: dict[str, Any] = {"supported": mid not in NO_EFFORT}
    for e in ALL_EFFORTS:
        effort[e] = {"supported": mid not in NO_EFFORT and (e not in ("xhigh", "max") or adaptive)}
    return {"image_input": {"supported": True}, "pdf_input": {"supported": True},
            "thinking": {"supported": True, "types": {"adaptive": {"supported": adaptive},
                                                      "enabled": {"supported": True}}},
            "effort": effort}


class ScriptedServer:
    """A local HTTP server (127.0.0.1, a free port unless given) answering from a script."""

    chat_paths: tuple[str, ...] = ()

    def __init__(self, script: list | Callable[[dict], Any] | None = None, *, port: int = 0):
        self.script: Any = list(script) if isinstance(script, (list, tuple)) else script
        self.requests: list[dict[str, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self._fail: list[tuple[int, Any, dict]] = []
        self._hold: list[float] = []
        self._delay = 0.0
        self.closed = False
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _do(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    js = json.loads(raw) if raw else None
                except ValueError:
                    js = None
                req = {"method": self.command, "path": self.path, "headers": dict(self.headers), "json": js,
                       "raw": raw}
                with owner.lock:
                    owner.requests.append(req)
                try:
                    status, headers, body = owner.respond(req)
                except Exception as e:  # noqa: BLE001 - report fake errors as 500s
                    status, headers, body = 500, {}, json.dumps({"error": f"fake server: {e!r}"}).encode()
                try:
                    self.send_response(status)
                    for k, v in (headers or {}).items():
                        self.send_header(k, v)
                    if isinstance(body, (bytes, bytearray)):
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self.end_headers()
                        for chunk in body:
                            if owner._delay:
                                time.sleep(owner._delay)
                            self.wfile.write(chunk)
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            do_GET = _do
            do_POST = _do

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------ control
    def fail_next(self, status: int, body: Any, headers: dict | None = None, times: int = 1) -> None:
        """The next ``times`` requests (any path) get this answer."""
        for _ in range(times):
            self._fail.append((status, body, headers or {}))

    def delay(self, seconds: float) -> None:
        """Sleep this long before each streamed chunk (slow streams: cancel and timeout tests)."""
        self._delay = seconds

    def hold_headers(self, seconds: float, times: int = 1) -> None:
        """The next ``times`` chat requests wait this long before any answer (a model loading, a long prompt):
        the client is still waiting for the response headers."""
        self._hold += [seconds] * times

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.httpd.shutdown()
            self.httpd.server_close()

    def __enter__(self) -> "ScriptedServer":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ answering
    def respond(self, req: dict[str, Any]) -> tuple[int, dict, Any]:
        if self._fail:
            status, body, headers = self._fail.pop(0)
            return status, {"Content-Type": "application/json", **headers}, _bytes(body)
        if self._hold and req["method"] == "POST" and any(x in req["path"] for x in self.chat_paths):
            with self.lock:
                wait = self._hold.pop(0) if self._hold else 0.0
            time.sleep(wait)
        return self.route(req)

    def route(self, req: dict[str, Any]) -> tuple[int, dict, Any]:  # pragma: no cover - overridden
        return 404, {}, b"{}"

    @staticmethod
    def raw_item(item: Any) -> tuple[int, dict, Any] | None:
        """A ("raw", status, headers, body) script item: that answer exactly."""
        if isinstance(item, tuple) and item and item[0] == "raw":
            return item[1], dict(item[2] or {}), _bytes(item[3])
        return None

    def next_item(self, req: dict[str, Any]) -> Any:
        with self.lock:
            self.chat_requests.append(req)
            if callable(self.script):
                return self.script(req)
            if self.script:
                item = self.script.pop(0)
                return item(req) if callable(item) else item
        return None


def _bytes(body: Any) -> bytes:
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        return body.encode()
    return json.dumps(body).encode()


def _split(s: str, n: int = 3) -> list[str]:
    if len(s) < n:
        return [s] if s else []
    k = max(1, len(s) // n)
    parts = [s[i:i + k] for i in range(0, len(s), k)]
    return parts


# ============================================================================ Anthropic
def _a_err(msg: str, status: int = 400, etype: str = "invalid_request_error") -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json"}, _bytes(
        {"type": "error", "error": {"type": etype, "message": msg}, "request_id": "req_strict"})


def validate_anthropic(req: dict[str, Any]) -> tuple[int, dict, bytes] | None:
    """The 400 the Messages API would answer, or None (documented API behaviour)."""
    import base64
    h = {k.lower(): v for k, v in req["headers"].items()}
    if h.get("anthropic-version") != "2023-06-01":
        return _a_err("anthropic-version: header is required")
    if "application/json" not in (h.get("content-type") or ""):
        return _a_err("content-type must be application/json")
    betas = {b.strip() for b in (h.get("anthropic-beta") or "").split(",") if b.strip()}
    body = req["json"] or {}
    model = str(body.get("model", ""))
    th = body.get("thinking") or {}
    if th.get("display") == "updates" and "thinking-display-updates-2026-08-18" not in betas:
        return _a_err("thinking.display: 'updates' requires the thinking-display-updates beta")
    if body.get("fallbacks") == "default" and "server-side-fallback-2026-07-01" not in betas:
        return _a_err("fallbacks: Extra inputs are not permitted")
    for k in ("temperature", "top_p", "top_k"):
        if k in body and model not in NO_ADAPTIVE:
            return _a_err(f"{k}: is not supported for this model")
    if model in NO_ADAPTIVE and th.get("type") == "adaptive":
        return _a_err('"thinking.type.adaptive" is not supported for this model.')
    if model in NO_EFFORT and (body.get("output_config") or {}).get("effort"):
        return _a_err("output_config.effort: This model does not support the effort parameter.")
    if th.get("display") == "updates" and model not in UPDATES_OK:
        return _a_err('thinking.display: "updates" is not supported for this model.')
    msgs = body.get("messages") or []
    if not msgs:
        return _a_err("messages: at least one message is required")
    if msgs[0].get("role") != "user":
        return _a_err('messages: first message must use the "user" role')
    for i, m in enumerate(msgs):
        c = m.get("content")
        last_assistant = i == len(msgs) - 1 and m.get("role") == "assistant"
        if (c == [] or c == "") and not last_assistant:
            return _a_err(f"messages.{i}: all messages must have non-empty content except for the optional final "
                          "assistant message")
        if isinstance(c, list):
            for j, b in enumerate(c):
                if b.get("type") == "text" and not b.get("text"):
                    return _a_err(f"messages.{i}.content.{j}.text: text content blocks must be non-empty")
                images = [b] if b.get("type") == "image" else [x for x in (b.get("content") or [])
                                                               if isinstance(x, dict) and x.get("type") == "image"] \
                    if b.get("type") == "tool_result" and isinstance(b.get("content"), list) else []
                for im in images:
                    src = im.get("source") or {}
                    mt = src.get("media_type")
                    if mt not in MEDIA_MAGIC:
                        return _a_err(f"messages.{i}.content.{j}.source.media_type: Input should be 'image/jpeg', "
                                      "'image/png', 'image/gif' or 'image/webp'")
                    head = base64.b64decode(str(src.get("data") or "")[:64] + "==")[:8]
                    if not head.startswith(MEDIA_MAGIC[mt]):
                        real = next((k for k, v in MEDIA_MAGIC.items() if head.startswith(v)), "unknown")
                        return _a_err(f"messages.{i}.content.{j}.image.source.base64.data: The image was specified "
                                      f"using the {mt} media type, but the image appears to be a {real} image")
        if m.get("role") == "assistant" and isinstance(c, list):
            ids = [b["id"] for b in c if b.get("type") == "tool_use"]
            if ids and i + 1 < len(msgs):
                got = [b.get("tool_use_id") for b in msgs[i + 1].get("content") or []
                       if isinstance(b, dict) and b.get("type") == "tool_result"] \
                    if isinstance(msgs[i + 1].get("content"), list) else []
                if set(ids) - set(got):
                    return _a_err(f"messages.{i + 1}: `tool_use` ids were found without `tool_result` blocks "
                                  f"immediately after: {', '.join(sorted(set(ids) - set(got)))}. Each `tool_use` block "
                                  "must have a corresponding `tool_result` block in the next message.")
        if m.get("role") == "user" and isinstance(c, list):
            res = [b for b in c if isinstance(b, dict) and b.get("type") == "tool_result"]
            if res:
                prev = msgs[i - 1] if i else {}
                prev_ids = {b.get("id") for b in prev.get("content") or [] if isinstance(b, dict)
                            and b.get("type") == "tool_use"} if isinstance(prev.get("content"), list) else set()
                for b in res:
                    if b.get("tool_use_id") not in prev_ids:
                        return _a_err(f"messages.{i}.content: unexpected `tool_use_id` found in `tool_result` blocks: "
                                      f"{b.get('tool_use_id')}. Each `tool_result` block must have a corresponding "
                                      "`tool_use` block in the previous message.")
                if [b.get("type") for b in c][:len(res)] != ["tool_result"] * len(res):
                    return _a_err(f"messages.{i}: tool_result blocks must come first in the content")
    return None


class FakeAnthropic(ScriptedServer):
    chat_paths = ("/v1/messages",)

    def __init__(self, script: Any = None, *, api_key: str | None = None, models: list[dict] | None = None,
                 port: int = 0, strict: bool = True):
        self.api_key = api_key
        self.models = models or ANTHROPIC_MODELS
        self.strict = strict
        self.rejected: list[dict[str, Any]] = []        # requests the strict checks refused (with the reason)
        super().__init__(script, port=port)

    # turn helpers
    @staticmethod
    def text(t: str) -> dict[str, Any]:
        return {"type": "text", "text": t}

    @staticmethod
    def tool(name: str, input: dict[str, Any], id: str | None = None, raw: str | None = None) -> dict[str, Any]:
        b: dict[str, Any] = {"type": "tool_use", "id": id or f"toolu_{name}_{int(time.monotonic() * 1e6) % 10**9}",
                             "name": name, "input": input}
        if raw is not None:
            b["_raw"] = raw
        return b

    @staticmethod
    def thinking(signature: str = "sig-abc123", text: str = "") -> dict[str, Any]:
        return {"type": "thinking", "thinking": text, "signature": signature}

    @staticmethod
    def fallback_block(frm: str, to: str) -> dict[str, Any]:
        return {"type": "fallback", "from": {"model": frm}, "to": {"model": to}}

    @staticmethod
    def turn(*blocks: dict[str, Any], stop: str | None = None, stop_details: dict | None = None,
             usage: dict | None = None, model: str | None = None, error_event: str | None = None,
             truncate: bool = False) -> dict[str, Any]:
        if stop is None:
            stop = "tool_use" if any(b.get("type") == "tool_use" for b in blocks) else "end_turn"
        return {"blocks": list(blocks), "stop": stop, "stop_details": stop_details,
                "usage": usage or {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 900,
                                   "cache_creation_input_tokens": 300},
                "model": model, "error_event": error_event, "truncate": truncate}

    def route(self, req: dict[str, Any]) -> tuple[int, dict, Any]:
        path = req["path"].split("?")[0]
        h = {k.lower(): v for k, v in req["headers"].items()}
        if not h.get("x-api-key") or (self.api_key and h.get("x-api-key") != self.api_key):
            return 401, {"Content-Type": "application/json"}, _bytes(
                {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                 "request_id": "req_fake"})
        if req["method"] == "GET" and path == "/v1/models":
            return 200, {"Content-Type": "application/json"}, _bytes(
                {"data": [{**m, "type": "model", "max_input_tokens": 1000000, "max_tokens": 128000,
                           "capabilities": m.get("capabilities") or model_capabilities(m["id"])}
                          for m in self.models],
                 "has_more": False})
        if req["method"] == "GET" and path.startswith("/v1/models/"):
            mid = path.rsplit("/", 1)[1]
            m = next((x for x in self.models if x["id"] == mid), None)
            if m is None:
                return 404, {"Content-Type": "application/json"}, _bytes(
                    {"type": "error", "error": {"type": "not_found_error", "message": f"model: {mid}"}})
            return 200, {"Content-Type": "application/json"}, _bytes(
                {**m, "type": "model", "max_input_tokens": 1000000, "max_tokens": 128000,
                 "capabilities": m.get("capabilities") or model_capabilities(m["id"])})
        if req["method"] == "POST" and path == "/v1/messages":
            bad = validate_anthropic(req) if self.strict else None
            if bad is not None:
                with self.lock:
                    self.chat_requests.append(req)
                    self.rejected.append({"request": req, "error": json.loads(bad[2])["error"]["message"]})
                return bad
            item = self.next_item(req)
            if item is None:
                item = self.turn(self.text("Done."))
            raw = self.raw_item(item)
            if raw is not None:
                return raw
            if isinstance(item, tuple) and item[0] == "error":
                return item[1], {"Content-Type": "application/json", **(item[3] if len(item) > 3 else {})}, _bytes(item[2])
            body = req["json"] or {}
            model = item.get("model") or body.get("model") or "claude-opus-5-5"
            if body.get("stream"):
                return 200, {"Content-Type": "text/event-stream"}, self._sse(item, model)
            return 200, {"Content-Type": "application/json"}, _bytes(self._message(item, model))
        return 404, {"Content-Type": "application/json"}, _bytes({"type": "error", "error": {
            "type": "not_found_error", "message": "not found"}})

    def _message(self, item: dict[str, Any], model: str) -> dict[str, Any]:
        content = [{k: v for k, v in b.items() if k != "_raw"} for b in item["blocks"]]
        return {"id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": content,
                "stop_reason": item["stop"], "stop_details": item.get("stop_details"), "usage": item["usage"]}

    def _sse(self, item: dict[str, Any], model: str) -> Iterable[bytes]:
        def ev(name: str, data: dict[str, Any]) -> bytes:
            return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()

        def gen() -> Iterable[bytes]:
            u = item["usage"]
            yield ev("message_start", {"type": "message_start", "message": {
                "id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": [],
                "stop_reason": None, "usage": {k: u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                                        "cache_creation_input_tokens")}
                | {"output_tokens": 1}}})
            for i, b in enumerate(item["blocks"]):
                if item.get("error_event") and i == 1:
                    yield ev("error", {"type": "error", "error": {"type": item["error_event"], "message": "Overloaded"}})
                    return
                t = b["type"]
                if t == "text":
                    yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                                     "content_block": {"type": "text", "text": ""}})
                    for part in _split(b["text"], 2):
                        yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                         "delta": {"type": "text_delta", "text": part}})
                elif t == "thinking":
                    yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                                     "content_block": {"type": "thinking", "thinking": "",
                                                                       "signature": ""}})
                    if b.get("thinking"):
                        yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                         "delta": {"type": "thinking_delta", "thinking": b["thinking"]}})
                    yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                     "delta": {"type": "signature_delta", "signature": b["signature"]}})
                elif t == "tool_use":
                    yield ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                        "type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
                    raw = b.get("_raw") if b.get("_raw") is not None else json.dumps(b["input"])
                    for part in _split(raw, 3):
                        yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                         "delta": {"type": "input_json_delta", "partial_json": part}})
                else:
                    yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                                     "content_block": {k: v for k, v in b.items() if k != "_raw"}})
                yield ev("content_block_stop", {"type": "content_block_stop", "index": i})
                if i == 0:
                    yield ev("ping", {"type": "ping"})
            if item.get("truncate"):
                return                       # the connection drops: no message_delta, no message_stop
            delta: dict[str, Any] = {"stop_reason": item["stop"], "stop_sequence": None}
            if item.get("stop_details"):
                delta["stop_details"] = item["stop_details"]
            yield ev("message_delta", {"type": "message_delta", "delta": delta,
                                       "usage": {"output_tokens": u.get("output_tokens", 0)}})
            yield ev("message_stop", {"type": "message_stop"})
        return gen()


def assert_append_only(requests: list[dict[str, Any]]) -> None:
    """Each Messages request extends the previous one (same system and tools, earlier messages unchanged, the
    returned assistant turn appended): what preserved thinking and prompt caching need."""
    msgs = [r for r in requests if r["method"] == "POST" and r["path"].startswith("/v1/messages") and r["json"]]
    for a, b in zip(msgs, msgs[1:]):
        ja, jb = a["json"], b["json"]
        assert json.dumps(ja.get("system"), sort_keys=True) == json.dumps(jb.get("system"), sort_keys=True), "system changed"
        assert json.dumps(ja.get("tools"), sort_keys=True) == json.dumps(jb.get("tools"), sort_keys=True), "tools changed"
        ma, mb = ja["messages"], jb["messages"]
        assert len(mb) > len(ma), "the conversation did not grow"
        assert mb[:len(ma)] == ma, "earlier messages were edited"
        assert mb[len(ma)]["role"] == "assistant", "the returned assistant turn was not appended next"


# ============================================================================ OpenAI-compatible
def validate_openai(body: dict[str, Any]) -> str | None:
    """The 400 message Chat Completions would answer for the message list, or None."""
    msgs = body.get("messages") or []
    pending: list[str] = []
    for i, m in enumerate(msgs):
        r = m.get("role")
        if r == "tool":
            if m.get("tool_call_id") not in pending:
                return ("Invalid parameter: messages with role 'tool' must be a response to a preceeding message "
                        "with 'tool_calls'.")
            pending.remove(m["tool_call_id"])
            continue
        if pending:
            return ("An assistant message with 'tool_calls' must be followed by tool messages responding to each "
                    f"'tool_call_id'. The following tool_call_ids did not have response messages: {', '.join(pending)}")
        if r == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if not isinstance((tc.get("function") or {}).get("arguments"), str):
                    return f"messages[{i}].tool_calls: arguments must be a string"
            pending = [tc["id"] for tc in m["tool_calls"]]
    return None


class FakeOpenAI(ScriptedServer):
    chat_paths = ("/chat/completions",)

    def __init__(self, script: Any = None, *, api_key: str | None = None, models: list[str] | None = None,
                 reject_stream_options: bool = False, reject_max_completion_tokens: bool = False,
                 reject_tools: bool = False, port: int = 0, strict: bool = True):
        self.strict = strict
        self.rejected: list[dict[str, Any]] = []
        self.api_key = api_key
        self.model_ids = models or ["gpt-5.1", "gpt-5.1-mini", "text-embedding-3-small", "whisper-1"]
        self.reject_stream_options = reject_stream_options
        self.reject_max_completion_tokens = reject_max_completion_tokens
        self.reject_tools = reject_tools
        super().__init__(script, port=port)

    @staticmethod
    def text(t: str) -> dict[str, Any]:
        return {"content": t}

    @staticmethod
    def tool(name: str, args: dict[str, Any] | str, id: str | None = None) -> dict[str, Any]:
        return {"tool": {"id": id or f"call_{name}_{int(time.monotonic() * 1e6) % 10**9}", "name": name,
                         "arguments": args if isinstance(args, str) else json.dumps(args)}}

    @staticmethod
    def turn(*parts: dict[str, Any], finish: str | None = None, usage: dict | None = None,
             reasoning: str | None = None, truncate: bool = False) -> dict[str, Any]:
        text = "".join(p.get("content", "") for p in parts)
        calls = [p["tool"] for p in parts if "tool" in p]
        return {"text": text, "calls": calls, "finish": finish or ("tool_calls" if calls else "stop"),
                "usage": usage or {"prompt_tokens": 1500, "completion_tokens": 90}, "reasoning": reasoning,
                "truncate": truncate}

    def _auth_ok(self, req: dict[str, Any]) -> bool:
        if not self.api_key:
            return True
        h = {k.lower(): v for k, v in req["headers"].items()}
        return h.get("authorization") == f"Bearer {self.api_key}"

    def extra_route(self, req: dict[str, Any], path: str) -> tuple[int, dict, Any] | None:
        return None

    def route(self, req: dict[str, Any]) -> tuple[int, dict, Any]:
        path = req["path"].split("?")[0]
        extra = self.extra_route(req, path)
        if extra is not None:
            return extra
        if not self._auth_ok(req):
            return 401, {"Content-Type": "application/json"}, _bytes(
                {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error",
                           "code": "invalid_api_key"}})
        if req["method"] == "GET" and path.endswith("/models"):
            return 200, {"Content-Type": "application/json"}, _bytes(
                {"object": "list", "data": [{"id": m, "object": "model"} for m in self.model_ids]})
        if req["method"] == "POST" and path.endswith("/chat/completions"):
            body = req["json"] or {}
            if self.reject_stream_options and "stream_options" in body:
                return 400, {"Content-Type": "application/json"}, _bytes(
                    {"error": {"message": "Unrecognized request argument supplied: stream_options"}})
            if self.reject_max_completion_tokens and "max_completion_tokens" in body:
                return 400, {"Content-Type": "application/json"}, _bytes(
                    {"error": {"message": "Unsupported parameter: 'max_completion_tokens'"}})
            if self.reject_tools and body.get("tools"):
                return 400, {"Content-Type": "application/json"}, _bytes(
                    {"error": {"message": "This model does not support tools"}})
            bad = validate_openai(body) if self.strict else None
            if bad:
                with self.lock:
                    self.chat_requests.append(req)
                    self.rejected.append({"request": req, "error": bad})
                return 400, {"Content-Type": "application/json"}, _bytes(
                    {"error": {"message": bad, "type": "invalid_request_error", "param": "messages", "code": None}})
            item = self.next_item(req)
            if item is None:
                item = self.turn(self.text("Done."))
            raw = self.raw_item(item)
            if raw is not None:
                return raw
            if isinstance(item, tuple) and item[0] == "error":
                return item[1], {"Content-Type": "application/json", **(item[3] if len(item) > 3 else {})}, _bytes(item[2])
            model = body.get("model") or "gpt-5.1"
            if body.get("stream"):
                return 200, {"Content-Type": "text/event-stream"}, self._sse(item, model, bool(body.get("stream_options")))
            return 200, {"Content-Type": "application/json"}, _bytes(self._json(item, model))
        return 404, {"Content-Type": "application/json"}, _bytes({"error": {"message": "not found"}})

    def _json(self, item: dict[str, Any], model: str) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": item["text"] or None}
        if item["calls"]:
            msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": c["arguments"]}} for c in item["calls"]]
        return {"id": "chatcmpl-fake", "object": "chat.completion", "model": model,
                "choices": [{"index": 0, "message": msg, "finish_reason": item["finish"]}], "usage": item["usage"]}

    def _sse(self, item: dict[str, Any], model: str, usage: bool) -> Iterable[bytes]:
        def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
            return ("data: " + json.dumps({"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": model,
                                           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})
                    + "\n\n").encode()

        def gen() -> Iterable[bytes]:
            yield chunk({"role": "assistant", "content": ""})
            if item.get("reasoning"):
                yield chunk({"reasoning_content": item["reasoning"]})
            for part in _split(item["text"], 2):
                yield chunk({"content": part})
            for idx, c in enumerate(item["calls"]):
                yield chunk({"tool_calls": [{"index": idx, "id": c["id"], "type": "function",
                                             "function": {"name": c["name"], "arguments": ""}}]})
                for part in _split(c["arguments"], 3):
                    yield chunk({"tool_calls": [{"index": idx, "function": {"arguments": part}}]})
            if item.get("truncate"):
                return                       # the connection drops: no finish_reason, no [DONE]
            yield chunk({}, item["finish"])
            if usage:
                yield ("data: " + json.dumps({"id": "chatcmpl-fake", "object": "chat.completion.chunk",
                                              "choices": [], "usage": item["usage"]}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
        return gen()


class FakeLMStudio(FakeOpenAI):
    def __init__(self, script: Any = None, *, models: list[dict] | None = None, no_model_loaded: bool = False,
                 v0: bool = True, port: int = 0):
        self.v0_models = models if models is not None else [
            {"id": "qwen2.5-14b-instruct", "type": "llm", "state": "loaded", "max_context_length": 32768,
             "loaded_context_length": 16384},
            {"id": "llava-v1.6", "type": "vlm", "state": "not-loaded", "max_context_length": 4096},
            {"id": "text-embedding-nomic", "type": "embeddings", "state": "loaded", "max_context_length": 2048}]
        self.no_model_loaded = no_model_loaded
        self.v0 = v0
        super().__init__(script, models=[m["id"] for m in self.v0_models], port=port)

    def extra_route(self, req: dict[str, Any], path: str) -> tuple[int, dict, Any] | None:
        if path == "/api/v0/models":
            if not self.v0:
                return 404, {"Content-Type": "application/json"}, _bytes({"error": "Unexpected endpoint"})
            return 200, {"Content-Type": "application/json"}, _bytes({"object": "list", "data": self.v0_models})
        if self.no_model_loaded and path.endswith("/chat/completions"):
            return 400, {"Content-Type": "application/json"}, _bytes(
                {"error": {"message": "No models loaded. Please load a model in the developer page or use the "
                                      "`lms load` command."}})
        return None


# ============================================================================ Ollama
class FakeOllama(ScriptedServer):
    chat_paths = ("/api/chat",)

    def __init__(self, script: Any = None, *, models: dict[str, dict] | None = None, version: str = "0.12.3",
                 port: int = 0):
        self.models = models if models is not None else {
            "qwen2.5:14b": {"tools": True, "vision": False, "context": 32768, "size": "14.8B"},
            "llama3.2:3b": {"tools": True, "vision": False, "context": 131072, "size": "3.2B"},
            "gemma2:9b": {"tools": False, "vision": False, "context": 8192, "size": "9.2B"}}
        self.version = version
        super().__init__(script, port=port)

    @staticmethod
    def text(t: str) -> dict[str, Any]:
        return {"content": t}

    @staticmethod
    def tool(name: str, args: dict[str, Any] | str) -> dict[str, Any]:
        return {"tool": {"name": name, "arguments": args}}

    @staticmethod
    def turn(*parts: dict[str, Any], done_reason: str = "stop", prompt_eval_count: int = 1500,
             thinking: str | None = None) -> dict[str, Any]:
        return {"text": "".join(p.get("content", "") for p in parts), "calls": [p["tool"] for p in parts if "tool" in p],
                "done_reason": done_reason, "prompt_eval_count": prompt_eval_count, "thinking": thinking}

    def route(self, req: dict[str, Any]) -> tuple[int, dict, Any]:
        path = req["path"].split("?")[0]
        j = {"Content-Type": "application/json"}
        if path == "/api/version":
            return 200, j, _bytes({"version": self.version})
        if path == "/v1/models":                  # Ollama's OpenAI-compatible listing
            return 200, j, _bytes({"object": "list", "data": [{"id": n, "object": "model"} for n in self.models]})
        if path == "/api/tags":
            return 200, j, _bytes({"models": [
                {"name": n, "model": n, "size": 9_000_000_000,
                 "details": {"parameter_size": m.get("size", "7B"), "family": n.split(":")[0],
                             "quantization_level": "Q4_K_M"}} for n, m in self.models.items()]})
        if path == "/api/show":
            name = (req["json"] or {}).get("model") or (req["json"] or {}).get("name")
            m = self._model(name)
            if m is None:
                return 404, j, _bytes({"error": f"model '{name}' not found"})
            caps = ["completion"] + (["tools"] if m.get("tools") else []) + (["vision"] if m.get("vision") else [])
            return 200, j, _bytes({"capabilities": caps, "model_info": {"general.architecture": "qwen2",
                                                                        "qwen2.context_length": m.get("context", 8192)}})
        if path == "/api/chat":
            body = req["json"] or {}
            name = body.get("model")
            m = self._model(name)
            if m is None:
                return 404, j, _bytes({"error": f"model \"{name}\" not found, try pulling it first"})
            if body.get("tools") and not m.get("tools"):
                return 400, j, _bytes({"error": f"registry.ollama.ai/library/{name} does not support tools"})
            item = self.next_item(req)
            if item is None:
                item = self.turn(self.text("Done."))
            raw = self.raw_item(item)
            if raw is not None:
                return raw
            if isinstance(item, tuple) and item[0] == "error":
                return item[1], j, _bytes(item[2])
            return 200, {"Content-Type": "application/x-ndjson"}, self._ndjson(item, name)
        return 404, {"Content-Type": "text/plain"}, b"404 page not found"     # Ollama's (gin) router

    def _model(self, name: Any) -> dict | None:
        if not isinstance(name, str):
            return None
        return self.models.get(name) or self.models.get(name + ":latest") or self.models.get(name.removesuffix(":latest"))

    def _ndjson(self, item: dict[str, Any], model: str) -> Iterable[bytes]:
        def line(obj: dict[str, Any]) -> bytes:
            return (json.dumps(obj) + "\n").encode()

        def gen() -> Iterable[bytes]:
            if item.get("thinking"):
                yield line({"model": model, "message": {"role": "assistant", "content": "",
                                                        "thinking": item["thinking"]}, "done": False})
            for part in _split(item["text"], 2):
                yield line({"model": model, "message": {"role": "assistant", "content": part}, "done": False})
            if item["calls"]:
                yield line({"model": model, "message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}} for c in item["calls"]]},
                    "done": False})
            yield line({"model": model, "message": {"role": "assistant", "content": ""}, "done": True,
                        "done_reason": item["done_reason"], "prompt_eval_count": item["prompt_eval_count"],
                        "eval_count": 120})
        return gen()


def closed_port() -> int:
    """A port nothing listens on."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ============================================================================ file builders (tests)
def png_bytes(w: int = 40, h: int = 30, rgb: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def gif_bytes(w: int = 20, h: int = 10, frames: int = 1) -> bytes:
    import struct
    head = b"GIF89a" + struct.pack("<HH", w, h) + b"\x80\x00\x00" + b"\x00\x00\x00\xff\xff\xff"
    frame = (b"\x21\xf9\x04\x00\x0a\x00\x00\x00" + b"\x2c" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00"
             + b"\x02\x02\x44\x01\x00")
    return head + frame * frames + b"\x3b"


def bmp_bytes(w: int = 16, h: int = 8) -> bytes:
    import struct
    row = (b"\x00\x00\xff" * w + b"\x00" * ((4 - (3 * w) % 4) % 4))
    pixels = row * h
    return (b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0) + pixels)


def jpeg_bytes(w: int = 64, h: int = 48) -> bytes:
    """A JPEG header with a SOF0 segment (enough for size sniffing; not a decodable picture)."""
    import struct
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, h, w, 3) + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp_bytes(w: int = 200, h: int = 100, animated: bool = False) -> bytes:
    import struct
    flags = 0x02 if animated else 0
    chunk = b"VP8X" + struct.pack("<I", 10) + bytes([flags, 0, 0, 0]) + (w - 1).to_bytes(3, "little") \
        + (h - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


def svg_bytes(w: int = 300, h: int = 150) -> bytes:
    return (f'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">'
            f'<rect width="{w}" height="{h}" fill="red"/></svg>').encode()


def wav_bytes(seconds: float = 0.5, rate: int = 8000) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wv:
        wv.setnchannels(1)
        wv.setsampwidth(2)
        wv.setframerate(rate)
        wv.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def xlsx_bytes(sheets: dict[str, list[list[Any]]], active: int = 0, doctype: bool = False) -> bytes:
    """A minimal .xlsx written with zipfile (inline strings), as Excel would read it."""
    import io
    import zipfile
    from xml.sax.saxutils import escape as xesc

    def col(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    def sheet_xml(rows: list[list[Any]]) -> str:
        out = []
        for ri, row in enumerate(rows, 1):
            cells = []
            for ci, v in enumerate(row):
                ref = f"{col(ci)}{ri}"
                if v is None:
                    continue
                if isinstance(v, bool):
                    cells.append(f'<c r="{ref}" t="b"><v>{int(v)}</v></c>')
                elif isinstance(v, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xesc(str(v))}</t></is></c>')
            out.append(f'<row r="{ri}">{"".join(cells)}</row>')
        dt = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' if doctype else ""
        return (f'<?xml version="1.0" encoding="UTF-8"?>{dt}<worksheet xmlns="http://schemas.openxmlformats.org/'
                f'spreadsheetml/2006/main"><sheetData>{"".join(out)}</sheetData></worksheet>')
    names = list(sheets)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"/>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"/>')
        sheets_xml = "".join(f'<sheet name="{xesc(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<bookViews><workbookView activeTab="{active}"/></bookViews><sheets>{sheets_xml}</sheets></workbook>')
        rels = "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       f'relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names)))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.'
                   f'openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, n in enumerate(names):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", sheet_xml(sheets[n]))
    return buf.getvalue()


# ============================================================================ scenarios (for UI checks)
def _last_user_text(kind: str, body: dict[str, Any]) -> tuple[str, int]:
    """The researcher's latest message and how many model turns already answered it."""
    msgs = body.get("messages") or []
    steps = 0
    for m in reversed(msgs):
        role = m.get("role")
        c = m.get("content")
        if role == "assistant":
            steps += 1
            continue
        if role == "user":
            if isinstance(c, list):
                texts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
                if texts and any("<request>" in t for t in texts):
                    return "\n".join(texts), steps
            elif isinstance(c, str) and "<request>" in c:
                return c, steps
    return "", steps


def scenario_steps(name: str, user: str, history: str = "") -> list[dict[str, Any]]:
    """Neutral steps: {"say": text, "tool": (name, input)} or {"say": text, "final": True}."""
    import re
    m = re.search(r'<attachment file="([^"]+)" kind="table"', user)
    table = m.group(1) if m else None
    if name == "answer":
        return [{"say": "This experiment shows each word once per trial and records the key press and the "
                        "response time.", "final": True}]
    if name == "code":
        return [{"say": "I'll add a Python item that keeps a running score.",
                 "tool": ("apply_operations", {"operations": [
                     {"op": "add_routine", "rid": "scoring", "add_to_flow": True, "duration": 0.5},
                     {"op": "add_component", "rid": "scoring", "ctype": "code", "cid": "score_code",
                      "properties": {"on_begin": "score = 0"}}]})},
                {"say": "", "tool": ("validate", {})},
                {"say": "This adds a screen “scoring” with Python code that sets score to 0. Read the code before "
                        "running participants.", "final": True}]
    built = ("trial:" in user and "word (text" in user) or (history.count("<request>") > 1
                                                           and "Colour-word Stroop" in history)
    if name == "stroop" and built:
        return [{"say": "I'll make the word bigger.",
                 "tool": ("apply_operations", {"operations": [
                     {"op": "update_component", "rid": "trial", "cid": "word", "set_props": {"height": 120}}]})},
                {"say": "", "tool": ("validate", {})},
                {"say": "This makes the word bigger (120 pixels instead of 80).", "final": True}]
    ops = json.loads(json.dumps(GOLDEN_OPS))
    steps: list[dict[str, Any]] = []
    if table:
        ops[8]["conditions"] = table
        steps.append({"say": "I'll read your list and build the Stroop task.",
                      "tool": ("read_attachment", {"file": table})})
        steps.append({"say": "", "tool": ("apply_operations", {"operations": ops})})
    else:
        ops[8]["conditions"] = STROOP_ROWS
        steps.append({"say": "I'll build a Stroop task with 9 colour-word combinations.",
                      "tool": ("apply_operations", {"operations": ops})})
    steps += [{"say": "", "tool": ("validate", {})}, {"say": "", "tool": ("dry_run", {})},
              {"say": FINAL_TEXT, "final": True}]
    return steps


def make_scenario(kind: str, name: str) -> Callable[[dict], Any]:
    def script(req: dict[str, Any]) -> Any:
        body = req["json"] or {}
        if name == "fail":
            return ("error", 529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        user, step = _last_user_text(kind, body)
        if name == "refuse":
            if kind == "anthropic":
                return FakeAnthropic.turn(stop="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                        "explanation": "declined (fake)"})
            return FakeOpenAI.turn(FakeOpenAI.text(""), finish="content_filter")
        steps = scenario_steps("stroop" if name == "slow" else name, user, json.dumps(body))
        s = steps[min(step, len(steps) - 1)]
        if kind == "anthropic":
            blocks = [FakeAnthropic.thinking(f"sig-{step}", "")]
            if s["say"]:
                blocks.append(FakeAnthropic.text(s["say"]))
            if not s.get("final"):
                blocks.append(FakeAnthropic.tool(s["tool"][0], s["tool"][1], id=f"toolu_{step}"))
            return FakeAnthropic.turn(*blocks)
        if kind in ("openai", "lmstudio"):
            parts = [FakeOpenAI.text(s["say"])] if s["say"] else []
            if not s.get("final"):
                parts.append(FakeOpenAI.tool(s["tool"][0], s["tool"][1], id=f"call_{step}"))
            return FakeOpenAI.turn(*parts)
        parts = [FakeOllama.text(s["say"])] if s["say"] else []
        if not s.get("final"):
            parts.append(FakeOllama.tool(s["tool"][0], s["tool"][1]))
        return FakeOllama.turn(*parts)
    return script


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run a fake model service for EDGE's assistant (testing only).")
    p.add_argument("--kind", choices=["anthropic", "openai", "ollama", "lmstudio"], default="anthropic")
    p.add_argument("--port", type=int, default=9310)
    p.add_argument("--scenario", choices=["stroop", "code", "answer", "slow", "refuse", "fail"], default="stroop")
    p.add_argument("--delay", type=float, default=None, help="seconds before each streamed chunk")
    a = p.parse_args(argv)
    cls = {"anthropic": FakeAnthropic, "openai": FakeOpenAI, "ollama": FakeOllama, "lmstudio": FakeLMStudio}[a.kind]
    srv = cls(make_scenario(a.kind, a.scenario), port=a.port)
    if a.delay is not None or a.scenario == "slow":
        srv.delay(a.delay if a.delay is not None else 0.4)
    base = srv.url + ("/v1" if a.kind in ("openai", "lmstudio") else "")
    model = {"anthropic": "claude-opus-5-5", "openai": "gpt-5.1", "ollama": "qwen2.5:14b",
             "lmstudio": "qwen2.5-14b-instruct"}[a.kind]
    print(f"Fake {a.kind} service ({a.scenario}) at {base}", flush=True)
    print(f"  edge assistant config --provider {a.kind} --base-url {base} --model {model}"
          + ("   (then --set-key with any key, e.g. sk-ant-fake-key-123456)" if a.kind in ("anthropic", "openai") else ""),
          flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.close()


if __name__ == "__main__":
    main()
