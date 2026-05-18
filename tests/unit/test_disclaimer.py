"""Tests for the disclaimer gate — server-side cookie + UI modal (DIST-04, Issue #5).

The disclaimer is now a real security gate:
  - POST /accept-disclaimer issues a signed, httponly, SameSite=strict cookie.
  - /run, /pause, /stop return 403 disclaimer_required when the cookie is absent.
  - The Jinja-rendered index reads acceptance from the cookie so the modal does
    not flash on repeat visits and so the UI is the only path to acceptance.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient


def test_index_has_disclaimer_modal():
    """GET / renders the modal markup with the new server-driven gate."""
    from agent.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    # Server-rendered initial state — the modal flips to accepted via cookie.
    assert "disclaimerAccepted: false" in html or "disclaimerAccepted: true" in html, (
        "index.html must render disclaimerAccepted state from the server cookie"
    )
    # Accept button POSTs to the new endpoint.
    assert "/accept-disclaimer" in html, (
        "modal Accept button must POST to /accept-disclaimer"
    )
    # `inert` keyboard-trap replaces the old pointer-events:none/blur-only gate.
    assert "inert" in html, (
        "main UI shell must use `inert` so Tab cannot bypass the modal"
    )


def test_index_disclaimer_explains_scope():
    """Modal copy still names the refusal envelope + the pause/stop reassurance."""
    from agent.main import app

    app.state.chrome_missing = False
    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "will not" in html.lower()
    assert "pause" in html.lower() or "stop" in html.lower()


def test_index_renders_accepted_state_when_cookie_present():
    """GET / with a valid disclaimer cookie renders disclaimerAccepted: true
    so the modal does not flash before Alpine reads localStorage / state.
    """
    from agent.main import (
        DISCLAIMER_COOKIE_NAME,
        _disclaimer_serializer,
        app,
    )

    app.state.chrome_missing = False
    cookie = _disclaimer_serializer().dumps("1")
    client = TestClient(app, raise_server_exceptions=True,
                        cookies={DISCLAIMER_COOKIE_NAME: cookie})
    html = client.get("/").text
    assert "disclaimerAccepted: true" in html, (
        "index.html must render disclaimerAccepted: true when cookie is valid"
    )


async def test_run_without_disclaimer_returns_403():
    """POST /run with no cookie must return 403 disclaimer_required."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/run", data={"task": "do something"})

    assert resp.status_code == 403, f"expected 403; got {resp.status_code}"
    assert resp.json() == {"status": "disclaimer_required"}


async def test_pause_without_disclaimer_returns_403():
    """POST /pause with no cookie must return 403 (NOT 400 no_active_run)."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/pause")

    assert resp.status_code == 403
    assert resp.json() == {"status": "disclaimer_required"}


async def test_stop_without_disclaimer_returns_403():
    """POST /stop with no cookie must return 403."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/stop")

    assert resp.status_code == 403
    assert resp.json() == {"status": "disclaimer_required"}


async def test_accept_disclaimer_sets_signed_cookie():
    """POST /accept-disclaimer issues a signed, httponly, SameSite=strict cookie."""
    from agent.main import DISCLAIMER_COOKIE_NAME, app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/accept-disclaimer")

    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
    set_cookie = resp.headers.get("set-cookie", "")
    assert DISCLAIMER_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie.lower() or "samesite=strict" in set_cookie.lower()


async def test_accepted_cookie_unlocks_run_endpoint(monkeypatch):
    """After /accept-disclaimer, /run no longer returns 403. We patch out
    run_agent so we don't actually spawn an agent task; we only assert the
    gate stopped firing.
    """
    import agent.main as main_mod
    from unittest.mock import AsyncMock
    monkeypatch.setattr(main_mod, "run_agent", AsyncMock())
    # Ensure no leftover task from a prior test holds the busy slot.
    monkeypatch.setattr(main_mod, "_active_task", None)

    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as client:
        accept = await client.post("/accept-disclaimer")
        assert accept.status_code == 200
        # AsyncClient persists cookies across requests in the same session.
        resp = await client.post("/run", data={"task": "demo task"})

    assert resp.status_code != 403, (
        f"after acceptance /run must not return 403; got {resp.status_code}: {resp.text}"
    )


async def test_tampered_cookie_rejected():
    """A cookie with the right name but a bogus signature is rejected —
    a casual unsigned `lba_disclaimer=1` set by another local site does
    NOT pass the gate.
    """
    from agent.main import DISCLAIMER_COOKIE_NAME, app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={DISCLAIMER_COOKIE_NAME: "1"},  # unsigned
    ) as client:
        resp = await client.post("/run", data={"task": "demo"})

    assert resp.status_code == 403, (
        f"unsigned cookie must NOT pass the gate; got {resp.status_code}"
    )
