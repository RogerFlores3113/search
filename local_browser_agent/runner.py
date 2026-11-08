"""BrowserAgent: the importable agent loop."""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import logging
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from browser_use import Agent

from local_browser_agent.browser import build_browser_session
from local_browser_agent.config import AgentConfig
from local_browser_agent.events import (
    ActionDetailEvent,
    DoneEvent,
    ErrorEvent,
    ModelInfoEvent,
    ProgressEvent,
    ScreenshotEvent,
    StateEvent,
    SummaryEvent,
    ThoughtEvent,
    TokenEvent,
)
from local_browser_agent.models import build_llm, resolve_model_name
from local_browser_agent.safety import ActionRequest, ApprovalCallback, GuardedTools  # noqa: F401

logger = logging.getLogger("local_browser_agent")

SCREENSHOT_INTERVAL_S = 0.5
_SCREENSHOT_BACKOFF_CAP_S = 4.0
_SCREENSHOT_TIMEOUT_S = 3.0
_LABEL_MAX_LEN = 80
_LABEL_TAG_FALLBACK = frozenset({"button", "a", "input", "textarea", "select"})


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


async def _screenshot_loop(browser: Any, emit) -> None:
    """Emit a JPEG ScreenshotEvent every ~0.5s with exponential back-off on failure.

    CancelledError is deliberately not caught so teardown can cancel it before
    the browser is killed.
    """
    failures = 0
    while True:
        try:
            data = await asyncio.wait_for(
                browser.take_screenshot(format="jpeg", quality=75), timeout=_SCREENSHOT_TIMEOUT_S
            )
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
    """

    def __init__(self, config: AgentConfig | None = None, *, sinks: Iterable[Any] = (),
                 approval: ApprovalCallback | None = None) -> None:
        self.config = config or AgentConfig()
        self.sinks = list(sinks)
        self.approval = approval
        self._agent: Any = None
        self._running = False
        self._stop_requested = False
        self._bg: set[asyncio.Task] = set()

    # ---- control -------------------------------------------------------
    def _fire(self, event: Any) -> None:
        try:
            task = asyncio.get_running_loop().create_task(self._emit(event))
        except RuntimeError:
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def pause(self) -> None:
        if self._agent is not None:
            self._agent.pause()
            self._fire(StateEvent(state="paused"))

    def resume(self) -> None:
        if self._agent is not None:
            self._agent.resume()
            self._fire(StateEvent(state="running"))

    def stop(self) -> None:
        self._stop_requested = True
        if self._agent is not None:
            self._agent.stop()

    # ---- events --------------------------------------------------------
    async def _emit(self, event: Any) -> None:
        for sink in self.sinks:
            try:
                await sink(event)
            except Exception as e:  # a failing sink must never crash a run
                logger.warning("event sink %r failed: %s", sink, e)

    def _wants_screenshots(self) -> bool:
        return any(getattr(s, "wants_screenshots", True) for s in self.sinks)

    # ---- run -----------------------------------------------------------
    async def run(self, task: str, start_url: str | None = None) -> RunResult:
        if self._running:
            raise RuntimeError("BrowserAgent is already running a task; use one instance per concurrent run")
        self._running = True
        self._stop_requested = False
        try:
            return await self._run(task, start_url)
        finally:
            self._running = False
            self._agent = None

    async def _run(self, task: str, start_url: str | None) -> RunResult:
        cfg = self.config
        provider = cfg.model.provider.lower()
        run_id = str(uuid.uuid4())
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
        browser = None
        screenshot_task = None
        agent = None

        try:
            model_name = resolve_model_name(cfg.model)
        except ValueError:
            model_name = cfg.model.model or ""

        await self._emit(StateEvent(state="running"))
        await self._emit(ModelInfoEvent(provider=provider, model_name=model_name))

        async def _pre_step(browser_state, agent_output, step_num: int) -> None:
            await self._emit(ThoughtEvent(
                step=step_num,
                thinking=agent_output.thinking or None,
                evaluation_previous_goal=agent_output.evaluation_previous_goal or None,
                next_goal=agent_output.next_goal or None,
                memory=agent_output.memory or None,
            ))

        async def _on_step_end(agent_instance) -> None:
            nonlocal step_start, cost_total, cost_seen, usage_seen
            duration_ms = int((time.monotonic() - step_start) * 1000)
            hist = agent_instance.history
            idx = hist.number_of_steps()  # 1-indexed
            actions = hist.model_actions()
            last = actions[-1] if actions else {}
            action_type = next((k for k in last if k != "interacted_element"), "unknown") if last else "unknown"
            inner = last.get(action_type) if isinstance(last.get(action_type), dict) else {}
            target = str(inner["index"]) if "index" in inner else None
            value = inner.get("text") or inner.get("query") or inner.get("keys") or None
            url = inner.get("url") or None
            label = extract_target_label(last.get("interacted_element")) if last else None
            step_error = None
            for r in (getattr(agent_instance.state, "last_result", None) or []):
                if getattr(r, "error", None):
                    step_error = r.error
                    break
            if step_error:
                errors.append(step_error)
            steps.append(StepRecord(index=idx, action_type=action_type, target_label=label,
                                    value=str(value) if value is not None else None,
                                    url=url, error=step_error, duration_ms=duration_ms))

            tok = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None}
            if cfg.calculate_cost and provider != "ollama":
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
            step_start = time.monotonic()

        try:
            try:
                llm = build_llm(cfg.model)
                browser = build_browser_session(cfg.browser, cfg.safety)
                tools = GuardedTools(
                    patterns=cfg.safety.commerce_patterns,
                    gate_commerce_clicks=cfg.safety.gate_commerce_clicks,
                    approval=self.approval,
                    blocked_log=blocked,
                )
                parts = [p for p in (cfg.system_prompt_extension, cfg.safety.guardrail_prompt) if p]
                kwargs: dict[str, Any] = dict(
                    task=task,
                    llm=llm,
                    browser_session=browser,
                    tools=tools,
                    extend_system_message="\n\n".join(parts) or None,
                    use_vision=cfg.use_vision,
                    use_judge=cfg.use_judge,
                    calculate_cost=cfg.calculate_cost,
                    register_new_step_callback=_pre_step,
                )
                if start_url:
                    kwargs["initial_actions"] = [{"navigate": {"url": start_url, "new_tab": False}}]
                agent = Agent(**kwargs)
                self._agent = agent
                if self._stop_requested:
                    agent.stop()
                if self.sinks and self._wants_screenshots():
                    screenshot_task = asyncio.create_task(_screenshot_loop(browser, self._emit))
                try:
                    history = await asyncio.wait_for(
                        agent.run(max_steps=cfg.max_steps, on_step_end=_on_step_end),
                        timeout=cfg.timeout_s,
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    error_msg = f"Run timed out after {cfg.timeout_s:g}s"
                    history = getattr(agent, "history", None)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}" if str(e) == "" else str(e)
                logger.warning("run %s failed: %s", run_id, error_msg)
                if agent is not None:
                    history = getattr(agent, "history", None)
            finally:
                # Cancel the screenshot loop BEFORE tearing down the browser.
                if screenshot_task is not None:
                    screenshot_task.cancel()
                    await asyncio.gather(screenshot_task, return_exceptions=True)
                if browser is not None:
                    try:
                        if cfg.browser.keep_alive or cfg.browser.cdp_url:
                            await browser.stop()  # leave a user-owned / kept-alive browser running
                        else:
                            await browser.kill()
                    except Exception as e:
                        logger.debug("browser teardown failed: %s", e)

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

            if error_msg and not timed_out:
                status = "error"
            elif timed_out:
                status = "timeout"
            elif stopped:
                status = "stopped"
            elif success_flag is True:
                status = "success"
            else:
                status = "failed"
            summary = final
            if error_msg:
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
            )
        finally:
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
    return await BrowserAgent(config, sinks=sinks, approval=approval).run(task, start_url=start_url)


def run_task_sync(task: str, config: AgentConfig | None = None, *, sinks: Iterable[Any] = (),
                  approval: ApprovalCallback | None = None, start_url: str | None = None) -> RunResult:
    return asyncio.run(run_task(task, config, sinks=sinks, approval=approval, start_url=start_url))
