"""Claude through the Anthropic Messages API, spoken over urllib (no SDK: EDGE keeps PyYAML as its only
required dependency).

* ``POST {base_url}/v1/messages`` with ``x-api-key`` and ``anthropic-version: 2023-06-01``, streaming (SSE).
* Adaptive thinking and ``output_config.effort`` per model (:data:`MODEL_TRAITS`); no temperature/top_p/top_k,
  no ``tool_choice`` (auto) and no prefill.
* Prompt caching: the primer is the first system block with ``cache_control``; a top-level ``cache_control``
  caches the growing conversation. System and tools are frozen per conversation and history is append-only,
  so thinking blocks (passed back unchanged, signatures intact) stay valid.
* Refusals end the job (``refused``); on the official API ``fallbacks: "default"`` lets Anthropic retry a
  declined request on another Claude model. Progress notes come from ``thinking.display: "updates"``.
"""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

from ..config import ANTHROPIC_URL, DEFAULT_MODEL, RECOMMENDED_ANTHROPIC
from ..errors import AssistantError, error
from .. import http
from ..http import Cancelled, HttpFailure, open_stream, request_json, sleep_or_cancel, with_retries
from .base import (Capabilities, EventFn, ImagePart, ModelInfo, Provider, TestResult, ToolResult, ToolSpec,
                   Transcript, TurnResult, ToolCall)

API_VERSION = "2023-06-01"
BETA_FALLBACK = "server-side-fallback-2026-07-01"
BETA_UPDATES = "thinking-display-updates-2026-08-18"
MAX_TOKENS = 64000
ALL_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DISABLED_FEATURES: set[str] = set()      # process-wide: features a server refused once ("updates", "fallbacks", "eager")


@dataclass(frozen=True)
class Traits:
    thinking: bool          # send {"type": "adaptive"}
    efforts: tuple[str, ...]
    updates: bool           # thinking.display "updates" (progress notes)
    fallbacks: bool         # fallbacks: "default"


MODEL_TRAITS: list[tuple[str, Traits]] = [
    ("claude-opus-5-5", Traits(True, ALL_EFFORTS, True, True)),
    ("claude-fable-5-1", Traits(True, ALL_EFFORTS, True, True)),
    ("claude-fable-5", Traits(True, ALL_EFFORTS, True, True)),
    ("claude-sonnet-5-5", Traits(True, ALL_EFFORTS, True, True)),
    ("claude-haiku-5-5", Traits(True, ALL_EFFORTS, False, False)),
    ("claude-opus-5", Traits(True, ALL_EFFORTS, False, True)),
    ("claude-sonnet-5", Traits(True, ALL_EFFORTS, False, False)),
    ("claude-opus-4-8", Traits(True, ALL_EFFORTS, False, False)),
    ("claude-opus-4-7", Traits(True, ALL_EFFORTS, False, False)),
    ("claude-opus-4-6", Traits(True, ("low", "medium", "high", "max"), False, False)),
    ("claude-sonnet-4-6", Traits(True, ("low", "medium", "high", "max"), False, False)),
    ("claude-haiku-4-5", Traits(False, (), False, False)),
    # older models the Models API still lists: no adaptive thinking (they use budget_tokens), effort only on Opus 4.5
    ("claude-opus-4-5", Traits(False, ("low", "medium", "high"), False, False)),
    ("claude-sonnet-4-5", Traits(False, (), False, False)),
    ("claude-opus-4-1", Traits(False, (), False, False)),
    ("claude-opus-4-0", Traits(False, (), False, False)),
    ("claude-opus-4", Traits(False, (), False, False)),
    ("claude-sonnet-4-0", Traits(False, (), False, False)),
    ("claude-sonnet-4", Traits(False, (), False, False)),
    ("claude-3-7-sonnet", Traits(False, (), False, False)),
    ("claude-3-5-haiku", Traits(False, (), False, False)),
    ("claude-3-haiku", Traits(False, (), False, False)),
]
NEWEST = MODEL_TRAITS[0][1]
OLDER = {m for m, t in MODEL_TRAITS if not t.thinking and m != "claude-haiku-4-5"}
LABELS = {m["id"]: m["label"] for m in RECOMMENDED_ANTHROPIC}


def _known(model: str) -> tuple[str, Traits] | None:
    for prefix, t in sorted(MODEL_TRAITS, key=lambda kv: -len(kv[0])):
        if model == prefix or model.startswith(prefix + "-") or model.startswith(prefix + "@"):
            return prefix, t
    return None


def traits_for(model: str, info: dict[str, Any] | None = None) -> Traits:
    """What the model accepts: from the Models API's capabilities when EDGE has them, else from the table (an
    unknown, newer id gets the newest model's request)."""
    k = _known(model)
    base = k[1] if k else NEWEST
    caps = (info or {}).get("capabilities") if isinstance(info, dict) else None
    if not isinstance(caps, dict):
        return base
    thinking, efforts = base.thinking, base.efforts
    th = caps.get("thinking")
    if isinstance(th, dict):
        adaptive = ((th.get("types") or {}).get("adaptive") or {}).get("supported") \
            if isinstance(th.get("types"), dict) else None
        if th.get("supported") is False:
            thinking = False
        elif isinstance(adaptive, bool):
            thinking = adaptive
    eff = caps.get("effort")
    if isinstance(eff, dict):
        if eff.get("supported") is False:
            efforts = ()
        else:
            levels = tuple(x for x in ALL_EFFORTS if isinstance(eff.get(x), dict) and eff[x].get("supported"))
            if levels:
                efforts = levels
    return Traits(thinking, efforts, base.updates and thinking, base.fallbacks)


def is_older(model: str) -> bool:
    k = _known(model)
    return bool(k and k[0] in OLDER)


class _Overloaded(Exception):
    pass


class AnthropicProvider(Provider):
    name = "anthropic"
    local = False
    default_url = ANTHROPIC_URL

    def __init__(self, settings: dict[str, Any], *, key: str | None = None, options: dict[str, Any] | None = None,
                 label: str | None = None, force_eager: bool = False, effort: str | None = None):
        super().__init__(settings, key=key, options=options, label=label or "Claude")
        self.model = self.model or DEFAULT_MODEL
        self.effort = effort or self.settings.get("effort") or "high"
        self.force_eager = force_eager
        self.official = self.base_url.rstrip("/").lower() == ANTHROPIC_URL
        self._model_info: dict[str, dict[str, Any]] = {}
        self.timeout = float(self.options.get("timeout_s") or 120)

    # ------------------------------------------------------------------ wire helpers
    def headers(self, betas: list[str] | None = None) -> dict[str, str]:
        if not self.key:
            raise error("not_configured", provider=self.name, message="No API key for Claude is set.",
                        hint="Open Assistant settings and paste your Anthropic API key (it starts with sk-ant-).")
        h = {"x-api-key": self.key, "anthropic-version": API_VERSION}
        if betas:
            h["anthropic-beta"] = ",".join(betas)
        return h

    def model_label(self, model: str | None = None) -> str:
        m = model or self.model or DEFAULT_MODEL
        return LABELS.get(m) or (self._model_info.get(m) or {}).get("display_name") or m

    def eager(self) -> bool:
        return (self.official or self.force_eager) and "eager" not in DISABLED_FEATURES

    def tool_json(self, t: ToolSpec) -> dict[str, Any]:
        d: dict[str, Any] = {"name": t.name, "description": t.description, "input_schema": t.schema}
        if self.eager():
            d["eager_input_streaming"] = True
        return d

    def body(self, tr: Transcript, model: str, effort: str | None = None) -> tuple[dict[str, Any], list[str]]:
        traits = traits_for(model, self._model_info.get(model))
        betas: list[str] = []
        body: dict[str, Any] = {"model": model, "max_tokens": MAX_TOKENS, "stream": True,
                                "system": [{"type": "text", "text": tr.system, "cache_control": {"type": "ephemeral"}}]}
        if tr.tools:
            body["tools"] = [self.tool_json(t) for t in tr.tools]
        if traits.thinking:
            th: dict[str, Any] = {"type": "adaptive"}
            if traits.updates and self.settings.get("progress_notes", True) and "updates" not in DISABLED_FEATURES:
                th["display"] = "updates"
                betas.append(BETA_UPDATES)
            body["thinking"] = th
        eff = effort or self.effort
        if traits.efforts:
            if eff not in traits.efforts:
                eff = "high" if "high" in traits.efforts else traits.efforts[-1]
            body["output_config"] = {"effort": eff}
        body["cache_control"] = {"type": "ephemeral"}
        if self.official and traits.fallbacks and self.settings.get("fallbacks", True) \
                and "fallbacks" not in DISABLED_FEATURES:
            body["fallbacks"] = "default"
            betas.append(BETA_FALLBACK)
        body["messages"] = tr.native
        return body, betas

    # ------------------------------------------------------------------ conversation
    def capabilities(self, model: str) -> Capabilities:
        info = self._model_info.get(model) or {}
        vision = ((info.get("capabilities") or {}).get("image_input") or {}).get("supported")
        return Capabilities(tools=True, vision=True if vision is None else bool(vision),
                            context_tokens=info.get("max_input_tokens"), json_schema=False,
                            max_output_tokens=MAX_TOKENS)

    def add_user(self, tr: Transcript, text: str, images: list[ImagePart]) -> None:
        content: list[dict[str, Any]] = [{"type": "image", "source": {"type": "base64", "media_type": im.media_type,
                                                                      "data": im.data_b64}} for im in images]
        content.append({"type": "text", "text": text})
        tr.native.append({"role": "user", "content": content})

    def add_tool_results(self, tr: Transcript, results: list[ToolResult]) -> None:
        blocks = []
        for r in results:
            content: list[dict[str, Any]] = [{"type": "text", "text": r.content}]
            content += [{"type": "image", "source": {"type": "base64", "media_type": im.media_type,
                                                     "data": im.data_b64}} for im in r.images]
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": r.call_id, "content": content}
            if r.is_error:
                block["is_error"] = True
            blocks.append(block)
        tr.native.append({"role": "user", "content": blocks})

    def complete(self, tr: Transcript, *, on_event: EventFn, cancel: threading.Event,
                 effort: str | None = None) -> TurnResult:
        model = self.need_model()
        degraded: set[str] = set()
        overloaded = 0
        while True:
            body, betas = self.body(tr, model, effort)
            try:
                stream = with_retries(
                    lambda: open_stream(f"{self.base_url}/v1/messages", headers=self.headers(betas), body=body,
                                        timeout=self.timeout, cancel=cancel),
                    on_wait=lambda msg, d: self.emit(on_event, "retry", msg.replace("The service", "Claude")),
                    cancel=cancel, local=False, label="Claude")
            except HttpFailure as f:
                feat = self._degradable(f)
                if feat and not (feat & degraded):
                    degraded |= feat
                    DISABLED_FEATURES.update(feat)
                    what = {"updates": "progress notes", "fallbacks": "automatic fallback",
                            "eager": "streamed tool input"}
                    self.emit(on_event, "warning",
                              "Continuing without " + " and ".join(what[x] for x in sorted(feat)))
                    continue
                msg = f.message().lower()
                if f.status == 400 and "signature" in msg and "thinking" in msg:
                    raise AssistantError("history_mismatch", message="The conversation history no longer matches.",
                                         hint="Start a new conversation.", status=400, detail=f.message()) from None
                raise self.fail(f) from None
            try:
                return self._read(stream, tr, on_event, cancel)
            except _Overloaded:
                overloaded += 1                 # mid-stream: wait like an HTTP 529, then send the request again
                if overloaded > 2:
                    raise error("overloaded", provider=self.name, label="Claude") from None
                delay = http.RETRY_BASE * (2 ** (overloaded - 1)) * random.uniform(0.8, 1.2)
                self.emit(on_event, "retry", f"Claude is busy — trying again in {max(1, round(delay))} s")
                sleep_or_cancel(delay, cancel)
                continue
            except HttpFailure as f:
                raise self.fail(f) from None

    @staticmethod
    def _degradable(f: HttpFailure) -> set[str] | None:
        if f.status != 400:
            return None
        msg = f.message().lower()
        out: set[str] = set()
        if "eager_input_streaming" in msg:
            out.add("eager")
        if "fallbacks" in msg or "server-side-fallback" in msg:
            out.add("fallbacks")
        if "display" in msg or "thinking-display" in msg:
            out.add("updates")
        if not out and "anthropic-beta" in msg:
            out |= {"updates", "fallbacks"}
        return out or None

    def _read(self, stream: Any, tr: Transcript, on_event: EventFn, cancel: threading.Event) -> TurnResult:
        blocks: dict[int, dict[str, Any]] = {}
        partial: dict[int, list[str]] = {}
        order: list[int] = []
        usage: dict[str, Any] = {}
        model = self.model or ""
        stop_reason = None
        stop_details = None
        got_stop = False
        for event, data in stream.iter_sse(cancel):
            try:
                ev = json.loads(data)
            except ValueError:
                raise error("bad_response", provider=self.name, label="Claude", detail=data[:300]) from None
            et = ev.get("type") or event
            if et == "message_start":
                msg = ev.get("message") or {}
                model = msg.get("model") or model
                usage.update({k: v for k, v in (msg.get("usage") or {}).items() if isinstance(v, (int, float))})
            elif et == "content_block_start":
                i = int(ev.get("index", len(order)))
                blk = dict(ev.get("content_block") or {})
                if blk.get("type") == "tool_use":
                    blk["input"] = {}
                    partial[i] = []
                blocks[i] = blk
                order.append(i)
            elif et == "content_block_delta":
                i = int(ev.get("index", 0))
                d = ev.get("delta") or {}
                blk = blocks.setdefault(i, {"type": "text", "text": ""})
                dt = d.get("type")
                if dt == "text_delta":
                    blk["text"] = blk.get("text", "") + d.get("text", "")
                elif dt == "thinking_delta":
                    blk["thinking"] = blk.get("thinking", "") + d.get("thinking", "")
                elif dt == "signature_delta":
                    blk["signature"] = blk.get("signature", "") + d.get("signature", "")
                elif dt == "input_json_delta":
                    partial.setdefault(i, []).append(d.get("partial_json", ""))
            elif et == "content_block_stop":
                i = int(ev.get("index", 0))
                blk = blocks.get(i) or {}
                if blk.get("type") == "thinking" and blk.get("thinking", "").strip():
                    self.emit(on_event, "note", blk["thinking"].strip())
            elif et == "message_delta":
                d = ev.get("delta") or {}
                stop_reason = d.get("stop_reason", stop_reason)
                stop_details = d.get("stop_details") or ev.get("stop_details") or stop_details
                usage.update({k: v for k, v in (ev.get("usage") or {}).items() if isinstance(v, (int, float))})
            elif et == "message_stop":
                got_stop = True
                break
            elif et == "error":
                err = ev.get("error") or {}
                if err.get("type") == "overloaded_error":
                    raise _Overloaded()
                raise error("provider_error", provider=self.name, label="Claude",
                            short=str(err.get("message") or err.get("type") or "stream error"),
                            detail=json.dumps(err)[:500])
        if cancel.is_set():
            raise Cancelled()
        if not got_stop and stop_reason is None:
            raise error("bad_response", provider=self.name, label="Claude", detail="the answer stopped early")
        content = [blocks[i] for i in order]
        calls: list[ToolCall] = []
        for i in order:
            blk = blocks[i]
            if blk.get("type") != "tool_use":
                continue
            raw = "".join(partial.get(i, []))
            call = ToolCall(id=str(blk.get("id") or f"toolu_{i}"), name=str(blk.get("name") or ""), input=None,
                            raw_input=raw)
            try:
                val = json.loads(raw) if raw.strip() else {}
                if isinstance(val, dict):
                    blk["input"] = val
                    call.input = val
                else:
                    call.parse_error = "the input is not a JSON object"
            except ValueError as e:
                call.parse_error = str(e)
            calls.append(call)
        # fallback echo rule: before the last fallback block only text (and the fallback markers) are kept
        last_fb = max((k for k, b in enumerate(content) if b.get("type") == "fallback"), default=-1)
        echoed = []
        dropped_ids: set[str] = set()
        for k, b in enumerate(content):
            if k < last_fb and b.get("type") not in ("text", "fallback"):
                if b.get("type") == "tool_use":
                    dropped_ids.add(str(b.get("id")))
                continue
            if b.get("type") == "text" and not b.get("text"):
                continue                    # the API refuses empty text blocks in a request
            echoed.append(b)
        calls = [c for c in calls if c.id not in dropped_ids]
        if echoed:
            # an empty answer is not kept: the API refuses an empty assistant message anywhere but last, and an
            # empty turn has no thinking to preserve (the next user message simply follows the previous one)
            tr.native.append({"role": "assistant", "content": echoed})
        text = "\n".join(b.get("text", "") for b in echoed if b.get("type") == "text").strip()
        stop = {"end_turn": "end", "tool_use": "tool_use", "max_tokens": "max_tokens", "refusal": "refusal",
                "model_context_window_exceeded": "max_tokens", "stop_sequence": "end"}.get(stop_reason or "", "other")
        if stop == "other" and calls:
            stop = "tool_use"
        refusal = None
        if stop == "refusal":
            sd = stop_details or {}
            refusal = {"category": sd.get("category"), "explanation": sd.get("explanation")}
        notes = [b["thinking"].strip() for b in echoed if b.get("type") == "thinking" and (b.get("thinking") or "").strip()]
        return TurnResult(text=text, notes=notes, tool_calls=calls, stop=stop, refusal=refusal,
                          usage={k: usage.get(k, 0) for k in ("input_tokens", "output_tokens",
                                                              "cache_read_input_tokens", "cache_creation_input_tokens")},
                          model=model)

    # ------------------------------------------------------------------ models and test
    def list_models(self) -> list[ModelInfo]:
        try:
            _, _, data = request_json("GET", f"{self.base_url}/v1/models?limit=100", headers=self.headers(),
                                      timeout=15, cancel=self.cancel)
        except HttpFailure as f:
            raise self.fail(f) from None
        rows = (data or {}).get("data") or []
        rank = {m["id"]: i for i, m in enumerate(RECOMMENDED_ANTHROPIC)}
        notes = {m["id"]: m["note"] for m in RECOMMENDED_ANTHROPIC}
        out = []
        for r in rows:
            mid = str(r.get("id") or "")
            if not mid:
                continue
            self._model_info[mid] = r
            vision = ((r.get("capabilities") or {}).get("image_input") or {}).get("supported")
            older = is_older(mid) or not traits_for(mid, r).thinking and not mid.startswith("claude-haiku-4-5")
            out.append(ModelInfo(id=mid, label=LABELS.get(mid) or r.get("display_name") or mid, tools=True,
                                 vision=True if vision is None else bool(vision), context=r.get("max_input_tokens"),
                                 recommended=mid in rank,
                                 note=notes.get(mid, "") or ("Older model" if older else "")))
        out.sort(key=lambda m: (rank.get(m.id, 99), -_ts(self._model_info.get(m.id, {}).get("created_at"))))
        return out

    def test(self, deep: bool = False) -> TestResult:
        res = TestResult(ok=False, provider=self.name, base_url=self.base_url, model=self.model)
        t0 = time.monotonic()
        try:
            _, _, info = request_json("GET", f"{self.base_url}/v1/models/{self.need_model()}", headers=self.headers(),
                                      timeout=15, cancel=self.cancel)
        except HttpFailure as f:
            res.error = self.fail(f).to_dict()
            return res
        except AssistantError as e:
            res.error = e.to_dict()
            return res
        res.latency_ms = int((time.monotonic() - t0) * 1000)
        if isinstance(info, dict):
            self._model_info[self.model or ""] = info
        caps = self.capabilities(self.model or "")
        res.server = "Anthropic API" if self.official else f"Anthropic-compatible API at {self.host}"
        res.capabilities = {"tools": True, "vision": caps.vision, "context_tokens": caps.context_tokens, "mode": "tools"}
        if not self.official:
            res.warnings.append("This is not Anthropic's own address; requests go to " + self.host + ".")
        if not traits_for(self.model or "", self._model_info.get(self.model or "")).thinking \
                and not (self.model or "").startswith("claude-haiku-4-5"):
            res.warnings.append(f"{self.model_label()} is an older model without adaptive thinking: it works, but "
                                "a current model (Claude Opus 5.5 or Sonnet 5.5) gives better results.")
        if deep:
            ok, why = self._deep_test()
            if not ok:
                res.error = why
                return res
        res.ok = True
        return res

    def _deep_test(self) -> tuple[bool, dict | None]:
        tr = self.new_transcript("You are testing a connection. Call the ping tool once, then stop.",
                                 [ToolSpec("ping", "Answers pong. Call it once.",
                                           {"type": "object", "properties": {}, "additionalProperties": False})])
        self.add_user(tr, "Call the ping tool now.", [])
        try:
            turn = self.complete(tr, on_event=lambda e: None, cancel=threading.Event(), effort="low")
        except AssistantError as e:
            return False, e.to_dict()
        if not any(c.name == "ping" for c in turn.tool_calls):
            return False, error("tools_unsupported", provider=self.name, label="Claude").to_dict()
        return True, None


def _ts(v: Any) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0
