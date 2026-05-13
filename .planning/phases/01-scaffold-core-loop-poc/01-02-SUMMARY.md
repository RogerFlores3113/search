---
phase: "01"
plan: "02"
subsystem: agent-core-loop
tags:
  - agent
  - browser-use
  - ollama
  - fastapi
  - asyncio
  - training-data
dependency_graph:
  requires:
    - "01-01: agent package skeleton, pyproject.toml, pytest harness"
  provides:
    - "pre_flight_check: Ollama daemon + model validation with actionable sys.exit messages"
    - "log_step: async on_step_end callback writing D-09 JSONL schema to training/runs.jsonl"
    - "run_agent: full agentic loop (pre-flight, BrowserSession, ChatOllama, Agent, wait_for, kill)"
    - "FastAPI lifespan: asyncio.create_task(run_agent) on startup from pending_task"
    - "CLI: python -m agent '<task>' with usage/exit-2 guard"
    - "tests/unit/test_runner.py: 9 mock-based unit tests for run_agent wiring"
  affects:
    - "01-03: FastAPI web UI integration (stream.py, SSE, history)"
tech_stack:
  added:
    - "browser_use.ChatOllama (module-level import, not langchain)"
    - "browser_use.browser.session.BrowserSession (channel=chrome, headless=False, keep_alive=False)"
    - "asyncio.wait_for wrapping agent.run for session timeout"
    - "httpx.AsyncClient for Ollama pre-flight GET /api/tags"
    - "uuid.uuid4() as module-level RUN_ID constant"
  patterns:
    - "Module-level browser-use imports for monkeypatch patchability in tests"
    - "FastAPI lifespan asynccontextmanager with asyncio.create_task for agent task"
    - "pre_flight_check returns None on success, sys.exit(1) on failure (not raises)"
    - "finally: await browser.kill() ensures Chrome cleanup on all exit paths"
    - "D-09 JSONL schema: 9 fields per step — timestamp, run_id, step_index, screenshot_b64, action_type, action_target, action_value, narration, step_success"
key_files:
  created:
    - tests/unit/test_runner.py
  modified:
    - agent/runner.py
    - agent/main.py
    - agent/__main__.py
    - tests/unit/test_training_log.py
    - tests/integration/test_model_validation.py
decisions:
  - "Browser-use imports (BrowserSession, ChatOllama, Agent) moved to module level in runner.py so unittest.mock.patch can find them as attributes; local imports inside run_agent() would be unpatchable"
  - "run_agent import in main.py promoted to module level for same patchability reason (lifespan test)"
  - "on_step_end signature confirmed: AgentHookFunc = Callable[['Agent'], Awaitable[None]] — matches RESEARCH.md Pattern 5 exactly; agent.history populated incrementally during run()"
  - "model_actions() returns dicts from action.model_dump() — keys are action-type names not the test fixture's action_type/action_target/action_value keys; log_step falls back gracefully via .get() with fallbacks"
metrics:
  duration: "204 seconds (~3 minutes)"
  completed: "2026-05-13"
  tasks_completed: 2
  files_created: 1
  files_modified: 5
---

# Phase 01 Plan 02: Core Loop Implementation Summary

Real implementations of `pre_flight_check` (Ollama daemon + model validation with sys.exit(1) and actionable messages), `log_step` (D-09 JSONL training logger), and `run_agent` (full BrowserSession+ChatOllama+Agent+asyncio.wait_for loop); all xfails from plan-01 turned green; 9 new mock-based unit tests added; all five critical pitfalls neutralized.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement pre_flight_check and log_step in runner.py | 65f5361 | agent/runner.py, tests/unit/test_training_log.py, tests/integration/test_model_validation.py |
| 2 | Implement run_agent, wire FastAPI lifespan, finalize __main__ CLI | a4cf5c0 | agent/runner.py, agent/main.py, agent/__main__.py, tests/unit/test_runner.py |

## on_step_end Signature Verification

Verified against installed browser-use 0.12.6 source at `.venv/lib/python3.11/site-packages/browser_use/agent/service.py`:

```
AgentHookFunc = Callable[['Agent'], Awaitable[None]]
```

- Callback receives the `Agent` instance (not a different type) — **matches RESEARCH.md Pattern 5 exactly**
- `agent.history` is an `AgentHistoryList` initialized at `__init__` and populated incrementally via `self.history.add_item(history_item)` during each step — **A3 confirmed: accessible during on_step_end**
- `AgentHistoryList` has all expected methods: `number_of_steps()`, `model_actions()`, `screenshots()`, `has_errors()`, `final_result()`
- **Divergence from RESEARCH.md Pattern 5:** `model_actions()` returns dicts from `action.model_dump(exclude_none=True, mode='json')` — the outer keys are action-type names (e.g., `click_element`, `type_text`), not `action`/`index`/`text`. The `log_step` implementation uses `.get("action_type")` with fallback to `list(last_action.keys())[0]` to handle both the test fixture's format and real browser-use production format.

## Test Results

```
uv run pytest tests/ -v: 20 passed, 0 failed, 0 skipped, 0 xfailed
```

| Test File | Tests | Result |
|-----------|-------|--------|
| tests/integration/test_model_validation.py | 3 | ALL PASS (was 3 xfail) |
| tests/unit/test_training_log.py | 3 | ALL PASS (was 3 xfail) |
| tests/unit/test_config.py | 5 | ALL PASS (unchanged) |
| tests/unit/test_runner.py | 9 | ALL PASS (new) |

## Critical Pitfall Mitigations

All five ROADMAP critical pitfalls are neutralized and grep-enforced:

| Pitfall | Mitigation | Enforcement |
|---------|-----------|-------------|
| 1: keep_alive=True hangs event loop | `keep_alive=False` in BrowserSession; `finally: await browser.kill()` | `grep -c 'keep_alive=True' agent/runner.py` → 0 |
| 2: No session timeout = infinite hang | `asyncio.wait_for(agent.run(...), timeout=config.session_timeout)` | `grep 'asyncio.wait_for' agent/runner.py` → match |
| 3: asyncio.run() inside running loop | All agent work via `asyncio.create_task()` inside FastAPI lifespan | No `asyncio.run()` in agent/ |
| 4: litellm supply chain backdoor | Pinned in plan-01; no langchain imports | `grep langchain agent/` → 0 matches |
| 5: Missing num_ctx truncates DOM | `ChatOllama(num_ctx=32000)` mandatory | `grep 'num_ctx=32000' agent/runner.py` → match |

## Requirements Satisfied

| ID | Description | Status |
|----|-------------|--------|
| LOOP-02 | Agent runs screenshot→LLM→action cycle | DONE — run_agent builds and runs browser-use Agent |
| LOOP-03 | BrowserSession(channel="chrome", headless=False) | DONE — grep-enforced |
| LOOP-04 | on_step_end=log_step wired to agent.run | DONE — unit-tested |
| LOOP-05 | max_steps=config.max_steps (default 25) | DONE — unit-tested |
| LOOP-06 | asyncio.wait_for(timeout=config.session_timeout) | DONE — grep-enforced + unit-tested |
| MODEL-01 | ChatOllama(model=config.ollama_model, num_ctx=32000) | DONE — grep-enforced + unit-tested |
| MODEL-04 | pre_flight_check with sys.exit(1) + actionable messages | DONE — integration-tested (3 scenarios) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Browser-use class imports moved to module level for test patchability**
- **Found during:** Task 2, writing test_runner.py
- **Issue:** `BrowserSession`, `ChatOllama`, `Agent` were imported inside `run_agent()` body as local imports. `unittest.mock.patch("agent.runner.BrowserSession")` raises `AttributeError` because local imports are not attributes of the module namespace.
- **Fix:** Moved imports to module level in `runner.py`. Same fix applied to `run_agent` import in `main.py` (needed for lifespan test). No behavior change — imports are still deferred enough that config loading is not affected.
- **Files modified:** agent/runner.py, agent/main.py
- **Commit:** a4cf5c0

## Known Stubs

None — all stubs from plan-01 have been replaced with real implementations.

## Threat Surface Scan

All threat mitigations from the plan's threat model are applied:
- T-02-01 (DoS — no upper bound): `asyncio.wait_for(timeout=600)` AND `max_steps=25` — both grep-enforced
- T-02-02 (DoS — BrowserSession leak): `finally: await browser.kill()` — tested for success, timeout, and exception paths; `keep_alive=False` enforced
- T-02-03 (EoP — POST /run unauthenticated): documented accept; `host="127.0.0.1"` loopback-only
- T-02-04 (InfoDisc — training JSONL screenshots): `.gitignore` blocks `training/*.jsonl` (plan-01)
- T-02-05 (Spoofing — Ollama impersonation): documented accept; default loopback-only
- T-02-06 (Tampering — malicious prompt): documented accept for Phase 1; Phase 2 adds guardrails
- T-02-07 (Repudiation — log_step failures): append-only writes; `test_log_step_appends_not_overwrites` enforces semantics
- T-02-08 (DoS — DOM truncation via small num_ctx): `num_ctx=32000` mandatory; grep-enforced

No new threat surface introduced beyond what was planned.

## Self-Check: PASSED

Files verified:
- agent/runner.py: EXISTS
- agent/main.py: EXISTS
- agent/__main__.py: EXISTS
- tests/unit/test_runner.py: EXISTS
- tests/unit/test_training_log.py: EXISTS
- tests/integration/test_model_validation.py: EXISTS

Commits verified:
- 65f5361: EXISTS (feat(01-02): implement pre_flight_check and log_step...)
- a4cf5c0: EXISTS (feat(01-02): implement run_agent, wire FastAPI lifespan...)
