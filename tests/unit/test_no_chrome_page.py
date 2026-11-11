"""Tests for no_chrome.html — Chrome-missing fallback page (DIST-02)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


def test_root_returns_no_chrome_when_flag_set(monkeypatch):
    """When app.state.chrome_missing=True, GET / returns the Chrome-required page."""
    from local_browser_agent.app.main import app

    import local_browser_agent.app.main as main_mod

    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: False)
    app.state.chrome_missing = False
    try:
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/")
        assert response.status_code == 200
        html = response.text
        assert "Google Chrome is required" in html
        assert "https://www.google.com/chrome" in html
        assert "Check again" in html
    finally:
        app.state.chrome_missing = False


def test_root_returns_index_when_chrome_present():
    """When chrome_missing is absent/False, GET / returns the normal index.html."""
    from local_browser_agent.app.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    # Phase-3 identifier present in index.html
    assert 'name="task"' in response.text


def test_chrome_is_rechecked_on_every_request(monkeypatch):
    """Installing Chrome while the app runs: the next GET / serves the real UI."""
    import local_browser_agent.app.main as main_mod
    from local_browser_agent.app.main import app

    installed = {"v": False}
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: installed["v"])
    client = TestClient(app)
    assert "Google Chrome is required" in client.get("/").text
    installed["v"] = True
    assert 'name="task"' in client.get("/").text
    installed["v"] = False
    assert "Google Chrome is required" in client.get("/").text


def test_no_chrome_page_links_to_settings(monkeypatch):
    """The Chrome-missing page lets the user reach Settings (with the security token)."""
    import local_browser_agent.app.main as main_mod
    from local_browser_agent.app.main import app

    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: False)
    client = TestClient(app)
    page = client.get("/")
    assert "/?settings=1" in page.text
    settings_page = client.get("/?settings=1")
    assert settings_page.status_code == 200
    assert main_mod.SECURITY_TOKEN in settings_page.text
    assert "this.openSettings();" in settings_page.text
