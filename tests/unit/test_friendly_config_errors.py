"""Invalid stored settings never leak raw pydantic text (persona round)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


@pytest.mark.parametrize("bad", ["notaurl", "ftp://host", "http://", "http://host:abc", "http:// spaced"])
def test_settings_rejects_invalid_ollama_host(bad, monkeypatch):
    from local_browser_agent.app.config import config
    from local_browser_agent.app.main import app

    monkeypatch.setattr(config, "ollama_host", "http://localhost:11434")
    client = TestClient(app)
    r = client.post("/api/settings", data={"provider": "ollama", "ollama_host": bad})
    assert r.status_code == 422
    assert "web address" in r.json()["detail"]
    assert config.ollama_host == "http://localhost:11434"


def test_settings_accepts_valid_ollama_host(monkeypatch):
    from local_browser_agent.app.config import config
    from local_browser_agent.app.main import app

    monkeypatch.setattr(config, "ollama_host", "http://localhost:11434")
    r = TestClient(app).post(
        "/api/settings", data={"provider": "ollama", "ollama_host": "http://192.168.1.5:11434"}
    )
    assert r.status_code == 200
    assert config.ollama_host == "http://192.168.1.5:11434"


async def test_invalid_stored_host_gives_friendly_error_run_id_and_history(monkeypatch):
    from local_browser_agent.app import db as history_db
    from local_browser_agent.app.config import config
    from local_browser_agent.app.runner import run_agent

    monkeypatch.setattr(config, "provider", "ollama")
    monkeypatch.setattr(config, "ollama_host", "notaurl")
    await history_db.init_db()
    queue: asyncio.Queue = asyncio.Queue()
    ctrl: asyncio.Queue = asyncio.Queue()
    browser_session = MagicMock()
    with patch("local_browser_agent.browser.BrowserSession", browser_session):
        await run_agent("do a thing", queue=queue, control_queue=ctrl)
    browser_session.assert_not_called()

    events = []
    for q in (queue, ctrl):
        while not q.empty():
            events.append(q.get_nowait())
    text = " ".join(repr(e) for e in events).lower()
    assert "pydantic" not in text and "validation error" not in text
    assert "ollama address isn't a valid web address" in text
    run_ids = {getattr(e, "run_id", "") for e in events if getattr(e, "run_id", "")}
    assert run_ids  # a real run_id
    rows = await history_db.list_runs()
    assert rows and rows[0]["status"] == "error"
    assert "pydantic" not in (rows[0]["error"] or "").lower()
    assert "valid web address" in rows[0]["error"]
