"""Ollama on this computer (default http://localhost:11434), through its native API.

``/api/version`` (running?), ``/api/tags`` (installed models), ``/api/show`` (capabilities: tools, vision;
context length) and ``/api/chat`` (one JSON object per line). Ollama silently cuts prompts longer than
``num_ctx``, so EDGE always sends ``options.num_ctx`` and refuses (``context_too_long``) before sending a
request that would not fit.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from ..errors import AssistantError, error
from ..http import Cancelled, HttpFailure, open_stream, request_json
from .base import (Capabilities, EventFn, ImagePart, ModelInfo, Provider, TestResult, ToolCall, ToolResult,
                   ToolSpec, Transcript, TurnResult)

_SHOW_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def parameter_billions(size: Any) -> float | None:
    """'14.8B' -> 14.8, '500M' -> 0.5."""
    m = re.match(r"^\s*([\d.]+)\s*([BbMmKk])", str(size or ""))
    if not m:
        return None
    n = float(m.group(1))
    return {"b": n, "m": n / 1000, "k": n / 1e6}[m.group(2).lower()]


class OllamaProvider(Provider):
    name = "ollama"
    local = True
    default_url = "http://localhost:11434"

    def __init__(self, settings: dict[str, Any], *, key: str | None = None, options: dict[str, Any] | None = None,
                 label: str | None = None):
        super().__init__(settings, key=None, options=options, label=label or "Ollama")
        self.num_ctx = int(self.settings.get("num_ctx") or 16384)
        self.keep_alive = self.settings.get("keep_alive") or "15m"
        self.temperature = float(self.settings.get("temperature") if self.settings.get("temperature") is not None else 0.2)
        self.timeout, self.first_byte = 180.0, 600.0
        if self.options.get("timeout_s"):
            self.first_byte = max(self.first_byte, float(self.options["timeout_s"]))

    # ------------------------------------------------------------------ server info
    def show(self, model: str) -> dict[str, Any]:
        k = (self.base_url, model)
        if k not in _SHOW_CACHE:
            try:
                _, _, data = request_json("POST", f"{self.base_url}/api/show", body={"model": model}, timeout=60,
                                          local=True, cancel=self.cancel)
            except HttpFailure as f:
                raise self.fail(f) from None
            _SHOW_CACHE[k] = data if isinstance(data, dict) else {}
        return _SHOW_CACHE[k]

    @staticmethod
    def context_length(info: dict[str, Any]) -> int | None:
        for k, v in (info.get("model_info") or {}).items():
            if k.endswith(".context_length") and isinstance(v, (int, float)):
                return int(v)
        return None

    def capabilities(self, model: str) -> Capabilities:
        info = self.show(model)
        caps = info.get("capabilities")
        tools = vision = None
        if isinstance(caps, list):
            tools, vision = "tools" in caps, "vision" in caps
        if "tools" in self.disabled:
            tools = False
        ctx_len = self.context_length(info)
        ctx = min(self.num_ctx, ctx_len) if ctx_len else self.num_ctx
        return Capabilities(tools=tools, vision=vision, context_tokens=ctx, json_schema=True, max_output_tokens=8192)

    # ------------------------------------------------------------------ conversation
    def add_user(self, tr: Transcript, text: str, images: list[ImagePart]) -> None:
        msg: dict[str, Any] = {"role": "user", "content": text}
        if images:
            msg["images"] = [im.data_b64 for im in images]
        tr.native.append(msg)

    def add_tool_results(self, tr: Transcript, results: list[ToolResult]) -> None:
        images: list[ImagePart] = []
        for r in results:
            content = r.content
            if r.images:
                content += "\n(image follows in the next message)"
                images += r.images
            tr.native.append({"role": "tool", "content": content, "tool_name": r.name})
        if images:
            self.add_user(tr, "Images returned by the tool calls above:", images)

    def body(self, tr: Transcript, model: str, num_ctx: int) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "stream": True, "keep_alive": self.keep_alive,
                                "options": {"num_ctx": num_ctx, "temperature": self.temperature},
                                "messages": [{"role": "system", "content": tr.system}] + tr.native}
        if tr.tools and "tools" not in self.disabled:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.schema}} for t in tr.tools]
        if tr.meta.get("json_schema") and "format" not in self.disabled:
            body["format"] = tr.meta["json_schema"]
        return body

    def complete(self, tr: Transcript, *, on_event: EventFn, cancel: threading.Event) -> TurnResult:
        model = self.need_model()
        self.cancel = self.cancel or cancel
        caps = self.capabilities(model)
        num_ctx = caps.context_tokens or self.num_ctx
        est = self.trim_context(tr, num_ctx, on_event)
        if est > 0.9 * num_ctx:
            raise error("context_too_long", provider=self.name, model=model,
                        detail=f"about {est} tokens for a context size of {num_ctx}")
        tried: set[str] = set()
        while True:
            body = self.body(tr, model, num_ctx)
            try:
                stream = open_stream(f"{self.base_url}/api/chat", body=body, timeout=self.timeout, local=True,
                                     first_byte_timeout=self.first_byte, cancel=cancel)
                return self._read(stream, tr, model, est, num_ctx, on_event, cancel)
            except HttpFailure as f:
                msg = f.message().lower()
                if f.status == 400 and "format" in msg and "format" not in tried and "format" in body:
                    tried.add("format")
                    self.disabled.add("format")
                    continue
                raise self.fail(f) from None

    def _read(self, stream: Any, tr: Transcript, model: str, est: int, num_ctx: int, on_event: EventFn,
              cancel: threading.Event) -> TurnResult:
        text: list[str] = []
        thinking: list[str] = []
        raw_calls: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        for obj in stream.iter_ndjson(cancel):
            if obj.get("error"):
                raise HttpFailure(400, {}, json.dumps({"error": obj["error"]}), url=self.base_url)
            m = obj.get("message") or {}
            if m.get("content"):
                text.append(m["content"])
            if m.get("thinking"):
                thinking.append(m["thinking"])
            for tc in m.get("tool_calls") or []:
                raw_calls.append(tc)
            if obj.get("done"):
                final = obj
                break
        if cancel.is_set():
            raise Cancelled()
        if not final:
            raise error("bad_response", provider=self.name, detail="the answer stopped early")
        calls: list[ToolCall] = []
        native_calls = []
        for n, tc in enumerate(raw_calls):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            call = ToolCall(id=str(tc.get("id") or f"call_{len(tr.native)}_{n}"), name=str(fn.get("name") or ""),
                            input=None)
            if isinstance(args, dict):
                call.input = args
                call.raw_input = json.dumps(args, ensure_ascii=False)
            else:
                call.raw_input = str(args or "")
                try:
                    val = json.loads(call.raw_input) if call.raw_input.strip() else {}
                    if isinstance(val, dict):
                        call.input = val
                    else:
                        call.parse_error = "the input is not a JSON object"
                except ValueError as e:
                    call.parse_error = str(e)
            calls.append(call)
            native_calls.append({"function": {"name": call.name, "arguments": call.input if call.input is not None else {}}})
        msg: dict[str, Any] = {"role": "assistant", "content": "".join(text)}
        if native_calls:
            msg["tool_calls"] = native_calls
        tr.native.append(msg)
        notes = []
        th = "".join(thinking).strip()
        if th and len(th) <= 400:
            notes.append(th)
            self.emit(on_event, "note", th)
        pe = final.get("prompt_eval_count")
        if isinstance(pe, int) and est > 0.8 * num_ctx and pe < 0.6 * est:
            self.emit(on_event, "warning", "Ollama may have cut the request short (the context size is nearly full)")
        reason = final.get("done_reason")
        stop = "max_tokens" if reason == "length" else ("tool_use" if calls else "end")
        return TurnResult(text="".join(text).strip(), notes=notes, tool_calls=calls, stop=stop, refusal=None,
                          usage={"input_tokens": int(pe or 0), "output_tokens": int(final.get("eval_count") or 0)},
                          model=model)

    # ------------------------------------------------------------------ models and test
    def _tags(self) -> list[dict[str, Any]]:
        try:
            _, _, data = request_json("GET", f"{self.base_url}/api/tags", timeout=30, local=True, cancel=self.cancel)
        except HttpFailure as f:
            raise self.fail(f) from None
        return [m for m in (data or {}).get("models") or [] if isinstance(m, dict) and m.get("name")]

    def list_models(self) -> list[ModelInfo]:
        tags = self._tags()
        out = []
        for m in tags:
            d = m.get("details") or {}
            size = d.get("parameter_size")
            label = m["name"] + (f" ({', '.join(x for x in (size, d.get('quantization_level')) if x)})"
                                 if size or d.get("quantization_level") else "")
            info = ModelInfo(id=m["name"], label=label)
            if len(tags) <= 15:
                try:
                    caps = self.capabilities(m["name"])
                    info.tools, info.vision, info.context = caps.tools, caps.vision, self.context_length(self.show(m["name"]))
                except AssistantError:
                    pass
            b = parameter_billions(size)
            if b is not None and b < 7:
                info.note = "Small models often make mistakes; a 14B+ model with tool support works best."
            info.recommended = bool(info.tools)
            out.append(info)
        sizes = {m["name"]: parameter_billions((m.get("details") or {}).get("parameter_size")) or 0 for m in tags}
        out.sort(key=lambda i: (not i.recommended, -sizes.get(i.id, 0), i.id))
        return out

    def test(self, deep: bool = False) -> TestResult:
        res = TestResult(ok=False, provider=self.name, base_url=self.base_url, model=self.model)
        t0 = time.monotonic()
        try:
            try:
                _, _, ver = request_json("GET", f"{self.base_url}/api/version", timeout=10, local=True,
                                         cancel=self.cancel)
            except HttpFailure as f:
                raise self.fail(f) from None
            res.server = f"Ollama {(ver or {}).get('version', '')}".strip()
            tags = self._tags()
            res.models = len(tags)
            res.latency_ms = int((time.monotonic() - t0) * 1000)
            if not self.model:
                res.warnings.append("Choose a model." if tags else "No models are installed: run `ollama pull qwen2.5:14b`.")
                res.ok = True
                return res
            names = {m["name"] for m in tags} | {m["name"].removesuffix(":latest") for m in tags}
            if self.model not in names:
                res.error = error("model_not_pulled", provider=self.name, model=self.model).to_dict()
                return res
            caps = self.capabilities(self.model)
        except AssistantError as e:
            res.error = e.to_dict()
            return res
        mode = "tools" if caps.tools is not False and self.settings.get("tool_mode", "auto") != "json" else "json"
        res.capabilities = {"tools": caps.tools, "vision": caps.vision, "context_tokens": caps.context_tokens, "mode": mode}
        if caps.context_tokens and caps.context_tokens < 16384:
            res.warnings.append(f"Context size {caps.context_tokens} is small; 16384 or more works better.")
        elif caps.context_tokens and caps.context_tokens < 32768:
            res.warnings.append(f"Context size {caps.context_tokens} is fine; 32768 is better for big experiments.")
        if caps.tools is False:
            res.warnings.append("This model has no tool support: EDGE will use a slower JSON mode. "
                                "A model with tools (e.g. qwen2.5:14b) works better.")
        tag = next((m for m in tags if m["name"] in (self.model, self.model + ":latest")), {})
        b = parameter_billions((tag.get("details") or {}).get("parameter_size"))
        if b is not None and b < 7:
            res.warnings.append("Small models often make mistakes; a 14B+ model with tool support works best.")
        res.ok = True
        return res
