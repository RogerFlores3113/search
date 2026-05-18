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

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from jinja2 import Environment, FileSystemLoader


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
# PERF-03: `/runs` payload (aggregates served from SQLite, no JSONL touch)
# ===========================================================================


async def test_runs_endpoint_renders_api_aggregates(monkeypatch):
    """PERF-03: /runs payload includes step_count, total_duration_s,
    total_cost_usd, model_name for an API-keyed run — sourced from the
    SQLite row, not from re-scanning training/runs.jsonl.
    """
    import agent.main as main_mod

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return [{
            "run_id": "r1",
            "task": "Find a 2BR in Brooklyn",
            "status": "complete",
            "summary": "",
            "started_at": "2026-05-17T00:00:00Z",
            "completed_at": "2026-05-17T00:00:02Z",
            "step_count": 3,
            "total_duration_s": 2,
            "total_cost_usd": 0.06,
            "model_name": "claude-sonnet-4-5",
            "provider": "anthropic",
        }]

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    body = resp.text
    assert "~$0.06" in body
    assert "3 steps" in body
    assert "2s" in body
    assert "claude-sonnet-4-5" in body


async def test_runs_endpoint_renders_ollama_null_cost(monkeypatch):
    """PERF-03 / Phase 5/8 null semantics: an Ollama row with
    total_cost_usd=NULL must render `local (no API cost)` and never
    coerce to `~$0.00`, `None`, `null`, or `NaN`.
    """
    import agent.main as main_mod

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return [{
            "run_id": "rO",
            "task": "ollama task",
            "status": "complete",
            "summary": "",
            "started_at": "2026-05-17T00:00:00Z",
            "completed_at": "2026-05-17T00:00:01Z",
            "step_count": 2,
            "total_duration_s": 1,
            "total_cost_usd": None,
            "model_name": "qwen2.5vl:7b",
            "provider": "ollama",
        }]

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    body = resp.text
    assert "local (no API cost)" in body
    for forbidden in ("~$0.00", "None", "null", "NaN"):
        assert forbidden not in body, f"forbidden token {forbidden!r} in body:\n{body}"


async def test_runs_endpoint_does_not_read_training_jsonl(monkeypatch, tmp_path):
    """/runs must NOT touch training/runs.jsonl — the LoRA corpus is
    write-only from the web layer. Point TRAINING_FILE at a missing path
    and confirm the endpoint still serves a 200.
    """
    import agent.main as main_mod
    import agent.runner as runner_mod

    monkeypatch.setattr(runner_mod, "TRAINING_FILE", tmp_path / "does-not-exist.jsonl")

    async def _fake_list_runs(limit: int = 10) -> list[dict]:
        return []

    monkeypatch.setattr(main_mod.history_db, "list_runs", _fake_list_runs)

    async with AsyncClient(
        transport=ASGITransport(app=main_mod.app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    assert not (tmp_path / "does-not-exist.jsonl").exists(), (
        "/runs must not create or read the JSONL"
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


# ===========================================================================
# PERF-03 / UI-01: index.html header ticker + new SSE bridges (D-01..D-04, D-22)
# ===========================================================================


def test_index_has_header_ticker():
    """D-01 / D-04: `<span class="header-ticker">` with `aria-live="polite"`
    is present inside `agent/templates/index.html`.
    """
    html = Path("agent/templates/index.html").read_text()
    assert 'class="header-ticker"' in html, (
        "index.html must include a `<span class=\"header-ticker\">` (D-01)"
    )
    assert 'aria-live="polite"' in html, (
        "index.html must include `aria-live=\"polite\"` on the ticker (D-04)"
    )


def test_index_has_token_handlers():
    """D-22: Alpine `agentUI()` declares `handleToken` and `handleModelInfo`
    methods for the new SSE bridges.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "handleToken" in html, (
        "index.html must declare a `handleToken` method on agentUI() (D-22)"
    )
    assert "handleModelInfo" in html, (
        "index.html must declare a `handleModelInfo` method on agentUI() (D-22)"
    )


def test_action_badge_assets_present():
    """D-22 / D-11: Alpine `agentUI()` declares `handleActionDetail` and
    `handleThought`; narration rows carry `data-step` for badge-race lookup.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "handleActionDetail" in html, (
        "index.html must declare `handleActionDetail` (D-22)"
    )
    assert "handleThought" in html, (
        "index.html must declare `handleThought` (D-22)"
    )
    assert "data-step" in html, (
        "narration rows must carry `data-step` for badge race injection (D-11)"
    )


def test_new_sse_bridges_inside_container():
    """D-22 + Phase 3 D-11: four new `sse-swap` bridges (`token`, `model_info`,
    `thought`, `action_detail`) are descendants of `#sse-container`.
    """
    html = Path("agent/templates/index.html").read_text()

    # Locate the #sse-container opening tag. Phase 3 D-11 locks bridge
    # placement: `htmx-ext-sse` only delivers to descendants.
    container_match = re.search(r'id\s*=\s*"sse-container"', html)
    assert container_match is not None, (
        "index.html must contain an `id=\"sse-container\"` element (Phase 3 D-11)"
    )
    container_start = container_match.start()

    required_bridges = ("token", "model_info", "thought", "action_detail")
    for ev in required_bridges:
        pattern = f'sse-swap="{ev}"'
        idx = html.find(pattern, container_start)
        assert idx != -1, (
            f"sse-swap=\"{ev}\" bridge missing or not after `#sse-container` (D-22)"
        )


# ===========================================================================
# Phase 6 success criterion: richer action labels — action_type + target/value
# (Issue #3 — ActionDetailEvent carries the data but UI rendered badge only)
# ===========================================================================


def test_handle_action_detail_renders_description():
    """handleActionDetail must compose a description from the event payload
    (target / value / url) and append a `.narration-text` span — without this
    the user sees only the badge + step number with no signal as to WHAT
    was clicked, navigated to, or typed.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "_buildActionDescription" in html, (
        "index.html must declare a _buildActionDescription helper"
    )
    assert "narration-text" in html, (
        "handleActionDetail must append a .narration-text span to the row"
    )


def test_action_description_covers_each_action_type():
    """Each action_type maps to a description that surfaces the payload
    field carrying the user signal: navigate→url, click→target/label,
    type→value, scroll→value.
    """
    html = Path("agent/templates/index.html").read_text()
    for needed in (
        "Navigating to ",
        "Clicking ",
        "Typing",
        "Scrolling",
        "Extracting page content",
        "Finished",
    ):
        assert needed in html, (
            f"_buildActionDescription must produce {needed!r} for the corresponding action_type"
        )


def test_action_description_prefers_target_label_over_index():
    """The label ('Search button') carries transferable signal; the bare
    DOM index ('#12') is page-specific noise. _buildActionDescription must
    prefer target_label when present and fall back to `element #N` only
    when no label was sent.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "d.target_label" in html, (
        "_buildActionDescription must read d.target_label from the event"
    )
    assert "element #" in html, (
        "_buildActionDescription must keep the `element #N` fallback when "
        "target_label is unavailable"
    )


# ===========================================================================
# UI-01 / UI-02: action-badge palette + summary marker reset (D-12, D-14)
# ===========================================================================


def test_action_badge_palette_hex():
    """D-12: `.action-badge-*` CSS rules reuse the four locked palette hex
    values (no new hues): navigate=#1d4ed8, click=#14532d, type=#92400e,
    scroll=#374151. The `action-badge-` class prefix must also be present.
    """
    css = Path("agent/static/style.css").read_text()
    for hex_val in ("#1d4ed8", "#14532d", "#92400e", "#374151"):
        assert hex_val in css, (
            f"style.css must contain locked palette hex {hex_val} (D-12)"
        )
    assert "action-badge-" in css, (
        "style.css must define `.action-badge-*` classes (D-12)"
    )


def test_summary_marker_reset_present():
    """D-14 / Pitfall 1: CSS must reset the disclosure triangle so the existing
    flex layout for run-history rows survives the `<details>` wrap. Requires
    BOTH `list-style: none` AND `::-webkit-details-marker` + `display: none`.
    """
    css = Path("agent/static/style.css").read_text()
    assert "list-style: none" in css, (
        "style.css must include `list-style: none` for summary reset (D-14)"
    )
    assert "::-webkit-details-marker" in css, (
        "style.css must include `::-webkit-details-marker` reset (D-14)"
    )
    assert "display: none" in css, (
        "style.css must include `display: none` for marker reset (D-14)"
    )


# ===========================================================================
# Screenshot Blob lifecycle (D-18..D-21)
# ===========================================================================


def test_no_data_url_in_index():
    """D-19: the old `data:image/png;base64,` assignment must be DELETED from
    index.html as part of the Blob lifecycle rewrite.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "data:image/png;base64," not in html, (
        "index.html must NOT contain `data:image/png;base64,` after D-19 rewrite"
    )


def test_handle_screenshot_blob_lifecycle():
    """D-18..D-21: rewritten `handleScreenshot` constructs a Blob, uses
    `URL.createObjectURL` + `URL.revokeObjectURL`, and the MIME is `image/jpeg`
    (Phase 7 emits JPEG q=75, not PNG — D-21 fixes the prior misassumption).
    """
    html = Path("agent/templates/index.html").read_text()
    for needle in (
        "URL.createObjectURL",
        "URL.revokeObjectURL",
        "image/jpeg",
        "new Blob(",
        "atob(",
    ):
        assert needle in html, (
            f"index.html `handleScreenshot` must use {needle!r} (D-18..D-21)"
        )
