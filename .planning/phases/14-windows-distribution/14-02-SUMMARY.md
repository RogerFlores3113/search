---
phase: 14
plan: "02"
subsystem: distribution
tags: [windows, pyinstaller, spec, win-01]
dependency_graph:
  requires: [14-00]
  provides: [local-browser-agent-windows.spec, WIN-01]
  affects: [release-workflow]
tech_stack:
  added: []
  patterns: [pyinstaller-onedir, windows-spec-mirror]
key_files:
  created: [local-browser-agent-windows.spec]
  modified: []
decisions:
  - "Removed literal BUNDLE( from comments to satisfy test_windows_spec_has_no_bundle assertion — test checks string presence anywhere in file, not just code"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-19"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 14 Plan 02: Windows PyInstaller Spec Summary

Windows PyInstaller spec file (`local-browser-agent-windows.spec`) created — 90-line onedir EXE+COLLECT build recipe mirroring the macOS spec exactly minus the BUNDLE block.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author local-browser-agent-windows.spec | 1b19474 | local-browser-agent-windows.spec (created, 90 lines) |

## File Created

**`local-browser-agent-windows.spec`** — 90 lines

Structure:
- **Block 1 (lines 1-12):** File header comment with Windows-specific rationale (upx=False, onedir mode, console=False), `import sys`, `block_cipher = None`
- **Block 2 (lines 14-62):** `a = Analysis(...)` — entrypoint `agent/__main__.py`, datas for templates and static, 20 hiddenimports identical to macOS spec
- **Block 3 (lines 64-88):** `pyz = PYZ(...)`, `exe = EXE(...)` (console=False, upx=False, exclude_binaries=True), `coll = COLLECT(...)` (upx=False)
- **Block 4 (line 90):** Trailing comment noting no BUNDLE block and Windows output path

## hiddenimports Match Confirmation

The 20 hiddenimports in the Windows spec are byte-identical to the macOS spec:
`uvicorn.logging`, `uvicorn.loops`, `uvicorn.loops.auto`, `uvicorn.protocols`, `uvicorn.protocols.http`, `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets`, `uvicorn.protocols.websockets.auto`, `uvicorn.lifespan`, `uvicorn.lifespan.on`, `aiosqlite`, `platformdirs`, `browser_use.browser.session`, `browser_use.browser.profile`, `browser_use.agent.service`, `browser_use.controller.service`, `browser_use.dom.service`, `cdp_use`, `cdp_use.client`, `cdp_use.cdp`

Test `test_hiddenimports_match` confirms set equality between the two spec files.

## Test Transitions: RED → GREEN

All 6 WIN-01 tests in `tests/unit/test_windows_spec_phase14.py` transitioned from RED to GREEN:

| Test | Status |
|------|--------|
| `test_windows_spec_file_exists` | RED → GREEN |
| `test_windows_spec_has_exe_and_collect` | RED → GREEN |
| `test_windows_spec_has_no_bundle` | RED → GREEN |
| `test_windows_spec_upx_false` | RED → GREEN |
| `test_windows_spec_console_false` | RED → GREEN |
| `test_hiddenimports_match` | RED → GREEN |

## Developer Note

Running `uv run pyinstaller local-browser-agent-windows.spec` on Windows produces `dist\local-browser-agent\local-browser-agent.exe` (onedir mode). On macOS, this build will fail — PyInstaller does not support cross-platform builds. This is expected and not a regression. The macOS spec (`local-browser-agent.spec`) remains the build target for macOS.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Rephrase comments containing literal "BUNDLE(" substring**

- **Found during:** Task 1 (first test run)
- **Issue:** The plan specified adding two comments containing the literal string `BUNDLE(` — one in the file header ("mirrors local-browser-agent.spec minus BUNDLE()") and one trailing comment ("No BUNDLE() — that is macOS-only"). The test `test_windows_spec_has_no_bundle` asserts `"BUNDLE(" not in content` for the entire file, not just code lines. Comments are included in the content check.
- **Fix:** Rephrased both comments to convey identical meaning without the literal substring: header uses "minus the macOS-only BUNDLE block"; trailing comment uses "No macOS BUNDLE block here"
- **Files modified:** `local-browser-agent-windows.spec`
- **Commit:** 1b19474

## Threat Surface Scan

No new threat surface introduced. The spec file is build-time configuration only; T-14-02-03 (UPX false positives) and T-14-02-04 (onedir startup performance) mitigations are in place as required.

## Self-Check: PASSED

- `local-browser-agent-windows.spec` exists: FOUND
- Commit 1b19474 exists: FOUND
- `uv run pytest tests/unit/test_windows_spec_phase14.py -q` exits 0: CONFIRMED (6 passed)
- `python -c "import ast; ast.parse(...)"` exits 0: CONFIRMED
- macOS spec unchanged: CONFIRMED (git diff shows no changes)
