---
phase: 4
requirements: [DIST-01, DIST-02, DIST-03, DIST-04, DIST-05]
---

# Phase 4: Manual UAT Script — Clean-Mac End-to-End Verification

**Purpose:** Verify DIST-01 through DIST-05 on a realistic non-developer Mac environment.

**Tester:** Developer or designated QA reviewer with access to a Mac (Sequoia preferred).

**Estimated time:** ~45 minutes (including CI wait time).

---

## Pre-flight Checks (Non-destructive — Do NOT Kill Ollama, Chrome, or Other Services)

Before starting, confirm your test environment without disrupting anything:

1. **Chrome is installed:** confirm `/Applications/Google Chrome.app` exists.
   ```
   ls /Applications/Google\ Chrome.app
   ```
   If missing, install from [google.com/chrome](https://www.google.com/chrome/) before proceeding.

2. **Ollama is running:** confirm Ollama is up with qwen2.5vl:7b pulled.
   ```
   ollama list
   ```
   You should see `qwen2.5vl:7b` in the output. If not, run `ollama pull qwen2.5vl:7b` (do NOT kill Ollama to "start fresh" — just confirm it's running).

3. **Fresh-user simulation (strongly recommended):** Rather than wiping your own environment, create a fresh macOS user account to simulate a "no Python / no uv / no Homebrew" Mac:
   - System Settings → Users & Groups → click + → create a Guest or Standard "Test User" account.
   - Log into that account to run DIST-01 and DIST-03 steps below.
   - This avoids any risk of disrupting your primary environment.

> **Non-destructive rule:** Do NOT uninstall Python, uv, Homebrew, or any tools from your primary account. Do NOT kill Ollama or any running services. The test account approach is the safe and correct method.

---

## Step 1: DIST-05 — Release Pipeline (Tag Push → GitHub Release)

**What we're testing:** Pushing a version tag triggers the `Release macOS App` GitHub Actions workflow, completes successfully, and produces a downloadable `.app.zip` in GitHub Releases.

### Actions

1. From a feature or release branch, push a pre-release tag:
   ```bash
   git tag v0.0.0-rc1
   git push origin v0.0.0-rc1
   ```

2. Open the **Actions** tab on the GitHub repository page.

3. Confirm the workflow **Release macOS App** appears and is running on `macos-latest`.

4. Wait for the workflow to complete (expected: under 20 minutes).
   - Confirm all steps are green.
   - If the **Verify core runtime imports** step fails (cdp_use/browser_use/agent.paths not found): the lockfile may not have been installed correctly — investigate `uv sync --frozen --all-groups` output in the logs.
   - If the **Build .app bundle** step fails: check for PyInstaller hidden-import errors or missing datas in the spec.
   - If the **Ad-hoc sign the bundle** step fails: check macOS codesign availability on the runner.

5. Open the **Releases** tab on the GitHub repository page.

6. Confirm a **pre-release** named `v0.0.0-rc1` exists with file:
   ```
   local-browser-agent-v0.0.0-rc1-mac.zip
   ```

7. Record the artifact file size. Expected range: **18–30 MB**.

### Pass Criteria

- [ ] Workflow completed green in under 20 minutes
- [ ] Pre-release `v0.0.0-rc1` visible in Releases page
- [ ] `.zip` artifact attached with size in expected range

---

## Step 2: DIST-01 — Double-Click Launch (Sequoia / Fresh User Account)

**What we're testing:** A non-technical user can download and open the `.app` with no terminal, Python, or developer tools.

### Actions (run from the fresh test user account)

1. Open Safari and download `local-browser-agent-v0.0.0-rc1-mac.zip` from the GitHub Releases page.

2. Double-click the `.zip` in Finder to unzip. You'll get `local-browser-agent.app`.

3. Double-click `local-browser-agent.app`.
   macOS shows:
   > "Apple could not verify 'local-browser-agent' is free of malware..."
   
   Click **Done**.

4. Open **System Settings** → **Privacy & Security**.

5. Scroll to the **Security** section. Click **Open Anyway**.

6. Authenticate with Touch ID or password.

7. Click **Open** on the final confirmation dialog.

8. Confirm the app launches and your default browser opens to **http://127.0.0.1:8080**.

9. Confirm the **disclaimer modal** appears ("Before You Begin").

### Pass Criteria

- [ ] App launched without requiring a terminal or Python
- [ ] Browser opened to http://127.0.0.1:8080
- [ ] Disclaimer modal visible on first launch
- [ ] System Settings → Open Anyway path worked as documented in README

---

## Step 3: DIST-03 — 3-Second Auto-Open Timing

**What we're testing:** The browser opens within 3 seconds of the user clicking the final "Open" button.

### Actions

1. Quit the running app (if open).

2. With a stopwatch or phone timer ready, click the final **Open** button in the Gatekeeper dialog (or just double-click if already authorized).

3. Start the timer the moment you click Open.

4. Stop the timer when the browser tab at http://127.0.0.1:8080 first renders (disclaimer modal is visible).

5. Record the elapsed time.

### Pass Criteria

- [ ] Browser tab first paint occurs within **3.0 seconds** of clicking Open

---

## Step 4: DIST-04 — One-Time Disclaimer (Persistence Check)

**What we're testing:** The disclaimer modal appears on first launch but does NOT appear on subsequent launches (persisted in browser localStorage).

### Actions

1. With the app running and the disclaimer modal visible, click **"I understand — let's go"**.

2. Confirm the task prompt box becomes accessible.

3. Quit the app (close terminal if running in dev mode, or use Cmd+Q from the Dock if packaged).

4. Re-launch the app (double-click; no Gatekeeper dialog this time since already authorized).

5. Confirm the browser opens to http://127.0.0.1:8080 **without** showing the disclaimer modal.

6. **Bonus (optional):** Open a private Safari window and navigate to http://127.0.0.1:8080. Confirm the disclaimer modal **does** appear there (proves the gate is client-side localStorage, not server state).

### Pass Criteria

- [ ] Disclaimer absent on second launch in same browser
- [ ] (Bonus) Disclaimer present in a private/incognito window

---

## Step 5: DIST-02 — Chrome-Missing Fallback

**What we're testing:** When Chrome is not at its standard path, the app shows a friendly "Download Chrome" page instead of crashing.

### Actions (reversible — Chrome is NOT deleted, only temporarily renamed)

1. Quit the agent app if running.

2. Temporarily rename (do NOT delete) the Chrome app:
   ```bash
   mv /Applications/Google\ Chrome.app /Applications/Google\ Chrome.app.bak
   ```

3. Launch the agent app (double-click from Finder or run via dev mode).

4. Confirm the browser opens to http://127.0.0.1:8080 and shows the **Chrome-missing page** with a "Download Chrome" link pointing to [google.com/chrome](https://www.google.com/chrome/).

5. Quit the app.

6. Restore Chrome immediately:
   ```bash
   mv /Applications/Google\ Chrome.app.bak /Applications/Google\ Chrome.app
   ```

7. Re-launch the app and confirm normal UI returns (disclaimer modal or task prompt).

### Pass Criteria

- [ ] Chrome-missing page shown when Chrome renamed to `.bak`
- [ ] "Download Chrome" link present on the page
- [ ] Normal UI returns after Chrome is restored
- [ ] Chrome was never deleted — only renamed (reversible)

---

## Cleanup

1. Switch back to your primary user account.

2. The test Guest/Standard account can be deleted: System Settings → Users & Groups → select test user → click - → Delete.

3. Confirm `/Applications/Google Chrome.app` exists (Chrome was restored in Step 5).

4. No services were killed, no tools were uninstalled, and no data was deleted.

---

## Pass/Fail Recording Table

| Requirement | Description | Result | Notes | Evidence (screenshot / log) |
|-------------|-------------|--------|-------|-----------------------------|
| DIST-05 | Tag push → green CI → .zip artifact in Releases | ⬜ | | |
| DIST-01 | Double-click launch on fresh Mac user (Sequoia) | ⬜ | | |
| DIST-03 | Browser first paint within 3.0 seconds | ⬜ | Observed time: ___s | |
| DIST-04 | Disclaimer absent on 2nd launch, present in private window | ⬜ | | |
| DIST-02 | Chrome-missing page shown when Chrome renamed, normal UI restored after | ⬜ | | |

**All 5 must be Pass before promoting v0.0.0-rc1 to a final v0.1.0 release.**

If any row fails: do NOT push the final release tag. Capture the failure evidence and report back with the failing row and attached logs/screenshots.
