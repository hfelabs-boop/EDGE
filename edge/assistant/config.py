"""Assistant settings: which model service to use, its address, model and API key.

Stored in the user's configuration folder (never in the experiments folder, which is shared, backed up and
bundled), in ``assistant.json``, readable only by the user (mode 0600 on macOS/Linux). The API key is
write-only from the browser: :func:`public_view` reports whether one is set and its last four characters,
never the key itself. :func:`redact` removes keys from any text before it is shown or logged.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROVIDERS = ("anthropic", "openai", "ollama", "lmstudio")
CLOUD = ("anthropic", "openai")
LABELS = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI-compatible", "ollama": "Ollama (on this computer)",
          "lmstudio": "LM Studio (on this computer)"}
PRESETS = {"openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OpenAI"),
           "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OpenRouter"),
           "custom": (None, "OPENAI_API_KEY", "the service")}
ANTHROPIC_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
TOOL_MODES = ("auto", "native", "json")
RECOMMENDED_ANTHROPIC = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Best results (default)"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Faster, lower cost"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "Fastest, lowest cost; small edits"},
    {"id": "claude-fable-5-1", "label": "Claude Fable 5.1", "note": "Most capable, highest cost"},
]

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "provider": None,
    "anthropic": {"api_key": None, "base_url": ANTHROPIC_URL, "model": DEFAULT_MODEL, "effort": "high",
                  "fallbacks": True, "progress_notes": True},
    "openai": {"preset": "openai", "base_url": "https://api.openai.com/v1", "api_key": None, "model": None},
    "ollama": {"base_url": "http://localhost:11434", "model": None, "num_ctx": 16384, "keep_alive": "15m",
               "temperature": 0.2, "tool_mode": "auto"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "model": None, "temperature": 0.2, "tool_mode": "auto"},
    "options": {"send_images": True, "auto_dry_run": True, "keep_history": True, "max_steps": None, "timeout_s": None},
    "consent": {},
}

# Key-shaped tokens. Anchored so that words merely containing "sk-" ("task-switching-…", "desk-lamp-…") are left
# alone: a key starts a token (after a space, quote, = or line start), never in the middle of a word.
KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_\-.])(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|"
                         r"Bearer\s+[A-Za-z0-9._\-]{16,})")
# the address each provider (and OpenAI-compatible preset) normally uses: keys from the environment go only there
DEFAULT_HOSTS = {"anthropic": "api.anthropic.com", "openai:openai": "api.openai.com",
                 "openai:openrouter": "openrouter.ai"}
MODEL_ID = re.compile(r"^[\w.:/@+\-]{1,200}$")
_SECRETS: set[str] = set()          # every key this process has seen (config or environment), for redact()


class ConfigError(ValueError):
    """A setting the builder sent can't be used; ``field`` names it."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


# ============================================================================ location
def config_dir() -> Path:
    env = os.environ.get("EDGE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "EDGE"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EDGE"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "edge"


def config_path() -> Path:
    return config_dir() / "assistant.json"


def display_path(p: Path) -> str:
    """The path with the home folder written as ~ (shown to people)."""
    try:
        return "~/" + str(Path(p).resolve().relative_to(Path.home().resolve())).replace("\\", "/")
    except (ValueError, OSError, RuntimeError):
        return str(p)


# ============================================================================ the config object
@dataclass
class AssistantConfig:
    data: dict[str, Any]
    path: Path
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []

    @property
    def provider(self) -> str | None:
        p = self.data.get("provider")
        return p if p in PROVIDERS else None

    def provider_settings(self, name: str) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULTS.get(name) or {})
        merged.update({k: v for k, v in (self.data.get(name) or {}).items() if v is not None or k == "api_key"})
        return merged

    @property
    def options(self) -> dict[str, Any]:
        o = copy.deepcopy(DEFAULTS["options"])
        o.update({k: v for k, v in (self.data.get("options") or {}).items() if v is not None})
        return o


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(DEFAULTS)
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v          # unknown keys are kept (forward compatibility)
    return out


def load_config() -> AssistantConfig:
    path = config_path()
    warnings: list[str] = []
    data: dict[str, Any] = {}
    if path.exists():
        if os.name == "posix":
            try:
                if path.stat().st_mode & 0o077:
                    os.chmod(path, 0o600)
                    warnings.append("config_permissions_fixed")
            except OSError:
                pass
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                path.replace(path.with_name(f"assistant.json.broken-{stamp}"))
            except OSError:
                pass
            warnings.append("config_error")
            data = {}
    cfg = AssistantConfig(_merge_defaults(data), path, warnings)
    for name in CLOUD:
        k = (cfg.data.get(name) or {}).get("api_key")
        if isinstance(k, str) and k:
            _SECRETS.add(k)
    return cfg


def save_config(cfg: AssistantConfig) -> None:
    d = cfg.path.parent
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    fd, tmp = tempfile.mkstemp(prefix=".assistant.", suffix=".tmp", dir=str(d))     # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg.data, f, indent=2, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, cfg.path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(cfg.path, 0o600)
    except OSError:
        pass


# ============================================================================ validation
def is_local_host(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip("[]").lower()
    if h in ("localhost", "::1") or h.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def check_base_url(url: Any, provider: str, field: str) -> str:
    if not isinstance(url, str) or not url.strip() or len(url) > 500:
        raise ConfigError(field, "Enter the service's address, e.g. https://api.openai.com/v1")
    url = url.strip().rstrip("/")
    try:
        u = urlparse(url)
        _ = u.port                              # raises for a port that isn't a number from 0 to 65535
    except ValueError:
        raise ConfigError(field, "That address can't be used (check the brackets and the port number)") from None
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ConfigError(field, "The address must start with http:// or https://")
    if u.username or u.password or "@" in u.netloc:
        raise ConfigError(field, "Don't put a user name or password in the address; use the API key field")
    if u.query or u.fragment:
        raise ConfigError(field, "The address can't contain ? or #")
    if u.scheme == "http" and not is_local_host(u.hostname) and provider in CLOUD:
        raise ConfigError(field, "Online services need an https:// address (an API key is never sent unencrypted)")
    return normalize_base_url(url, provider)


def normalize_base_url(url: str, provider: str) -> str:
    """The address as each provider expects it, whatever was pasted: Claude without /v1 (EDGE adds /v1/messages),
    Ollama without /v1 or /api (it uses /api/chat), LM Studio with /v1, OpenAI-compatible without
    /chat/completions."""
    url = (url or "").strip().rstrip("/")
    low = url.lower()

    def cut(*tails: str) -> str:
        nonlocal url, low
        changed = True
        while changed:
            changed = False
            for t in tails:
                if low.endswith(t):
                    url, low = url[: -len(t)].rstrip("/"), low[: -len(t)].rstrip("/")
                    changed = True
        return url
    if provider == "anthropic":
        return cut("/messages", "/v1")
    if provider == "ollama":
        return cut("/chat", "/chat/completions", "/api", "/v1")
    if provider in ("openai", "lmstudio"):
        url = cut("/chat/completions", "/completions")
        if provider == "lmstudio" and not urlparse(url).path.strip("/"):
            url += "/v1"
        return url
    return url


def origin_of(url: Any) -> tuple[str, str, int | None]:
    """(scheme, host, port) of an address — what decides where a key goes."""
    try:
        u = urlparse(str(url or ""))
        return u.scheme.lower(), (u.hostname or "").lower(), u.port or {"http": 80, "https": 443}.get(u.scheme.lower())
    except ValueError:
        return "", "", None


def _check_model(v: Any, field: str) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not MODEL_ID.match(v):
        raise ConfigError(field, "A model name has letters, digits and . : / @ + - _ only (at most 200 characters)")
    return v


def _check_key(v: Any, field: str) -> str | None:
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not 8 <= len(v) <= 400 or any(c.isspace() for c in v):
        raise ConfigError(field, "That doesn't look like an API key (8–400 characters, no spaces)")
    return v


def _bool(v: Any, field: str) -> bool:
    if not isinstance(v, bool):
        raise ConfigError(field, f"'{field}' must be true or false")
    return v


def validate_patch(patch: Any) -> dict[str, Any]:
    """Check a settings change from the builder or the CLI; return a cleaned copy."""
    if not isinstance(patch, dict):
        raise ConfigError("", "the settings must be a JSON object")
    out: dict[str, Any] = {}
    for k, v in patch.items():
        if k == "provider":
            if v is not None and v not in PROVIDERS:
                raise ConfigError("provider", f"Choose one of: {', '.join(PROVIDERS)}")
            out[k] = v
        elif k in PROVIDERS:
            if not isinstance(v, dict):
                raise ConfigError(k, f"'{k}' must be an object")
            out[k] = _validate_provider(k, v)
        elif k == "options":
            if not isinstance(v, dict):
                raise ConfigError(k, "'options' must be an object")
            o: dict[str, Any] = {}
            for ok, ov in v.items():
                f = f"options.{ok}"
                if ok in ("send_images", "auto_dry_run", "keep_history"):
                    o[ok] = _bool(ov, f)
                elif ok == "max_steps":
                    if ov is not None and (isinstance(ov, bool) or not isinstance(ov, int) or not 1 <= ov <= 100):
                        raise ConfigError(f, "max_steps must be a whole number from 1 to 100")
                    o[ok] = ov
                elif ok == "timeout_s":
                    if ov is not None and (isinstance(ov, bool) or not isinstance(ov, (int, float)) or not 30 <= ov <= 7200):
                        raise ConfigError(f, "timeout_s must be between 30 and 7200 seconds")
                    o[ok] = ov
                else:
                    raise ConfigError(f, f"unknown option '{ok}'")
            out[k] = o
        elif k in ("version", "consent"):
            continue                       # not settable this way
        else:
            raise ConfigError(k, f"unknown setting '{k}'")
    return out


def _validate_provider(name: str, v: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, val in v.items():
        f = f"{name}.{k}"
        if k == "base_url":
            out[k] = None if val in (None, "") else check_base_url(val, name, f)
        elif k == "api_key" and name in CLOUD:
            out[k] = _check_key(val, f)
        elif k == "model":
            out[k] = _check_model(val, f)
        elif k == "effort" and name == "anthropic":
            if val not in EFFORTS:
                raise ConfigError(f, f"effort must be one of {', '.join(EFFORTS)}")
            out[k] = val
        elif k in ("fallbacks", "progress_notes") and name == "anthropic":
            out[k] = _bool(val, f)
        elif k == "preset" and name == "openai":
            if val not in PRESETS:
                raise ConfigError(f, f"service must be one of {', '.join(PRESETS)}")
            out[k] = val
        elif k == "num_ctx" and name == "ollama":
            if isinstance(val, bool) or not isinstance(val, int) or not 2048 <= val <= 262144:
                raise ConfigError(f, "context size must be a whole number from 2048 to 262144")
            out[k] = val
        elif k == "temperature" and name in ("ollama", "lmstudio"):
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 <= val <= 1:
                raise ConfigError(f, "temperature must be between 0 and 1")
            out[k] = float(val)
        elif k == "tool_mode" and name in ("ollama", "lmstudio"):
            if val not in TOOL_MODES:
                raise ConfigError(f, f"tool mode must be one of {', '.join(TOOL_MODES)}")
            out[k] = val
        elif k == "keep_alive" and name == "ollama":
            if not isinstance(val, (str, int)) or isinstance(val, bool) or len(str(val)) > 20:
                raise ConfigError(f, "keep_alive must be like 15m")
            out[k] = val
        else:
            raise ConfigError(f, f"unknown setting '{f}'")
    return out


def update_config(patch: dict[str, Any]) -> AssistantConfig:
    """Validate, merge and save a settings change. ``api_key: ""`` or ``null`` removes a stored key.

    A stored key belongs to the address it was entered for: when a change sends a cloud provider to another
    address (another host, port or scheme, or another OpenAI-compatible service) without giving a key in the
    same change, the stored key is removed and ``cfg.warnings`` gets ``"api_key_cleared"`` — so the key can
    never be redirected to an address that was not there when it was typed."""
    clean = validate_patch(patch)
    cfg = load_config()
    before = {name: origin_of(cfg.provider_settings(name).get("base_url")) for name in CLOUD}
    for k, v in clean.items():
        if isinstance(v, dict):
            cur = cfg.data.setdefault(k, {})
            if not isinstance(cur, dict):
                cur = cfg.data[k] = {}
            if k == "openai" and "preset" in v and "base_url" not in v and v["preset"] != "custom":
                v = {**v, "base_url": PRESETS[v["preset"]][0]}
            for kk, vv in v.items():
                if vv is None and kk != "api_key" and kk in (DEFAULTS.get(k) or {}):
                    cur[kk] = copy.deepcopy(DEFAULTS[k][kk])
                else:
                    cur[kk] = vv
        else:
            cfg.data[k] = v
    for name in CLOUD:
        sect = cfg.data.get(name) or {}
        if sect.get("api_key") and "api_key" not in (clean.get(name) or {}) \
                and origin_of(cfg.provider_settings(name).get("base_url")) != before[name]:
            sect["api_key"] = None
            cfg.warnings.append("api_key_cleared")
    for name in CLOUD:
        key = (cfg.data.get(name) or {}).get("api_key")
        if key:
            _SECRETS.add(key)
    save_config(cfg)
    return cfg


# ============================================================================ keys
def env_key_name(cfg: AssistantConfig, provider: str) -> str | None:
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "openai":
        preset = cfg.provider_settings("openai").get("preset") or "openai"
        return PRESETS.get(preset, PRESETS["openai"])[1]
    return None


def default_host(cfg: AssistantConfig, provider: str) -> str | None:
    """The host a key from the environment may be sent to (the service's own address), or None."""
    if provider == "openai":
        return DEFAULT_HOSTS.get(f"openai:{cfg.provider_settings('openai').get('preset') or 'openai'}")
    return DEFAULT_HOSTS.get(provider)


def resolve_key(cfg: AssistantConfig, provider: str) -> tuple[str | None, str | None]:
    """(key, source): a stored key wins ("config"), then the environment ("env:NAME"), else (None, None).

    A key from the environment is used only with the service's own address (api.anthropic.com, api.openai.com,
    openrouter.ai): for any other address the key must be entered in Assistant settings, so changing the address
    can never send an environment key somewhere else."""
    if provider not in CLOUD:
        return None, None
    stored = (cfg.data.get(provider) or {}).get("api_key")
    if isinstance(stored, str) and stored:
        _SECRETS.add(stored)
        return stored, "config"
    name = env_key_name(cfg, provider)
    val = os.environ.get(name or "") if name else None
    if val:
        _SECRETS.add(val)
        o = origin_of(cfg.provider_settings(provider).get("base_url"))
        if o[0] == "https" and o[1] == default_host(cfg, provider) and o[2] == 443:
            return val, f"env:{name}"
    return None, None


def _env_secrets() -> list[str]:
    out = []
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        v = os.environ.get(name)
        if v and len(v) >= 8:
            out.append(v)
    return out


def redact(text: Any, cfg: AssistantConfig | None = None) -> str:
    """Remove every known API key (config and environment) and anything that looks like one."""
    if text is None:
        return ""
    s = str(text)
    secrets = set(_SECRETS) | set(_env_secrets())
    if cfg is not None:
        for name in CLOUD:
            k = (cfg.data.get(name) or {}).get("api_key")
            if k:
                secrets.add(k)
    for k in sorted(secrets, key=len, reverse=True):
        if k and len(k) >= 8 and k in s:
            s = s.replace(k, "…" + k[-4:])
    return KEY_PATTERN.sub("«key removed»", s)


# ============================================================================ consent and the public view
def remote_host(cfg: AssistantConfig, provider: str) -> str | None:
    """For Ollama / LM Studio: the host when it is another computer (None when it runs on this one)."""
    if provider in CLOUD or provider not in PROVIDERS:
        return None
    host = urlparse(cfg.provider_settings(provider).get("base_url") or "").hostname
    return None if is_local_host(host) else (host or "?")


def anthropic_host(cfg: AssistantConfig) -> str | None:
    """The host of a Claude address that isn't Anthropic's own (a gateway or proxy), else None."""
    host = (urlparse(cfg.provider_settings("anthropic").get("base_url") or ANTHROPIC_URL).hostname or "").lower()
    return None if host in ("", DEFAULT_HOSTS["anthropic"]) else host


def consent_key(cfg: AssistantConfig, provider: str) -> str:
    if provider == "anthropic" and anthropic_host(cfg):     # another address is another company: ask again
        return f"anthropic:custom:{anthropic_host(cfg)}"
    if provider == "openai":
        s = cfg.provider_settings("openai")
        preset = s.get("preset") or "openai"
        if preset == "custom":           # another address is another company: ask again
            return f"openai:custom:{(urlparse(s.get('base_url') or '').hostname or '').lower()}"
        return f"openai:{preset}"
    host = remote_host(cfg, provider)
    return f"{provider}:{host.lower()}" if host else provider


def needs_consent(cfg: AssistantConfig, provider: str) -> bool:
    """Cloud services, and Ollama / LM Studio running on another computer, ask before the first request."""
    return provider in CLOUD or remote_host(cfg, provider) is not None


def record_consent(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ConfigError("provider", f"Choose one of: {', '.join(PROVIDERS)}")
    cfg = load_config()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if needs_consent(cfg, provider):
        cfg.data.setdefault("consent", {})[consent_key(cfg, provider)] = stamp
        save_config(cfg)
    return stamp


def has_consent(cfg: AssistantConfig, provider: str) -> bool:
    if not needs_consent(cfg, provider):
        return True
    return bool((cfg.data.get("consent") or {}).get(consent_key(cfg, provider)))


def service_name(cfg: AssistantConfig, provider: str) -> str:
    if provider == "anthropic":
        host = anthropic_host(cfg)
        return f"Claude at {host}" if host else "Anthropic"
    if provider == "openai":
        s = cfg.provider_settings("openai")
        preset = s.get("preset") or "openai"
        if preset == "custom":
            return urlparse(s.get("base_url") or "").hostname or "the service"
        return PRESETS[preset][2]
    host = remote_host(cfg, provider)
    if host:
        return f"{'Ollama' if provider == 'ollama' else 'LM Studio'} at {host}"
    return LABELS.get(provider, provider)


def remote_text(cfg: AssistantConfig, provider: str) -> str | None:
    host = remote_host(cfg, provider)
    if not host:
        return None
    plain = urlparse(cfg.provider_settings(provider).get("base_url") or "").scheme == "http"
    name = "Ollama" if provider == "ollama" else "LM Studio"
    return (f"On another computer: {name} runs at {host}, so what you type, the experiment you are editing and the "
            f"files you attach are sent to that computer"
            + (" over the network unencrypted (http://): others on the network could read them" if plain else "")
            + ". EDGE never sends your participants' data (the data folders). Use an address on this computer "
              "(localhost) to keep everything here.")


def privacy_texts(cfg: AssistantConfig) -> dict[str, Any]:
    where = display_path(cfg.path)
    cloud = ("What is sent where. With a cloud assistant (Claude by Anthropic, OpenAI, OpenRouter or another online "
             "service), what you type, the experiment you are editing (its screens, texts, settings and trial lists) "
             "and the files you attach are sent to that company to produce the answer, under its terms. EDGE never "
             "sends your participants' data (the data folders) and never sends your API key anywhere except to that "
             "service. Check your institution's rules before sending unpublished materials or anything that "
             "identifies people. With Ollama or LM Studio on this computer, everything stays on this computer.\n\n"
             f"Your API key is stored only on this computer, in {where}, readable only by your user account. You can "
             "remove it at any time in Assistant settings.")
    local = "On this computer: nothing is sent anywhere. The model runs in Ollama or LM Studio on this computer."
    remote = {name: t for name in ("ollama", "lmstudio") if (t := remote_text(cfg, name))}
    if cfg.provider in remote:
        local = remote[cfg.provider]
    return {"version": 1, "cloud": cloud, "local": local, "remote": remote}


def _last4(key: str) -> str:
    return key[-4:] if len(key) >= 12 else "set"


def public_view(cfg: AssistantConfig) -> dict[str, Any]:
    """Everything the builder may show about the settings. Never contains a key."""
    providers: dict[str, Any] = {}
    for name in PROVIDERS:
        s = cfg.provider_settings(name)
        row: dict[str, Any] = {"label": LABELS[name], "kind": "cloud" if name in CLOUD else "local",
                               "base_url": s.get("base_url"), "model": s.get("model")}
        if name == "anthropic":
            row.update({k: s.get(k) for k in ("effort", "fallbacks", "progress_notes")})
            row["service"] = service_name(cfg, "anthropic")
        if name == "openai":
            row["preset"] = s.get("preset")
            row["service"] = service_name(cfg, "openai")
        if name == "ollama":
            row.update({k: s.get(k) for k in ("num_ctx", "tool_mode", "keep_alive", "temperature")})
        if name == "lmstudio":
            row.update({k: s.get(k) for k in ("tool_mode", "temperature")})
        if name in CLOUD:
            key, source = resolve_key(cfg, name)
            row.update({"has_key": bool(key), "key_last4": _last4(key) if key else None, "key_source": source,
                        "key_env": env_key_name(cfg, name), "consented": has_consent(cfg, name)})
        else:
            host = remote_host(cfg, name)
            row["on_this_computer"] = host is None
            row["consented"] = has_consent(cfg, name)
            if host:
                row["label"] = f"{'Ollama' if name == 'ollama' else 'LM Studio'} (at {host})"
        providers[name] = row
    p = cfg.provider
    configured = False
    if p:
        s = cfg.provider_settings(p)
        configured = bool(s.get("model")) and (p not in CLOUD or bool(resolve_key(cfg, p)[0]))
    opts = cfg.options
    return {"configured": configured, "provider": p, "config_path": display_path(cfg.path),
            "config_warnings": list(cfg.warnings),
            "providers": providers,
            "options": {k: opts.get(k) for k in ("send_images", "auto_dry_run", "keep_history", "max_steps", "timeout_s")},
            "recommended_models": {"anthropic": copy.deepcopy(RECOMMENDED_ANTHROPIC)},
            "privacy": privacy_texts(cfg)}
