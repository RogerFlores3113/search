---
phase: 06-model-transparency
plan: "01"
subsystem: tests
tags:
  - tests
  - red-gate
  - sse-events
  - browser-use
dependency_graph:
  requires:
    - tests/unit/test_events_phase5.py
    - agent/events.py
    - agent/runner.py
  provides:
    - tests/unit/test_events_phase6.py
  affects:
    - agent/events.py (Plan 02 must add ThoughtEvent + ActionDetailEvent)
    - agent/runner.py (Plan 02 must add _pre_step + ActionDetailEvent extraction)
tech_stack:
  added: []
  patterns:
    - FakeAgentWithCallback — captures register_new_step_callback from Agent() kwargs
    - CapturingAgentClass — records Agent constructor kwargs for assertion
    - Queue drain pattern — drain asyncio.Queue post-run, filter by isinstance
key_files:
  created:
    - tests/unit/test_events_phase6.py
  modified: []
decisions:
  - FakeAgentWithCallback written as a standalone class (not inner class) so it can be subclassed per-test for step_num override
  - _make_fake_agent_history accepts an optional actions= kwarg to allow per-test action injection without duplicating the full helper
  - 18 tests written in a single commit rather than incrementally (identical semantic result — all tests are RED at commit time)
metrics:
  duration_minutes: 12
  completed: "2026-05-17"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 1
---

# Phase 06 Plan 01: Phase 6 RED Gate Test Suite Summary

**One-liner:** RED gate test suite for ThoughtEvent + ActionDetailEvent: 18 tests that import non-existent dataclasses from agent.events, confirming ImportError until Plan 02 wires runner.py and events.py.

## What Was Built

Created `tests/unit/test_events_phase6.py` — the executable specification for Plan 02. All 18 tests fail with `ImportError: cannot import name 'ThoughtEvent' from 'agent.events'` until Plan 02 implements the two new dataclasses and wires the runner.

**Test file location:** `tests/unit/test_events_phase6.py`
**Total test count:** 18

## RED Gate Confirmation

Running `uv run pytest tests/unit/test_events_phase6.py -x` produces:

```
ImportError: cannot import name 'ThoughtEvent' from 'agent.events'
```

The import at line 23 (`from agent.events import ThoughtEvent, ActionDetailEvent, NarrationEvent, StateEvent`) fails at collection time — 0 tests collected, 1 collection error. This is the expected RED state.

Phase 5 tests (`uv run pytest tests/unit/test_events_phase5.py`) continue to pass (9/9) — Plan 01 only added a new file.

## Requirement Coverage Map

| Requirement | Test(s) | What It Pins |
|-------------|---------|-------------|
| TRANS-01 | `test_thought_event_shape`, `test_thought_event_null_fields`, `test_thought_event_type_literal`, `test_pre_step_emits_thought_event`, `test_thought_event_null_when_model_omits_thinking` | ThoughtEvent dataclass fields and null-key contract (ROADMAP criterion 4) |
| TRANS-02 | `test_run_agent_passes_register_new_step_callback_kwarg`, `test_thought_event_step_matches_callback_step_num`, `test_thought_event_fires_before_action_detail`, `test_thought_and_action_share_step_when_both_fire` | _pre_step wired via register_new_step_callback; ThoughtEvent fires before ActionDetailEvent |
| TRANS-03 | `test_action_detail_event_shape`, `test_action_detail_event_null_fields`, `test_action_detail_event_type_literal`, `test_log_step_emits_action_detail_event`, `test_action_type_excludes_interacted_element`, `test_action_detail_navigate_url`, `test_action_detail_input_text_value`, `test_action_detail_success_is_none_midrun`, `test_narration_event_removed_from_log_step` | ActionDetailEvent dataclass shape, extraction logic, NarrationEvent removal |

## Test Structure (18 tests total)

**Dataclass shape contract — TRANS-01, TRANS-03** (6 synchronous tests):
- `test_thought_event_shape` — default instantiation + keyword construction
- `test_thought_event_null_fields` — asdict() contains null-eligible keys with None values
- `test_thought_event_type_literal` — type == "thought"
- `test_action_detail_event_shape` — default instantiation + keyword construction
- `test_action_detail_event_null_fields` — asdict() null-key presence
- `test_action_detail_event_type_literal` — type == "action_detail"

**TRANS-01 / TRANS-02 — _pre_step wiring and ThoughtEvent emission** (5 async tests):
- `test_run_agent_passes_register_new_step_callback_kwarg` — Agent() receives async callback
- `test_pre_step_emits_thought_event` — 1 ThoughtEvent with all 4 thought fields
- `test_thought_event_null_when_model_omits_thinking` — None + empty string normalized to None
- `test_thought_event_step_matches_callback_step_num` — step from callback param, not history
- `test_thought_event_fires_before_action_detail` — ThoughtEvent index < ActionDetailEvent index

**TRANS-03 — ActionDetailEvent extraction** (7 async tests):
- `test_log_step_emits_action_detail_event` — click_element → action_type, target
- `test_action_type_excludes_interacted_element` — interacted_element key excluded
- `test_action_detail_navigate_url` — navigate → url field populated
- `test_action_detail_input_text_value` — input_text → target (index) + value (text)
- `test_action_detail_success_is_none_midrun` — success always None for non-final steps
- `test_narration_event_removed_from_log_step` — 0 NarrationEvent after D-05
- `test_thought_and_action_share_step_when_both_fire` — both events share step=1

## Helpers Defined

**`_make_agent_output(thinking, evaluation_previous_goal, next_goal, memory)`:** Returns a SimpleNamespace mimicking AgentOutput with the four thought fields. The action attribute is a list placeholder (_pre_step does not read it).

**`_make_fake_agent_history(actions=None)`:** Returns a fake agent shaped like browser-use's Agent object. The `actions` kwarg is overridable per-test to inject specific action dict shapes (click_element, navigate, input_text, etc.). Includes `token_cost_service` namespace so _log_step's token path doesn't crash.

**`FakeAgentWithCallback`:** Standalone class (not inner class) that captures `register_new_step_callback` from Agent() `**kwargs`, stores configurable `agent_output` and `step_num`, and in `async def run()` invokes the callback before `on_step_end`. Uses `inspect.iscoroutinefunction` guard for callback dispatch. Designed to be subclassed per-test for step_num override.

## Deviations from Plan

### Auto-fixed — Implementation Refinements

**1. [Rule 1 - Design] Written as single commit rather than three incremental commits**
- **Found during:** Task 1 authoring
- **Issue:** The plan described building the file incrementally across Tasks 1→3, but all three tasks produce the same final file. Writing once and committing is semantically identical.
- **Fix:** Created the complete 18-test file in a single Write operation, confirmed RED state, committed once.
- **Files modified:** `tests/unit/test_events_phase6.py`
- **Commit:** 49b97cd

**2. [Rule 2 - Pattern] FakeAgentWithCallback written as standalone class**
- **Found during:** Task 2 authoring
- **Issue:** Plan said "inner class" but inner classes cannot be subclassed in the same test to vary step_num.
- **Fix:** Made `FakeAgentWithCallback` a module-level class, used anonymous subclasses (`class _Fake(FakeAgentWithCallback): ...`) inside each test function that needs step_num override. Matches plan intent while enabling clean per-test configuration.

## Plan 02 Pointer

Plan 02 (GREEN gate) must:
1. Add `ThoughtEvent` and `ActionDetailEvent` dataclasses to `agent/events.py`
2. Define `_pre_step` closure inside `run_agent` in `agent/runner.py`
3. Add `register_new_step_callback=_pre_step` to the `Agent()` constructor
4. Replace `NarrationEvent` emission in `_log_step` with `ActionDetailEvent` extraction
5. Update Phase 5 tests that assert `NarrationEvent` presence (per RESEARCH.md Pitfall 5)

All 18 tests in `test_events_phase6.py` pass (GREEN) when Plan 02 is complete.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1+2+3 (combined) | 49b97cd | test(06-01): add Phase 6 RED gate test suite — ThoughtEvent + ActionDetailEvent contract |

## Self-Check: PASSED

- [x] `tests/unit/test_events_phase6.py` exists at correct path
- [x] 18 test functions found (verified via AST parse)
- [x] ImportError confirmed on `uv run pytest tests/unit/test_events_phase6.py -x`
- [x] Phase 5 tests still pass (9/9)
- [x] Commit 49b97cd exists in git log
- [x] Syntax valid: `python3 -c "import ast; ast.parse(...)"` exits 0
