"""Shared autouse fixture: pretend a Chrome binary exists so no test depends on the host."""
import pytest


@pytest.fixture(autouse=True)
def fake_chrome(monkeypatch):
    monkeypatch.setattr("local_browser_agent.browser.find_chrome", lambda channel="chrome": "/usr/bin/fake-chrome")
