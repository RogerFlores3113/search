from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from browser_use import Agent, ChatOllama
from browser_use.browser.session import BrowserSession

from agent.config import config

if TYPE_CHECKING:
    from agent.config import Settings

# Module-level constant: one run_id shared across all steps in a single process run.
RUN_ID = str(uuid.uuid4())

TRAINING_FILE = Path("training/runs.jsonl")


async def pre_flight_check(cfg: "Settings") -> None:
    """Validate Ollama daemon + model availability.

    Print actionable error and sys.exit(1) on failure.
    """
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
        sys.exit(1)

    # Base-name substring match: "qwen2.5vl" matches "qwen2.5vl:7b", "qwen2.5vl:latest", etc.
    model_base = cfg.ollama_model.split(":")[0]
    if not any(model_base in m for m in models):
        print(
            f"ERROR: Model '{cfg.ollama_model}' is not pulled.\n"
            f"  Pull it with: ollama pull {cfg.ollama_model}"
        )
        sys.exit(1)


async def log_step(agent) -> None:
    """on_step_end callback. Writes one JSONL record to training/runs.jsonl.

    Callback signature: async def log_step(agent: Agent) -> None
    Verified against installed browser_use 0.12.6 agent/service.py:
      AgentHookFunc = Callable[['Agent'], Awaitable[None]]
      agent.history (AgentHistoryList) is populated incrementally during run().
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
        "run_id": RUN_ID,
        "step_index": step_idx,
        "screenshot_b64": screenshot_b64,
        "action_type": action_type,
        "action_target": str(action_target),
        "action_value": str(action_value),
        "narration": f"Step {step_idx + 1}: {action_type}",
        "step_success": not history.has_errors(),
    }

    with open(TRAINING_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(f"[step {step_idx + 1}] {record['narration']}")


async def run_agent(task: str) -> None:
    """Pre-flight, build BrowserSession+ChatOllama+Agent, asyncio.wait_for(agent.run(...), timeout).

    Final: await browser.kill().
    """
    await pre_flight_check(config)

    browser = BrowserSession(channel="chrome", headless=False, keep_alive=False)
    try:
        llm = ChatOllama(model=config.ollama_model, ollama_options={"num_ctx": 32000})
        agent = Agent(task=task, llm=llm, browser_session=browser)

        try:
            history = await asyncio.wait_for(
                agent.run(max_steps=config.max_steps, on_step_end=log_step),
                timeout=config.session_timeout,
            )
            print(f"Done: {history.final_result()}")
        except asyncio.TimeoutError:
            print(f"Session timeout reached ({config.session_timeout}s). Stopping.")
    finally:
        await browser.kill()
