"""Unit tests for the Phase 3 web UI — POST /run, GET /stream, SSE queue bridge.

Wave 0 scaffold: 13 required test stubs (per VALIDATION.md) + dataclass discriminant test.
Tests that require Task 2/3 implementation are marked pytest.fail("RED — implemented in Task 2/3").
Tests deferred to Plan 02 or Plan 03 are marked pytest.skip(reason="Plan 02/03").

All tests are async def without @pytest.mark.asyncio because asyncio_mode = "auto".
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Dataclass event type discriminants (VALIDATION.md 03-W0-01 area; passes in Wave 0)
# ---------------------------------------------------------------------------

def test_event_dataclasses_have_type_discriminant():
    """Each of the 7 event classes must carry the correct type literal field."""
    from agent.events import (
        ScreenshotEvent,
        NarrationEvent,
        StateEvent,
        ProgressEvent,
        SummaryEvent,
        ErrorEvent,
        DoneEvent,
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
# POST /run (LOOP-01) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_post_run_returns_started(monkeypatch):
    """POST /run with task string must return 200 + {"status": "started"} + HX-Trigger header."""
    pytest.fail("RED — implemented in Task 2")


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
# NarrationEvent emission from _log_step (LOOP-09) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_log_step_emits_narration_event(monkeypatch):
    """run_agent's _log_step closure must put NarrationEvent on queue after log_step runs."""
    pytest.fail("RED — implemented in Task 2")


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
# StateEvent emission (UI-04) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_run_agent_emits_state_events(monkeypatch):
    """run_agent must emit StateEvent("running") at start and StateEvent("complete") in finally."""
    pytest.fail("RED — implemented in Task 2")


# ---------------------------------------------------------------------------
# ErrorEvent on PreFlightError (UI-08) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_run_agent_emits_error_event_on_preflight(monkeypatch):
    """When pre_flight_check raises PreFlightError, queue receives ErrorEvent + StateEvent("error") + DoneEvent."""
    pytest.fail("RED — implemented in Task 2")


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
# DoneEvent always emitted (D-11) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_done_event_always_emitted(monkeypatch):
    """DoneEvent must be the last item on the queue for success, PreFlightError, and TimeoutError."""
    pytest.fail("RED — implemented in Task 2")


# ---------------------------------------------------------------------------
# SSE stream yields until DoneEvent (SSE) — implemented in Task 2
# ---------------------------------------------------------------------------

async def test_sse_stream_yields_until_done(monkeypatch):
    """GET /stream must yield state+narration events then close on DoneEvent."""
    pytest.fail("RED — implemented in Task 2")
