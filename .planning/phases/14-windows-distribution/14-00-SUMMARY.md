---
phase: 14
plan: "00"
subsystem: testing
tags: [tdd, red-scaffold, windows, distribution, phase14]
dependency_graph:
  requires: []
  provides:
    - RED test scaffold for WIN-01 (Windows spec file structure)
    - RED test scaffold for WIN-02 (freeze_support, stdout redirect, use_colors=False)
    - RED test scaffold for WIN-03 (Windows Chrome detection)
    - RED test scaffold for WIN-04 (CI build jobs in release.yml)
  affects:
    - tests/unit/test_chrome_detect.py
    - tests/unit/test_entrypoint_phase14.py
    - tests/unit/test_windows_spec_phase14.py
    - tests/unit/test_release_workflow_phase14.py
tech_stack:
  added: []
  patterns:
    - AST parse for entrypoint structure validation
    - YAML parse (yaml.safe_load) for CI workflow structure validation
    - monkeypatch + importlib.reload for frozen-app entrypoint tests
    - regex hiddenimports extraction for cross-spec comparison
key_files:
  created:
    - tests/unit/test_entrypoint_phase14.py
    - tests/unit/test_windows_spec_phase14.py
    - tests/unit/test_release_workflow_phase14.py
  modified:
    - tests/unit/test_chrome_detect.py
decisions:
  - Pre-import agent.__main__ before setting sys.frozen=True to avoid _MEIPASS lookup during cold import (agent.main uses sys._MEIPASS if frozen)
  - PyYAML (6.0.3) confirmed available as transitive dep — no pyproject.toml change needed
  - test_windows_chrome_missing is the sole failing RED test for WIN-03 because the other 3 Windows tests assert True (which the placeholder also returns); the RED gate is satisfied by the missing=False assertion
metrics:
  duration: ~15 minutes
  completed_date: "2026-05-19"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 14 Plan 00: Wave 0 RED Test Scaffolding Summary

Wave 0 RED test scaffold for Phase 14 Windows distribution — 4 test files covering WIN-01 through WIN-04, all failing before any implementation. Nyquist lock-in: each subsequent Plan (01-03) turns specific tests GREEN.

## Tests Created

### tests/unit/test_chrome_detect.py (extended — WIN-03)

4 new test functions appended after `test_non_darwin_passthrough`:

| Function | Asserts | RED state |
|----------|---------|-----------|
| `test_windows_localappdata_found` | `chrome_is_installed()` returns True when LOCALAPPDATA path exists | passes (placeholder also returns True) |
| `test_windows_programfiles_fallback` | returns True when only PROGRAMFILES path exists | passes (placeholder also returns True) |
| `test_windows_x86_fallback` | returns True when only ProgramFiles(x86) path exists | passes (placeholder also returns True) |
| `test_windows_chrome_missing` | returns False when no Windows path exists | **FAILS** (placeholder returns True unconditionally) |

Existing 3 tests (test_chrome_present, test_chrome_missing, test_non_darwin_passthrough) unchanged and passing.

Commit: `c5ff41a`

### tests/unit/test_entrypoint_phase14.py (new — WIN-02)

3 test functions:

| Function | Asserts | RED state |
|----------|---------|-----------|
| `test_freeze_support_is_first` | AST: first statement in `if __name__ == "__main__":` is `multiprocessing.freeze_support()` | **FAILS** (first statement is `main()`) |
| `test_stdout_redirect_in_frozen_guard` | frozen=True → app.log created, sys.stderr is sys.stdout | **FAILS** (no redirect implemented) |
| `test_uvicorn_use_colors_false` | uvicorn.run() called with use_colors=False | **FAILS** (kwarg not present) |

Commit: `3f6009b`

### tests/unit/test_windows_spec_phase14.py (new — WIN-01)

6 test functions:

| Function | Asserts | RED state |
|----------|---------|-----------|
| `test_windows_spec_file_exists` | Path("local-browser-agent-windows.spec").exists() | **FAILS** (file does not exist) |
| `test_windows_spec_has_exe_and_collect` | contains "exe = EXE(" and "coll = COLLECT(" | **FAILS** (FileNotFoundError) |
| `test_windows_spec_has_no_bundle` | does NOT contain "BUNDLE(" | **FAILS** (FileNotFoundError) |
| `test_windows_spec_upx_false` | upx=False appears >= 2 times | **FAILS** (FileNotFoundError) |
| `test_windows_spec_console_false` | contains "console=False" | **FAILS** (FileNotFoundError) |
| `test_hiddenimports_match` | hiddenimports sets are equal between Mac and Windows spec | **FAILS** (FileNotFoundError) |

Commit: `ada848e`

### tests/unit/test_release_workflow_phase14.py (new — WIN-04)

7 test functions:

| Function | Asserts | RED state |
|----------|---------|-----------|
| `test_build_mac_and_windows_jobs_exist` | "build-mac" and "build-windows" in workflow["jobs"] | **FAILS** |
| `test_jobs_depend_on_test` | both jobs declare needs: test | **FAILS** (KeyError: build-mac) |
| `test_jobs_have_tag_condition` | both jobs have if: startsWith(github.ref, 'refs/tags/v') | **FAILS** (KeyError) |
| `test_jobs_have_write_permissions` | both jobs have permissions.contents == "write" | **FAILS** (KeyError) |
| `test_build_windows_uses_windows_runner` | build-windows runs-on == "windows-latest" | **FAILS** (KeyError) |
| `test_build_mac_uses_macos_runner` | build-mac runs-on == "macos-latest" | **FAILS** (KeyError) |
| `test_build_windows_uses_windows_spec` | steps include "local-browser-agent-windows.spec" | **FAILS** (KeyError) |

Commit: `ada848e`

## RED Count Summary

| File | Failing (RED) | Passing | Total |
|------|--------------|---------|-------|
| test_chrome_detect.py (extended) | 1 | 6 | 7 |
| test_entrypoint_phase14.py | 3 | 0 | 3 |
| test_windows_spec_phase14.py | 6 | 0 | 6 |
| test_release_workflow_phase14.py | 7 | 0 | 7 |
| **Total** | **17** | **6** | **23** |

Success criterion: ≥ 12 failures across the 4 files. **Actual: 17 failures.**

## pyproject.toml Changes

None — PyYAML 6.0.3 is already available as a transitive pytest dependency. No explicit dev dep addition needed.

## Pre-Phase-14 Test Suite Confirmation

Running the pre-Phase-14 suite (excluding new Phase 14 test files):
- Existing chrome_detect tests (3): all PASS
- Pre-existing failures (test_events_phase8.py x3, test_events_phase5.py x1, test_events_phase9.py x1, test_runner.py x6, test_launcher.py::test_main_redirects_paths_when_frozen x1, others): pre-existing before Phase 14; NOT introduced by this plan
- No new regressions introduced by this plan's changes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-import agent.__main__ before setting sys.frozen=True**

- **Found during:** Task 2 — first run of test_stdout_redirect_in_frozen_guard
- **Issue:** Setting `sys.frozen=True` before importing `agent.__main__` caused `agent.main` to call `_resource_path()` which tried to read `sys._MEIPASS` (frozen-only attribute), raising `AttributeError: module 'sys' has no attribute '_MEIPASS'`
- **Fix:** Pre-import and reload `agent.__main__` with `frozen=False` first (so `agent.main` gets cached in sys.modules), then set `frozen=True` and reload again — matching the pattern used by test_launcher.py
- **Files modified:** tests/unit/test_entrypoint_phase14.py
- **Commit:** 3f6009b

## Known Stubs

None — this plan creates tests only, no implementation stubs.

## Threat Flags

No new threat surface introduced — test files only, no production endpoints, auth paths, or storage changes.

## Self-Check: PASSED

- tests/unit/test_chrome_detect.py — modified, exists ✓
- tests/unit/test_entrypoint_phase14.py — created, exists ✓
- tests/unit/test_windows_spec_phase14.py — created, exists ✓
- tests/unit/test_release_workflow_phase14.py — created, exists ✓
- Commits c5ff41a, 3f6009b, ada848e — all present in git log ✓
- Total RED failures: 17 (≥ 12 required) ✓
- No pyproject.toml changes needed ✓
