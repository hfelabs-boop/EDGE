"""LM Studio's local server (default http://localhost:1234/v1): OpenAI-compatible, no key.

A best-effort probe of ``/api/v0/models`` (LM Studio's own listing) tells which models are loaded, which can
see pictures (``type: vlm``) and their context length; a 404 there is ignored (older versions).
"""

from __future__ import annotations

import time
from typing import Any

from ..errors import AssistantError, error
from ..http import HttpFailure, request_json
from .base import Capabilities, ModelInfo, TestResult
from .openai_compat import OpenAICompatProvider


class LMStudioProvider(OpenAICompatProvider):
    name = "lmstudio"
    local = True
    default_url = "http://localhost:1234/v1"

    def __init__(self, settings: dict[str, Any], *, key: str | None = None, options: dict[str, Any] | None = None,
                 label: str | None = None):
        settings = {**(settings or {}), "preset": "custom"}
        if not settings.get("base_url"):
            settings["base_url"] = self.default_url
        super().__init__(settings, key=None, options=options, label=label or "LM Studio")
        self.local = True
        self.timeout, self.first_byte = 180.0, 600.0
        self.max_param = "max_tokens"
        t = self.settings.get("temperature")
        self.temperature = float(t) if t is not None else 0.2
        self._v0: dict[str, dict[str, Any]] | None = None

    @property
    def root(self) -> str:
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    def probe(self) -> dict[str, dict[str, Any]]:
        if self._v0 is None:
            self._v0 = {}
            try:
                _, _, data = request_json("GET", f"{self.root}/api/v0/models", timeout=10, local=True,
                                          cancel=self.cancel)
                for m in (data or {}).get("data") or []:
                    if isinstance(m, dict) and m.get("id"):
                        self._v0[str(m["id"])] = m
            except HttpFailure:
                pass
        return self._v0

    def capabilities(self, model: str) -> Capabilities:
        caps = super().capabilities(model)
        info = self.probe().get(model) or {}
        if info.get("type") in ("vlm", "llm") and "vision" not in self.disabled:
            caps.vision = info["type"] == "vlm"
        ctx = info.get("loaded_context_length") or info.get("max_context_length")
        caps.context_tokens = ctx if isinstance(ctx, int) else None     # unknown: let the server say
        return caps

    def list_models(self) -> list[ModelInfo]:
        v0 = self.probe()
        rows = self._get_models()
        out = []
        for r in rows:
            mid = str(r["id"])
            info = v0.get(mid) or {}
            if info.get("type") == "embeddings" or "embed" in mid.lower() and not info:
                continue
            ctx = info.get("loaded_context_length") or info.get("max_context_length")
            out.append(ModelInfo(id=mid, label=mid + (" (loaded)" if info.get("state") == "loaded" else ""),
                                 vision=(info.get("type") == "vlm") if info else None, context=ctx,
                                 recommended=info.get("state") == "loaded"))
        out.sort(key=lambda m: (not m.recommended, m.id))
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
        v0 = self.probe()
        res.server = "LM Studio"
        res.models = len(rows)
        loaded = [k for k, v in v0.items() if v.get("state") == "loaded" and v.get("type") != "embeddings"]
        if v0 and not loaded:
            res.error = error("no_model_loaded", provider=self.name).to_dict()
            return res
        if not self.model:
            res.warnings.append("Choose a model.")
            res.ok = True
            return res
        if self.model not in {str(r["id"]) for r in rows}:
            res.warnings.append(f"“{self.model}” is not loaded in LM Studio; load it, or pick a loaded model.")
        caps = self.capabilities(self.model)
        mode = "json" if self.settings.get("tool_mode") == "json" else "tools"
        res.capabilities = {"tools": caps.tools, "vision": caps.vision, "context_tokens": caps.context_tokens,
                            "mode": mode}
        if caps.context_tokens and caps.context_tokens < 16384:
            res.warnings.append(f"Context length {caps.context_tokens} is small: load the model with 16384 or more.")
        if deep:
            ok, why = self._deep_test()
            if not ok:
                res.error = why
                return res
        res.ok = True
        return res
