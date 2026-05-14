---
phase: "01"
plan: "03"
subsystem: agent-e2e-test
tags:
  - smoke-test
  - end-to-end
  - walking-skeleton
  - asyncio
  - testclient
dependency_graph:
  requires:
    - "01-02: run_agent, log_step, pre_flight_check, FastAPI lifespan — all real implementations"
  provides:
    - "tests/integration/test_end_to_end.py: Automated E2E proof of asyncio plumbing without Chrome or Ollama"
    - "01-03-MANUAL-VERIFICATION.md: Manual smoke-test record (PENDING — Task 2 checkpoint)"
  affects:
    - "Phase 1 sign-off: all ROADMAP Phase 1 success criteria covered (automated + manual)"
tech_stack:
  added:
    - "starlette.testclient.TestClient for in-process FastAPI lifespan testing"
    - "unittest.mock.patch targeting agent.runner.BrowserSession/ChatOllama/Agent at module level"
  patterns:
    - "Fake Agent.run calls on_step_end(fake_agent) twice so real log_step code executes and JSONL is written"
    - "monkeypatch.chdir(tmp_path) redirects TRAINING_FILE writes to temp directory"
    - "AsyncMock for pre_flight_check patch; fast-returning mock Agent.run completes before lifespan cancel fires"
key_files:
  created:
    - tests/integration/test_end_to_end.py
  modified: []
decisions:
  - "Mock Agent.run uses a real async def side_effect that awaits on_step_end — this exercises the real log_step rather than bypassing it, making the test a true structural proof"
  - "TestClient runs the lifespan in an anyio portal; task completes before cancel because mock Agent.run returns immediately — no extra sleep or asyncio manipulation needed"
  - "Scenario B asserts Agent was called with task= matching the HTTP POST body (not just status=started) — confirms the wiring from /run → create_task → run_agent → Agent(task=...)"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-13"
  tasks_completed: 1
  tasks_pending: 1
  files_created: 1
  files_modified: 0
---

# Phase 01 Plan 03: E2E Walking-Skeleton Proof Summary

Automated E2E test (TestClient + mocked browser-use) proves the full asyncio plumbing chain — lifespan startup, create_task, on_step_end callback, D-09 JSONL write, browser.kill — without Chrome or Ollama; manual smoke test (Task 2) is pending human verification.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Automated E2E test — lifespan + create_task + on_step_end + JSONL | 67eee96 | tests/integration/test_end_to_end.py |

## Tasks Pending

| Task | Name | Status | Blocked by |
|------|------|--------|------------|
| 2 | Manual smoke test — Chrome + Ollama live | CHECKPOINT | Human verification required (Chrome + Ollama on physical machine) |

## What the Automated Test Proves

**Scenario A (`test_lifespan_runs_full_agent_loop_with_mocks`):**
- FastAPI lifespan fires `asyncio.create_task(run_agent("test task"))` on startup
- `pre_flight_check` is patched out (no Ollama needed)
- `BrowserSession` was constructed with `channel="chrome"`, `headless=False`, `keep_alive=False`
- `ChatOllama` was constructed with `model=config.ollama_model`, `num_ctx=32000`
- Mock `Agent.run` calls `on_step_end(fake_agent)` twice → real `log_step` executes
- `training/runs.jsonl` exists with exactly 2 lines, each containing all 9 D-09 keys:
  `timestamp`, `run_id`, `step_index`, `screenshot_b64`, `action_type`, `action_target`, `action_value`, `narration`, `step_success`
- `browser.kill()` was awaited in the `finally` block

**Scenario B (`test_post_run_endpoint_starts_agent`):**
- `POST /run` returns `{"status": "started"}` with HTTP 200
- `Agent` was instantiated with `task="another task"` from the request body

## Test Results

```
uv run pytest tests/integration/test_end_to_end.py -v: 2 passed
uv run pytest tests/ -v: 22 passed, 0 failed, 0 skipped
```

## Manual Verification Status (Task 2 — PENDING)

Task 2 requires a machine with Chrome and Ollama installed. Five verifications must be recorded:

| Verification | Requirement | Status |
|-------------|-------------|--------|
| A — happy path (Chrome opens, Wikipedia navigates, JSONL written) | LOOP-02, LOOP-03, LOOP-04, MODEL-01 | PENDING |
| B — Ollama down (actionable error, Chrome never opens) | MODEL-04 | PENDING |
| C — model not pulled (actionable error with pull command) | MODEL-04 | PENDING |
| D — max_steps=3 terminates cleanly, no orphan Chrome | LOOP-05 | PENDING |
| E — SESSION_TIMEOUT=30 exits within 30s with timeout message | LOOP-06 | PENDING |

## Requirements Coverage

| ID | Description | Coverage | Test |
|----|-------------|----------|------|
| LOOP-02 | Agent runs screenshot→LLM→action cycle | Automated | test_lifespan_runs_full_agent_loop_with_mocks (mock Agent.run) |
| LOOP-03 | BrowserSession(channel="chrome", headless=False) | Automated | BrowserSession.assert_called_once_with(...) |
| LOOP-04 | on_step_end=log_step wired to agent.run | Automated | fake_run calls on_step_end; JSONL asserted |
| LOOP-05 | max_steps=config.max_steps | Unit (01-02) + Manual pending | Unit: test_run_agent_calls_max_steps_25; Manual: Verification D |
| LOOP-06 | asyncio.wait_for(timeout=config.session_timeout) | Unit (01-02) + Manual pending | Unit: test_run_agent_wraps_in_wait_for; Manual: Verification E |
| MODEL-01 | ChatOllama(model=..., num_ctx=32000) | Automated | MockChatOllama.assert_called_once_with(num_ctx=32000) |
| MODEL-04 | pre_flight_check with sys.exit(1) + actionable messages | Integration (01-02) + Manual pending | test_model_validation.py; Manual: Verifications B + C |

## Deviations from Plan

None — test exercises the exact plumbing described in the plan spec. No auto-fixes needed.

## Known Stubs

None in this plan. Manual verification record (`01-03-MANUAL-VERIFICATION.md`) has not yet been created — it will be authored by the user during Task 2 checkpoint.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Test file is dev-only; no production surface added.

## Self-Check: PASSED

Files verified:
- tests/integration/test_end_to_end.py: EXISTS

Commits verified:
- 67eee96: EXISTS (test(01-03): automated E2E test...)
