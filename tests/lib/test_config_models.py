import json

import pytest
from pydantic import SecretStr

from local_browser_agent import (
    SAFETY_DEFAULTS, AgentConfig, ModelConfig, SafetyPolicy, build_llm, register_provider,
)
from local_browser_agent.models import default_model, known_providers


def test_defaults():
    c = AgentConfig()
    assert c.model.provider == "ollama" and c.model.model is None
    assert c.max_steps == 25 and c.timeout_s == 600 and c.use_judge is False
    assert c.browser.headless is False and c.browser.channel == "chrome"
    assert c.browser.window_width == 1280 and c.browser.llm_screenshot_height == 640
    assert c.safety.gate_commerce_clicks is True
    assert SAFETY_DEFAULTS <= c.safety.blocked_domains


def test_blocked_domains_cannot_shrink():
    assert SAFETY_DEFAULTS <= SafetyPolicy(blocked_domains=[]).blocked_domains
    p = SafetyPolicy(blocked_domains=["Evil.com"])
    assert "evil.com" in p.blocked_domains and SAFETY_DEFAULTS <= p.blocked_domains
    p.blocked_domains = frozenset({"x.com"})  # assignment is validated too
    assert SAFETY_DEFAULTS <= p.blocked_domains


def test_from_env_basic():
    env = {
        "LBA_PROVIDER": "anthropic", "LBA_MODEL": "m", "LBA_API_KEY": "sk-secret",
        "LBA_HEADLESS": "true", "LBA_CDP_URL": "http://localhost:9222", "LBA_MAX_STEPS": "7",
        "LBA_TIMEOUT_S": "30", "LBA_ALLOWED_DOMAINS": "a.com, b.com", "LBA_BLOCKED_DOMAINS": "z.com",
    }
    c = AgentConfig.from_env(env=env)
    assert c.model.provider == "anthropic" and c.model.model == "m"
    assert c.model.api_key.get_secret_value() == "sk-secret"
    assert c.browser.headless is True and c.browser.cdp_url == "http://localhost:9222"
    assert c.max_steps == 7 and c.timeout_s == 30
    assert c.safety.allowed_domains == ["a.com", "b.com"]
    assert "z.com" in c.safety.blocked_domains and SAFETY_DEFAULTS <= c.safety.blocked_domains


def test_from_env_provider_key_fallback():
    c = AgentConfig.from_env(env={"LBA_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "ak"})
    assert c.model.api_key.get_secret_value() == "ak"
    c = AgentConfig.from_env(env={"LBA_PROVIDER": "openai", "OPENAI_API_KEY": "ok", "ANTHROPIC_API_KEY": "ak"})
    assert c.model.api_key.get_secret_value() == "ok"
    c = AgentConfig.from_env(env={"LBA_PROVIDER": "anthropic", "LBA_API_KEY": "own", "ANTHROPIC_API_KEY": "ak"})
    assert c.model.api_key.get_secret_value() == "own"
    c = AgentConfig.from_env(env={"ANTHROPIC_API_KEY": "ak"})  # provider ollama: no fallback
    assert c.model.api_key is None


def test_secrets_hidden():
    c = AgentConfig(model=ModelConfig(provider="openai", api_key=SecretStr("sk-topsecret")))
    assert "sk-topsecret" not in repr(c) and "sk-topsecret" not in str(c)
    assert "sk-topsecret" not in json.dumps(c.model_dump(mode="json"))


def test_default_models():
    assert default_model("ollama") == "qwen2.5vl:7b"
    assert default_model("anthropic") == "claude-sonnet-4-5"
    assert default_model("openai") == "gpt-4o"


def test_custom_provider_registration():
    seen = []

    def factory(cfg):
        seen.append(cfg)
        return "LLM"

    register_provider("MyProv", factory)
    assert "myprov" in known_providers()
    assert build_llm(ModelConfig(provider="myprov")) == "LLM" and seen


def test_unknown_provider_lists_known():
    with pytest.raises(ValueError) as e:
        build_llm(ModelConfig(provider="nope"))
    assert "ollama" in str(e.value) and "anthropic" in str(e.value)


def test_builtins_construct():
    ol = build_llm(ModelConfig(provider="ollama", base_url="http://h:1"))
    assert ol.model == "qwen2.5vl:7b" and ol.host == "http://h:1"
    assert ol.ollama_options["num_ctx"] == 32000
    an = build_llm(ModelConfig(provider="anthropic", api_key=SecretStr("k")))
    assert an.model == "claude-sonnet-4-5"
    oa = build_llm(ModelConfig(provider="openai", api_key=SecretStr("k")))
    assert oa.model == "gpt-4o"
    oc = build_llm(ModelConfig(provider="openai_compatible", model="llama", base_url="http://x/v1"))
    assert oc.base_url is not None and "x/v1" in str(oc.base_url)
    ll = build_llm(ModelConfig(provider="litellm", model="gemini/gemini-2.0-flash", api_key=SecretStr("k")))
    assert ll.model == "gemini/gemini-2.0-flash"


def test_missing_requirements():
    for p in ("anthropic", "openai"):
        with pytest.raises(ValueError, match="api_key"):
            build_llm(ModelConfig(provider=p))
    with pytest.raises(ValueError, match="base_url"):
        build_llm(ModelConfig(provider="openai_compatible", model="m"))
    with pytest.raises(ValueError, match="model"):
        build_llm(ModelConfig(provider="litellm"))
