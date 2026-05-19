"""Phase 12 RED scaffold — Prompt Library.

Contains 12 failing test functions covering PROMPT-01 through PROMPT-07.
All tests are RED on first run because the symbols and HTML elements they assert
do not exist yet. Wave 1 (Plan 02) and Wave 2 (Plan 03) drive them GREEN.

Test names are normative — see .planning/phases/12-prompt-library/12-VALIDATION.md
for the canonical list and downstream verify commands.

RED run command:
    uv run pytest tests/unit/test_prompts_phase12.py -x -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# PROMPT-06: First-init seeding
# ---------------------------------------------------------------------------


def test_seed_prompts_written_when_absent(tmp_path, monkeypatch):
    """PROMPT-06: seed_prompts_if_absent() writes 4 seed entries when settings.json is absent."""
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: tmp_path / "settings.json")
    # Symbol does not exist yet — import inside body so collection succeeds
    from agent.settings import seed_prompts_if_absent  # noqa: PLC0415
    from agent.settings import load_settings_json  # noqa: PLC0415

    seed_prompts_if_absent()
    stored = load_settings_json()

    assert "prompts" in stored, "settings.json must contain 'prompts' key after seeding"
    assert len(stored["prompts"]) == 4, f"Expected 4 seed prompts, got {len(stored['prompts'])}"

    for entry in stored["prompts"]:
        for key in ("id", "name", "content", "is_seed"):
            assert key in entry, f"Seed entry missing key {key!r}: {entry}"
        assert entry["is_seed"] is True, f"is_seed must be True for seed entry: {entry}"

    ids = {p["id"] for p in stored["prompts"]}
    assert ids == {"generic", "apartment", "job", "candidate"}, (
        f"Expected exactly {{generic, apartment, job, candidate}}, got {ids}"
    )

    assert stored.get("active_prompt_id") == "generic", (
        f"active_prompt_id must default to 'generic', got {stored.get('active_prompt_id')!r}"
    )


def test_seed_prompts_not_overwritten_if_present(tmp_path, monkeypatch):
    """PROMPT-06: seed_prompts_if_absent() does NOT overwrite when 'prompts' key exists."""
    settings_file = tmp_path / "settings.json"
    existing = {
        "prompts": [{"id": "custom", "name": "X", "content": "x", "is_seed": False}],
        "active_prompt_id": "custom",
    }
    settings_file.write_text(json.dumps(existing))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.settings import seed_prompts_if_absent  # noqa: PLC0415
    from agent.settings import load_settings_json  # noqa: PLC0415

    seed_prompts_if_absent()
    stored = load_settings_json()

    assert len(stored["prompts"]) == 1, (
        f"Seeding must NOT add prompts when key already exists; got {stored['prompts']}"
    )
    assert stored["prompts"][0]["id"] == "custom", (
        "Existing 'custom' entry must be preserved unchanged"
    )
    assert stored.get("active_prompt_id") == "custom", (
        f"active_prompt_id must remain 'custom', got {stored.get('active_prompt_id')!r}"
    )
    assert not any(p["id"] == "generic" for p in stored["prompts"]), (
        "No 'generic' seed must be added when prompts key already exists"
    )


# ---------------------------------------------------------------------------
# PROMPT-01: GET /api/settings returns prompts list
# ---------------------------------------------------------------------------


async def test_get_settings_returns_prompts(tmp_path, monkeypatch):
    """PROMPT-01: GET /api/settings includes 'prompts' list and 'active_prompt_id'."""
    settings_file = tmp_path / "settings.json"
    seed_data = [
        {"id": "generic", "name": "Generic", "content": "gen", "is_seed": True},
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
        {"id": "job", "name": "Job Search", "content": "job", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "apartment"}))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.main import app  # noqa: PLC0415

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    body = r.json()
    assert isinstance(body.get("prompts"), list), (
        f"'prompts' must be a list in GET /api/settings response; got {body.get('prompts')!r}"
    )
    assert len(body["prompts"]) == 4, (
        f"Expected 4 prompts in response, got {len(body['prompts'])}"
    )
    assert body.get("active_prompt_id") == "apartment", (
        f"active_prompt_id must be 'apartment', got {body.get('active_prompt_id')!r}"
    )


# ---------------------------------------------------------------------------
# PROMPT-02: addPrompt() Alpine function (HTML inspection)
# ---------------------------------------------------------------------------


def test_add_prompt_creates_entry():
    """PROMPT-02: index.html contains addPrompt() with crypto.randomUUID() and is_seed: false."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert "addPrompt()" in html, "index.html must contain addPrompt() call"
    assert "crypto.randomUUID(" in html, (
        "addPrompt() must use crypto.randomUUID() for new prompt ids"
    )
    assert "is_seed: false" in html, (
        "addPrompt() must default is_seed: false for new user-created prompts"
    )


# ---------------------------------------------------------------------------
# PROMPT-03: POST /api/settings persists prompt edits
# ---------------------------------------------------------------------------


async def test_save_prompts_persists_edit(tmp_path, monkeypatch):
    """PROMPT-03: POST /api/settings with edited prompts_json persists the change."""
    settings_file = tmp_path / "settings.json"
    seed_data = [
        {"id": "generic", "name": "Generic", "content": "ORIGINAL-CONTENT", "is_seed": True},
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
        {"id": "job", "name": "Job Search", "content": "job", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "generic"}))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.main import app  # noqa: PLC0415
    from agent.settings import load_settings_json  # noqa: PLC0415

    edited = [
        {"id": "generic", "name": "Generic", "content": "EDITED-CONTENT", "is_seed": True},
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
        {"id": "job", "name": "Job Search", "content": "job", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/settings", data={
            "provider": "ollama",
            "anthropic_key_action": "keep",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
            "prompts_json": json.dumps(edited),
            "active_prompt_id": "generic",
        })

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    stored = load_settings_json()
    generic_entry = next((p for p in stored.get("prompts", []) if p["id"] == "generic"), None)
    assert generic_entry is not None, "generic prompt entry must be present in stored settings"
    assert generic_entry["content"] == "EDITED-CONTENT", (
        f"generic prompt content must be 'EDITED-CONTENT', got {generic_entry['content']!r}"
    )


# ---------------------------------------------------------------------------
# PROMPT-04: POST accepts payload as sent (seed deletion via API is allowed)
# ---------------------------------------------------------------------------


async def test_seed_prompts_not_deleted_via_api(tmp_path, monkeypatch):
    """PROMPT-04: POST with omitted 'job' seed — server accepts payload; job entry is gone.

    Documents the locked decision (RESEARCH.md Open Question 1): server accepts the payload
    as sent. The UI is what prevents seed deletion, not the server. Asserts the inverse —
    that the API does NOT silently re-add a missing seed entry.
    """
    settings_file = tmp_path / "settings.json"
    seed_data = [
        {"id": "generic", "name": "Generic", "content": "gen", "is_seed": True},
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
        {"id": "job", "name": "Job Search", "content": "job", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "generic"}))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.main import app  # noqa: PLC0415
    from agent.settings import load_settings_json  # noqa: PLC0415

    # Payload omits the 'job' entry
    without_job = [
        {"id": "generic", "name": "Generic", "content": "gen", "is_seed": True},
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/settings", data={
            "provider": "ollama",
            "anthropic_key_action": "keep",
            "openai_key_action": "keep",
            "user_domains_json": "[]",
            "prompts_json": json.dumps(without_job),
            "active_prompt_id": "generic",
        })

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    stored = load_settings_json()
    assert not any(p["id"] == "job" for p in stored.get("prompts", [])), (
        "Server must NOT silently re-add 'job' seed; it was omitted from payload"
    )


# ---------------------------------------------------------------------------
# PROMPT-05: active_prompt_id saved and live-patched in config
# ---------------------------------------------------------------------------


async def test_active_prompt_id_saved_and_live_patched(tmp_path, monkeypatch):
    """PROMPT-05: POST /api/settings saves active_prompt_id and live-patches config."""
    settings_file = tmp_path / "settings.json"
    seed_data = [
        {"id": "generic", "name": "Generic", "content": "gen", "is_seed": True},
        {"id": "candidate", "name": "Candidate Search", "content": "cand", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "generic"}))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.main import app  # noqa: PLC0415
    from agent.settings import load_settings_json  # noqa: PLC0415
    import agent.config as cfg_mod  # noqa: PLC0415

    original_active = getattr(cfg_mod.config, "active_prompt_id", None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/settings", data={
                "provider": "ollama",
                "anthropic_key_action": "keep",
                "openai_key_action": "keep",
                "user_domains_json": "[]",
                "prompts_json": json.dumps(seed_data),
                "active_prompt_id": "candidate",
            })

        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        stored = load_settings_json()
        assert stored.get("active_prompt_id") == "candidate", (
            f"settings.json must have active_prompt_id='candidate', got {stored.get('active_prompt_id')!r}"
        )
        assert cfg_mod.config.active_prompt_id == "candidate", (
            f"config.active_prompt_id must be live-patched to 'candidate', got {cfg_mod.config.active_prompt_id!r}"
        )
    finally:
        if original_active is not None:
            cfg_mod.config.active_prompt_id = original_active


# ---------------------------------------------------------------------------
# PROMPT-07: _build_extend_system_message — GUARDRAIL always appended
# ---------------------------------------------------------------------------


def test_guardrail_always_appended():
    """PROMPT-07: _build_extend_system_message() appends GUARDRAIL_PROMPT as suffix."""
    # Import inside body — symbol does not exist until Wave 1
    from agent.runner import _build_extend_system_message, GUARDRAIL_PROMPT  # noqa: PLC0415

    prompts = [{"id": "generic", "name": "Generic", "content": "USER-CONTENT", "is_seed": True}]
    msg = _build_extend_system_message("generic", prompts)

    assert msg.startswith("USER-CONTENT"), (
        f"Built message must start with user prompt content; got: {msg[:80]!r}"
    )
    assert msg.endswith(GUARDRAIL_PROMPT), (
        "Built message must end with GUARDRAIL_PROMPT"
    )
    assert "\n\n" in msg, "User content and GUARDRAIL_PROMPT must be separated by double newline"


def test_guardrail_fallback_when_no_active_prompt():
    """PROMPT-07: _build_extend_system_message() falls back to GUARDRAIL_PROMPT when no match."""
    from agent.runner import _build_extend_system_message, GUARDRAIL_PROMPT  # noqa: PLC0415

    # Empty active_prompt_id
    assert _build_extend_system_message("", []) == GUARDRAIL_PROMPT, (
        "Empty active_prompt_id + empty list must return GUARDRAIL_PROMPT"
    )

    # active_prompt_id not found in prompts list
    prompts = [{"id": "generic", "name": "Generic", "content": "X", "is_seed": True}]
    assert _build_extend_system_message("missing-id", prompts) == GUARDRAIL_PROMPT, (
        "Missing ID must fall back to GUARDRAIL_PROMPT"
    )

    # Matching entry has empty content
    empty_content = [{"id": "generic", "name": "Generic", "content": "", "is_seed": True}]
    assert _build_extend_system_message("generic", empty_content) == GUARDRAIL_PROMPT, (
        "Empty prompt content must fall back to GUARDRAIL_PROMPT"
    )


# ---------------------------------------------------------------------------
# PROMPT-07 (T-12-01): GET /api/settings must not leak GUARDRAIL_PROMPT
# ---------------------------------------------------------------------------


async def test_guardrail_not_in_api_response(tmp_path, monkeypatch):
    """T-12-01: GET /api/settings response must never include GUARDRAIL_PROMPT content."""
    settings_file = tmp_path / "settings.json"
    seed_data = [
        {"id": "generic", "name": "Generic", "content": "gen", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "generic"}))

    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)
    from agent.main import app  # noqa: PLC0415
    from agent.runner import GUARDRAIL_PROMPT  # noqa: PLC0415

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/settings")

    assert r.status_code == 200
    assert GUARDRAIL_PROMPT not in r.text, (
        "GUARDRAIL_PROMPT content must not appear in GET /api/settings response"
    )
    assert "GUARDRAIL_PROMPT" not in r.text, (
        "The literal symbol name 'GUARDRAIL_PROMPT' must not leak in API response"
    )


# ---------------------------------------------------------------------------
# PROMPT-01/05: HTML — active prompt label below task textarea
# ---------------------------------------------------------------------------


def test_active_prompt_label_in_html():
    """PROMPT-01/05: index.html contains active-prompt-label span with activePromptName."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert "active-prompt-label" in html, (
        "index.html must contain 'active-prompt-label' CSS class"
    )
    assert "System prompt: " in html, (
        "index.html must contain literal 'System prompt: ' (matches x-text binding)"
    )
    assert "activePromptName" in html, (
        "index.html must contain 'activePromptName' Alpine method reference"
    )


# ---------------------------------------------------------------------------
# PROMPT-01/06: HTML — prompt section in settings overlay
# ---------------------------------------------------------------------------


def test_prompt_section_in_settings_overlay():
    """PROMPT-01/06: index.html settings overlay contains System Prompts section."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert "System Prompts" in html, (
        "index.html must contain 'System Prompts' heading in settings overlay"
    )
    assert "prompt-list" in html, (
        "index.html must contain 'prompt-list' CSS class (new in Phase 12)"
    )
    assert "prompt-editor" in html, (
        "index.html must contain 'prompt-editor' CSS class (new in Phase 12)"
    )
    assert "addPrompt" in html, (
        "index.html must contain 'addPrompt' function reference"
    )
    assert "deletePrompt" in html, (
        "index.html must contain 'deletePrompt' function reference"
    )
