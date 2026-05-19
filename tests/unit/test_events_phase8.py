"""Phase 8 RED test suite: JSONL training data enrichment, run_success back-fill,
step_quality classification, converter quality gate + CLI, and training scaffold
guardrails.

All tests in this file are RED (failing) until Plan 02 wires:
  - agent/runner.py log_step() to accept duration_ms and emit enriched fields
  - agent/runner.py _rewrite_jsonl_run_success() helper for run-completion back-fill
  - training/converter.py CLI + quality gate + image extraction
  - training/train_nvidia.py VRAM detection + QLoRA + main()
  - training/train_apple.py Apple Silicon platform check + main()

Requirements covered:
  - TRAIN-01: enriched JSONL schema (19 keys)
  - TRAIN-02: provider gate (only anthropic/openai populate token + thought fields)
  - TRAIN-03: run_success back-fill + step_quality per-step classification
  - TRAIN-04: converter quality gate + CLI shape + image extraction + format adapters
  - TRAIN-05: train_nvidia QLoRA auto-quantization below 16GB
  - TRAIN-06: train_apple non-darwin friendly error
  - CR-01: log_step must NOT shadow `history` binding; must use `token_thistory`
  - CR-02: log_step must use `next((k ... if k != "interacted_element"), "unknown")`

Phase 8 boundary: tests target signatures/behaviors that do not yet exist on
the current codebase. The new file MUST collect cleanly (no ImportError) and
fail on assertion or attribute lookup — never on collection. Heavy import
guards (torch / unsloth / mlx_vlm) are installed via sys.modules stubs at
module import time so collection works on machines without those packages.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import io
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.runner


# ---------------------------------------------------------------------------
# sys.modules stubs for heavy training-time deps
# ---------------------------------------------------------------------------
# train_nvidia.py imports torch and unsloth; train_apple.py imports mlx_vlm.
# We stub these BEFORE the test suite touches the training package so that
# `import training.train_nvidia` / `import training.train_apple` succeed on a
# CI box that does not have GPU-side packages installed. Plan 02's actual
# modules MUST defer heavy imports (function-scope or try/except ImportError)
# so collection works even with these stubs in place.

for _heavy in ("torch", "torch.cuda", "unsloth", "mlx_vlm", "mlx", "mlx.core"):
    if _heavy not in sys.modules:
        sys.modules[_heavy] = types.ModuleType(_heavy)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_fake_agent(
    provider_supports_tokens: bool = True,
    has_error: bool = False,
    thoughts: dict | None = None,
    model_actions=None,
    number_of_steps: int = 1,
):
    """Return a fake agent shaped like browser_use's Agent — patterned after
    tests/unit/test_events_phase7.py::_make_fake_agent_history but extended with
    last_result, token usage_history, and a calculate_cost stub.
    """
    if model_actions is None:
        model_actions = [{"click_element": {"index": 5}, "interacted_element": None}]

    # token_cost_service.usage_history entry shaped like browser_use's
    # TokenCostService records (model + usage with prompt_tokens / completion_tokens).
    usage_entry = types.SimpleNamespace(
        model="claude-sonnet-4-5",
        usage=types.SimpleNamespace(prompt_tokens=123, completion_tokens=45),
    )
    cost_result = types.SimpleNamespace(total_cost=0.000123)
    token_cost_service = types.SimpleNamespace(
        usage_history=[usage_entry] if provider_supports_tokens else [],
        calculate_cost=AsyncMock(return_value=cost_result),
    )

    err_value = "ElementNotFound" if has_error else None
    state = types.SimpleNamespace(
        last_result=[types.SimpleNamespace(error=err_value)],
        stopped=False,
    )

    history = types.SimpleNamespace(
        number_of_steps=lambda: number_of_steps,
        model_actions=lambda: model_actions,
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: has_error,
    )

    return types.SimpleNamespace(
        history=history,
        state=state,
        token_cost_service=token_cost_service,
        # Plan 02 may attach _thoughts to the agent OR to the run_agent closure.
        # Tests that need to verify thought-field injection patch agent.runner
        # internals directly, so we expose an attribute for completeness.
        _thoughts=thoughts or {},
        pause=MagicMock(),
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ===========================================================================
# TRAIN-01: enriched JSONL schema (19 keys)
# ===========================================================================

PHASE8_REQUIRED_KEYS = {
    # Phase 5/6/7 fields:
    "timestamp", "run_id", "step_index", "screenshot_b64",
    "action_type", "action_target", "action_value", "narration", "step_success",
    # Phase 8 additions:
    "step_duration_ms",
    "prompt_tokens", "completion_tokens", "cost_usd",
    "model_thought", "evaluation_previous_goal", "next_goal",
    "provider", "model_name", "step_quality",
    # Option B addition: human-readable element label for the LoRA corpus.
    "action_target_label",
}


async def test_jsonl_enriched_fields_anthropic(training_dir, monkeypatch):
    """TRAIN-01: log_step writes all 19 enriched fields for an anthropic run."""
    from agent.runner import log_step

    # Provide a thoughts accumulator at the module level so log_step can find it.
    # Plan 02 is free to attach it to the agent OR to a module-level dict — tests
    # here patch the most-likely module-level binding name.
    fake_agent = _make_fake_agent()
    monkeypatch.setattr(
        agent.runner, "_thoughts", {1: {
            "thinking": "I should click the search box",
            "evaluation_previous_goal": "Previous goal succeeded",
            "next_goal": "Type the query",
        }}, raising=False,
    )
    fake_agent._thoughts = {1: {
        "thinking": "I should click the search box",
        "evaluation_previous_goal": "Previous goal succeeded",
        "next_goal": "Type the query",
    }}

    await log_step(fake_agent, run_id="r1", provider="anthropic", duration_ms=1234, thoughts=fake_agent._thoughts)

    records = _read_jsonl(training_dir / "runs.jsonl")
    assert len(records) == 1, f"Expected 1 JSONL record; got {len(records)}"

    record = records[0]
    missing = PHASE8_REQUIRED_KEYS - set(record.keys())
    assert not missing, f"JSONL record missing Phase 8 keys: {missing}"

    assert record["step_duration_ms"] == 1234
    assert isinstance(record["prompt_tokens"], int)
    assert isinstance(record["completion_tokens"], int)
    assert isinstance(record["cost_usd"], float)
    assert isinstance(record["model_thought"], str) and record["model_thought"]
    assert isinstance(record["evaluation_previous_goal"], str)
    assert isinstance(record["next_goal"], str)
    assert record["provider"] == "anthropic"
    assert isinstance(record["model_name"], str) and record["model_name"]
    assert record["step_quality"] in {"clean", "partial", "failed"}


def test_log_step_signature_includes_duration_ms():
    """TRAIN-01: log_step exposes duration_ms as a keyword-only parameter."""
    sig = inspect.signature(agent.runner.log_step)
    assert "duration_ms" in sig.parameters, (
        f"log_step must accept duration_ms; current params: {list(sig.parameters)}"
    )
    param = sig.parameters["duration_ms"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        f"duration_ms must be keyword-only; got kind={param.kind}"
    )


# ===========================================================================
# TRAIN-02: provider gate
# ===========================================================================

async def test_provider_gate_ollama_nulls_token_and_thought(training_dir, monkeypatch):
    """TRAIN-02: when provider is not anthropic/openai, all 6 gated fields are None."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    # Even if thoughts are present, ollama path must null them out
    fake_agent._thoughts = {1: {"thinking": "x", "evaluation_previous_goal": "y", "next_goal": "z"}}
    monkeypatch.setattr(agent.runner, "_thoughts", fake_agent._thoughts, raising=False)

    await log_step(fake_agent, run_id="rO", provider="ollama", duration_ms=10)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    for gated in (
        "prompt_tokens", "completion_tokens", "cost_usd",
        "model_thought", "evaluation_previous_goal", "next_goal",
    ):
        assert record[gated] is None, (
            f"Provider gate failed: '{gated}' must be None for ollama; got {record[gated]!r}"
        )


async def test_provider_gate_openai_populates_fields(training_dir, monkeypatch):
    """TRAIN-02: openai provider populates all six gated fields."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    fake_agent._thoughts = {1: {
        "thinking": "openai thought",
        "evaluation_previous_goal": "ok",
        "next_goal": "continue",
    }}
    monkeypatch.setattr(agent.runner, "_thoughts", fake_agent._thoughts, raising=False)

    await log_step(fake_agent, run_id="rOA", provider="openai", duration_ms=100, thoughts=fake_agent._thoughts)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    for gated in (
        "prompt_tokens", "completion_tokens", "cost_usd",
        "model_thought", "evaluation_previous_goal", "next_goal",
    ):
        assert record[gated] is not None, (
            f"Provider gate failed: '{gated}' must be populated for openai"
        )


async def test_provider_gate_anthropic_canonical_lower(training_dir, monkeypatch):
    """TRAIN-02: provider param is canonical lower-case; literal 'anthropic' populates."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    fake_agent._thoughts = {1: {"thinking": "t", "evaluation_previous_goal": "e", "next_goal": "n"}}
    monkeypatch.setattr(agent.runner, "_thoughts", fake_agent._thoughts, raising=False)

    await log_step(fake_agent, run_id="rA2", provider="anthropic", duration_ms=50)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["prompt_tokens"] is not None
    assert record["cost_usd"] is not None


# ===========================================================================
# TRAIN-03: run_success back-fill + step_quality
# ===========================================================================

def test_rewrite_jsonl_run_success_adds_field_to_all_matching_records(tmp_path):
    """TRAIN-03: _rewrite_jsonl_run_success annotates every record matching run_id."""
    path = tmp_path / "runs.jsonl"
    path.write_text(
        json.dumps({"run_id": "rA", "step_index": 0}) + "\n" +
        json.dumps({"run_id": "rA", "step_index": 1}) + "\n" +
        json.dumps({"run_id": "rB", "step_index": 0}) + "\n"
    )

    agent.runner._rewrite_jsonl_run_success(path, "rA", True)  # type: ignore[attr-defined]

    records = _read_jsonl(path)
    assert records[0]["run_success"] is True
    assert records[1]["run_success"] is True
    # rB record is unrelated — must be untouched
    assert records[2].get("run_success") is None or "run_success" not in records[2]


def test_rewrite_jsonl_run_success_writes_false_for_failed_run(tmp_path):
    """TRAIN-03: rewrite writes the literal False for failed runs."""
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({"run_id": "rX", "step_index": 0}) + "\n")

    agent.runner._rewrite_jsonl_run_success(path, "rX", False)  # type: ignore[attr-defined]

    record = _read_jsonl(path)[0]
    assert record["run_success"] is False


def test_rewrite_jsonl_run_success_preserves_malformed_lines(tmp_path):
    """TRAIN-03: malformed JSONL lines are preserved verbatim; valid lines are annotated."""
    path = tmp_path / "runs.jsonl"
    path.write_text(
        "not json at all\n" +
        json.dumps({"run_id": "rM", "step_index": 0}) + "\n"
    )

    agent.runner._rewrite_jsonl_run_success(path, "rM", True)  # type: ignore[attr-defined]

    raw = path.read_text().splitlines()
    assert raw[0] == "not json at all", "malformed line must be preserved verbatim"
    valid = json.loads(raw[1])
    assert valid["run_success"] is True


def test_rewrite_jsonl_run_success_idempotent(tmp_path):
    """TRAIN-03: calling rewrite twice produces the same final state as one call."""
    path = tmp_path / "runs.jsonl"
    path.write_text(json.dumps({"run_id": "rI", "step_index": 0}) + "\n")

    agent.runner._rewrite_jsonl_run_success(path, "rI", True)  # type: ignore[attr-defined]
    after_first = path.read_text()
    agent.runner._rewrite_jsonl_run_success(path, "rI", True)  # type: ignore[attr-defined]
    after_second = path.read_text()
    assert after_first == after_second, "rewrite must be idempotent"


def test_rewrite_jsonl_run_success_missing_file_noop(tmp_path):
    """TRAIN-03: rewrite against a non-existent path returns silently (no exception)."""
    missing = tmp_path / "does-not-exist.jsonl"
    # Must not raise
    agent.runner._rewrite_jsonl_run_success(missing, "r0", True)  # type: ignore[attr-defined]


async def test_step_quality_clean_when_no_errors(training_dir, monkeypatch):
    """TRAIN-03: step_quality is 'clean' when last_result has no errors."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent(has_error=False)
    monkeypatch.setattr(agent.runner, "_thoughts", {}, raising=False)

    await log_step(fake_agent, run_id="rQC", provider="ollama", duration_ms=10)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["step_quality"] == "clean"


async def test_step_quality_failed_when_error_present(training_dir, monkeypatch):
    """TRAIN-03: step_quality is 'failed' when any last_result.error is non-None."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent(has_error=True)
    monkeypatch.setattr(agent.runner, "_thoughts", {}, raising=False)

    await log_step(fake_agent, run_id="rQF", provider="ollama", duration_ms=10)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["step_quality"] == "failed"


async def test_step_quality_per_step_not_cumulative(training_dir, monkeypatch):
    """TRAIN-03 / Pitfall 2: step_quality reflects the current step's last_result,
    NOT the cumulative history.has_errors() (which is True for the run as a whole).
    """
    from agent.runner import log_step

    fake_agent = _make_fake_agent(has_error=False)
    # Cumulative history says there WERE errors, but the current step's
    # last_result is clean — per-step semantics win.
    fake_agent.history.has_errors = lambda: True
    fake_agent.state.last_result = [types.SimpleNamespace(error=None)]
    monkeypatch.setattr(agent.runner, "_thoughts", {}, raising=False)

    await log_step(fake_agent, run_id="rQP", provider="ollama", duration_ms=10)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["step_quality"] == "clean", (
        "step_quality must be derived per-step from last_result, not from cumulative has_errors()"
    )


async def test_step_quality_is_valid_literal(training_dir, monkeypatch):
    """TRAIN-03: step_quality is always in the {clean, partial, failed} set."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    monkeypatch.setattr(agent.runner, "_thoughts", {}, raising=False)

    await log_step(fake_agent, run_id="rQV", provider="ollama", duration_ms=10)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["step_quality"] in {"clean", "partial", "failed"}


async def test_thoughts_accumulator_key_alignment(training_dir, monkeypatch):
    """TRAIN-03 / Pitfall 1: thought lookup uses step_idx + 1 (1-indexed key)
    so that _pre_step's step_num=1 is found by _log_step at step_idx=0.
    """
    from agent.runner import log_step

    fake_agent = _make_fake_agent(number_of_steps=1)  # step_idx == 0
    # _thoughts is keyed 1-indexed
    captured_thoughts = {1: {
        "thinking": "key-1 thought",
        "evaluation_previous_goal": "key-1 eval",
        "next_goal": "key-1 next",
    }}
    fake_agent._thoughts = captured_thoughts
    monkeypatch.setattr(agent.runner, "_thoughts", captured_thoughts, raising=False)

    await log_step(fake_agent, run_id="rT", provider="anthropic", duration_ms=10, thoughts=captured_thoughts)

    record = _read_jsonl(training_dir / "runs.jsonl")[0]
    assert record["model_thought"] == "key-1 thought", (
        f"step_idx+1 lookup off-by-one: expected 'key-1 thought', got {record['model_thought']!r}"
    )


# ===========================================================================
# TRAIN-04: converter
# ===========================================================================

def test_converter_module_importable():
    """TRAIN-04: training.converter is importable (training/__init__.py + module exists)."""
    import training.converter  # noqa: F401


def test_converter_cli_help_lists_flags():
    """TRAIN-04: python -m training.converter --help exposes the documented flags."""
    result = subprocess.run(
        [sys.executable, "-m", "training.converter", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"--help must exit 0; stderr={result.stderr}"
    for flag in ("--input", "--output", "--format", "--min-steps"):
        assert flag in result.stdout, f"--help must mention {flag}; got:\n{result.stdout}"


def _make_runs_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _make_b64_png_1x1() -> str:
    # 1x1 transparent PNG (smallest valid PNG)
    raw = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c6300010000000500010d0a2db40000000049454e44"
        "ae426082"
    )
    return base64.b64encode(raw).decode()


def _build_runs_record(
    *,
    run_id: str = "r1",
    step_index: int = 0,
    run_success: bool = True,
    step_quality: str = "clean",
    model_thought: str | None = "thought",
    action_type: str = "click",
    action_target: str = "5",
    action_value: str = "",
    screenshot_b64: str | None = None,
    task: str = "Find a 2BR in Brooklyn",
) -> dict:
    return {
        "timestamp": "2026-05-18T00:00:00Z",
        "run_id": run_id,
        "step_index": step_index,
        "screenshot_b64": screenshot_b64 if screenshot_b64 is not None else _make_b64_png_1x1(),
        "action_type": action_type,
        "action_target": action_target,
        "action_value": action_value,
        "narration": f"Step {step_index + 1}: {action_type}",
        "step_success": True,
        "step_duration_ms": 100,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_usd": 0.0001,
        "model_thought": model_thought,
        "evaluation_previous_goal": "ok",
        "next_goal": "next",
        "provider": "anthropic",
        "model_name": "claude-sonnet-4-5",
        "step_quality": step_quality,
        "run_success": run_success,
        "task": task,
    }


def _run_converter(input_path: Path, output_path: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "training.converter",
         "--input", str(input_path),
         "--output", str(output_path),
         *extra_args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_converter_filters_failed_runs(tmp_path):
    """TRAIN-04 (D-10): records with run_success=False are dropped."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rA", step_index=0, run_success=True, step_quality="clean"),
        _build_runs_record(run_id="rA", step_index=1, run_success=True, step_quality="clean"),
        _build_runs_record(run_id="rA", step_index=2, run_success=True, step_quality="clean"),
        _build_runs_record(run_id="rB", step_index=0, run_success=False, step_quality="clean"),
        _build_runs_record(run_id="rB", step_index=1, run_success=False, step_quality="clean"),
        _build_runs_record(run_id="rB", step_index=2, run_success=False, step_quality="clean"),
    ])

    result = _run_converter(input_path, output_path, "--image-dir", str(image_dir), "--min-steps", "1")
    assert result.returncode == 0, f"converter must exit 0; stderr={result.stderr}"

    out = _read_jsonl(output_path)
    # Only run rA (3 steps, all clean, run_success=True) should pass the gate
    assert len(out) == 3, f"Expected 3 records (rA only); got {len(out)}"


def test_converter_filters_failed_steps(tmp_path):
    """TRAIN-04 (D-10): records with step_quality='failed' are dropped even if run succeeded."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rA", step_index=0, run_success=True, step_quality="clean"),
        _build_runs_record(run_id="rA", step_index=1, run_success=True, step_quality="failed"),
        _build_runs_record(run_id="rA", step_index=2, run_success=True, step_quality="clean"),
    ])

    result = _run_converter(input_path, output_path, "--image-dir", str(image_dir), "--min-steps", "1")
    assert result.returncode == 0, f"converter must exit 0; stderr={result.stderr}"

    out = _read_jsonl(output_path)
    assert len(out) == 2, f"failed step must be filtered; got {len(out)} records"


def test_converter_emits_unsloth_format(tmp_path):
    """TRAIN-04: --format=unsloth emits the unsloth conversation shape."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rU", step_index=i) for i in range(3)
    ])

    result = _run_converter(
        input_path, output_path,
        "--format", "unsloth",
        "--image-dir", str(image_dir),
        "--min-steps", "1",
    )
    assert result.returncode == 0, f"converter failed: {result.stderr}"

    records = _read_jsonl(output_path)
    assert len(records) >= 1
    rec = records[0]
    assert "messages" in rec, f"unsloth output must have 'messages' key; got keys={list(rec)}"
    assert "images" in rec, "unsloth output must include 'images' list"
    user_msg = rec["messages"][0]
    assert user_msg["role"] == "user"
    content_types = [c.get("type") for c in user_msg["content"]]
    assert "image" in content_types
    assert "text" in content_types
    assistant_msg = rec["messages"][1]
    assert assistant_msg["role"] == "assistant"


def test_converter_emits_mlx_vlm_format(tmp_path):
    """TRAIN-04: --format=mlx_vlm emits the mlx-vlm contract."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rMX", step_index=i) for i in range(3)
    ])

    result = _run_converter(
        input_path, output_path,
        "--format", "mlx_vlm",
        "--image-dir", str(image_dir),
        "--min-steps", "1",
    )
    assert result.returncode == 0, f"converter failed: {result.stderr}"

    records = _read_jsonl(output_path)
    rec = records[0]
    assert "messages" in rec
    assert "images" in rec
    user_msg = rec["messages"][0]
    content_types = [c.get("type") for c in user_msg["content"]]
    assert "image" in content_types
    assert "text" in content_types


def test_converter_decodes_screenshots_to_jpeg_files(tmp_path):
    """TRAIN-04: converter decodes screenshot_b64 to <image-dir>/<run_id>/<step_index>.jpg."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rJ", step_index=i) for i in range(3)
    ])

    result = _run_converter(
        input_path, output_path,
        "--image-dir", str(image_dir),
        "--min-steps", "1",
    )
    assert result.returncode == 0, f"converter failed: {result.stderr}"

    expected = image_dir / "rJ" / "0.jpg"
    assert expected.exists(), f"converter must write JPEG to {expected}"

    rec = _read_jsonl(output_path)[0]
    refs = rec.get("images", [])
    assert any("rJ" in r and r.endswith("0.jpg") for r in refs), (
        f"emitted record images must reference rJ/0.jpg; got {refs}"
    )


def test_converter_min_steps_filter(tmp_path):
    """TRAIN-04: --min-steps drops runs shorter than the threshold."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    # Only 2 steps — below default min-steps=3
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rShort", step_index=0),
        _build_runs_record(run_id="rShort", step_index=1),
    ])

    result = _run_converter(
        input_path, output_path,
        "--min-steps", "3",
        "--image-dir", str(image_dir),
    )
    assert result.returncode == 0, f"converter must exit 0 even when output is empty; stderr={result.stderr}"

    if output_path.exists():
        records = _read_jsonl(output_path)
        assert len(records) == 0, f"min-steps=3 must drop a 2-step run; got {len(records)} records"


def test_converter_uses_target_label_when_present(tmp_path):
    """Option B: when the JSONL record carries `action_target_label`, the
    LoRA assistant content uses it as `target="..."` instead of the bare DOM
    index — labels carry transferable cross-page signal, indices don't.
    """
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"

    base = _build_runs_record(run_id="rL", step_index=0, action_type="click",
                              action_target="12", action_value="")
    base["action_target_label"] = "Search button"
    base_next = _build_runs_record(run_id="rL", step_index=1, action_type="click",
                                   action_target="3", action_value="")
    base_next["action_target_label"] = None
    base_third = _build_runs_record(run_id="rL", step_index=2, action_type="click",
                                    action_target="3", action_value="")
    base_third["action_target_label"] = None
    _make_runs_jsonl(input_path, [base, base_next, base_third])

    result = _run_converter(
        input_path, output_path,
        "--image-dir", str(image_dir),
        "--min-steps", "1",
    )
    assert result.returncode == 0, f"converter failed: {result.stderr}"

    records = _read_jsonl(output_path)
    first_assistant = records[0]["messages"][1]["content"][0]["text"]
    assert 'target="Search button"' in first_assistant, (
        f"labeled record must produce target=\"Search button\"; got:\n{first_assistant}"
    )
    # The unlabeled records still fall back to the bare-index form so
    # we don't lose information when the label is absent.
    second_assistant = records[1]["messages"][1]["content"][0]["text"]
    assert "target=3" in second_assistant, (
        f"unlabeled record must fall back to target=N; got:\n{second_assistant}"
    )


def test_converter_handles_null_thought_gracefully(tmp_path):
    """TRAIN-04 / Pitfall 4: null model_thought must not crash; assistant text uses ''."""
    input_path = tmp_path / "runs.jsonl"
    output_path = tmp_path / "out.jsonl"
    image_dir = tmp_path / "images"
    _make_runs_jsonl(input_path, [
        _build_runs_record(run_id="rN", step_index=i, model_thought=None) for i in range(3)
    ])

    result = _run_converter(
        input_path, output_path,
        "--image-dir", str(image_dir),
        "--min-steps", "1",
    )
    assert result.returncode == 0, f"converter must handle null thought; stderr={result.stderr}"
    records = _read_jsonl(output_path)
    assert len(records) >= 1


# ===========================================================================
# TRAIN-05: train_nvidia.py
# ===========================================================================

def test_train_nvidia_module_importable():
    """TRAIN-05: training.train_nvidia imports without torch/unsloth installed."""
    import training.train_nvidia  # noqa: F401


def test_train_nvidia_should_quantize_when_no_cuda():
    """TRAIN-05: should_quantize(None) is True (no CUDA → safe default = quantize)."""
    from training.train_nvidia import should_quantize
    assert should_quantize(None) is True


def test_train_nvidia_should_quantize_below_16gb():
    """TRAIN-05: should_quantize is True for VRAM < 16GB (D-12)."""
    from training.train_nvidia import should_quantize
    assert should_quantize(8.0) is True
    assert should_quantize(12.0) is True
    assert should_quantize(15.9) is True


def test_train_nvidia_should_not_quantize_at_or_above_16gb():
    """TRAIN-05: should_quantize is False for VRAM >= 16GB."""
    from training.train_nvidia import should_quantize
    assert should_quantize(16.0) is False
    assert should_quantize(24.0) is False


def test_train_nvidia_oom_message_human_readable():
    """TRAIN-05: _build_quantization_message returns the documented user-facing string."""
    from training.train_nvidia import _build_quantization_message
    msg = _build_quantization_message(8.0)
    assert "4-bit quantization (QLoRA)" in msg
    assert "16GB+" in msg


def test_train_nvidia_model_id_targets_qwen_7b():
    """TRAIN-05: MODEL_ID targets a Qwen 7B variant (D-12)."""
    from training.train_nvidia import MODEL_ID
    assert "Qwen" in MODEL_ID
    assert ("7B" in MODEL_ID) or ("7b" in MODEL_ID)


# ===========================================================================
# TRAIN-06: train_apple.py
# ===========================================================================

def test_train_apple_module_importable():
    """TRAIN-06: training.train_apple imports without mlx_vlm installed."""
    import training.train_apple  # noqa: F401


def test_train_apple_non_darwin_friendly_error(monkeypatch, capsys):
    """TRAIN-06 (D-13): non-darwin → non-zero exit + friendly stderr/stdout message."""
    import training.train_apple

    monkeypatch.setattr(sys, "platform", "linux")
    rc = training.train_apple.main([])
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()

    assert rc != 0, f"main() must return non-zero on non-darwin; got {rc}"
    assert "apple silicon" in combined, (
        f"non-darwin message must mention 'Apple Silicon'; got:\n{captured.out}\n---\n{captured.err}"
    )
    assert ("darwin" in combined) or ("macos" in combined), (
        f"non-darwin message must mention darwin or macOS; got:\n{captured.out}\n---\n{captured.err}"
    )


def test_train_apple_model_id_targets_qwen_3b():
    """TRAIN-06: MODEL_ID targets a Qwen 3B variant (D-13)."""
    import training.train_apple
    mid = training.train_apple.MODEL_ID
    assert "Qwen" in mid
    assert ("3B" in mid) or ("3b" in mid)


# ===========================================================================
# CR-01 / CR-02 regression tests
# ===========================================================================

def test_cr01_no_history_shadow_in_log_step():
    """CR-01: log_step source must use 'token_history' AND must NOT contain a
    second `    history = ` re-binding that shadows the initial agent.history binding.
    """
    src = inspect.getsource(agent.runner.log_step)
    assert "token_history" in src, (
        "log_step source must rename the token_cost_service usage_history binding "
        "to 'token_history' (CR-01 fix)"
    )
    # Count occurrences of "    history = " (the indented re-binding pattern).
    # The initial `history = agent.history` is fine; a second one is the shadow.
    count = src.count("    history = ")
    assert count <= 1, (
        f"log_step contains {count} `    history = ` bindings — only the initial "
        "`history = agent.history` is allowed (CR-01 fix)"
    )


def test_cr02_action_type_uses_interacted_element_skip():
    """CR-02: log_step source must use the `interacted_element` skip-key idiom
    and MUST NOT use the `list(last_action.keys())[0]` fallback.
    """
    src = inspect.getsource(agent.runner.log_step)
    assert "'interacted_element'" in src or '"interacted_element"' in src, (
        "log_step must reference the 'interacted_element' skip key (CR-02 fix)"
    )
    assert "list(last_action.keys())[0]" not in src, (
        "log_step must NOT use the list(last_action.keys())[0] fallback (CR-02 fix)"
    )


# ===========================================================================
# Sanity: training package marker exists
# ===========================================================================

def test_training_package_marker_exists():
    """Sanity: training/__init__.py exists so `python -m training.converter` resolves."""
    assert Path("training/__init__.py").exists(), (
        "training/__init__.py must exist for python -m training.converter to resolve"
    )
