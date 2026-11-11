"""BrowserAgent: the importable agent loop."""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import inspect
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from browser_use import Agent
from pydantic import ValidationError

from local_browser_agent.browser import build_browser_session, start_url_problem
from local_browser_agent.captcha import looks_like_captcha
from local_browser_agent.chrome import ChromeNotFoundError
from local_browser_agent.config import AgentConfig
from local_browser_agent.events import (
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
from local_browser_agent.models import PreFlightError, build_llm, resolve_model_name
from local_browser_agent.redact import redact, redact_url
from local_browser_agent.safety import ActionRequest, ApprovalCallback, GuardedTools  # noqa: F401

logger = logging.getLogger("local_browser_agent")

SINK_TIMEOUT_S = 5.0  # a hung event sink is logged and dropped after this long
TEARDOWN_TIMEOUT_S = 10.0  # bound on stopping/killing the browser
STOP_GRACE_S = 2.0  # after stop(), let the current step finish this long, then cancel it
SINK_MAX_TIMEOUTS = 3  # a sink that times out this many times in a row is dropped for the run
_TICK_S = 0.1  # supervisor poll interval (timeout clock / stop checks)
_CONNECTION_ERROR_MARKERS = (
    "all connection attempts failed", "connect call failed", "connection refused",
    "econnrefused", "cannot connect to host", "failed to connect", "connecterror",
)
SCREENSHOT_INTERVAL_S = 0.5
_SCREENSHOT_BACKOFF_CAP_S = 4.0
_SCREENSHOT_TIMEOUT_S = 3.0
_LABEL_MAX_LEN = 80
_LABEL_TAG_FALLBACK = frozenset({"button", "a", "input", "textarea", "select"})


# RunResult.error_kind values:
#   chrome_missing     no Chrome/Chromium found (and no cdp_url / executable_path)
#   preflight          provider/API-key/model check failed (PreFlightError or a custom preflight)
#   config             invalid configuration found while building the LLM or browser
#   cdp_connect        could not attach to Chrome at BrowserConfig.cdp_url
#   timeout            AgentConfig.timeout_s elapsed
#   captcha            CAPTCHA / human verification stopped the run (on_captcha="fail")
#   stopped            stop() was called
#   start_url_blocked  start_url is not http(s), blocked, outside allowed_domains or local
#   agent_error        any other error during the run
ERROR_KINDS = ("chrome_missing", "preflight", "config", "cdp_connect", "timeout", "captcha",
               "stopped", "start_url_blocked", "agent_error")


@dataclass
class StepRecord:
    index: int
    action_type: str = "unknown"
    target_label: str | None = None
    value: str | None = None
    url: str | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass
class RunResult:
    run_id: str
    task: str
    status: str  # success | failed | error | timeout | stopped
    success: bool | None = None
    final_result: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    step_count: int = 0
    duration_s: float = 0.0
    cost_usd: float | None = None
    errors: list[str] = field(default_factory=list)
    urls_visited: list[str] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    # Why the run ended badly (None on success / plain agent failure). One of ERROR_KINDS.
    error_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _truncate_label(s: str) -> str:
    s = " ".join(s.split())
    return s if len(s) <= _LABEL_MAX_LEN else s[: _LABEL_MAX_LEN - 1].rstrip() + "…"


def extract_target_label(interacted_element: object) -> str | None:
    """Best-effort human-readable label of the element acted on (never raises)."""
    if interacted_element is None:
        return None

    def _get(name: str):
        v = getattr(interacted_element, name, None)
        if v is None and isinstance(interacted_element, dict):
            v = interacted_element.get(name)
        return v

    ax_name = _get("ax_name")
    if isinstance(ax_name, str) and ax_name.strip():
        return _truncate_label(ax_name)
    attributes = _get("attributes") or {}
    if isinstance(attributes, dict):
        for attr in ("aria-label", "title", "placeholder", "name"):
            v = attributes.get(attr)
            if isinstance(v, str) and v.strip():
                return _truncate_label(v)
    node_value = _get("node_value")
    if isinstance(node_value, str) and node_value.strip():
        return _truncate_label(node_value)
    node_name = _get("node_name")
    if isinstance(node_name, str) and node_name.strip().lower() in _LABEL_TAG_FALLBACK:
        return f"<{node_name.strip().lower()}>"
    return None


async def _screenshot_loop(browser: Any, emit, stop: asyncio.Event | None = None) -> None:
    """Emit a JPEG ScreenshotEvent every ~0.5s with exponential back-off on failure.

    CancelledError is deliberately not caught so teardown can cancel it before
    the browser is killed. ``stop`` is a second way out: on Python 3.11
    ``asyncio.wait_for`` can swallow a cancel that lands as the inner call
    finishes, which used to leave this loop (and teardown) running forever, so
    the per-shot timeout uses ``asyncio.timeout`` and the loop also checks ``stop``.
    """
    failures = 0
    while stop is None or not stop.is_set():
        try:
            async with asyncio.timeout(_SCREENSHOT_TIMEOUT_S):
                data = await browser.take_screenshot(format="jpeg", quality=75)
            await emit(ScreenshotEvent(b64=base64.b64encode(data).decode()))
            failures = 0
            await asyncio.sleep(SCREENSHOT_INTERVAL_S)
        except Exception:
            failures += 1
            await asyncio.sleep(min(SCREENSHOT_INTERVAL_S * (2 ** (failures - 1)), _SCREENSHOT_BACKOFF_CAP_S))


class BrowserAgent:
    """Runs one natural-language task at a time in a browser.

    ``sinks`` are async callables receiving event dataclasses. ``approval`` is
    ``async (ActionRequest) -> bool`` asked before a gated (commerce) click.
    ``preflight`` is an optional ``async () -> None`` run after the start events and
    before the browser is built; an exception from it ends the run with status "error".
    """

    def __init__(self, config: AgentConfig | None = None, *, sinks: Iterable[Any] = (),
                 approval: ApprovalCallback | None = None,
                 preflight: Callable[[], Awaitable[None]] | None = None) -> None:
        self.config = config or AgentConfig()
        self.sinks = list(sinks)
        self.approval = approval
        self.preflight = preflight
        self._agent: Any = None
        self._running = False
        self._stop_requested = False
        self._paused = False
        self._bg: set[asyncio.Task] = set()
        self._run_id = ""
        self._main_task: asyncio.Future | None = None
        self._sink_timeouts: dict[int, int] = {}
        self._sinks_dropped: set[int] = set()

    # ---- control -------------------------------------------------------
    def _fire(self, event: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._emit(event))
        except RuntimeError:
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    @property
    def is_active(self) -> bool:
        """True once the underlying browser-use agent exists (pause/resume/stop take effect)."""
        return self._agent is not None

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        if self._agent is not None:
            self._agent.pause()
            self._paused = True
            self._fire(StateEvent(state="paused"))

    def resume(self) -> None:
        if self._agent is not None:
            self._agent.resume()
            self._paused = False
            self._fire(StateEvent(state="running"))

    def stop(self) -> None:
        """Stop the run. The current step gets ``STOP_GRACE_S`` to finish, then the in-flight
        action (model call, browser action or pending approval) is cancelled, so a stopped run
        ends within a few seconds and returns ``status="stopped"``."""
        self._stop_requested = True
        self._paused = False
        if self._agent is not None:
            self._agent.stop()

    # ---- events --------------------------------------------------------
    def _secrets(self) -> list[str]:
        key = self.config.model.api_key
        return [key.get_secret_value()] if key is not None else []

    def _redact(self, text: str) -> str:
        return redact(text, self._secrets())

    async def _emit(self, event: Any) -> None:
        step_event = isinstance(event, StepCompletedEvent)
        if self._run_id and getattr(event, "run_id", None) == "":
            event.run_id = self._run_id
        etype = getattr(event, "type", type(event).__name__)
        for sink in self.sinks:
            key = id(sink)
            if key in self._sinks_dropped:
                continue
            if step_event and not getattr(sink, "wants_step_events", False):
                continue
            try:
                async with asyncio.timeout(SINK_TIMEOUT_S):
                    await sink(event)
                self._sink_timeouts[key] = 0
            except TimeoutError:
                n = self._sink_timeouts.get(key, 0) + 1
                self._sink_timeouts[key] = n
                if key in self._sinks_dropped:
                    continue  # dropped by a concurrent emit while this one was waiting
                if n >= SINK_MAX_TIMEOUTS:
                    self._sinks_dropped.add(key)
                    logger.warning("event sink %r timed out %d times in a row (last on %r event, limit %gs); "
                                   "dropping it for the rest of the run", sink, n, etype, SINK_TIMEOUT_S)
                else:
                    logger.debug("event sink %r timed out on %r event after %gs", sink, etype, SINK_TIMEOUT_S)
            except Exception as e:  # a failing sink must never crash a run
                logger.warning("event sink %r failed on %r event: %s", sink, etype,
                               self._redact(str(e)), exc_info=True)

    def _wants_screenshots(self) -> bool:
        return any(getattr(s, "wants_screenshots", True) for s in self.sinks)

    # ---- run -----------------------------------------------------------
    async def run(self, task: str, start_url: str | None = None) -> RunResult:
        if self._running:
            raise RuntimeError("BrowserAgent is already running a task; use one instance per concurrent run")
        self._running = True
        self._stop_requested = False
        self._paused = False
        self._sink_timeouts = {}
        self._sinks_dropped = set()
        try:
            return await self._run(task, start_url)
        finally:
            self._running = False
            self._paused = False
            self._agent = None
            self._main_task = None

    async def _run(self, task: str, start_url: str | None) -> RunResult:
        cfg = self.config
        provider = cfg.model.provider.lower()
        run_id = str(uuid.uuid4())
        self._run_id = run_id
        t0 = time.monotonic()
        steps: list[StepRecord] = []
        errors: list[str] = []
        blocked: list[str] = []
        cost_total = 0.0
        cost_seen = False
        usage_seen = 0
        step_start = time.monotonic()
        summary: str | None = None
        history: Any = None
        timed_out = False
        error_msg: str | None = None
        captcha_msg: str | None = None
        thoughts: dict[int, dict[str, str | None]] = {}
        want_step_events = any(getattr(s, "wants_step_events", False) for s in self.sinks)
        browser = None
        screenshot_task = None
        screenshot_stop = asyncio.Event()
        agent = None
        conn_msg: str | None = None
        error_kind: str | None = None
        phase = "build"
        start_err = start_url_problem(start_url, cfg.safety) if start_url else None
        fatal: BaseException | None = None
        # Cost tracking fetches pricing data over the network. The runner honours
        # ``cfg.calculate_cost`` as-is; the field's default (True) lives in config.py.
        want_cost = bool(cfg.calculate_cost)

        def _cdp_connect_message(text: str) -> str | None:
            """Friendly message when attaching to ``browser.cdp_url`` failed to connect."""
            url = cfg.browser.cdp_url
            low = text.lower()
            if not url or "net::" in low or not any(m in low for m in _CONNECTION_ERROR_MARKERS):
                return None
            return (f"Could not connect to Chrome at {redact_url(url)}. "
                    "Is Chrome running with --remote-debugging-port?")

        try:
            model_name = resolve_model_name(cfg.model)
        except ValueError:
            model_name = cfg.model.model or ""

        await self._emit(StateEvent(state="running"))
        await self._emit(ModelInfoEvent(provider=provider, model_name=model_name))

        async def _pre_step(browser_state, agent_output, step_num: int) -> None:
            thoughts[step_num] = {
                "thinking": agent_output.thinking or None,
                "evaluation_previous_goal": agent_output.evaluation_previous_goal or None,
                "next_goal": agent_output.next_goal or None,
                "memory": agent_output.memory or None,
            }
            await self._emit(ThoughtEvent(
                step=step_num,
                thinking=agent_output.thinking or None,
                evaluation_previous_goal=agent_output.evaluation_previous_goal or None,
                next_goal=agent_output.next_goal or None,
                memory=agent_output.memory or None,
            ))

        async def _on_step_end(agent_instance) -> None:
            nonlocal step_start, cost_total, cost_seen, usage_seen, captcha_msg, conn_msg
            duration_ms = int((time.monotonic() - step_start) * 1000)
            hist = agent_instance.history
            idx = hist.number_of_steps()  # 1-indexed
            actions = hist.model_actions()
            last = actions[-1] if actions else {}
            action_type = next((k for k in last if k != "interacted_element"), "unknown") if last else "unknown"
            inner = last.get(action_type) if isinstance(last.get(action_type), dict) else {}
            target = str(inner["index"]) if "index" in inner else None
            if target is None and last.get("action_target") not in (None, ""):
                target = str(last["action_target"])
            value = inner.get("text") or inner.get("query") or inner.get("keys") or last.get("action_value") or None
            url = inner.get("url") or None
            label = extract_target_label(last.get("interacted_element")) if last else None
            step_error = None
            captcha_hit = False
            for r in (getattr(agent_instance.state, "last_result", None) or []):
                err = getattr(r, "error", None)
                if err:
                    if looks_like_captcha(str(err)):
                        captcha_hit = True
                    mapped = _cdp_connect_message(str(err))
                    if mapped is not None and conn_msg is None:
                        conn_msg = mapped
                        agent_instance.stop()
                    if step_error is None:
                        step_error = mapped or self._redact(str(err))
            if step_error:
                errors.append(step_error)
            steps.append(StepRecord(index=idx, action_type=action_type, target_label=label,
                                    value=str(value) if value is not None else None,
                                    url=url, error=step_error, duration_ms=duration_ms))

            tok = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}
            if want_cost and provider != "ollama":
                try:
                    svc = agent_instance.token_cost_service
                    new = svc.usage_history[usage_seen:]
                    usage_seen = len(svc.usage_history)
                    for entry in new:
                        tok["prompt_tokens"] = (tok["prompt_tokens"] or 0) + entry.usage.prompt_tokens
                        tok["completion_tokens"] = (tok["completion_tokens"] or 0) + entry.usage.completion_tokens
                        calc = await svc.calculate_cost(entry.model, entry.usage)
                        if calc is not None:
                            tok["cost_usd"] = (tok["cost_usd"] or 0.0) + calc.total_cost
                except Exception as e:
                    logger.debug("token/cost extraction failed: %s", e)
                if tok["cost_usd"] is not None:
                    tok["cost_usd"] = round(tok["cost_usd"], 6)
                    cost_total += tok["cost_usd"]
                    cost_seen = True

            await self._emit(ActionDetailEvent(step=idx, action_type=action_type, target=target,
                                               target_label=label, value=steps[-1].value, url=url,
                                               success=None if step_error is None else False,
                                               step_duration_ms=duration_ms))
            await self._emit(ProgressEvent(step=idx, max_steps=cfg.max_steps))
            await self._emit(TokenEvent(step=idx, **tok))

            if want_step_events:
                shot = ""
                try:
                    shots = hist.screenshots()
                    shot = (shots[-1] if shots else "") or ""
                except Exception as e:
                    logger.debug("step screenshot read failed: %s", e)
                th = thoughts.get(idx, {})
                try:
                    run_has_errors = bool(hist.has_errors())
                except Exception:
                    run_has_errors = bool(errors)
                await self._emit(StepCompletedEvent(
                    run_id=run_id, step=idx, screenshot_b64=shot, action_type=action_type, target=target,
                    target_label=label, value=steps[-1].value, url=url,
                    thinking=th.get("thinking"), evaluation_previous_goal=th.get("evaluation_previous_goal"),
                    next_goal=th.get("next_goal"), memory=th.get("memory"),
                    prompt_tokens=tok["prompt_tokens"], completion_tokens=tok["completion_tokens"],
                    cost_usd=tok["cost_usd"], duration_ms=duration_ms, error=step_error,
                    run_has_errors=run_has_errors,
                ))

            if captcha_hit and captcha_msg is None:
                page_url = None
                try:
                    seen = [u for u in hist.urls() if u and u != "about:blank"]
                    page_url = seen[-1] if seen else None
                except Exception:
                    pass
                where = f" at {page_url}" if page_url else ""
                note = self._redact(f"Human verification required (CAPTCHA or bot check detected{where})")
                await self._emit(HumanNeededEvent(reason="captcha", url=page_url, message=note))
                if cfg.on_captcha == "pause":
                    # Pause, never solve: the browser-use loop waits before the next step until
                    # resume() (or stop()) is called, e.g. after the person solves it in Chrome.
                    agent_instance.pause()
                    self._paused = True
                    await self._emit(StateEvent(state="paused"))
                else:
                    captcha_msg = note
                    errors.append(note)
                    agent_instance.stop()
            step_start = time.monotonic()

        try:
            try:
                async def _main() -> None:
                    nonlocal browser, agent, screenshot_task, history
                    nonlocal fatal, error_msg, error_kind, phase
                    if start_err:
                        # Nothing is launched (no preflight, LLM or browser) for a bad start_url.
                        error_msg, error_kind = start_err, "start_url_blocked"
                        return
                    if self.preflight is not None:
                        phase = "preflight"
                        try:
                            await self.preflight()
                        except (SystemExit, KeyboardInterrupt) as exc:
                            # A task would hand these to the event loop; re-raise from run() instead.
                            fatal = exc
                            return
                        phase = "build"
                    if self._stop_requested:
                        return  # stop() during preflight: build neither the Agent nor the browser
                    llm = build_llm(cfg.model)
                    browser = build_browser_session(cfg.browser, cfg.safety)
                    tool_kwargs: dict[str, Any] = dict(
                        patterns=cfg.safety.commerce_patterns,
                        gate_commerce_clicks=cfg.safety.gate_commerce_clicks,
                        allow_evaluate=cfg.safety.allow_evaluate,
                        blocked_domains=cfg.safety.blocked_domains,
                        approval=self.approval,
                        blocked_log=blocked,
                    )
                    if "allow_local_network" in inspect.signature(GuardedTools.__init__).parameters:
                        tool_kwargs["allow_local_network"] = cfg.safety.allow_local_network
                    tools = GuardedTools(**tool_kwargs)
                    parts = [p for p in (cfg.system_prompt_extension, cfg.safety.guardrail_prompt) if p]
                    kwargs: dict[str, Any] = dict(
                        task=task,
                        llm=llm,
                        browser_session=browser,
                        tools=tools,
                        extend_system_message="\n\n".join(parts) or None,
                        use_vision=cfg.use_vision,
                        use_judge=cfg.use_judge,
                        calculate_cost=want_cost,
                        register_new_step_callback=_pre_step,
                    )
                    if start_url:
                        kwargs["initial_actions"] = [{"navigate": {"url": start_url, "new_tab": False}}]
                    agent = Agent(**kwargs)
                    self._agent = agent
                    phase = "run"
                    if self._stop_requested:
                        agent.stop()
                    if self.sinks and self._wants_screenshots():
                        screenshot_task = asyncio.create_task(
                            _screenshot_loop(browser, self._emit, screenshot_stop)
                        )
                    history = await agent.run(max_steps=cfg.max_steps, on_step_end=_on_step_end)

                # timeout_s covers the whole run (preflight, build, agent loop). The clock is
                # paused while the run is paused (e.g. on_captcha="pause" waiting for a human).
                main_task = asyncio.ensure_future(_main())
                self._main_task = main_task
                stop_at: float | None = None
                stop_cancelled = False
                deadline = time.monotonic() + cfg.timeout_s
                last_tick = time.monotonic()
                try:
                    while not main_task.done():
                        now = time.monotonic()
                        if self._paused:
                            deadline += now - last_tick
                        last_tick = now
                        remaining = deadline - now
                        if remaining <= 0:
                            timed_out = True
                            break
                        if self._stop_requested:
                            stop_at = now if stop_at is None else stop_at
                            if agent is None or now - stop_at >= STOP_GRACE_S:
                                # Cancel the in-flight action (preflight, model call, browser
                                # action, pending approval) instead of waiting for it.
                                stop_cancelled = True
                                main_task.cancel()
                                await asyncio.wait({main_task}, timeout=TEARDOWN_TIMEOUT_S)
                                break
                        await asyncio.wait({main_task}, timeout=min(remaining, _TICK_S))
                    if stop_cancelled:
                        history = getattr(agent, "history", None)
                    if timed_out:
                        error_msg = f"Session timeout ({cfg.timeout_s:g}s)"
                        if agent is not None:
                            try:
                                agent.stop()
                            except Exception as e:
                                logger.debug("agent.stop() failed: %s", e)
                        main_task.cancel()
                        await asyncio.wait({main_task}, timeout=TEARDOWN_TIMEOUT_S)
                        history = getattr(agent, "history", None)
                    elif main_task.done() and not main_task.cancelled():
                        main_task.result()  # re-raise a real failure
                    if fatal is not None:
                        raise fatal
                finally:
                    if not main_task.done():
                        main_task.cancel()
            except Exception as e:
                error_msg = self._redact(f"{type(e).__name__}: {e}" if str(e) == "" else str(e))
                cdp_msg = _cdp_connect_message(str(e))
                error_msg = cdp_msg or error_msg
                if cdp_msg:
                    error_kind = "cdp_connect"
                elif isinstance(e, ChromeNotFoundError):
                    error_kind = "chrome_missing"
                elif isinstance(e, PreFlightError) or phase == "preflight":
                    error_kind = "preflight"
                elif phase == "build" and isinstance(e, (ValueError, ValidationError)):
                    error_kind = "config"
                else:
                    error_kind = "agent_error"
                logger.warning("run %s failed: %s", run_id, error_msg)
                if agent is not None:
                    history = getattr(agent, "history", None)
            finally:
                # Cancel the screenshot loop BEFORE tearing down the browser.
                if screenshot_task is not None:
                    screenshot_stop.set()
                    screenshot_task.cancel()
                    done, _ = await asyncio.wait({screenshot_task}, timeout=_SCREENSHOT_TIMEOUT_S + 1)
                    if not done:
                        logger.warning("screenshot loop did not stop in time; continuing teardown")
                if browser is not None:
                    try:
                        async with asyncio.timeout(TEARDOWN_TIMEOUT_S):
                            if cfg.browser.keep_alive or cfg.browser.cdp_url:
                                await browser.stop()  # leave a user-owned / kept-alive browser running
                            else:
                                await browser.kill()
                    except TimeoutError:
                        logger.warning("browser teardown timed out after %gs", TEARDOWN_TIMEOUT_S)
                    except Exception as e:
                        logger.debug("browser teardown failed: %s", self._redact(str(e)))

            urls: list[str] = []
            success_flag: bool | None = None
            final: str | None = None
            if history is not None:
                try:
                    final = history.final_result()
                    success_flag = history.is_successful()
                    for u in history.urls():
                        if u and u != "about:blank" and u not in urls:
                            urls.append(u)
                except Exception as e:
                    logger.debug("history read failed: %s", e)
            stopped = self._stop_requested or bool(
                agent is not None and getattr(getattr(agent, "state", None), "stopped", False)
            )

            if conn_msg and not error_msg:
                error_msg = conn_msg
                error_kind = "cdp_connect"
            if error_msg and not timed_out:
                status = "error"
                error_kind = error_kind or "agent_error"
            elif timed_out:
                status = "timeout"
                error_kind = "timeout"
            elif captcha_msg:
                status = "failed"
                error_kind = "captcha"
            elif stopped:
                status = "stopped"
                error_kind = "stopped"
            elif success_flag is True:
                status = "success"
            else:
                status = "failed"
            summary = final
            if error_msg and error_msg not in errors:
                errors.append(error_msg)
            return RunResult(
                run_id=run_id,
                task=task,
                status=status,
                success=True if status == "success" else (False if status == "failed" else None),
                final_result=final,
                steps=steps,
                step_count=len(steps),
                duration_s=round(time.monotonic() - t0, 3),
                cost_usd=round(cost_total, 6) if cost_seen else None,
                errors=errors,
                urls_visited=urls,
                blocked_actions=list(blocked),
                error_kind=error_kind,
            )
        finally:
            error_msg = error_msg or captcha_msg
            if error_msg:
                await self._emit(ErrorEvent(message=error_msg))
                await self._emit(StateEvent(state="error"))
            else:
                if summary:
                    await self._emit(SummaryEvent(text=summary))
                await self._emit(StateEvent(state="complete"))
            await self._emit(DoneEvent())


async def run_task(task: str, config: AgentConfig | None = None, *, sinks: Iterable[Any] = (),
                   approval: ApprovalCallback | None = None, start_url: str | None = None) -> RunResult:
    """Run one natural-language task in Chrome and return its :class:`RunResult`.

    Args:
        task: What the agent should do, in plain language.
        config: Model, browser and safety settings; ``AgentConfig.from_env()`` when omitted.
        sinks: Event sinks (``QueueSink``, ``JsonlTraceSink``, ``CallbackSink`` or your own).
        approval: Async callback asked before any gated purchase-like action; without
            one, gated actions are denied.
        start_url: Optional page to open before the agent starts.

    Never raises for run failures: errors (including a missing Chrome or provider
    problems) come back as ``status="error"`` with messages in ``RunResult.errors``.
    """
    return await BrowserAgent(config, sinks=sinks, approval=approval).run(task, start_url=start_url)


def run_task_sync(task: str, config: AgentConfig | None = None, *, sinks: Iterable[Any] = (),
                  approval: ApprovalCallback | None = None, start_url: str | None = None) -> RunResult:
    """Blocking wrapper around :func:`run_task` for scripts without an event loop."""
    return asyncio.run(run_task(task, config, sinks=sinks, approval=approval, start_url=start_url))
