"""Shared pytest fixtures for the local-browser-agent test suite."""
from __future__ import annotations

import os
import pytest


@pytest.fixture
def monkeypatch_env(monkeypatch):
    """Clear all agent-relevant env vars so Settings() uses defaults."""
    for var in ("PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL", "MAX_STEPS", "SESSION_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def training_dir(tmp_path, monkeypatch):
    """Yield a tmp Path for training/ and chdir so JSONL writes land there."""
    monkeypatch.chdir(tmp_path)
    training = tmp_path / "training"
    training.mkdir()
    return training


@pytest.fixture
def mock_ollama_tags_ok(httpx_mock):
    """Return 200 with both qwen2.5vl:7b and gemma4:e4b present."""
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:11434/api/tags",
        json={"models": [{"name": "qwen2.5vl:7b"}, {"name": "gemma4:e4b"}]},
    )
    return httpx_mock


@pytest.fixture
def mock_ollama_unreachable(httpx_mock):
    """Simulate a connection error for Ollama."""
    import httpx

    httpx_mock.add_exception(
        httpx.ConnectError("Connection refused"),
        method="GET",
        url="http://localhost:11434/api/tags",
    )
    return httpx_mock


@pytest.fixture
def mock_ollama_model_missing(httpx_mock):
    """Return 200 but qwen2.5vl:7b is absent from the model list."""
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:11434/api/tags",
        json={"models": [{"name": "gemma4:e4b"}]},
    )
    return httpx_mock
