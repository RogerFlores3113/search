"""Phase 11 tests — Settings Panel + Domain Safety.

config mutability verified at scaffolding time: MUTABILITY_MODE: direct field assignment
(config.provider = value works without raising; no object.__setattr__ required)

Test inventory:
  GREEN in Task 1 (this plan):
    - test_config_field_assignment_works
    - test_settings_path_uses_user_config_dir

  GREEN in Task 2 (this plan):
    - test_fernet_key_stable
    - test_encrypt_decrypt_roundtrip
    - test_load_settings_json_missing_returns_empty
    - test_save_settings_json_atomic
    - test_cve_2025_47241_urlparse_used

  RED until Plan 02:
    - test_safety_defaults_banking
    - test_safety_defaults_gov_medical
    - test_cve_2025_47241_credential_url_blocked

  RED until Plan 03:
    - test_ollama_models_endpoint
    - test_ollama_models_unreachable
    - test_save_api_key_encrypted
    - test_get_settings_no_plaintext_key
    - test_save_updates_live_config
    - test_save_user_domains

  RED until Plan 04:
    - test_gear_button_present
    - test_settings_overlay_aria
    - test_domain_list_two_tier_html
"""
from __future__ import annotations

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Task 1: Mutability + Path tests (GREEN in Plan 01)
# ---------------------------------------------------------------------------

def test_config_field_assignment_works(monkeypatch_env):
    """Verify config.provider = value works (direct field assignment, not frozen)."""
    from agent.config import config
    original = config.provider
    try:
        config.provider = "anthropic"
        assert config.provider == "anthropic", "Direct field assignment must work"
    finally:
        config.provider = original


def test_settings_path_uses_user_config_dir():
    """get_settings_path() must return a path ending in .../local-browser-agent/settings.json."""
    from agent.paths import get_settings_path
    p = get_settings_path()
    assert p.name == "settings.json", f"Expected settings.json, got {p.name}"
    assert "local-browser-agent" in str(p), f"Expected local-browser-agent in path, got {p}"
    assert p.parent.exists(), f"Parent directory must be created: {p.parent}"


# ---------------------------------------------------------------------------
# Task 2: Fernet helpers + JSON I/O + CVE test (GREEN in Plan 01 Task 2)
# ---------------------------------------------------------------------------

def test_fernet_key_stable():
    """_derive_fernet_key() must return the same key on successive calls (machine-stable)."""
    from agent.settings import _derive_fernet_key, encrypt_api_key, decrypt_api_key
    # Encrypt with one derived key, decrypt with another — they must share the same key
    token = _derive_fernet_key().encrypt(b"test-value")
    result = _derive_fernet_key().decrypt(token)
    assert result == b"test-value", "Keys derived on same machine must be byte-identical"


def test_encrypt_decrypt_roundtrip():
    """encrypt_api_key / decrypt_api_key round-trip must recover the original string."""
    from agent.settings import encrypt_api_key, decrypt_api_key
    assert decrypt_api_key(encrypt_api_key("sk-test-123")) == "sk-test-123"
    assert decrypt_api_key(encrypt_api_key("")) == ""


def test_load_settings_json_missing_returns_empty(tmp_path, monkeypatch):
    """load_settings_json() must return {} silently when settings.json does not exist."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.settings import load_settings_json
    result = load_settings_json()
    assert result == {}, f"Expected empty dict, got {result!r}"


def test_save_settings_json_atomic(tmp_path, monkeypatch):
    """save_settings_json writes data atomically and leaves no .tmp file behind."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.settings import save_settings_json, load_settings_json
    save_settings_json({"a": 1, "b": "hello"})
    loaded = load_settings_json()
    assert loaded == {"a": 1, "b": "hello"}, f"Loaded data mismatch: {loaded!r}"
    # Verify no .tmp file left behind
    tmp_file = tmp_path / "settings.tmp"
    assert not tmp_file.exists(), f"Temp file must be removed after atomic write: {tmp_file}"


def test_cve_2025_47241_urlparse_used():
    """SAFE-04: browser-use 0.12.6 security_watchdog.py must use urlparse (CVE patched)."""
    import browser_use
    watchdog_path = Path(browser_use.__file__).parent / "browser" / "watchdogs" / "security_watchdog.py"
    assert watchdog_path.exists(), f"security_watchdog.py not found at {watchdog_path}"
    source = watchdog_path.read_text(encoding="utf-8")
    assert "urlparse" in source, "security_watchdog.py must use urlparse (CVE-2025-47241 patch)"
    assert "_is_url_allowed" in source, "security_watchdog.py must define _is_url_allowed"
    # Verify the import is from urllib.parse (not a colon-split workaround)
    assert "from urllib.parse import urlparse" in source or "urllib.parse" in source, (
        "urlparse must be imported from urllib.parse"
    )


# ---------------------------------------------------------------------------
# RED until Plan 02: SAFETY_DEFAULTS (config.py extension)
# ---------------------------------------------------------------------------

def test_safety_defaults_banking(monkeypatch_env):
    """SAFE-01: SAFETY_DEFAULTS frozenset must contain banking domains."""
    pytest.fail("RED — implemented in Plan 02 (config.py SAFETY_DEFAULTS)")


def test_safety_defaults_gov_medical(monkeypatch_env):
    """SAFE-01: SAFETY_DEFAULTS frozenset must contain government and medical domains."""
    pytest.fail("RED — implemented in Plan 02 (config.py SAFETY_DEFAULTS)")


def test_cve_2025_47241_credential_url_blocked(monkeypatch_env):
    """SAFE-04: credential-embedded URL (user:pass@chase.com) must be blocked."""
    pytest.fail("RED — implemented in Plan 02 (needs SAFETY_DEFAULTS in config.py)")


# ---------------------------------------------------------------------------
# RED until Plan 03: API endpoints (main.py extension)
# ---------------------------------------------------------------------------

async def test_ollama_models_endpoint(monkeypatch_env, mock_ollama_tags_ok):
    """SET-02: GET /api/settings/ollama-models returns list of model names."""
    pytest.fail("RED — implemented in Plan 03 (GET /api/settings/ollama-models)")


async def test_ollama_models_unreachable(monkeypatch_env, mock_ollama_unreachable):
    """SET-02: GET /api/settings/ollama-models returns error key when Ollama is down."""
    pytest.fail("RED — implemented in Plan 03 (GET /api/settings/ollama-models)")


async def test_save_api_key_encrypted(tmp_path, monkeypatch, monkeypatch_env):
    """SET-03: POST /api/settings encrypts API key — plaintext must not appear in settings.json."""
    pytest.fail("RED — implemented in Plan 03 (POST /api/settings)")


async def test_get_settings_no_plaintext_key(tmp_path, monkeypatch, monkeypatch_env):
    """SET-03: GET /api/settings returns anthropic_key_set bool, not plaintext or encrypted blob."""
    pytest.fail("RED — implemented in Plan 03 (GET /api/settings)")


async def test_save_updates_live_config(tmp_path, monkeypatch, monkeypatch_env):
    """SET-04: POST /api/settings patches config.provider live in-process."""
    pytest.fail("RED — implemented in Plan 03 (POST /api/settings live patch)")


async def test_save_user_domains(tmp_path, monkeypatch, monkeypatch_env):
    """SAFE-02: POST /api/settings persists user_domains list to settings.json."""
    pytest.fail("RED — implemented in Plan 03 (POST /api/settings user_domains)")


# ---------------------------------------------------------------------------
# RED until Plan 04: HTML/CSS (index.html + style.css extension)
# ---------------------------------------------------------------------------

def test_gear_button_present():
    """SET-01: index.html must contain gear button and showSettings Alpine prop."""
    pytest.fail("RED — implemented in Plan 04 (index.html gear button + showSettings)")


def test_settings_overlay_aria():
    """SET-01: settings overlay must have role=dialog and aria-modal=true."""
    pytest.fail("RED — implemented in Plan 04 (index.html settings overlay)")


def test_domain_list_two_tier_html():
    """SAFE-03: domain list must show user domains with remove (✕) and defaults with lock (🔒)."""
    pytest.fail("RED — implemented in Plan 04 (index.html two-tier domain list)")
