"""Errors the assistant reports to people: a code, a plain message, what to do next.

Every message and detail passes through :func:`edge.assistant.config.redact` before it leaves this module,
so an API key a server echoes back never reaches the browser, the log or the terminal.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

PROVIDER_NAMES = {"anthropic": "Claude", "openai": "The service", "ollama": "Ollama", "lmstudio": "LM Studio"}

# code -> (message template, hint template). Templates use {provider}, {model}, {host}, {base_url}, {n},
# {retry_after}, {category}, {short}.
MESSAGES: dict[str, tuple[str, str]] = {
    "not_configured": ("The assistant isn't set up yet.",
                       "Open Assistant settings and choose Claude, an OpenAI-compatible service, Ollama or LM Studio."),
    "consent_required": ("Confirm that EDGE may send your request to {provider}.",
                         "Read the privacy note in Assistant settings and press Continue, or use a local model."),
    "server_not_running": ("{provider} isn't running on this computer (nothing answers at {base_url}).",
                           "Start {provider}, then press Test connection."),
    "connection_failed": ("Couldn't reach {host}.",
                          "Check the internet connection. Offline? Ollama or LM Studio work without internet."),
    "tls_failed": ("Couldn't make a secure connection to {host}.",
                   "Check the computer's date and time; if your institution uses a proxy, set HTTPS_PROXY."),
    "timeout": ("No answer from {provider} after {n} s.", "Try again in a moment, or ask for a smaller change."),
    "bad_key": ("{provider} didn't accept the API key.", "Paste the key again in Assistant settings."),
    "forbidden": ("This key isn't allowed to use {model}.",
                  "Check the key's organisation/workspace settings, or choose another model."),
    "billing": ("{provider} says the account has no credit left.",
                "Add credit in your account's billing page, or use a local model."),
    "model_not_found": ("The model “{model}” isn't available for this key.",
                        "Pick a model from the list (Refresh models)."),
    "model_not_pulled": ("The model “{model}” isn't downloaded in Ollama.",
                         "Run `ollama pull {model}` in a terminal, or pick an installed model."),
    "no_model_loaded": ("LM Studio has no model loaded.",
                        "Load a model in LM Studio (or `lms load <model>`), then press Test connection."),
    "rate_limited": ("{provider} is limiting requests right now.", "Wait {retry_after} s and try again."),
    "overloaded": ("{provider} is busy.", "Try again in a minute, or choose another model."),
    "context_too_long": ("The request is too long for {model}.",
                         "Attach fewer or smaller files, or start a new conversation."),
    "request_too_large": ("The request is too big to send.", "Attach fewer or smaller files."),
    "tools_unsupported": ("This model can't follow EDGE's instructions.", "Choose a model with tool support."),
    "refused": ("The model declined this request{category}.", "Rephrase the request (your text is back in the box), or choose another model."),
    "bad_response": ("{provider} sent an answer EDGE couldn't read.",
                     "Try again; if it keeps happening choose another model."),
    "provider_error": ("{provider} reported an error: {short}", ""),
    "cancelled": ("Stopped.", ""),
    "step_limit": ("The assistant needed more steps than allowed.",
                   "Apply what it did so far, or ask for a smaller change."),
    "busy": ("The assistant is still working on your last request.", "Wait for it to finish, or press Stop."),
    "redirected": ("{host} sent the request somewhere else, which EDGE doesn't follow (it would send your key along).",
                   "Check the address in Assistant settings."),
    "wrong_address": ("The address {base_url} doesn't lead to {provider}.",
                      "Check the address in Assistant settings."),
    "service_error": ("{provider} had a problem on its side ({short}).",
                      "Try again in a few minutes."),
    "out_of_memory": ("The model stopped: it doesn't fit in this computer's memory.",
                      "Choose a smaller model, or lower the context size."),
}
TLS_VERIFY_HINT = ("Your network presents a certificate this computer doesn't trust (common on institutional networks "
                   "that inspect traffic). Ask IT for the certificate file and set SSL_CERT_FILE to it; on a Mac with "
                   "Python from python.org, run “Install Certificates.command”.")
ADDRESS_HINTS = {
    "anthropic": "For Claude the address is https://api.anthropic.com (without /v1).",
    "ollama": "For Ollama the address is http://localhost:11434 (without /v1 or /api).",
    "lmstudio": "For LM Studio the address is http://localhost:1234/v1.",
    "openai": "OpenAI-compatible addresses usually end in /v1, e.g. https://api.openai.com/v1.",
}
SERVICE_HINTS = {"anthropic": "Try again in a few minutes (status.anthropic.com shows Claude's status)."}
MEMORY_WORDS = ("runner process has terminated", "out of memory", "unable to allocate", "cuda error: out of memory",
                "failed to allocate", "not enough memory", "insufficient memory")

LOCAL_HINTS = {
    ("server_not_running", "ollama"): "Start the Ollama app, or run `ollama serve` in a terminal, then press Test connection.",
    ("server_not_running", "lmstudio"): "In LM Studio open the Developer tab and switch the server on, or run "
                                        "`lms server start`.",
    ("timeout", "local"): "The model may still be loading — try again, or choose a smaller model.",
    ("context_too_long", "local"): "Raise the context length (Ollama: Context size in settings; LM Studio: Context "
                                   "Length when loading the model), attach fewer files, or start a new conversation.",
    ("bad_key", "anthropic"): "Paste the key again (it starts with sk-ant-). Keys are made at console.anthropic.com → "
                              "API keys.",
    ("bad_key", "openai"): "Paste the key again in Assistant settings (OpenAI: platform.openai.com → API keys; "
                           "OpenRouter: openrouter.ai → Keys).",
}
LOCAL_MESSAGES = {
    ("server_not_running", "ollama"): "Ollama isn't running on this computer (nothing answers at {base_url}).",
    ("server_not_running", "lmstudio"): "LM Studio's local server isn't running (nothing answers at {base_url}).",
}


class AssistantError(Exception):
    """A failure with a code the builder can act on, a message for people and a hint."""

    def __init__(self, code: str, message: str | None = None, hint: str | None = None, status: int | None = None,
                 retry_after: float | None = None, detail: str | None = None, **fmt: Any):
        tmpl, hint_tmpl = MESSAGES.get(code, ("{short}", ""))
        values = {"provider": "the assistant", "model": "this model", "host": "the server", "base_url": "",
                  "n": "?", "retry_after": int(retry_after or 60), "category": "", "short": code}
        values.update({k: v for k, v in fmt.items() if v is not None})
        from .config import redact
        self.code = code
        self.message = redact(message if message is not None else _fill(tmpl, values))
        self.hint = redact(hint if hint is not None else _fill(hint_tmpl, values))
        self.status = status
        self.retry_after = retry_after
        self.detail = redact(detail)[:500] if detail else None
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        from .config import redact
        return {"code": self.code, "message": redact(self.message), "hint": redact(self.hint or ""),
                "status": self.status, "retry_after": self.retry_after,
                "detail": redact(self.detail)[:500] if self.detail else None}


def _fill(tmpl: str, values: dict[str, Any]) -> str:
    try:
        out = tmpl.format(**values)
    except (KeyError, IndexError, ValueError):
        return tmpl
    if tmpl.startswith("{provider}") or tmpl.startswith("{host}"):
        out = capitalize(out)           # "the service is busy" -> "The service is busy"
    return out


def capitalize(text: str) -> str:
    """Upper-case the first letter of a sentence that starts with a name like "the service"."""
    return text[:1].upper() + text[1:] if text[:1].islower() and not text.startswith(("http", "localhost")) else text


def error(code: str, *, provider: str | None = None, **kw: Any) -> AssistantError:
    """Build an AssistantError with the provider-specific wording (local servers, key hints)."""
    name = kw.pop("label", None) or PROVIDER_NAMES.get(provider or "", provider or "the assistant")
    local = provider in ("ollama", "lmstudio")
    msg = LOCAL_MESSAGES.get((code, provider or ""))
    hint = LOCAL_HINTS.get((code, provider or "")) or (LOCAL_HINTS.get((code, "local")) if local else None)
    if msg is not None and "message" not in kw:
        kw["message"] = _fill(msg, {"base_url": kw.get("base_url", ""), "provider": name})
    if hint is not None and "hint" not in kw:
        kw["hint"] = hint
    return AssistantError(code, provider=name, **kw)


def _server_message(f: Any) -> str:
    """The error text a server put in its body (Anthropic, OpenAI, Ollama and LM Studio shapes)."""
    j = getattr(f, "body_json", None)
    if isinstance(j, dict):
        e = j.get("error")
        if isinstance(e, dict):
            return str(e.get("message") or e.get("type") or e)
        if isinstance(e, str):
            return e
        if j.get("message"):
            return str(j["message"])
    return (getattr(f, "body_text", "") or "").strip()[:500]


def _error_type(f: Any) -> str:
    j = getattr(f, "body_json", None)
    if isinstance(j, dict) and isinstance(j.get("error"), dict):
        return str(j["error"].get("type") or j["error"].get("code") or "")
    return ""


CONTEXT_WORDS = ("prompt is too long", "context_length_exceeded", "context length", "n_ctx", "maximum context",
                 "too many tokens", "context window", "context size", "exceeds the context")


def map_failure(f: Any, *, provider: str, model: str | None, base_url: str, label: str | None = None) -> AssistantError:
    """Turn an HttpFailure (or a transport exception) into an AssistantError with the right code and hint."""
    from .http import HttpFailure
    host = urlparse(base_url).netloc or base_url
    common = {"provider": provider, "model": model or "this model", "host": host, "base_url": base_url,
              "label": label}
    local = provider in ("ollama", "lmstudio")
    if isinstance(f, AssistantError):
        return f
    if not isinstance(f, HttpFailure):
        return error("provider_error", message=f"{type(f).__name__}: {f}", detail=str(f), **common)
    msg = _server_message(f)
    low = msg.lower()
    etype = _error_type(f).lower()
    detail = msg
    rid = (f.body_json or {}).get("request_id") if isinstance(f.body_json, dict) else None
    if rid:
        detail = f"{msg} (request id {rid})"
    status = f.status
    if f.reason == "redirect":
        return error("redirected", status=status, detail=detail, **common)
    if f.reason in ("connection_refused",) and local:
        return error("server_not_running", detail=detail, **common)
    if f.reason in ("connection_refused", "dns", "reset", "unreachable"):
        if local:
            return error("server_not_running", detail=detail, **common)
        return error("connection_failed", detail=detail, **common)
    if f.reason == "tls":
        tls_hint = {"hint": TLS_VERIFY_HINT} if "certificate_verify_failed" in (f.body_text or "").lower() \
            or "certificate verify failed" in (f.body_text or "").lower() else {}
        return error("tls_failed", detail=detail, **tls_hint, **common)
    if f.reason == "timeout":
        return error("timeout", n=int(getattr(f, "timeout", 0) or 0), detail=detail, **common)
    if "no models loaded" in low or "no model loaded" in low:
        return error("no_model_loaded", status=status, detail=detail, **common)
    if provider == "ollama" and ("try pulling" in low or (status == 404 and "not found" in low and "model" in low
                                                          and f.body_json is not None)):
        return error("model_not_pulled", status=status, detail=detail, **common)
    if status == 401 or etype in ("authentication_error", "invalid_api_key") or "invalid_api_key" in low:
        return error("bad_key", status=status, detail=detail, **common)
    if status == 402 or etype in ("billing_error", "insufficient_quota") or "insufficient_quota" in low \
            or "credit balance" in low or "purchase credits" in low:
        return error("billing", status=status, detail=detail, **common)
    if status == 403:
        return error("forbidden", status=status, detail=detail, **common)
    if status == 413 or any(w in low for w in CONTEXT_WORDS):
        return error("context_too_long", status=status, detail=detail, **common)
    if status is not None and 400 <= status < 500 and _tools_refused(low):
        return error("tools_unsupported", status=status, detail=detail, **common)
    if "unexpected endpoint" in low or (status in (404, 405) and _wrong_address(f, low, etype)):
        return error("wrong_address", status=status, detail=detail or f"HTTP {status} from {f.url or base_url}",
                     hint=ADDRESS_HINTS.get(provider, ADDRESS_HINTS["openai"]), **common)
    if status == 404:
        return error("model_not_found", status=status, detail=detail, **common)
    if status == 429:
        return error("rate_limited", status=status, retry_after=f.retry_after(), detail=detail, **common)
    if status in (529, 503) or etype == "overloaded_error":
        return error("overloaded", status=status, detail=detail, **common)
    if local and any(w in low for w in MEMORY_WORDS):
        return error("out_of_memory", status=status, detail=detail, **common)
    if status in (500, 502, 504) or etype in ("api_error", "timeout_error"):
        short = msg.splitlines()[0][:120] if msg else f"HTTP {status}"
        return error("service_error", status=status, detail=detail, short=short,
                     hint=SERVICE_HINTS.get(provider, MESSAGES["service_error"][1]), **common)
    if status is not None and 400 <= status < 600:
        short = msg.splitlines()[0][:200] if msg else f"HTTP {status}"
        return error("provider_error", status=status, detail=detail, short=short, **common)
    return error("bad_response", detail=detail, **common)


def _tools_refused(low: str) -> bool:
    """The model (or every route to it) can't call tools: switch to EDGE's JSON mode."""
    return ("does not support tools" in low or "function calling" in low or "support tool use" in low
            or "no endpoints found that support tool" in low
            or (("tool" in low or "function" in low)
                and any(w in low for w in ("not support", "unsupported", "not enabled", "not available"))))


def _wrong_address(f: Any, low: str, etype: str) -> bool:
    """A 404 from a route that doesn't exist (a wrong /v1, /api …), not from an unknown model."""
    if f.body_json is None:
        return True                     # "404 page not found" (Ollama's router), HTML pages, empty bodies
    if etype == "model_not_found" or low.startswith("model:") or "no endpoints found" in low:
        return False
    if "model" in low and any(w in low for w in ("not found", "does not exist", "not exist", "unknown", "no such",
                                                 "not available", "invalid model")):
        return False
    return True
