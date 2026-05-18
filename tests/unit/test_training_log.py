"""Unit tests for log_step in agent/runner.py (RUN-03 JSONL schema contract).

All tests are xfail-by-design until Wave 1 (plan 02) implements log_step.
The nine field names here are the Nyquist contract — Wave 1 MUST satisfy them.
"""
from __future__ import annotations

import json
import types

import pytest


def _make_fake_agent():
    """Build a minimal fake Agent namespace with the attributes log_step reads."""
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "click", "action_target": "#btn", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],  # minimal base64 stub
        has_errors=lambda: False,
    )
    # state.last_result is required by the CAPTCHA detection branch in log_step
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(history=history, state=state)


async def test_log_step_writes_jsonl_line(training_dir):
    """log_step must write exactly one JSONL record with all nine D-09 schema fields."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    jsonl_file = training_dir / "runs.jsonl"
    assert jsonl_file.exists(), "training/runs.jsonl must be created by log_step"

    lines = jsonl_file.read_text().strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    for field in (
        "timestamp",
        "run_id",
        "step_index",
        "screenshot_b64",
        "action_type",
        "action_target",
        "action_value",
        "narration",
        "step_success",
    ):
        assert field in record, f"Missing field: {field}"


async def test_log_step_creates_training_dir(training_dir):
    """log_step must create the training/ directory if it does not exist."""
    import shutil

    from agent.runner import log_step

    shutil.rmtree(training_dir)
    assert not training_dir.exists()

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    assert training_dir.exists(), "log_step must create training/ dir if missing"
    assert (training_dir / "runs.jsonl").exists()


async def test_log_step_appends_not_overwrites(training_dir):
    """Calling log_step twice must produce exactly 2 JSONL lines (append, not overwrite)."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    jsonl_file = training_dir / "runs.jsonl"
    lines = jsonl_file.read_text().strip().splitlines()
    assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"
