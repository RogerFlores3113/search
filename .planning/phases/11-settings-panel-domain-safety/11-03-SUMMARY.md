---
phase: 11
plan: "03"
subsystem: settings-api-routes
tags: [fastapi, settings, encryption, fernet, httpx, ollama, tdd]
dependency_graph:
  requires:
    - agent/settings.py (Plans 01: Fernet helpers, atomic JSON I/O)
    - agent/config.py (Plan 02: SAFETY_DEFAULTS, user_domains, blocked_domains property)
  provides:
    - GET /api/settings (sanitized settings read — key_set booleans, never plaintext)
    - GET /api/settings/ollama-models (httpx Ollama proxy with graceful degradation)
    - POST /api/settings (encrypt keys, filter user_domains, atomic write, live-patch config)
  affects:
    - Plan 04 (frontend Alpine fetch calls target these routes)
tech_stack:
  added:
    - httpx (already dep; newly imported in agent/main.py)
    - fastapi.Form (added to existing import)
  patterns:
    - Lazy imports inside route handlers (avoids load-order issues)
    - AsyncClient + Timeout(3.0) for Ollama proxy (mirrors runner.py pre_flight_check pattern)
    - key_action enum (set/keep/clear) prevents accidental key overwrite
    - SAFETY_DEFAULTS server-side filter on user_domains (defense in depth)
    - Direct field assignment live-patch (MUTABILITY_MODE confirmed in Plan 01)
key_files:
  created: []
  modified:
    - agent/main.py (3 new async route handlers + httpx import + Form import)
    - tests/unit/test_settings_phase11.py (6 Plan-03 tests flipped GREEN + 2 new regression tests)
decisions:
  - "Mutability mode: direct field assignment (config.provider = value) confirmed from Plan 01 SUMMARY — no object.__setattr__ needed."
  - "GET /api/settings response shape: 9 sanitized keys (provider, ollama_model, ollama_host, anthropic_model, openai_model, anthropic_key_set, openai_key_set, safety_defaults, user_domains) — encrypted blobs and plaintext never included."
  - "Ollama proxy timeout: 3.0s (matches RESEARCH.md recommendation; shorter than runner.py 5.0s pre-flight)."
  - "user_domains normalization: strip http(s)://, trailing /, whitespace; lowercase; deduplicate; filter SAFETY_DEFAULTS; drop empty strings."
metrics:
  duration: "~20 minutes"
  completed: "2026-05-18"
  tasks_completed: 2
  files_changed: 2
---

# Phase 11 Plan 03: FastAPI Settings Routes — GET + POST /api/settings

Lands the three FastAPI routes that bridge the encryption/config foundation (Plans 01/02) to the settings overlay UI (Plan 04).

## What Was Built

### Task 1: GET /api/settings and GET /api/settings/ollama-models

**GET /api/settings/ollama-models** (line 292 in agent/main.py):
- Async httpx proxy to `{config.ollama_host}/api/tags` with `Timeout(3.0)`.
- Returns `{"models": [...names...]}` on success (extracts `m["name"]` from Ollama response).
- Returns `{"models": [], "error": "unreachable"}` on any exception (ConnectError, TimeoutException, JSONDecodeError, etc.) — handler never raises or returns 5xx.
- Pattern mirrors `runner.py::pre_flight_check` exactly: `async with httpx.AsyncClient(timeout=...)`.

**GET /api/settings** (line 266 in agent/main.py):
- Returns 200 with exactly 9 sanitized keys:
  `provider`, `ollama_model`, `ollama_host`, `anthropic_model`, `openai_model`,
  `anthropic_key_set` (bool), `openai_key_set` (bool), `safety_defaults` (sorted list), `user_domains` (list).
- `*_key_set` booleans derived from presence of `*_api_key_enc` in settings.json — the encrypted blob and plaintext never appear in the response.
- `safety_defaults` is `sorted(SAFETY_DEFAULTS)` — all 27+ locked domains.

Tests flipped GREEN: `test_ollama_models_endpoint`, `test_ollama_models_unreachable`, `test_get_settings_sanitized_shape` (new).

### Task 2: POST /api/settings

**POST /api/settings** (line 318 in agent/main.py):
- Form fields: `provider`, `ollama_model`, `ollama_host`, `anthropic_key_action`, `anthropic_key_value`, `openai_key_action`, `openai_key_value`, `user_domains_json`.
- Key handling three-branch logic: `set` → encrypt and store; `clear` → pop enc blob; `keep` → no-op (preserves existing key on empty submission).
- `user_domains_json` parsing: JSON decode → strip `http(s)://` and trailing `/` → lowercase → drop empty/whitespace → filter against SAFETY_DEFAULTS → deduplicate.
- Atomic write via `save_settings_json(stored)` (tmp + os.replace, Plan 01 contract).
- Live-patches config singleton using **direct field assignment** (MUTABILITY_MODE from Plan 01): `config.provider`, `config.ollama_model`, `config.ollama_host`, `config.user_domains`, `config.anthropic_api_key`, `config.openai_api_key`.
- Returns `{"status": "saved"}` on success; `{"status": "error", "detail": ...}` (500) on exception — raw key values never echoed in error path.

Tests flipped GREEN: `test_save_api_key_encrypted`, `test_get_settings_no_plaintext_key`, `test_save_updates_live_config`, `test_save_user_domains`, `test_save_key_action_keep_preserves` (new), `test_save_key_action_clear_removes` (new).

## Sanitized Response Shape (GET /api/settings)

```json
{
  "provider": "ollama",
  "ollama_model": "qwen2.5vl:7b",
  "ollama_host": "http://localhost:11434",
  "anthropic_model": "claude-opus-4-5",
  "openai_model": "gpt-4o",
  "anthropic_key_set": false,
  "openai_key_set": false,
  "safety_defaults": ["accounts.google.com", "bankofamerica.com", ...],
  "user_domains": []
}
```

Keys NOT present: `anthropic_api_key`, `openai_api_key`, `anthropic_api_key_enc`, `openai_api_key_enc`.

## Test Inventory After Plan 03

| Test | Status |
|------|--------|
| `test_config_field_assignment_works` | GREEN (Plan 01) |
| `test_settings_path_uses_user_config_dir` | GREEN (Plan 01) |
| `test_fernet_key_stable` | GREEN (Plan 01) |
| `test_encrypt_decrypt_roundtrip` | GREEN (Plan 01) |
| `test_load_settings_json_missing_returns_empty` | GREEN (Plan 01) |
| `test_save_settings_json_atomic` | GREEN (Plan 01) |
| `test_cve_2025_47241_urlparse_used` | GREEN (Plan 01) |
| `test_safety_defaults_banking` | GREEN (Plan 02) |
| `test_safety_defaults_gov_medical` | GREEN (Plan 02) |
| `test_cve_2025_47241_credential_url_blocked` | GREEN (Plan 02) |
| `test_ollama_models_endpoint` | GREEN (Plan 03) |
| `test_ollama_models_unreachable` | GREEN (Plan 03) |
| `test_save_api_key_encrypted` | GREEN (Plan 03) |
| `test_get_settings_no_plaintext_key` | GREEN (Plan 03) |
| `test_save_updates_live_config` | GREEN (Plan 03) |
| `test_save_user_domains` | GREEN (Plan 03) |
| `test_get_settings_sanitized_shape` | GREEN (Plan 03, new) |
| `test_save_key_action_keep_preserves` | GREEN (Plan 03, new) |
| `test_save_key_action_clear_removes` | GREEN (Plan 03, new) |
| `test_gear_button_present` | GREEN (Plan 04) |
| `test_settings_overlay_aria` | GREEN (Plan 04) |
| `test_domain_list_two_tier_html` | GREEN (Plan 04) |
| `test_settings_overlay_present` | GREEN (Plan 04) |
| `test_provider_radio_present` | GREEN (Plan 04) |
| `test_api_key_input_type_password` | GREEN (Plan 04) |

**Total: 25/25 GREEN**

## Deviations from Plan

- Plan specified 6 endpoint tests for Plan 03; 3 additional test names were added by Plan 04 (test_settings_overlay_present, test_provider_radio_present, test_api_key_input_type_password) but all already pass.
- `test_get_settings_sanitized_shape` was added as a new test (not a renamed stub) per Task 1 Step 5 instructions.
- `test_save_key_action_keep_preserves` and `test_save_key_action_clear_removes` were new tests per Task 2 Step 3.

## Threat Surface Scan

Three new API endpoints added (T-11-11 through T-11-17 mitigated per plan threat model):
- T-11-11 (info disclosure via GET response): response dict explicitly enumerates allowed keys only.
- T-11-12 (info disclosure via POST error path): key values never echoed; 200-char truncation.
- T-11-13 (tampering via user_domains_json): defensive JSON parse + domain normalization + SAFETY_DEFAULTS filter.
- T-11-14 (tampering via key_action enum): only "set"/"clear" are acted on; empty string under "set" treated as keep.
- T-11-15 (DoS via Ollama proxy): 3.0s timeout + broad except → graceful {"models": [], "error": "unreachable"}.

## Self-Check: PASSED

- `grep -c '@app.get("/api/settings")' agent/main.py` → 1: FOUND
- `grep -c '@app.get("/api/settings/ollama-models")' agent/main.py` → 1: FOUND
- `grep -c '@app.post("/api/settings")' agent/main.py` → 1: FOUND
- `grep -c 'import httpx' agent/main.py` → 1: FOUND
- `grep -c 'encrypt_api_key' agent/main.py` → 2 (anthropic + openai): FOUND
- `grep -c 'SAFETY_DEFAULTS' agent/main.py` → 2 (GET + POST): FOUND
- `uv run pytest tests/unit/test_settings_phase11.py -q` → 25 passed: VERIFIED
- feat(11-03): Task 1 commit `e3c4dd3`: FOUND
- feat(11-03): Task 2 commit `bf86367`: FOUND
