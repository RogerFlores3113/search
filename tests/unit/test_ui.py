"""Unit tests for the Phase 3 web UI — POST /run, GET /stream, SSE queue bridge.

Tests use httpx.AsyncClient + ASGITransport (mirrors test_runner.py style).
Tests deferred to Plan 02 or Plan 03 are marked pytest.skip(reason="Plan 02/03").

All tests are async def without @pytest.mark.asyncio because asyncio_mode = "auto".
"""
from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _disclaimer_cookies() -> dict[str, str]:
    """Return a cookie dict carrying a valid signed disclaimer cookie.

    The /run, /pause, /stop endpoints gate on this cookie (Issue #5). Tests
    that exercise those endpoints set it directly rather than POSTing
    /accept-disclaimer first so each test stays self-contained.
    """
    from agent.main import DISCLAIMER_COOKIE_NAME, _disclaimer_serializer
    return {DISCLAIMER_COOKIE_NAME: _disclaimer_serializer().dumps("1")}


def _make_mock_history(final_result="task complete"):
    history = MagicMock()
    history.final_result.return_value = final_result
    return history


def _make_mock_agent(history=None):
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=history or _make_mock_history())
    mock_agent.state = MagicMock()
    mock_agent.state.paused = False
    mock_agent.pause = MagicMock()
    mock_agent.resume = MagicMock()
    mock_agent.stop = MagicMock()
    return mock_agent


def _make_fake_agent_instance():
    """Build a minimal fake browser-use agent instance for queue emission tests."""
    from unittest.mock import AsyncMock as _AsyncMock
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"navigate": {"url": "https://example.com"}, "interacted_element": None}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    token_cost_service = types.SimpleNamespace(
        usage_history=[],
        calculate_cost=_AsyncMock(return_value=None),
    )
    return types.SimpleNamespace(
        history=history,
        state=types.SimpleNamespace(last_result=[]),
        token_cost_service=token_cost_service,
    )


# ---------------------------------------------------------------------------
# Dataclass event type discriminants (passes in Wave 0)
# ---------------------------------------------------------------------------

def test_event_dataclasses_have_type_discriminant():
    """Each event class must carry the correct type literal field."""
    from agent.events import (
        ScreenshotEvent, StateEvent,
        ProgressEvent, SummaryEvent, ErrorEvent, DoneEvent,
    )
    import dataclasses

    assert dataclasses.is_dataclass(ScreenshotEvent)
    assert dataclasses.is_dataclass(StateEvent)
    assert dataclasses.is_dataclass(ProgressEvent)
    assert dataclasses.is_dataclass(SummaryEvent)
    assert dataclasses.is_dataclass(ErrorEvent)
    assert dataclasses.is_dataclass(DoneEvent)

    assert ScreenshotEvent().type == "screenshot"
    assert StateEvent().type == "state"
    assert ProgressEvent().type == "progress"
    assert SummaryEvent().type == "summary"
    assert ErrorEvent().type == "error_msg"
    assert DoneEvent().type == "done"


def test_narration_event_removed():
    """Regression guard for Issue #7: NarrationEvent must not be re-introduced.
    The runner emits ActionDetailEvent + ThoughtEvent + ProgressEvent now;
    bringing back a third per-step text event would re-create the dual
    row-builder divergence we deleted.
    """
    import agent.events
    assert not hasattr(agent.events, "NarrationEvent"), (
        "NarrationEvent was removed in Issue #7. Re-introducing it splits "
        "narration-row construction across two code paths — use "
        "ActionDetailEvent (+ optionally extend it) instead."
    )


# ---------------------------------------------------------------------------
# POST /run (LOOP-01)
# ---------------------------------------------------------------------------

async def test_post_run_returns_started(monkeypatch):
    """POST /run with task string must return 200 + {"status": "started"} + HX-Trigger header."""
    import agent.main as main_mod

    # Reset global state so there is no active task from a prior test
    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)

    # Prevent run_agent from actually running (it would try pre_flight_check)
    mock_run_agent = AsyncMock()
    monkeypatch.setattr("agent.main.run_agent", mock_run_agent)

    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/run", data={"task": "test task"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.headers.get("hx-trigger") == "streamStarted"


async def test_post_run_busy(monkeypatch):
    """Second POST /run while a task is active must return 409 with {"status": "busy"}."""
    import agent.main as main_mod
    from agent.main import app

    # Simulate an active running task
    fake_task = MagicMock()
    fake_task.done.return_value = False
    monkeypatch.setattr(main_mod, "_active_task", fake_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/run", data={"task": "another task"})

    assert resp.status_code == 409
    assert resp.json()["status"] == "busy"


async def test_post_run_concurrent_requests_yield_exactly_one_started(monkeypatch):
    """Two simultaneous POST /run requests must produce exactly one 200 and
    exactly one 409 — the busy check and the _active_task assignment are
    serialized under _start_lock so the TOCTOU race window is closed.

    Without the lock, both requests could pass the `_active_task is None`
    check at the same time and both schedule a run_agent task, leaving the
    first task orphaned and two BrowserSessions racing for Chrome.

    run_agent is replaced with a long-lived stub so the task created by the
    winning request stays in the "not done" state long enough for the racing
    request to observe it. The stub completes deterministically when the
    test sets an asyncio.Event.
    """
    import agent.main as main_mod

    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)
    monkeypatch.setattr(main_mod, "_active_control_queue", None)

    done_event = asyncio.Event()

    async def stub_run_agent(task, *, queue=None, control_queue=None):
        await done_event.wait()

    monkeypatch.setattr("agent.main.run_agent", stub_run_agent)

    async with AsyncClient(transport=ASGITransport(app=main_mod.app),
                           base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        try:
            r1, r2 = await asyncio.gather(
                client.post("/run", data={"task": "first"}),
                client.post("/run", data={"task": "second"}),
            )
        finally:
            done_event.set()
            if main_mod._active_task is not None:
                try:
                    await asyncio.wait_for(main_mod._active_task, timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], (
        f"Expected exactly one 200 + one 409 under concurrent /run; got {statuses}. "
        f"This means two requests both passed the busy check (race window open)."
    )
    started = r1 if r1.status_code == 200 else r2
    busy = r1 if r1.status_code == 409 else r2
    assert started.json()["status"] == "started"
    assert busy.json()["status"] == "busy"


async def test_post_run_sequential_after_completion_succeeds(monkeypatch):
    """The lock guards scheduling, NOT the duration of the run. A second
    /run posted AFTER the first task finishes must succeed — regression
    guard against accidentally serializing across run lifetimes.
    """
    import agent.main as main_mod

    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)
    monkeypatch.setattr(main_mod, "_active_control_queue", None)

    async def quick_run_agent(task, *, queue=None, control_queue=None):
        return  # finishes immediately

    monkeypatch.setattr("agent.main.run_agent", quick_run_agent)

    async with AsyncClient(transport=ASGITransport(app=main_mod.app),
                           base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        r1 = await client.post("/run", data={"task": "first"})
        assert r1.status_code == 200
        # Let the first task settle so _active_task.done() returns True.
        if main_mod._active_task is not None:
            try:
                await asyncio.wait_for(main_mod._active_task, timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass
        r2 = await client.post("/run", data={"task": "second"})

    assert r2.status_code == 200, (
        f"second sequential /run after task completion must succeed; "
        f"got {r2.status_code}: {r2.text}"
    )


# ---------------------------------------------------------------------------
# POST /pause (LOOP-07)
# ---------------------------------------------------------------------------

async def test_post_pause_calls_agent_pause(monkeypatch):
    """POST /pause must call agent.pause() when agent is active and not paused."""
    import agent.main as main_mod
    from agent.main import app

    mock_agent = _make_mock_agent()
    mock_agent.state.paused = False
    queue: asyncio.Queue = asyncio.Queue()

    monkeypatch.setattr(main_mod, "_active_agent", mock_agent)
    monkeypatch.setattr(main_mod, "_active_queue", queue)
    monkeypatch.setattr(main_mod, "_active_control_queue", queue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/pause")

    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    mock_agent.pause.assert_called_once()
    # StateEvent("paused") must be on the queue
    from agent.events import StateEvent
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    state_events = [e for e in events if isinstance(e, StateEvent)]
    assert any(e.state == "paused" for e in state_events), f"Expected StateEvent('paused'); got {events}"


async def test_post_pause_toggles_resume(monkeypatch):
    """POST /pause on a paused agent must call agent.resume() instead."""
    import agent.main as main_mod
    from agent.main import app

    mock_agent = _make_mock_agent()
    mock_agent.state.paused = True
    queue: asyncio.Queue = asyncio.Queue()

    monkeypatch.setattr(main_mod, "_active_agent", mock_agent)
    monkeypatch.setattr(main_mod, "_active_queue", queue)
    monkeypatch.setattr(main_mod, "_active_control_queue", queue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/pause")

    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"
    mock_agent.resume.assert_called_once()
    # StateEvent("running") must be on the queue
    from agent.events import StateEvent
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    state_events = [e for e in events if isinstance(e, StateEvent)]
    assert any(e.state == "running" for e in state_events), f"Expected StateEvent('running'); got {events}"


async def test_post_pause_no_active_run(monkeypatch):
    """POST /pause must return 400 when no agent is active."""
    import agent.main as main_mod
    from agent.main import app

    monkeypatch.setattr(main_mod, "_active_agent", None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/pause")

    assert resp.status_code == 400
    assert resp.json()["status"] == "no_active_run"


# ---------------------------------------------------------------------------
# POST /stop (LOOP-08)
# ---------------------------------------------------------------------------

async def test_post_stop_calls_agent_stop(monkeypatch):
    """POST /stop must call agent.stop() and return {"status": "stopped"}."""
    import agent.main as main_mod
    from agent.main import app

    mock_agent = _make_mock_agent()

    monkeypatch.setattr(main_mod, "_active_agent", mock_agent)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/stop")

    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"
    mock_agent.stop.assert_called_once()


async def test_post_stop_no_active_run(monkeypatch):
    """POST /stop must return 400 when no agent is active."""
    import agent.main as main_mod
    from agent.main import app

    monkeypatch.setattr(main_mod, "_active_agent", None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/stop")

    assert resp.status_code == 400
    assert resp.json()["status"] == "no_active_run"


# ---------------------------------------------------------------------------
# ActionDetailEvent emission from _log_step (LOOP-09, updated Phase 6 D-05)
# ---------------------------------------------------------------------------

async def test_log_step_emits_narration_event(monkeypatch):
    """run_agent's _log_step closure must put ActionDetailEvent on queue after log_step runs.

    NarrationEvent was replaced by ActionDetailEvent in Phase 6 Plan 02 (D-05).
    ActionDetailEvent carries structured action metadata (action_type, target, url, value)
    instead of a plain text narration string.
    """
    from agent.events import ActionDetailEvent, StateEvent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent_instance = _make_fake_agent_instance()

    # Patch log_step (the JSONL writer) to be a no-op so test stays unit-level
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))
    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None

    captured_on_step_end = {}

    async def fake_run(max_steps, on_step_end, **kwargs):
        captured_on_step_end["fn"] = on_step_end
        await on_step_end(fake_agent_instance)
        return _make_mock_history()

    mock_agent = MagicMock()
    mock_agent.run = fake_run

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())

    from agent.runner import run_agent
    await run_agent("test task", queue=queue)

    # Drain the queue into a list
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    event_types = [type(e).__name__ for e in events]
    assert "ActionDetailEvent" in event_types, f"Expected ActionDetailEvent; got {event_types}"

    action_detail_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_detail_events) >= 1
    assert action_detail_events[0].action_type == "navigate", (
        f"action_type must be 'navigate'; got {action_detail_events[0].action_type!r}"
    )


# ---------------------------------------------------------------------------
# SummaryEvent emission (LOOP-10)
# ---------------------------------------------------------------------------

async def test_run_agent_emits_summary_event(monkeypatch):
    """run_agent must put SummaryEvent(text=final_result) on queue on success."""
    from agent.events import SummaryEvent, StateEvent
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_history = _make_mock_history(final_result="Found article")
    mock_agent = _make_mock_agent(history=mock_history)

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    summary_events = [e for e in events if isinstance(e, SummaryEvent)]
    assert len(summary_events) >= 1, f"Expected SummaryEvent; got {[type(e).__name__ for e in events]}"
    assert summary_events[0].text == "Found article"

    # SummaryEvent must come before StateEvent("complete")
    summary_idx = next(i for i, e in enumerate(events) if isinstance(e, SummaryEvent))
    complete_idx = next(
        i for i, e in enumerate(events)
        if isinstance(e, StateEvent) and e.state == "complete"
    )
    assert summary_idx < complete_idx, "SummaryEvent must precede StateEvent('complete')"


async def test_run_agent_omits_summary_when_no_final_result(monkeypatch):
    """When history.final_result() returns None, NO SummaryEvent is emitted."""
    from agent.events import SummaryEvent, StateEvent, DoneEvent
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_history = _make_mock_history(final_result=None)
    mock_agent = _make_mock_agent(history=mock_history)

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # No SummaryEvent should be emitted
    summary_events = [e for e in events if isinstance(e, SummaryEvent)]
    assert len(summary_events) == 0, f"Expected no SummaryEvent; got {summary_events}"

    # But StateEvent("complete") and DoneEvent must still be emitted
    state_events = [e for e in events if isinstance(e, StateEvent)]
    states = [e.state for e in state_events]
    assert "complete" in states
    assert isinstance(events[-1], DoneEvent)


# ---------------------------------------------------------------------------
# ScreenshotEvent emission (UI-02)
# ---------------------------------------------------------------------------

async def test_log_step_does_not_emit_screenshot_event(monkeypatch):
    """_log_step must NOT emit ScreenshotEvent — Phase 7 D-05/D-06 moved this to _screenshot_loop."""
    from agent.events import ScreenshotEvent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent_instance = _make_fake_agent_instance()

    async def fake_run(max_steps, on_step_end):
        await on_step_end(fake_agent_instance)
        return _make_mock_history()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.take_screenshot = AsyncMock(return_value=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00')
    mock_browser.llm_screenshot_size = None
    mock_agent = MagicMock()
    mock_agent.run = fake_run

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    from agent.runner import run_agent
    import inspect
    source = inspect.getsource(run_agent)
    assert "history.screenshots()" not in source, (
        "_log_step must not contain history.screenshots() — removed in Phase 7 D-05/D-06"
    )


async def test_log_step_does_not_read_history_screenshots(monkeypatch):
    """_log_step must not call history.screenshots() — Phase 7 D-06 removed that code path."""
    from agent.runner import run_agent
    import inspect
    source = inspect.getsource(run_agent)
    assert "history.screenshots()" not in source, (
        "run_agent must not contain history.screenshots() inside run_agent — "
        "removed in Phase 7 D-06. ScreenshotEvent is now emitted by _screenshot_loop."
    )


async def test_log_step_emits_progress_event(monkeypatch):
    """_log_step closure must emit ProgressEvent with step==step_idx+1 and max_steps==config.max_steps."""
    from agent.events import ProgressEvent
    from agent.config import config

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent_instance = _make_fake_agent_instance()  # number_of_steps() returns 1

    async def fake_run(max_steps, on_step_end):
        await on_step_end(fake_agent_instance)
        return _make_mock_history()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_agent = MagicMock()
    mock_agent.run = fake_run

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    from agent.runner import run_agent
    await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    progress_events = [e for e in events if isinstance(e, ProgressEvent)]
    assert len(progress_events) >= 1, f"Expected ProgressEvent; got {[type(e).__name__ for e in events]}"
    # number_of_steps() returns 1, so step_idx = 0, step = 1
    assert progress_events[0].step == 1, f"Expected step=1; got {progress_events[0].step}"
    assert progress_events[0].max_steps == config.max_steps, f"Expected max_steps={config.max_steps}; got {progress_events[0].max_steps}"


# ---------------------------------------------------------------------------
# StateEvent emission (UI-04)
# ---------------------------------------------------------------------------

async def test_run_agent_emits_state_events(monkeypatch):
    """run_agent must emit StateEvent("running") at start and StateEvent("complete") in finally."""
    from agent.events import StateEvent

    queue: asyncio.Queue = asyncio.Queue()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=_make_mock_history())

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    from agent.runner import run_agent
    await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    state_events = [e for e in events if isinstance(e, StateEvent)]
    states = [e.state for e in state_events]

    assert "running" in states, f"Expected 'running' StateEvent; got states: {states}"
    assert "complete" in states, f"Expected 'complete' StateEvent; got states: {states}"
    # running must come before complete
    assert states.index("running") < states.index("complete")


# ---------------------------------------------------------------------------
# ErrorEvent on PreFlightError (UI-08)
# ---------------------------------------------------------------------------

async def test_run_agent_emits_error_event_on_preflight(monkeypatch):
    """When pre_flight_check raises PreFlightError, queue receives ErrorEvent + StateEvent('error') + DoneEvent."""
    from agent.runner import PreFlightError, run_agent
    from agent.events import ErrorEvent, StateEvent, DoneEvent

    queue: asyncio.Queue = asyncio.Queue()

    async def fake_preflight(cfg):
        raise PreFlightError("ollama not running")

    monkeypatch.setattr("agent.runner.pre_flight_check", fake_preflight)

    await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    # Sequence after the initial StateEvent("running"):
    # StateEvent("running"), ErrorEvent(...), StateEvent("error"), DoneEvent()
    assert any(isinstance(e, ErrorEvent) for e in events), f"Expected ErrorEvent; got {events}"
    error_ev = next(e for e in events if isinstance(e, ErrorEvent))
    assert "ollama not running" in error_ev.message

    state_events = [e for e in events if isinstance(e, StateEvent)]
    states = [e.state for e in state_events]
    assert "error" in states, f"Expected StateEvent('error'); got {states}"

    assert isinstance(events[-1], DoneEvent), f"Last event must be DoneEvent; got {events[-1]}"


# ---------------------------------------------------------------------------
# DB insert from runner finally (RUN-01)
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_dir(tmp_path, monkeypatch):
    """Patch DB_PATH to a tmp location so data/history.db writes stay isolated.

    Uses monkeypatch.setattr instead of chdir so the Jinja2 template directory
    (relative path 'agent/templates') remains resolvable from the project root.
    """
    import agent.db as _db_mod
    from pathlib import Path
    db_path = tmp_path / "data" / "history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_db_mod, "DB_PATH", db_path)
    return tmp_path


async def test_run_agent_inserts_run_to_db(monkeypatch, db_dir):
    """run_agent finally block must insert a row with task, status='complete', summary, and timestamps."""
    from agent.runner import run_agent
    from agent import db as history_db

    await history_db.init_db()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_history = _make_mock_history(final_result="found it")
    mock_agent = _make_mock_agent(history=mock_history)
    mock_agent.state = MagicMock()
    mock_agent.state.stopped = False

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    await run_agent("test task")

    runs = await history_db.list_runs(limit=10)
    assert len(runs) >= 1, f"Expected a run to be inserted; got {runs}"
    row = runs[0]
    assert row["task"] == "test task", f"Expected task='test task'; got {row['task']!r}"
    assert row["status"] == "complete", f"Expected status='complete'; got {row['status']!r}"
    assert row["summary"] == "found it", f"Expected summary='found it'; got {row['summary']!r}"
    assert row["started_at"] is not None
    assert row["completed_at"] is not None


async def test_run_agent_inserts_error_status_on_preflight(monkeypatch, db_dir):
    """When PreFlightError occurs, runner inserts a row with status='error'."""
    from agent.runner import run_agent, PreFlightError
    from agent import db as history_db

    await history_db.init_db()

    async def fake_preflight(cfg):
        raise PreFlightError("ollama not running")

    monkeypatch.setattr("agent.runner.pre_flight_check", fake_preflight)

    await run_agent("error task")

    runs = await history_db.list_runs(limit=10)
    assert len(runs) >= 1, f"Expected a row inserted; got {runs}"
    assert runs[0]["status"] == "error", f"Expected status='error'; got {runs[0]['status']!r}"


async def test_run_agent_inserts_stopped_status_when_agent_state_stopped(monkeypatch, db_dir):
    """When agent.state.stopped is True after run(), status is 'stopped'."""
    from agent.runner import run_agent
    from agent import db as history_db

    await history_db.init_db()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_history = _make_mock_history(final_result=None)
    mock_agent = _make_mock_agent(history=mock_history)
    mock_agent.state = MagicMock()
    mock_agent.state.stopped = True  # user stopped the agent

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    await run_agent("stopped task")

    runs = await history_db.list_runs(limit=10)
    assert len(runs) >= 1
    assert runs[0]["status"] == "stopped", f"Expected status='stopped'; got {runs[0]['status']!r}"


async def test_run_agent_clears_active_agent_in_finally(monkeypatch, db_dir):
    """After run_agent returns, _active_agent and _active_queue are both None."""
    import agent.main as main_mod
    from agent.runner import run_agent
    from agent import db as history_db

    await history_db.init_db()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_history = _make_mock_history()
    mock_agent = _make_mock_agent(history=mock_history)
    mock_agent.state = MagicMock()
    mock_agent.state.stopped = False

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    queue: asyncio.Queue = asyncio.Queue()
    monkeypatch.setattr(main_mod, "_active_queue", queue)

    await run_agent("clear task", queue=queue)

    assert main_mod._active_agent is None, f"Expected _active_agent=None; got {main_mod._active_agent}"
    assert main_mod._active_queue is None, f"Expected _active_queue=None; got {main_mod._active_queue}"


# ---------------------------------------------------------------------------
# GET /runs history endpoint (RUN-02)
# ---------------------------------------------------------------------------

async def test_get_runs_returns_history(monkeypatch, db_dir):
    """GET /runs must return HTML with the most recent run records."""
    from agent.main import app
    from agent import db as history_db

    await history_db.init_db()

    # Insert 3 runs in order
    await history_db.insert_run(
        run_id="run-001", task="first task", status="complete",
        summary=None, started_at="2026-05-16T10:00:00Z", completed_at="2026-05-16T10:01:00Z"
    )
    await history_db.insert_run(
        run_id="run-002", task="second task", status="error",
        summary=None, started_at="2026-05-16T11:00:00Z", completed_at="2026-05-16T11:01:00Z"
    )
    await history_db.insert_run(
        run_id="run-003", task="third task", status="stopped",
        summary=None, started_at="2026-05-16T12:00:00Z", completed_at="2026-05-16T12:01:00Z"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", ""), \
        f"Expected HTML; got {resp.headers.get('content-type')}"
    body = resp.text
    assert "first task" in body, "Expected 'first task' in response body"
    assert "second task" in body, "Expected 'second task' in response body"
    assert "third task" in body, "Expected 'third task' in response body"


# ---------------------------------------------------------------------------
# Task 2: runs_fragment.html rendering + UI pause/stop buttons + history panel
# ---------------------------------------------------------------------------

def test_runs_fragment_renders_rows():
    """runs_fragment.html must render each run's task, status, and started_at."""
    from fastapi.templating import Jinja2Templates
    t = Jinja2Templates(directory="agent/templates")
    runs = [
        {"task": "first task", "status": "complete", "summary": None,
         "started_at": "2026-05-16T10:00:00Z", "completed_at": None, "run_id": "a"},
        {"task": "second task", "status": "error", "summary": None,
         "started_at": "2026-05-16T11:00:00Z", "completed_at": None, "run_id": "b"},
        {"task": "third task", "status": "stopped", "summary": None,
         "started_at": "2026-05-16T12:00:00Z", "completed_at": None, "run_id": "c"},
    ]
    rendered = t.get_template("runs_fragment.html").render(runs=runs)
    assert "first task" in rendered
    assert "second task" in rendered
    assert "third task" in rendered
    assert "complete" in rendered
    assert "error" in rendered
    assert "stopped" in rendered
    assert "2026-05-16T10:00:00Z" in rendered


def test_runs_fragment_empty_state():
    """runs_fragment.html with empty runs must show 'No runs yet.' empty-state copy."""
    from fastapi.templating import Jinja2Templates
    t = Jinja2Templates(directory="agent/templates")
    rendered = t.get_template("runs_fragment.html").render(runs=[])
    assert "No runs yet. Enter a task above to start." in rendered


def test_runs_fragment_escapes_task():
    """runs_fragment.html must HTML-escape task strings (XSS mitigation T-03-02)."""
    from fastapi.templating import Jinja2Templates
    t = Jinja2Templates(directory="agent/templates")
    runs = [{"task": "<script>alert(1)</script>", "status": "complete", "summary": None,
             "started_at": "2026-05-16T00:00:00Z", "completed_at": None, "run_id": "abc"}]
    rendered = t.get_template("runs_fragment.html").render(runs=runs)
    assert "<script>" not in rendered, "XSS: raw <script> tag must not appear in output"
    assert "&lt;script&gt;" in rendered, "Expected Jinja2 auto-escaped &lt;script&gt;"


async def test_index_has_run_history_panel():
    """GET / response body must contain <section id='run-history' and hx-get='/runs' with load trigger."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert '<section id="run-history"' in body, "Missing <section id='run-history'>"
    assert 'hx-get="/runs"' in body, "Missing hx-get='/runs' in index.html"
    assert "load" in body, "Missing 'load' trigger in run history section"


async def test_index_pause_button_enabled_per_state():
    """Pause button must have hx-post='/pause' and Alpine :disabled binding for running/paused states."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert 'hx-post="/pause"' in body, "Missing hx-post='/pause' on Pause button"
    # The :disabled expression must evaluate to false when state in {running, paused}
    assert "state !== 'running' && state !== 'paused'" in body, \
        "Missing correct :disabled expression for Pause button"


async def test_index_stop_button_enabled_per_state():
    """Stop button must have hx-post='/stop' and Alpine :disabled binding for running/paused states."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert 'hx-post="/stop"' in body, "Missing hx-post='/stop' on Stop button"
    assert "state !== 'running' && state !== 'paused'" in body, \
        "Missing correct :disabled expression for Stop button"


async def test_index_pause_button_label_resume():
    """Pause button must have Alpine x-text binding for Pause/Resume toggle."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert "state === 'paused' ? 'Resume' : 'Pause'" in body, \
        "Missing x-text='state === ...' Pause/Resume toggle on Pause button"


# ---------------------------------------------------------------------------
# DoneEvent always emitted (D-11)
# ---------------------------------------------------------------------------

async def test_done_event_always_emitted(monkeypatch):
    """DoneEvent must be the last item on the queue for success, PreFlightError, and TimeoutError."""
    from agent.runner import PreFlightError, run_agent
    from agent.events import DoneEvent

    # --- Path 1: Success ---
    queue1: asyncio.Queue = asyncio.Queue()

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=_make_mock_history())

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.log_step", AsyncMock(return_value={"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}))

    await run_agent("success task", queue=queue1)
    events1 = []
    while not queue1.empty():
        events1.append(queue1.get_nowait())
    assert isinstance(events1[-1], DoneEvent), f"Success path: last event should be DoneEvent, got {events1[-1]}"

    # --- Path 2: PreFlightError ---
    queue2: asyncio.Queue = asyncio.Queue()

    async def raise_preflight(cfg):
        raise PreFlightError("ollama not running")

    monkeypatch.setattr("agent.runner.pre_flight_check", raise_preflight)
    await run_agent("preflight fail", queue=queue2)
    events2 = []
    while not queue2.empty():
        events2.append(queue2.get_nowait())
    assert isinstance(events2[-1], DoneEvent), f"PreFlightError path: last event should be DoneEvent, got {events2[-1]}"

    # --- Path 3: asyncio.TimeoutError ---
    queue3: asyncio.Queue = asyncio.Queue()

    mock_browser2 = MagicMock()
    mock_browser2.kill = AsyncMock()
    mock_browser2.llm_screenshot_size = None
    mock_agent2 = MagicMock()

    # Simulate agent.run() taking too long: have it raise TimeoutError, which
    # propagates through asyncio.wait_for the same way a real timeout would.
    # Narrower than patching asyncio.wait_for globally — leaves _put_control's
    # internal timeout untouched.
    async def agent_run_times_out(*args, **kwargs):
        raise asyncio.TimeoutError()
    mock_agent2.run = agent_run_times_out

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser2))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent2))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())

    await run_agent("timeout task", queue=queue3)
    events3 = []
    while not queue3.empty():
        events3.append(queue3.get_nowait())
    assert isinstance(events3[-1], DoneEvent), f"Timeout path: last event should be DoneEvent, got {events3[-1]}"


# ---------------------------------------------------------------------------
# SSE stream yields until DoneEvent (SSE)
# ---------------------------------------------------------------------------

async def test_sse_stream_yields_until_done(monkeypatch):
    """GET /stream must yield state+action_detail events then close on DoneEvent."""
    import agent.main as main_mod
    from agent.events import StateEvent, ActionDetailEvent, DoneEvent
    from agent.main import app

    # Pre-populate _active_queue with known events
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(StateEvent(state="running"))
    queue.put_nowait(ActionDetailEvent(step=1, action_type="navigate", url="https://example.com"))
    queue.put_nowait(DoneEvent())

    monkeypatch.setattr(main_mod, "_active_queue", queue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/stream")

    body = resp.text
    assert "event: state" in body, f"Expected 'event: state' in SSE body; got:\n{body}"
    assert "event: action_detail" in body, f"Expected 'event: action_detail' in SSE body; got:\n{body}"
    assert "event: done" in body, f"Expected 'event: done' in SSE body; got:\n{body}"


# ---------------------------------------------------------------------------
# Two-queue path: DoneEvent must arrive even when the data queue is full
# (Issue #2 — DoneEvent dropped on QueueFull caused SSE hang)
# ---------------------------------------------------------------------------

async def test_done_event_delivered_when_data_queue_full(monkeypatch):
    """With the two-queue split, DoneEvent rides the control queue and
    reaches the consumer even if the data queue is saturated. Before the
    fix, _put_nowait(DoneEvent) on a full single queue dropped silently.
    """
    import agent.main as main_mod
    from agent.events import DoneEvent, ScreenshotEvent, StateEvent
    from agent.main import app

    data_q: asyncio.Queue = asyncio.Queue(maxsize=3)
    ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=16)
    # Saturate the data queue.
    for _ in range(3):
        data_q.put_nowait(ScreenshotEvent(b64="x"))
    # Control queue has the lifecycle terminator.
    ctrl_q.put_nowait(StateEvent(state="complete"))
    ctrl_q.put_nowait(DoneEvent())

    monkeypatch.setattr(main_mod, "_active_queue", data_q)
    monkeypatch.setattr(main_mod, "_active_control_queue", ctrl_q)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/stream")

    body = resp.text
    assert "event: done" in body, (
        "DoneEvent must reach SSE consumer even when data queue is full; got:\n" + body
    )
    assert "event: state" in body, "control-queue StateEvent must also pass through"


async def test_stream_drains_data_queue_before_done(monkeypatch):
    """When DoneEvent arrives on the control queue, /stream must drain any
    remaining items from the data queue (the tail of the run — final
    screenshot, final token update) BEFORE yielding the done frame, so the
    user sees a complete sequence.
    """
    import agent.main as main_mod
    from agent.events import (
        DoneEvent, ScreenshotEvent, TokenEvent, StateEvent,
    )
    from agent.main import app

    data_q: asyncio.Queue = asyncio.Queue(maxsize=10)
    ctrl_q: asyncio.Queue = asyncio.Queue(maxsize=16)
    data_q.put_nowait(ScreenshotEvent(b64="frame-A"))
    data_q.put_nowait(TokenEvent(step=1, prompt_tokens=10, completion_tokens=5))
    data_q.put_nowait(ScreenshotEvent(b64="frame-B"))
    ctrl_q.put_nowait(StateEvent(state="complete"))
    ctrl_q.put_nowait(DoneEvent())

    monkeypatch.setattr(main_mod, "_active_queue", data_q)
    monkeypatch.setattr(main_mod, "_active_control_queue", ctrl_q)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/stream")

    body = resp.text
    # All tail data events must appear before the terminator.
    done_pos = body.find("event: done")
    assert done_pos != -1, "Expected event: done frame"
    for tail_marker in ("frame-A", "frame-B", '"prompt_tokens": 10'):
        pos = body.find(tail_marker)
        assert pos != -1, f"Expected tail marker {tail_marker!r} in body:\n{body}"
        assert pos < done_pos, (
            f"Tail marker {tail_marker!r} appeared after done — drain failed"
        )


async def test_pause_routes_state_event_to_control_queue(monkeypatch):
    """When both queues are wired, /pause emits StateEvent on the control
    queue (not the data queue) so the pause indicator can't be dropped by a
    saturated screenshot stream.
    """
    import agent.main as main_mod
    from agent.events import StateEvent
    from agent.main import app

    mock_agent = _make_mock_agent()
    mock_agent.state.paused = False
    data_q: asyncio.Queue = asyncio.Queue()
    ctrl_q: asyncio.Queue = asyncio.Queue()

    monkeypatch.setattr(main_mod, "_active_agent", mock_agent)
    monkeypatch.setattr(main_mod, "_active_queue", data_q)
    monkeypatch.setattr(main_mod, "_active_control_queue", ctrl_q)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           cookies=_disclaimer_cookies()) as client:
        resp = await client.post("/pause")

    assert resp.status_code == 200
    assert data_q.empty(), "StateEvent must not land on the data queue"
    events = []
    while not ctrl_q.empty():
        events.append(ctrl_q.get_nowait())
    assert any(isinstance(e, StateEvent) and e.state == "paused" for e in events), (
        f"Expected StateEvent('paused') on control queue; got {events}"
    )


# ---------------------------------------------------------------------------
# GET / returns HTML with SSE container (index.html check)
# ---------------------------------------------------------------------------

async def test_get_index_returns_html(monkeypatch):
    """GET / must return 200 HTML with hx-ext='sse', sse-connect='/stream', and textarea[name=task]."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert 'hx-ext="sse"' in body, "Expected hx-ext=\"sse\" in index.html"
    assert 'sse-connect="/stream"' in body, "Expected sse-connect=\"/stream\" in index.html"
    assert 'name="task"' in body, "Expected textarea name=\"task\" in index.html"


# ---------------------------------------------------------------------------
# Task 2: Alpine handlers + CSS wiring (UI-02, UI-05, UI-08, UI-09)
# ---------------------------------------------------------------------------

async def test_get_index_contains_alpine_handlers():
    """GET / response body must contain all six Alpine handler names."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    for handler in ("handleScreenshot", "handleProgress", "handleSummary",
                    "handleError", "handleState", "handleActionDetail",
                    "handleThought", "handleToken", "handleModelInfo"):
        assert handler in body, f"Missing Alpine handler: {handler}"
    assert "handleNarration" not in body, (
        "handleNarration was removed in Issue #7 — the row builder is now "
        "_ensureNarrationRow + handleActionDetail. See agent/templates/index.html."
    )


async def test_sse_bridges_use_data_bridge_not_hx_on():
    """SSE bridge divs must use data-bridge + Alpine init(), not hx-on.

    hx-on creates a global-scope function that cannot resolve Alpine component
    methods, producing 'handleState is not defined' ReferenceErrors and breaking
    all SSE-driven UI updates (screenshot, state, pause/stop buttons).
    """
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert "hx-on:htmx:sse-message" not in body, (
        "hx-on:htmx:sse-message resolves handlers in global scope; "
        "Alpine component methods are unreachable. Use data-bridge + init() instead."
    )
    for swap_name, handler in (
        ("state", "handleState"),
        ("summary", "handleSummary"),
        ("error_msg", "handleError"),
        ("screenshot", "handleScreenshot"),
        ("progress", "handleProgress"),
        ("token", "handleToken"),
        ("model_info", "handleModelInfo"),
        ("thought", "handleThought"),
        ("action_detail", "handleActionDetail"),
    ):
        assert f'sse-swap="{swap_name}"' in body, f"Missing sse-swap bridge for {swap_name}"
        assert f'data-bridge="{handler}"' in body, f"Missing data-bridge for {handler}"
    # Regression guard for Issue #7: the dead narration bridge stays out.
    assert 'sse-swap="narration"' not in body, (
        "narration sse-swap was removed in Issue #7"
    )
    assert "addEventListener('htmx:sseMessage'" in body, (
        "Expected init() to attach handlers via addEventListener('htmx:sseMessage', ...)"
    )


async def test_get_index_has_result_area():
    """GET / response body must contain #result-area with x-show='summary' and x-show='errorMsg'."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert 'id="result-area"' in body, "Missing #result-area div"
    assert 'x-show="summary"' in body, "Missing x-show='summary'"
    assert 'x-show="errorMsg"' in body, "Missing x-show='errorMsg'"


async def test_get_index_links_stylesheet():
    """GET / response body must contain a link to /static/style.css."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert '/static/style.css' in body, "Missing /static/style.css link in index.html"


async def test_static_css_served():
    """GET /static/style.css must return 200 with content-type text/css and contain --bg-dominant."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/static/style.css")

    assert resp.status_code == 200, f"Expected 200; got {resp.status_code}"
    assert "text/css" in resp.headers.get("content-type", ""), \
        f"Expected text/css; got {resp.headers.get('content-type')}"
    assert "--bg-dominant" in resp.text, "Missing --bg-dominant CSS custom property"


async def test_index_no_unsafe_html():
    """GET / response body must NOT contain '| safe' or 'innerHTML =' (XSS hygiene T-03-02)."""
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")

    body = resp.text
    assert "| safe" not in body, "Found '| safe' Jinja2 escape bypass in index.html"
    assert "innerHTML =" not in body, "Found 'innerHTML =' in index.html (XSS risk)"
