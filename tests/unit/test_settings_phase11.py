"""Phase 11 tests — Settings Panel + Domain Safety.

config mutability verified at scaffolding time: MUTABILITY_MODE: direct field assignment
(config.provider = value works without raising; no object.__setattr__ required)

Test inventory:
  GREEN in Plan 01:
    - test_config_field_assignment_works
    - test_settings_path_uses_user_config_dir
    - test_fernet_key_stable
    - test_encrypt_decrypt_roundtrip
    - test_load_settings_json_missing_returns_empty
    - test_save_settings_json_atomic
    - test_cve_2025_47241_urlparse_used

  GREEN in Plan 02:
    - test_safety_defaults_banking
    - test_safety_defaults_gov_medical
    - test_blocked_domains_property_includes_user_domains
    - test_settings_json_overrides_env
    - test_cve_2025_47241_credential_url_blocked

  GREEN in Plan 03 (Task 1):
    - test_ollama_models_endpoint
    - test_ollama_models_unreachable
    - test_get_settings_sanitized_shape

  GREEN in Plan 03 (Task 2):
    - test_save_api_key_encrypted
    - test_get_settings_no_plaintext_key
    - test_save_updates_live_config
    - test_save_user_domains
    - test_save_key_action_keep_preserves
    - test_save_key_action_clear_removes

  RED until Plan 04:
    - test_gear_button_present
    - test_settings_overlay_aria
    - test_domain_list_two_tier_html
"""
from __future__ import annotations

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport


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
# GREEN in Plan 02: SAFETY_DEFAULTS (config.py extension)
# ---------------------------------------------------------------------------

def test_safety_defaults_banking(monkeypatch_env):
    """SAFE-01: SAFETY_DEFAULTS frozenset must contain banking and payment domains."""
    from agent.config import SAFETY_DEFAULTS
    assert isinstance(SAFETY_DEFAULTS, frozenset), "SAFETY_DEFAULTS must be a frozenset"
    assert {"chase.com", "wellsfargo.com", "paypal.com", "venmo.com"}.issubset(SAFETY_DEFAULTS), (
        f"Banking/payment domains missing from SAFETY_DEFAULTS: {SAFETY_DEFAULTS}"
    )


def test_safety_defaults_gov_medical(monkeypatch_env):
    """SAFE-01: SAFETY_DEFAULTS frozenset must contain government, medical, and credential domains."""
    from agent.config import SAFETY_DEFAULTS
    assert {
        "irs.gov", "ssa.gov", "healthcare.gov",
        "labcorp.com", "mychart.com",
        "lastpass.com", "1password.com",
    }.issubset(SAFETY_DEFAULTS), (
        f"Gov/medical/credential domains missing from SAFETY_DEFAULTS: {SAFETY_DEFAULTS}"
    )


def test_blocked_domains_property_includes_user_domains(monkeypatch_env):
    """SAFE-01: blocked_domains property merges SAFETY_DEFAULTS with user_domains."""
    from agent.config import Settings
    s = Settings(user_domains=["myexample.com"])
    assert "myexample.com" in s.blocked_domains, "User domain must appear in blocked_domains"
    assert "chase.com" in s.blocked_domains, "Safety default must still appear in blocked_domains"


def test_settings_json_overrides_env(tmp_path, monkeypatch):
    """SET-04: JsonConfigSettingsSource injects settings.json above .env in precedence."""
    import json
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"provider": "anthropic", "user_domains": ["foo.com"]}))

    # Patch both locations so the classmethod sees the temp file.
    monkeypatch.setattr("agent.paths.get_settings_path", lambda: settings_file)
    monkeypatch.setattr("agent.config.get_settings_path", lambda: settings_file, raising=False)

    # Re-import Settings fresh (do NOT use the module-level config singleton).
    import importlib
    import agent.config as cfg_module
    importlib.reload(cfg_module)
    s = cfg_module.Settings()
    assert s.provider == "anthropic", f"Expected anthropic from JSON, got {s.provider!r}"
    assert s.user_domains == ["foo.com"], f"Expected ['foo.com'] from JSON, got {s.user_domains!r}"
    # Reload back to defaults so other tests are not affected.
    importlib.reload(cfg_module)


def test_cve_2025_47241_credential_url_blocked(monkeypatch_env):
    """SAFE-04: credential-embedded URL (user:pass@chase.com) must be blocked via SAFETY_DEFAULTS."""
    from urllib.parse import urlparse
    from agent.config import SAFETY_DEFAULTS

    # Simulate what browser-use's _is_url_allowed does: urlparse strips credentials.
    url = "https://creds@chase.com/login"
    hostname = urlparse(url).hostname
    assert hostname == "chase.com", f"urlparse must strip credentials; got hostname={hostname!r}"
    assert "chase.com" in SAFETY_DEFAULTS, (
        "chase.com must be in SAFETY_DEFAULTS so BrowserProfile blocks it"
    )


# ---------------------------------------------------------------------------
# GREEN in Plan 03 Task 1: GET /api/settings and GET /api/settings/ollama-models
# ---------------------------------------------------------------------------

async def test_ollama_models_endpoint(monkeypatch_env, mock_ollama_tags_ok):
    """SET-02: GET /api/settings/ollama-models returns list of model names."""
    from agent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings/ollama-models")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == ["qwen3-vl:8b", "gemma4:e4b"]
    assert "error" not in body


async def test_ollama_models_unreachable(monkeypatch_env, mock_ollama_unreachable):
    """SET-02: GET /api/settings/ollama-models returns error key when Ollama is down."""
    from agent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings/ollama-models")
    assert r.status_code == 200
    assert r.json() == {"models": [], "error": "unreachable"}


async def test_get_settings_sanitized_shape(tmp_path, monkeypatch, monkeypatch_env):
    """T-11-11: GET /api/settings response never leaks plaintext keys or encrypted blobs."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    # Required keys present
    for key in ("provider", "safety_defaults", "user_domains", "anthropic_key_set", "openai_key_set"):
        assert key in body, f"Missing expected key: {key}"
    # No key set when no settings.json
    assert body["anthropic_key_set"] is False
    assert body["openai_key_set"] is False
    # Forbidden keys absent (T-11-11)
    forbidden = {"anthropic_api_key", "openai_api_key", "anthropic_api_key_enc", "openai_api_key_enc"}
    assert not (forbidden & set(body.keys())), f"Forbidden keys in response: {forbidden & set(body.keys())}"


# ---------------------------------------------------------------------------
# GREEN in Plan 03 Task 2: POST /api/settings
# ---------------------------------------------------------------------------

async def test_save_api_key_encrypted(tmp_path, monkeypatch, monkeypatch_env):
    """SET-03: POST /api/settings encrypts API key — plaintext must not appear in settings.json."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    from agent.settings import decrypt_api_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/settings", data={
            "provider": "anthropic",
            "anthropic_key_action": "set",
            "anthropic_key_value": "sk-test-123",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
        })
    assert r.status_code == 200
    assert r.json() == {"status": "saved"}

    data = _json.loads((tmp_path / "settings.json").read_text())
    assert "anthropic_api_key_enc" in data
    assert "sk-test-123" not in data["anthropic_api_key_enc"]
    # Raw text scan
    assert "sk-test-123" not in (tmp_path / "settings.json").read_text()
    # Roundtrip proves encryption is real
    assert decrypt_api_key(data["anthropic_api_key_enc"]) == "sk-test-123"


async def test_get_settings_no_plaintext_key(tmp_path, monkeypatch, monkeypatch_env):
    """SET-03: GET /api/settings returns anthropic_key_set bool, not plaintext or encrypted blob."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # POST a key first
        await client.post("/api/settings", data={
            "provider": "anthropic",
            "anthropic_key_action": "set",
            "anthropic_key_value": "sk-test-123",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
        })
        r = await client.get("/api/settings")

    assert r.status_code == 200
    assert r.json()["anthropic_key_set"] is True
    # No plaintext in full response body
    assert "sk-test-123" not in r.text
    # No forbidden keys in response
    forbidden = {"anthropic_api_key", "anthropic_api_key_enc", "openai_api_key", "openai_api_key_enc"}
    assert not (forbidden & set(r.json().keys()))


async def test_save_updates_live_config(tmp_path, monkeypatch, monkeypatch_env):
    """SET-04: POST /api/settings patches config.provider live in-process."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original_provider = cfg_mod.config.provider
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
        assert r.status_code == 200
        assert cfg_mod.config.provider == "anthropic"
    finally:
        cfg_mod.config.provider = original_provider


async def test_save_user_domains(tmp_path, monkeypatch, monkeypatch_env):
    """SAFE-02: POST /api/settings persists user_domains list, filters SAFETY_DEFAULTS."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original_domains = list(cfg_mod.config.user_domains)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/settings", data={
                "provider": "ollama",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": '["example.com","wellsfargo.com","  ","https://foo.com/"]',
            })
        assert r.status_code == 200
        data = _json.loads((tmp_path / "settings.json").read_text())
        assert data["user_domains"] == ["example.com", "foo.com"]
        assert "wellsfargo.com" not in data["user_domains"]
        assert cfg_mod.config.user_domains == ["example.com", "foo.com"]
    finally:
        cfg_mod.config.user_domains = original_domains


async def test_save_key_action_keep_preserves(tmp_path, monkeypatch, monkeypatch_env):
    """Pitfall 4 regression gate: key_action=keep must not overwrite existing encrypted key."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    from agent.settings import decrypt_api_key

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First: set a real key
        await client.post("/api/settings", data={
            "provider": "anthropic",
            "anthropic_key_action": "set",
            "anthropic_key_value": "sk-original",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
        })
        blob1 = _json.loads((tmp_path / "settings.json").read_text())["anthropic_api_key_enc"]

        # Second: submit with keep + empty value — blob must be unchanged
        await client.post("/api/settings", data={
            "provider": "anthropic",
            "anthropic_key_action": "keep",
            "anthropic_key_value": "",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
        })
        blob2 = _json.loads((tmp_path / "settings.json").read_text())["anthropic_api_key_enc"]

    assert blob1 == blob2, "keep must not rotate the encrypted key"
    assert decrypt_api_key(blob2) == "sk-original"


async def test_save_key_action_clear_removes(tmp_path, monkeypatch, monkeypatch_env):
    """key_action=clear must remove the encrypted key from settings.json and config."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original_key = cfg_mod.config.anthropic_api_key
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_key_action": "set",
                "anthropic_key_value": "sk-tmp",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
            await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_key_action": "clear",
                "anthropic_key_value": "",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
            data = _json.loads((tmp_path / "settings.json").read_text())
            assert "anthropic_api_key_enc" not in data

            r = await client.get("/api/settings")
            assert r.json()["anthropic_key_set"] is False
        assert cfg_mod.config.anthropic_api_key is None
    finally:
        cfg_mod.config.anthropic_api_key = original_key


# ---------------------------------------------------------------------------
# RED until Plan 04: HTML/CSS (index.html + style.css extension)
# ---------------------------------------------------------------------------

def test_gear_button_present():
    """SET-01: index.html must contain gear button and showSettings Alpine prop."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'aria-label="Open settings"' in html, "Gear button aria-label missing"
    assert 'showSettings = true' in html, "showSettings = true click handler missing"
    assert '⚙' in html or '&#x2699;' in html, "Gear icon (⚙) missing"
    assert 'showSettings:' in html, "showSettings Alpine prop initializer missing"


def test_settings_overlay_aria():
    """SET-01: settings overlay must have role=dialog and aria-modal=true."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'role="dialog"' in html, "role=dialog missing"
    assert 'aria-modal="true"' in html, "aria-modal=true missing"
    assert 'aria-labelledby="settings-title"' in html, "aria-labelledby=settings-title missing"
    assert 'id="settings-title"' in html, "id=settings-title missing"
    assert 'x-show="showSettings"' in html, "x-show=showSettings missing"
    assert '>Settings<' in html, "Settings title text missing"


def test_domain_list_two_tier_html():
    """SAFE-03: domain list must show user domains with remove (✕) and defaults with lock (🔒)."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'domain-row--locked' in html, "Locked domain row class missing"
    assert 'domain-row--user' in html, "User domain row class missing"
    assert 'safetyDefaults' in html, "safetyDefaults prop reference missing"
    assert 'userDomains' in html, "userDomains prop reference missing"
    assert 'Remove ${d}' in html, "Remove aria-label template literal missing"
    assert '🔒' in html or '&#x1F512;' in html, "Lock icon (🔒) missing"
    # XSS guard: no innerHTML assignment on non-comment lines (matches Phase 10 test_index_no_unsafe_html)
    assert 'innerHTML =' not in html, "innerHTML assignment found in index.html (XSS risk)"


def test_no_innerhtml_phase11():
    """Defense-in-depth: no innerHTML assignment in index.html (Phase 10 XSS guard re-assertion)."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'innerHTML =' not in html, "innerHTML assignment found in index.html (XSS risk)"


# ---------------------------------------------------------------------------
# Plan 05 Task 1 — CR-01 regression: overlay inside agentUI() scope
# ---------------------------------------------------------------------------

def test_settings_overlay_inside_agentui_scope():
    """CR-01: settings-overlay div must be a descendant of the agentUI() Alpine scope (#sse-container)."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    # Find the position of the agentUI() x-data attribute (opening of #sse-container)
    agentui_pos = html.index('x-data="agentUI()"')
    # Find the closing marker of #sse-container
    sse_close_pos = html.index('</div><!-- /sse-container -->')
    # Find the settings-overlay class attribute
    overlay_pos = html.index('class="settings-overlay"')
    assert overlay_pos > agentui_pos, (
        "settings-overlay must appear AFTER x-data=\"agentUI()\" (i.e., inside the agentUI scope); "
        f"overlay at {overlay_pos}, agentUI at {agentui_pos}"
    )
    assert overlay_pos < sse_close_pos, (
        "settings-overlay must appear BEFORE </div><!-- /sse-container --> "
        f"(i.e., inside the agentUI scope); overlay at {overlay_pos}, sse-close at {sse_close_pos}"
    )


def test_settings_overlay_not_in_outer_disclaimer_scope():
    """CR-01: settings-overlay must NOT appear before the agentUI() scope (i.e., not in the outer disclaimer scope)."""
    html = (Path(__file__).parent.parent.parent / "agent" / "templates" / "index.html").read_text(encoding="utf-8")
    agentui_pos = html.index('x-data="agentUI()"')
    overlay_pos = html.index('class="settings-overlay"')
    assert overlay_pos > agentui_pos, (
        "settings-overlay must NOT be in the outer disclaimer Alpine scope — "
        f"it must come AFTER x-data=\"agentUI()\"; overlay at {overlay_pos}, agentUI at {agentui_pos}"
    )


# ---------------------------------------------------------------------------
# Plan 05 Task 2 — CR-02 + CR-03 regression: provider enum gate + model round-trip
# ---------------------------------------------------------------------------

async def test_post_settings_rejects_invalid_provider(tmp_path, monkeypatch, monkeypatch_env):
    """CR-02: POST /api/settings must reject unknown provider with HTTP 422 and not modify settings.json."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app

    # Write a known-good settings.json so we can verify it is unchanged after rejection
    initial_data = {"provider": "ollama"}
    (tmp_path / "settings.json").write_text(_json.dumps(initial_data))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/settings", data={
            "provider": "evilcorp",
            "anthropic_key_action": "keep",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
        })
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    body = r.json()
    assert body.get("detail") == "invalid provider", f"Expected detail='invalid provider', got {body}"
    # settings.json must be unchanged
    on_disk = _json.loads((tmp_path / "settings.json").read_text())
    assert on_disk == initial_data, f"settings.json was modified on rejection: {on_disk}"


async def test_post_settings_accepts_each_valid_provider(tmp_path, monkeypatch, monkeypatch_env):
    """CR-02: POST /api/settings must accept each provider in {ollama, anthropic, openai}."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original = cfg_mod.config.provider
    try:
        for provider in ("ollama", "anthropic", "openai"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post("/api/settings", data={
                    "provider": provider,
                    "anthropic_key_action": "keep",
                    "openai_key_action": "keep",
                    "user_domains_json": "[]",
                })
            assert r.status_code == 200, f"provider={provider!r} expected 200, got {r.status_code}"
            assert cfg_mod.config.provider == provider, (
                f"config.provider not updated for provider={provider!r}: {cfg_mod.config.provider!r}"
            )
    finally:
        cfg_mod.config.provider = original


async def test_post_settings_persists_anthropic_model(tmp_path, monkeypatch, monkeypatch_env):
    """CR-03: POST /api/settings must persist anthropic_model to settings.json AND live-patch config."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original = cfg_mod.config.anthropic_model
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_model": "claude-opus-4-5",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        on_disk = _json.loads((tmp_path / "settings.json").read_text())
        assert on_disk.get("anthropic_model") == "claude-opus-4-5", (
            f"settings.json[anthropic_model] expected 'claude-opus-4-5', got {on_disk.get('anthropic_model')!r}"
        )
        assert cfg_mod.config.anthropic_model == "claude-opus-4-5", (
            f"config.anthropic_model expected 'claude-opus-4-5', got {cfg_mod.config.anthropic_model!r}"
        )
    finally:
        cfg_mod.config.anthropic_model = original


async def test_post_settings_persists_openai_model(tmp_path, monkeypatch, monkeypatch_env):
    """CR-03: POST /api/settings must persist openai_model to settings.json AND live-patch config."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original = cfg_mod.config.openai_model
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/settings", data={
                "provider": "openai",
                "openai_model": "gpt-4o-mini",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        on_disk = _json.loads((tmp_path / "settings.json").read_text())
        assert on_disk.get("openai_model") == "gpt-4o-mini", (
            f"settings.json[openai_model] expected 'gpt-4o-mini', got {on_disk.get('openai_model')!r}"
        )
        assert cfg_mod.config.openai_model == "gpt-4o-mini", (
            f"config.openai_model expected 'gpt-4o-mini', got {cfg_mod.config.openai_model!r}"
        )
    finally:
        cfg_mod.config.openai_model = original


async def test_post_settings_blank_model_preserves_existing(tmp_path, monkeypatch, monkeypatch_env):
    """CR-03: Submitting blank anthropic_model must preserve the existing stored value (fallback pattern)."""
    import json as _json
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    from agent.main import app
    import agent.config as cfg_mod

    original = cfg_mod.config.anthropic_model
    try:
        # First: store a model name
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_model": "claude-sonnet-4-5",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
            # Second: submit with blank anthropic_model — stored value must be preserved
            r = await client.post("/api/settings", data={
                "provider": "anthropic",
                "anthropic_model": "",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
            })
        assert r.status_code == 200
        on_disk = _json.loads((tmp_path / "settings.json").read_text())
        assert on_disk.get("anthropic_model") == "claude-sonnet-4-5", (
            f"Blank submit must preserve existing model; got {on_disk.get('anthropic_model')!r}"
        )
    finally:
        cfg_mod.config.anthropic_model = original
