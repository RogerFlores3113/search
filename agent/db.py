from __future__ import annotations

import aiosqlite

from agent.paths import get_user_data_dir

DB_PATH = get_user_data_dir() / "history.db"


async def init_db() -> None:
    """Create the runs table if it does not exist.

    Called from FastAPI lifespan at startup so the table is always present.
    Ensures DB_PATH.parent exists — necessary because DB_PATH is computed at module
    import time using get_user_data_dir(), which mkdir's the data dir at that point.
    If tests chdir after import, the relative 'data/' may not exist in the new cwd.
    Re-calling mkdir here is idempotent and safe.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        await db.commit()


async def insert_run(
    run_id: str,
    task: str,
    status: str,
    summary: str | None,
    started_at: str,
    completed_at: str,
) -> None:
    """Insert a completed run record into the runs table.

    Uses parameterized queries with ? placeholders — never f-string or .format SQL
    to mitigate STRIDE Tampering threat T-03-01 (SQL injection via task string).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO runs (run_id, task, status, summary, started_at, completed_at) "
            "VALUES (?,?,?,?,?,?)",
            (run_id, task, status, summary, started_at, completed_at),
        )
        await db.commit()


async def list_runs(limit: int = 10) -> list[dict]:
    """Return the most recent `limit` run records ordered by started_at DESC.

    Uses aiosqlite.Row as row_factory so rows can be converted to dict with dict(row).
    Uses parameterized ? placeholder for the LIMIT value.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT run_id, task, status, summary, started_at, completed_at "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            return [dict(row) async for row in cursor]
