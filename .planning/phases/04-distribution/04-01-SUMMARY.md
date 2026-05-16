---
phase: 04-distribution
plan: 01
subsystem: infra
tags: [pyinstaller, platformdirs, chrome-detection, frozen-app, disclaimer, localStorage, alpine-js]

# Dependency graph
requires:
  - phase: 03-browser-control
    provides: "FastAPI app, agent runner, DB, SSE streaming UI"
provides:
  - "agent/paths.py: get_user_data_dir() for frozen/dev path resolution"
  - "agent/chrome_detect.py: chrome_is_installed() pre-flight check"
  - "agent/launcher.py: schedule_browser_open() threading.Timer scheduler"
  - "agent/templates/no_chrome.html: Chrome-missing fallback page"
  - "agent/templates/index.html: one-time disclaimer modal gated by Alpine.js + localStorage"
  - "local-browser-agent.spec: PyInstaller spec with playwright driver + templates/static datas"
  - "Frozen-aware DB_PATH and TRAINING_FILE via agent.paths"
  - "_resource_path() helper in agent/main.py for Jinja2 + StaticFiles under sys._MEIPASS"
affects: [04-distribution-plan-02, CI-release-pipeline]

# Tech tracking
tech-stack:
  added:
    - platformdirs==4.9.6 (dev dep — user_data_dir cross-platform resolution)
    - pyinstaller==6.20.0 (dev dep — .app bundle builder)
  patterns:
    - "Frozen-app path resolution: getattr(sys, 'frozen', False) → platformdirs vs Path('data')"
    - "_resource_path(relative) helper for Jinja2Templates + StaticFiles under sys._MEIPASS"
    - "threading.Timer(delay, webbrowser.open, args=[url]) for non-blocking browser open"
    - "Alpine.js x-data disclaimer gate via localStorage.getItem('disclaimer_accepted')"
    - "app.state.chrome_missing flag set in __main__ before uvicorn, read in GET / route"

key-files:
  created:
    - agent/paths.py
    - agent/chrome_detect.py
    - agent/launcher.py
    - agent/templates/no_chrome.html
    - local-browser-agent.spec
    - tests/unit/test_paths.py
    - tests/unit/test_chrome_detect.py
    - tests/unit/test_disclaimer.py
    - tests/unit/test_launcher.py
    - tests/unit/test_no_chrome_page.py
  modified:
    - agent/db.py (DB_PATH via get_user_data_dir)
    - agent/runner.py (TRAINING_FILE via get_user_data_dir)
    - agent/main.py (_resource_path helper, chrome_missing route, app.state default)
    - agent/__main__.py (redirect_data_paths, chrome check, schedule_browser_open, file logging)
    - agent/templates/index.html (disclaimer modal + Alpine gate)
    - pyproject.toml (platformdirs + pyinstaller in dev deps)
    - uv.lock (updated)
    - tests/conftest.py (training_dir fixture monkeypatches runner.TRAINING_FILE)
    - tests/integration/test_end_to_end.py (monkeypatches TRAINING_FILE to tmp_path)

key-decisions:
  - "DB_PATH and TRAINING_FILE computed as module-level constants via get_user_data_dir() — tests monkeypatch runner.TRAINING_FILE rather than chdir"
  - "app.state.chrome_missing initialized to False at module level in main.py so TestClient works without __main__.py"
  - "init_db() re-calls DB_PATH.parent.mkdir() for test chdir safety (idempotent, safe)"
  - "upx=False in PyInstaller spec — UPX not installed by default on macOS, can break codesign"
  - "Chrome detection non-darwin path returns True (deferred to PLAT-01/02)"

patterns-established:
  - "Pattern: frozen path redirect — get_user_data_dir() switches on getattr(sys, 'frozen', False)"
  - "Pattern: _resource_path(relative) helper for bundle-relative asset paths"
  - "Pattern: monkeypatch runner.TRAINING_FILE in tests that write JSONL (vs monkeypatch.chdir)"
  - "Pattern: app.state flag set pre-uvicorn in __main__, read in FastAPI routes"

requirements-completed: [DIST-01, DIST-02, DIST-03, DIST-04]

# Metrics
duration: ~45min
completed: 2026-05-16
---

# Phase 04 Plan 01: Distribution Foundation Summary

**PyInstaller .app spec + frozen path redirection (platformdirs), Chrome detection with no_chrome.html fallback, threading.Timer browser auto-open, and one-time Alpine.js localStorage disclaimer modal**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-16
- **Completed:** 2026-05-16
- **Tasks:** 5 of 5 auto tasks (Task 6 is human checkpoint)
- **Files modified:** 18

## Accomplishments

- Frozen path redirection: DB_PATH and TRAINING_FILE resolve under `~/Library/Application Support/local-browser-agent/` when `sys.frozen=True`, `./data/` in dev
- Chrome detection: `chrome_is_installed()` checks standard macOS path; `no_chrome.html` served when missing
- Browser auto-open: `schedule_browser_open()` fires `webbrowser.open` on a daemon thread 2s after uvicorn binds
- One-time disclaimer modal: Alpine.js + localStorage gate on index.html ("Before You Begin" with will-not list and stop/pause reassurance)
- PyInstaller spec: `collect_data_files("playwright")` for driver, templates, static, hiddenimports for uvicorn/aiosqlite/platformdirs
- 106 tests pass (17 new, full suite green)

## Task Commits

1. **Task 1: Test scaffolding + dev deps + agent/paths.py** - `21dbc4d` (feat)
2. **Task 2: Wire frozen-aware paths into db.py, runner.py, main.py** - `0e777b4` (feat)
3. **Task 3: Chrome detection + no_chrome page + disclaimer modal** - `5c0feab` (feat)
4. **Task 4: Launcher + frozen-aware __main__.py** - `27aabc9` (feat)
5. **Task 5: PyInstaller spec file** - `2f61859` (feat)

## Files Created/Modified

- `agent/paths.py` — APP_NAME + get_user_data_dir() frozen/dev resolution
- `agent/chrome_detect.py` — CHROME_PATH_MACOS + chrome_is_installed()
- `agent/launcher.py` — schedule_browser_open() threading.Timer
- `agent/templates/no_chrome.html` — Chrome-missing page with google.com/chrome link
- `agent/templates/index.html` — added Alpine.js disclaimer modal gate
- `local-browser-agent.spec` — PyInstaller spec with playwright datas + BUNDLE
- `agent/db.py` — DB_PATH via get_user_data_dir(); init_db() re-mkdirs for chdir safety
- `agent/runner.py` — TRAINING_FILE via get_user_data_dir(); mkdir via TRAINING_FILE.parent
- `agent/main.py` — _resource_path() helper; app.state.chrome_missing; conditional GET /
- `agent/__main__.py` — redirect_data_paths(), chrome check, schedule_browser_open, file logging
- `pyproject.toml` — added platformdirs>=4.9.6 and pyinstaller==6.20.0 to dev deps
- `uv.lock` — updated with pyinstaller, platformdirs, altgraph, macholib, etc.
- `tests/conftest.py` — training_dir fixture monkeypatches runner.TRAINING_FILE
- `tests/integration/test_end_to_end.py` — monkeypatches TRAINING_FILE to tmp_path

## Decisions Made

- **Module-level constants for TRAINING_FILE/DB_PATH:** Computed at import via get_user_data_dir(). Tests monkeypatch the module attribute rather than relying on chdir. This is the correct pattern for frozen-mode where the path must be known at import time.
- **app.state.chrome_missing initialized at module level:** Ensures TestClient-based tests work without running through __main__. The attribute is always present so routes can safely call getattr(..., False).
- **init_db() re-calls mkdir:** get_user_data_dir() mkdir's at import time, but tests chdir after import. Re-calling mkdir inside init_db() is idempotent and safe, making the integration test reliable.
- **upx=False:** Explicitly disabled in spec — UPX causes codesign failures on macOS if not pre-installed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Integration test failed after TRAINING_FILE became module-level constant**
- **Found during:** Task 2 (wire frozen paths into db.py/runner.py)
- **Issue:** `TRAINING_FILE = get_user_data_dir() / "training" / "runs.jsonl"` is set at module import time. The integration test uses `monkeypatch.chdir(tmp_path)` after import, so TRAINING_FILE pointed to the original cwd's `data/training/runs.jsonl`, not `tmp_path/training/runs.jsonl`. Test failed on missing file assertion.
- **Fix:** Updated `tests/conftest.py` `training_dir` fixture to monkeypatch `runner.TRAINING_FILE` to `tmp_path / "training" / "runs.jsonl"`. Updated integration test to do the same.
- **Files modified:** tests/conftest.py, tests/integration/test_end_to_end.py
- **Verification:** `uv run pytest tests/ -q` → 95 passed after fix, 106 passed at end of plan
- **Committed in:** `0e777b4` (Task 2 commit)

**2. [Rule 1 - Bug] sqlite3.OperationalError when init_db() ran after test chdir**
- **Found during:** Task 2 (same root cause as above)
- **Issue:** After `monkeypatch.chdir(tmp_path)`, `DB_PATH` (relative `data/history.db`) resolved to `tmp_path/data/history.db` but the directory didn't exist. `init_db()` tried to connect and failed with `unable to open database file`.
- **Fix:** Added `DB_PATH.parent.mkdir(parents=True, exist_ok=True)` back to `init_db()` — idempotent and ensures the directory exists regardless of when cwd changes.
- **Files modified:** agent/db.py
- **Verification:** Integration test passes after fix
- **Committed in:** `0e777b4` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs introduced by the module-level constant change)
**Impact on plan:** Both fixes were necessary for correctness. No scope creep. The underlying design (module-level constants + monkeypatch in tests) is correct and consistent with the plan's test architecture.

## Known Stubs

None — all plan features are wired. Chrome detection on non-darwin returns True pending PLAT-01/PLAT-02 (documented deferral in research, not a stub).

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model. The disclaimer modal is localStorage-gated (T-04-06 accepted), no new endpoints, no new auth paths.

## Issues Encountered

- threading.Timer test required `t.join(timeout=2.0)` to wait for the 10ms timer to fire — simple, no issue.
- The `xfail` stub test files were replaced with real tests across Tasks 3-4 as designed.

## User Setup Required

None — all changes are code-only. The human macOS smoke test (Task 6) is the only external requirement and is documented as a checkpoint, not user setup.

## Next Phase Readiness

- `local-browser-agent.spec` is committed and ready for `uv run pyinstaller --clean --noconfirm local-browser-agent.spec` on a developer Mac (Task 6 human checkpoint)
- After Task 6 approval, Plan 02 (CI/CD release pipeline) can wire the same spec into GitHub Actions
- Open Question 2 from research (Playwright v6 macOS hook compatibility) will be answered during Task 6

---
*Phase: 04-distribution*
*Completed: 2026-05-16*
