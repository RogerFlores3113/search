"""Unit tests for agent/config.py (MODEL-01 requirements)."""
from __future__ import annotations

import pytest


def test_defaults_match_d06(monkeypatch_env):
    """D-06: Settings() must use the agreed defaults when no env vars are set."""
    from agent.config import Settings

    settings = Settings()
    assert settings.provider == "ollama"
    assert settings.ollama_host == "http://localhost:11434"
    assert settings.ollama_model == "qwen2.5vl:7b"
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
