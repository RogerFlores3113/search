from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.config import Settings


async def pre_flight_check(config: "Settings") -> None:
    """Validate Ollama daemon + model availability.

    Print actionable error and sys.exit(1) on failure.
    """
    raise NotImplementedError("Wave 1: implement in plan 02")


async def log_step(agent) -> None:
    """on_step_end callback. Writes one JSONL record to training/runs.jsonl."""
    raise NotImplementedError("Wave 1: implement in plan 02")


async def run_agent(task: str) -> None:
    """Pre-flight, build BrowserSession+ChatOllama+Agent, asyncio.wait_for(agent.run(...), timeout).

    Final: await browser.kill().
    """
    raise NotImplementedError("Wave 1: implement in plan 02")
