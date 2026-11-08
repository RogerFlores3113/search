"""MCP server exposing the agent as a single tool (stdio transport).

Requires the optional ``mcp`` extra: ``uv add "local-browser-agent[mcp] @ git+..."``.
"""
from __future__ import annotations

import asyncio
from typing import Any

from local_browser_agent.config import AgentConfig, SafetyPolicy
from local_browser_agent.runner import run_task

_locks: dict[int, asyncio.Lock] = {}


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lk = _locks.get(id(loop))
    if lk is None:
        lk = _locks[id(loop)] = asyncio.Lock()
    return lk


def public_config(cfg: AgentConfig) -> dict[str, Any]:
    """Config as a plain dict with all secrets removed."""
    d = cfg.model_dump(mode="json")
    d["model"]["api_key"] = "set" if cfg.model.api_key is not None else None
    d["safety"]["blocked_domains"] = sorted(cfg.safety.blocked_domains)
    return d


async def run_browser_task(
    task: str,
    start_url: str | None = None,
    max_steps: int | None = None,
    allowed_domains: list[str] | None = None,
) -> dict:
    """Run a natural-language task in a browser and return the RunResult as a dict.

    Only one task runs at a time; a concurrent call returns {"status": "error", "error": "busy..."}.
    """
    lock = _lock()
    if lock.locked():
        return {"status": "error", "success": None, "errors": ["busy: another browser task is already running"],
                "error": "busy: another browser task is already running"}
    async with lock:
        try:
            cfg = AgentConfig.from_env()
            if max_steps:
                cfg.max_steps = max_steps
            if allowed_domains:
                cfg.safety = SafetyPolicy(**{**cfg.safety.model_dump(), "allowed_domains": allowed_domains})
        except Exception as e:
            return {"status": "error", "success": None, "errors": [f"invalid configuration: {e}"],
                    "error": f"invalid configuration: {e}"}
        result = await run_task(task, cfg, start_url=start_url)
        return result.to_dict()


def get_agent_config() -> dict:
    """Return the effective agent configuration (API keys are never included)."""
    return public_config(AgentConfig.from_env())


def build_server() -> Any:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("local-browser-agent")
    server.tool()(run_browser_task)
    server.tool()(get_agent_config)
    return server


def serve() -> None:
    build_server().run(transport="stdio")
