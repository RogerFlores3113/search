"""Config validation, env parsing, safety invariants, package surface."""
import subprocess
import sys

import pytest
from pydantic import ValidationError

import local_browser_agent
from local_browser_agent import AgentConfig, ModelConfig, SafetyPolicy, register_provider
from local_browser_agent.models import PreFlightError, build_llm, check_provider, resolve_model_name
from local_browser_agent.safety import SAFETY_DEFAULTS


def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="Unknown provider 'nope'"):
        ModelConfig(provider="nope")


def test_provider_normalised_and_custom_accepted():
    assert ModelConfig(provider=" Anthropic ").provider == "anthropic"
    register_provider("cfgtest-custom", lambda cfg: object())
    assert ModelConfig(provider="cfgtest-custom").provider == "cfgtest-custom"


def test_openai_compatible_requires_base_url():
    with pytest.raises(ValueError, match="requires base_url"):
        ModelConfig(provider="openai_compatible", model="m")
    assert ModelConfig(provider="openai_compatible", base_url="http://h/v1").base_url == "http://h/v1"


@pytest.mark.parametrize("bad", ["localhost:11434", "ftp://x", "http://", "not a url"])
def test_malformed_base_url(bad):
    with pytest.raises(ValidationError, match="base_url"):
        ModelConfig(provider="ollama", base_url=bad)


def test_api_key_not_required_at_construction():
    ModelConfig(provider="anthropic")


def test_missing_key_messages_name_env_vars():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY or LBA_API_KEY"):
        build_llm(ModelConfig(provider="anthropic"))
    with pytest.raises(ValueError, match="OPENAI_API_KEY or LBA_API_KEY"):
        build_llm(ModelConfig(provider="openai"))


async def test_preflight_missing_key_messages():
    with pytest.raises(PreFlightError, match="Anthropic API key is not set. Set ANTHROPIC_API_KEY or LBA_API_KEY."):
        await check_provider(ModelConfig(provider="anthropic"))
    with pytest.raises(PreFlightError, match="OpenAI API key is not set. Set OPENAI_API_KEY or LBA_API_KEY."):
        await check_provider(ModelConfig(provider="openai"))


def test_resolve_model_name_custom_provider_fallback():
    register_provider("cfgtest-nodefault", lambda cfg: object())
    assert resolve_model_name(ModelConfig(provider="cfgtest-nodefault")) == "cfgtest-nodefault"
    assert resolve_model_name(ModelConfig(provider="cfgtest-nodefault", model="m1")) == "m1"
    with pytest.raises(ValueError, match="no default model"):
        resolve_model_name(ModelConfig(provider="litellm"))


@pytest.mark.parametrize(
    "var,val,msg",
    [
        ("LBA_MAX_STEPS", "abc", "LBA_MAX_STEPS must be an integer, got 'abc'"),
        ("LBA_TIMEOUT_S", "soon", "LBA_TIMEOUT_S must be a number, got 'soon'"),
        ("LBA_TEMPERATURE", "hot", "LBA_TEMPERATURE must be a number, got 'hot'"),
        ("LBA_HEADLESS", "maybe", "LBA_HEADLESS must be a boolean"),
        ("LBA_USE_VISION", "2", "LBA_USE_VISION must be a boolean"),
    ],
)
def test_from_env_typed_errors(var, val, msg):
    with pytest.raises(ValueError, match=msg):
        AgentConfig.from_env(env={var: val})


def test_from_env_booleans_and_values():
    cfg = AgentConfig.from_env(env={"LBA_HEADLESS": "Off", "LBA_USE_JUDGE": "yes", "LBA_MAX_STEPS": " 7 "})
    assert cfg.browser.headless is False and cfg.use_judge is True and cfg.max_steps == 7


def test_bounds():
    for kw in ({"max_steps": 0}, {"max_steps": 501}, {"timeout_s": 0}, {"timeout_s": -1}):
        with pytest.raises(ValidationError):
            AgentConfig(**kw)
    assert AgentConfig(max_steps=500).max_steps == 500


def test_blocked_wins_over_allowed():
    p = SafetyPolicy(allowed_domains=["Example.com.", "paypal.com", "www.paypal.com", "evil.test"],
                     blocked_domains=["Evil.test."])
    assert p.allowed_domains == ["example.com"]
    assert "evil.test" in p.blocked_domains


def test_allowed_only_blocked_rejected():
    with pytest.raises(ValidationError, match="blocked domains always win"):
        SafetyPolicy(allowed_domains=["paypal.com"])


def test_blocked_normalised():
    assert "foo.com" in SafetyPolicy(blocked_domains=[" FOO.com. "]).blocked_domains


def test_model_copy_keeps_defaults():
    p = SafetyPolicy().model_copy(update={"blocked_domains": frozenset({"x.com"})})
    assert SAFETY_DEFAULTS <= p.blocked_domains and "x.com" in p.blocked_domains
    q = SafetyPolicy().model_copy(update={"blocked_domains": frozenset()})
    assert SAFETY_DEFAULTS <= q.blocked_domains


def test_model_construct_keeps_defaults():
    p = SafetyPolicy.model_construct(blocked_domains=frozenset({"x.com"}))
    assert SAFETY_DEFAULTS <= p.blocked_domains


def test_model_copy_allowed_respects_blocked():
    p = SafetyPolicy().model_copy(update={"allowed_domains": ["ok.com", "chase.com"]})
    assert p.allowed_domains == ["ok.com"]


def test_assignment_keeps_defaults():
    p = SafetyPolicy()
    p.blocked_domains = frozenset({"y.com"})
    assert SAFETY_DEFAULTS <= p.blocked_domains


def test_version_and_py_typed():
    from importlib import metadata, resources

    assert local_browser_agent.__version__ == metadata.version("local-browser-agent")
    assert resources.files("local_browser_agent").joinpath("py.typed").is_file()


def _env_after_import(env_extra):
    import os

    env = {k: v for k, v in os.environ.items() if k not in ("ANONYMIZED_TELEMETRY", "LITELLM_LOCAL_MODEL_COST_MAP", "LBA_ALLOW_TELEMETRY")}
    env.update(env_extra)
    code = ("import os, local_browser_agent;"
            "print(os.environ['ANONYMIZED_TELEMETRY'], os.environ['LITELLM_LOCAL_MODEL_COST_MAP'])")
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.split()


def test_telemetry_forced_off_even_if_inherited_true():
    assert _env_after_import({"ANONYMIZED_TELEMETRY": "true"}) == ["false", "True"]


def test_telemetry_opt_in():
    assert _env_after_import({"ANONYMIZED_TELEMETRY": "true", "LBA_ALLOW_TELEMETRY": "1"})[0] == "true"
