---
phase: 05-token-counting-timing
plan: "01"
subsystem: agent/events + tests
tags:
  - sse
  - dataclass
  - tdd
  - timing
  - tokens
dependency_graph:
  requires:
    - agent/events.py (existing dataclass pattern)
  provides:
    - agent.events.TokenEvent
    - agent.events.ModelInfoEvent
    - agent.events.NarrationEvent.step_duration_ms
    - tests/unit/test_events_phase5.py (RED gate for Plan 02)
  affects:
    - agent/runner.py (Plan 02 wires against these dataclasses)
    - Phase 8 JSONL enrichment (TokenEvent fields in wire contract)
    - Phase 9 UI wiring (ModelInfoEvent, step_duration_ms rendering)
tech_stack:
  added: []
  patterns:
    - "@dataclass + Literal type field (existing events.py pattern extended)"
    - "Optional[int] / Optional[float] for nullable token fields"
    - "asyncio.Queue drain pattern (queue.get_nowait) for SSE bridge tests"
    - "types.SimpleNamespace fake agent with token_cost_service stub"
key_files:
  created:
    - tests/unit/test_events_phase5.py
  modified:
    - agent/events.py
decisions:
  - "step_duration_ms added as last field on NarrationEvent (default=0) to preserve backward-compatible positional construction"
  - "TokenEvent prompt_tokens/completion_tokens/cost_usd all Optional — Ollama emits None, API providers emit int/float"
  - "test_narration_event_has_step_duration_ms passes (field exists from Task 1); test_step_duration_ms_is_nonzero is RED (runner timing not wired)"
metrics:
  duration: "179s (~3 minutes)"
  completed: "2026-05-17"
  tasks_completed: 2
  files_modified: 2
---

# Phase 05 Plan 01: Event Shapes + Phase 5 RED Gate Summary

**One-liner:** TokenEvent and ModelInfoEvent dataclasses added to agent.events with Optional token fields; NarrationEvent extended with step_duration_ms=0; 9 RED gate tests authored for Plan 02 runner wiring.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend agent/events.py with TokenEvent, ModelInfoEvent, NarrationEvent.step_duration_ms | 01cf90b | agent/events.py |
| 2 | Author tests/unit/test_events_phase5.py covering every PERF-01, PERF-02, PERF-04 behavior | 6d9e823 | tests/unit/test_events_phase5.py |

## What Was Built

### Task 1: Event Shape Extensions (agent/events.py)

Added `Optional` to the typing import. Added two new dataclasses following the existing `@dataclass + Literal` pattern:

- **TokenEvent** — `type: Literal["token"]`, `step: int = 0`, `prompt_tokens: Optional[int] = None`, `completion_tokens: Optional[int] = None`, `cost_usd: Optional[float] = None`
- **ModelInfoEvent** — `type: Literal["model_info"]`, `provider: str = ""`, `model_name: str = ""`

Extended **NarrationEvent** with `step_duration_ms: int = 0` as the final field (backward-compatible — all existing positional construction sites remain valid).

### Task 2: RED Gate Tests (tests/unit/test_events_phase5.py)

9 tests covering every behavior row in 05-RESEARCH.md Phase Requirements -> Test Map:

| Test | Req | Status |
|------|-----|--------|
| test_narration_event_has_step_duration_ms | PERF-01 | PASS (field exists) |
| test_step_duration_ms_is_nonzero | PERF-01 | FAIL (RED — runner not wired) |
| test_token_event_emitted_per_step | PERF-02 | FAIL (RED) |
| test_ollama_token_event_fields_are_none | PERF-02 | FAIL (RED) |
| test_api_token_event_has_integer_counts | PERF-02 | FAIL (RED) |
| test_model_info_event_emitted_at_run_start | PERF-04 | FAIL (RED) |
| test_model_info_event_fields | PERF-04 | FAIL (RED) |
| test_log_step_returns_token_dict | guard | FAIL (RED) |
| test_run_agent_sets_calculate_cost | guard | FAIL (RED) |

8/9 tests RED — RED gate established for Plan 02. The one passing test (`test_narration_event_has_step_duration_ms`) correctly validates the dataclass field added in Task 1 (`isinstance(int) and >= 0`), not the runner wiring.

## Decisions Made

- `step_duration_ms` as last field on NarrationEvent preserves backward-compatible positional construction (existing call sites use `NarrationEvent(step=N, text=..., timestamp=...)` without `step_duration_ms`)
- Tests use `types.SimpleNamespace` fake agents with `token_cost_service` stubs following the `_make_fake_agent_with_tokens` template from 05-PATTERNS.md
- Fake agents use `queue.get_nowait()` drain pattern (never `await queue.put()`) matching established runner.py pattern
- `_make_fake_agent_ollama()` has empty `usage_history=[]` matching real Ollama behavior (browser-use 0.12.6 never appends when `result.usage` is None)

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

- `uv run python -c "import agent.events"` → exits 0
- `uv run python -c "from agent.events import TokenEvent, ModelInfoEvent, NarrationEvent; ..."` → exits 0
- `uv run pytest tests/unit/test_runner.py tests/unit/test_training_log.py -x -q` → 23 passed (no regression)
- `uv run pytest tests/unit/test_events_phase5.py --collect-only -q` → 9 tests collected
- `uv run pytest tests/unit/test_events_phase5.py -q` → 8 failed, 1 passed (RED gate)

## Known Stubs

None — dataclass event shapes are complete wire contract definitions, not stubs.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced. T-05-03 mitigation verified: all default values are empty strings, 0, or None — no secret material in defaults.

## Self-Check: PASSED

- agent/events.py exists and contains TokenEvent, ModelInfoEvent, step_duration_ms
- tests/unit/test_events_phase5.py exists with 9 tests
- Commits 01cf90b and 6d9e823 verified in git log
