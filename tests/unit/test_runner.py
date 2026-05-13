"""Unit tests for run_agent in agent/runner.py (LOOP-02 through LOOP-06, MODEL-01 wiring).

Tests use mocks to verify the construction chain and lifecycle contracts without
requiring a live Chrome or Ollama instance.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from agent.config import config as _default_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_history():
    """Build a minimal AgentHistoryList mock that returns a final result string."""
    history = MagicMock()
    history.final_result.return_value = "task complete"
    return history


def _make_mock_agent(history=None):
    """Build a mock browser-use Agent whose run() returns the provided history."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=history or _make_mock_history())
    return mock_agent


def _make_mock_browser():
    """Build a mock BrowserSession with an awaitable kill()."""
    browser = MagicMock()
    browser.kill = AsyncMock()
    return browser


# ---------------------------------------------------------------------------
# BrowserSession construction
# ---------------------------------------------------------------------------

async def test_run_agent_constructs_browser_session_with_chrome_channel(monkeypatch):
    """run_agent must build BrowserSession(channel='chrome', headless=False, keep_alive=False)."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    MockBrowserSession.assert_called_once_with(
        channel="chrome",
        headless=False,
        keep_alive=False,
    )


# ---------------------------------------------------------------------------
# ChatOllama construction
# ---------------------------------------------------------------------------

async def test_run_agent_constructs_chat_ollama_with_num_ctx(monkeypatch):
    """run_agent must build ChatOllama(model=config.ollama_model, num_ctx=32000)."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    MockChatOllama.assert_called_once_with(
        model=_default_config.ollama_model,
        num_ctx=32000,
    )


# ---------------------------------------------------------------------------
# asyncio.wait_for wrapping
# ---------------------------------------------------------------------------

async def test_run_agent_wraps_in_wait_for(monkeypatch):
    """run_agent must wrap agent.run() in asyncio.wait_for with timeout=config.session_timeout."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    captured_calls = []

    async def fake_wait_for(coro, timeout=None):
        captured_calls.append({"timeout": timeout})
        return await coro

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.asyncio.wait_for", fake_wait_for)

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    assert len(captured_calls) == 1
    assert captured_calls[0]["timeout"] == _default_config.session_timeout


# ---------------------------------------------------------------------------
# max_steps and on_step_end wiring
# ---------------------------------------------------------------------------

async def test_run_agent_calls_max_steps_25(monkeypatch):
    """run_agent must call agent.run(max_steps=config.max_steps, on_step_end=log_step)."""
    from agent.runner import log_step

    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    mock_agent_instance.run.assert_called_once_with(
        max_steps=_default_config.max_steps,
        on_step_end=log_step,
    )


# ---------------------------------------------------------------------------
# browser.kill() called in finally — success path
# ---------------------------------------------------------------------------

async def test_run_agent_calls_browser_kill_on_success(monkeypatch):
    """run_agent must await browser.kill() after a successful run."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    mock_browser.kill.assert_awaited_once()


# ---------------------------------------------------------------------------
# browser.kill() called in finally — timeout path
# ---------------------------------------------------------------------------

async def test_run_agent_calls_browser_kill_on_timeout(monkeypatch):
    """run_agent must await browser.kill() on asyncio.TimeoutError; no exception escapes."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)
    MockChatOllama = MagicMock()

    # Mock agent.run to return a coroutine that wait_for will receive
    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)

    async def raise_timeout(coro, timeout=None):
        # Close the coroutine to avoid "was never awaited" warning
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.asyncio.wait_for", raise_timeout)

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        # TimeoutError must NOT propagate — run_agent handles it as clean termination
        await run_agent("test task")

    mock_browser.kill.assert_awaited_once()


# ---------------------------------------------------------------------------
# browser.kill() called in finally — exception path
# ---------------------------------------------------------------------------

async def test_run_agent_calls_browser_kill_on_exception(monkeypatch):
    """run_agent must await browser.kill() on RuntimeError; exception must propagate."""
    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)
    MockChatOllama = MagicMock()

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("agent error"))
    MockAgent = MagicMock(return_value=mock_agent_instance)

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        with pytest.raises(RuntimeError, match="agent error"):
            await run_agent("test task")

    mock_browser.kill.assert_awaited_once()


# ---------------------------------------------------------------------------
# BrowserSession NOT constructed when pre_flight_check exits
# ---------------------------------------------------------------------------

async def test_run_agent_skips_browser_when_preflight_exits(monkeypatch):
    """run_agent must not instantiate BrowserSession when pre_flight_check calls sys.exit."""
    MockBrowserSession = MagicMock()
    MockChatOllama = MagicMock()
    MockAgent = MagicMock()

    async def fake_preflight(cfg):
        sys.exit(1)

    monkeypatch.setattr("agent.runner.pre_flight_check", fake_preflight)

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        with pytest.raises(SystemExit) as exc:
            await run_agent("test task")

    assert exc.value.code == 1
    MockBrowserSession.assert_not_called()


# ---------------------------------------------------------------------------
# FastAPI lifespan creates agent task when pending_task is set
# ---------------------------------------------------------------------------

async def test_lifespan_creates_agent_task_when_pending_task_set(monkeypatch):
    """FastAPI lifespan must call run_agent with pending_task via asyncio.create_task."""
    from agent.main import app, lifespan

    run_agent_mock = AsyncMock()
    monkeypatch.setattr("agent.main.run_agent", run_agent_mock)

    app.state.pending_task = "test task"

    async with lifespan(app):
        # yield happens — give the created task a chance to start
        await asyncio.sleep(0)

    run_agent_mock.assert_awaited_once_with("test task")
