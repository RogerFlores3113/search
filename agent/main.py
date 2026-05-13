from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan. Wave 1 will add asyncio.create_task(run_agent(...)) here."""
    yield


app = FastAPI(lifespan=lifespan)


class RunRequest(BaseModel):
    task: str


@app.post("/run")
async def run_endpoint(request: RunRequest):
    """Accept a task and trigger the agent. Stub — Wave 1 will wire run_agent."""
    return {"status": "stub — wave 1 will wire run_agent"}
