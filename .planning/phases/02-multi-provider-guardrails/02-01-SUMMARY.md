---
phase: "02"
plan: "01"
subsystem: "agent-core"
tags: ["llm-providers", "anthropic", "openai", "secrets", "preflight"]
dependency_graph:
  requires: ["01-03"]
  provides: ["multi-provider-llm", "build_llm-factory", "secretstr-api-keys"]
  affects: ["agent/config.py", "agent/runner.py"]
tech_stack:
  added: ["pydantic.SecretStr", "browser_use.ChatAnthropic", "browser_use.ChatLiteLLM", "anthropic SDK (transitive)", "openai SDK (transitive)"]
  patterns: ["build_llm factory dispatch", "provider-level pre_flight_check branching", "SecretStr for API key masking"]
key_files:
  created: [".env.example (updated)"]
  modified: ["agent/config.py", "agent/runner.py", "tests/conftest.py", "tests/unit/test_config.py", "tests/unit/test_runner.py"]
decisions:
  - "Use provider-level if/elif in pre_flight_check (not nested in ollama try/except) — correct structural pattern for multi-provider validation"
  - "xfail strict=True on Task 1 tests ensures they register as XFAIL not FAIL before implementation"
  - "build_llm() is module-level function (not method) — matches PATTERNS.md spec and is easily patchable in tests"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-15T23:45:50Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 5
---

# Phase 02 Plan 01: Multi-Provider LLM Integration Summary

## One-Liner

Anthropic and OpenAI wired via `build_llm(cfg)` factory with `SecretStr` API key storage, provider-level `pre_flight_check` validation, and 31 green unit tests.

## What Was Built

### Settings Fields (agent/config.py)

Added `from pydantic import SecretStr` import and four new fields to `Settings`:

| Field | Type | Default |
|-------|------|---------|
| `anthropic_api_key` | `SecretStr \| None` | `None` |
| `anthropic_model` | `str` | `"claude-sonnet-4-5"` |
| `openai_api_key` | `SecretStr \| None` | `None` |
| `openai_model` | `str` | `"gpt-4o"` |

`SecretStr` ensures API key values never appear in `repr()`, logs, or stdout. `.get_secret_value()` is called only at LLM constructor call sites.

### build_llm Factory (agent/runner.py)

New module-level function dispatching on `cfg.provider.lower()`:

```python
def build_llm(cfg: "Settings"):
    provider = cfg.provider.lower()
    if provider == "ollama":
        return ChatOllama(model=cfg.ollama_model, ollama_options={"num_ctx": 32000})
    elif provider == "anthropic":
        return ChatAnthropic(model=cfg.anthropic_model, api_key=cfg.anthropic_api_key.get_secret_value())
    elif provider == "openai":
        return ChatLiteLLM(model=cfg.openai_model, api_key=cfg.openai_api_key.get_secret_value())
    else:
        raise ValueError(f"Unknown provider: {provider!r}")
```

`run_agent` now calls `llm = build_llm(config)` instead of constructing `ChatOllama` directly.

### pre_flight_check Extension (agent/runner.py)

Restructured from Ollama-only to provider-level branching:

| Provider | Validation | Error |
|----------|-----------|-------|
| `ollama` | `GET /api/tags` + model name check (unchanged) | `PreFlightError("Ollama unreachable")` / `"Model not pulled"` |
| `anthropic` | Missing key check + `AsyncAnthropic.models.list()` | `PreFlightError("Missing Anthropic API key")` / `"Invalid Anthropic API key"` / `"Anthropic API unreachable"` |
| `openai` | Missing key check + `GET https://api.openai.com/v1/models` | `PreFlightError("Missing OpenAI API key")` / `"Invalid OpenAI API key"` / `"OpenAI API unreachable"` |

All branches print an actionable error to stdout before raising.

### .env.example

Updated with `PROVIDER`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL` placeholders with documentation comments.

### Tests

| File | New Tests | Coverage |
|------|-----------|---------|
| `tests/conftest.py` | Extended `monkeypatch_env` (4 new delenv vars) + `mock_openai_models_ok` + `mock_openai_models_401` fixtures | OpenAI httpx mock |
| `tests/unit/test_config.py` | 6 new tests | `SecretStr` loading, repr masking, default None, model env overrides |
| `tests/unit/test_runner.py` | 8 new tests | `build_llm` dispatch (4), `pre_flight_check` branches (4) |

**Total: 31 unit tests, all passing.**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] pre_flight_check structural fix**

- **Found during:** Task 2 implementation
- **Issue:** Initial edit appended `elif cfg.provider == "anthropic":` inside the Ollama-specific `if not any(model_base in m for m in models):` block as a sibling `elif`. This created a broken structure where Ollama model-check code ran for all providers before anthropic/openai branches were ever reached.
- **Fix:** Rewrote `pre_flight_check` with top-level provider dispatch (`if cfg.provider == "ollama": ... elif cfg.provider == "anthropic": ... elif cfg.provider == "openai": ...`). Ollama logic is fully contained in the `ollama` branch.
- **Files modified:** `agent/runner.py`
- **Commit:** Included in b8c9cbb

## Threat Mitigations Applied

Per the plan's `<threat_model>`:

| Threat | Mitigation Applied |
|--------|-------------------|
| T-02-01 Information Disclosure (API keys in repr) | `SecretStr \| None` for both provider keys; repr shows `SecretStr('**********')` |
| T-02-05 Information Disclosure (key in build_llm) | `.get_secret_value()` called only at LLM constructor call sites (2 in build_llm, 2 in pre_flight_check = 4 total); never assigned to module-level variables |
| T-02-06 Spoofing (pre_flight accepting any non-empty key) | Live endpoint validation before browser launch: `AsyncAnthropic.models.list()` for Anthropic, `GET /v1/models` for OpenAI |
| T-02-08 DoS (pre_flight hanging) | `httpx.AsyncClient(timeout=5.0)` for OpenAI; anthropic SDK has built-in timeout; generic Exception -> `PreFlightError("... unreachable")` |

## Known Stubs

None — all new fields are properly wired. The `anthropic_api_key` and `openai_api_key` default to `None` by design (user must set in `.env`). This is correct behavior, not a stub.

## Self-Check

### Files Exist
- [x] `agent/config.py` — exists with `SecretStr` fields
- [x] `agent/runner.py` — exists with `build_llm` and extended `pre_flight_check`
- [x] `.env.example` — exists with provider placeholders
- [x] `tests/conftest.py` — exists with new fixtures
- [x] `tests/unit/test_config.py` — exists with 6 new tests
- [x] `tests/unit/test_runner.py` — exists with 8 new tests

### Commits Exist
- [x] 2728478 — Task 1 test stubs
- [x] b8c9cbb — Task 2 implementation

## Self-Check: PASSED
