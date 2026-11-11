"""Shared pytest fixtures for the local-browser-agent test suite."""
from __future__ import annotations

import os
import tempfile

import pytest

# Module-level data paths (db.DB_PATH, training_sink.TRAINING_FILE) are computed at import
# time: point them at a throwaway directory so the suite never touches <repo>/data.
os.environ["LBA_DATA_DIR"] = tempfile.mkdtemp(prefix="lba-test-data-")


@pytest.fixture(autouse=True)
def _app_test_defaults(monkeypatch):
    """Relax the web app's request security for tests that use ad-hoc hosts and no token.

    Security behaviour itself is covered in tests/unit/test_app_security.py, which turns
    enforcement back on. Chrome is reported installed so no test depends on the machine.
    """
    import local_browser_agent.app.main as main_mod
    import local_browser_agent.app.runner as runner_mod

    monkeypatch.setattr(main_mod, "_EXTRA_ALLOWED_HOSTS", {"test", "testserver"})
    monkeypatch.setattr(main_mod, "_REQUIRE_TOKEN", False)
    monkeypatch.setattr(runner_mod, "chrome_is_installed", lambda: True)
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: True)


@pytest.fixture(autouse=True)
def _isolated_history_db(tmp_path, monkeypatch):
    """Each test gets its own history.db (the data dir is no longer cwd-relative)."""
    import local_browser_agent.app.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "history.db")


@pytest.fixture(autouse=True)
def _isolated_user_config(tmp_path, monkeypatch):
    """Keep tests off the developer's real settings.json.

    A configured app on the test machine (for example provider "ollama") would otherwise
    leak into Settings() defaults and break provider and preflight assertions.
    """
    import platformdirs

    cfg_root = tmp_path / "user-config"
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda appname=None, *a, **k: str(cfg_root / (appname or "")))
    # settings.json follows LBA_DATA_DIR when set, so give each test its own data dir too.
    data_dir = tmp_path / "lba-data"
    data_dir.mkdir()
    monkeypatch.setenv("LBA_DATA_DIR", str(data_dir))


@pytest.fixture
def monkeypatch_env(monkeypatch):
    """Clear all agent-relevant env vars so Settings() uses defaults."""
    for var in (
        "PROVIDER", "OLLAMA_HOST", "OLLAMA_MODEL", "MAX_STEPS", "SESSION_TIMEOUT",
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def training_dir(tmp_path, monkeypatch):
    """Yield a tmp Path for training/ and redirect runner.TRAINING_FILE there.

    TRAINING_FILE is a module-level constant computed at import via get_user_data_dir().
    Monkeypatching it ensures JSONL writes land in the test directory regardless of cwd.
    """
    monkeypatch.chdir(tmp_path)
    training = tmp_path / "training"
    training.mkdir()
    import local_browser_agent.app.training_sink as training_sink_mod
    monkeypatch.setattr(training_sink_mod, "TRAINING_FILE", training / "runs.jsonl")
    return training


@pytest.fixture
def mock_ollama_tags_ok(httpx_mock):
    """Return 200 with both qwen2.5vl:7b and gemma4:e4b present."""
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:11434/api/tags",
        json={"models": [{"name": "qwen3-vl:8b"}, {"name": "gemma4:e4b"}]},
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


@pytest.fixture
def mock_openai_models_ok(httpx_mock):
    """Return 200 for OpenAI /v1/models endpoint."""
    httpx_mock.add_response(
        method="GET",
        url="https://api.openai.com/v1/models",
        json={"object": "list", "data": []},
        status_code=200,
    )
    return httpx_mock


@pytest.fixture
def mock_openai_models_401(httpx_mock):
    """Return 401 for OpenAI /v1/models endpoint."""
    httpx_mock.add_response(
        method="GET",
        url="https://api.openai.com/v1/models",
        status_code=401,
    )
    return httpx_mock
