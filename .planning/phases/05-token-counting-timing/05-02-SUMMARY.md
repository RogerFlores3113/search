---
phase: 05-token-counting-timing
plan: "02"
subsystem: agent/runner
tags:
  - sse
  - runner
  - timing
  - tokens
  - browser-use
dependency_graph:
  requires:
    - agent/events.py (TokenEvent, ModelInfoEvent, NarrationEvent.step_duration_ms — Plan 01)
    - tests/unit/test_events_phase5.py (RED gate authored in Plan 01)
  provides:
    - agent/runner.py::_resolve_model_name
    - agent/runner.py::log_step (now returns dict with token data)
    - agent/runner.py::_log_step (emits TokenEvent + step_duration_ms)
    - agent/runner.py::run_agent (emits ModelInfoEvent, constructs Agent with calculate_cost=True)
  affects:
    - Phase 8 JSONL enrichment (token fields available from log_step return value)
    - Phase 9 UI wiring (TokenEvent, ModelInfoEvent, step_duration_ms ready for rendering)
tech_stack:
  added:
    - "import time (stdlib)"
  patterns:
    - "nonlocal closure variable mutation for step_start timing"
    - "provider-gated token_cost_service.usage_history[-1] read"
    - "Settings() called fresh inside log_step for test env var compatibility"
    - "queue.put_nowait(TokenEvent(...)) after ProgressEvent in _log_step"
    - "ModelInfoEvent emitted immediately after StateEvent('running') in run_agent"
key_files:
  created: []
  modified:
    - agent/runner.py
decisions:
  - "Settings() instantiated fresh inside log_step token extraction block to pick up monkeypatched env vars in tests (module-level config singleton is set at import time and does not reflect test env overrides)"
  - "_resolve_model_name placed at module level near build_llm to keep provider resolution logic co-located"
  - "step_start reset is the last statement of _log_step (after all put_nowait calls) per Pitfall 5 in 05-RESEARCH.md"
  - "TokenEvent emitted even when queue is not None only — no-op on Ollama with None fields"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-17"
  tasks_completed: 2
  files_modified: 1
---

# Phase 05 Plan 02: Runner Wiring — Token Counting + Timing Summary

**One-liner:** agent/runner.py extended with time.monotonic() step timing, per-step TokenEvent emission via token_cost_service.usage_history, ModelInfoEvent at run start, and calculate_cost=True; all 9 Phase 5 RED gate tests turned GREEN.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add timing closure, ModelInfoEvent emission, calculate_cost=True, _resolve_model_name | 020562a | agent/runner.py |
| 2 | Extend log_step to return token dict and _log_step to emit TokenEvent + step_duration_ms | 53dbb0b | agent/runner.py |

## What Was Built

### Task 1: run_agent infrastructure (agent/runner.py)

- **`import time`** added to stdlib block
- **`TokenEvent, ModelInfoEvent`** added to events import
- **`_resolve_model_name(cfg)`** — module-level helper returning the configured model string for the active provider (ollama/anthropic/openai → respective model field; else "unknown")
- **`step_start = time.monotonic()`** — initialized before the try block in `run_agent`, establishing the closure variable for `_log_step` to read and reset via `nonlocal`
- **`ModelInfoEvent` emission** — `queue.put_nowait(ModelInfoEvent(provider=config.provider, model_name=_resolve_model_name(config)))` immediately after `StateEvent(state="running")` and before `agent.run()` is awaited
- **`calculate_cost=True`** — added as the last kwarg to the `Agent(...)` constructor call

### Task 2: log_step + _log_step extensions (agent/runner.py)

- **`log_step` return type** changed from `-> None` to `-> dict`
- **Token extraction block** appended after CAPTCHA detection: reads `Settings().provider` fresh (for test env var compatibility), gates on `provider in ("anthropic", "openai")`, reads `agent.token_cost_service.usage_history[-1]`, extracts `prompt_tokens` / `completion_tokens`, awaits `calculate_cost()` and rounds `total_cost` to 6 decimal places; returns `token_data` dict with three keys always present
- **`_log_step` nonlocal timing** — `nonlocal step_start`, `duration_ms = int((time.monotonic() - step_start) * 1000)` computed before `log_step` call
- **`NarrationEvent`** extended with `step_duration_ms=duration_ms` kwarg
- **`TokenEvent` emission** — `queue.put_nowait(TokenEvent(step=step_idx + 1, **token_data))` after `ProgressEvent`
- **`step_start` reset** — `step_start = time.monotonic()` as the last statement of `_log_step` (after all puts)

## Verification Results

- `uv run pytest tests/unit/test_events_phase5.py -x -q` → 9 passed (all GREEN)
- `uv run pytest tests/unit/test_runner.py -x -q` → 23 passed (no regression)
- `uv run pytest tests/unit/test_training_log.py -x -q` → passed (no regression)
- `uv run pytest tests/unit/ -x -q` → 32 passed total
- Forbidden patterns: `agent.usage_history` = 0, `await queue.put(` = 0, `time.time()` = 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fresh Settings() for provider read in log_step**
- **Found during:** Task 2 verification — `test_api_token_event_has_integer_counts` failed because `config.provider` (module-level singleton) was `"ollama"` even when test set `PROVIDER=anthropic` via `monkeypatch_env.setenv`
- **Issue:** Module-level `config = Settings()` is evaluated once at import time; env var changes via `monkeypatch` do not propagate to the singleton
- **Fix:** Changed `provider = config.provider.lower()` inside `log_step` token extraction block to use `Settings().provider.lower()` (fresh instance per call)
- **Files modified:** agent/runner.py (token extraction block only)
- **Commit:** 53dbb0b

## Known Stubs

None — all token fields are populated from live `token_cost_service.usage_history` for API providers; None values for Ollama are correct by spec (not stubs).

## Threat Flags

No new network endpoints, auth paths, or file access patterns introduced beyond what is documented in the plan's threat model (T-05-05 through T-05-10). All mitigations applied:
- T-05-07: provider gate `if provider in ("anthropic", "openai")` and `if history` guard both present
- T-05-10: `time.monotonic()` used exclusively; `time.time()` forbidden pattern verified absent

## Self-Check: PASSED

- agent/runner.py exists and contains all required additions
- Commits 020562a and 53dbb0b verified in git log
- `uv run pytest tests/unit/ -x -q` → 32 passed
