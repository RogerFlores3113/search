"""MCP server exposing the agent as a single tool (stdio transport).

Requires the optional ``mcp`` extra: ``uv add "local-browser-agent[mcp] @ git+..."``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

try:  # optional extra; only needed to actually serve
    from mcp.types import CallToolResult, TextContent, ToolAnnotations
except ImportError:  # pragma: no cover
    CallToolResult = TextContent = ToolAnnotations = None  # type: ignore[assignment,misc]

from local_browser_agent.config import AgentConfig, SafetyPolicy
from local_browser_agent.runner import run_task
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


def restrict_domains(server: list[str] | None, requested: list[str]) -> list[str]:
    """Combine the server allowlist with a per-call one.

    Entries go through the same normalisation as ``SafetyPolicy.allowed_domains`` (plain
    hostname or ``*.hostname``; a bare ``*`` or ``*.com`` raises ``ValueError``). With no
    server allowlist the normalised call list is used. Otherwise only call domains that equal,
    or are subdomains of, a server domain survive; the call can narrow the server policy but
    never widen it.
    """
    req = [normalize_allowed_domain(r) for r in requested if str(r).strip()]
    if not server:
        return req
    srv = [_norm_domain(normalize_allowed_domain(s)) for s in server if s.strip()]
    return [r for r in req if any(_norm_domain(r) == s or _norm_domain(r).endswith("." + s) for s in srv)]


def _error(message: str) -> dict:
    return {"status": "error", "success": None, "errors": [message], "error": message}


async def _run(task: str, start_url: str | None, max_steps: int | None,
               allowed_domains: list[str] | None) -> dict:
    if not task or not task.strip():
        return _error("task must be a non-empty string")
    if max_steps is not None and not (1 <= max_steps <= MAX_STEPS_CAP):
        return _error(f"max_steps must be between 1 and {MAX_STEPS_CAP}")
    if allowed_domains is not None and not [d for d in allowed_domains if d.strip()]:
        return _error("allowed_domains must not be empty; omit it to use the server's policy")
    lock = _lock()
    if lock.locked():
        return _error("busy: another browser task is already running")
    async with lock:
        try:
            cfg = AgentConfig.from_env()
            if max_steps is not None:
                cfg.max_steps = max_steps
            if allowed_domains is not None:
                effective = restrict_domains(cfg.safety.allowed_domains, allowed_domains)
                if not effective:
                    return _error("none of the requested allowed_domains are permitted by this server's "
                                  "LBA_ALLOWED_DOMAINS policy; nothing was run")
                cfg.safety = SafetyPolicy(**{**cfg.safety.model_dump(), "allowed_domains": effective})
        except Exception as e:
            return _error(f"invalid configuration: {e}")
        # stdout carries the MCP JSON-RPC stream; send any stray print() from
        # browser-use (e.g. its pause banner) to stderr instead of corrupting it.
        with contextlib.redirect_stdout(sys.stderr):
            result = await run_task(task, cfg, start_url=start_url)
        return result.to_dict()


RUN_DESCRIPTION = (
    "Run ONE natural-language task in a real local Chrome browser (the user's own browser, visible by default) "
    "and return a RunResult: status (success|failed|error|timeout|stopped), success, final_result, steps, "
    "step_count, duration_s, cost_usd, errors, urls_visited, blocked_actions. "
    "Only one task runs at a time; a concurrent call fails immediately with a 'busy' error rather than queueing. "
    "Runs can take minutes. Safety gates always apply: banks, payment, government, medical and password-manager "
    "domains are blocked; purchase/checkout clicks are blocked and listed in blocked_actions; CAPTCHAs are never "
    "solved (the run fails with a human-verification error). If the server operator set LBA_ALLOWED_DOMAINS, "
    "allowed_domains can only narrow that list. Failures (anything but status 'success') are returned with "
    "isError=true; the RunResult is in structuredContent and the text content."
)


async def run_browser_task(
    task: Annotated[str, Field(min_length=1, description="What the browser agent should do, in plain language.")],
    start_url: Annotated[str | None, Field(description="Optional URL to open before the agent starts.")] = None,
    max_steps: Annotated[int | None, Field(ge=1, le=MAX_STEPS_CAP,
                                           description="Step budget for this run (server default if omitted).")] = None,
    allowed_domains: Annotated[list[str] | None, Field(
        min_length=1, description="Restrict navigation to these domains (and subdomains). Cannot widen the "
        "server's LBA_ALLOWED_DOMAINS. Omit for the server policy; an empty list is rejected.")] = None,
) -> CallToolResult:
    result = await _run(task, start_url, max_steps, allowed_domains)
    ok = result.get("status") == "success"
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, indent=2, default=str))],
        structuredContent=result,
        isError=not ok,
    )


def get_agent_config() -> dict:
    """Return the effective agent configuration (API keys are never included)."""
    return public_config(AgentConfig.from_env())


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("local-browser-agent")
    server.tool(description=RUN_DESCRIPTION, annotations=ToolAnnotations(
        title="Run browser task", readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        openWorldHint=True))(run_browser_task)
    server.tool(description="Return the server's effective agent configuration (provider, model, browser and "
                "safety settings). Secrets are never included: the API key is shown only as 'set', URL "
                "credentials and tokens are redacted.", annotations=ToolAnnotations(
        title="Show config", readOnlyHint=True, openWorldHint=False))(get_agent_config)
    return server


def serve(log_level: str = "warning") -> None:
    """Run the stdio server. stderr is quiet by default (only warnings and errors)."""
    from local_browser_agent.log import configure_logging

    configure_logging(log_level)
    build_server().run(transport="stdio")
