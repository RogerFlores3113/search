"""Web-app runner: a thin wrapper that runs one task through ``local_browser_agent.BrowserAgent``.

The app-specific parts live here: translating ``Settings`` into an ``AgentConfig``, the
pre-flight check, the SSE queue wiring, the training-JSONL sink and the ``history.db`` row.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from pydantic import SecretStr

from local_browser_agent import (
    AgentConfig, BrowserAgent, BrowserConfig, ModelConfig, QueueSink, SafetyPolicy,
)
from local_browser_agent.events import HumanNeededEvent, ModelInfoEvent
from local_browser_agent.models import build_llm as _lib_build_llm
from local_browser_agent.runner import extract_target_label as _extract_target_label  # noqa: F401
from local_browser_agent.safety import GUARDRAIL_PROMPT  # noqa: F401  (re-exported)

from local_browser_agent.app.chrome_detect import chrome_is_installed
from local_browser_agent.app.config import config
from local_browser_agent.app import db as history_db
from local_browser_agent.app import training_sink
from local_browser_agent.app.training_sink import TrainingSink

if TYPE_CHECKING:
    from local_browser_agent.app.config import Settings

logger = logging.getLogger(__name__)


class PreFlightError(RuntimeError):
    """Raised when pre_flight_check detects a fatal configuration issue.

    The message is written for the end user: it is shown verbatim in the UI.
    """


class StoppedBeforeStart(RuntimeError):
    """The user pressed Stop while the pre-flight check was still running."""


CHROME_MISSING_MESSAGE = (
    "Google Chrome was not found on this computer. "
    "Install it from https://www.google.com/chrome/ and then try again."
)


def stop_agent(agent) -> None:
    """Stop ``agent``, including while it is still in pre-flight (no browser-use agent yet)."""
    agent.stop()
    event = getattr(agent, "_app_stop_event", None)
    if event is not None:
        event.set()


def _build_extend_system_message(active_prompt_id: str, prompts: list[dict]) -> str:
    """Build the extend_system_message string for the Agent constructor.

    If active_prompt_id matches an entry in prompts with non-empty content,
    returns user_prompt_content + '\\n\\n' + GUARDRAIL_PROMPT.

    Falls back to GUARDRAIL_PROMPT alone when:
    - active_prompt_id is falsy
    - prompts is empty
    - no entry matches active_prompt_id
    - the matching entry has empty/falsy content

    GUARDRAIL_PROMPT is always the suffix — it cannot be removed or reordered
    via the API (T-12-03 mitigation).
    """
    if active_prompt_id and prompts:
        match = next((p for p in prompts if p.get("id") == active_prompt_id), None)
        if match and match.get("content"):
            return match["content"] + "\n\n" + GUARDRAIL_PROMPT
    return GUARDRAIL_PROMPT


def _prompt_extension(active_prompt_id: str, prompts: list[dict]) -> str | None:
    """The user's selected prompt content, or None. GUARDRAIL_PROMPT is appended by the library."""
    if active_prompt_id and prompts:
        match = next((p for p in prompts if p.get("id") == active_prompt_id), None)
        if match and match.get("content"):
            return match["content"]
    return None


def _model_config(cfg: "Settings") -> ModelConfig:
    """Translate the app's per-provider settings into a library ModelConfig.

    The app's "openai" provider has always gone through ChatLiteLLM, so it maps to the
    library's "litellm" provider (the UI/DB/training label stays "openai").
    """
    provider = cfg.provider.lower()
    if provider == "ollama":
        return ModelConfig(provider="ollama", model=cfg.ollama_model, base_url=cfg.ollama_host)
    if provider == "anthropic":
        return ModelConfig(provider="anthropic", model=cfg.anthropic_model, api_key=cfg.anthropic_api_key)
    if provider == "openai":
        return ModelConfig(provider="litellm", model=cfg.openai_model, api_key=cfg.openai_api_key)
    return ModelConfig(provider=provider)


def build_agent_config(cfg: "Settings", active_prompt_id: str | None = None) -> AgentConfig:
    """AgentConfig for one run, snapshotting everything from the app settings."""
    prompt_id = active_prompt_id if active_prompt_id else cfg.active_prompt_id
    return AgentConfig(
        model=_model_config(cfg),
        browser=BrowserConfig(
            headless=False,
            channel="chrome",
            keep_alive=False,
            window_width=cfg.browser_width,
            window_height=cfg.browser_height,
            llm_screenshot_width=cfg.llm_screenshot_width,
            llm_screenshot_height=cfg.llm_screenshot_height,
        ),
        safety=SafetyPolicy(blocked_domains=list(cfg.user_domains)),
        max_steps=cfg.max_steps,
        timeout_s=cfg.session_timeout,
        system_prompt_extension=_prompt_extension(prompt_id, cfg.prompts),
        on_captcha="pause",
    )


def build_llm(cfg: "Settings"):
    """Construct the LLM object for the app's configured provider (via the library registry)."""
    return _lib_build_llm(_model_config(cfg))


def _resolve_model_name(cfg: "Settings") -> str:
    """Return the configured model name string for the active provider."""
    provider = cfg.provider.lower()
    if provider == "ollama":
        return cfg.ollama_model
    elif provider == "anthropic":
        return cfg.anthropic_model
    elif provider == "openai":
        return cfg.openai_model
    return "unknown"


async def pre_flight_check(cfg: "Settings") -> None:
    """Validate provider availability before launching the browser.

    For Ollama: checks daemon is running and model is pulled.
    For Anthropic: validates API key against the live endpoint.
    For OpenAI: validates API key against the live endpoint.

    Prints actionable error and raises PreFlightError on failure.
    """
    if cfg.provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{cfg.ollama_host}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            message = (
                f"Ollama is not running or unreachable at {cfg.ollama_host}. "
                f"Start it with: ollama serve  -  then pull the model with: ollama pull {cfg.ollama_model}"
            )
            print(
                f"ERROR: Ollama is not running or unreachable.\n"
                f"  Start it with: ollama serve\n"
                f"  Then pull the model: ollama pull {cfg.ollama_model}"
            )
            raise PreFlightError(message)

        # Exact base-name match: split both sides on ":" to avoid substring false positives.
        # e.g. "qwen3-vl" must not match "old-qwen3-vl-7b" or "qwen3" matching "qwen3-vl".
        model_base = cfg.ollama_model.split(":")[0]
        pulled_bases = [m.split(":")[0] for m in models]
        if model_base not in pulled_bases:
            print(
                f"ERROR: Model '{cfg.ollama_model}' is not pulled.\n"
                f"  Pull it with: ollama pull {cfg.ollama_model}"
            )
            raise PreFlightError(
                f"The model '{cfg.ollama_model}' has not been downloaded yet. "
                f"Pull it with: ollama pull {cfg.ollama_model}"
            )

    elif cfg.provider == "anthropic":
        if not cfg.anthropic_api_key:
            print("ERROR: No Anthropic API key is set. Add one in Settings.")
            raise PreFlightError(
                "No Anthropic API key is set. Open Settings (the gear icon), "
                "choose Anthropic and paste your API key."
            )
        import anthropic as _anthropic
        try:
            client = _anthropic.AsyncAnthropic(
                api_key=cfg.anthropic_api_key.get_secret_value()
            )
            await client.models.list()
        except _anthropic.AuthenticationError:
            print("ERROR: Anthropic API key is invalid.")
            raise PreFlightError(
                "The Anthropic API key was rejected as invalid. "
                "Check it in Settings (the gear icon) and try again."
            )
        except _anthropic.APIConnectionError as e:
            print(f"ERROR: Cannot reach Anthropic API: {e}")
            raise PreFlightError(
                "Could not reach the Anthropic API. Check your internet connection and try again."
            )
        except Exception as e:
            print(f"ERROR: Anthropic API check failed: {e}")
            raise PreFlightError(
                f"The Anthropic API check failed ({type(e).__name__}). "
                "Check your connection and API key in Settings, then try again."
            )

    elif cfg.provider == "openai":
        if not cfg.openai_api_key:
            print("ERROR: No OpenAI API key is set. Add one in Settings.")
            raise PreFlightError(
                "No OpenAI API key is set. Open Settings (the gear icon), "
                "choose OpenAI and paste your API key."
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {cfg.openai_api_key.get_secret_value()}"},
                )
                if resp.status_code == 401:
                    print("ERROR: OpenAI API key is invalid.")
                    raise PreFlightError(
                        "The OpenAI API key was rejected as invalid. "
                        "Check it in Settings (the gear icon) and try again."
                    )
                resp.raise_for_status()
        except PreFlightError:
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            print(f"ERROR: Cannot reach OpenAI API: {e}")
            raise PreFlightError(
                "Could not reach the OpenAI API. Check your internet connection and try again."
            )
        except Exception as e:
            print(f"ERROR: OpenAI API check failed: {e}")
            raise PreFlightError(
                f"The OpenAI API check failed ({type(e).__name__}). "
                "Check your connection and API key in Settings, then try again."
            )


class _AppQueueSink(QueueSink):
    """QueueSink that keeps the app's provider label ("openai") on ModelInfoEvent."""

    def __init__(self, data_q, control_q, provider_label: str) -> None:
        super().__init__(data_q, control_q)
        self._label = provider_label

    async def __call__(self, event) -> None:
        if isinstance(event, ModelInfoEvent):
            event = ModelInfoEvent(provider=self._label, model_name=event.model_name)
        await super().__call__(event)


async def _console_sink(event) -> None:
    """Console notice for a human-verification pause (the UI shows the paused state)."""
    if isinstance(event, HumanNeededEvent):
        print(
            "\n[CAPTCHA DETECTED] Agent encountered a CAPTCHA challenge.\n"
            "  The agent is now paused. Solve the CAPTCHA manually in Chrome,\n"
            "  then press Resume in the UI to continue (or Stop to end the run).\n"
        )


_console_sink.wants_screenshots = False  # type: ignore[attr-defined]


async def run_agent(
    task: str,
    queue: asyncio.Queue | None = None,
    control_queue: asyncio.Queue | None = None,
    active_prompt_id: str | None = None,
    on_agent: Callable[[BrowserAgent | None], None] | None = None,
) -> None:
    """Pre-flight, then run ``task`` through ``BrowserAgent`` and record the run.

    Event routing (see ``QueueSink``):
      * ``queue`` carries high-volume data events (screenshots, thought, action,
        progress, token) with drop-on-overflow semantics.
      * ``control_queue`` carries lifecycle events (state, model_info, summary,
        error, done) that MUST deliver; producers block (with timeout) instead of dropping.

    Back-compat: when ``control_queue`` is None, control events fall back to ``queue``.
    ``on_agent`` is called with the live BrowserAgent just before the run and with None
    once it ends, so the web layer can reach pause/resume/stop without this module
    knowing about it.
    """
    ctrl_q = control_queue if control_queue is not None else queue
    started_at = datetime.now(timezone.utc)
    # Snapshot provider/model/prompt_id before any await so mid-run settings
    # changes cannot affect this run.
    snapshot_provider = config.provider
    snapshot_model = _resolve_model_name(config)
    snapshot_prompt_id = active_prompt_id if active_prompt_id else config.active_prompt_id

    cfg = build_agent_config(config, snapshot_prompt_id)
    sinks: list = []
    if queue is not None:
        sinks.append(_AppQueueSink(queue, ctrl_q, snapshot_provider.lower()))
    sinks.append(TrainingSink(snapshot_provider, snapshot_model))
    sinks.append(_console_sink)

    stop_event = asyncio.Event()
    stopped_in_preflight = False

    async def _preflight() -> None:
        nonlocal stopped_in_preflight
        # With an explicit binary or an attach URL we never look for a system Chrome.
        own_browser = bool(cfg.browser.cdp_url or cfg.browser.executable_path)
        if not own_browser and not chrome_is_installed():
            raise PreFlightError(CHROME_MISSING_MESSAGE)
        if stop_event.is_set():
            stopped_in_preflight = True
            raise StoppedBeforeStart("Run stopped before it started.")
        async def _guarded():
            # Run in a task so Stop can interrupt it; hand any exit/exception back to the caller
            # (a SystemExit raised inside a task would otherwise kill the event loop).
            try:
                await pre_flight_check(config)
            except (Exception, SystemExit) as e:  # noqa: BLE001
                return e
            return None

        check = asyncio.ensure_future(_guarded())
        stopper = asyncio.ensure_future(stop_event.wait())
        try:
            await asyncio.wait({check, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if stopper.done():
                stopped_in_preflight = True
                raise StoppedBeforeStart("Run stopped before it started.")
            failure = check.result()
            if failure is not None:
                raise failure
        finally:
            for t in (check, stopper):
                if not t.done():
                    t.cancel()

    browser_agent = BrowserAgent(cfg, sinks=sinks, preflight=_preflight)
    browser_agent._app_stop_event = stop_event  # type: ignore[attr-defined]  # see stop_agent()
    if on_agent is not None:
        on_agent(browser_agent)
    result = None
    try:
        result = await browser_agent.run(task)
    finally:
        if on_agent is not None:
            on_agent(None)

        # Persist run record to history DB. A DB failure must never prevent cleanup.
        run_status = "error"
        error_text: str | None = None
        if result is not None:
            if stopped_in_preflight:
                run_status = "stopped"
            elif result.status in ("error", "timeout"):
                run_status = "error"
            elif result.status == "stopped":
                run_status = "stopped"
            else:
                run_status = "complete"
            if run_status == "error" and result.errors:
                error_text = str(result.errors[-1])[:500]
            if result.status == "timeout":
                print(f"Session timeout reached ({config.session_timeout}s). Stopping.")
            elif result.status != "error" and result.final_result:
                print(f"Done: {result.final_result}")
        try:
            if result is not None:
                step_ms = sum(s.duration_ms or 0 for s in result.steps)
                if result.cost_usd is not None:
                    cost = result.cost_usd
                else:
                    cost = None if snapshot_provider.lower() == "ollama" else 0.0
                summary = None if run_status == "error" else result.final_result
                await history_db.insert_run(
                    run_id=result.run_id,
                    task=task,
                    status=run_status,
                    summary=summary,
                    started_at=started_at.isoformat(),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    step_count=result.step_count,
                    total_duration_s=step_ms // 1000,
                    total_cost_usd=cost,
                    model_name=snapshot_model,
                    provider=snapshot_provider.lower(),
                    prompt_id=snapshot_prompt_id,
                    error=error_text,
                )
        except Exception:
            pass  # DB failure must not surface

        # Back-fill run_success into every JSONL record for this run (D-04 / TRAINING-03).
        if result is not None:
            await training_sink.backfill_run_success(result.run_id, run_status == "complete")
