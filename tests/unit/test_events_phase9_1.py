"""Phase 9.1 RED gate test suite: ActionDetailEvent.step_duration_ms contract for PERF-01."""
from __future__ import annotations

import asyncio
import dataclasses
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.events import ActionDetailEvent
from agent.runner import run_agent


# ---------------------------------------------------------------------------
# Fake agent helpers
# ---------------------------------------------------------------------------

def _make_fake_agent_with_tokens():
    """Fake agent with token_cost_service populated for integration test."""
    token_cost_service = types.SimpleNamespace(
        usage_history=[],
        calculate_cost=AsyncMock(return_value=None),
    )
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"click_element": {"index": 5}, "interacted_element": None}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(history=history, state=state, token_cost_service=token_cost_service)


# ---------------------------------------------------------------------------
# Test 1: shape test — field existence and default
# ---------------------------------------------------------------------------

def test_action_detail_event_has_step_duration_ms_field():
    """ActionDetailEvent must have step_duration_ms field: default None, accepts int, serializes via asdict."""
    evt = ActionDetailEvent()
    assert evt.step_duration_ms is None

    evt2 = ActionDetailEvent(
        step=1,
        action_type="click_element",
        step_duration_ms=1234,
    )
    assert evt2.step_duration_ms == 1234

    result = dataclasses.asdict(evt2)
    assert "step_duration_ms" in result
    assert result["step_duration_ms"] == 1234


# ---------------------------------------------------------------------------
# Test 2: roundtrip / serialization
# ---------------------------------------------------------------------------

def test_action_detail_event_duration_roundtrip():
    """step_duration_ms=1234 must survive dataclasses.asdict() — pins the JSONL/SSE serialization path."""
    evt = ActionDetailEvent(step=1, action_type="click_element", step_duration_ms=1234)
    result = dataclasses.asdict(evt)
    assert result["step_duration_ms"] == 1234


# ---------------------------------------------------------------------------
# Test 3: integration — _log_step must populate step_duration_ms on emitted event
# ---------------------------------------------------------------------------

async def test_log_step_puts_duration_on_action_detail_event(training_dir, monkeypatch_env):
    """_log_step must emit ActionDetailEvent with step_duration_ms != None after a timed step."""
    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await asyncio.sleep(0.010)
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_detail_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_detail_events) >= 1
    assert action_detail_events[0].step_duration_ms is not None
    assert action_detail_events[0].step_duration_ms >= 0
