"""Event dataclasses now live in ``local_browser_agent.events``; re-exported here."""
from __future__ import annotations

from local_browser_agent.events import (  # noqa: F401
    ScreenshotEvent,
    StateEvent,
    ProgressEvent,
    SummaryEvent,
    ErrorEvent,
    DoneEvent,
    TokenEvent,
    ModelInfoEvent,
    ThoughtEvent,
    ActionDetailEvent,
)

__all__ = [
    "ScreenshotEvent",
    "StateEvent",
    "ProgressEvent",
    "SummaryEvent",
    "ErrorEvent",
    "DoneEvent",
    "TokenEvent",
    "ModelInfoEvent",
    "ThoughtEvent",
    "ActionDetailEvent",
]
