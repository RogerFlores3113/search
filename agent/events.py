from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


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
    step_duration_ms: int = 0


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


@dataclass
class TokenEvent:
    type: Literal["token"] = "token"
    step: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None


@dataclass
class ModelInfoEvent:
    type: Literal["model_info"] = "model_info"
    provider: str = ""
    model_name: str = ""


@dataclass
class ThoughtEvent:
    type: Literal["thought"] = "thought"
    step: int = 0
    thinking: Optional[str] = None
    evaluation_previous_goal: Optional[str] = None
    next_goal: Optional[str] = None
    memory: Optional[str] = None


@dataclass
class ActionDetailEvent:
    type: Literal["action_detail"] = "action_detail"
    step: int = 0
    action_type: str = "unknown"
    target: Optional[str] = None
    target_label: Optional[str] = None  # human-readable element label (ax_name / aria-label / tag)
    value: Optional[str] = None
    url: Optional[str] = None
    success: Optional[bool] = None
