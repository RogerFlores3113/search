"""Tests for no_chrome.html — Chrome-missing fallback page (DIST-02)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


def test_root_returns_no_chrome_when_flag_set():
    """When app.state.chrome_missing=True, GET / returns the Chrome-required page."""
    from agent.main import app

    app.state.chrome_missing = True
    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "Google Chrome is required" in html
        assert "https://www.google.com/chrome" in html
    finally:
        app.state.chrome_missing = False


def test_root_returns_index_when_chrome_present():
    """When chrome_missing is absent/False, GET / returns the normal index.html."""
    from agent.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    # Phase-3 identifier present in index.html
    assert 'name="task"' in response.text
