---
phase: 11
plan: "02"
subsystem: settings-domain-safety
tags: [safety, config, pydantic-settings, two-tier-blocklist, tdd]
dependency_graph:
  requires:
    - 11-01 (agent/paths.py::get_settings_path, test scaffold)
  provides:
    - agent/config.py::SAFETY_DEFAULTS (frozenset, 29 domains)
    - agent/config.py::Settings.user_domains (loadable field)
    - agent/config.py::Settings.blocked_domains (property, two-tier merge)
    - agent/config.py::Settings.settings_customise_sources (JsonConfigSettingsSource chain)
    - agent/runner.py::BrowserProfile two-tier prohibited_domains merge
  affects:
    - Plans 03-04 (read/mutate user_domains via POST /api/settings)
tech_stack:
  added: []
  patterns:
    - SAFETY_DEFAULTS frozenset literal in code (not loaded from JSON — T-11-07 mitigation)
    - JsonConfigSettingsSource precedence: init > settings.json > env > .env > file_secret
    - Two-tier merge at run start: SAFETY_DEFAULTS | set(config.user_domains)
key_files:
  created: []
  modified:
    - agent/config.py (SAFETY_DEFAULTS, user_domains, blocked_domains property, settings_customise_sources)
    - agent/runner.py (import SAFETY_DEFAULTS; BrowserProfile prohibited_domains two-tier merge)
    - tests/unit/test_settings_phase11.py (5 RED tests flipped GREEN)
decisions:
  - "SAFETY_DEFAULTS is a frozenset literal in code — never read from settings.json — so tampering with settings.json cannot weaken the safety tier (T-11-07)"
  - "Merge happens at BrowserProfile construction (run start), not import time — newly saved user_domains take effect on next run without process restart (T-11-08)"
  - "get_settings_path lazy-imported inside settings_customise_sources to avoid import cycle"
  - "blocked_domains kept as a property (not removed) for backward compat with test_guardrails.py::test_blocked_domains_contains_default_banks"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-18"
  tasks_completed: 2
  files_changed: 3
---

# Phase 11 Plan 02: SAFETY_DEFAULTS Frozenset + Two-Tier Blocklist + JsonConfigSettingsSource

Reshape agent/config.py from a single blocked_domains field into the two-tier safety model: SAFETY_DEFAULTS frozenset (code-locked) + user_domains (settings.json-loaded) with backward-compat blocked_domains property.

## What Was Built

### Task 1: agent/config.py Refactor

- **SAFETY_DEFAULTS frozenset**: 29 domains across 5 categories, defined at module scope above the Settings class.
- **user_domains field**: `user_domains: list[str] = []` — loaded from settings.json via JsonConfigSettingsSource.
- **blocked_domains property**: `return SAFETY_DEFAULTS | set(self.user_domains)` — user cannot shrink the safety tier (T-11-06 mitigation).
- **settings_customise_sources**: Injects JsonConfigSettingsSource at second position in precedence chain (init > settings.json > env > .env > file_secret). get_settings_path lazy-imported to avoid circular imports.
- **Backward compat**: test_guardrails.py::test_blocked_domains_contains_default_banks still passes (blocked_domains property returns a superset of the original hardcoded set).

### SAFETY_DEFAULTS Contents (sorted by category)

| Category | Domains |
|----------|---------|
| Banking | bankofamerica.com, chase.com, citi.com, usbank.com, wellsfargo.com |
| Payment | braintree.com, paypal.com, square.com, stripe.com, venmo.com |
| Government | dhs.gov, fbi.gov, healthcare.gov, irs.gov, ssa.gov, state.gov, va.gov, whitehouse.gov |
| Medical | epic.com, labcorp.com, mychart.com, questdiagnostics.com |
| Credential/Identity | 1password.com, auth0.com, bitwarden.com, dashlane.com, lastpass.com, nordpass.com, okta.com |

Total: 29 domains.

### settings_customise_sources Precedence Chain Confirmed

```
init_settings > JsonConfigSettingsSource(settings.json) > env_settings > dotenv_settings > file_secret_settings
```

Verified by test_settings_json_overrides_env: writing `{"provider": "anthropic", "user_domains": ["foo.com"]}` to a temp settings.json and instantiating Settings() loads both values correctly.

### Task 2: agent/runner.py BrowserProfile Wiring

Two-line change:

```python
# Before (line 17):
from agent.config import config
# After:
from agent.config import config, SAFETY_DEFAULTS

# Before (line 505):
prohibited_domains=config.blocked_domains,
# After:
prohibited_domains=SAFETY_DEFAULTS | set(config.user_domains),
```

The merge happens at BrowserProfile construction (run start), not at import time. Newly saved user_domains take effect on next run without process restart (T-11-08 mitigation).

## Test Inventory After Plan 02

| Test | Status | Plan |
|------|--------|------|
| test_config_field_assignment_works | GREEN | 01 |
| test_settings_path_uses_user_config_dir | GREEN | 01 |
| test_fernet_key_stable | GREEN | 01 |
| test_encrypt_decrypt_roundtrip | GREEN | 01 |
| test_load_settings_json_missing_returns_empty | GREEN | 01 |
| test_save_settings_json_atomic | GREEN | 01 |
| test_cve_2025_47241_urlparse_used | GREEN | 01 |
| test_safety_defaults_banking | GREEN | 02 |
| test_safety_defaults_gov_medical | GREEN | 02 |
| test_blocked_domains_property_includes_user_domains | GREEN | 02 |
| test_settings_json_overrides_env | GREEN | 02 |
| test_cve_2025_47241_credential_url_blocked | GREEN | 02 |
| test_ollama_models_endpoint | RED | 03 |
| test_ollama_models_unreachable | RED | 03 |
| test_save_api_key_encrypted | RED | 03 |
| test_get_settings_no_plaintext_key | RED | 03 |
| test_save_updates_live_config | RED | 03 |
| test_save_user_domains | RED | 03 |
| test_gear_button_present | RED | 04 |
| test_settings_overlay_aria | RED | 04 |
| test_domain_list_two_tier_html | RED | 04 |

**Summary: 12 GREEN, 9 RED (clean pytest.fail — no collection errors)**

Full unit suite: 239 passed, 3 pre-existing test_events_phase8.py failures only.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints or auth paths introduced. Changes are confined to:
- agent/config.py: in-process settings model
- agent/runner.py: one-line import + one-line argument change

T-11-06, T-11-07, T-11-08, T-11-09, T-11-10 mitigations all implemented as specified in the threat register.

## Self-Check: PASSED

- SAFETY_DEFAULTS at module scope in agent/config.py: FOUND (line 13)
- user_domains field in Settings: FOUND
- blocked_domains property: FOUND
- settings_customise_sources: FOUND
- JsonConfigSettingsSource import: FOUND
- SAFETY_DEFAULTS import in runner.py: FOUND (line 17)
- BrowserProfile two-tier merge: FOUND (line 505)
- Task 1 commit 3729882: FOUND
- Task 2 commit af19d7f: FOUND
- 12 GREEN / 9 RED test state: VERIFIED
- Full unit suite 239 passed + 3 pre-existing failures: VERIFIED
