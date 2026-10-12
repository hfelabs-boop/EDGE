"""Neutral types shared by every model service, and the common provider plumbing."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from ..errors import AssistantError, error, map_failure


@dataclass
class Capabilities:
    tools: bool | None          # None = unknown: try native, degrade on error
    vision: bool | None
    context_tokens: int | None
    json_schema: bool           # constrained JSON output available (fallback mode)
    max_output_tokens: int


@dataclass
class ModelInfo:
    id: str
    label: str
    tools: bool | None = None
    vision: bool | None = None
    context: int | None = None
    recommended: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestResult:
    ok: bool
    provider: str
    base_url: str
    model: str | None
    latency_ms: int | None = None
    server: str | None = None
    models: int | None = None
    capabilities: dict | None = None
    warnings: list[str] = field(default_factory=list)
    error: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict


@dataclass
class ImagePart:
    media_type: str
    data_b64: str
    name: str


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict | None
    raw_input: str | None = None
    parse_error: str | None = None
    from_text: bool = False         # recovered from the model's text (no call id exists on the server)


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False
    images: list[ImagePart] = field(default_factory=list)


@dataclass
class TurnResult:
    text: str
    notes: list[str]
    tool_calls: list[ToolCall]
    stop: str                       # "end" | "tool_use" | "max_tokens" | "refusal" | "other"
    refusal: dict | None
    usage: dict
    model: str


class Transcript:
    """Provider-native conversation. APPEND-ONLY: system and tools are frozen at creation."""

    def __init__(self, system: str, tools: list[ToolSpec]):
        self.system = system
        self.tools = list(tools)
        self.native: list[Any] = []
        self.frozen = json.dumps({"system": system, "tools": [asdict(t) for t in self.tools]}, sort_keys=True,
                                 ensure_ascii=False, separators=(",", ":"))
        self.meta: dict[str, Any] = {}
        self.parent: Transcript | None = None
        self.base_len = 0

    def checkpoint(self) -> int:
        return len(self.native)

    def rollback(self, cp: int) -> None:
        """Drop the messages appended after ``cp`` (the un-committed tail of a failed or cancelled job only)."""
        del self.native[cp:]
        self.meta["tool_result_idx"] = [i for i in self.meta.get("tool_result_idx", []) if i < cp]

    def fork(self) -> "Transcript":
        """A copy a job works on; the conversation adopts it only when the job finishes (a stopped job's late
        steps can never change the history the next request uses). Messages are shared, never edited in place."""
        t = Transcript.__new__(Transcript)
        t.system, t.tools, t.frozen = self.system, list(self.tools), self.frozen
        t.native = list(self.native)
        t.meta = {k: (list(v) if isinstance(v, list) else v) for k, v in self.meta.items()}
        t.parent = self
        t.base_len = len(self.native)
        return t

    def mark_tool_result(self) -> None:
        """The last message carries a tool result as plain user text (JSON mode, recovered text calls): context
        trimming may shorten it like a native tool result."""
        self.meta.setdefault("tool_result_idx", []).append(len(self.native) - 1)

    def chars(self) -> int:
        return len(self.system) + sum(len(json.dumps(t.schema)) + len(t.description) for t in self.tools) + \
            sum(len(json.dumps(m, ensure_ascii=False)) for m in self.native)


EventFn = Callable[[dict], None]


class Provider:
    """Common plumbing; subclasses implement the wire format."""

    name = "base"
    local = False
    default_url = ""

    def __init__(self, settings: dict[str, Any], *, key: str | None = None, options: dict[str, Any] | None = None,
                 label: str | None = None):
        self.settings = dict(settings or {})
        self.key = key
        if key:
            from ..config import _SECRETS
            _SECRETS.add(key)            # so redact() can remove it from anything a server echoes
        self.options = dict(options or {})
        from ..config import normalize_base_url
        self.base_url = normalize_base_url(self.settings.get("base_url") or self.default_url, self.name)
        self.model: str | None = self.settings.get("model")
        self.label = label or self.name
        self.host = urlparse(self.base_url).hostname or ""
        self.disabled: set[str] = set()      # features this conversation had to drop after a 400
        self.cancel: threading.Event | None = None     # the running job's Stop, for requests outside complete()

    # ------------------------------------------------------------------ helpers
    def fail(self, f: Any) -> AssistantError:
        return map_failure(f, provider=self.name, model=self.model, base_url=self.base_url, label=self.label)

    def need_model(self) -> str:
        if not self.model:
            raise error("not_configured", provider=self.name, message="Choose a model in Assistant settings.",
                        hint="Open Assistant settings, press Refresh and pick a model.")
        return self.model

    @staticmethod
    def emit(on_event: EventFn | None, kind: str, text: str, **kw: Any) -> None:
        if on_event:
            on_event({"kind": kind, "text": text, **kw})

    def model_label(self, model: str | None = None) -> str:
        return model or self.model or self.label

    # ------------------------------------------------------------------ interface
    def capabilities(self, model: str) -> Capabilities:  # pragma: no cover - abstract
        raise NotImplementedError

    def list_models(self) -> list[ModelInfo]:  # pragma: no cover - abstract
        raise NotImplementedError

    def test(self, deep: bool = False) -> TestResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def new_transcript(self, system: str, tools: list[ToolSpec]) -> Transcript:
        return Transcript(system, tools)

    def add_user(self, tr: Transcript, text: str, images: list[ImagePart]) -> None:  # pragma: no cover
        raise NotImplementedError

    def add_tool_results(self, tr: Transcript, results: list[ToolResult]) -> None:  # pragma: no cover
        raise NotImplementedError

    def complete(self, tr: Transcript, *, on_event: EventFn, cancel: threading.Event) -> TurnResult:  # pragma: no cover
        raise NotImplementedError

    # ------------------------------------------------------------------ context management (not Anthropic)
    @staticmethod
    def estimate_tokens(tr: Transcript, extra_images: int = 0) -> int:
        chars = len(tr.system) + sum(len(t.description) + len(json.dumps(t.schema)) for t in tr.tools)
        images = extra_images
        for m in tr.native:
            images += _count_images(m)
            chars += len(_strip_images(m))
        return int(chars / 3.5) + 1000 * images

    def trim_context(self, tr: Transcript, context_tokens: int | None, on_event: EventFn | None,
                     limit: float = 0.85) -> int:
        """Replace the oldest tool results (never the latest two) until the estimate fits; returns the estimate."""
        est = self.estimate_tokens(tr)
        if not context_tokens or est <= limit * context_tokens:
            return est
        marked = set(tr.meta.get("tool_result_idx", []))
        idx = [i for i, m in enumerate(tr.native) if _is_tool_result(m) or i in marked]
        trimmed = 0
        for i in idx[:-2]:
            if est <= limit * context_tokens:
                break
            short = _trimmed(tr.native[i])
            if short is not None:
                tr.native[i] = short          # replaced, never edited: a forked transcript keeps its own copy
                trimmed += 1
                est = self.estimate_tokens(tr)
        if trimmed:
            self.emit(on_event, "warning", f"Removed {trimmed} older tool result(s) to keep the request short enough")
        return est


TRIMMED = json.dumps({"trimmed": "older tool result removed to save space"})


def _is_tool_result(m: Any) -> bool:
    return isinstance(m, dict) and m.get("role") == "tool"


def _trimmed(m: Any) -> dict | None:
    """The message with its content replaced by a short note (and no pictures), or None if it already is."""
    if not isinstance(m, dict) or m.get("content") == TRIMMED:
        return None
    return {**{k: v for k, v in m.items() if k != "images"}, "content": TRIMMED}


def _count_images(m: Any) -> int:
    if not isinstance(m, dict):
        return 0
    n = len(m.get("images") or [])
    c = m.get("content")
    if isinstance(c, list):
        n += sum(1 for p in c if isinstance(p, dict) and p.get("type") in ("image_url", "image"))
    return n


def _strip_images(m: Any) -> str:
    if not isinstance(m, dict):
        return json.dumps(m, ensure_ascii=False)
    c = m.get("content")
    parts = {k: v for k, v in m.items() if k not in ("images", "content")}
    if isinstance(c, list):
        c = [p for p in c if not (isinstance(p, dict) and p.get("type") in ("image_url", "image"))]
    parts["content"] = c
    return json.dumps(parts, ensure_ascii=False)
