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
_active_queue: Optional[asyncio.Queue] = None   # per-run SSE queue
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
    global _active_task, _active_queue
    if _active_task is not None and not _active_task.done():
        return JSONResponse({"status": "busy"}, status_code=409)
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _active_queue = queue
    _active_task = asyncio.create_task(run_agent(task, queue=queue))
    return JSONResponse({"status": "started"}, headers={"HX-Trigger": "streamStarted"})


@app.post("/pause")
async def pause_endpoint():
    """Toggle pause/resume on the active agent.

    If no agent is running, returns HTTP 400 with {"status": "no_active_run"}.
    If agent.state.paused is True, calls agent.resume() (sync — RESEARCH Pattern 5).
    Otherwise, calls agent.pause() (sync).
    Emits StateEvent("paused" or "running") to _active_queue.
    """
    global _active_agent, _active_queue
    if _active_agent is None:
        return JSONResponse({"status": "no_active_run"}, status_code=400)
    if _active_agent.state.paused:
        _active_agent.resume()
        if _active_queue is not None:
            _active_queue.put_nowait(StateEvent(state="running"))
        return JSONResponse({"status": "resumed"})
    else:
        _active_agent.pause()
        if _active_queue is not None:
            _active_queue.put_nowait(StateEvent(state="paused"))
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


def _aggregate_run_metrics(run_ids: set[str]) -> dict[str, dict]:
    """Aggregate per-run metrics from training/runs.jsonl (D-17, PERF-03).

    Reads the JSONL file line-by-line. For each record whose `run_id` is in
    `run_ids`, accumulates:
      - step_count: incremented by 1 per record
      - total_duration_s: sum of step_duration_ms, divided by 1000 at the end
      - total_cost_usd: None if any matching record has cost_usd is None AND
        provider == 'ollama'; otherwise sum of non-null cost_usd values
      - model_name: last seen non-null
      - provider:   last seen non-null

    Returns {} if TRAINING_FILE does not exist.

    Pure file I/O — safe to invoke from a worker thread via asyncio.to_thread
    (Pitfall 3 — never block the event loop on JSONL reads).
    """
    # Resolve TRAINING_FILE lazily so test monkeypatches on agent.runner take effect.
    from agent import runner as runner_mod
    path = runner_mod.TRAINING_FILE
    if not path.exists():
        return {}

    metrics: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = record.get("run_id")
            if rid not in run_ids:
                continue
            m = metrics.setdefault(rid, {
                "step_count": 0,
                "_duration_ms": 0,
                "total_cost_usd": 0.0,
                "_ollama_null_cost": False,
                "model_name": None,
                "provider": None,
            })
            m["step_count"] += 1
            duration_ms = record.get("step_duration_ms") or 0
            m["_duration_ms"] += int(duration_ms)
            cost = record.get("cost_usd")
            provider = record.get("provider")
            if cost is None and (provider or "").lower() == "ollama":
                m["_ollama_null_cost"] = True
            elif cost is not None:
                m["total_cost_usd"] += float(cost)
            if provider is not None:
                m["provider"] = provider
            model = record.get("model_name")
            if model is not None:
                m["model_name"] = model

    # Finalise: convert duration ms→s int, gate cost on Ollama null semantics.
    out: dict[str, dict] = {}
    for rid, m in metrics.items():
        total_cost = None if m["_ollama_null_cost"] else m["total_cost_usd"]
        out[rid] = {
            "step_count": m["step_count"],
            "total_duration_s": m["_duration_ms"] // 1000,
            "total_cost_usd": total_cost,
            "model_name": m["model_name"],
            "provider": m["provider"],
        }
    return out


@app.get("/runs")
async def runs_endpoint(request: Request):
    """Return the last 10 run records as an HTML fragment.

    Enriches each DB row with JSONL-derived metrics (step_count,
    total_duration_s, total_cost_usd, model_name, provider) via the
    `_aggregate_run_metrics` helper. The aggregator runs in a worker thread
    (D-17, Pitfall 3) so the event loop is not blocked on file I/O.

    Renders templates/runs_fragment.html with the enriched run records.
    """
    runs = await history_db.list_runs(limit=10)
    run_ids = {r["run_id"] for r in runs}
    metrics = await asyncio.to_thread(_aggregate_run_metrics, run_ids)
    defaults = {
        "step_count": 0,
        "total_duration_s": 0,
        "total_cost_usd": None,
        "model_name": None,
        "provider": None,
    }
    for r in runs:
        r.update(metrics.get(r["run_id"], defaults))
    return templates.TemplateResponse(
        request=request, name="runs_fragment.html", context={"runs": runs}
    )


@app.get("/stream", response_class=EventSourceResponse)
async def stream_events() -> AsyncIterable[ServerSentEvent]:
    """SSE endpoint that drains the active run queue until DoneEvent is received.

    If no run is active, yields a single state:idle event and closes.
    Each non-Done event is JSON-serialised via dataclasses.asdict() and sent with
    the event's `type` field as the SSE event name (state, narration, etc.).
    DoneEvent is sent with event="done" and empty data, then the generator returns,
    which closes the SSE connection.

    The local `queue` variable captures _active_queue at connection time so a new
    run starting after the SSE connects does not cross-wire events (T-03-06).
    """
    global _active_queue
    if _active_queue is None:
        yield ServerSentEvent(raw_data='{"state":"idle"}', event="state")
        yield ServerSentEvent(raw_data="", event="done")
        return
    queue = _active_queue
    while True:
        event = await queue.get()
        if isinstance(event, DoneEvent):
            yield ServerSentEvent(raw_data="", event="done")
            break
        yield ServerSentEvent(
            raw_data=json.dumps(dataclasses.asdict(event)),
            event=event.type,
        )
