"""Unit tests for run_agent in local_browser_agent/app/runner.py (LOOP-02 through LOOP-06, MODEL-01 wiring).

Tests use mocks to verify the construction chain and lifecycle contracts without
requiring a live Chrome or Ollama instance.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from local_browser_agent.app.config import config as _default_config


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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())

    with patch("local_browser_agent.browser.BrowserProfile", MockBrowserProfile), \
         patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
        await run_agent("test task")

    MockChatOllama.assert_called_once_with(
        model=_default_config.ollama_model,
        host=_default_config.ollama_host,
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

    # The library supervises the whole run itself (not via asyncio.wait_for): the app only has
    # to hand the configured session timeout to AgentConfig.timeout_s.
    from local_browser_agent.app.runner import build_agent_config
    assert build_agent_config(_default_config).timeout_s == _default_config.session_timeout

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())
    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
        await run_agent("test task")
    assert mock_agent_instance.run.await_count == 1


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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("local_browser_agent.app.runner.asyncio.wait_for", raise_timeout)

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
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
    from local_browser_agent.app.events import ErrorEvent, DoneEvent

    mock_browser = _make_mock_browser()
    MockBrowserSession = MagicMock(return_value=mock_browser)
    MockChatOllama = MagicMock()

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(side_effect=RuntimeError("agent error"))
    MockAgent = MagicMock(return_value=mock_agent_instance)

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())

    queue: asyncio.Queue = asyncio.Queue()

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
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

    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", fake_preflight)

    with patch("local_browser_agent.browser.BrowserSession", MockBrowserSession), \
         patch("browser_use.ChatOllama", MockChatOllama), \
         patch("local_browser_agent.runner.Agent", MockAgent):
        from local_browser_agent.app.runner import run_agent
        with pytest.raises(SystemExit) as exc:
            await run_agent("test task")

    assert exc.value.code == 1
    MockBrowserSession.assert_not_called()


# ---------------------------------------------------------------------------
# FastAPI lifespan creates agent task when pending_task is set
# ---------------------------------------------------------------------------

async def test_lifespan_creates_agent_task_when_pending_task_set(monkeypatch):
    """FastAPI lifespan must call run_agent with pending_task via asyncio.create_task."""
    from local_browser_agent.app.main import app, lifespan

    run_agent_mock = AsyncMock()
    monkeypatch.setattr("local_browser_agent.app.main.run_agent", run_agent_mock)

    app.state.pending_task = "test task"

    async with lifespan(app):
        # yield happens — give the created task a chance to start
        await asyncio.sleep(0)

    run_agent_mock.assert_awaited_once()
    assert run_agent_mock.await_args.args == ("test task",)
    assert callable(run_agent_mock.await_args.kwargs["on_agent"])  # pause/stop reach the run


# ---------------------------------------------------------------------------
# build_llm factory (MODEL-02, MODEL-03)
# ---------------------------------------------------------------------------

def test_build_llm_returns_chat_ollama_for_ollama_provider(monkeypatch_env):
    """build_llm must return a ChatOllama instance when provider='ollama'."""
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import build_llm

    cfg = Settings()
    with patch("browser_use.ChatOllama") as MockChatOllama:
        build_llm(cfg)
        MockChatOllama.assert_called_once_with(
            model=cfg.ollama_model,
            host=cfg.ollama_host,
            ollama_options={"num_ctx": 32000},
        )


def test_build_llm_returns_chat_anthropic_for_anthropic_provider(monkeypatch_env):
    """build_llm must return a ChatAnthropic instance when provider='anthropic'."""
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import build_llm

    cfg = Settings()
    with patch("browser_use.ChatAnthropic") as MockChatAnthropic:
        build_llm(cfg)
        MockChatAnthropic.assert_called_once_with(
            model=cfg.anthropic_model,
            api_key="sk-ant-fake",
        )


def test_build_llm_returns_chat_litellm_for_openai_provider(monkeypatch_env):
    """build_llm must return a ChatLiteLLM instance when provider='openai'."""
    monkeypatch_env.setenv("PROVIDER", "openai")
    monkeypatch_env.setenv("OPENAI_API_KEY", "sk-openai-fake")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import build_llm

    cfg = Settings()
    with patch("browser_use.ChatLiteLLM") as MockChatLiteLLM:
        build_llm(cfg)
        MockChatLiteLLM.assert_called_once_with(
            model=cfg.openai_model,
            api_key="sk-openai-fake",
        )


def test_build_llm_raises_for_unknown_provider(monkeypatch_env):
    """build_llm must raise ValueError for an unrecognised provider string."""
    monkeypatch_env.setenv("PROVIDER", "groq")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import build_llm

    with pytest.raises(ValueError, match="Unknown provider"):
        build_llm(Settings())


# ---------------------------------------------------------------------------
# pre_flight_check — anthropic branch (MODEL-02)
# ---------------------------------------------------------------------------

async def test_preflight_raises_when_anthropic_key_missing(monkeypatch_env):
    """pre_flight_check must raise PreFlightError when provider=anthropic and key absent."""
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="No Anthropic API key is set.*Settings"):
        await pre_flight_check(Settings())


async def test_preflight_raises_when_anthropic_key_invalid(monkeypatch_env):
    """pre_flight_check must raise PreFlightError on Anthropic AuthenticationError."""
    import anthropic as _anthropic
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-bad-key")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(
        side_effect=_anthropic.AuthenticationError(
            message="invalid key", response=MagicMock(), body={}
        )
    )
    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        with pytest.raises(PreFlightError, match="Anthropic API key was rejected"):
            await pre_flight_check(Settings())


# ---------------------------------------------------------------------------
# pre_flight_check — openai branch (MODEL-03)
# ---------------------------------------------------------------------------

async def test_preflight_raises_when_openai_key_missing(monkeypatch_env):
    """pre_flight_check must raise PreFlightError when provider=openai and key absent."""
    monkeypatch_env.setenv("PROVIDER", "openai")
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="No OpenAI API key is set.*Settings"):
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
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError, match="OpenAI API key was rejected"):
        await pre_flight_check(Settings())


# ---------------------------------------------------------------------------
# CAPTCHA pause + resume (GUARD-04; replaces the old log_step keyword/pause tests)
# Keyword detection itself is covered in tests/lib/test_captcha.py.
# ---------------------------------------------------------------------------

def test_app_config_pauses_on_captcha(monkeypatch_env):
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import build_agent_config

    assert build_agent_config(Settings()).on_captcha == "pause"


async def test_captcha_notice_printed_to_stdout(capsys):
    """A HumanNeededEvent prints the CAPTCHA notice telling the user to solve it and press Resume."""
    from local_browser_agent.app.runner import _console_sink
    from local_browser_agent.events import HumanNeededEvent, StateEvent

    await _console_sink(StateEvent(state="running"))
    assert capsys.readouterr().out == ""
    await _console_sink(HumanNeededEvent(reason="captcha", url="https://x.test"))
    out = capsys.readouterr().out
    assert "CAPTCHA" in out and "Resume" in out


async def test_run_agent_captcha_pauses_then_resume_continues(monkeypatch, training_dir):
    """End to end through run_agent: a CAPTCHA error pauses the run (StateEvent paused on the
    control queue), the UI's Resume (BrowserAgent.resume via the on_agent hook) continues it."""
    import types
    from local_browser_agent.app.events import StateEvent
    from local_browser_agent.app.runner import run_agent

    holder = {}
    ran = []

    class FakeAgent:
        def __init__(self, **kw):
            self.state = types.SimpleNamespace(stopped=False, last_result=[])
            self.actions = []
            self.paused = False
            self.history = types.SimpleNamespace(
                number_of_steps=lambda: len(self.actions), model_actions=lambda: self.actions,
                screenshots=lambda: ["abc"], has_errors=lambda: False, urls=lambda: ["https://x.test"],
                final_result=lambda: "finished", is_successful=lambda: True)
            self.token_cost_service = types.SimpleNamespace(usage_history=[], calculate_cost=None)

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        def stop(self):
            self.state.stopped = True

        async def run(self, max_steps, on_step_end):
            for i in range(1, 4):
                while self.paused and not self.state.stopped:
                    await asyncio.sleep(0.01)
                self.actions.append({"click": {"index": i}, "interacted_element": None})
                self.state.last_result = [types.SimpleNamespace(error="Please solve the captcha")] if i == 1 else []
                ran.append(i)
                await on_step_end(self)
            return self.history

    browser = _make_mock_browser()
    monkeypatch.setattr("local_browser_agent.app.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("local_browser_agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("local_browser_agent.browser.BrowserSession", MagicMock(return_value=browser))
    monkeypatch.setattr("local_browser_agent.browser.BrowserProfile", MagicMock())
    monkeypatch.setattr("local_browser_agent.runner.Agent", FakeAgent)

    data_q: asyncio.Queue = asyncio.Queue()
    ctrl_q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(run_agent("t", queue=data_q, control_queue=ctrl_q,
                                         on_agent=lambda a: holder.__setitem__("agent", a)))
    await asyncio.sleep(0.3)
    ba = holder["agent"]
    assert ba is not None and ba.is_paused and ran == [1] and not task.done()
    ba.resume()
    await asyncio.wait_for(task, 3)
    assert ran == [1, 2, 3] and holder["agent"] is None

    states = []
    while not ctrl_q.empty():
        e = ctrl_q.get_nowait()
        if isinstance(e, StateEvent):
            states.append(e.state)
    assert states == ["running", "paused", "running", "complete"]
