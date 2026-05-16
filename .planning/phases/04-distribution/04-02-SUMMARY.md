---
phase: 04-distribution
plan: 02
subsystem: infra
tags: [github-actions, codesign, pyinstaller, release-pipeline, readme, uat, cdp-use]

# Dependency graph
requires:
  - phase: 04-distribution
    plan: 01
    provides: "local-browser-agent.spec, agent/paths.py, chrome detection, launcher, disclaimer modal"
provides:
  - ".github/workflows/release.yml: tag-triggered macOS build -> sign -> zip -> GitHub Release upload"
  - "build_scripts/sign.sh: ad-hoc codesign .app + embedded .so/.dylib re-signing"
  - "build_scripts/build_mac.sh: local developer build mirror of CI pipeline"
  - "README.md: Installing on macOS section with Sequoia Open Anyway path"
  - ".planning/phases/04-distribution/04-HUMAN-UAT.md: numbered clean-Mac UAT script for DIST-01..DIST-05"
affects: [04-distribution-plan-03-human-checkpoint, GitHub-Releases]

# Tech tracking
tech-stack:
  added:
    - "softprops/action-gh-release@v2 (GitHub Actions release upload)"
    - "actions/checkout@v4, actions/setup-python@v5 (CI dependencies)"
  patterns:
    - "uv sync --frozen --all-groups in CI (installs dev deps including pyinstaller)"
    - "Smoke gate: assert bundle binary at Contents/MacOS/ before upload"
    - "Core import check: cdp_use + browser_use + agent.paths (replaces playwright driver check)"
    - "Ad-hoc codesign: --sign - --force --deep + find .so/.dylib re-sign"
    - "prerelease auto-detect via github.ref_name contains -rc or -beta"

key-files:
  created:
    - .github/workflows/release.yml
    - build_scripts/sign.sh
    - build_scripts/build_mac.sh
    - README.md
    - .planning/phases/04-distribution/04-HUMAN-UAT.md
  modified: []

key-decisions:
  - "Playwright driver check removed: browser-use 0.12.6 uses cdp-use (pure Python CDP), no Node.js driver binary exists"
  - "Core import smoke step: python -c 'import cdp_use; import browser_use; import agent.paths' verifies key runtime packages"
  - "sign.sh: ad-hoc sign entire .app with --deep, then recursively re-sign .so/.dylib; no node binary search"
  - "uv sync --frozen --all-groups: installs dev group (pyinstaller, platformdirs) in CI without separate pip install step"
  - "prerelease flag quoted in YAML: ${{ ... }} expressions with || operator require quoting to parse correctly"
  - "README created fresh (did not exist before this plan)"
  - "04-HUMAN-UAT.md force-added with git add -f: .planning/ is gitignored but individual files can be tracked"

# Metrics
duration: ~30min
completed: 2026-05-16
---

# Phase 04 Plan 02: Release Pipeline + Documentation Summary

**GitHub Actions tag-triggered macOS release pipeline with ad-hoc codesign, bundle smoke gate, Sequoia install docs, and clean-Mac UAT script — no Playwright dependency (cdp-use used instead)**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-05-16
- **Completed:** 2026-05-16
- **Tasks:** 4 of 4 auto tasks completed (Task 5 is human checkpoint — not executed)
- **Files created:** 5

## Accomplishments

- `build_scripts/sign.sh`: ad-hoc codesigns the entire `.app` with `codesign --sign - --force --deep`, then re-signs all embedded `.so` and `.dylib` files via find+xargs
- `build_scripts/build_mac.sh`: local developer one-liner that mirrors the CI pipeline exactly (uv sync → pyinstaller → sign → zip)
- `.github/workflows/release.yml`: tag `v*` push triggers macos-latest job with 20-minute timeout, `permissions: contents: write`; steps include uv sync --frozen --all-groups, core import smoke, pyinstaller build, sign.sh, bundle binary assertion, zip, and softprops/action-gh-release@v2 upload
- `README.md`: full Installing on macOS section with Sequoia-specific System Settings → Privacy & Security → Open Anyway path; Chrome prerequisite; user_data_dir location; dev build instructions
- `04-HUMAN-UAT.md`: numbered 5-step UAT script covering DIST-01 through DIST-05 with non-destructive prereqs (guest account simulation, reversible Chrome rename)
- 106 tests remain green (no new test files in this plan — scripts are shell/config/docs)

## Task Commits

1. **Task 1: Local build + sign scripts** - `fd8b267` (feat)
2. **Task 2: GitHub Actions release pipeline** - `1080b46` (feat)
3. **Task 3: README Installing section** - `87bb5ff` (docs)
4. **Task 4: Clean-Mac UAT script** - `66548e9` (docs)

## Files Created/Modified

- `build_scripts/sign.sh` — ad-hoc codesign script (executable)
- `build_scripts/build_mac.sh` — local developer build script (executable)
- `.github/workflows/release.yml` — tag-triggered GitHub Actions release workflow
- `README.md` — macOS install guide with Sequoia Gatekeeper workaround
- `.planning/phases/04-distribution/04-HUMAN-UAT.md` — 5-step manual UAT script

## Decisions Made

- **No Playwright driver in sign.sh or release.yml:** browser-use 0.12.6 dropped the `playwright` Python package entirely; it uses `cdp-use` (pure Python CDP over WebSocket). There is no `node` binary to sign or verify. The plan's Playwright steps were replaced with a `cdp_use`/`browser_use`/`agent.paths` import smoke check.
- **Core import check in CI:** Replaces the Playwright driver ls check. `python -c "import cdp_use; import browser_use; import agent.paths; print('core imports ok')"` verifies the three most critical runtime packages are accessible in the venv before pyinstaller runs.
- **`uv sync --frozen --all-groups`:** Installs the dev dependency group (pyinstaller==6.20.0, platformdirs>=4.9.6) without a separate `pip install` step. The lockfile from Plan 01 includes these packages.
- **YAML quoting for prerelease:** The `${{ contains(...) || contains(...) }}` expression contains a colon-after-pipe sequence that pyyaml parses as a mapping value. Quoted with double quotes to parse correctly.
- **force-add for .planning/04-HUMAN-UAT.md:** The `.planning/` directory is gitignored, but individual files inside can be tracked by force-adding. Consistent with how 04-01-SUMMARY.md and STATE.md are tracked.

## Deviations from Plan

### Applied Corrections (per execution instructions)

**1. [Correction] Removed Playwright driver verification step from release.yml**
- **Why:** browser-use 0.12.6 uses cdp-use, not playwright. There is no `playwright/driver/node` binary.
- **Replacement:** `python -c "import cdp_use; import browser_use; import agent.paths; print('core imports ok')"` (Step 5 in CI)
- **Correction source:** Objective block in execution instructions

**2. [Correction] Removed Playwright node binary smoke check from release.yml**
- **Why:** Same reason — no playwright node binary exists in the bundle.
- **Replacement:** `pathlib.Path('dist/local-browser-agent.app/Contents/MacOS/local-browser-agent').exists()` assertion (bundle binary presence)
- **Correction source:** Objective block in execution instructions

**3. [Correction] Removed node binary find in sign.sh**
- **Why:** No playwright node binary to sign.
- **sign.sh behavior:** `codesign --sign - --force --deep "$APP"` then find+xargs for `*.so` and `*.dylib` only.
- **Correction source:** Objective block in execution instructions

### Auto-fixed Issues

**4. [Rule 1 - Bug] YAML parse error: prerelease expression contained colon**
- **Found during:** Task 2 verification (yaml.safe_load raised ScannerError at column 168)
- **Issue:** `prerelease: ${{ contains(github.ref_name, '-rc') || contains(github.ref_name, '-beta') }}` — pyyaml interprets the `||` pattern followed by remaining content as a mapping value
- **Fix:** Quoted the value: `prerelease: "${{ contains(...) || contains(...) }}"`
- **Files modified:** .github/workflows/release.yml

## Known Stubs

None. All artifacts are fully implemented. The human checkpoint (Task 5) is the only remaining gate — it requires a real tag push and Mac verification, which cannot be automated.

## Threat Flags

No new threat surface beyond the plan's threat model (T-04-08 through T-04-13). The workflow correctly uses `permissions: contents: write` (minimum scope) and `uv sync --frozen` (lockfile enforcement). No third-party secrets referenced.

## Self-Check

- [x] `build_scripts/sign.sh` exists and is executable
- [x] `build_scripts/build_mac.sh` exists and is executable
- [x] `.github/workflows/release.yml` exists and parses as valid YAML
- [x] `README.md` contains "Open Anyway", "Application Support/local-browser-agent", "google.com/chrome"
- [x] `04-HUMAN-UAT.md` exists, references DIST-01..DIST-05, references "Open Anyway", no destructive prereqs
- [x] All 4 task commits exist: fd8b267, 1080b46, 87bb5ff, 66548e9
- [x] 106 tests pass

## Self-Check: PASSED
