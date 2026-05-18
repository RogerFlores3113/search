from __future__ import annotations

import asyncio
import base64
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
    ScreenshotEvent, StateEvent,
    ProgressEvent, SummaryEvent, ErrorEvent, DoneEvent,
    TokenEvent, ModelInfoEvent, ThoughtEvent, ActionDetailEvent,
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


def _put_nowait(queue: asyncio.Queue, event: object) -> None:
    """Put event on queue, silently dropping if full."""
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass


def _write_jsonl(path: Path, record: dict) -> None:
    """Write a single JSONL record to path (append mode). Called via asyncio.to_thread."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _rewrite_jsonl_run_success(path: Path, run_id: str, run_success: bool) -> None:
    """Back-fill `run_success` into every record matching `run_id` (D-04).

    Synchronous, in-place rewrite. Callers wrap with asyncio.to_thread.
    Malformed JSONL lines are preserved verbatim. Missing file is a no-op.
    Failures in this routine MUST be swallowed by the caller's try/except so the
    user is never surfaced a rewrite failure (per D-04).
    """
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        if record.get("run_id") == run_id:
            record["run_success"] = run_success
        out.append(json.dumps(record))
    if out:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _derive_step_quality(agent) -> str:
    """Return per-step quality literal: 'clean' | 'partial' | 'failed'.

    Per-step semantics (RESEARCH.md Pitfall 2): read `agent.state.last_result`
    (NOT `agent.history.has_errors()` which is cumulative across the whole run).
    If any current-step result carries a non-None .error, return 'failed'; else
    'clean'. The 'partial' literal is reserved (Open Q2) but not emitted in v1.
    """
    last_results = agent.state.last_result or []
    if any(getattr(r, "error", None) is not None for r in last_results):
        return "failed"
    return "clean"


# Module-level thoughts accumulator (closure-scoped equivalent for testability).
# In production this is reset and populated inside run_agent's _pre_step closure;
# tests patch this dict directly to inject thoughts into log_step.
_thoughts: dict[int, dict] = {}


async def log_step(agent, *, run_id: str, provider: str, duration_ms: int, thoughts: dict | None = None) -> dict:
    """on_step_end callback. Writes one JSONL record to training/runs.jsonl.

    Callback signature: async def log_step(agent: Agent) -> None
    Verified against installed browser_use 0.12.6 agent/service.py:
      AgentHookFunc = Callable[['Agent'], Awaitable[None]]
      agent.history (AgentHistoryList) is populated incrementally during run().
    run_id must be passed via a closure (see run_agent) so each agent session
    gets its own unique identifier.
    provider must be passed from the call site (config.provider.lower()) so the
    Settings object is not re-instantiated on every step.
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
    action_type = next(
        (k for k in last_action if k != "interacted_element"),
        "unknown",
    ) if last_action else "unknown"
    action_target = last_action.get("action_target", last_action.get("index", ""))
    action_value = last_action.get("action_value", last_action.get("text", ""))

    # Token delta extraction — Phase 5 (PERF-02). Computed before record build so
    # the enriched record (TRAIN-01) can embed the values. Provider gate (TRAIN-02):
    # only anthropic/openai populate token + thought fields; Ollama gets explicit null.
    token_data: dict = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}

    if provider in ("anthropic", "openai"):
        # CR-01 fix (D-07): rename the inner re-binding to `token_history` so it does
        # NOT shadow the outer `history = agent.history` binding.
        token_history = agent.token_cost_service.usage_history
        if token_history:
            entry = token_history[-1]
            token_data["prompt_tokens"] = entry.usage.prompt_tokens
            token_data["completion_tokens"] = entry.usage.completion_tokens
            cost_calc = await agent.token_cost_service.calculate_cost(
                entry.model, entry.usage
            )
            if cost_calc is not None:
                token_data["cost_usd"] = round(cost_calc.total_cost, 6)

    # Resolve thought fields. Lookup key is 1-indexed (step_idx + 1) — equivalent to
    # agent.history.number_of_steps() — per Pitfall 1. Falls back to the module-level
    # _thoughts dict for direct-call test paths.
    if thoughts is None:
        thoughts = _thoughts
    thought_for_step = thoughts.get(step_idx + 1, {}) if isinstance(thoughts, dict) else {}

    api_provider = provider in ("anthropic", "openai")
    model_thought = thought_for_step.get("thinking") if api_provider else None
    evaluation_previous_goal = thought_for_step.get("evaluation_previous_goal") if api_provider else None
    next_goal = thought_for_step.get("next_goal") if api_provider else None

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
        "step_duration_ms": duration_ms,
        "prompt_tokens": token_data["prompt_tokens"],
        "completion_tokens": token_data["completion_tokens"],
        "cost_usd": token_data["cost_usd"],
        "model_thought": model_thought,
        "evaluation_previous_goal": evaluation_previous_goal,
        "next_goal": next_goal,
        "provider": provider,
        "model_name": _resolve_model_name(config),
        "step_quality": _derive_step_quality(agent),
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
    # Closure-scoped thoughts accumulator: _pre_step writes at 1-indexed step_num,
    # _log_step reads at step_idx+1 (Pitfall 1).
    run_thoughts: dict[int, dict] = {}
    # Per-run aggregates persisted to SQLite at completion so /runs is a
    # straight DB read with no JSONL scan. `cost_is_null_for_ollama` flips
    # True whenever an Ollama step reports None — the final cost stays None
    # in that case (Phase 5/8 null semantics).
    run_step_count = 0
    run_duration_ms = 0
    run_cost_usd = 0.0
    run_cost_is_null_for_ollama = False

    if queue is not None:
        _put_nowait(queue, StateEvent(state="running"))
        _put_nowait(queue, ModelInfoEvent(provider=config.provider, model_name=_resolve_model_name(config)))

    browser = None
    screenshot_task = None
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

        async def _pre_step(browser_state, agent_output, step_num: int) -> None:
            """Pre-action callback fired via register_new_step_callback before each step.

            Puts a ThoughtEvent on the queue carrying the model's reasoning fields.
            When queue is None (CLI path), returns immediately without side effects.
            Empty string fields are normalized to None via 'or None' guard (RESEARCH.md Pitfall 2).

            Also writes to run_thoughts so log_step can embed the same fields in JSONL.
            step_num is 1-indexed (matches agent.history.number_of_steps()).
            """
            run_thoughts[step_num] = {
                "thinking": agent_output.thinking or None,
                "evaluation_previous_goal": agent_output.evaluation_previous_goal or None,
                "next_goal": agent_output.next_goal or None,
            }
            if queue is None:
                return
            _put_nowait(queue, ThoughtEvent(
                step=step_num,
                thinking=agent_output.thinking or None,
                evaluation_previous_goal=agent_output.evaluation_previous_goal or None,
                next_goal=agent_output.next_goal or None,
                memory=agent_output.memory or None,
            ))

        async def _log_step(agent_instance):
            nonlocal step_start, run_step_count, run_duration_ms, run_cost_usd, run_cost_is_null_for_ollama
            duration_ms = int((time.monotonic() - step_start) * 1000)
            step_idx = agent_instance.history.number_of_steps() - 1
            token_data = await log_step(
                agent_instance,
                run_id=run_id,
                provider=config.provider.lower(),
                duration_ms=duration_ms,
                thoughts=run_thoughts,
            )
            run_step_count += 1
            run_duration_ms += duration_ms
            step_cost = token_data.get("cost_usd")
            if step_cost is None and config.provider.lower() == "ollama":
                run_cost_is_null_for_ollama = True
            elif step_cost is not None:
                run_cost_usd += step_cost
            if queue is not None:
                actions = agent_instance.history.model_actions()
                last_action = actions[-1] if actions else {}
                # action_type: first key that is NOT 'interacted_element' (RESEARCH.md Pitfall 4)
                action_type = next(
                    (k for k in last_action if k != "interacted_element"), "unknown"
                )
                # Extract action params — inner dict keyed by action_type
                params = last_action.get(action_type) if isinstance(last_action.get(action_type), dict) else {}
                target = str(params["index"]) if "index" in params else None
                value = params.get("text") or params.get("query") or params.get("keys") or None
                url = params.get("url") or None
                # ActionDetailEvent replaces NarrationEvent (D-05)
                _put_nowait(queue, ActionDetailEvent(
                    step=step_idx + 1,
                    action_type=action_type,
                    target=target,
                    value=value,
                    url=url,
                    success=None,
                ))
                # ProgressEvent — step counter for the UI progress display
                _put_nowait(queue, ProgressEvent(step=step_idx + 1, max_steps=config.max_steps))
                # TokenEvent — one per step (PERF-02)
                _put_nowait(queue, TokenEvent(step=step_idx + 1, **token_data))
            step_start = time.monotonic()

        async def _screenshot_loop() -> None:
            while True:
                captured = False
                try:
                    data = await asyncio.wait_for(
                        browser.take_screenshot(format='jpeg', quality=75),
                        timeout=3.0,
                    )
                    b64 = base64.b64encode(data).decode()
                    _put_nowait(queue, ScreenshotEvent(b64=b64))
                    captured = True
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass
                await asyncio.sleep(0.5 if captured else 0)

        try:
            llm = build_llm(config)
            agent = Agent(
                task=task,
                llm=llm,
                browser_session=browser,
                extend_system_message=GUARDRAIL_PROMPT,
                calculate_cost=True,
                register_new_step_callback=_pre_step,
            )

            # Set module-level ref so /pause and /stop can reach the active agent.
            # Deferred import inside run_agent to avoid circular import at module load time
            # (agent/main.py imports from agent/runner.py at module level).
            from agent import main as _main_module  # noqa: PLC0415
            _main_module._active_agent = agent

            if queue is not None:
                screenshot_task = asyncio.create_task(_screenshot_loop())

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
            if screenshot_task is not None:
                screenshot_task.cancel()
                await asyncio.gather(screenshot_task, return_exceptions=True)
            if browser is not None:
                await browser.kill()

    finally:
        if queue is not None:
            if error_msg:
                _put_nowait(queue, ErrorEvent(message=error_msg))
                _put_nowait(queue, StateEvent(state="error"))
            else:
                if summary:
                    _put_nowait(queue, SummaryEvent(text=summary))
                _put_nowait(queue, StateEvent(state="complete"))
            _put_nowait(queue, DoneEvent())

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
            final_cost = None if run_cost_is_null_for_ollama else run_cost_usd
            await history_db.insert_run(
                run_id=run_id,
                task=task,
                status=run_status,
                summary=summary,
                started_at=started_at_iso,
                completed_at=completed_at,
                step_count=run_step_count,
                total_duration_s=run_duration_ms // 1000,
                total_cost_usd=final_cost,
                model_name=_resolve_model_name(config),
                provider=config.provider.lower(),
            )
        except Exception:
            pass  # DB failure must not surface — cleanup below must always run

        # Back-fill run_success into every JSONL record for this run (D-04 / TRAIN-03).
        # Synchronous helper wrapped via asyncio.to_thread. Failures MUST never surface.
        try:
            run_success = (run_status == "complete")
            await asyncio.to_thread(_rewrite_jsonl_run_success, TRAINING_FILE, run_id, run_success)
        except Exception:
            pass  # rewrite failure must never surface (D-04)

        # Clear module-level refs so stale SSE consumers detect run ended.
        try:
            from agent import main as _main_module  # noqa: PLC0415
            _main_module._active_agent = None
            _main_module._active_queue = None
        except Exception:
            pass
