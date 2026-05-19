from __future__ import annotations

import aiosqlite

from agent.paths import get_user_data_dir

DB_PATH = get_user_data_dir() / "history.db"

# Columns added after the initial schema. `init_db` runs ADD COLUMN for each
# missing entry so existing databases pick them up without a rewrite. Order
# does not matter — SQLite ALTER TABLE appends.
_AGGREGATE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("step_count",       "INTEGER NOT NULL DEFAULT 0"),
    ("total_duration_s", "INTEGER NOT NULL DEFAULT 0"),
    ("total_cost_usd",   "REAL"),
    ("model_name",       "TEXT"),
    ("provider",         "TEXT"),
    ("prompt_id",        "TEXT"),
)


async def init_db() -> None:
    """Create the runs table (if missing) and migrate it to the current schema.

    Called from FastAPI lifespan at startup so the table is always present.
    Ensures DB_PATH.parent exists. Idempotent: CREATE IF NOT EXISTS for fresh
    installs; ALTER TABLE ADD COLUMN for any aggregate columns missing on an
    existing table. SQLite ADD COLUMN is O(1) — no row rewrite.
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
        async with db.execute("PRAGMA table_info(runs)") as cursor:
            existing = {row[1] async for row in cursor}
        for col_name, col_decl in _AGGREGATE_COLUMNS:
            if col_name not in existing:
                await db.execute(f"ALTER TABLE runs ADD COLUMN {col_name} {col_decl}")
        await db.commit()


async def insert_run(
    *,
    run_id: str,
    task: str,
    status: str,
    summary: str | None,
    started_at: str,
    completed_at: str,
    step_count: int = 0,
    total_duration_s: int = 0,
    total_cost_usd: float | None = None,
    model_name: str | None = None,
    provider: str | None = None,
    prompt_id: str | None = None,
) -> None:
    """Insert a completed run record into the runs table.

    Uses parameterized queries with ? placeholders — never f-string or .format SQL
    to mitigate STRIDE Tampering threat T-03-01 (SQL injection via task string).

    The aggregate fields (step_count..provider) are the UI's read model: computed
    once when the run finishes, written here, served straight to `/runs`. Keep
    them in sync with `agent/runner.py` accumulation.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO runs (run_id, task, status, summary, started_at, completed_at, "
            "step_count, total_duration_s, total_cost_usd, model_name, provider, prompt_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, task, status, summary, started_at, completed_at,
                step_count, total_duration_s, total_cost_usd, model_name, provider, prompt_id,
            ),
        )
        await db.commit()


async def list_runs(limit: int = 10) -> list[dict]:
    """Return the most recent `limit` run records ordered by started_at DESC.

    Returns every column on the row (including aggregates) so the `/runs`
    endpoint can pass the dict straight to the Jinja template without further
    enrichment.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT run_id, task, status, summary, started_at, completed_at, "
            "step_count, total_duration_s, total_cost_usd, model_name, provider, prompt_id "
            "FROM runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            return [dict(row) async for row in cursor]
