from __future__ import annotations

import asyncio
import json
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
)
from agent import db as history_db

if TYPE_CHECKING:
    from agent.config import Settings


class PreFlightError(RuntimeError):
    """Raised when pre_flight_check detects a fatal configuration issue."""

TRAINING_FILE = Path("training/runs.jsonl")

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


async def log_step(agent, *, run_id: str) -> None:
    """on_step_end callback. Writes one JSONL record to training/runs.jsonl.

    Callback signature: async def log_step(agent: Agent) -> None
    Verified against installed browser_use 0.12.6 agent/service.py:
      AgentHookFunc = Callable[['Agent'], Awaitable[None]]
      agent.history (AgentHistoryList) is populated incrementally during run().
    run_id must be passed via a closure (see run_agent) so each agent session
    gets its own unique identifier.
    """
    Path("training").mkdir(exist_ok=True)

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

    if queue is not None:
        queue.put_nowait(StateEvent(state="running"))

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
            await log_step(agent_instance, run_id=run_id)
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
                ))

        try:
            llm = build_llm(config)
            agent = Agent(
                task=task,
                llm=llm,
                browser_session=browser,
                extend_system_message=GUARDRAIL_PROMPT,
            )

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
                raise
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
