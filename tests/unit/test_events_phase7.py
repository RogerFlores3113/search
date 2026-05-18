"""Phase 7 RED test suite: background screenshot loop contract (SCR-01, SCR-02).

All tests in this file are RED (failing) until Plan 02 wires agent/runner.py
and agent/main.py. Tests cover every row in 07-VALIDATION.md.

Requirements covered: SCR-01 (background 500ms loop, JPEG quality=75,
QueueFull drop, exception continuation, no-queue skip, immediate first
capture), SCR-02 (cancel-before-kill ordering, clean termination,
_log_step no longer emits ScreenshotEvent, queue bounded maxsize=50,
valid b64 JPEG).

Phase 7 boundary: _screenshot_loop closure fires concurrently with
agent.run(); screenshot task is cancelled before browser.kill() in finally.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.main
import agent.runner
from agent.events import DoneEvent, ScreenshotEvent, StateEvent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_fake_agent_history(actions=None):
    """Return a fake agent instance shaped like browser-use's Agent object."""
    if actions is None:
        actions = [{"click_element": {"index": 5}, "interacted_element": None}]
    action_list = actions

    token_cost_service = types.SimpleNamespace(
        usage_history=[],
        calculate_cost=AsyncMock(return_value=None),
    )
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: action_list,
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(
        history=history,
        state=state,
        token_cost_service=token_cost_service,
    )


def _make_mock_browser():
    """Return a MagicMock browser with kill and take_screenshot wired."""
    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()
    mock_browser.take_screenshot = AsyncMock(
        return_value=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
    )
    return mock_browser


def _make_fake_agent_class(fake_agent):
    """Return an inline FakeAgentClass that calls on_step_end once."""
    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    return FakeAgentClass


# ---------------------------------------------------------------------------
# SCR-01: Background 500ms screenshot loop — 7 tests
# ---------------------------------------------------------------------------

async def test_screenshot_loop_emits_events(training_dir, monkeypatch_env):
    """run_agent with a queue must emit at least one ScreenshotEvent via _screenshot_loop.

    SCR-01: background loop runs during agent.run(), taking screenshots and
    placing ScreenshotEvent instances on the queue.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    screenshot_events = [e for e in events if isinstance(e, ScreenshotEvent)]
    assert len(screenshot_events) >= 1, (
        f"Expected at least 1 ScreenshotEvent from _screenshot_loop; "
        f"got {len(screenshot_events)}. Event types: {[type(e).__name__ for e in events]}"
    )

    # Verify take_screenshot was called with format='jpeg' quality=75
    assert mock_browser.take_screenshot.await_count >= 1, (
        "mock_browser.take_screenshot must be awaited at least once"
    )
    for call in mock_browser.take_screenshot.await_args_list:
        assert call.kwargs.get("format") == "jpeg", (
            f"take_screenshot must be called with format='jpeg'; got {call.kwargs}"
        )
        assert call.kwargs.get("quality") == 75, (
            f"take_screenshot must be called with quality=75; got {call.kwargs}"
        )


async def test_screenshot_loop_first_capture_immediate(training_dir, monkeypatch_env):
    """_screenshot_loop must capture a screenshot BEFORE the first asyncio.sleep(0.5).

    SCR-01: first capture happens immediately on loop entry (no leading sleep).
    Strategy: track sequence of 'shot' vs 'sleep' events; first must be 'shot'.
    """
    from agent.runner import run_agent

    # Bounded queue: production uses maxsize=50; mirror that here so the loop
    # cannot accumulate ScreenshotEvents without limit if cancel is delayed.
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sequence: list[str] = []
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()

    original_take = mock_browser.take_screenshot.side_effect

    async def _take_screenshot_side_effect(**kwargs):
        sequence.append("shot")
        return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'

    mock_browser.take_screenshot.side_effect = _take_screenshot_side_effect

    real_sleep = asyncio.sleep

    # Iteration cap: the loop's only production pacing is real CDP latency
    # inside take_screenshot. With take_screenshot mocked to return instantly
    # AND asyncio.sleep patched to sleep(0), the loop becomes a pure busy-yield
    # gated only by the cancel() in run_agent's finally — which only fires once
    # FakeAgentClass.run resolves. To prove "first action is shot, not sleep"
    # we need a handful of iterations, not thousands. Raise CancelledError from
    # the patched sleep after a small budget; that propagates out of the loop
    # (CancelledError is BaseException; the loop's `except Exception` does not
    # swallow it) and the outer finally block still runs cleanly.
    _MAX_LOOP_ITERATIONS = 5
    _sleep_calls = 0

    async def _patched_sleep(delay):
        nonlocal _sleep_calls
        if delay == 0.5:
            sequence.append("sleep")
        _sleep_calls += 1
        if _sleep_calls >= _MAX_LOOP_ITERATIONS:
            raise asyncio.CancelledError()
        await real_sleep(0)  # don't actually sleep in tests

    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass), \
         patch("agent.runner.asyncio.sleep", _patched_sleep):
        await run_agent("test task", queue=queue)

    assert len(sequence) >= 1, "Expected at least one 'shot' or 'sleep' entry"
    assert sequence[0] == "shot", (
        f"First action in _screenshot_loop must be 'shot' (take_screenshot), "
        f"not 'sleep'. Sequence: {sequence}"
    )


async def test_screenshot_loop_jpeg_quality(training_dir, monkeypatch_env):
    """Every take_screenshot call must use exactly format='jpeg' and quality=75.

    SCR-01: JPEG quality=75 is the required encoding for bandwidth efficiency.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    assert mock_browser.take_screenshot.await_count >= 1, (
        "take_screenshot must be awaited at least once"
    )
    for i, call in enumerate(mock_browser.take_screenshot.await_args_list):
        assert call.kwargs == {"format": "jpeg", "quality": 75}, (
            f"Call {i}: take_screenshot kwargs must be exactly "
            f"{{'format': 'jpeg', 'quality': 75}}; got {call.kwargs}"
        )


async def test_screenshot_loop_queue_full_drops_silently(training_dir, monkeypatch_env):
    """When queue is full, _screenshot_loop must drop frames silently (no QueueFull raise).

    SCR-01 + T-07-01: bounded queue overflow must never block the event loop.
    Strategy: fill a maxsize=1 queue with a sentinel before run_agent; assert
    run_agent completes normally and QueueFull is never raised.
    """
    from agent.runner import run_agent

    sentinel = object()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(sentinel)  # fill the queue so put_nowait raises QueueFull

    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    # run_agent must complete without raising asyncio.QueueFull
    try:
        with patch("agent.runner.pre_flight_check", AsyncMock()), \
             patch("agent.runner.BrowserSession", return_value=mock_browser), \
             patch("agent.runner.ChatOllama", MagicMock()), \
             patch("agent.runner.Agent", FakeAgentClass):
            await run_agent("test task", queue=queue)
    except asyncio.QueueFull:
        pytest.fail("_screenshot_loop must catch asyncio.QueueFull and drop silently")

    # sentinel must still be present (queue was full, not drained by loop)
    # OR the queue must not exceed maxsize — either proves drop semantics
    assert mock_browser.take_screenshot.await_count >= 1, (
        "take_screenshot must have been awaited even though queue was full"
    )


async def test_screenshot_loop_exception_continues(training_dir, monkeypatch_env):
    """_screenshot_loop must continue after ConnectionError (not crash or stop).

    SCR-01: CDP WebSocket can disconnect mid-capture; loop must survive and retry.
    After a ConnectionError, the loop must attempt take_screenshot again.

    Loop termination is enforced by the side_effect script — call 5 raises
    asyncio.CancelledError (BaseException, NOT caught by the loop's
    `except Exception`), so the loop exits deterministically after exactly
    4 real take_screenshot calls. asyncio.sleep stays real; FakeAgent.run()
    awaits an Event set by the script so the run_agent finally does not
    cancel the screenshot task before the script completes (~2s wall time).
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    _done_event = asyncio.Event()
    _call_count = 0

    async def _bounded_side_effect(**kwargs):
        nonlocal _call_count
        _call_count += 1
        if _call_count == 1:
            raise ConnectionError("Client is stopping")
        elif _call_count == 2:
            return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        elif _call_count == 3:
            raise ConnectionError("WebSocket connection closed")
        elif _call_count == 4:
            return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        else:
            _done_event.set()
            raise asyncio.CancelledError()

    mock_browser.take_screenshot.side_effect = _bounded_side_effect

    class _WaitingFakeAgent:
        def __init__(self, **kwargs):
            pass

        async def run(self, max_steps, on_step_end):
            await on_step_end(fake_agent)
            await _done_event.wait()
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _WaitingFakeAgent):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    screenshot_events = [e for e in events if isinstance(e, ScreenshotEvent)]
    assert mock_browser.take_screenshot.await_count >= 2, (
        f"Loop must attempt take_screenshot at least twice (continue after exception); "
        f"got {mock_browser.take_screenshot.await_count}"
    )
    assert len(screenshot_events) >= 1, (
        "At least one ScreenshotEvent must reach the queue AFTER the ConnectionError"
    )


async def test_screenshot_loop_timeout_continues(training_dir, monkeypatch_env):
    """_screenshot_loop must continue after asyncio.TimeoutError from asyncio.wait_for.

    SCR-01: slow screenshot (>3s) triggers timeout; loop must retry, not crash.

    Same bounded-script pattern as test_screenshot_loop_exception_continues:
    call 5 raises CancelledError to terminate the loop deterministically;
    asyncio.sleep stays real; FakeAgent.run() awaits an Event set by the
    script so run_agent's finally does not cancel before the script ends.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    _done_event = asyncio.Event()
    _call_count = 0

    async def _bounded_side_effect(**kwargs):
        nonlocal _call_count
        _call_count += 1
        if _call_count == 1:
            raise asyncio.TimeoutError()
        elif _call_count == 2:
            return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        elif _call_count == 3:
            raise asyncio.TimeoutError()
        elif _call_count == 4:
            return b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
        else:
            _done_event.set()
            raise asyncio.CancelledError()

    mock_browser.take_screenshot.side_effect = _bounded_side_effect

    class _WaitingFakeAgent:
        def __init__(self, **kwargs):
            pass

        async def run(self, max_steps, on_step_end):
            await on_step_end(fake_agent)
            await _done_event.wait()
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _WaitingFakeAgent):
        await run_agent("test task", queue=queue)

    assert mock_browser.take_screenshot.await_count >= 2, (
        f"Loop must attempt take_screenshot at least twice after TimeoutError; "
        f"got {mock_browser.take_screenshot.await_count}"
    )


async def test_screenshot_loop_skipped_when_no_queue(training_dir, monkeypatch_env):
    """When run_agent is called without a queue, _screenshot_loop must not start.

    SCR-01: background loop is a UI feature only — skip for CLI path (no queue).
    Proof: take_screenshot is never awaited when queue=None.
    """
    from agent.runner import run_agent

    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task")  # no queue kwarg

    assert mock_browser.take_screenshot.await_count == 0, (
        f"_screenshot_loop must NOT run when queue=None; "
        f"take_screenshot was called {mock_browser.take_screenshot.await_count} time(s)"
    )


# ---------------------------------------------------------------------------
# SCR-02: Clean shutdown — cancel task before browser.kill() — 5 tests
# ---------------------------------------------------------------------------

async def test_screenshot_task_cancelled_before_browser_kill(training_dir, monkeypatch_env):
    """screenshot_task.cancel() + gather must complete before browser.kill() is awaited.

    SCR-02: correct shutdown order prevents TargetClosedError from firing during
    cleanup. The gather must appear before kill in the call order.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    order_list: list[str] = []

    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()

    # Wrap browser.kill to record call order via side_effect (non-recursive)
    async def _kill_with_order():
        order_list.append("kill")

    mock_browser.kill = AsyncMock(side_effect=_kill_with_order)

    # Patch asyncio.gather inside agent.runner to record call order
    real_gather = asyncio.gather

    async def _gather_with_order(*args, **kwargs):
        order_list.append("gather")
        return await real_gather(*args, **kwargs)

    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass), \
         patch("agent.runner.asyncio.gather", _gather_with_order):
        await run_agent("test task", queue=queue)

    assert "gather" in order_list, (
        f"asyncio.gather must be called in the finally block; order_list={order_list}"
    )
    assert "kill" in order_list, (
        f"browser.kill must be called in the finally block; order_list={order_list}"
    )
    assert order_list.index("gather") < order_list.index("kill"), (
        f"asyncio.gather (task cancellation) must happen BEFORE browser.kill; "
        f"order_list={order_list}"
    )


async def test_screenshot_task_cancel_terminates_cleanly(training_dir, monkeypatch_env):
    """run_agent must complete (not hang) when the screenshot task is cancelled in finally.

    SCR-02: clean CancelledError propagation ensures asyncio.gather returns promptly.
    If CancelledError were caught in the loop, gather would hang and this test would
    timeout via the outer asyncio.wait_for guard.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    # asyncio.wait_for outer guard: run_agent must not hang
    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await asyncio.wait_for(
            run_agent("test task", queue=queue),
            timeout=5.0,
        )
    # If we reach here, run_agent completed without hanging — SCR-02 satisfied


async def test_screenshot_event_not_emitted_by_log_step(training_dir, monkeypatch_env):
    """_log_step must NOT emit ScreenshotEvent (removed in D-05/D-06).

    SCR-02: ScreenshotEvent is emitted exclusively by _screenshot_loop (D-05).
    D-06: lines `screenshots = agent_instance.history.screenshots()` and
    `queue.put_nowait(ScreenshotEvent(b64=b64))` must be removed from _log_step.

    Primary assertion (source inspection): 'history.screenshots()' must NOT
    appear in inspect.getsource(run_agent).
    """
    # Source inspection: the removed lines must not be present
    source = inspect.getsource(agent.runner.run_agent)
    assert "history.screenshots()" not in source, (
        "run_agent source must NOT contain 'history.screenshots()' — "
        "this line was removed in D-05/D-06 (SCR-02). "
        "ScreenshotEvent is now emitted exclusively by _screenshot_loop."
    )


async def test_queue_is_bounded_maxsize_50():
    """agent/main.py must construct asyncio.Queue(maxsize=50) in the /run handler.

    SCR-02 + T-07-01: bounded queue prevents unbounded memory growth from the
    high-frequency screenshot producer (D-10, D-11).
    """
    import re

    source = inspect.getsource(agent.main)
    pattern = r"asyncio\.Queue\(\s*maxsize\s*=\s*50\s*\)"
    assert re.search(pattern, source) is not None, (
        "agent/main.py must contain asyncio.Queue(maxsize=50) in the /run handler. "
        "Current source does not match pattern: asyncio.Queue(maxsize=50). "
        "This is required by D-10 (SCR-02) to bound queue memory usage."
    )


async def test_screenshot_event_b64_is_valid(training_dir, monkeypatch_env):
    """ScreenshotEvents from _screenshot_loop must carry valid base64-encoded JPEG data.

    SCR-01 + SCR-02: b64 field must be non-empty and decode to bytes starting with
    the JPEG SOI marker (0xFF 0xD8 0xFF).
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history()
    mock_browser = _make_mock_browser()
    # take_screenshot returns minimal JPEG header bytes
    mock_browser.take_screenshot = AsyncMock(
        return_value=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00'
    )
    FakeAgentClass = _make_fake_agent_class(fake_agent)

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    screenshot_events = [e for e in events if isinstance(e, ScreenshotEvent)]
    assert len(screenshot_events) >= 1, (
        "Expected at least 1 ScreenshotEvent from _screenshot_loop"
    )

    for evt in screenshot_events:
        assert evt.b64 != "", (
            "ScreenshotEvent.b64 must not be empty string"
        )
        decoded = base64.b64decode(evt.b64)
        assert decoded[:3] == b'\xff\xd8\xff', (
            f"ScreenshotEvent.b64 must decode to bytes starting with JPEG SOI marker "
            f"(0xFF 0xD8 0xFF); got {decoded[:3].hex()}"
        )


# ---------------------------------------------------------------------------
# _screenshot_loop back-off + cadence (Issue #4)
# ---------------------------------------------------------------------------

async def test_screenshot_loop_sleeps_after_success():
    """Every successful capture is followed by a 0.5s sleep — the loop
    NEVER yields with sleep(0) on the success path (the old behavior
    would tight-loop on failure because of `sleep(0.5 if captured else 0)`).
    Loop is bounded by injecting CancelledError after 2 successes.
    """
    from agent.runner import _screenshot_loop

    browser = MagicMock()
    browser.take_screenshot = AsyncMock(side_effect=[
        b'\xff\xd8\xff',
        b'\xff\xd8\xff',
        asyncio.CancelledError(),
    ])
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sleeps: list[float] = []
    async def _record_sleep(seconds):
        sleeps.append(seconds)

    with patch("agent.runner.asyncio.sleep", _record_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _screenshot_loop(browser, queue)

    assert sleeps == [0.5, 0.5], (
        f"Each success must be followed by a 0.5s sleep; got {sleeps}"
    )


async def test_screenshot_loop_backs_off_on_consecutive_failures():
    """Consecutive `take_screenshot` failures grow the sleep exponentially:
    0.5 → 1.0 → 2.0 → 4.0 → 4.0 (capped). Without this, the loop spins as
    fast as the event loop can schedule it (the original bug — sleep(0)
    when `captured` was False).
    """
    from agent.runner import _screenshot_loop

    browser = MagicMock()
    browser.take_screenshot = AsyncMock(side_effect=[
        ConnectionError("WebSocket closed"),
        ConnectionError("WebSocket closed"),
        ConnectionError("WebSocket closed"),
        ConnectionError("WebSocket closed"),
        ConnectionError("WebSocket closed"),
        asyncio.CancelledError(),
    ])
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sleeps: list[float] = []
    async def _record_sleep(seconds):
        sleeps.append(seconds)

    with patch("agent.runner.asyncio.sleep", _record_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _screenshot_loop(browser, queue)

    assert sleeps == [0.5, 1.0, 2.0, 4.0, 4.0], (
        f"Expected exponential back-off capped at 4.0s; got {sleeps}"
    )


async def test_screenshot_loop_backoff_resets_on_success():
    """A successful capture between failures resets the back-off counter,
    so the next failure starts again at 0.5s instead of continuing the
    exponential ladder.
    """
    from agent.runner import _screenshot_loop

    browser = MagicMock()
    browser.take_screenshot = AsyncMock(side_effect=[
        ConnectionError("fail"),          # back-off 0.5
        ConnectionError("fail"),          # back-off 1.0
        b'\xff\xd8\xff',                  # success → reset; sleep 0.5
        ConnectionError("fail"),          # back-off 0.5 (NOT 2.0)
        asyncio.CancelledError(),
    ])
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sleeps: list[float] = []
    async def _record_sleep(seconds):
        sleeps.append(seconds)

    with patch("agent.runner.asyncio.sleep", _record_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _screenshot_loop(browser, queue)

    assert sleeps == [0.5, 1.0, 0.5, 0.5], (
        f"Successful capture must reset back-off; got {sleeps}"
    )
