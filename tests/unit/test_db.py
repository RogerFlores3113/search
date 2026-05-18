"""Unit tests for agent/db.py — init_db, insert_run, list_runs (RUN-01, RUN-02, T-03-01).

Tests use a tmp_path fixture so data/history.db writes land in an isolated directory.
All tests are async def without @pytest.mark.asyncio because asyncio_mode = "auto".
"""
from __future__ import annotations

import pytest


@pytest.fixture
async def db_dir(tmp_path, monkeypatch):
    """Yield a tmp path and chdir so data/history.db writes land there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def test_init_db_creates_runs_table(db_dir):
    """init_db must create the runs table with the required columns."""
    import aiosqlite
    from agent.db import init_db, DB_PATH

    await init_db()
    assert DB_PATH.exists(), "DB file should exist after init_db()"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None, "runs table should exist after init_db()"

    # Verify all required columns are present
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(runs)") as cursor:
            cols = {r[1] async for r in cursor}
    expected_cols = {
        "id", "run_id", "task", "status", "summary", "started_at", "completed_at",
        "step_count", "total_duration_s", "total_cost_usd", "model_name", "provider",
    }
    assert expected_cols.issubset(cols), f"Missing columns: {expected_cols - cols}"


async def test_insert_and_list_runs_roundtrip(db_dir):
    """insert_run then list_runs must return the row with matching data."""
    from agent.db import init_db, insert_run, list_runs

    await init_db()
    await insert_run(
        run_id="test-run-001",
        task="go to wikipedia.org",
        status="complete",
        summary="Found Wikipedia main page",
        started_at="2026-01-01T10:00:00+00:00",
        completed_at="2026-01-01T10:01:00+00:00",
    )

    rows = await list_runs()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "test-run-001"
    assert rows[0]["task"] == "go to wikipedia.org"
    assert rows[0]["status"] == "complete"
    assert rows[0]["summary"] == "Found Wikipedia main page"

    # Insert a second row; list_runs returns newest first (started_at DESC)
    await insert_run(
        run_id="test-run-002",
        task="search for news",
        status="error",
        summary=None,
        started_at="2026-01-01T11:00:00+00:00",
        completed_at="2026-01-01T11:00:30+00:00",
    )
    rows = await list_runs()
    assert len(rows) == 2
    assert rows[0]["run_id"] == "test-run-002", "Newest run should be first (DESC order)"
    assert rows[1]["run_id"] == "test-run-001"


async def test_list_runs_respects_limit(db_dir):
    """list_runs(limit=10) must return at most 10 rows when 12 exist."""
    from agent.db import init_db, insert_run, list_runs

    await init_db()
    for i in range(12):
        await insert_run(
            run_id=f"run-{i:03d}",
            task=f"task {i}",
            status="complete",
            summary=None,
            started_at=f"2026-01-{i + 1:02d}T10:00:00+00:00",
            completed_at=f"2026-01-{i + 1:02d}T10:01:00+00:00",
        )

    rows = await list_runs(limit=10)
    assert len(rows) == 10, f"Expected 10 rows, got {len(rows)}"


async def test_insert_run_uses_parameterized_query(db_dir):
    """Inserting a task with SQL injection attempt must NOT drop the table.

    Verifies that parameterized ? placeholders are used (T-03-01 mitigation).
    """
    from agent.db import init_db, insert_run, list_runs

    await init_db()

    # This is a classic SQL injection attempt
    malicious_task = "'); DROP TABLE runs; --"
    await insert_run(
        run_id="attack-run",
        task=malicious_task,
        status="complete",
        summary=None,
        started_at="2026-01-01T10:00:00+00:00",
        completed_at="2026-01-01T10:00:01+00:00",
    )

    # The runs table must still exist and contain the row
    rows = await list_runs()
    assert len(rows) == 1, "runs table should still exist after injection attempt"
    assert rows[0]["task"] == malicious_task, "Injected task string should be stored literally"


async def test_aggregates_roundtrip(db_dir):
    """step_count, total_duration_s, total_cost_usd, model_name, provider
    round-trip through insert_run / list_runs unchanged.
    """
    from agent.db import init_db, insert_run, list_runs

    await init_db()
    await insert_run(
        run_id="api-run",
        task="search wiki",
        status="complete",
        summary=None,
        started_at="2026-05-17T10:00:00Z",
        completed_at="2026-05-17T10:00:05Z",
        step_count=4,
        total_duration_s=5,
        total_cost_usd=0.0234,
        model_name="claude-sonnet-4-5",
        provider="anthropic",
    )
    await insert_run(
        run_id="ollama-run",
        task="local search",
        status="complete",
        summary=None,
        started_at="2026-05-17T11:00:00Z",
        completed_at="2026-05-17T11:00:03Z",
        step_count=2,
        total_duration_s=3,
        total_cost_usd=None,
        model_name="qwen2.5vl:7b",
        provider="ollama",
    )

    rows = await list_runs()
    by_id = {r["run_id"]: r for r in rows}

    api = by_id["api-run"]
    assert api["step_count"] == 4
    assert api["total_duration_s"] == 5
    assert api["total_cost_usd"] == 0.0234
    assert api["model_name"] == "claude-sonnet-4-5"
    assert api["provider"] == "anthropic"

    ollama = by_id["ollama-run"]
    assert ollama["step_count"] == 2
    assert ollama["total_cost_usd"] is None, "Ollama null cost must round-trip as None, not 0"
    assert ollama["provider"] == "ollama"


async def test_insert_run_defaults_when_aggregates_omitted(db_dir):
    """Existing callers that don't pass the aggregate kwargs (e.g. tests
    pre-dating the schema migration) still work; aggregates default to 0/None.
    """
    from agent.db import init_db, insert_run, list_runs

    await init_db()
    await insert_run(
        run_id="legacy",
        task="t",
        status="complete",
        summary=None,
        started_at="2026-05-17T12:00:00Z",
        completed_at="2026-05-17T12:00:01Z",
    )
    rows = await list_runs()
    assert rows[0]["step_count"] == 0
    assert rows[0]["total_duration_s"] == 0
    assert rows[0]["total_cost_usd"] is None
    assert rows[0]["model_name"] is None
    assert rows[0]["provider"] is None


async def test_init_db_migrates_existing_table(db_dir):
    """A pre-existing runs table without the aggregate columns is migrated
    in place via ALTER TABLE ADD COLUMN. Idempotent on a second init_db call.
    """
    import aiosqlite
    from agent.db import DB_PATH, init_db

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        await db.execute(
            "INSERT INTO runs (run_id, task, status, summary, started_at, completed_at) "
            "VALUES (?,?,?,?,?,?)",
            ("pre-existing", "t", "complete", None,
             "2026-05-17T09:00:00Z", "2026-05-17T09:00:01Z"),
        )
        await db.commit()

    await init_db()
    await init_db()  # second call must be a no-op (idempotent)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("PRAGMA table_info(runs)") as cursor:
            cols = {r[1] async for r in cursor}
        async with db.execute("SELECT run_id, step_count, total_cost_usd FROM runs") as cursor:
            row = await cursor.fetchone()

    for needed in ("step_count", "total_duration_s", "total_cost_usd", "model_name", "provider"):
        assert needed in cols, f"Migration must add {needed!r}; cols={cols}"
    assert row[0] == "pre-existing"
    assert row[1] == 0, "Pre-existing row must default step_count to 0"
    assert row[2] is None, "Pre-existing row must default total_cost_usd to NULL"
