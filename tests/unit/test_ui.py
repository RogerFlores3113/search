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
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "navigate", "action_target": "", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    return types.SimpleNamespace(
        history=history,
        state=types.SimpleNamespace(last_result=[]),
    )


# ---------------------------------------------------------------------------
# Dataclass event type discriminants (passes in Wave 0)
# ---------------------------------------------------------------------------

def test_event_dataclasses_have_type_discriminant():
    """Each of the 7 event classes must carry the correct type literal field."""
    from agent.events import (
        ScreenshotEvent, NarrationEvent, StateEvent,
        ProgressEvent, SummaryEvent, ErrorEvent, DoneEvent,
    )
    import dataclasses

    assert dataclasses.is_dataclass(ScreenshotEvent)
    assert dataclasses.is_dataclass(NarrationEvent)
    assert dataclasses.is_dataclass(StateEvent)
    assert dataclasses.is_dataclass(ProgressEvent)
    assert dataclasses.is_dataclass(SummaryEvent)
    assert dataclasses.is_dataclass(ErrorEvent)
    assert dataclasses.is_dataclass(DoneEvent)

    assert ScreenshotEvent().type == "screenshot"
    assert NarrationEvent().type == "narration"
    assert StateEvent().type == "state"
    assert ProgressEvent().type == "progress"
    assert SummaryEvent().type == "summary"
    assert ErrorEvent().type == "error_msg"
    assert DoneEvent().type == "done"


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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/run", json={"task": "test task"})

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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/run", json={"task": "another task"})

    assert resp.status_code == 409
    assert resp.json()["status"] == "busy"


# ---------------------------------------------------------------------------
# POST /pause (LOOP-07) — deferred to Plan 03
# ---------------------------------------------------------------------------

async def test_post_pause_calls_agent_pause(monkeypatch):
    """POST /pause must call agent.pause() when a run is active."""
    pytest.skip(reason="Plan 02/03")


async def test_post_pause_toggles_resume(monkeypatch):
    """POST /pause on a paused agent must call agent.resume() instead."""
    pytest.skip(reason="Plan 02/03")


# ---------------------------------------------------------------------------
# POST /stop (LOOP-08) — deferred to Plan 03
# ---------------------------------------------------------------------------

async def test_post_stop_calls_agent_stop(monkeypatch):
    """POST /stop must call agent.stop() and return {"status": "stopped"}."""
    pytest.skip(reason="Plan 02/03")


# ---------------------------------------------------------------------------
# NarrationEvent emission from _log_step (LOOP-09)
# ---------------------------------------------------------------------------

async def test_log_step_emits_narration_event(monkeypatch):
    """run_agent's _log_step closure must put NarrationEvent on queue after log_step runs."""
    from agent.events import NarrationEvent, StateEvent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent_instance = _make_fake_agent_instance()

    # Patch log_step (the JSONL writer) to be a no-op so test stays unit-level
    monkeypatch.setattr("agent.runner.log_step", AsyncMock())
    # Patch pre_flight_check to raise PreFlightError immediately so we can test
    # NarrationEvent emission independently via _log_step directly
    # Instead, invoke run_agent with a mock that calls on_step_end exactly once
    from agent.runner import PreFlightError
    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.llm_screenshot_size = None

    captured_on_step_end = {}

    async def fake_run(max_steps, on_step_end):
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
    assert "NarrationEvent" in event_types, f"Expected NarrationEvent; got {event_types}"

    narration_events = [e for e in events if isinstance(e, NarrationEvent)]
    assert len(narration_events) >= 1
    assert "navigate" in narration_events[0].text or "Step" in narration_events[0].text


# ---------------------------------------------------------------------------
# SummaryEvent emission (LOOP-10) — deferred to Plan 02
# ---------------------------------------------------------------------------

async def test_run_agent_emits_summary_event(monkeypatch):
    """run_agent must put SummaryEvent(text=final_result) on queue on success."""
    pytest.skip(reason="Plan 02/03")


# ---------------------------------------------------------------------------
# ScreenshotEvent emission (UI-02) — deferred to Plan 02
# ---------------------------------------------------------------------------

async def test_log_step_emits_screenshot_event(monkeypatch):
    """_log_step closure must put ScreenshotEvent(b64=...) on queue after each step."""
    pytest.skip(reason="Plan 02/03")


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
    monkeypatch.setattr("agent.runner.log_step", AsyncMock())

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
# DB insert from runner finally (RUN-01) — deferred to Plan 03
# ---------------------------------------------------------------------------

async def test_run_agent_inserts_run_to_db(monkeypatch):
    """run_agent finally block must call history_db.insert_run with correct args."""
    pytest.skip(reason="Plan 02/03")


# ---------------------------------------------------------------------------
# GET /runs history endpoint (RUN-02) — deferred to Plan 03
# ---------------------------------------------------------------------------

async def test_get_runs_returns_history(monkeypatch):
    """GET /runs must return a list of run records from the database."""
    pytest.skip(reason="Plan 02/03")


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
    monkeypatch.setattr("agent.runner.log_step", AsyncMock())

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

    async def raise_timeout(coro, timeout=None):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("agent.runner.pre_flight_check", AsyncMock())
    monkeypatch.setattr("agent.runner.BrowserSession", MagicMock(return_value=mock_browser2))
    monkeypatch.setattr("agent.runner.BrowserProfile", MagicMock())
    monkeypatch.setattr("agent.runner.Agent", MagicMock(return_value=mock_agent2))
    monkeypatch.setattr("agent.runner.build_llm", MagicMock())
    monkeypatch.setattr("agent.runner.asyncio.wait_for", raise_timeout)

    await run_agent("timeout task", queue=queue3)
    events3 = []
    while not queue3.empty():
        events3.append(queue3.get_nowait())
    assert isinstance(events3[-1], DoneEvent), f"Timeout path: last event should be DoneEvent, got {events3[-1]}"


# ---------------------------------------------------------------------------
# SSE stream yields until DoneEvent (SSE)
# ---------------------------------------------------------------------------

async def test_sse_stream_yields_until_done(monkeypatch):
    """GET /stream must yield state+narration events then close on DoneEvent."""
    import agent.main as main_mod
    from agent.events import StateEvent, NarrationEvent, DoneEvent
    from agent.main import app

    # Pre-populate _active_queue with known events
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(StateEvent(state="running"))
    queue.put_nowait(NarrationEvent(step=1, text="Step 1: navigate"))
    queue.put_nowait(DoneEvent())

    monkeypatch.setattr(main_mod, "_active_queue", queue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/stream")

    body = resp.text
    assert "event: state" in body, f"Expected 'event: state' in SSE body; got:\n{body}"
    assert "event: narration" in body, f"Expected 'event: narration' in SSE body; got:\n{body}"
    assert "event: done" in body, f"Expected 'event: done' in SSE body; got:\n{body}"


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
