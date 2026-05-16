from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent.runner import run_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan hook.

    On startup: if app.state.pending_task is set, create an asyncio task for run_agent.
    On shutdown: cancel the task if still running.
    """
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

_active_task: Optional[asyncio.Task] = None


class RunRequest(BaseModel):
    task: str


@app.post("/run")
async def run_endpoint(request: RunRequest):
    """Accept a task string and start the agent as a fire-and-forget asyncio task.

    Returns HTTP 409 if an agent session is already running to prevent multiple
    concurrent BrowserSession instances and interleaved JSONL writes.
    """
    global _active_task
    if _active_task is not None and not _active_task.done():
        return JSONResponse({"status": "busy"}, status_code=409)
    _active_task = asyncio.create_task(run_agent(request.task))
    return {"status": "started"}
