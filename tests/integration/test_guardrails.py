"""Integration tests for guardrail enforcement in agent/runner.py (GUARD-01, GUARD-02)."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from agent.config import Settings
from agent.runner import PreFlightError


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
async def test_run_agent_passes_blocked_domains_to_browser_profile(monkeypatch_env):
    """run_agent must construct BrowserProfile with prohibited_domains=cfg.blocked_domains."""
    from agent.runner import GUARDRAIL_PROMPT

    cfg = Settings()
    mock_profile = MagicMock()
    MockBrowserProfile = MagicMock(return_value=mock_profile)

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    MockBrowserSession = MagicMock(return_value=mock_browser)

    mock_agent_instance = MagicMock()
    mock_history = MagicMock()
    mock_history.final_result.return_value = "done"
    mock_agent_instance.run = AsyncMock(return_value=mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserProfile", MockBrowserProfile), \
         patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.Agent", MockAgent), \
         patch("agent.runner.build_llm", MagicMock()):
        from agent.runner import run_agent
        await run_agent("test task")

    call_kwargs = MockBrowserProfile.call_args.kwargs
    assert call_kwargs["prohibited_domains"] == cfg.blocked_domains


@pytest.mark.xfail(reason="Implemented in Task 2", strict=True)
async def test_run_agent_passes_guardrail_prompt_to_agent(monkeypatch_env):
    """run_agent must construct Agent with extend_system_message=GUARDRAIL_PROMPT."""
    from agent.runner import GUARDRAIL_PROMPT

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    MockBrowserSession = MagicMock(return_value=mock_browser)
    MockBrowserProfile = MagicMock(return_value=MagicMock())

    mock_agent_instance = MagicMock()
    mock_history = MagicMock()
    mock_history.final_result.return_value = "done"
    mock_agent_instance.run = AsyncMock(return_value=mock_history)
    MockAgent = MagicMock(return_value=mock_agent_instance)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserProfile", MockBrowserProfile), \
         patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.Agent", MockAgent), \
         patch("agent.runner.build_llm", MagicMock()):
        from agent.runner import run_agent
        await run_agent("test task")

    call_kwargs = MockAgent.call_args.kwargs
    assert call_kwargs.get("extend_system_message") == GUARDRAIL_PROMPT
