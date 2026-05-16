from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ScreenshotEvent:
    type: Literal["screenshot"] = "screenshot"
    b64: str = ""


@dataclass
class NarrationEvent:
    type: Literal["narration"] = "narration"
    step: int = 0
    text: str = ""
    timestamp: str = ""


@dataclass
class StateEvent:
    type: Literal["state"] = "state"
    state: str = "idle"  # idle | running | paused | complete | error


@dataclass
class ProgressEvent:
    type: Literal["progress"] = "progress"
    step: int = 0
    max_steps: int = 25


@dataclass
class SummaryEvent:
    type: Literal["summary"] = "summary"
    text: str = ""


@dataclass
class ErrorEvent:
    type: Literal["error_msg"] = "error_msg"
    message: str = ""


@dataclass
class DoneEvent:
    type: Literal["done"] = "done"
