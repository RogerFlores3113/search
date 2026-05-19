---
phase: 14
plan: "01"
subsystem: distribution
tags: [windows, pyinstaller, frozen-app, chrome-detection, WIN-02, WIN-03]
dependency_graph:
  requires: ["14-00"]
  provides: ["WIN-02", "WIN-03"]
  affects: ["agent/__main__.py", "agent/chrome_detect.py"]
tech_stack:
  added: []
  patterns:
    - "freeze_support() as first statement in if __name__ == '__main__': (PyInstaller Windows)"
    - "sys.stdout/stderr redirect to app.log before uvicorn start (console=False frozen guard)"
    - "uvicorn.run() use_colors=False (prevents ColourizedFormatter crash on frozen Windows)"
    - "os.environ.get() for safe env var access in frozen context (no KeyError on stripped envs)"
key_files:
  modified:
    - agent/__main__.py
    - agent/chrome_detect.py
decisions:
  - "use_colors=False applied unconditionally (not inside frozen guard) per RESEARCH.md Open Q1 — simpler code path; cosmetic only"
  - "sys.stdout redirect placed BEFORE logging.basicConfig inside frozen guard — matches Pattern 2 ordering requirement"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-19"
  tasks_completed: 2
  files_modified: 2
---

# Phase 14 Plan 01: WIN-02 + WIN-03 Runtime Fixes Summary

**One-liner:** freeze_support + stdout/stderr redirect + uvicorn use_colors=False in __main__.py; Windows Chrome detection via LOCALAPPDATA/PROGRAMFILES/ProgramFiles(x86) in chrome_detect.py.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | WIN-02: freeze_support + stdout redirect + use_colors=False | aca199a | agent/__main__.py |
| 2 | WIN-03: Windows Chrome detection | 82297c4 | agent/chrome_detect.py |

## agent/__main__.py Changes (WIN-02)

**Change A — import multiprocessing:** Added `import multiprocessing` in the stdlib block after `import sys`.

**Change B — stdout/stderr redirect:** Inserted inside `if getattr(sys, "frozen", False):` block, BEFORE `logging.basicConfig()`:
```python
sys.stdout = open(log_path, "a", encoding="utf-8")  # noqa: WPS515
sys.stderr = sys.stdout
```
Dev mode is unaffected (guard is `if frozen`). Encoding is explicit UTF-8 to avoid cp1252 issues on Windows.

**Change C — uvicorn.run() use_colors=False:** Added as keyword argument unconditionally (per RESEARCH.md Open Q1 — cosmetic-only impact on dev mode). Reformatted the call across multiple lines.

**Change D — freeze_support() first:** Added `multiprocessing.freeze_support()` as first statement in `if __name__ == "__main__":`, before `main()`.

## agent/chrome_detect.py Changes (WIN-03)

**New helper `_windows_chrome_paths() -> list[str]`:** Inserted before `chrome_is_installed()`. Iterates `("LOCALAPPDATA", "PROGRAMFILES", "ProgramFiles(x86)")` using `os.environ.get()` (not `[]`) for frozen-context safety. Returns candidate paths list.

**Updated `chrome_is_installed()`:** Replaced non-macOS placeholder `return True` with:
- `if sys.platform == "win32": return any(os.path.exists(p) for p in _windows_chrome_paths())`
- `return True  # Linux/other: don't block`

**Updated docstrings:** Module-level and function docstrings updated to remove "deferred to PLAT-01/02" language and document Windows coverage.

## WIN-02 / WIN-03 RED → GREEN Test Transition

| Test File | Test Name | Requirement | Status |
|-----------|-----------|-------------|--------|
| test_entrypoint_phase14.py | test_freeze_support_is_first | WIN-02 | RED → GREEN |
| test_entrypoint_phase14.py | test_stdout_redirect_in_frozen_guard | WIN-02 | RED → GREEN |
| test_entrypoint_phase14.py | test_uvicorn_use_colors_false | WIN-02 | RED → GREEN |
| test_chrome_detect.py | test_windows_localappdata_found | WIN-03 | RED → GREEN |
| test_chrome_detect.py | test_windows_programfiles_fallback | WIN-03 | RED → GREEN |
| test_chrome_detect.py | test_windows_x86_fallback | WIN-03 | RED → GREEN |
| test_chrome_detect.py | test_windows_chrome_missing | WIN-03 | RED → GREEN |

Previously passing tests (no regression):
- test_launcher.py: 4 tests still pass
- test_chrome_detect.py: 3 original darwin/passthrough tests still pass

## Deviations from Plan

None — plan executed exactly as written. All four changes match the 14-PATTERNS.md target snippets verbatim.

## Known Stubs

None.

## Threat Flags

None. Changes are confined to entrypoint startup logic and a utility helper — no new network endpoints, auth paths, or file access patterns beyond existing app.log behavior.

## Self-Check: PASSED

- agent/__main__.py: FOUND
- agent/chrome_detect.py: FOUND
- Commit aca199a (feat(14-01): WIN-02): FOUND
- Commit 82297c4 (feat(14-01): WIN-03): FOUND
