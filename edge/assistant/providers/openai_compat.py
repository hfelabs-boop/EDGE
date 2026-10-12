"""Any OpenAI-compatible Chat Completions service: OpenAI, OpenRouter, a custom address (and LM Studio,
which subclasses this).

``POST {base_url}/chat/completions`` (streaming SSE, tool calls assembled by index), ``GET {base_url}/models``.
Servers differ in what they accept, so each refusal of an optional feature (``stream_options``, streaming
with tools, ``max_completion_tokens``, ``response_format``, images) is retried once without it.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import urlparse

from ..config import PRESETS, is_local_host
from ..errors import AssistantError, error
from ..http import Cancelled, HttpFailure, open_stream, request_json, with_retries
from .base import (Capabilities, EventFn, ImagePart, ModelInfo, Provider, TestResult, ToolCall, ToolResult,
                   ToolSpec, Transcript, TurnResult)

HIDDEN_MODELS = re.compile(r"^(text-embedding|whisper|tts|dall-e|omni-moderation|babbage|davinci|gpt-image)")
MAX_OUTPUT = 16384
LOCAL_CONTEXT = 32768             # an OpenAI-compatible server on this computer that doesn't say its context size
OLLAMA_COMPAT_CONTEXT = 8192      # Ollama through /v1: its default context (EDGE can't raise it there)
OLLAMA_HINT = ("This is Ollama: choose “Ollama” (not OpenAI-compatible) in Assistant settings, so EDGE can set the "
               "context size.")
NO_IMAGE = "[image not available: metadata only]"


class OpenAICompatProvider(Provider):
    name = "openai"
    local = False
    default_url = PRESETS["openai"][0]

    def __init__(self, settings: dict[str, Any], *, key: str | None = None, options: dict[str, Any] | None = None,
                 label: str | None = None):
        preset = (settings or {}).get("preset") or "openai"
        if not (settings or {}).get("base_url") and PRESETS.get(preset, (None,))[0]:
            settings = {**(settings or {}), "base_url": PRESETS[preset][0]}
        super().__init__(settings, key=key, options=options, label=label or PRESETS.get(preset, PRESETS["openai"])[2])
        self.preset = preset
        self.is_openai = self.host == "api.openai.com"
        self.is_openrouter = self.host.endswith("openrouter.ai")
        self.max_param = "max_completion_tokens" if self.is_openai else "max_tokens"
        self.temperature: float | None = None
        self._listing: dict[str, dict[str, Any]] = {}
        self.timeout = float(self.options.get("timeout_s") or 120)
        self.first_byte: float | None = None
        if is_local_host(self.host):
            self.local = True
            self.timeout, self.first_byte = 180.0, 600.0

    # ------------------------------------------------------------------ wire helpers
    def headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        if self.is_openrouter:
            h["HTTP-Referer"] = "https://edge.local/"
            h["X-Title"] = "EDGE experiment builder"
        return h

    def require_key(self) -> None:
        if not self.key and not self.local:
            raise error("not_configured", provider=self.name, label=self.label,
                        message=f"No API key for {self.label} is set.",
                        hint="Open Assistant settings and paste the service's API key.")

    @staticmethod
    def tool_json(t: ToolSpec) -> dict[str, Any]:
        return {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}

    def capabilities(self, model: str) -> Capabilities:
        info = self._listing.get(model) or {}
        vision: bool | None = None
        mods = (info.get("architecture") or {}).get("input_modalities")
        if isinstance(mods, list):
            vision = "image" in mods
        if "vision" in self.disabled:
            vision = False
        ctx = info.get("context_length") or (info.get("top_provider") or {}).get("context_length")
        if not isinstance(ctx, (int, float)):
            # unknown: online services have large contexts; a server on this computer is assumed small, so long
            # requests are trimmed (or refused) instead of being cut silently by the server
            ctx = (OLLAMA_COMPAT_CONTEXT if self.looks_like_ollama() else LOCAL_CONTEXT) if self.local else 128000
        return Capabilities(tools=False if "tools" in self.disabled else None, vision=vision,
                            context_tokens=int(ctx), json_schema=True, max_output_tokens=MAX_OUTPUT)

    def looks_like_ollama(self) -> bool:
        """Ollama's OpenAI-compatible address (port 11434): it can't be told the context size, so it cuts long
        requests to its default (a few thousand tokens). EDGE's Ollama option sets the size."""
        try:
            port = urlparse(self.base_url).port
        except ValueError:
            port = None
        return self.name == "openai" and self.local and port == 11434

    # ------------------------------------------------------------------ conversation
    def add_user(self, tr: Transcript, text: str, images: list[ImagePart]) -> None:
        if images and "vision" not in self.disabled:
            parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:{im.media_type};base64,{im.data_b64}"}}
                      for im in images]
            tr.native.append({"role": "user", "content": parts})
        else:
            if images:
                text += "\n" + "\n".join(f"{NO_IMAGE} ({im.name})" for im in images)
            tr.native.append({"role": "user", "content": text})

    def add_tool_results(self, tr: Transcript, results: list[ToolResult]) -> None:
        images: list[ImagePart] = []
        for r in results:
            content = r.content
            if r.images:
                content += "\n(image follows in the next message)"
                images += r.images
            tr.native.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
        if images:
            self.add_user(tr, "Images returned by the tool calls above:", images)

    def body(self, tr: Transcript, model: str, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "stream": stream}
        if stream and "stream_options" not in self.disabled:
            body["stream_options"] = {"include_usage": True}
        body["messages"] = [{"role": "system", "content": tr.system}] + tr.native
        if tr.tools and "tools" not in self.disabled:
            body["tools"] = [self.tool_json(t) for t in tr.tools]
            body["tool_choice"] = "auto"
        schema = tr.meta.get("json_schema")
        if schema and "response_format" not in self.disabled:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "edge_step", "schema": schema}}
        body[self.max_param] = MAX_OUTPUT
        if self.temperature is not None:
            body["temperature"] = self.temperature
        return body

    def complete(self, tr: Transcript, *, on_event: EventFn, cancel: threading.Event) -> TurnResult:
        model = self.need_model()
        self.require_key()
        self.cancel = self.cancel or cancel
        caps = self.capabilities(model)
        self.prepare(tr, caps, on_event)
        tried: set[str] = set()
        while True:
            stream_mode = "stream" not in self.disabled
            body = self.body(tr, model, stream_mode)
            url = f"{self.base_url}/chat/completions"
            try:
                resp = with_retries(
                    lambda: open_stream(url, headers=self.headers(), body=body, timeout=self.timeout,
                                        local=self.local, first_byte_timeout=self.first_byte, cancel=cancel),
                    on_wait=lambda msg, d: self.emit(on_event, "retry", msg),
                    cancel=cancel, local=self.local, label=self.label)
                if stream_mode and "json" not in str(resp.headers.get("content-type") or "").lower():
                    return self._read_stream(resp, tr, model, on_event, cancel)
                return self._read_json(resp.read_json(cancel), tr, model, on_event)
            except HttpFailure as f:
                feat = self._degradable(f, tr)
                if feat and feat not in tried:
                    tried.add(feat)
                    self._degrade(feat, tr, on_event)
                    continue
                raise self.fail(f) from None

    def prepare(self, tr: Transcript, caps: Capabilities, on_event: EventFn) -> None:
        est = self.trim_context(tr, caps.context_tokens, on_event)
        if caps.context_tokens and est > caps.context_tokens:
            extra = {"hint": OLLAMA_HINT} if self.looks_like_ollama() else {}
            raise error("context_too_long", provider=self.name, label=self.label, model=self.model,
                        detail=f"about {est} tokens for a context of {caps.context_tokens}", **extra)

    def fail(self, f: Any) -> AssistantError:
        e = super().fail(f)
        if e.code == "tools_unsupported":
            return error("tools_unsupported", provider=self.name, label=self.label, detail=e.detail, status=e.status)
        return e

    def _degradable(self, f: HttpFailure, tr: Transcript) -> str | None:
        if f.status not in (400, 422):
            return None
        msg = f.message().lower()
        if "max_completion_tokens" in msg or ("max_tokens" in msg and "unsupported" in msg):
            return "max_param"
        if "stream_options" in msg:
            return "stream_options"
        if "response_format" in msg or "json_schema" in msg:
            return "response_format"
        if "stream" in msg and ("tool" in msg or "not supported" in msg or "unsupported" in msg):
            return "stream"
        if ("image" in msg or "vision" in msg or "multimodal" in msg) and _has_images(tr):
            return "vision"
        return None

    def _degrade(self, feat: str, tr: Transcript, on_event: EventFn) -> None:
        if feat == "max_param":
            self.max_param = "max_tokens" if self.max_param == "max_completion_tokens" else "max_completion_tokens"
        elif feat == "vision":
            self.disabled.add("vision")
            _strip_images(tr)
            self.emit(on_event, "warning", "This model can't look at pictures: it gets their names and sizes only")
        else:
            self.disabled.add(feat)

    def _read_stream(self, resp: Any, tr: Transcript, model: str, on_event: EventFn,
                     cancel: threading.Event) -> TurnResult:
        text: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish = None
        usage: dict[str, Any] = {}
        served = model
        chunks = 0
        for _event, data in resp.iter_sse(cancel):
            try:
                chunk = json.loads(data)
            except ValueError:
                raise error("bad_response", provider=self.name, label=self.label, detail=data[:300]) from None
            if not isinstance(chunk, dict):
                raise error("bad_response", provider=self.name, label=self.label, detail=data[:300])
            chunks += 1
            if isinstance(chunk.get("error"), (dict, str)):
                e = chunk["error"]
                raise HttpFailure(400, {}, json.dumps({"error": e}), url=self.base_url)
            served = chunk.get("model") or served
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("content"):
                    text.append(d["content"])
                r = d.get("reasoning_content") or d.get("reasoning")
                if isinstance(r, str) and r:
                    reasoning.append(r)
                for tc in d.get("tool_calls") or []:
                    idx = int(tc.get("index", len(calls)))
                    cur = calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if tc.get("id"):
                        cur["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        cur["name"] += fn["name"]
                    if fn.get("arguments"):
                        cur["arguments"] += fn["arguments"] if isinstance(fn["arguments"], str) else json.dumps(fn["arguments"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
        if cancel.is_set():
            raise Cancelled()
        if not chunks or (finish is None and not resp.saw_done):
            # the stream ended without a finish_reason or [DONE]: cut off (a dropped connection, a proxy timeout)
            raise error("bad_response", provider=self.name, label=self.label, detail="the answer stopped early")
        return self._finish(tr, "".join(text), "".join(reasoning), [calls[k] for k in sorted(calls)], finish,
                            usage, served, on_event)

    def _read_json(self, data: Any, tr: Transcript, model: str, on_event: EventFn) -> TurnResult:
        if not isinstance(data, dict) or not data.get("choices"):
            if isinstance(data, dict) and data.get("error"):
                raise HttpFailure(400, {}, json.dumps({"error": data["error"]}), url=self.base_url)
            raise error("bad_response", provider=self.name, label=self.label, detail=str(data)[:300])
        ch = data["choices"][0]
        msg = ch.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            calls.append({"id": tc.get("id"), "name": fn.get("name") or "",
                          "arguments": args if isinstance(args, str) else json.dumps(args or {})})
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return self._finish(tr, msg.get("content") or "", reasoning if isinstance(reasoning, str) else "", calls,
                            ch.get("finish_reason"), data.get("usage") or {}, data.get("model") or model, on_event)

    def _finish(self, tr: Transcript, text: str, reasoning: str, raw_calls: list[dict[str, Any]], finish: Any,
                usage: dict[str, Any], model: str, on_event: EventFn) -> TurnResult:
        if str(finish or "") == "error":       # OpenRouter's normalised mid-stream error
            raise error("provider_error", provider=self.name, label=self.label,
                        short="the answer stopped with an error", detail=text[:300] or None)
        tool_calls: list[ToolCall] = []
        native_calls = []
        for n, c in enumerate(raw_calls):
            cid = c.get("id") or f"call_{len(tr.native)}_{n}"
            args = c.get("arguments") or ""
            call = ToolCall(id=cid, name=c.get("name") or "", input=None, raw_input=args)
            try:
                val = json.loads(args) if args.strip() else {}
                if isinstance(val, dict):
                    call.input = val
                else:
                    call.parse_error = "the input is not a JSON object"
            except ValueError as e:
                call.parse_error = str(e)
            tool_calls.append(call)
            native_calls.append({"id": cid, "type": "function", "function": {"name": call.name, "arguments": args}})
        msg: dict[str, Any] = {"role": "assistant", "content": text or ""}
        if native_calls:
            msg["tool_calls"] = native_calls
        tr.native.append(msg)
        notes = []
        if reasoning.strip() and len(reasoning.strip()) <= 600:
            notes.append(reasoning.strip())
            self.emit(on_event, "note", reasoning.strip())
        stop = {"stop": "end", "tool_calls": "tool_use", "function_call": "tool_use", "length": "max_tokens",
                "content_filter": "refusal"}.get(str(finish or ""), "end" if not tool_calls else "tool_use")
        refusal = {"category": "content_filter", "explanation": None} if stop == "refusal" else None
        return TurnResult(text=text.strip(), notes=notes, tool_calls=tool_calls, stop=stop, refusal=refusal,
                          usage={"input_tokens": int(usage.get("prompt_tokens") or 0),
                                 "output_tokens": int(usage.get("completion_tokens") or 0)},
                          model=model)

    # ------------------------------------------------------------------ models and test
    def _get_models(self) -> list[dict[str, Any]]:
        self.require_key()
        try:
            status, headers, data = request_json("GET", f"{self.base_url}/models", headers=self.headers(),
                                                 timeout=60 if self.local else 15, local=self.local,
                                                 cancel=self.cancel)
            if isinstance(data, dict) and data.get("error") and not isinstance(data.get("data"), list):
                # LM Studio answers an unknown route with 200 {"error": "Unexpected endpoint …"}
                raise HttpFailure(status, headers, json.dumps({"error": data["error"]}), url=self.base_url)
        except HttpFailure as f:
            raise self.fail(f) from None
        rows = (data or {}).get("data") if isinstance(data, dict) else data
        rows = [r for r in rows or [] if isinstance(r, dict) and r.get("id")]
        for r in rows:
            self._listing[str(r["id"])] = r
        return rows

    def list_models(self) -> list[ModelInfo]:
        out = []
        for r in self._get_models():
            mid = str(r["id"])
            if HIDDEN_MODELS.match(mid):
                continue
            caps = self.capabilities(mid)
            out.append(ModelInfo(id=mid, label=r.get("name") or mid, tools=None, vision=caps.vision,
                                 context=r.get("context_length")))
        out.sort(key=lambda m: m.id)
        return out

    def test(self, deep: bool = False) -> TestResult:
        res = TestResult(ok=False, provider=self.name, base_url=self.base_url, model=self.model)
        t0 = time.monotonic()
        try:
            rows = self._get_models()
        except AssistantError as e:
            res.error = e.to_dict()
            return res
        res.latency_ms = int((time.monotonic() - t0) * 1000)
        res.models = len(rows)
        res.server = self.label if self.preset != "custom" else self.host
        ids = {str(r["id"]) for r in rows}
        if not self.model:
            res.warnings.append("Choose a model.")
        elif self.model not in ids:
            res.warnings.append(f"“{self.model}” is not in the service's list of models; it may still work.")
        if self.model:
            caps = self.capabilities(self.model)
            res.capabilities = {"tools": caps.tools, "vision": caps.vision, "context_tokens": caps.context_tokens,
                                "mode": "tools"}
        if self.looks_like_ollama() or (self.name == "openai" and self.local and self._answers_like_ollama()):
            res.warnings.append(OLLAMA_HINT + " Through this address Ollama cuts long requests short.")
        if deep and self.model:
            ok, why = self._deep_test()
            if not ok:
                res.error = why
                return res
        res.ok = True
        return res

    def _answers_like_ollama(self) -> bool:
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            _, _, data = request_json("GET", f"{root}/api/version", timeout=3, local=True, cancel=self.cancel)
        except (HttpFailure, Cancelled):
            return False
        return isinstance(data, dict) and "version" in data

    def _deep_test(self) -> tuple[bool, dict | None]:
        tr = self.new_transcript("You are testing a connection. Call the ping tool once.",
                                 [ToolSpec("ping", "Answers pong. Call it once.", {"type": "object", "properties": {}})])
        self.add_user(tr, "Call the ping tool now.", [])
        try:
            turn = self.complete(tr, on_event=lambda e: None, cancel=threading.Event())
        except AssistantError as e:
            return False, e.to_dict()
        if not any(c.name == "ping" for c in turn.tool_calls):
            return False, error("tools_unsupported", provider=self.name, label=self.label).to_dict()
        return True, None


def _has_images(tr: Transcript) -> bool:
    return any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"]
                                                          if isinstance(p, dict))
               for m in tr.native if isinstance(m, dict))


def _strip_images(tr: Transcript) -> None:
    """Replace image parts with a note (this model can't take pictures). Not used for Claude. Messages are
    replaced, never edited in place (a job's transcript shares them with the conversation's)."""
    for i, m in enumerate(tr.native):
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in c):
            parts = [{"type": "text", "text": NO_IMAGE} if isinstance(p, dict) and p.get("type") == "image_url" else p
                     for p in c]
            tr.native[i] = {**m, "content": parts}
