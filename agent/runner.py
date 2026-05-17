from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from browser_use import Agent, ChatAnthropic, ChatLiteLLM, ChatOllama
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession

from agent.config import config
from agent.events import (
    ScreenshotEvent, NarrationEvent, StateEvent,
    ProgressEvent, SummaryEvent, ErrorEvent, DoneEvent,
    TokenEvent, ModelInfoEvent,
)
from agent import db as history_db
from agent.paths import get_user_data_dir

if TYPE_CHECKING:
    from agent.config import Settings


class PreFlightError(RuntimeError):
    """Raised when pre_flight_check detects a fatal configuration issue."""

TRAINING_FILE = get_user_data_dir() / "training" / "runs.jsonl"

GUARDRAIL_PROMPT = (
    "\nSAFETY GUARDRAILS — override everything else:\n"
    "1. NEVER click Buy Now, Purchase, Checkout, Pay, Place Order, Confirm Order, "
    "Complete Purchase, or any equivalent commerce CTA.\n"
    "2. NEVER submit forms containing credit card numbers, CVVs, bank account details, "
    "Social Security Numbers, or passwords on any site the user did not explicitly name.\n"
    "3. NEVER submit credentials (username/password) on any site not explicitly named.\n"
    "4. If you encounter such an element, set is_done=True, success=False, explain what you found.\n"
)

CAPTCHA_KEYWORDS = frozenset([
    "captcha", "recaptcha", "hcaptcha", "cloudflare",
    "bot detection", "access denied", "verify you are human",
    "i'm not a robot", "challenge",
])


def build_llm(cfg: "Settings"):
    """Construct the LLM object for the configured provider.

    api_key is passed explicitly — never set as os.environ to avoid log leakage.
    .get_secret_value() is called at the call site only; the SecretStr wrapper is
    never passed to an external constructor or logged.
    """
    provider = cfg.provider.lower()
    if provider == "ollama":
        return ChatOllama(model=cfg.ollama_model, ollama_options={"num_ctx": 32000})
    elif provider == "anthropic":
        if not cfg.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        return ChatAnthropic(
            model=cfg.anthropic_model,
            api_key=cfg.anthropic_api_key.get_secret_value(),
        )
    elif provider == "openai":
        if not cfg.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        return ChatLiteLLM(
            model=cfg.openai_model,
            api_key=cfg.openai_api_key.get_secret_value(),
        )
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


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
            print(
                f"ERROR: Ollama is not running or unreachable.\n"
                f"  Start it with: ollama serve\n"
                f"  Then pull the model: ollama pull {cfg.ollama_model}"
            )
            raise PreFlightError("Ollama unreachable")

        # Exact base-name match: split both sides on ":" to avoid substring false positives.
        # e.g. "qwen3-vl" must not match "old-qwen3-vl-7b" or "qwen3" matching "qwen3-vl".
        model_base = cfg.ollama_model.split(":")[0]
        pulled_bases = [m.split(":")[0] for m in models]
        if model_base not in pulled_bases:
            print(
                f"ERROR: Model '{cfg.ollama_model}' is not pulled.\n"
                f"  Pull it with: ollama pull {cfg.ollama_model}"
            )
            raise PreFlightError(f"Model not pulled: {cfg.ollama_model}")

    elif cfg.provider == "anthropic":
        if not cfg.anthropic_api_key:
            print("ERROR: ANTHROPIC_API_KEY is not set in .env")
            raise PreFlightError("Missing Anthropic API key")
        try:
            import anthropic as _anthropic
            client = _anthropic.AsyncAnthropic(
                api_key=cfg.anthropic_api_key.get_secret_value()
            )
            await client.models.list()
        except _anthropic.AuthenticationError:
            print("ERROR: Anthropic API key is invalid.")
            raise PreFlightError("Invalid Anthropic API key")
        except Exception as e:
            print(f"ERROR: Cannot reach Anthropic API: {e}")
            raise PreFlightError("Anthropic API unreachable")

    elif cfg.provider == "openai":
        if not cfg.openai_api_key:
            print("ERROR: OPENAI_API_KEY is not set in .env")
            raise PreFlightError("Missing OpenAI API key")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {cfg.openai_api_key.get_secret_value()}"},
                )
                if resp.status_code == 401:
                    print("ERROR: OpenAI API key is invalid.")
                    raise PreFlightError("Invalid OpenAI API key")
                resp.raise_for_status()
        except PreFlightError:
            raise
        except Exception as e:
            print(f"ERROR: Cannot reach OpenAI API: {e}")
            raise PreFlightError("OpenAI API unreachable")


def _write_jsonl(path: Path, record: dict) -> None:
    """Write a single JSONL record to path (append mode). Called via asyncio.to_thread."""
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


async def log_step(agent, *, run_id: str) -> dict:
    """on_step_end callback. Writes one JSONL record to training/runs.jsonl.

    Callback signature: async def log_step(agent: Agent) -> None
    Verified against installed browser_use 0.12.6 agent/service.py:
      AgentHookFunc = Callable[['Agent'], Awaitable[None]]
      agent.history (AgentHistoryList) is populated incrementally during run().
    run_id must be passed via a closure (see run_agent) so each agent session
    gets its own unique identifier.
    """
    TRAINING_FILE.parent.mkdir(parents=True, exist_ok=True)

    history = agent.history
    step_idx = history.number_of_steps() - 1

    actions = history.model_actions()
    last_action = actions[-1] if actions else {}

    screenshots = history.screenshots()
    screenshot_b64 = screenshots[-1] if screenshots else ""
    # screenshots() may return None entries; guard against None
    if screenshot_b64 is None:
        screenshot_b64 = ""

    # Extract action fields from the action dict.
    # model_actions() returns dicts from action.model_dump() — keys are action type names.
    # The test fake uses .get("action_type"), .get("action_target"), .get("action_value")
    # which return the stub values from _make_fake_agent(). In production these will be
    # the first key of the dumped action dict; we extract a best-effort representation.
    action_type = last_action.get("action_type") or (list(last_action.keys())[0] if last_action else "unknown")
    action_target = last_action.get("action_target", last_action.get("index", ""))
    action_value = last_action.get("action_value", last_action.get("text", ""))

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "step_index": step_idx,
        "screenshot_b64": screenshot_b64,
        "action_type": action_type,
        "action_target": str(action_target),
        "action_value": str(action_value),
        "narration": f"Step {step_idx + 1}: {action_type}",
        "step_success": not history.has_errors(),
    }

    await asyncio.to_thread(_write_jsonl, TRAINING_FILE, record)

    print(f"[step {step_idx + 1}] {record['narration']}")

    # CAPTCHA detection via error keyword scan (CaptchaWatchdog does not fire for local Chrome)
    last_results = agent.state.last_result or []
    for result in last_results:
        error_text = (getattr(result, "error", None) or "").lower()
        if any(kw in error_text for kw in CAPTCHA_KEYWORDS):
            print(
                "\n[CAPTCHA DETECTED] Agent encountered a CAPTCHA challenge.\n"
                "  The agent is now paused. Solve the CAPTCHA manually in Chrome.\n"
                "  The run will not auto-continue. Press Ctrl+C to stop.\n"
            )
            agent.pause()
            break

    # Token delta extraction — Phase 5 (PERF-02)
    # Use a fresh Settings() instance so tests can override PROVIDER via env vars.
    from agent.config import Settings as _Settings  # noqa: PLC0415
    provider = _Settings().provider.lower()
    token_data: dict = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}

    if provider in ("anthropic", "openai"):
        history = agent.token_cost_service.usage_history
        if history:
            entry = history[-1]
            token_data["prompt_tokens"] = entry.usage.prompt_tokens
            token_data["completion_tokens"] = entry.usage.completion_tokens
            cost_calc = await agent.token_cost_service.calculate_cost(
                entry.model, entry.usage
            )
            if cost_calc is not None:
                token_data["cost_usd"] = round(cost_calc.total_cost, 6)

    return token_data


async def run_agent(task: str, queue: asyncio.Queue | None = None) -> None:
    """Pre-flight, build BrowserSession+Agent, asyncio.wait_for(agent.run(...), timeout).

    If `queue` is provided, emits SSE event dataclasses for the web UI bridge (D-11).
    DoneEvent is always the final item put on the queue regardless of exit path —
    this prevents the GET /stream endpoint from hanging forever.

    The `browser` variable is initialized to None before the try block so the
    finally handler can guard `await browser.kill()` against the PreFlightError path
    (where BrowserSession is never constructed). See RESEARCH.md Pitfall 4.
    """
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    step_start = time.monotonic()

    if queue is not None:
        queue.put_nowait(StateEvent(state="running"))
        queue.put_nowait(ModelInfoEvent(provider=config.provider, model_name=_resolve_model_name(config)))

    browser = None
    summary = None
    error_msg = None

    try:
        await pre_flight_check(config)
    except PreFlightError as e:
        error_msg = str(e)
        # Fall through to finally — do not return here so DoneEvent is always emitted
    else:
        profile = BrowserProfile(
            prohibited_domains=config.blocked_domains,
            channel="chrome",
            headless=False,
            keep_alive=False,
            window_size={"width": config.browser_width, "height": config.browser_height},
        )
        browser = BrowserSession(browser_profile=profile)
        browser.llm_screenshot_size = (config.llm_screenshot_width, config.llm_screenshot_height)

        async def _log_step(agent_instance):
            nonlocal step_start
            duration_ms = int((time.monotonic() - step_start) * 1000)
            token_data = await log_step(agent_instance, run_id=run_id)
            if queue is not None:
                step_idx = agent_instance.history.number_of_steps() - 1
                actions = agent_instance.history.model_actions()
                last_action = actions[-1] if actions else {}
                action_type = (
                    last_action.get("action_type")
                    or (list(last_action.keys())[0] if last_action else "unknown")
                )
                narration = f"Step {step_idx + 1}: {action_type}"
                queue.put_nowait(NarrationEvent(
                    step=step_idx + 1,
                    text=narration,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    step_duration_ms=duration_ms,
                ))
                # ScreenshotEvent — emit after narration; empty b64 on missing screenshot
                screenshots = agent_instance.history.screenshots()
                b64 = screenshots[-1] if (screenshots and screenshots[-1]) else ""
                queue.put_nowait(ScreenshotEvent(b64=b64))
                # ProgressEvent — step counter for the UI progress display
                queue.put_nowait(ProgressEvent(step=step_idx + 1, max_steps=config.max_steps))
                # TokenEvent — one per step (PERF-02)
                queue.put_nowait(TokenEvent(step=step_idx + 1, **token_data))
            step_start = time.monotonic()

        try:
            llm = build_llm(config)
            agent = Agent(
                task=task,
                llm=llm,
                browser_session=browser,
                extend_system_message=GUARDRAIL_PROMPT,
                calculate_cost=True,
            )

            # Set module-level ref so /pause and /stop can reach the active agent.
            # Deferred import inside run_agent to avoid circular import at module load time
            # (agent/main.py imports from agent/runner.py at module level).
            from agent import main as _main_module  # noqa: PLC0415
            _main_module._active_agent = agent

            try:
                history = await asyncio.wait_for(
                    agent.run(max_steps=config.max_steps, on_step_end=_log_step),
                    timeout=config.session_timeout,
                )
                summary = history.final_result()
                print(f"Done: {summary}")
            except asyncio.TimeoutError:
                error_msg = f"Session timeout ({config.session_timeout}s)"
                print(f"Session timeout reached ({config.session_timeout}s). Stopping.")
        except Exception as e:
            if not isinstance(e, asyncio.TimeoutError):
                error_msg = str(e)
                # Do not re-raise: error_msg is sent to the queue in the outer finally block.
                # A bare raise here propagates out of the asyncio.Task and produces a noisy
                # "Task exception was never retrieved" warning with no additional benefit since
                # the error is already captured and will be surfaced to the UI via ErrorEvent.
        finally:
            if browser is not None:
                await browser.kill()

    finally:
        if queue is not None:
            if error_msg:
                queue.put_nowait(ErrorEvent(message=error_msg))
                queue.put_nowait(StateEvent(state="error"))
            else:
                if summary:
                    queue.put_nowait(SummaryEvent(text=summary))
                queue.put_nowait(StateEvent(state="complete"))
            queue.put_nowait(DoneEvent())

        # Persist run record to history DB.
        # Guard with try/except so a DB failure NEVER prevents cleanup below.
        try:
            if error_msg:
                run_status = "error"
            else:
                try:
                    _agent_stopped = (
                        getattr(agent, "state", None) is not None
                        and getattr(agent.state, "stopped", False)
                    )
                except NameError:
                    _agent_stopped = False
                run_status = "stopped" if _agent_stopped else "complete"

            completed_at = datetime.now(timezone.utc).isoformat()
            started_at_iso = started_at.isoformat()
            await history_db.insert_run(
                run_id=run_id,
                task=task,
                status=run_status,
                summary=summary,
                started_at=started_at_iso,
                completed_at=completed_at,
            )
        except Exception:
            pass  # DB failure must not surface — cleanup below must always run

        # Clear module-level refs so stale SSE consumers detect run ended.
        try:
            from agent import main as _main_module  # noqa: PLC0415
            _main_module._active_agent = None
            _main_module._active_queue = None
        except Exception:
            pass
