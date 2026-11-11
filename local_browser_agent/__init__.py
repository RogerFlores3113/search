"""local_browser_agent: an importable browser-agent library (browser-use based).

Importing this package reads no configuration, touches no disk and uses no network, and
installs no logging handlers on the root logger (see ``BROWSER_USE_SETUP_LOGGING`` below).
"""
import os
from importlib import metadata as _metadata

# Must run before anything imports browser_use. An inherited ANONYMIZED_TELEMETRY=true is
# overridden; opt in explicitly with LBA_ALLOW_TELEMETRY=1.
if os.environ.get("LBA_ALLOW_TELEMETRY") != "1":
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    # Cloud sync sends run data to browser-use's cloud; forced off (not setdefault).
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
    # Keep litellm from fetching its model-cost map from GitHub at import time.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
else:
    os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
# browser-use's package import otherwise replaces the root logger's handlers with a
# StderrHandler(INFO). Skip that unless the user chose a value. With setup disabled,
# BROWSER_USE_LOGGING_LEVEL has no effect; the CLI / MCP entry points call
# log.configure_logging(), which installs its own stderr handler on the browser_use loggers and
# sets their level directly.
os.environ.setdefault("BROWSER_USE_SETUP_LOGGING", "false")

import logging as _logging  # noqa: E402

# Library etiquette: never trigger logging.lastResort for an application that configured nothing.
_logging.getLogger("local_browser_agent").addHandler(_logging.NullHandler())

from local_browser_agent.log import install_quiet_filters as _install_quiet_filters  # noqa: E402

_install_quiet_filters()  # drop browser-use's duplicate failure noise whatever handlers the host uses

try:
    __version__ = _metadata.version("local-browser-agent")
except _metadata.PackageNotFoundError:  # pragma: no cover - running from a bare checkout
    __version__ = "0.0.0+unknown"

from local_browser_agent.chrome import ChromeNotFoundError  # noqa: E402
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
from local_browser_agent.log import configure_logging  # noqa: E402
from local_browser_agent.sinks import CallbackSink, JsonlTraceSink, QueueSink  # noqa: E402

__all__ = [
    "__version__",
    "AgentConfig", "ModelConfig", "BrowserConfig", "SafetyPolicy",
    "BrowserAgent", "RunResult", "StepRecord", "run_task", "run_task_sync",
    "register_provider", "build_llm", "default_model", "check_provider", "PreFlightError", "ChromeNotFoundError",
    "SAFETY_DEFAULTS", "GUARDRAIL_PROMPT", "ActionRequest", "GuardedTools", "is_commerce_label",
    "QueueSink", "JsonlTraceSink", "CallbackSink", "configure_logging",
    "ScreenshotEvent", "StateEvent", "ProgressEvent", "SummaryEvent", "ErrorEvent", "DoneEvent",
    "TokenEvent", "ModelInfoEvent", "ThoughtEvent", "ActionDetailEvent",
    "HumanNeededEvent", "StepCompletedEvent",
]
