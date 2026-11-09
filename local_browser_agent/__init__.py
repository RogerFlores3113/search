"""local_browser_agent: an importable browser-agent library (browser-use based).

Importing this package reads no configuration, touches no disk and uses no network.
"""
import os

# Must run before anything imports browser_use.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")

__version__ = "0.1.0"

from local_browser_agent.config import AgentConfig, BrowserConfig, ModelConfig, SafetyPolicy  # noqa: E402
from local_browser_agent.events import (  # noqa: E402
    ActionDetailEvent,
    DoneEvent,
    ErrorEvent,
    HumanNeededEvent,
    ModelInfoEvent,
    ProgressEvent,
    ScreenshotEvent,
    StateEvent,
    StepCompletedEvent,
    SummaryEvent,
    ThoughtEvent,
    TokenEvent,
)
from local_browser_agent.models import (  # noqa: E402
    PreFlightError,
    build_llm,
    check_provider,
    default_model,
    register_provider,
)
from local_browser_agent.runner import (  # noqa: E402
    BrowserAgent,
    RunResult,
    StepRecord,
    run_task,
    run_task_sync,
)
from local_browser_agent.safety import (  # noqa: E402
    GUARDRAIL_PROMPT,
    SAFETY_DEFAULTS,
    ActionRequest,
    GuardedTools,
    is_commerce_label,
)
from local_browser_agent.sinks import CallbackSink, JsonlTraceSink, QueueSink  # noqa: E402

__all__ = [
    "__version__",
    "AgentConfig", "ModelConfig", "BrowserConfig", "SafetyPolicy",
    "BrowserAgent", "RunResult", "StepRecord", "run_task", "run_task_sync",
    "register_provider", "build_llm", "default_model", "check_provider", "PreFlightError",
    "SAFETY_DEFAULTS", "GUARDRAIL_PROMPT", "ActionRequest", "GuardedTools", "is_commerce_label",
    "QueueSink", "JsonlTraceSink", "CallbackSink",
    "ScreenshotEvent", "StateEvent", "ProgressEvent", "SummaryEvent", "ErrorEvent", "DoneEvent",
    "TokenEvent", "ModelInfoEvent", "ThoughtEvent", "ActionDetailEvent",
    "HumanNeededEvent", "StepCompletedEvent",
]
