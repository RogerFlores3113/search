from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from agent.events import DoneEvent, StateEvent
from agent import db as history_db
from agent.runner import run_agent


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource, works in dev and frozen modes.

    Dev mode:   returns the relative path string unchanged
    Frozen app: returns str(Path(sys._MEIPASS) / relative)

    See: .planning/phases/04-distribution/04-RESEARCH.md Pitfall 5
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / relative)
    # Dev mode: resolve relative to the project root (parent of the agent
    # package) so callers that chdir away (e.g., pytest tmp_path fixtures)
    # still find bundled resources like agent/templates and agent/static.
    project_root = Path(__file__).resolve().parent.parent
    candidate = project_root / relative
    if candidate.exists():
        return str(candidate)
    return relative


templates = Jinja2Templates(directory=_resource_path("agent/templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan hook.

    On startup: initialise the runs DB table, then if app.state.pending_task is
    set, create an asyncio task for run_agent.
    On shutdown: cancel the task if still running.
    """
    await history_db.init_db()

    task_ref: Optional[asyncio.Task] = None
    pending = getattr(app.state, "pending_task", None)
    if pending:
        task_ref = asyncio.create_task(run_agent(pending))

    yield

    if task_ref is not None and not task_ref.done():
        task_ref.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(task_ref, return_exceptions=True), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # task outlived grace period; it will be garbage-collected


app = FastAPI(lifespan=lifespan)

# Default chrome_missing to False; set to True by __main__.py pre-flight check (DIST-02)
app.state.chrome_missing = False

# Mount static files with check_dir=False so startup does not crash when the
# agent/static directory has not yet been created (RESEARCH Anti-Patterns).
app.mount("/static", StaticFiles(directory=_resource_path("agent/static"), check_dir=False), name="static")

_active_task: Optional[asyncio.Task] = None
# Per-run SSE queues. Data queue (bounded, drop-on-overflow) carries
# screenshots and per-step updates; control queue (small, blocking puts)
# carries lifecycle events (state, model_info, summary, error, done) that
# the UI cannot recover from if dropped. `/stream` multiplexes both.
_active_queue: Optional[asyncio.Queue] = None
_active_control_queue: Optional[asyncio.Queue] = None
_active_agent = None                             # Agent ref for pause/stop (Plan 03)


@app.get("/")
async def index(request: Request):
    """Render the HTMX+Alpine UI skeleton, or Chrome-missing page if Chrome not found."""
    if getattr(request.app.state, "chrome_missing", False):
        return templates.TemplateResponse(request=request, name="no_chrome.html", context={})
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.post("/run")
async def run_endpoint(task: str = Form(..., max_length=2000)):
    """Accept a task string and start the agent as a fire-and-forget asyncio task.

    Accepts application/x-www-form-urlencoded (the HTMX default for form submissions).
    task is validated to a maximum of 2000 characters; FastAPI returns HTTP 422 if
    exceeded.

    Returns HTTP 409 if an agent session is already running to prevent multiple
    concurrent BrowserSession instances and interleaved JSONL writes.

    On accept: creates an asyncio.Queue, assigns it to _active_queue, starts the
    run_agent coroutine as an asyncio.Task with the queue wired in, and responds
    with HX-Trigger: streamStarted so the HTMX SSE container activates.
    """
    global _active_task, _active_queue, _active_control_queue
    if _active_task is not None and not _active_task.done():
        return JSONResponse({"status": "busy"}, status_code=409)
    data_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    control_queue: asyncio.Queue = asyncio.Queue(maxsize=16)
    _active_queue = data_queue
    _active_control_queue = control_queue
    _active_task = asyncio.create_task(
        run_agent(task, queue=data_queue, control_queue=control_queue)
    )
    return JSONResponse({"status": "started"}, headers={"HX-Trigger": "streamStarted"})


@app.post("/pause")
async def pause_endpoint():
    """Toggle pause/resume on the active agent.

    If no agent is running, returns HTTP 400 with {"status": "no_active_run"}.
    If agent.state.paused is True, calls agent.resume() (sync — RESEARCH Pattern 5).
    Otherwise, calls agent.pause() (sync).
    Emits StateEvent("paused" or "running") to _active_queue.
    """
    global _active_agent, _active_queue, _active_control_queue
    if _active_agent is None:
        return JSONResponse({"status": "no_active_run"}, status_code=400)
    # State transitions ride on the control queue (lifecycle), falling back
    # to the data queue for back-compat in test paths that wired only one.
    target = _active_control_queue if _active_control_queue is not None else _active_queue
    if _active_agent.state.paused:
        _active_agent.resume()
        if target is not None:
            target.put_nowait(StateEvent(state="running"))
        return JSONResponse({"status": "resumed"})
    else:
        _active_agent.pause()
        if target is not None:
            target.put_nowait(StateEvent(state="paused"))
        return JSONResponse({"status": "paused"})


@app.post("/stop")
async def stop_endpoint():
    """Stop the active agent.

    If no agent is running, returns HTTP 400 with {"status": "no_active_run"}.
    Calls agent.stop() (sync) — the runner finally block handles status="stopped" in DB.
    """
    global _active_agent
    if _active_agent is None:
        return JSONResponse({"status": "no_active_run"}, status_code=400)
    _active_agent.stop()
    return JSONResponse({"status": "stopped"})


@app.get("/runs")
async def runs_endpoint(request: Request):
    """Return the last 10 run records as an HTML fragment.

    All UI-facing aggregates (step_count, total_duration_s, total_cost_usd,
    model_name, provider) are columns on the runs row — computed once by
    `agent.runner.run_agent` when the run finishes. This endpoint is a
    straight SELECT; the LoRA-only `training/runs.jsonl` is not touched.
    """
    runs = await history_db.list_runs(limit=10)
    return templates.TemplateResponse(
        request=request, name="runs_fragment.html", context={"runs": runs}
    )


def _serialize_event(event: object) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=json.dumps(dataclasses.asdict(event)),
        event=event.type,
    )


@app.get("/stream", response_class=EventSourceResponse)
async def stream_events() -> AsyncIterable[ServerSentEvent]:
    """SSE endpoint that drains the active run queues until DoneEvent.

    Two-queue path (production): multiplexes the bounded data queue and the
    control queue via asyncio.wait. When DoneEvent arrives on the control
    queue, drains any remaining items off the data queue (the producers are
    quiesced by then — the screenshot loop is cancelled before run_agent's
    finally emits DoneEvent) and yields them before signaling done. This
    preserves the final frame and tail token updates the user expects to see.

    Single-queue path: back-compat for test code paths that wired one queue
    only — behaves exactly like the original loop.

    Idle path: no active run — yield a state:idle frame and close.

    Local queue refs are captured at connection time so a new run starting
    after the SSE connects does not cross-wire events (T-03-06).
    """
    global _active_queue, _active_control_queue
    if _active_queue is None:
        yield ServerSentEvent(raw_data='{"state":"idle"}', event="state")
        yield ServerSentEvent(raw_data="", event="done")
        return

    data_q = _active_queue
    ctrl_q = _active_control_queue

    if ctrl_q is None or ctrl_q is data_q:
        while True:
            event = await data_q.get()
            if isinstance(event, DoneEvent):
                yield ServerSentEvent(raw_data="", event="done")
                return
            yield _serialize_event(event)

    control_task = asyncio.create_task(ctrl_q.get())
    data_task = asyncio.create_task(data_q.get())
    pending: set[asyncio.Task] = {control_task, data_task}
    try:
        while True:
            completed, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            # Pre-scan: if DoneEvent is among the completed tasks, do NOT
            # re-arm any waiter — re-arming a queue.get() task on a queue
            # that already has items immediately consumes one of those
            # items into the new task's result, and that result is lost
            # when we cancel pending tasks on exit (the race that ate the
            # tail TokenEvent in test_stream_drains_data_queue_before_done).
            done_event_seen = any(
                isinstance(t.result(), DoneEvent) for t in completed
            )
            for task in completed:
                event = task.result()
                if isinstance(event, DoneEvent):
                    continue
                yield _serialize_event(event)
                if done_event_seen:
                    continue
                if task is control_task:
                    control_task = asyncio.create_task(ctrl_q.get())
                    pending.add(control_task)
                else:
                    data_task = asyncio.create_task(data_q.get())
                    pending.add(data_task)
            if done_event_seen:
                while True:
                    try:
                        tail = data_q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    yield _serialize_event(tail)
                yield ServerSentEvent(raw_data="", event="done")
                return
    finally:
        for t in pending:
            t.cancel()
