"""MCP server exposing the agent as a single tool (stdio transport).

Requires the optional ``mcp`` extra: ``uv add "local-browser-agent[mcp] @ git+..."``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
import uuid
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

try:  # optional extra; only needed to actually serve
    from mcp.server.fastmcp import Context
    from mcp.types import CallToolResult, TextContent, ToolAnnotations
except ImportError:  # pragma: no cover
    CallToolResult = TextContent = ToolAnnotations = None  # type: ignore[assignment,misc]
    Context = Any  # type: ignore[assignment,misc]

from local_browser_agent.config import AgentConfig, SafetyPolicy
from local_browser_agent.log import format_validation_error
from local_browser_agent.runner import RunResult, run_task
from local_browser_agent.safety import normalize_allowed_domain

_locks: dict[int, asyncio.Lock] = {}


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lk = _locks.get(id(loop))
    if lk is None:
        lk = _locks[id(loop)] = asyncio.Lock()
    return lk


_REDACTED = "<redacted>"
MAX_STEPS_CAP = 200


def _redact_url(url: str | None) -> str | None:
    """Mask user:pass@ credentials and query-string values in a URL."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            netloc = f"{_REDACTED}@{netloc.rsplit('@', 1)[1]}"
        query = "&".join(f"{kv.split('=', 1)[0]}={_REDACTED}" if "=" in kv else kv for kv in parts.query.split("&")) if parts.query else ""
        return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
    except ValueError:
        return _REDACTED


def public_config(cfg: AgentConfig) -> dict[str, Any]:
    """Config as a plain dict with secrets removed (API key, URL credentials/tokens, ``extra`` values)."""
    d = cfg.model_dump(mode="json")
    d["model"]["api_key"] = "set" if cfg.model.api_key is not None else None
    d["model"]["base_url"] = _redact_url(d["model"].get("base_url"))
    d["model"]["extra"] = {k: _REDACTED for k in (d["model"].get("extra") or {})}
    d["browser"]["cdp_url"] = _redact_url(d["browser"].get("cdp_url"))
    d["safety"]["blocked_domains"] = sorted(cfg.safety.blocked_domains)
    return d


def _norm_domain(d: str) -> str:
    d = d.strip().lower()
    for prefix in ("*.", "."):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d


def _covered(call: str, server: list[str]) -> bool:
    """Whether the (normalised) call entry is no wider than some server entry.

    Mirrors browser-use's host matching (``_is_url_match``): ``*.d`` covers ``d`` and every
    subdomain; a plain ``d`` covers only the host ``d`` (and ``www.d``), not arbitrary
    subdomains. So a wildcard call entry is only allowed under a wildcard server entry.
    """
    c_wild, cd = call.startswith("*."), _norm_domain(call)
    for s in server:
        s_wild, sd = s.startswith("*."), _norm_domain(s)
        if s_wild:
            if cd == sd or cd.endswith("." + sd):
                return True
        elif not c_wild and cd in (sd, "www." + sd):
            return True
    return False


def restrict_domains(server: list[str] | None, requested: list[str]) -> list[str]:
    """Combine the server allowlist with a per-call one.

    Entries go through the same normalisation as ``SafetyPolicy.allowed_domains`` (plain
    hostname or ``*.hostname``; a bare ``*`` or ``*.com`` raises ``ValueError``). With no
    server allowlist the normalised call list is used. Otherwise a call entry survives only if
    the server entries already cover everything it would allow (see :func:`_covered`): the call
    can narrow the server policy but never widen it. In particular ``*.a.com`` does not survive
    a plain server ``a.com``, and a plain ``x.a.com`` needs a server ``*.a.com``.
    """
    req = list(dict.fromkeys(normalize_allowed_domain(r) for r in requested if str(r).strip()))
    if not server:
        return req
    srv = [normalize_allowed_domain(s) for s in server if s.strip()]
    return [r for r in req if _covered(r, srv)]


class StepRecordModel(BaseModel):
    index: int
    action_type: str = "unknown"
    target_label: str | None = None
    value: str | None = None
    url: str | None = None
    error: str | None = None
    duration_ms: int | None = None


class RunResultModel(BaseModel):
    """Mirrors :class:`local_browser_agent.runner.RunResult`; the tool's ``outputSchema``."""

    run_id: str
    task: str
    status: str = Field(description="success | failed | error | timeout | stopped")
    success: bool | None = None
    final_result: str | None = None
    steps: list[StepRecordModel] = Field(default_factory=list)
    step_count: int = 0
    duration_s: float = 0.0
    cost_usd: float | None = None
    errors: list[str] = Field(default_factory=list)
    urls_visited: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    error_kind: str | None = Field(
        default=None, description="machine-readable failure class (config, busy, invalid_argument, ...) or null")


class _ModelSection(BaseModel):
    """``model`` section of :class:`AgentConfigModel`; extra keys are tolerated so new settings never break it."""

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, description="'set' when a key is configured, never the key itself")
    base_url: str | None = Field(default=None, description="credentials and query values redacted")
    temperature: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict, description="provider options; values redacted")


class _BrowserSection(BaseModel):
    model_config = ConfigDict(extra="allow")

    headless: bool | None = None
    channel: str | None = None
    executable_path: str | None = None
    cdp_url: str | None = Field(default=None, description="credentials and query values redacted")
    user_data_dir: str | None = None
    window_width: int | None = None
    window_height: int | None = None
    llm_screenshot_width: int | None = None
    llm_screenshot_height: int | None = None
    keep_alive: bool | None = None
    allow_downloads: bool | None = None


class _SafetySection(BaseModel):
    model_config = ConfigDict(extra="allow")

    blocked_domains: list[str] | None = None
    allowed_domains: list[str] | None = None
    guardrail_prompt: str | None = None
    gate_commerce_clicks: bool | None = None
    commerce_patterns: list[str] | None = None
    allow_evaluate: bool | None = None
    allow_local_network: bool | None = None
    approval_timeout_s: float | None = None


class AgentConfigModel(BaseModel):
    """Output schema of ``get_agent_config`` (secrets removed). On failure ``error`` / ``error_kind`` are set."""

    model_config = ConfigDict(extra="allow")

    model: _ModelSection | None = None
    browser: _BrowserSection | None = None
    safety: _SafetySection | None = None
    max_steps: int | None = None
    timeout_s: float | None = None
    use_vision: bool | None = None
    use_judge: bool | None = None
    calculate_cost: bool | None = None
    on_captcha: str | None = None
    system_prompt_extension: str | None = None
    status: str | None = None
    error: str | None = None
    error_kind: str | None = None


def _error(message: str, kind: str, task: str = "") -> dict:
    """The one failure shape: a complete RunResult-shaped dict with status ``error``."""
    d = RunResult(run_id=str(uuid.uuid4()), task=task, status="error", success=None, errors=[message]).to_dict()
    d["error_kind"] = kind
    return d


def _as_result(d: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(d, indent=2, default=str))],
        structuredContent=d,
        isError=d.get("status") != "success",
    )


def _check_start_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
        ok = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        ok = False
    return None if ok else f"start_url must be an http(s):// URL with a host, got {_redact_url(url)!r}"


class _ProgressSink:
    """Event sink that turns the run's step events into MCP progress notifications."""

    wants_screenshots = False  # never trigger the screenshot loop for a progress feed

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._last: dict[int, str] = {}

    @staticmethod
    def _describe(ev: Any) -> str:
        what = getattr(ev, "action_type", None) or "step"
        target = getattr(ev, "target_label", None) or getattr(ev, "value", None) or getattr(ev, "url", None)
        text = f"{what}: {target}" if target else str(what)
        return _redact_url(text) if text.startswith(("http://", "https://")) else text[:120]

    async def __call__(self, event: Any) -> None:
        kind = getattr(event, "type", "")
        if kind == "action_detail":
            self._last[event.step] = self._describe(event)
        elif kind == "progress":
            msg = self._last.pop(event.step, None)
            await self.ctx.report_progress(progress=event.step, total=event.max_steps,
                                           message=f"Step {event.step}/{event.max_steps}" + (f": {msg}" if msg else ""))


def _progress_sink(ctx: Any) -> _ProgressSink | None:
    """A progress sink when the client asked for progress (sent a progressToken), else None."""
    if ctx is None:
        return None
    try:
        meta = ctx.request_context.meta
        token = getattr(meta, "progressToken", None) if meta else None
    except Exception:  # no request context (called outside a request)
        return None
    return _ProgressSink(ctx) if token is not None else None


async def _run(task: str, start_url: str | None, max_steps: int | None,
               allowed_domains: list[str] | None, ctx: Any = None) -> dict:
    def err(msg: str, kind: str) -> dict:
        return _error(msg, kind, task if isinstance(task, str) else "")

    if not isinstance(task, str) or not task.strip():
        return err("task must be a non-empty string", "invalid_argument")
    if max_steps is not None and not (1 <= max_steps <= MAX_STEPS_CAP):
        return err(f"max_steps must be between 1 and {MAX_STEPS_CAP}", "invalid_argument")
    if allowed_domains is not None and not [d for d in allowed_domains if d.strip()]:
        return err("allowed_domains must not be empty; omit it to use the server's policy", "invalid_argument")
    if start_url is not None and (msg := _check_start_url(start_url)):
        return err(msg, "invalid_argument")
    # All pure validation happens before the busy check, so a bad call is reported as such
    # (invalid_argument / config) even while another run is active.
    try:
        cfg = AgentConfig.from_env()
        if max_steps is not None:
            cfg.max_steps = max_steps
        if allowed_domains is not None:
            try:
                effective = restrict_domains(cfg.safety.allowed_domains, allowed_domains)
            except ValueError as e:  # e.g. "*.com": the caller's argument is bad, not the server config
                return err(f"invalid allowed_domains: {format_validation_error(e)}", "invalid_argument")
            if not effective:
                return err("none of the requested allowed_domains are permitted by this server's "
                           "LBA_ALLOWED_DOMAINS policy; nothing was run", "invalid_argument")
            cfg.safety = SafetyPolicy(**{**cfg.safety.model_dump(), "allowed_domains": effective})
    except Exception as e:  # ValueError / pydantic ValidationError
        return err(f"invalid configuration: {format_validation_error(e)}", "config")
    lock = _lock()
    if lock.locked():
        return err("busy: another browser task is already running", "busy")
    async with lock:
        try:
            # stdout carries the MCP JSON-RPC stream; send any stray print() from
            # browser-use (e.g. its pause banner) to stderr instead of corrupting it.
            with contextlib.redirect_stdout(sys.stderr):
                sink = _progress_sink(ctx)
                extra = {"sinks": [sink]} if sink is not None else {}
                result = await run_task(task, cfg, start_url=start_url, **extra)
        except Exception as e:  # run_task reports failures in the result; this is a last resort
            return err(f"internal error: {type(e).__name__}: {e}", "internal")
        d = result.to_dict()
        d.setdefault("error_kind", getattr(result, "error_kind", None))
        return d


_RUN_ARGS = frozenset({"task", "start_url", "max_steps", "allowed_domains"})

RUN_DESCRIPTION = (
    "Run ONE natural-language task in a real local Chrome browser (the user's own browser, visible by default) "
    "and return a RunResult: status (success|failed|error|timeout|stopped), success, final_result, steps, "
    "step_count, duration_s, cost_usd, errors, urls_visited, blocked_actions, error_kind. "
    "Only one task runs at a time; a concurrent call fails immediately with a 'busy' error rather than queueing. "
    "Runs can take minutes. Safety gates always apply: banks, payment, government, medical and password-manager "
    "domains are blocked; purchase/checkout clicks are blocked and listed in blocked_actions; CAPTCHAs are never "
    "solved (the run fails with a human-verification error). IP-address URLs, localhost and local network names are "
    "blocked unless the operator sets LBA_ALLOW_LOCAL_NETWORK=1; use a hostname instead of retrying. If the server operator set LBA_ALLOWED_DOMAINS, "
    "allowed_domains can only narrow that list. Every failure (anything but status 'success', including invalid "
    "arguments) is returned with isError=true in the same RunResult shape; errors raised before a run have "
    "status 'error' and an error_kind (config, busy, invalid_argument, ...). The RunResult is in "
    "structuredContent and the text content."
)

SERVER_INSTRUCTIONS = (
    "Drives the user's own local Chrome to complete one natural-language browser task.\n"
    "- run_browser_task(task, start_url?, max_steps?, allowed_domains?): runs the task and returns a RunResult "
    "(status, final_result, steps, errors, blocked_actions, error_kind). Runs can take minutes. Only ONE task "
    "runs at a time; a concurrent call returns error_kind 'busy' immediately, so wait and retry.\n"
    "- get_agent_config(): the effective configuration, secrets redacted.\n"
    "Safety gates always apply and cannot be lifted per call: bank, payment, government, medical and "
    "password-manager sites are blocked; purchase/checkout clicks are refused (see blocked_actions); CAPTCHAs "
    "are not solved. allowed_domains can only narrow the operator's LBA_ALLOWED_DOMAINS.\n"
    "Operator configuration comes from LBA_* environment variables: LBA_PROVIDER, LBA_MODEL, LBA_API_KEY, "
    "LBA_BASE_URL, LBA_HEADLESS, LBA_CDP_URL, LBA_MAX_STEPS, LBA_TIMEOUT_S, LBA_ALLOWED_DOMAINS, "
    "LBA_BLOCKED_DOMAINS (see docs/LIBRARY.md, Configuration)."
)


async def run_browser_task(
    task: Annotated[str, Field(min_length=1, description="What the browser agent should do, in plain language.")],
    start_url: Annotated[str | None, Field(
        description="Optional http(s) URL to open before the agent starts.")] = None,
    max_steps: Annotated[int | None, Field(ge=1, le=MAX_STEPS_CAP,
                                           description="Step budget for this run (server default if omitted).")] = None,
    allowed_domains: Annotated[list[str] | None, Field(
        min_length=1, description="Restrict navigation to these domains (and subdomains). Cannot widen the "
        "server's LBA_ALLOWED_DOMAINS. Omit for the server policy; an empty list is rejected.")] = None,
    ctx: Context = None,  # type: ignore[assignment]  # injected by FastMCP; not part of the input schema
) -> Annotated[CallToolResult, RunResultModel]:
    return _as_result(await _run(task, start_url, max_steps, allowed_domains, ctx))


def get_agent_config() -> Annotated[CallToolResult, AgentConfigModel]:
    """Return the effective agent configuration (API keys are never included)."""
    try:
        d = public_config(AgentConfig.from_env())
        is_error = False
    except Exception as e:
        d = {"status": "error", "error_kind": "config",
             "error": f"invalid configuration: {format_validation_error(e)}"}
        is_error = True
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(d, indent=2, default=str))],
                          structuredContent=d, isError=is_error)


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from pydantic import ValidationError

    class _Server(FastMCP):
        async def call_tool(self, name: str, arguments: dict[str, Any]):  # type: ignore[override]
            if name == "run_browser_task" and isinstance(arguments, dict):
                unknown = sorted(set(arguments) - _RUN_ARGS)
                if unknown:
                    task = arguments.get("task")
                    return _as_result(_error(
                        f"unknown argument(s): {', '.join(map(str, unknown))}; "
                        f"accepted: {', '.join(sorted(_RUN_ARGS))}", "invalid_argument",
                        task if isinstance(task, str) else ""))
            elif name == "get_agent_config" and arguments:
                d = {"status": "error", "error_kind": "invalid_argument",
                     "error": f"unknown argument(s): {', '.join(sorted(map(str, arguments)))}; "
                              "get_agent_config takes no arguments"}
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(d, indent=2))],
                                      structuredContent=d, isError=True)
            try:
                return await super().call_tool(name, arguments)
            except ToolError as e:
                # Schema violations (max_steps=0, allowed_domains=[], ...) come back in the same
                # RunResult envelope as every other failure instead of a bare text error.
                cause = e.__cause__
                if name == "run_browser_task" and isinstance(cause, ValidationError):
                    task = arguments.get("task") if isinstance(arguments, dict) else None
                    return _as_result(_error(format_validation_error(cause), "invalid_argument",
                                             task if isinstance(task, str) else ""))
                raise

    # The mcp library warns "Tool 'x' not listed, no validation will be performed" for unknown tool names.
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.ERROR)
    server = _Server("local-browser-agent", instructions=SERVER_INSTRUCTIONS)
    server.tool(description=RUN_DESCRIPTION, annotations=ToolAnnotations(
        title="Run browser task", readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        openWorldHint=True), structured_output=True)(run_browser_task)
    server.tool(description="Return the server's effective agent configuration (provider, model, browser and "
                "safety settings). Secrets are never included: the API key is shown only as 'set', URL "
                "credentials and tokens are redacted.", annotations=ToolAnnotations(
        title="Show config", readOnlyHint=True, openWorldHint=False), structured_output=True)(get_agent_config)
    for t in server._tool_manager.list_tools():  # advertise that unknown keys are rejected
        t.parameters["additionalProperties"] = False
    return server


def serve(log_level: str = "warning", *, third_party: str | None = None) -> int:
    """Run the stdio server; returns an exit code (2 on bad configuration or a missing ``mcp`` extra).

    stderr is quiet by default (only warnings and errors). The ``LBA_*`` configuration is validated once
    here, so a bad value fails at startup instead of on every call.
    """
    from local_browser_agent.log import configure_logging

    configure_logging(log_level, third_party=third_party)
    try:
        AgentConfig.from_env()
    except Exception as e:
        from local_browser_agent.cli import _config_problems

        for problem in _config_problems(e):
            print(f"lba mcp: error: invalid configuration: {problem}", file=sys.stderr)
        return 2
    try:
        server = build_server()
    except ImportError as e:
        print(f"lba mcp: error: the MCP server needs the 'mcp' extra ({e}). "
              "Install with: pip install 'local-browser-agent[mcp]'", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0
