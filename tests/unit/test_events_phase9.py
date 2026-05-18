"""Phase 9 RED test suite: frontend polish — header ticker (PERF-03),
collapsible thought (TRANS-01 → UI), action-type badge (UI-01), expandable
run-history rows (UI-02), and screenshot Blob lifecycle.

All tests in this file are RED until Plan 02 (GREEN) lands the production
changes locked by 09-CONTEXT.md decisions D-01..D-24 and the locked design
contract in 09-UI-SPEC.md. Until then, this module:

  - Confirms RED state on the new `/runs` aggregator, `runs_fragment.html`
    `<details>` wrap, header ticker, SSE bridges, action-badge CSS palette,
    summary-marker reset, and screenshot blob handler rewrite.
  - MUST collect cleanly (no ImportError) and fail on assertion only.
  - Touches NO production code under `agent/` — Plan 02 owns those edits.

Phase 9 boundary: tests target template strings, CSS hexes, JS function
names, and `/runs` response payloads that do not yet exist on the current
codebase. The new file MUST collect cleanly and fail on assertion or
attribute lookup — never on collection.

Requirements covered:
  - PERF-03: header token/cost ticker + `/runs` aggregator
  - UI-01: color-coded action-type badge + new SSE bridges
  - UI-02: expandable run-history `<details>` rows
  - (Screenshot Blob lifecycle, D-18..D-21): replace base64 data: URL with
    `URL.createObjectURL` + `revokeObjectURL`

Test-name authority: every `def test_*` here is enumerated in
.planning/phases/09-frontend-polish/09-VALIDATION.md Per-Task Verification Map.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from jinja2 import Environment, FileSystemLoader

import agent.runner  # noqa: F401  (kept for parity with phase-8 preamble)


# ---------------------------------------------------------------------------
# Shared helpers — lifted verbatim shape from tests/unit/test_events_phase8.py
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _make_runs_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _build_runs_record(
    *,
    run_id: str = "r1",
    step_index: int = 0,
    step_duration_ms: int = 500,
    cost_usd: float | None = 0.01,
    provider: str = "anthropic",
    model_name: str = "claude-sonnet-4-5",
) -> dict:
    """Slim Phase-9 record — only the fields the `/runs` aggregator reads."""
    return {
        "run_id": run_id,
        "step_index": step_index,
        "step_duration_ms": step_duration_ms,
        "cost_usd": cost_usd,
        "provider": provider,
        "model_name": model_name,
    }


def _render_runs_fragment(runs: list[dict]) -> str:
    """Render agent/templates/runs_fragment.html directly via Jinja2."""
    env = Environment(loader=FileSystemLoader("agent/templates"), autoescape=True)
    tmpl = env.get_template("runs_fragment.html")
    return tmpl.render(runs=runs)


def _make_run_dict(
    *,
    run_id: str = "r1",
    task: str = "Find a 2BR in Brooklyn",
    status: str = "complete",
    started_at: str = "2026-05-17T00:00:00Z",
    step_count: int = 3,
    total_duration_s: int = 2,
    total_cost_usd: float | None = 0.06,
    model_name: str | None = "claude-sonnet-4-5",
    provider: str | None = "anthropic",
) -> dict:
    """Build a run dict matching the post-aggregator shape (D-17)."""
    return {
        "run_id": run_id,
        "task": task,
        "status": status,
        "started_at": started_at,
        "step_count": step_count,
        "total_duration_s": total_duration_s,
        "total_cost_usd": total_cost_usd,
        "model_name": model_name,
        "provider": provider,
    }


# ===========================================================================
# PERF-03: `/runs` aggregator (server-side D-17)
# ===========================================================================


async def test_runs_aggregates_api_cost(jsonl_with_records, monkeypatch):
    """PERF-03 / D-17: `/runs` payload includes step_count, total_duration_s,
    total_cost_usd, model_name, provider for an API-keyed (anthropic) run.

    RED today: agent/main.py `/runs` endpoint does not aggregate from JSONL yet;
    the rendered fragment will not contain `~$0.06`, `3 steps`, or the model
    name until Plan 02 lands D-13..D-17.
    """
    jsonl_with_records([
        _build_runs_record(run_id="r1", step_index=0, step_duration_ms=500, cost_usd=0.01),
        _build_runs_record(run_id="r1", step_index=1, step_duration_ms=700, cost_usd=0.02),
        _build_runs_record(run_id="r1", step_index=2, step_duration_ms=800, cost_usd=0.03),
    ])

    import agent.main as main_mod

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return [{
            "run_id": "r1",
            "task": "Find a 2BR in Brooklyn",
            "status": "complete",
            "summary": "",
            "started_at": "2026-05-17T00:00:00Z",
            "completed_at": "2026-05-17T00:00:02Z",
        }]

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200, f"/runs must return 200; got {resp.status_code}"
    body = resp.text
    assert "~$0.06" in body, f"/runs payload must include aggregated cost '~$0.06'; got:\n{body}"
    assert "3 steps" in body, f"/runs payload must include '3 steps'; got:\n{body}"
    assert "2s" in body, f"/runs payload must include '2s' (1000+700+800 → 2s); got:\n{body}"
    assert "claude-sonnet-4-5" in body, "/runs payload must include the model name"


async def test_runs_aggregator_ollama_null(jsonl_with_records, monkeypatch):
    """PERF-03 / D-16 / Phase 5/8 null semantics: Ollama-only run renders
    `local (no API cost)` and NEVER `~$0.00`, `None`, `null`, or `NaN`.
    """
    jsonl_with_records([
        _build_runs_record(
            run_id="rO", step_index=0, step_duration_ms=500,
            cost_usd=None, provider="ollama", model_name="qwen2.5vl:7b",
        ),
        _build_runs_record(
            run_id="rO", step_index=1, step_duration_ms=600,
            cost_usd=None, provider="ollama", model_name="qwen2.5vl:7b",
        ),
    ])

    import agent.main as main_mod

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return [{
            "run_id": "rO",
            "task": "ollama task",
            "status": "complete",
            "summary": "",
            "started_at": "2026-05-17T00:00:00Z",
            "completed_at": "2026-05-17T00:00:01Z",
        }]

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    body = resp.text
    assert "local (no API cost)" in body, (
        f"Ollama-only run must render 'local (no API cost)'; got:\n{body}"
    )
    for forbidden in ("~$0.00", "None", "null", "NaN"):
        assert forbidden not in body, (
            f"Ollama payload must not contain {forbidden!r}; got:\n{body}"
        )


async def test_runs_aggregator_offloaded(monkeypatch):
    """PERF-03 / Pitfall 3: aggregator MUST offload the JSONL read via
    `asyncio.to_thread` so the event loop is not blocked. Patches
    `asyncio.to_thread` and asserts it is awaited with the aggregator helper
    (`_aggregate_run_metrics`) as the first positional arg.
    """
    import agent.main as main_mod

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return [{
            "run_id": "rX",
            "task": "t",
            "status": "complete",
            "summary": "",
            "started_at": "2026-05-17T00:00:00Z",
            "completed_at": "2026-05-17T00:00:01Z",
        }]

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    spy = AsyncMock(return_value={})
    # Patch asyncio.to_thread as seen by agent.main (it may be imported as
    # `asyncio.to_thread` or rebound — patch the module attribute).
    monkeypatch.setattr(main_mod.asyncio, "to_thread", spy)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        await client.get("/runs")

    assert spy.await_count >= 1, (
        "/runs aggregator must await asyncio.to_thread at least once (Pitfall 3)"
    )
    first_call_args = spy.await_args_list[0].args
    assert first_call_args, "asyncio.to_thread must be called with positional args"
    first_arg = first_call_args[0]
    name = getattr(first_arg, "__name__", str(first_arg))
    assert name == "_aggregate_run_metrics", (
        f"asyncio.to_thread first positional arg must be _aggregate_run_metrics; got {name!r}"
    )


# ===========================================================================
# PERF-03 / UI-02: runs_fragment.html (D-13..D-16)
# ===========================================================================


def test_runs_fragment_ollama_copy():
    """D-16 / Phase 5/8 null semantics: Jinja fragment renders
    `local (no API cost)` for Ollama runs and NEVER `~$0.00`.
    """
    html = _render_runs_fragment([
        _make_run_dict(provider="ollama", total_cost_usd=None, model_name="qwen2.5vl:7b"),
    ])
    assert "local (no API cost)" in html, (
        f"Ollama fragment must render 'local (no API cost)'; got:\n{html}"
    )
    assert "~$0.00" not in html, f"Fragment must never render '~$0.00'; got:\n{html}"


def test_runs_fragment_api_cost_format():
    """D-15 / D-17: API cost is formatted via `'%.2f'` (0.0567 → ~$0.06)."""
    html = _render_runs_fragment([
        _make_run_dict(provider="anthropic", total_cost_usd=0.0567),
    ])
    assert "~$0.06" in html, (
        f"API cost must be formatted as '~$0.06' (%.2f); got:\n{html}"
    )


def test_runs_fragment_uses_details():
    """D-13: `runs_fragment.html` wraps each `<li>` in `<details><summary>`."""
    src = Path("agent/templates/runs_fragment.html").read_text()
    assert "<details" in src, (
        "runs_fragment.html must wrap each run row in a <details> element (D-13)"
    )
    assert "<summary" in src, (
        "runs_fragment.html must include a <summary> element (D-13)"
    )


def test_runs_fragment_detail_row():
    """D-15: Expanded body uses class `run-history-detail`, the middle-dot `·`
    separator, and the literal `steps` token.
    """
    src = Path("agent/templates/runs_fragment.html").read_text()
    assert "run-history-detail" in src, (
        "runs_fragment.html must contain a `run-history-detail` block (D-15)"
    )
    assert "·" in src, (
        "runs_fragment.html must use middle-dot `·` separator in detail row (D-15)"
    )
    assert "steps" in src, "runs_fragment.html must contain the `steps` literal token (D-15)"


def test_runs_fragment_missing_data():
    """D-16: For missing/null fields render `—` and NEVER `None`/`null`/`undefined`/`NaN`."""
    html = _render_runs_fragment([
        _make_run_dict(
            step_count=0, total_duration_s=0,
            total_cost_usd=None, model_name=None, provider=None,
        ),
    ])
    assert "—" in html, f"Missing data must render an em-dash `—`; got:\n{html}"
    for forbidden in ("None", "null", "undefined", "NaN"):
        assert forbidden not in html, (
            f"Fragment must never render {forbidden!r}; got:\n{html}"
        )
