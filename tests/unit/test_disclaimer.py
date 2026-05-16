"""Tests for disclaimer modal in agent/templates/index.html (DIST-04)."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


def test_index_has_disclaimer_modal():
    """GET / response HTML contains the localStorage gate and Accept button."""
    from agent.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    # localStorage gate must be present
    assert "localStorage.getItem('disclaimer_accepted')" in html
    # Accept button Alpine click handler
    assert "disclaimerAccepted = true" in html


def test_index_disclaimer_explains_scope():
    """GET / response HTML contains refusal text ('will not') and control reassurance ('pause' or 'stop')."""
    from agent.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "will not" in html.lower()
    assert "pause" in html.lower() or "stop" in html.lower()
