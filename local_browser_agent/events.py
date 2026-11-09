from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class ScreenshotEvent:
    type: Literal["screenshot"] = "screenshot"
    b64: str = ""


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
    step_duration_ms: Optional[int] = None


@dataclass
class HumanNeededEvent:
    """The run needs a person (CAPTCHA / human-verification page). Never auto-solved."""

    type: Literal["human_needed"] = "human_needed"
    reason: str = "captcha"
    url: Optional[str] = None
    message: str = ""


@dataclass
class StepCompletedEvent:
    """Everything known about one finished step (for trace/training sinks).

    Only delivered to sinks that set ``wants_step_events = True``; it carries the
    step screenshot, so the built-in queue/trace sinks do not receive it.
    ``step`` is 1-indexed. ``run_has_errors`` is cumulative over the run;
    ``error`` is this step's own error (None when the step was clean).
    """

    type: Literal["step_completed"] = "step_completed"
    run_id: str = ""
    step: int = 0
    screenshot_b64: str = ""
    action_type: str = "unknown"
    target: Optional[str] = None
    target_label: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    thinking: Optional[str] = None
    evaluation_previous_goal: Optional[str] = None
    next_goal: Optional[str] = None
    memory: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    run_has_errors: bool = False


__all__ = [
    "HumanNeededEvent",
    "StepCompletedEvent",
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
