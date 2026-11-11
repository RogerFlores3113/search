"""Event sinks: async callables taking an event dataclass.

A sink that raises never crashes a run (the runner swallows and logs the error).
Sinks may set ``wants_screenshots = False`` to opt out of the screenshot loop.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
import uuid
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from local_browser_agent.events import ScreenshotEvent

logger = logging.getLogger("local_browser_agent")

EventSink = Callable[[Any], Awaitable[None]]

# Lifecycle events the consumer cannot recover from if dropped.
CONTROL_EVENT_TYPES = frozenset({"state", "model_info", "summary", "error_msg", "done", "human_needed"})
_CONTROL_PUT_TIMEOUT_S = 2.0


class QueueSink:
    """Pushes events onto asyncio queues.

    Data events (screenshots, per-step thought/action/token/progress) use a lossy
    ``put_nowait``. Lifecycle events block up to 2s so a ``done`` is never dropped.
    When ``control_q`` is None everything goes to ``data_q``.
    """

    wants_screenshots = True
    wants_step_events = False

    def __init__(self, data_q: asyncio.Queue, control_q: asyncio.Queue | None = None) -> None:
        self.data_q = data_q
        self.control_q = control_q

    async def __call__(self, event: Any) -> None:
        if getattr(event, "type", None) in CONTROL_EVENT_TYPES:
            q = self.control_q if self.control_q is not None else self.data_q
            try:
                await asyncio.wait_for(q.put(event), timeout=_CONTROL_PUT_TIMEOUT_S)
            except asyncio.TimeoutError:
                pass
        else:
            try:
                self.data_q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class JsonlTraceSink:
    """Appends one JSON object per event to ``path`` (screenshots dropped by default).

    The file is opened in append mode: an existing file is never truncated, so
    traces from several runs can share a file (tell them apart by ``run_id``).
    Every record carries ``ts`` (ISO 8601, UTC) and ``run_id`` (a uuid4 generated
    per sink instance, i.e. per CLI run). A StepCompletedEvent's own run_id, when
    different, is kept as ``agent_run_id``.
    """

    def __init__(self, path: str | Path, include_screenshots: bool = False) -> None:
        self.path = Path(path)
        self.run_id = str(uuid.uuid4())
        self.events_written = 0
        self.include_screenshots = include_screenshots
        self.wants_screenshots = include_screenshots

    def _write(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    async def __call__(self, event: Any) -> None:
        if isinstance(event, ScreenshotEvent) and not self.include_screenshots:
            return
        record = dataclasses.asdict(event) if dataclasses.is_dataclass(event) else {"event": repr(event)}
        record.setdefault("type", type(event).__name__)
        own = record.get("run_id")
        if own and own != self.run_id:
            record["agent_run_id"] = own
        record["run_id"] = self.run_id
        record["ts"] = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(self._write, json.dumps(record, default=str))
        self.events_written += 1


class CallbackSink:
    """Wraps a sync or async function as a sink."""

    wants_screenshots = True

    def __init__(self, fn: Callable[[Any], Any]) -> None:
        self.fn = fn

    async def __call__(self, event: Any) -> None:
        result = self.fn(event)
        if inspect.isawaitable(result):
            await result
