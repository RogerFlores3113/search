---
phase: 09-frontend-polish
plan: 01
subsystem: tests
tags: [red-scaffold, wave-0, frontend, tdd-red]
requires:
  - tests/unit/test_events_phase8.py (analog)
  - tests/conftest.py training_dir fixture
  - .planning/phases/09-frontend-polish/09-VALIDATION.md (test-name authority)
  - .planning/phases/09-frontend-polish/09-CONTEXT.md (D-01..D-24)
provides:
  - Full Phase 9 RED test suite (16 named tests) driving Plan 02 GREEN
  - jsonl_with_records fixture (reusable across /runs aggregator tests)
affects:
  - tests/unit/test_events_phase9.py (new)
  - tests/conftest.py (one fixture added)
tech-stack:
  added: []
  patterns:
    - "pytest + asyncio_mode='auto' (no @pytest.mark.asyncio)"
    - "httpx.AsyncClient + ASGITransport for /runs endpoint tests"
    - "jinja2.Environment(FileSystemLoader('agent/templates')) for direct fragment render"
    - "Static-asset string assertions on agent/templates/*.html + agent/static/style.css"
key-files:
  created:
    - tests/unit/test_events_phase9.py
    - .planning/phases/09-frontend-polish/09-01-SUMMARY.md
  modified:
    - tests/conftest.py
decisions:
  - "Mirror tests/unit/test_events_phase8.py preamble + helper shape (per 09-PATTERNS.md analog)"
  - "Use Jinja2 Environment(autoescape=True) for direct runs_fragment.html render rather than spinning up FastAPI templates"
  - "Monkeypatch agent.main.history_db.list_runs in /runs tests so the test is hermetic and does not depend on SQLite state"
  - "Patch main_mod.asyncio.to_thread (not asyncio.to_thread globally) to validate the offload contract without breaking the rest of the event loop"
metrics:
  duration: "~12 min"
  completed: 2026-05-17
  tasks_completed: 3
  files_created: 2
  files_modified: 1
  tests_added: 16
---

# Phase 9 Plan 01: Frontend Polish RED Test Scaffold Summary

Authored the full Phase 9 RED test suite (16 tests in `tests/unit/test_events_phase9.py`) and a reusable `jsonl_with_records` conftest fixture, locking the assertion contract for Plan 02 (GREEN) against the design decisions in `09-CONTEXT.md` D-01..D-24 and the locked spec in `09-UI-SPEC.md`. All 16 tests fail today (full RED); the existing 174-test unit suite still passes.

## What Changed

### Task 1 — `jsonl_with_records` fixture (commit `02f6522`)
Added a fixture to `tests/conftest.py` that returns a callable `_make(records: list[dict]) -> Path`. Builds on `training_dir` (which already monkeypatches `agent.runner.TRAINING_FILE`) and writes records as newline-delimited JSON. Used by the three Phase 9 `/runs` aggregator tests to avoid duplicating `_make_runs_jsonl` per-test.

### Task 2 — `/runs` aggregator + `runs_fragment.html` tests (commit `510aff1`)
8 tests authored in `tests/unit/test_events_phase9.py`:

| Test | Validation Row | Decision Lock |
|------|----------------|---------------|
| `test_runs_aggregates_api_cost` | 09-02-01 | D-17 (server aggregator shape) |
| `test_runs_aggregator_ollama_null` | 09-02-01 | D-16 (Ollama null semantics) |
| `test_runs_aggregator_offloaded` | 09-02-02 | Pitfall 3 (`asyncio.to_thread`) |
| `test_runs_fragment_ollama_copy` | 09-03-01 | D-16 (Ollama "local (no API cost)") |
| `test_runs_fragment_api_cost_format` | 09-03-01 | D-15 (`%.2f` format) |
| `test_runs_fragment_uses_details` | 09-03-02 | D-13 (`<details>` wrap) |
| `test_runs_fragment_detail_row` | 09-03-02 | D-15 (`run-history-detail`, `·`, `steps`) |
| `test_runs_fragment_missing_data` | 09-03-02 | D-16 (em-dash, never null/NaN/undefined) |

### Task 3 — Header/Bridge/CSS/Blob static-asset tests (commit `2a9b006`)
8 more tests appended:

| Test | Validation Row | Decision Lock |
|------|----------------|---------------|
| `test_index_has_header_ticker` | 09-04-01 | D-01, D-04 (`header-ticker` + `aria-live="polite"`) |
| `test_index_has_token_handlers` | 09-04-01 | D-22 (`handleToken`, `handleModelInfo`) |
| `test_action_badge_assets_present` | 09-04-02 | D-22, D-11 (`handleActionDetail`, `handleThought`, `data-step`) |
| `test_new_sse_bridges_inside_container` | 09-04-02 | D-22 + Phase 3 D-11 (four bridges descend from `#sse-container`) |
| `test_action_badge_palette_hex` | 09-05-01 | D-12 (locked hexes `#1d4ed8/#14532d/#92400e/#374151` + `action-badge-` prefix) |
| `test_summary_marker_reset_present` | 09-05-01 | D-14, Pitfall 1 (`list-style: none` + `::-webkit-details-marker` + `display: none`) |
| `test_no_data_url_in_index` | 09-06-01 | D-19 (delete `data:image/png;base64,`) |
| `test_handle_screenshot_blob_lifecycle` | 09-06-01 | D-18..D-21 (`URL.createObjectURL`, `URL.revokeObjectURL`, `image/jpeg`, `new Blob(`, `atob(`) |

## RED Confirmation

First failing assertion from `uv run pytest tests/unit/test_events_phase9.py::test_runs_fragment_uses_details -x`:

```
E       AssertionError: runs_fragment.html must wrap each run row in a <details> element (D-13)
E       assert '<details' in '{% if runs %}\n<ul class="run-history-list">\n  {% for run in runs %}\n  <li class="run-history-item">\n    <span cla...'
```

Full suite result: `16 failed in 1.05s` — full RED. The existing unit suite (`tests/unit/ --ignore=tests/unit/test_events_phase9.py`) reports `174 passed` (no regression).

## Deviations from Plan

None — the plan was executed exactly as written. Notes on Claude's discretion within the spec:

- **`asyncio.to_thread` patching strategy** (Task 2, `test_runs_aggregator_offloaded`): patched `agent.main.asyncio.to_thread` (the module-bound symbol) rather than `asyncio.to_thread` globally. This is the hermetic pattern — patching globally would break unrelated event-loop machinery during the AsyncClient context. Plan 02's aggregator MUST call `asyncio.to_thread` via the `asyncio` module attribute (which it will — that is the documented import shape in `agent/main.py`).
- **`_aggregate_run_metrics` name assertion**: the offload test asserts `first_arg.__name__ == "_aggregate_run_metrics"`. This matches 09-PATTERNS.md `agent/main.py` § "Helper `_aggregate_run_metrics(run_ids: set[str]) -> dict[str, dict]`" verbatim. Plan 02 must use exactly this helper name.
- **Test count reconciliation**: 09-VALIDATION.md row 09-04-02 lists `test_action_badge_assets_present` AND `test_new_sse_bridges_inside_container`; both are included. The plan asks for 16 tests total (8 in Task 2, 8 in Task 3) — delivered exactly.

## Notes for Plan 02 (GREEN)

When Plan 02 lands, every test in this file should flip green WITHOUT modifying the tests. Anchor points the GREEN implementer cannot change without also touching this RED file:

1. **`/runs` aggregator** must populate `step_count`, `total_duration_s`, `total_cost_usd`, `model_name`, `provider` on each run dict and wrap the JSONL read in `asyncio.to_thread(_aggregate_run_metrics, run_ids)`.
2. **`runs_fragment.html`** must use `<details><summary>...</summary><div class="run-history-detail">{step_count} steps · {total_duration_s}s · ... · {model_name}</div></details>` with provider-gated cost branch (`local (no API cost)` for ollama; `~${{ '%.2f' % cost }}` for API; `—` for missing).
3. **`index.html`** must add `<span class="header-ticker" aria-live="polite">`, four new SSE bridges (`token`, `model_info`, `thought`, `action_detail`) as descendants of `#sse-container`, four matching handlers (`handleToken`, `handleModelInfo`, `handleThought`, `handleActionDetail`), `data-step` on narration rows, and the `handleScreenshot` rewrite using `URL.createObjectURL` / `URL.revokeObjectURL` / `new Blob([bytes], {type: 'image/jpeg'})` / `atob(d.b64)`. The line `img.src = 'data:image/png;base64,' + d.b64` must be deleted.
4. **`style.css`** must add `.action-badge-*` classes with the four locked hex values, plus `summary { list-style: none }` and `summary::-webkit-details-marker { display: none }` to preserve the flex layout under `<details>`.

## Self-Check: PASSED

Files verified to exist on disk:
- `tests/unit/test_events_phase9.py` — FOUND
- `tests/conftest.py` (with `jsonl_with_records` fixture) — FOUND
- `.planning/phases/09-frontend-polish/09-01-SUMMARY.md` — being written

Commits verified in git log:
- `02f6522` test(09-01): add jsonl_with_records fixture — FOUND
- `510aff1` test(09-01): add Phase 9 RED tests for /runs aggregator + runs_fragment — FOUND
- `2a9b006` test(09-01): add Phase 9 RED tests for header ticker, badges, blob lifecycle — FOUND
