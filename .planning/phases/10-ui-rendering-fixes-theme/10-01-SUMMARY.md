---
phase: 10-ui-rendering-fixes-theme
plan: "01"
subsystem: testing
tags: [pytest, css, html, tdd, red-tests, phase10]

requires:
  - phase: 09-frontend-polish
    provides: "tests/unit/test_events_phase9.py with test_action_badge_palette_hex to update"
  - phase: 09.1-close-gap-perf-01-wire-step-duration-ms-to-actiondetailevent
    provides: "Final baseline: agent/static/style.css and agent/templates/index.html current state"

provides:
  - "14 RED acceptance tests in tests/unit/test_events_phase10.py covering FIX-01..04 and THEME-01..05"
  - "Updated test_action_badge_palette_hex asserting unified blue #1d4ed8 palette and absence of legacy hues"

affects:
  - 10-02 (GREEN implementation plan — must pass all 14 tests from this plan)
  - 10-03 (verification — runs full suite including these tests)

tech-stack:
  added: []
  patterns:
    - "Phase 10 test pattern: pathlib.Path read + rule-body slice via brace-depth walk for JS function body isolation"
    - "Negative badge assertion: extract CSS rule body from class start to closing }, assert legacy hex absent within slice"

key-files:
  created:
    - tests/unit/test_events_phase10.py
  modified:
    - tests/unit/test_events_phase9.py

key-decisions:
  - "Used brace-depth walk (not fixed-char-window) for JS function body extraction in test_model_info_precedes_token — fixed-window was too wide and captured adjacent handleModelInfo body, causing false GREEN"
  - "Negative badge assertions use extracted CSS rule body (brace-to-close) rather than full-file string match — prevents false negatives from unrelated rules containing same hex values"

patterns-established:
  - "Phase RED tests must be verified as genuinely failing before commit — test_model_info_precedes_token initially PASSED due to 600-char window spilling into handleModelInfo; fixed by brace-depth walk"

requirements-completed: [FIX-01, FIX-02, FIX-03, FIX-04, THEME-01, THEME-02, THEME-03, THEME-04, THEME-05]

duration: 4min
completed: 2026-05-19
---

# Phase 10, Plan 01: RED Test Scaffold Summary

**14 acceptance tests locking Phase 10 CSS/HTML requirements (all RED), plus updated badge palette test in phase9 suite — brace-depth JS body extraction replaced naive char-window to prevent false GREEN**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-19T02:05:46Z
- **Completed:** 2026-05-19T02:09:05Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `tests/unit/test_events_phase10.py` with 14 source-state string-search assertions covering all 9 Phase 10 requirements (FIX-01 through THEME-05)
- All 14 tests confirmed RED against current production code — no false GREENs
- Updated `test_action_badge_palette_hex` in phase9 suite to assert unified blue palette (#1d4ed8) and absence of legacy multi-color hues from .action-badge-* rules
- All 18 other tests in test_events_phase9.py continue passing; the 3 pre-existing failures in test_events_phase8.py unchanged

## Task Commits

1. **Task 1: Create tests/unit/test_events_phase10.py with 14 RED assertions** - `0b87a6a` (test)
2. **Task 2: Update test_action_badge_palette_hex to assert new blue-only palette** - `c1b5de6` (test)

## Files Created/Modified

- `tests/unit/test_events_phase10.py` — 14 new RED acceptance tests for FIX-01..04 and THEME-01..05 via CSS/HTML string-search assertions
- `tests/unit/test_events_phase9.py` — Updated `test_action_badge_palette_hex` to assert unified blue palette; added per-rule negative assertions for legacy hues

## Decisions Made

- Used brace-depth walk (not 600-char string window) for JS function body isolation in `test_model_info_precedes_token` — the naive window included the adjacent `handleModelInfo` body which contains `modelName`, producing a false GREEN that masked the missing functionality
- Negative badge assertions in both phase9 and phase10 tests extract the CSS rule body via `css.find(cls + " ")` + brace-to-close slice, then assert the legacy hex absent in that slice — narrower than full-file `not in css` which could block legitimate reuse of the same hex in other unrelated rules

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_model_info_precedes_token: fixed false GREEN from naive char-window**
- **Found during:** Task 1 (creating test file, verification run)
- **Issue:** Initial implementation used `html[tok_start: tok_start + 600]` as the "handleToken body" window. The handleToken function is only ~8 lines; the 600-char window spilled into handleModelInfo which contains `this.modelName = d.model_name || ''` — the test passed against current source (false GREEN)
- **Fix:** Replaced fixed window with brace-depth walk: find opening `{` after `handleToken(`, walk character-by-character tracking depth, stop at depth==0 close `}`. The extracted body contains only handleToken's own code.
- **Files modified:** tests/unit/test_events_phase10.py
- **Verification:** Test now FAILS as expected (RED) — handleToken body has no modelName reference
- **Committed in:** `0b87a6a` (Task 1 commit, updated before commit)

**2. [Rule 1 - Bug] test_action_badge_palette_hex (phase9): negative assertions used wrong CSS substring format**
- **Found during:** Task 2 (verifying updated test is RED)
- **Issue:** Initial negative assertions used `".action-badge-click { background: #14532d"` (1 space) but actual CSS has 4 spaces for alignment (`.action-badge-click    { background:`). String-not-found = test passes (false GREEN)
- **Fix:** Switched to per-rule body extraction: `css.find(cls + " ")` → brace open → brace close, then assert `legacy_hex not in rule_body`
- **Files modified:** tests/unit/test_events_phase9.py
- **Verification:** Test now FAILS as expected (`.action-badge-click` body contains `#14532d`)
- **Committed in:** `c1b5de6` (Task 2 commit, updated before commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs — both false GREENs in test assertions caught during in-task verification)
**Impact on plan:** Essential corrections; both bugs would have allowed Plan 02/03 to ship without actually implementing the required changes. No scope creep.

## Issues Encountered

None beyond the two false-GREEN bugs documented above.

## Known Stubs

None — this plan creates only test files with no stub production code.

## Threat Flags

None — test-only plan; no new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED

- `tests/unit/test_events_phase10.py` exists: FOUND
- Commits `0b87a6a` and `c1b5de6` exist in git log: verified
- 14 tests collected: confirmed
- 14 tests failing: confirmed (RED state)
- test_action_badge_palette_hex RED: confirmed
- Baseline unit tests: 224 passed, 3 pre-existing failures (unchanged)

## Next Phase Readiness

- Plan 02 (GREEN implementation) can now start — all 14 acceptance criteria are locked in code
- Plan 02 must make all 14 `test_events_phase10.py` tests GREEN and also turn `test_action_badge_palette_hex` GREEN
- No blockers

---
*Phase: 10-ui-rendering-fixes-theme*
*Completed: 2026-05-19*
