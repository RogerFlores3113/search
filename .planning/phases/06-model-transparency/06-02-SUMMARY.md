---
phase: 06-model-transparency
plan: "02"
subsystem: agent
tags:
  - sse-events
  - browser-use
  - register-new-step-callback
  - green-gate
  - ThoughtEvent
  - ActionDetailEvent
dependency_graph:
  requires:
    - tests/unit/test_events_phase6.py
    - agent/events.py
    - agent/runner.py
    - tests/unit/test_events_phase5.py
  provides:
    - ThoughtEvent dataclass (agent/events.py)
    - ActionDetailEvent dataclass (agent/events.py)
    - _pre_step closure (agent/runner.py)
    - register_new_step_callback wiring (agent/runner.py)
    - ActionDetailEvent extraction in _log_step (agent/runner.py)
  affects:
    - tests/unit/test_events_phase5.py (two tests renamed; fakes updated)
    - tests/unit/test_ui.py (narration test renamed; fake helper updated)
    - tests/integration/test_end_to_end.py (Agent assertion updated)
tech_stack:
  added: []
  patterns:
    - or None guard for empty-string normalization on ThoughtEvent fields
    - next(k for k in d if k != "interacted_element") for action_type extraction
    - register_new_step_callback async closure pattern for pre-action ThoughtEvent
decisions:
  - NarrationEvent class preserved in events.py for backward compatibility; only emission removed from runner.py
  - _pre_step uses queue.put_nowait (not await queue.put) per Phase 3 D-11 lock
  - success=None for all mid-run ActionDetailEvents (ActionResult.success only set when is_done=True)
  - duration_ms kept as internal computation in _log_step (no longer surfaced on any SSE event)
metrics:
  duration_minutes: 4
  completed: "2026-05-17"
  tasks_completed: 5
  tasks_total: 5
  files_changed: 5
---

# Phase 06 Plan 02: GREEN Gate — ThoughtEvent + ActionDetailEvent Summary

**One-liner:** Wired ThoughtEvent + ActionDetailEvent SSE events via _pre_step closure (register_new_step_callback) and ActionDetailEvent extraction replacing NarrationEvent in _log_step, turning all 18 Phase 6 RED tests GREEN.

## What Was Built

### Task 1: ThoughtEvent + ActionDetailEvent dataclasses (agent/events.py)

Added two new `@dataclass` blocks after `ModelInfoEvent` (lines 69-89):

**ThoughtEvent** (`agent/events.py` line 69):
- `type: Literal["thought"] = "thought"`
- `step: int = 0`
- `thinking: Optional[str] = None`
- `evaluation_previous_goal: Optional[str] = None`
- `next_goal: Optional[str] = None`
- `memory: Optional[str] = None`

**ActionDetailEvent** (`agent/events.py` line 79):
- `type: Literal["action_detail"] = "action_detail"`
- `step: int = 0`
- `action_type: str = "unknown"`
- `target: Optional[str] = None`
- `value: Optional[str] = None`
- `url: Optional[str] = None`
- `success: Optional[bool] = None`

Both follow the established TokenEvent/ModelInfoEvent dataclass pattern.

### Task 2: _pre_step closure + register_new_step_callback wiring (agent/runner.py)

**_pre_step closure** (agent/runner.py, inside `run_agent`'s `else:` block, immediately before `_log_step`):

```python
async def _pre_step(browser_state, agent_output, step_num: int) -> None:
    if queue is None:
        return
    queue.put_nowait(ThoughtEvent(
        step=step_num,
        thinking=agent_output.thinking or None,
        evaluation_previous_goal=agent_output.evaluation_previous_goal or None,
        next_goal=agent_output.next_goal or None,
        memory=agent_output.memory or None,
    ))
```

- Returns immediately when `queue is None` (CLI path)
- Uses `or None` guard to normalize empty strings to `None` (RESEARCH.md Pitfall 2)
- Reads `step_num` from callback parameter (not `history.number_of_steps()` — off by one pre-action)

**Agent constructor wiring** (`agent/runner.py`):
- `register_new_step_callback=_pre_step` added as last kwarg to `Agent(...)` constructor

### Task 3: ActionDetailEvent extraction in _log_step (agent/runner.py)

**action_type extraction** (RESEARCH.md Pitfall 4 fix):
- Old: `last_action.get("action_type") or (list(last_action.keys())[0] if last_action else "unknown")`
- New: `next((k for k in last_action if k != "interacted_element"), "unknown")`

**params extraction**:
- `params = last_action.get(action_type) if isinstance(last_action.get(action_type), dict) else {}`
- `target = str(params["index"]) if "index" in params else None`
- `value = params.get("text") or params.get("query") or params.get("keys") or None`
- `url = params.get("url") or None`

**NarrationEvent emission replaced** with:
```python
queue.put_nowait(ActionDetailEvent(
    step=step_idx + 1,
    action_type=action_type,
    target=target,
    value=value,
    url=url,
    success=None,
))
```

`duration_ms` computation kept (timing reset `step_start = time.monotonic()` unchanged) but no longer surfaced on any SSE event.

### Task 4: Phase 5 test updates (tests/unit/test_events_phase5.py)

| Change | Before | After |
|--------|--------|-------|
| Import | `NarrationEvent` | `ActionDetailEvent` |
| Fake model_actions | `[{"action_type": "click", "action_target": "#btn", "action_value": ""}]` | `[{"click_element": {"index": 5}, "interacted_element": None}]` |
| `test_narration_event_has_step_duration_ms` | Asserted NarrationEvent.step_duration_ms | Renamed `test_action_detail_event_emitted_per_step`, asserts ActionDetailEvent presence + step=1 + action_type="click_element" |
| `test_step_duration_ms_is_nonzero` | Asserted NarrationEvent.step_duration_ms > 0 | Renamed `test_log_step_timing_closure_executes`, asserts run completes with ActionDetailEvent emitted after sleep |

### Task 5: Full regression (test_end_to_end.py, test_ui.py)

**Rule 1 auto-fixes:**

1. `tests/integration/test_end_to_end.py` — `MockAgent.assert_called_once_with` was missing `calculate_cost=True` and `register_new_step_callback`. Updated to include both, using `unittest.mock.ANY` for the closure, with an additional `inspect.iscoroutinefunction` assertion.

2. `tests/unit/test_ui.py` — `_make_fake_agent_instance()` used old-shape action dict and lacked `token_cost_service`. Updated to real-shape dict and added `token_cost_service` namespace. `test_log_step_emits_narration_event` updated to assert `ActionDetailEvent` instead of `NarrationEvent`.

## Final Test Suite Output

```
133 passed, 3 warnings in 1.55s
```

The 3 warnings are pre-existing `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` from tests that mock `log_step` as `AsyncMock()` without patching its return value to a dict — these are not failures and were present before Plan 02.

## Verification Grep Results

| Check | Expected | Actual |
|-------|----------|--------|
| `grep -nE "(class ThoughtEvent\|class ActionDetailEvent)" agent/events.py` | 2 matches | 2 (lines 69, 79) |
| `grep -c "register_new_step_callback=_pre_step" agent/runner.py` | 1 | 1 |
| `grep -c "queue.put_nowait(ThoughtEvent" agent/runner.py` | 1 | 1 |
| `grep -c "queue.put_nowait(ActionDetailEvent" agent/runner.py` | 1 | 1 |
| `grep -c "queue.put_nowait(NarrationEvent" agent/runner.py` | 0 | 0 |
| `grep -n "NarrationEvent" agent/runner.py` | import + comment only | lines 18 (import), 325 (comment) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Integration test Agent assertion missing Phase 5+6 kwargs**
- **Found during:** Task 5
- **Issue:** `tests/integration/test_end_to_end.py::test_post_run_endpoint_starts_agent` used `assert_called_once_with` without `calculate_cost=True` or `register_new_step_callback=_pre_step`. Fails because the Agent() call now includes these kwargs.
- **Fix:** Updated assertion to include `calculate_cost=True` and `register_new_step_callback=ANY`, plus added `inspect.iscoroutinefunction` check.
- **Files modified:** `tests/integration/test_end_to_end.py`
- **Commit:** f45629b

**2. [Rule 1 - Bug] test_ui.py fake agent missing token_cost_service + old-shape model_actions**
- **Found during:** Task 5
- **Issue:** `_make_fake_agent_instance()` in test_ui.py used old-shape `{"action_type": "navigate", ...}` dict and lacked `token_cost_service`. The new `_log_step` tries `next(k for k in d if k != "interacted_element")` — this gives `"action_type"` as the key name, not the action name. Also `log_step` (the JSONL writer) needs `token_cost_service` unless mocked.
- **Fix:** Updated helper to use real-shape `{"navigate": {"url": "..."}, "interacted_element": None}` and added `token_cost_service` namespace. Also fixed `test_log_step_emits_narration_event` to assert `ActionDetailEvent`.
- **Files modified:** `tests/unit/test_ui.py`
- **Commit:** f45629b

## TRANS-01 / TRANS-02 / TRANS-03 Traceability

| Requirement | Test(s) | Status |
|-------------|---------|--------|
| TRANS-01 (ThoughtEvent shape + null keys) | `test_thought_event_shape`, `test_thought_event_null_fields`, `test_thought_event_type_literal`, `test_pre_step_emits_thought_event`, `test_thought_event_null_when_model_omits_thinking` | GREEN |
| TRANS-02 (_pre_step wiring + ordering) | `test_run_agent_passes_register_new_step_callback_kwarg`, `test_thought_event_step_matches_callback_step_num`, `test_thought_event_fires_before_action_detail`, `test_thought_and_action_share_step_when_both_fire` | GREEN |
| TRANS-03 (ActionDetailEvent extraction) | `test_action_detail_event_shape`, `test_action_detail_event_null_fields`, `test_action_detail_event_type_literal`, `test_log_step_emits_action_detail_event`, `test_action_type_excludes_interacted_element`, `test_action_detail_navigate_url`, `test_action_detail_input_text_value`, `test_action_detail_success_is_none_midrun`, `test_narration_event_removed_from_log_step` | GREEN |

## Threat Model Dispositions

| Threat ID | Disposition | Notes |
|-----------|-------------|-------|
| T-06-04 | Mitigated | ThoughtEvent fields not logged/printed; localhost-only SSE binding (Phase 3 D-11); no print/log of ThoughtEvent payload |
| T-06-05 | Accepted (Phase 9 mitigates) | Phase 6 emits raw strings to in-memory queue only; Phase 9 responsible for HTML escaping |
| T-06-06 | Accepted | model_actions() output is validated Pydantic; no new trust boundary in Phase 6 |
| T-06-07 | Mitigated | _pre_step body is minimal (one dict + one put_nowait); unbounded queue; if-None guard for CLI path |
| T-06-08 | Accepted | ThoughtEvent is UX enhancement; missing events degrade UX not security |

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | f25ad43 | feat(06-02): add ThoughtEvent and ActionDetailEvent dataclasses to agent/events.py |
| 2 | cef293e | feat(06-02): add _pre_step closure and register_new_step_callback wiring in runner.py |
| 3 | 64a0f49 | feat(06-02): replace NarrationEvent with ActionDetailEvent extraction in _log_step |
| 4 | 33b0625 | test(06-02): update Phase 5 tests to assert ActionDetailEvent instead of NarrationEvent |
| 5 | f45629b | test(06-02): update integration and UI tests for ActionDetailEvent replacement |

## Self-Check: PASSED

- [x] `agent/events.py` defines `ThoughtEvent` (line 69) and `ActionDetailEvent` (line 79)
- [x] `NarrationEvent` class still present in `agent/events.py` (backward compatibility)
- [x] `agent/runner.py` defines `async def _pre_step` inside `run_agent`
- [x] `Agent(...)` constructor includes `register_new_step_callback=_pre_step`
- [x] `_log_step` emits `ActionDetailEvent` (not `NarrationEvent`)
- [x] `grep -c "queue.put_nowait(NarrationEvent" agent/runner.py` returns 0
- [x] All 18 Phase 6 tests pass GREEN (`uv run pytest tests/unit/test_events_phase6.py -q`)
- [x] All Phase 5 tests pass GREEN (`uv run pytest tests/unit/test_events_phase5.py -q`)
- [x] Full suite 133 tests pass (`uv run pytest tests/ -q`)
- [x] Commits f25ad43, cef293e, 64a0f49, 33b0625, f45629b exist in git log
