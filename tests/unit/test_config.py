"""Unit tests for agent/config.py (MODEL-01 requirements)."""
from __future__ import annotations

import pytest


def test_defaults_match_d06(monkeypatch_env):
    """D-06: Settings() must use the agreed defaults when no env vars are set."""
    from agent.config import Settings

    settings = Settings()
    assert settings.provider == "ollama"
    assert settings.ollama_host == "http://localhost:11434"
    assert settings.ollama_model == "qwen3-vl:8b"
    assert settings.max_steps == 25
    assert settings.session_timeout == 600


def test_env_override_provider(monkeypatch_env):
    """PROVIDER env var must override the default provider."""
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    from agent.config import Settings

    assert Settings().provider == "anthropic"


def test_env_override_ollama_model(monkeypatch_env):
    """OLLAMA_MODEL env var must override the default model."""
    monkeypatch_env.setenv("OLLAMA_MODEL", "gemma4:e4b")
    from agent.config import Settings

    assert Settings().ollama_model == "gemma4:e4b"


def test_env_override_ollama_host(monkeypatch_env):
    """OLLAMA_HOST env var must override the default host."""
    monkeypatch_env.setenv("OLLAMA_HOST", "http://192.168.1.10:11434")
    from agent.config import Settings

    assert Settings().ollama_host == "http://192.168.1.10:11434"


def test_max_steps_coerced_to_int(monkeypatch_env):
    """MAX_STEPS env var (string) must be coerced to int by pydantic-settings."""
    monkeypatch_env.setenv("MAX_STEPS", "3")
    from agent.config import Settings

    s = Settings()
    assert isinstance(s.max_steps, int)
    assert s.max_steps == 3


# ---------------------------------------------------------------------------
# Multi-provider API key fields (MODEL-02, MODEL-03)
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_anthropic_api_key_loads_as_secret_str(monkeypatch_env):
    """ANTHROPIC_API_KEY must load as SecretStr and hide value in repr."""
    from pydantic import SecretStr
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    from agent.config import Settings

    s = Settings()
    assert isinstance(s.anthropic_api_key, SecretStr)
    assert "sk-ant-test-key" not in repr(s.anthropic_api_key)
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test-key"


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_openai_api_key_loads_as_secret_str(monkeypatch_env):
    """OPENAI_API_KEY must load as SecretStr and hide value in repr."""
    from pydantic import SecretStr
    monkeypatch_env.setenv("OPENAI_API_KEY", "sk-openai-test-key")
    from agent.config import Settings

    s = Settings()
    assert isinstance(s.openai_api_key, SecretStr)
    assert "sk-openai-test-key" not in repr(s.openai_api_key)
    assert s.openai_api_key.get_secret_value() == "sk-openai-test-key"


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_anthropic_api_key_defaults_to_none(monkeypatch_env):
    """ANTHROPIC_API_KEY must default to None when not set."""
    from agent.config import Settings

    assert Settings().anthropic_api_key is None


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_openai_api_key_defaults_to_none(monkeypatch_env):
    """OPENAI_API_KEY must default to None when not set."""
    from agent.config import Settings

    assert Settings().openai_api_key is None


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_anthropic_model_env_override(monkeypatch_env):
    """ANTHROPIC_MODEL env var must override the default model string."""
    monkeypatch_env.setenv("ANTHROPIC_MODEL", "claude-opus-4-5")
    from agent.config import Settings

    assert Settings().anthropic_model == "claude-opus-4-5"


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
def test_openai_model_env_override(monkeypatch_env):
    """OPENAI_MODEL env var must override the default model string."""
    monkeypatch_env.setenv("OPENAI_MODEL", "gpt-4o-mini")
    from agent.config import Settings

    assert Settings().openai_model == "gpt-4o-mini"
