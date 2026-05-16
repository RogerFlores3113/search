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
    expected_cols = {"id", "run_id", "task", "status", "summary", "started_at", "completed_at"}
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
