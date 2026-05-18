"""Phase 5 RED gate tests: token counting, timing, and model info events.

All tests in this file are RED (failing) until Plan 02 wires runner.py.
Tests cover every row in 05-RESEARCH.md Phase Requirements -> Test Map.

Requirements covered: PERF-01, PERF-02, PERF-04
"""
from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.events import TokenEvent, ModelInfoEvent, ActionDetailEvent, StateEvent


# ---------------------------------------------------------------------------
# Fake agent helpers
# ---------------------------------------------------------------------------

def _make_fake_agent_with_tokens(prompt_tokens=100, completion_tokens=50, cost=0.000123):
    """Fake agent with token_cost_service populated for API provider tests."""
    usage = types.SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    cost_calc = types.SimpleNamespace(total_cost=cost)
    entry = types.SimpleNamespace(usage=usage, model="claude-sonnet-4-5")

    token_cost_service = types.SimpleNamespace(
        usage_history=[entry],
        calculate_cost=AsyncMock(return_value=cost_calc),
    )
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"click_element": {"index": 5}, "interacted_element": None}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(history=history, state=state, token_cost_service=token_cost_service)


def _make_fake_agent_ollama():
    """Fake agent for Ollama path — usage_history is empty (Ollama never appends)."""
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
# PERF-01: step_duration_ms on NarrationEvent
# ---------------------------------------------------------------------------

async def test_action_detail_event_emitted_per_step(training_dir, monkeypatch_env):
    """ActionDetailEvent must be emitted by _log_step once per step with correct action_type and step.

    NarrationEvent was replaced by ActionDetailEvent in Phase 6 Plan 02 (D-05).
    ActionDetailEvent carries structured action metadata instead of a text narration.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
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
    assert len(action_detail_events) >= 1, (
        f"Expected at least one ActionDetailEvent; got {[type(e).__name__ for e in events]}"
    )
    assert action_detail_events[0].step == 1, (
        f"ActionDetailEvent.step must be 1; got {action_detail_events[0].step}"
    )
    assert action_detail_events[0].action_type == "click_element", (
        f"ActionDetailEvent.action_type must be 'click_element'; got {action_detail_events[0].action_type!r}"
    )


async def test_log_step_timing_closure_executes(training_dir, monkeypatch_env):
    """Timing closure in _log_step must execute and run completes with ActionDetailEvent emitted.

    step_duration_ms is computed in _log_step and is surfaced on ActionDetailEvent (PERF-01 wired in Phase 9.1).
    This test guards against regression in the surrounding closure structure by confirming the run completes and
    ActionDetailEvent is emitted even after a sleep delay.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            # Sleep 10ms to ensure timing closure executes across measurable elapsed time
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
    assert len(action_detail_events) >= 1, (
        f"Expected at least one ActionDetailEvent after timing closure; "
        f"got {[type(e).__name__ for e in events]}"
    )


# ---------------------------------------------------------------------------
# PERF-02: TokenEvent emitted per step
# ---------------------------------------------------------------------------

async def test_token_event_emitted_per_step(training_dir, monkeypatch_env):
    """Exactly one TokenEvent must be emitted per _log_step invocation.

    This test is RED until Plan 02 adds queue.put_nowait(TokenEvent(...)) to _log_step.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
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

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert len(token_events) == 1, (
        f"Expected exactly 1 TokenEvent per _log_step; got {len(token_events)}"
    )


async def test_ollama_token_event_fields_are_none(training_dir, monkeypatch_env):
    """TokenEvent emitted for Ollama steps must have None for all numeric fields.

    This test is RED until Plan 02 gates token extraction behind the provider check.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_ollama()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    # PROVIDER defaults to "ollama" — monkeypatch_env clears env vars so Settings() is ollama
    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert len(token_events) >= 1, "Expected at least one TokenEvent for Ollama run"
    t = token_events[0]
    assert t.prompt_tokens is None, f"Ollama TokenEvent.prompt_tokens must be None; got {t.prompt_tokens!r}"
    assert t.completion_tokens is None, f"Ollama TokenEvent.completion_tokens must be None; got {t.completion_tokens!r}"
    assert t.cost_usd is None, f"Ollama TokenEvent.cost_usd must be None; got {t.cost_usd!r}"


async def test_api_token_event_has_integer_counts(training_dir, monkeypatch_env):
    """For Anthropic provider, TokenEvent.prompt_tokens and completion_tokens must be positive ints.

    This test is RED until Plan 02 reads token_cost_service.usage_history[-1].usage.
    """
    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    from agent.runner import run_agent
    import agent.runner as runner_mod

    # Patch config.provider on the module-level singleton so config.provider.lower()
    # returns "anthropic" inside _log_step. The module-level config singleton does not
    # pick up env var changes set after import.
    monkeypatch_env.setattr(runner_mod.config, "provider", "anthropic")

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens(prompt_tokens=150, completion_tokens=75, cost=0.000456)

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatAnthropic", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert len(token_events) >= 1, "Expected at least one TokenEvent for Anthropic run"
    t = token_events[0]
    assert isinstance(t.prompt_tokens, int) and t.prompt_tokens > 0, (
        f"prompt_tokens must be a positive int; got {t.prompt_tokens!r}"
    )
    assert isinstance(t.completion_tokens, int) and t.completion_tokens > 0, (
        f"completion_tokens must be a positive int; got {t.completion_tokens!r}"
    )


# ---------------------------------------------------------------------------
# PERF-04: ModelInfoEvent at run start
# ---------------------------------------------------------------------------

async def test_model_info_event_emitted_at_run_start(training_dir, monkeypatch_env):
    """ModelInfoEvent must appear immediately after StateEvent(state='running') in the queue.

    Position must be: StateEvent('running') at index N, ModelInfoEvent at index N+1.
    This test is RED until Plan 02 emits ModelInfoEvent after StateEvent('running').
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
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

    running_indices = [i for i, e in enumerate(events) if isinstance(e, StateEvent) and e.state == "running"]
    model_info_indices = [i for i, e in enumerate(events) if isinstance(e, ModelInfoEvent)]

    assert len(running_indices) >= 1, "Expected StateEvent(state='running') in queue"
    assert len(model_info_indices) >= 1, (
        f"Expected ModelInfoEvent in queue; got {[type(e).__name__ for e in events]}"
    )
    running_idx = running_indices[0]
    model_info_idx = model_info_indices[0]
    assert model_info_idx == running_idx + 1, (
        f"ModelInfoEvent must be immediately after StateEvent('running'); "
        f"running_idx={running_idx}, model_info_idx={model_info_idx}"
    )


async def test_model_info_event_fields(training_dir, monkeypatch_env):
    """ModelInfoEvent.provider must equal config.provider and model_name the resolved model field.

    For default Ollama config: provider='ollama', model_name=config.ollama_model.
    This test is RED until Plan 02 emits ModelInfoEvent with resolved model name.
    """
    from agent.config import Settings
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_with_tokens()

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    expected_cfg = Settings()  # reads defaults: provider='ollama', ollama_model='qwen3-vl:8b'

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    model_info_events = [e for e in events if isinstance(e, ModelInfoEvent)]
    assert len(model_info_events) >= 1, (
        f"Expected ModelInfoEvent in queue; got {[type(e).__name__ for e in events]}"
    )
    m = model_info_events[0]
    assert m.provider == expected_cfg.provider, (
        f"ModelInfoEvent.provider must be {expected_cfg.provider!r}; got {m.provider!r}"
    )
    assert m.model_name == expected_cfg.ollama_model, (
        f"ModelInfoEvent.model_name must be {expected_cfg.ollama_model!r}; got {m.model_name!r}"
    )


# ---------------------------------------------------------------------------
# Guard: log_step return value
# ---------------------------------------------------------------------------

async def test_log_step_returns_token_dict(training_dir, monkeypatch_env):
    """log_step must return a dict with exactly the three token keys (not None).

    This test is RED until Plan 02 changes log_step return type from None to dict.
    """
    from agent.runner import log_step

    fake_agent = _make_fake_agent_with_tokens()
    result = await log_step(fake_agent, run_id="test-run-id", provider="anthropic", duration_ms=0)

    assert isinstance(result, dict), (
        f"log_step must return dict; got {type(result)}"
    )
    assert "prompt_tokens" in result, "log_step dict must contain 'prompt_tokens'"
    assert "completion_tokens" in result, "log_step dict must contain 'completion_tokens'"
    assert "cost_usd" in result, "log_step dict must contain 'cost_usd'"


# ---------------------------------------------------------------------------
# Guard: Agent constructor receives calculate_cost=True
# ---------------------------------------------------------------------------

async def test_run_agent_sets_calculate_cost(training_dir, monkeypatch_env):
    """run_agent must construct Agent with calculate_cost=True.

    This test is RED until Plan 02 adds calculate_cost=True to the Agent constructor call.
    """
    from agent.runner import run_agent

    captured_kwargs: dict = {}

    class CapturingAgentClass:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self._history = MagicMock()
            self._history.final_result.return_value = "done"

        async def run(self, max_steps, on_step_end):
            return self._history

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatAnthropic", MagicMock()), \
         patch("agent.runner.Agent", CapturingAgentClass):
        await run_agent("test task")

    assert captured_kwargs.get("calculate_cost") is True, (
        f"Agent must be constructed with calculate_cost=True; got kwargs: {captured_kwargs}"
    )
