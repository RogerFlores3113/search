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
    """run_agent must build BrowserProfile(channel='chrome', ...) then BrowserSession(browser_profile=...)."""
    mock_browser = _make_mock_browser()
    mock_profile = MagicMock()
    MockBrowserProfile = MagicMock(return_value=mock_profile)
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_history = _make_mock_history()
    mock_agent_instance = _make_mock_agent(mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)
    MockChatOllama = MagicMock()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    with patch("agent.runner.BrowserProfile", MockBrowserProfile), \
         patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        await run_agent("test task")

    # BrowserProfile must be built with browser settings and prohibited_domains
    assert MockBrowserProfile.called, "BrowserProfile was never instantiated"
    profile_kwargs = MockBrowserProfile.call_args.kwargs
    assert profile_kwargs.get("channel") == "chrome"
    assert profile_kwargs.get("headless") is False
    assert profile_kwargs.get("keep_alive") is False
    assert profile_kwargs.get("window_size") == {"width": 1280, "height": 800}
    assert "prohibited_domains" in profile_kwargs

    # BrowserSession must be built with the profile object
    MockBrowserSession.assert_called_once_with(browser_profile=mock_profile)
    assert mock_browser.llm_screenshot_size == (1024, 640)


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
        ollama_options={"num_ctx": 32000},
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
    """run_agent must call agent.run(max_steps=config.max_steps, on_step_end=<callable>).

    After WR-01, on_step_end is a closure (_log_step) that threads run_id into log_step,
    so we assert it is a callable rather than checking the exact function reference.
    """
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

    call_kwargs = mock_agent_instance.run.call_args
    assert call_kwargs is not None, "agent.run() was not called"
    assert call_kwargs.kwargs.get("max_steps") == _default_config.max_steps
    assert callable(call_kwargs.kwargs.get("on_step_end")), "on_step_end must be a callable"


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
    """run_agent must await browser.kill() on RuntimeError and capture error in queue.

    WR-03: the RuntimeError must NOT propagate out of run_agent — it is already
    captured in error_msg and emitted as an ErrorEvent via the queue's finally
    block. Re-raising would produce noisy 'Task exception was never retrieved'
    warnings when run_agent is launched via asyncio.create_task().
    """
    import asyncio
    from agent.events import ErrorEvent, DoneEvent

    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)
    MockChatOllama = MagicMock()

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("agent error"))
    MockAgent = MagicMock(return_value=mock_agent_instance)

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()

    with patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):
        from agent.runner import run_agent
        # run_agent must complete without raising — error is surfaced via queue
        await run_agent("test task", queue=queue)

    mock_browser.kill.assert_awaited_once()

    # Error must be captured and sent to the queue, not re-raised
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) >= 1, f"Expected ErrorEvent in queue; got {[type(e).__name__ for e in events]}"
    assert "agent error" in error_events[0].message
    assert isinstance(events[-1], DoneEvent), f"Last event must be DoneEvent; got {events[-1]}"


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


# ---------------------------------------------------------------------------
# build_llm factory (MODEL-02, MODEL-03)
# ---------------------------------------------------------------------------

def test_build_llm_returns_chat_ollama_for_ollama_provider(monkeypatch_env):
    """build_llm must return a ChatOllama instance when provider='ollama'."""
    from agent.config import Settings
    from agent.runner import build_llm

    cfg = Settings()
    with patch("agent.runner.ChatOllama") as MockChatOllama:
        build_llm(cfg)
        MockChatOllama.assert_called_once_with(
            model=cfg.ollama_model,
            ollama_options={"num_ctx": 32000},
        )


def test_build_llm_returns_chat_anthropic_for_anthropic_provider(monkeypatch_env):
    """build_llm must return a ChatAnthropic instance when provider='anthropic'."""
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    from agent.config import Settings
    from agent.runner import build_llm

    cfg = Settings()
    with patch("agent.runner.ChatAnthropic") as MockChatAnthropic:
        build_llm(cfg)
        MockChatAnthropic.assert_called_once_with(
            model=cfg.anthropic_model,
            api_key="sk-ant-fake",
        )


def test_build_llm_returns_chat_litellm_for_openai_provider(monkeypatch_env):
    """build_llm must return a ChatLiteLLM instance when provider='openai'."""
    monkeypatch_env.setenv("PROVIDER", "openai")
    monkeypatch_env.setenv("OPENAI_API_KEY", "sk-openai-fake")
    from agent.config import Settings
    from agent.runner import build_llm

    cfg = Settings()
    with patch("agent.runner.ChatLiteLLM") as MockChatLiteLLM:
        build_llm(cfg)
        MockChatLiteLLM.assert_called_once_with(
            model=cfg.openai_model,
            api_key="sk-openai-fake",
        )


def test_build_llm_raises_for_unknown_provider(monkeypatch_env):
    """build_llm must raise ValueError for an unrecognised provider string."""
    monkeypatch_env.setenv("PROVIDER", "groq")
    from agent.config import Settings
    from agent.runner import build_llm

    with pytest.raises(ValueError, match="Unknown provider"):
        build_llm(Settings())


# ---------------------------------------------------------------------------
# pre_flight_check — anthropic branch (MODEL-02)
# ---------------------------------------------------------------------------

async def test_preflight_raises_when_anthropic_key_missing(monkeypatch_env):
    """pre_flight_check must raise PreFlightError when provider=anthropic and key absent."""
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    from agent.config import Settings
    from agent.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="Missing Anthropic API key"):
        await pre_flight_check(Settings())


async def test_preflight_raises_when_anthropic_key_invalid(monkeypatch_env):
    """pre_flight_check must raise PreFlightError on Anthropic AuthenticationError."""
    import anthropic as _anthropic
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-bad-key")
    from agent.config import Settings
    from agent.runner import PreFlightError, pre_flight_check

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(
        side_effect=_anthropic.AuthenticationError(
            message="invalid key", response=MagicMock(), body={}
        )
    )
    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        with pytest.raises(PreFlightError, match="Invalid Anthropic API key"):
            await pre_flight_check(Settings())


# ---------------------------------------------------------------------------
# pre_flight_check — openai branch (MODEL-03)
# ---------------------------------------------------------------------------

async def test_preflight_raises_when_openai_key_missing(monkeypatch_env):
    """pre_flight_check must raise PreFlightError when provider=openai and key absent."""
    monkeypatch_env.setenv("PROVIDER", "openai")
    from agent.config import Settings
    from agent.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="Missing OpenAI API key"):
        await pre_flight_check(Settings())


async def test_preflight_raises_when_openai_key_invalid(monkeypatch_env, httpx_mock):
    """pre_flight_check must raise PreFlightError when OpenAI returns 401."""
    monkeypatch_env.setenv("PROVIDER", "openai")
    monkeypatch_env.setenv("OPENAI_API_KEY", "sk-bad")
    httpx_mock.add_response(
        method="GET",
        url="https://api.openai.com/v1/models",
        status_code=401,
    )
    from agent.config import Settings
    from agent.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="Invalid OpenAI API key"):
        await pre_flight_check(Settings())


# ---------------------------------------------------------------------------
# CAPTCHA detection in log_step (GUARD-04)
# ---------------------------------------------------------------------------

async def test_captcha_keyword_triggers_pause(training_dir):
    """log_step must call agent.pause() when error text contains a CAPTCHA keyword."""
    import types
    from agent.runner import log_step

    result_stub = types.SimpleNamespace(error="Please solve the captcha to continue")
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "navigate", "action_target": "", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: True,
    )
    agent = types.SimpleNamespace(
        history=history,
        state=types.SimpleNamespace(last_result=[result_stub]),
        pause=MagicMock(),
    )
    await log_step(agent, run_id="test-run-id")
    agent.pause.assert_called_once()


async def test_captcha_notification_printed_to_stdout(training_dir, capsys):
    """log_step must print a CAPTCHA notification message to stdout on detection."""
    import types
    from agent.runner import log_step

    result_stub = types.SimpleNamespace(error="recaptcha challenge detected")
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "navigate", "action_target": "", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: True,
    )
    agent = types.SimpleNamespace(
        history=history,
        state=types.SimpleNamespace(last_result=[result_stub]),
        pause=MagicMock(),
    )
    await log_step(agent, run_id="test-run-id")
    captured = capsys.readouterr()
    assert "CAPTCHA" in captured.out


async def test_no_captcha_no_pause_when_error_text_clean(training_dir):
    """log_step must NOT call agent.pause() when error text contains no CAPTCHA keyword."""
    import types
    from agent.runner import log_step

    result_stub = types.SimpleNamespace(error="element not found")
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "click", "action_target": "#x", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: True,
    )
    agent = types.SimpleNamespace(
        history=history,
        state=types.SimpleNamespace(last_result=[result_stub]),
        pause=MagicMock(),
    )
    await log_step(agent, run_id="test-run-id")
    agent.pause.assert_not_called()
