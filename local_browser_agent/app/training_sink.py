"""Training-data sink: writes one JSONL record per step to ``training/runs.jsonl``.

App-owned (the library has no training concept). It consumes the library's
``StepCompletedEvent`` and keeps the exact record schema the LoRA converter expects.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from local_browser_agent.events import StepCompletedEvent

from local_browser_agent.app.paths import get_user_data_dir

TRAINING_FILE = get_user_data_dir() / "training" / "runs.jsonl"

# Only API providers populate thought fields (Ollama gets explicit nulls).
_API_PROVIDERS = ("anthropic", "openai")


def _write_jsonl(path: Path, record: dict) -> None:
    """Append a single JSONL record to path. Called via asyncio.to_thread."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def rewrite_jsonl_run_success(path: Path, run_id: str, run_success: bool) -> None:
    """Back-fill `run_success` into every record matching `run_id` (D-04).

    Synchronous, in-place rewrite. Callers wrap with asyncio.to_thread.
    Malformed JSONL lines are preserved verbatim. Missing file is a no-op.
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


def step_record(event: StepCompletedEvent, *, provider: str, model_name: str) -> dict:
    """Build the training record (the runs.jsonl schema) for one finished step."""
    api_provider = provider in _API_PROVIDERS
    action_type = event.action_type
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": event.run_id,
        "step_index": event.step - 1,
        "screenshot_b64": event.screenshot_b64 or "",
        "action_type": action_type,
        "action_target": str(event.target if event.target is not None else ""),
        "action_target_label": event.target_label,
        "action_value": str(event.value if event.value is not None else ""),
        "narration": f"Step {event.step}: {action_type}",
        "step_success": not event.run_has_errors,
        "step_duration_ms": event.duration_ms,
        "prompt_tokens": event.prompt_tokens,
        "completion_tokens": event.completion_tokens,
        "cost_usd": event.cost_usd,
        "model_thought": event.thinking if api_provider else None,
        "evaluation_previous_goal": event.evaluation_previous_goal if api_provider else None,
        "next_goal": event.next_goal if api_provider else None,
        "provider": provider,
        "model_name": model_name,
        "step_quality": "failed" if event.error else "clean",
    }


class TrainingSink:
    """Event sink: appends a training record for each ``StepCompletedEvent``."""

    wants_screenshots = False
    wants_step_events = True

    def __init__(self, provider: str, model_name: str) -> None:
        self.provider = provider.lower()
        self.model_name = model_name

    async def __call__(self, event: object) -> None:
        if not isinstance(event, StepCompletedEvent):
            return
        record = step_record(event, provider=self.provider, model_name=self.model_name)
        # TRAINING_FILE is looked up at call time so tests can redirect it.
        path = TRAINING_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_write_jsonl, path, record)
        print(f"[step {event.step}] {record['narration']}")


async def backfill_run_success(run_id: str, run_success: bool) -> None:
    """Back-fill run_success into this run's records. Never raises (D-04)."""
    try:
        await asyncio.to_thread(rewrite_jsonl_run_success, TRAINING_FILE, run_id, run_success)
    except Exception:
        pass
