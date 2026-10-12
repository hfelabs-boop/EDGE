"""Assistant settings: where they live, file permissions, keys (write-only, redacted), validation."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from edge.assistant import config as C


@pytest.fixture(autouse=True)
def cfgdir(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    monkeypatch.setenv("EDGE_CONFIG_DIR", str(d))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return d


KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz-x7Qa"


def test_config_dir_is_not_the_experiments_folder(cfgdir):
    assert C.config_path() == cfgdir / "assistant.json"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
def test_key_is_stored_0600_in_a_0700_folder(cfgdir):
    C.update_config({"provider": "anthropic", "anthropic": {"api_key": KEY}})
    assert stat.S_IMODE(os.stat(C.config_path()).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(cfgdir).st_mode) == 0o700
    assert json.loads(C.config_path().read_text())["anthropic"]["api_key"] == KEY
    assert not list(cfgdir.glob(".assistant.*.tmp"))          # atomic write leaves nothing behind


def test_public_view_never_contains_the_key():
    C.update_config({"provider": "anthropic", "anthropic": {"api_key": KEY, "model": "claude-opus-5-5"}})
    view = C.public_view(C.load_config())
    a = view["providers"]["anthropic"]
    assert a["has_key"] and a["key_last4"] == "x7Qa" and a["key_source"] == "config"
    assert KEY not in json.dumps(view)
    assert view["configured"] and view["provider"] == "anthropic"
    assert view["config_path"].endswith("assistant.json")
    assert [m["id"] for m in view["recommended_models"]["anthropic"]][0] == "claude-opus-5-5"
    assert "never sends your participants' data" in view["privacy"]["cloud"]


def test_short_keys_only_say_set():
    C.update_config({"provider": "openai", "openai": {"api_key": "sk-12345678", "model": "gpt-5.1"}})
    assert C.public_view(C.load_config())["providers"]["openai"]["key_last4"] == "set"


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permissions")
def test_loose_permissions_are_fixed_on_load():
    C.update_config({"anthropic": {"api_key": KEY}})
    os.chmod(C.config_path(), 0o644)
    cfg = C.load_config()
    assert "config_permissions_fixed" in cfg.warnings
    assert stat.S_IMODE(os.stat(C.config_path()).st_mode) == 0o600


def test_environment_keys_and_precedence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-key-0000000000000000-ENVK")
    cfg = C.load_config()
    assert C.resolve_key(cfg, "anthropic") == ("sk-ant-env-key-0000000000000000-ENVK", "env:ANTHROPIC_API_KEY")
    view = C.public_view(cfg)["providers"]["anthropic"]
    assert view["key_source"] == "env:ANTHROPIC_API_KEY" and view["key_last4"] == "ENVK"
    C.update_config({"anthropic": {"api_key": KEY}})                     # a stored key wins
    assert C.resolve_key(C.load_config(), "anthropic") == (KEY, "config")
    C.update_config({"anthropic": {"api_key": ""}})                      # clearing falls back to the environment
    assert C.resolve_key(C.load_config(), "anthropic")[1] == "env:ANTHROPIC_API_KEY"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-0000000000000000000000")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-1111111111111111111111")
    C.update_config({"openai": {"preset": "openrouter"}})
    cfg = C.load_config()
    assert C.resolve_key(cfg, "openai") == ("sk-or-v1-0000000000000000000000", "env:OPENROUTER_API_KEY")
    assert cfg.provider_settings("openai")["base_url"] == "https://openrouter.ai/api/v1"
    C.update_config({"openai": {"preset": "openai"}})
    assert C.resolve_key(C.load_config(), "openai")[1] == "env:OPENAI_API_KEY"
    assert C.resolve_key(C.load_config(), "ollama") == (None, None)


@pytest.mark.parametrize("patch, field", [
    ({"provider": "gemini"}, "provider"),
    ({"anthropic": {"effort": "extreme"}}, "anthropic.effort"),
    ({"ollama": {"num_ctx": 100}}, "ollama.num_ctx"),
    ({"ollama": {"num_ctx": True}}, "ollama.num_ctx"),
    ({"openai": {"base_url": "http://api.example.org/v1"}}, "openai.base_url"),        # a key over plain http
    ({"anthropic": {"base_url": "https://user:pw@api.anthropic.com"}}, "anthropic.base_url"),
    ({"anthropic": {"base_url": "https://api.anthropic.com/?x=1"}}, "anthropic.base_url"),
    ({"anthropic": {"base_url": "ftp://api.anthropic.com"}}, "anthropic.base_url"),
    ({"anthropic": {"api_key": "short"}}, "anthropic.api_key"),
    ({"anthropic": {"api_key": "sk-ant has spaces in it"}}, "anthropic.api_key"),
    ({"ollama": {"model": "bad model name!"}}, "ollama.model"),
    ({"lmstudio": {"temperature": 3}}, "lmstudio.temperature"),
    ({"lmstudio": {"tool_mode": "magic"}}, "lmstudio.tool_mode"),
    ({"options": {"send_images": "yes"}}, "options.send_images"),
    ({"surprise": 1}, "surprise"),
])
def test_bad_settings_are_refused_with_the_field(patch, field):
    with pytest.raises(C.ConfigError) as e:
        C.update_config(patch)
    assert e.value.field == field and str(e.value)
    assert not C.config_path().exists()


def test_local_addresses_may_use_http():
    C.update_config({"openai": {"preset": "custom", "base_url": "http://127.0.0.1:8000/v1"}})
    C.update_config({"ollama": {"base_url": "http://localhost:11434"}})
    C.update_config({"ollama": {"base_url": "http://192.168.1.20:11434"}})       # another computer, no key involved
    assert C.load_config().provider_settings("ollama")["base_url"] == "http://192.168.1.20:11434"
    assert C.public_view(C.load_config())["providers"]["ollama"]["on_this_computer"] is False


def test_redact_removes_known_and_key_shaped_tokens(monkeypatch):
    C.update_config({"anthropic": {"api_key": KEY}})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-zzzzzzzzzzzzzzzzzzzzzzzzzzzz9999")
    cfg = C.load_config()
    text = (f"bad key {KEY} and sk-proj-zzzzzzzzzzzzzzzzzzzzzzzzzzzz9999, also sk-ant-unknownkey123456 and "
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    out = C.redact(text, cfg)
    assert KEY not in out and "zzzz9999" not in out and "unknownkey" not in out and "abcdefghijklmnop" not in out
    assert "…x7Qa" in out and "«key removed»" in out


def test_corrupt_config_is_set_aside(cfgdir):
    cfgdir.mkdir(parents=True)
    C.config_path().write_text("{not json")
    cfg = C.load_config()
    assert "config_error" in cfg.warnings and cfg.provider is None
    assert list(cfgdir.glob("assistant.json.broken-*"))
    assert "config_error" in C.public_view(cfg)["config_warnings"]


def test_unknown_keys_are_kept_on_save(cfgdir):
    cfgdir.mkdir(parents=True)
    C.config_path().write_text(json.dumps({"version": 1, "future": {"x": 1}, "anthropic": {"newer_option": 2}}))
    C.update_config({"provider": "ollama"})
    data = json.loads(C.config_path().read_text())
    assert data["future"] == {"x": 1} and data["anthropic"]["newer_option"] == 2 and data["provider"] == "ollama"


def test_consent_per_cloud_service():
    cfg = C.load_config()
    assert C.has_consent(cfg, "ollama") and C.has_consent(cfg, "lmstudio")
    assert not C.has_consent(cfg, "anthropic")
    stamp = C.record_consent("anthropic")
    assert stamp.endswith("Z") and C.has_consent(C.load_config(), "anthropic")
    C.record_consent("openai")
    C.update_config({"openai": {"preset": "openrouter"}})                 # another company: ask again
    assert not C.has_consent(C.load_config(), "openai")


def test_redact_leaves_words_that_merely_contain_sk_alone():
    for text in ("task-switching-replication-2026", "conditions/task-switching-practice-block.csv",
                 "desk-lamp-calibration-procedure-v2", "This is the task-switching-practice-block."):
        assert C.redact(text) == text
    assert C.redact("key=sk-proj-abcdefghijklmnopqrstuvwxyz0123") == "key=«key removed»"
    assert C.redact('"sk-ant-api03-zzzzzzzzzzzz"') == '"«key removed»"'


def test_a_key_never_follows_an_address_change():
    C.update_config({"provider": "anthropic", "anthropic": {"api_key": KEY}})
    cfg = C.update_config({"anthropic": {"model": "claude-sonnet-5-5"}})             # same address: kept
    assert C.resolve_key(cfg, "anthropic")[0] == KEY and "api_key_cleared" not in cfg.warnings
    cfg = C.update_config({"anthropic": {"base_url": "https://api.anthropic.com/v1"}})  # the same, normalised
    assert C.resolve_key(cfg, "anthropic")[0] == KEY
    cfg = C.update_config({"anthropic": {"base_url": "https://gateway.example.org"}})
    assert C.resolve_key(cfg, "anthropic") == (None, None) and "api_key_cleared" in cfg.warnings
    cfg = C.update_config({"anthropic": {"base_url": "https://gateway.example.org", "api_key": KEY}})
    assert C.resolve_key(cfg, "anthropic")[0] == KEY                                  # given with the change: kept
    C.update_config({"openai": {"api_key": "sk-proj-1111111111111111111111"}})
    cfg = C.update_config({"openai": {"preset": "openrouter"}})                      # another company
    assert C.resolve_key(cfg, "openai") == (None, None)


def test_custom_services_ask_for_consent_per_address():
    C.update_config({"openai": {"preset": "custom", "base_url": "https://llm.example.org/v1"}})
    C.record_consent("openai")
    assert C.has_consent(C.load_config(), "openai")
    C.update_config({"openai": {"base_url": "https://other.example.net/v1"}})
    assert not C.has_consent(C.load_config(), "openai")
