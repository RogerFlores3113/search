"""Phase 10 RED test suite: UI rendering fixes and dark-green theme refactor.

All tests in this file are RED until Plans 02 and 03 (GREEN) land the
production changes locked by Phase 10 decisions. Until then, this module:

  - Confirms RED state on the 9 requirements: FIX-01, FIX-02, FIX-03,
    FIX-04, THEME-01, THEME-02, THEME-03, THEME-04, THEME-05.
  - MUST collect cleanly (no ImportError) and fail on assertion only.
  - Touches NO production code under `agent/` — Plans 02/03 own those edits.

Phase 10 boundary: tests target CSS declarations, HTML attribute strings,
and JS function bodies that must be present after the refactor but are
absent or incorrect in the current codebase.

Requirements covered:
  - FIX-01 (D-01): .timestamp color must be var(--text-secondary), not
    var(--text-placeholder)
  - FIX-02 (D-03): handleToken must include modelName fallback update
  - FIX-03 (D-05): .narration-row must use align-items: center
  - FIX-04 (D-07): run-history expand/collapse ::before indicators
  - THEME-01 (D-09, D-10): dark green CSS custom properties
  - THEME-02 (D-12): unified blue action-badge palette
  - THEME-03 (D-14..D-16): agent-status spinner div + Alpine wiring
  - THEME-04 (D-17..D-19): thought-area div replaces inline insertion
  - THEME-05 (D-21, D-22): compressed narration feed height and row padding

Test-name authority: every `def test_*` here is enumerated in
.planning/phases/10-ui-rendering-fixes-theme/10-VALIDATION.md Per-Task
Verification Map.
"""
from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# FIX-01 (D-01): timestamp color readability
# ---------------------------------------------------------------------------


def test_timestamp_color_is_visible():
    """FIX-01, D-01: .timestamp color must be var(--text-secondary) for
    readability. Currently var(--text-placeholder) which is too dim.
    """
    css = Path("agent/static/style.css").read_text()
    # Find the .timestamp rule body
    ts_start = css.find(".timestamp {")
    assert ts_start != -1, "style.css must contain a .timestamp { rule"
    ts_body = css[ts_start: css.find("}", ts_start) + 1]
    assert "var(--text-secondary)" in ts_body, (
        "style.css .timestamp { } must use color: var(--text-secondary) (FIX-01 D-01)"
    )
    assert "var(--text-placeholder)" not in ts_body, (
        "style.css .timestamp { } must NOT use var(--text-placeholder) — too dim (FIX-01 D-01)"
    )


# ---------------------------------------------------------------------------
# FIX-02 (D-03): handleToken must include modelName fallback update
# ---------------------------------------------------------------------------


def test_model_info_precedes_token():
    """FIX-02, D-03: handleToken must update this.modelName as a fallback
    when a TokenEvent arrives before a model-info event.
    The assignment must be inside the handleToken function body itself.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "handleToken" in html, (
        "index.html must contain handleToken function (FIX-02 D-03)"
    )
    # Locate handleToken body — from the opening { to its closing },
    # stopping at the first },\n pattern (method separator in Alpine object).
    tok_start = html.find("handleToken(")
    assert tok_start != -1, "index.html must define handleToken( (FIX-02 D-03)"
    brace_open = html.find("{", tok_start)
    assert brace_open != -1, "handleToken must have a body block { (FIX-02 D-03)"
    # Find the closing }, that ends this method (not a nested brace)
    # Walk forward counting depth to find the matching }
    depth = 0
    i = brace_open
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    tok_body = html[brace_open:i + 1]
    assert "modelName" in tok_body, (
        "handleToken body must reference this.modelName for ticker fallback (FIX-02 D-03)"
    )


# ---------------------------------------------------------------------------
# FIX-03 (D-05): narration-row align-items
# ---------------------------------------------------------------------------


def test_narration_row_align_items():
    """FIX-03, D-05: .narration-row must use align-items: center so that
    action badges (which are taller than inline text) are centred vertically.
    Currently uses align-items: baseline which causes misalignment.
    """
    css = Path("agent/static/style.css").read_text()
    row_start = css.find(".narration-row {")
    assert row_start != -1, "style.css must contain .narration-row { rule"
    row_body = css[row_start: css.find("}", row_start) + 1]
    assert "align-items: center" in row_body, (
        "style.css .narration-row must use align-items: center (FIX-03 D-05)"
    )
    assert "align-items: baseline" not in row_body, (
        "style.css .narration-row must NOT use align-items: baseline (FIX-03 D-05)"
    )


# ---------------------------------------------------------------------------
# FIX-04 (D-07): run-history expand/collapse indicator
# ---------------------------------------------------------------------------


def test_run_history_expand_indicator():
    """FIX-04, D-07: Run history rows must have CSS ::before indicators
    (triangle arrows) to signal expandability to users.
    """
    css = Path("agent/static/style.css").read_text()
    assert ".run-history-item > details > summary::before" in css, (
        "style.css must define .run-history-item > details > summary::before (FIX-04 D-07)"
    )
    # Collapsed indicator
    assert "content: '▶'" in css or 'content: "▶"' in css, (
        "style.css summary::before must set content: '\\u25b6' for collapsed state (FIX-04 D-07)"
    )
    # Open indicator
    assert "details[open] > summary::before" in css, (
        "style.css must define details[open] > summary::before rule (FIX-04 D-07)"
    )
    assert "content: '▼'" in css or 'content: "▼"' in css, (
        "style.css details[open] > summary::before must set content: '\\u25bc' (FIX-04 D-07)"
    )


# ---------------------------------------------------------------------------
# THEME-01 (D-09, D-10): dark green CSS custom properties
# ---------------------------------------------------------------------------


def test_dark_green_theme_vars():
    """THEME-01, D-09, D-10: :root must declare dark-green palette values
    for bg-dominant, bg-panel, border, and accent-green.
    Old neutral-dark values must be removed.
    """
    css = Path("agent/static/style.css").read_text()
    # New green values must be present
    assert "--bg-dominant: #091209" in css, (
        "style.css must set --bg-dominant: #091209 (THEME-01 D-09)"
    )
    assert "--bg-panel: #0f1f0f" in css, (
        "style.css must set --bg-panel: #0f1f0f (THEME-01 D-09)"
    )
    assert "--border: #143214" in css, (
        "style.css must set --border: #143214 (THEME-01 D-10)"
    )
    assert "--accent-green: #16a34a" in css, (
        "style.css must declare --accent-green: #16a34a (THEME-01 D-10)"
    )
    # Old neutral values must be gone from :root block
    assert "--bg-dominant: #0f0f0f" not in css, (
        "style.css must NOT contain old --bg-dominant: #0f0f0f (THEME-01 D-09)"
    )
    assert "--bg-panel: #1a1a1a" not in css, (
        "style.css must NOT contain old --bg-panel: #1a1a1a (THEME-01 D-09)"
    )


# ---------------------------------------------------------------------------
# THEME-02 (D-12): unified blue action-badge palette
# ---------------------------------------------------------------------------


def test_action_badge_blue_unified():
    """THEME-02, D-12: All .action-badge-* backgrounds must use the unified
    blue #1d4ed8 (at least 4 occurrences). Old multi-color palette
    (#14532d green, #92400e amber, #374151 slate) must be absent from
    .action-badge-* rules.
    """
    css = Path("agent/static/style.css").read_text()
    assert css.count("#1d4ed8") >= 4, (
        "style.css must contain #1d4ed8 at least 4 times (THEME-02 D-12 — unified blue)"
    )
    # Narrow negative assertions: these legacy hexes must not appear in
    # the .action-badge-* class declarations
    assert ".action-badge-click { background: #14532d" not in css, (
        "style.css must NOT have .action-badge-click with #14532d (THEME-02 D-12)"
    )
    assert ".action-badge-type { background: #92400e" not in css, (
        "style.css must NOT have .action-badge-type with #92400e (THEME-02 D-12)"
    )
    assert ".action-badge-scroll { background: #374151" not in css, (
        "style.css must NOT have .action-badge-scroll with #374151 (THEME-02 D-12)"
    )


# ---------------------------------------------------------------------------
# THEME-03 (D-14..D-16): agent-status spinner div + Alpine wiring
# ---------------------------------------------------------------------------


def test_agent_status_div_present():
    """THEME-03, D-14: index.html must include an .agent-status div with
    Alpine x-show and a .spinner child, plus an agentStatusText() helper.
    """
    html = Path("agent/templates/index.html").read_text()
    assert 'class="agent-status"' in html, (
        "index.html must contain class=\"agent-status\" div (THEME-03 D-14)"
    )
    assert "x-show=\"state === 'running'\"" in html, (
        "index.html agent-status must have x-show=\"state === 'running'\" (THEME-03 D-14)"
    )
    assert 'class="spinner"' in html, (
        "index.html must contain class=\"spinner\" child element (THEME-03 D-14)"
    )
    assert "agentStatusText()" in html, (
        "index.html must call agentStatusText() helper (THEME-03 D-14)"
    )


def test_current_action_prop_declared():
    """THEME-03, D-15: Alpine component must declare currentAction property
    and handleActionDetail must mutate it for the status display.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "currentAction:" in html, (
        "index.html Alpine component must declare currentAction: property (THEME-03 D-15)"
    )
    assert "this.currentAction = d.action_type || 'thinking'" in html, (
        "handleActionDetail must set this.currentAction from payload (THEME-03 D-15)"
    )


def test_spinner_css_declared():
    """THEME-03, D-16: style.css must declare the spin keyframe animation
    and .spinner class with the animation applied.
    """
    css = Path("agent/static/style.css").read_text()
    assert "@keyframes spin" in css, (
        "style.css must declare @keyframes spin (THEME-03 D-16)"
    )
    assert ".spinner {" in css, (
        "style.css must declare .spinner { rule (THEME-03 D-16)"
    )
    assert "animation: spin 1s linear infinite" in css, (
        "style.css .spinner must use animation: spin 1s linear infinite (THEME-03 D-16)"
    )


# ---------------------------------------------------------------------------
# THEME-04 (D-17..D-19): thought-area div + handleThought targeting it
# ---------------------------------------------------------------------------


def test_thought_area_div_present():
    """THEME-04, D-17: index.html must have a dedicated #thought-area /
    .thought-area container. style.css must declare .thought-area { rule.
    """
    html = Path("agent/templates/index.html").read_text()
    assert 'id="thought-area"' in html, (
        "index.html must contain id=\"thought-area\" container (THEME-04 D-17)"
    )
    assert 'class="thought-area"' in html, (
        "index.html must contain class=\"thought-area\" on the container (THEME-04 D-17)"
    )
    css = Path("agent/static/style.css").read_text()
    assert ".thought-area {" in css, (
        "style.css must declare .thought-area { rule (THEME-04 D-17)"
    )


def test_thought_handler_targets_area():
    """THEME-04, D-18: handleThought must target #thought-area via
    document.getElementById('thought-area') instead of appending to a
    narration row.
    """
    html = Path("agent/templates/index.html").read_text()
    assert "document.getElementById('thought-area')" in html, (
        "handleThought must use document.getElementById('thought-area') (THEME-04 D-18)"
    )


def test_thought_area_cleared_on_run():
    """THEME-04, D-19: handleState must clear the #thought-area container
    when a new run starts (state === 'running') so stale thoughts don't
    persist across runs.
    """
    html = Path("agent/templates/index.html").read_text()
    # Locate handleState body
    hs_start = html.find("handleState(")
    assert hs_start != -1, "index.html must define handleState( (THEME-04 D-19)"
    hs_body = html[hs_start: hs_start + 800]
    assert "thought-area" in hs_body, (
        "handleState body must reference thought-area for clear-on-run (THEME-04 D-19)"
    )
    assert "removeChild" in hs_body, (
        "handleState body must use removeChild loop to clear thought-area (THEME-04 D-19)"
    )


# ---------------------------------------------------------------------------
# THEME-05 (D-21, D-22): compressed narration feed and row padding
# ---------------------------------------------------------------------------


def test_narration_feed_compressed():
    """THEME-05, D-21: .narration-feed must use max-height: 200px and
    gap: 3px to give more screen space to the screenshot and thought blocks.
    Old values (max-height: 300px, gap: 6px) must be removed.
    """
    css = Path("agent/static/style.css").read_text()
    feed_start = css.find(".narration-feed {")
    assert feed_start != -1, "style.css must contain .narration-feed { rule"
    feed_body = css[feed_start: css.find("}", feed_start) + 1]
    assert "max-height: 200px" in feed_body, (
        "style.css .narration-feed must set max-height: 200px (THEME-05 D-21)"
    )
    assert "gap: 3px" in feed_body, (
        "style.css .narration-feed must set gap: 3px (THEME-05 D-21)"
    )
    assert "max-height: 300px" not in feed_body, (
        "style.css .narration-feed must NOT have max-height: 300px (THEME-05 D-21)"
    )
    assert "gap: 6px" not in feed_body, (
        "style.css .narration-feed must NOT have gap: 6px (THEME-05 D-21)"
    )


def test_narration_row_padding():
    """THEME-05, D-22: .narration-row padding must be 4px 8px (tighter
    than the old var(--sp-sm) 10px) to compress the feed vertically.
    """
    css = Path("agent/static/style.css").read_text()
    row_start = css.find(".narration-row {")
    assert row_start != -1, "style.css must contain .narration-row { rule"
    row_body = css[row_start: css.find("}", row_start) + 1]
    assert "padding: 4px 8px" in row_body, (
        "style.css .narration-row must set padding: 4px 8px (THEME-05 D-22)"
    )
    assert "padding: var(--sp-sm) 10px" not in row_body, (
        "style.css .narration-row must NOT use padding: var(--sp-sm) 10px (THEME-05 D-22)"
    )
