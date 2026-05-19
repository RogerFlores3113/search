"""Phase 13 RED scaffold — Task Presets + Prompt Engineering + Runner Wiring.

Contains 12 failing test functions covering PRESET-01 through PRESET-03,
ENG-01 through ENG-04, runner snapshot, DB migration, /run endpoint, and
runs_fragment rendering.

All tests are RED on first run because the target symbols/HTML/columns do not
exist yet. Every subsequent plan must turn one or more of these tests green.

Test names are normative — see .planning/phases/13-task-presets-prompt-engineering-runner-wiring/13-VALIDATION.md
for the canonical list and downstream verify commands.

RED run command:
    uv run pytest tests/unit/test_presets_phase13.py -x -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import aiosqlite
from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# PRESET-01: Preset buttons present in index.html
# ---------------------------------------------------------------------------


def test_preset_buttons_in_html():
    """PRESET-01: index.html must contain preset-row + three preset buttons."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert 'class="preset-row"' in html, (
        "index.html must contain class=\"preset-row\""
    )
    assert 'class="btn btn-preset"' in html, (
        "index.html must contain class=\"btn btn-preset\""
    )
    assert "@click=\"applyPreset('apartment-search')\"" in html, (
        "index.html must contain applyPreset('apartment-search') click handler"
    )
    assert "@click=\"applyPreset('job-search')\"" in html, (
        "index.html must contain applyPreset('job-search') click handler"
    )
    assert "@click=\"applyPreset('candidate-search')\"" in html, (
        "index.html must contain applyPreset('candidate-search') click handler"
    )
    assert "Apartment Search" in html, "index.html must contain 'Apartment Search' button label"
    assert "Job Search" in html, "index.html must contain 'Job Search' button label"
    assert "Candidate Search" in html, "index.html must contain 'Candidate Search' button label"


# ---------------------------------------------------------------------------
# PRESET-02: applyPreset() method defined in index.html
# ---------------------------------------------------------------------------


def test_apply_preset_method_in_html():
    """PRESET-02: index.html must define applyPreset() with PRESET_TEMPLATES and slugToPromptId."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert "applyPreset(presetSlug)" in html, (
        "index.html must define applyPreset(presetSlug) method"
    )
    assert "PRESET_TEMPLATES" in html, (
        "index.html must define PRESET_TEMPLATES lookup"
    )
    assert "'apartment-search':" in html, (
        "index.html must contain 'apartment-search' key in template map"
    )
    assert "'job-search':" in html, (
        "index.html must contain 'job-search' key in template map"
    )
    assert "'candidate-search':" in html, (
        "index.html must contain 'candidate-search' key in template map"
    )
    assert "slugToPromptId" in html, (
        "index.html must define slugToPromptId mapping"
    )
    assert "querySelector('textarea[name=\"task\"]')" in html, (
        "index.html applyPreset must querySelector for task textarea"
    )
    assert ".focus()" in html, (
        "index.html applyPreset must call .focus() on textarea"
    )


# ---------------------------------------------------------------------------
# PRESET-03 (frontend): applyPreset sets activePromptId
# ---------------------------------------------------------------------------


def test_apply_preset_sets_active_prompt_id():
    """PRESET-03 (frontend): applyPreset() must set this.activePromptId from slugToPromptId."""
    html = Path("agent/templates/index.html").read_text(encoding="utf-8")
    assert "this.activePromptId = slugToPromptId[presetSlug]" in html, (
        "index.html applyPreset must set this.activePromptId = slugToPromptId[presetSlug]"
    )
    assert "'apartment-search': 'apartment'" in html, (
        "slugToPromptId must map 'apartment-search' -> 'apartment'"
    )
    # Accept both spacing variants
    assert ("'job-search':       'job'" in html or "'job-search': 'job'" in html), (
        "slugToPromptId must map 'job-search' -> 'job'"
    )
    assert "'candidate-search': 'candidate'" in html, (
        "slugToPromptId must map 'candidate-search' -> 'candidate'"
    )


# ---------------------------------------------------------------------------
# ENG-01: Generic system prompt quality
# ---------------------------------------------------------------------------


def test_generic_prompt_eng01():
    """ENG-01: SEED_PROMPTS 'generic' entry must be a substantive structured prompt."""
    from agent.settings import SEED_PROMPTS  # noqa: PLC0415

    entry = next((p for p in SEED_PROMPTS if p["id"] == "generic"), None)
    assert entry is not None, "SEED_PROMPTS must contain entry with id='generic'"
    content = entry["content"]
    for keyword in ("ENVIRONMENT", "NUMBERED STEPS", "STOP CONDITIONS", "OUTPUT SCHEMA",
                    "TIME/COST AWARENESS", "is_done"):
        assert keyword in content, (
            f"generic prompt must contain {keyword!r}; content excerpt: {content[:200]!r}"
        )
    assert len(content.splitlines()) >= 20, (
        f"generic prompt must be at least 20 lines; got {len(content.splitlines())}"
    )


# ---------------------------------------------------------------------------
# ENG-02: Apartment system prompt quality
# ---------------------------------------------------------------------------


def test_apartment_prompt_eng02():
    """ENG-02: SEED_PROMPTS 'apartment' entry must reference target sites and structured fields."""
    from agent.settings import SEED_PROMPTS  # noqa: PLC0415

    entry = next((p for p in SEED_PROMPTS if p["id"] == "apartment"), None)
    assert entry is not None, "SEED_PROMPTS must contain entry with id='apartment'"
    content = entry["content"]
    for keyword in ("Craigslist", "Apartments.com", "Zillow", "STOP CONDITIONS",
                    "JSON", "address", "price", "bedrooms"):
        assert keyword in content, (
            f"apartment prompt must contain {keyword!r}; content excerpt: {content[:200]!r}"
        )
    assert ("pagination" in content or "page" in content), (
        "apartment prompt must mention pagination behavior"
    )
    assert len(content.splitlines()) >= 20, (
        f"apartment prompt must be at least 20 lines; got {len(content.splitlines())}"
    )


# ---------------------------------------------------------------------------
# ENG-03: Job system prompt quality (unauthenticated flows only)
# ---------------------------------------------------------------------------


def test_job_prompt_eng03():
    """ENG-03: SEED_PROMPTS 'job' entry must enforce unauthenticated-only constraint."""
    from agent.settings import SEED_PROMPTS  # noqa: PLC0415

    entry = next((p for p in SEED_PROMPTS if p["id"] == "job"), None)
    assert entry is not None, "SEED_PROMPTS must contain entry with id='job'"
    content = entry["content"]
    for keyword in ("LinkedIn", "Indeed", "STOP CONDITIONS", "company", "title"):
        assert keyword in content, (
            f"job prompt must contain {keyword!r}; content excerpt: {content[:200]!r}"
        )
    assert ("filter" in content or "Filter" in content), (
        "job prompt must mention filter usage"
    )
    # STATE.md blocker: job search must scope to unauthenticated flows only
    assert (
        "unauthenticated" in content
        or "do not log in" in content.lower()
        or "do not submit credentials" in content.lower()
    ), (
        "job prompt must explicitly restrict to unauthenticated/no-login flows (STATE.md blocker)"
    )
    assert len(content.splitlines()) >= 20, (
        f"job prompt must be at least 20 lines; got {len(content.splitlines())}"
    )


# ---------------------------------------------------------------------------
# ENG-04: Candidate system prompt quality
# ---------------------------------------------------------------------------


def test_candidate_prompt_eng04():
    """ENG-04: SEED_PROMPTS 'candidate' entry must be substantive with credibility signal."""
    from agent.settings import SEED_PROMPTS  # noqa: PLC0415

    entry = next((p for p in SEED_PROMPTS if p["id"] == "candidate"), None)
    assert entry is not None, "SEED_PROMPTS must contain entry with id='candidate'"
    content = entry["content"]
    for keyword in ("STOP CONDITIONS", "profile", "JSON"):
        assert keyword in content, (
            f"candidate prompt must contain {keyword!r}; content excerpt: {content[:200]!r}"
        )
    assert ("credibility" in content or "credible" in content), (
        "candidate prompt must mention credibility signal"
    )
    assert ("source" in content or "Source" in content), (
        "candidate prompt must mention source(s)"
    )
    assert len(content.splitlines()) >= 20, (
        f"candidate prompt must be at least 20 lines; got {len(content.splitlines())}"
    )


# ---------------------------------------------------------------------------
# DB migration: prompt_id column in runs table
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_dir(tmp_path, monkeypatch):
    """Yield a tmp path and chdir so data/history.db writes land there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def test_prompt_id_column_migrated(db_dir):
    """DB migration: init_db() must add prompt_id column to runs table."""
    from agent.db import init_db, DB_PATH  # noqa: PLC0415

    await init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(runs)") as cursor:
            cols = {r[1] async for r in cursor}
    assert "prompt_id" in cols, (
        f"init_db() must migrate runs table to include 'prompt_id' column; got cols={cols}"
    )


async def test_insert_run_accepts_prompt_id(db_dir):
    """DB migration: insert_run() must accept and persist prompt_id kwarg."""
    from agent.db import init_db, insert_run, DB_PATH  # noqa: PLC0415

    await init_db()
    await insert_run(
        run_id="preset-run-001",
        task="find apartments in SF",
        status="complete",
        summary="Found 5 listings",
        started_at="2026-05-19T10:00:00Z",
        completed_at="2026-05-19T10:01:00Z",
        prompt_id="apartment",
    )
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT prompt_id FROM runs WHERE run_id=?", ("preset-run-001",)
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None, "Inserted run must be found in DB"
    assert row[0] == "apartment", (
        f"prompt_id must round-trip as 'apartment'; got {row[0]!r}"
    )


# ---------------------------------------------------------------------------
# PRESET-03 (backend): runner snapshot captures prompt_id
# ---------------------------------------------------------------------------


def test_runner_snapshot_prompt_id():
    """PRESET-03 (backend): runner.py must snapshot active_prompt_id before agent runs."""
    source = Path("agent/runner.py").read_text(encoding="utf-8")
    assert "snapshot_prompt_id" in source, (
        "runner.py must define snapshot_prompt_id local variable"
    )
    assert "snapshot_provider" in source, (
        "runner.py must define snapshot_provider local variable"
    )
    assert "snapshot_model" in source, (
        "runner.py must define snapshot_model local variable"
    )
    assert "active_prompt_id: str | None = None" in source, (
        "run_agent() must accept active_prompt_id: str | None = None parameter"
    )
    assert "_build_extend_system_message(snapshot_prompt_id" in source, (
        "runner.py must pass snapshot_prompt_id (not config.active_prompt_id) to _build_extend_system_message"
    )
    assert "_build_extend_system_message(config.active_prompt_id" not in source, (
        "runner.py must NOT pass config.active_prompt_id to _build_extend_system_message (use snapshot instead)"
    )


# ---------------------------------------------------------------------------
# /run endpoint: accepts active_prompt_id form field
# ---------------------------------------------------------------------------


async def test_run_endpoint_accepts_active_prompt_id(tmp_path, monkeypatch):
    """PRESET-03: /run endpoint must accept active_prompt_id form field and pass it to run_agent."""
    source = Path("agent/main.py").read_text(encoding="utf-8")
    assert "active_prompt_id: str = Form(" in source, (
        "main.py /run endpoint must declare active_prompt_id: str = Form(...) parameter"
    )
    assert "active_prompt_id=active_prompt_id" in source, (
        "main.py must pass active_prompt_id=active_prompt_id to run_agent()"
    )

    # Also exercise via ASGI client — assert status is 200/303/409 (409 = already running)
    settings_file = tmp_path / "settings.json"
    import json
    seed_data = [
        {"id": "apartment", "name": "Apartment Search", "content": "apt", "is_seed": True},
    ]
    settings_file.write_text(json.dumps({"prompts": seed_data, "active_prompt_id": "apartment"}))
    monkeypatch.setattr("agent.settings.get_settings_path", lambda: settings_file)

    from agent.main import app  # noqa: PLC0415

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/run", data={
            "task": "find apartments",
            "active_prompt_id": "apartment",
        })
    assert r.status_code in (200, 303, 409), (
        f"POST /run with active_prompt_id must return 200/303/409, got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# runs_fragment: renders prompt_id
# ---------------------------------------------------------------------------


def test_runs_fragment_renders_prompt_id():
    """runs_fragment.html must render the prompt_id field from the run record."""
    source = Path("agent/templates/runs_fragment.html").read_text(encoding="utf-8")
    assert "{% set _prompt_id = run.get('prompt_id'" in source, (
        "runs_fragment.html must define _prompt_id via run.get('prompt_id'...)"
    )
    assert "{% if _prompt_id %}" in source, (
        "runs_fragment.html must guard prompt_id display with {% if _prompt_id %}"
    )
    assert "System prompt:" in source, (
        "runs_fragment.html must display 'System prompt:' label for prompt_id"
    )
