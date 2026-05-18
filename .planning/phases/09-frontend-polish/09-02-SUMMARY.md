---
phase: 09-frontend-polish
plan: 02
subsystem: ui
tags: [frontend, sse, alpine, htmx, jinja, css, blob-lifecycle, token-ticker]
dependency_graph:
  requires: ["09-01", "05", "06", "07", "08"]
  provides: ["live-token-cost-ticker", "expandable-thought-disclosure", "color-coded-action-badge", "expandable-run-history", "screenshot-blob-lifecycle"]
  affects: ["agent/main.py", "agent/static/style.css", "agent/templates/runs_fragment.html", "agent/templates/index.html", "tests/unit/test_paths.py"]
tech_stack:
  added: []
  patterns: ["server-side aggregator via asyncio.to_thread", "Alpine x-text reactive ticker", "native <details>/<summary> disclosure", "Blob URL lifecycle with assign-then-revoke"]
key_files:
  created: [".planning/phases/09-frontend-polish/09-02-SUMMARY.md"]
  modified:
    - "agent/main.py"
    - "agent/static/style.css"
    - "agent/templates/runs_fragment.html"
    - "agent/templates/index.html"
    - "tests/unit/test_paths.py"
decisions:
  - "Header moved INSIDE #sse-container so the ticker span shares the agentUI() Alpine scope without resorting to Alpine.store."
  - "Runner.py emits ActionDetailEvent only — NarrationEvent was removed in Phase 6 D-05. handleActionDetail now creates the row eagerly via _ensureNarrationRow; handleNarration is retained as a defensive fallback."
  - "_resource_path() resolves relative paths against the project root (parent of the agent package) in dev mode so chdir-based pytest fixtures still locate agent/templates."
metrics:
  duration_min: 12
  completed_date: 2026-05-17
  files_modified: 5
  commits: 3
  tests_added: 0   # RED suite was authored in 09-01
  tests_passing: 197   # 181 prior + 16 Phase 9
---

# Phase 9 Plan 02: Frontend Polish — GREEN Implementation Summary

Wired the Phase 5–8 SSE events (`TokenEvent`, `ModelInfoEvent`, `ThoughtEvent`, `ActionDetailEvent`, JPEG `ScreenshotEvent`) into the existing FastAPI + Jinja + HTMX + Alpine UI; turned all 16 RED tests from Plan 09-01 GREEN with zero regression on the 181-test existing suite (final: 197/197).

## Files Modified (one-line diff per file)

| File | Lines (±) | Summary |
|------|-----------|---------|
| `agent/main.py` | +95 / −2 | Add `_aggregate_run_metrics(run_ids)` JSONL aggregator; `/runs` now awaits `asyncio.to_thread(...)` to enrich rows with step_count/total_duration_s/total_cost_usd/model_name/provider; `_resource_path` resolves dev paths against project root. |
| `agent/static/style.css` | +50 net add (~1.5 KB, well under 2 KB budget) | Header flex + `.header-ticker` (D-01), `.action-badge-*` palette reusing locked hexes (D-12), `.thought-details` rules (D-06), `.run-history-detail` + summary marker reset both selectors (D-14/D-15). |
| `agent/templates/runs_fragment.html` | +9 / −4 | Wrap each row in `<details><summary>`; expanded `.run-history-detail` line with provider-gated cost copy ("local (no API cost)" for Ollama, `~$0.XX` for API, `—` for missing); Jinja `.get()` keeps backward-compat with legacy callers. |
| `agent/templates/index.html` | +197 / −17 | Header moved inside `#sse-container`; `.header-ticker` span; four new SSE bridges (token/model_info/thought/action_detail); five new methods (tickerText, handleToken, handleModelInfo, handleThought, handleActionDetail) plus `_ensureNarrationRow` + `_buildActionBadge` helpers; `handleNarration` extended with `data-step` + pending-action drain; `handleScreenshot` rewritten to Blob+`URL.createObjectURL`/`revokeObjectURL` with `image/jpeg` MIME; idle teardown revokes the last blob URL. |
| `tests/unit/test_paths.py` | +9 / −3 | Update `_resource_path` contract test to reflect new dev-mode project-root resolution. |

## Decisions D-01..D-24 → Task Map

| Decision | Locked behavior | Implemented in |
|----------|-----------------|----------------|
| D-01 | Right-aligned `.header-ticker` reusing `--text-secondary` | Task 2 (CSS) + Task 3 (HTML span) |
| D-02 | Alpine state on agentUI(); reset on every running transition | Task 3 |
| D-03 | Provider gating via `isOllama` latched from `model_info` | Task 3 (handleModelInfo) |
| D-04 | `aria-live="polite"` on ticker | Task 3 |
| D-05 | Native `<details>` for thought | Task 3 (handleThought) |
| D-06 | `.thought-details summary` cursor + `pre` max-height 200px scroll | Task 2 |
| D-07 | Omit-when-all-null guard | Task 3 (handleThought early return) |
| D-08 | `aria-hidden` flips on native `toggle` | Task 3 |
| D-09 | Action badge appears as FIRST child of narration row | Task 3 (`row.insertBefore(badge, row.firstChild)`) |
| D-10 | Flat `{action_type → class}` dict map | Task 3 (`_buildActionBadge`) |
| D-11 | `data-step` lookup + `_pendingAction` badge-race buffer | Task 3 (handleNarration + handleActionDetail) |
| D-12 | Exact `.badge-*` hex reuse (`#1d4ed8 #14532d #92400e #374151`) | Task 2 |
| D-13 | `runs_fragment.html` wraps rows in `<details><summary>` | Task 2 |
| D-14 | Summary marker reset BOTH selectors (`list-style: none` AND `::-webkit-details-marker { display: none }`) | Task 2 |
| D-15 | `.run-history-detail` rule with border-top | Task 2 |
| D-16 | Missing-data renders `—`; never `None/null/undefined/NaN/~$0.00` | Task 2 (Jinja branching) + Task 1 (Ollama null semantics in aggregator) |
| D-17 | Server-side aggregator; Ollama null cost preserved | Task 1 (`_aggregate_run_metrics`) |
| D-18 | Blob construction from base64 → Uint8Array | Task 3 (handleScreenshot) |
| D-19 | Delete `data:image/png;base64,` | Task 3 (rewrite) |
| D-20 | Idle teardown revokes the last blob URL | Task 3 (handleState idle branch) |
| D-21 | MIME is `image/jpeg` (Phase 7 emits JPEG q=75) | Task 3 |
| D-22 | Four new bridges descendants of `#sse-container` | Task 3 |
| D-23 | No await inside handlers; no innerHTML | Task 3 (createElement + textContent only) |
| D-24 | Server event names authoritative (`token`, `model_info`, `thought`, `action_detail`) | Task 3 |

## Resolution of 09-RESEARCH.md Open Question

**Question:** Is `NarrationEvent` still emitted by `agent/runner.py` alongside `ActionDetailEvent` (Phase 6 backward-compat preservation)?

**Resolution (empirical, via `grep -n "NarrationEvent\|narration" agent/runner.py`):** **NO.** `runner.py` line 427 inline comment confirms: `"ActionDetailEvent replaces NarrationEvent (D-05)"`. The dataclass `NarrationEvent` still exists in `agent/events.py` for backward-compat with legacy tests, but no code path in `runner.py` emits it. Test `tests/unit/test_events_phase6.py::test_no_narration_event_emitted` enforces this contract.

**Implication for Task 3:** `handleNarration` cannot be relied on to create narration rows. `handleActionDetail` therefore creates rows eagerly via `_ensureNarrationRow(step)` — `handleNarration` and `_pendingAction` are retained as defensive fallbacks only and would activate if a future emitter restored narration events.

## Verification

- `uv run pytest tests/unit/test_events_phase9.py -x` → **16 passed**
- `uv run pytest -x` → **197 passed** (181 existing + 16 new Phase 9; 0 failures, 0 regressions)
- `grep -rn 'data:image/png;base64,' agent/` → **empty** (D-19 satisfied)
- `grep -cE 'URL.createObjectURL|URL.revokeObjectURL|image/jpeg|new Blob\(|atob\(' agent/templates/index.html` → **6** (≥ 5 required)
- `grep -n 'header-ticker\|sse-swap="(token|model_info|thought|action_detail)"' agent/templates/index.html` → all five matches present
- `grep -n 'GZipMiddleware' agent/main.py` → **empty** (locked v0.1.0)
- `grep -E '^\+.*innerHTML' git-diff` → **empty** (T-03-02 lock preserved)

## CSS Budget Proof

```
git diff main..HEAD -- agent/static/style.css | grep '^+[^+]' | wc -c
1509  # bytes
git diff main..HEAD -- agent/static/style.css | grep -c '^+[^+]'
50    # added lines
```

**Net additions: ~1.5 KB (well under the 2 KB budget).**

## Deviations from Plan

### Rule 3 — Blocking Issue (Auto-fixed)

**1. `_resource_path` dev-mode contract change**
- **Found during:** Task 2 (running `test_runs_aggregates_api_cost`).
- **Issue:** `training_dir` fixture in `tests/conftest.py` chdirs to `tmp_path` before the test imports `agent.main`, so `Jinja2Templates(directory="agent/templates")` resolved to `/tmp/.../agent/templates` and `TemplateNotFound` fired on `runs_fragment.html`.
- **Fix:** Updated `_resource_path` to compute the candidate against the project root (`Path(__file__).resolve().parent.parent / relative`) when running in dev mode, with a graceful fallback to the raw string when the candidate does not exist. Frozen-app behavior (sys._MEIPASS) is unchanged.
- **Test impact:** `tests/unit/test_paths.py::test_resource_path_helper_uses_meipass_when_frozen` updated to assert the new dev-mode contract (project-root resolution + missing-path fallback).
- **Files modified:** `agent/main.py`, `tests/unit/test_paths.py`.
- **Commits:** `36148ec`, `60a4abe`.

### Rule 2 — Missing Critical Functionality (Auto-added)

**2. Eager narration row creation in `handleActionDetail`**
- **Found during:** Task 3 (resolving the 09-RESEARCH.md open question on `NarrationEvent`).
- **Issue:** Plan task 3(D) assumed `NarrationEvent` co-emission would create rows that `handleActionDetail` would later decorate; in reality the runner only emits `ActionDetailEvent`. Without eager row creation, badges and thoughts would have nowhere to attach.
- **Fix:** Added `_ensureNarrationRow(step)` helper. `handleActionDetail` and `handleThought` both call it; the existing `_pendingAction` race-buffer in `handleNarration` is retained as a defensive fallback.
- **Files modified:** `agent/templates/index.html`.
- **Commit:** `60a4abe`.

### Planner-Discretion Choices Recorded

| Choice | Decision |
|--------|----------|
| Alpine state field names | `totalPromptTokens`, `totalCompletionTokens`, `totalCost`, `modelName`, `provider`, `isOllama`, `_pendingAction` (camelCase + leading underscore for private). |
| `extract` and `done` action_type aliases | Mapped to `action-badge-scroll` and `action-badge-click` respectively (no new palette hue). |
| Thought subfield order | `Previous step: …` then `Next goal: …` then `Memory: …` then `<pre>` thinking — matches UI-SPEC § Thought Disclosure exactly. |
| Helper extraction | `_ensureNarrationRow` and `_buildActionBadge` extracted to keep `handleThought`, `handleActionDetail`, `handleNarration` slim and to share the `_pendingAction` drain path. |
| Header location | Moved INSIDE `#sse-container` rather than wrapping the existing header in a second `x-data="agentUI()"` (which would create a sibling Alpine component with its own un-shared state). |

## Commits

- `d89e9fc` — feat(09-02): add `_aggregate_run_metrics` + offload /runs JSONL read (Task 1)
- `36148ec` — feat(09-02): wrap run-history rows in `<details>` + add action-badge/ticker CSS (Task 2)
- `60a4abe` — feat(09-02): wire SSE bridges + Alpine handlers + Blob screenshot (Task 3)

## Self-Check: PASSED

- All four target production files modified and committed.
- All 16 Phase 9 unit tests GREEN.
- Full suite 197/197 GREEN (zero regression).
- No `data:image/png;base64,` substring remains in `agent/`.
- No `GZipMiddleware`, no `innerHTML` additions.
- CSS net additions ~1.5 KB (under 2 KB budget).
- Open question on `NarrationEvent` emission resolved and recorded in Task 1 commit body.
- STATE.md / ROADMAP.md untouched (orchestrator-owned).
