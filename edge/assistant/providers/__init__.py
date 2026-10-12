"""The model services the assistant can use."""

from __future__ import annotations

from typing import Any

from ..config import (CLOUD, LABELS, PROVIDERS, AssistantConfig, normalize_base_url, origin_of, resolve_key,
                      service_name)
from ..errors import error
from .base import Provider

PROVIDER_LABELS = dict(LABELS)


def get_provider(cfg: AssistantConfig, name: str | None = None, *, settings: dict[str, Any] | None = None,
                 model: str | None = None, effort: str | None = None) -> Provider:
    """The configured provider (or ``name``), with unsaved ``settings`` (from Test connection) laid over it."""
    name = name or cfg.provider
    if name not in PROVIDERS:
        raise error("not_configured")
    s = cfg.provider_settings(name)
    key, _ = resolve_key(cfg, name)
    if settings:
        saved = origin_of(normalize_base_url(s.get("base_url") or "", name))
        s.update({k: v for k, v in settings.items() if v is not None and k != "api_key"})
        if name == "openai" and settings.get("preset") and not settings.get("base_url"):
            from ..config import PRESETS
            s["base_url"] = PRESETS[settings["preset"]][0] or s.get("base_url")
        if origin_of(normalize_base_url(s.get("base_url") or "", name)) != saved:
            key = None           # the stored (or environment) key never goes to an address that isn't saved
        if settings.get("api_key"):
            key = settings["api_key"]
    if model:
        s["model"] = model
    opts = cfg.options
    if name == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(s, key=key, options=opts, effort=effort)
    if name == "openai":
        from .openai_compat import OpenAICompatProvider
        tmp = AssistantConfig({**cfg.data, "openai": s}, cfg.path)
        return OpenAICompatProvider(s, key=key, options=opts, label=service_name(tmp, "openai"))
    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(s, options=opts)
    from .lmstudio import LMStudioProvider
    return LMStudioProvider(s, options=opts)


__all__ = ["get_provider", "PROVIDER_LABELS", "CLOUD"]
