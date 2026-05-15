---
phase: "02"
plan: "02"
subsystem: guardrails
tags: [security, browser-use, captcha-detection, domain-blocking, system-prompt]
dependency_graph:
  requires: ["02-01"]
  provides: ["blocked_domains", "GUARDRAIL_PROMPT", "CAPTCHA_KEYWORDS", "BrowserProfile-wiring", "SecurityWatchdog-enforcement"]
  affects: ["agent/runner.py", "agent/config.py"]
tech_stack:
  added: ["browser_use.browser.profile.BrowserProfile", "browser_use.browser.watchdogs.SecurityWatchdog (via prohibited_domains)"]
  patterns: ["CDP-level domain blocking", "system-prompt guardrails via extend_system_message", "CAPTCHA keyword detection in step callback"]
key_files:
  created:
    - tests/unit/test_guardrails.py
    - tests/integration/test_guardrails.py
  modified:
    - agent/config.py
    - agent/runner.py
    - tests/unit/test_runner.py
    - tests/unit/test_training_log.py
    - tests/integration/test_end_to_end.py
decisions:
  - "blocked_domains is a hardcoded set[str] default — pydantic-settings set[str] coercion from env var is unverified; Phase 3 UI will add configuration"
  - "CaptchaWatchdog NOT enabled — it requires cloud browser CDP events; local Chrome never emits them (Pitfall 7)"
  - "extend_system_message used (not override_system_message) — override replaces the entire base prompt and breaks navigation (Pitfall 6)"
  - "agent.pause() called synchronously in log_step — not awaitable; blocks agent at next _check_stop_or_pause() call"
metrics:
  duration: "269s"
  completed: "2026-05-15"
  tasks_completed: 2
  files_changed: 7
---

# Phase 02 Plan 02: Guardrails — Domain Blocking, Action Guardrails, CAPTCHA Detection Summary

CDP-level domain blocking via BrowserProfile.prohibited_domains + SecurityWatchdog, system-prompt action guardrails via extend_system_message=GUARDRAIL_PROMPT, and CAPTCHA keyword detection in log_step that pauses the agent with stdout notification.

## What Was Built

### Task 1 (480549e) — Guardrail test stubs with xfail markers
Created three test files with stub tests marked xfail(strict=True) to establish the TDD RED phase:
- `tests/unit/test_guardrails.py`: 7 tests for GUARDRAIL_PROMPT content, CAPTCHA_KEYWORDS type/contents, blocked_domains defaults
- `tests/integration/test_guardrails.py`: 2 async integration tests for BrowserProfile.prohibited_domains and Agent.extend_system_message wiring
- `tests/unit/test_runner.py` extended: 3 CAPTCHA log_step tests (2 xfail, 1 already passing)

### Task 2 (dded5d8) — Full implementation, xfails removed
All three guardrail enforcement layers implemented:

**GUARD-01: CDP-level domain blocking**
```python
profile = BrowserProfile(
    prohibited_domains=config.blocked_domains,
    channel="chrome",
    headless=False,
    keep_alive=False,
    window_size={"width": config.browser_width, "height": config.browser_height},
)
browser = BrowserSession(browser_profile=profile)
```
SecurityWatchdog auto-registers when prohibited_domains is set; intercepts NavigateToUrlEvent at CDP layer before the page loads.

**GUARD-02/03: System-prompt action guardrails**
```
GUARDRAIL_PROMPT = "\nSAFETY GUARDRAILS — override everything else:\n
1. NEVER click Buy Now, Purchase, Checkout, Pay, Place Order, Confirm Order, Complete Purchase...\n
2. NEVER submit forms containing credit card numbers, CVVs, bank account details, SSNs, or passwords...\n
3. NEVER submit credentials (username/password) on any site not explicitly named.\n
4. If you encounter such an element, set is_done=True, success=False, explain what you found.\n"
```
Injected via `Agent(..., extend_system_message=GUARDRAIL_PROMPT)`.

**GUARD-04: CAPTCHA detection in log_step**
```python
CAPTCHA_KEYWORDS = frozenset([
    "captcha", "recaptcha", "hcaptcha", "cloudflare",
    "bot detection", "access denied", "verify you are human",
    "i'm not a robot", "challenge",
])
```
After each step, log_step scans `agent.state.last_result` errors. On keyword match: prints `[CAPTCHA DETECTED]` notification to stdout + calls `agent.pause()`.

**blocked_domains defaults (10 domains)**
```python
blocked_domains: set[str] = {
    "chase.com", "wellsfargo.com", "bankofamerica.com",
    "citi.com", "usbank.com", "paypal.com", "venmo.com",
    "stripe.com", "square.com", "braintree.com",
}
```

## Test Results
- 48 tests total, 48 passing, 0 failures, 0 xfails remaining
- `uv run pytest tests/ -x -q` exits 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_no_captcha_no_pause_when_error_text_clean was xfail when it should pass**
- **Found during:** Task 1 verification
- **Issue:** The "no pause on clean error" test passed immediately (no CAPTCHA code existed yet), causing xfail(strict=True) to fail the suite
- **Fix:** Removed xfail from this specific test — it already validates expected behavior
- **Files modified:** tests/unit/test_runner.py

**2. [Rule 1 - Bug] test_run_agent_constructs_browser_session_with_chrome_channel broke after BrowserProfile refactor**
- **Found during:** Task 2 verification
- **Issue:** Unit test asserted `BrowserSession.assert_called_once_with(channel='chrome', ...)` but run_agent now calls `BrowserSession(browser_profile=profile)` — the kwargs changed
- **Fix:** Updated test to patch BrowserProfile, assert BrowserProfile kwargs, and assert BrowserSession called with browser_profile=mock_profile
- **Files modified:** tests/unit/test_runner.py, tests/integration/test_end_to_end.py

**3. [Rule 1 - Bug] _make_fake_agent missing state.last_result caused AttributeError in log_step**
- **Found during:** Task 2 verification
- **Issue:** The new CAPTCHA detection branch reads `agent.state.last_result`; fake agents in test_training_log.py and test_end_to_end.py lacked the `state` attribute
- **Fix:** Added `state = SimpleNamespace(last_result=[])` to both fake agent constructors
- **Files modified:** tests/unit/test_training_log.py, tests/integration/test_end_to_end.py

**4. [Rule 1 - Bug] test_post_run_endpoint_starts_agent broke because Agent now receives extend_system_message**
- **Found during:** Task 2 verification
- **Issue:** MockAgent.assert_called_once_with(task=..., llm=..., browser_session=...) failed because Agent constructor now also receives extend_system_message=GUARDRAIL_PROMPT
- **Fix:** Added extend_system_message=GUARDRAIL_PROMPT to the assertion and added BrowserProfile patch
- **Files modified:** tests/integration/test_end_to_end.py

## Threat Dispositions

| Threat ID | Status | Enforcement |
|-----------|--------|-------------|
| T-02-02 | Mitigated | BrowserProfile.prohibited_domains + SecurityWatchdog; navigation to banking domains blocked at CDP |
| T-02-03 | Mitigated | extend_system_message=GUARDRAIL_PROMPT with 4 numbered clauses covering commerce CTAs |
| T-02-09 | Mitigated | GUARDRAIL_PROMPT clauses 2 and 3 forbid credential/payment submission on unnamed sites |
| T-02-04 | Mitigated | log_step CAPTCHA detection calls agent.pause() on keyword match; no silent looping |
| T-02-10 | Mitigated by exclusion | No captcha_solver=True; CaptchaWatchdog not enabled |
| T-02-11 | Mitigated | SecurityWatchdog hooks NavigationCompleteEvent (post-redirect re-check) |
| T-02-12 | Accepted | Prompt injection residual risk; SecurityWatchdog is the hard floor for navigation |

## Anti-pattern Enforcement (grep verified)

- `grep -c "override_system_message" agent/runner.py` → 0 (Pitfall 6: never replace base prompt)
- `grep -c "captcha_solver" agent/runner.py` → 0 (Pitfall 7: CaptchaWatchdog requires cloud CDP)
- `grep -c "page.route" agent/runner.py` → 0 (anti-pattern: prohibited_domains is the correct mechanism)

## Self-Check: PASSED

All files exist, all commits verified:
- FOUND: .planning/phases/02-multi-provider-guardrails/02-02-SUMMARY.md
- FOUND: agent/config.py
- FOUND: agent/runner.py
- FOUND: tests/unit/test_guardrails.py
- FOUND: tests/integration/test_guardrails.py
- FOUND: commit 480549e (Task 1 — test stubs)
- FOUND: commit dded5d8 (Task 2 — implementation)
