"""Unit tests for log_step in agent/runner.py (RUN-03 JSONL schema contract).

All tests are xfail-by-design until Wave 1 (plan 02) implements log_step.
The nine field names here are the Nyquist contract — Wave 1 MUST satisfy them.
"""
from __future__ import annotations

import json
import types

import pytest


def _make_fake_agent():
    """Build a minimal fake Agent namespace with the attributes log_step reads."""
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{"action_type": "click", "action_target": "#btn", "action_value": ""}],
        screenshots=lambda: ["iVBORw0KGgo="],  # minimal base64 stub
        has_errors=lambda: False,
    )
    # state.last_result is required by the CAPTCHA detection branch in log_step
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(history=history, state=state)


async def test_log_step_writes_jsonl_line(training_dir):
    """log_step must write exactly one JSONL record with all nine D-09 schema fields."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    jsonl_file = training_dir / "runs.jsonl"
    assert jsonl_file.exists(), "training/runs.jsonl must be created by log_step"

    lines = jsonl_file.read_text().strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    for field in (
        "timestamp",
        "run_id",
        "step_index",
        "screenshot_b64",
        "action_type",
        "action_target",
        "action_value",
        "narration",
        "step_success",
    ):
        assert field in record, f"Missing field: {field}"


async def test_log_step_creates_training_dir(training_dir):
    """log_step must create the training/ directory if it does not exist."""
    import shutil

    from agent.runner import log_step

    shutil.rmtree(training_dir)
    assert not training_dir.exists()

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    assert training_dir.exists(), "log_step must create training/ dir if missing"
    assert (training_dir / "runs.jsonl").exists()


async def test_log_step_appends_not_overwrites(training_dir):
    """Calling log_step twice must produce exactly 2 JSONL lines (append, not overwrite)."""
    from agent.runner import log_step

    fake_agent = _make_fake_agent()
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)
    await log_step(fake_agent, run_id="test-run-id", provider="ollama", duration_ms=0)

    jsonl_file = training_dir / "runs.jsonl"
    lines = jsonl_file.read_text().strip().splitlines()
    assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"


# ---------------------------------------------------------------------------
# action_target_label — enriches LoRA training data with the browser's
# accessibility name for the interacted element (Issue #3 / option B)
# ---------------------------------------------------------------------------

class _FakeInteractedElement:
    """Stand-in for browser_use.dom.views.DOMInteractedElement — duck-typed
    so the extractor does not need to import browser-use to be tested.
    """
    def __init__(self, *, ax_name=None, node_name=None, attributes=None, node_value=None):
        self.ax_name = ax_name
        self.node_name = node_name
        self.attributes = attributes
        self.node_value = node_value


def test_extract_target_label_prefers_ax_name():
    from agent.runner import _extract_target_label
    el = _FakeInteractedElement(
        ax_name="Search button",
        node_name="BUTTON",
        attributes={"aria-label": "ignored when ax_name present", "title": "also ignored"},
    )
    assert _extract_target_label(el) == "Search button"


def test_extract_target_label_falls_back_through_attributes():
    from agent.runner import _extract_target_label
    # aria-label wins when ax_name is missing
    assert _extract_target_label(_FakeInteractedElement(
        attributes={"aria-label": "Close dialog", "title": "Close"},
    )) == "Close dialog"
    # title wins when aria-label is missing
    assert _extract_target_label(_FakeInteractedElement(
        attributes={"title": "Profile menu"},
    )) == "Profile menu"
    # placeholder wins for empty inputs with no other label
    assert _extract_target_label(_FakeInteractedElement(
        node_name="INPUT",
        attributes={"placeholder": "Email address"},
    )) == "Email address"


def test_extract_target_label_tag_fallback_for_interactive_elements():
    from agent.runner import _extract_target_label
    el = _FakeInteractedElement(node_name="BUTTON", attributes={})
    assert _extract_target_label(el) == "<button>"


def test_extract_target_label_returns_none_for_unlabeled_div():
    """Non-interactive elements with no label provide no useful signal — None
    is honest (caller falls back to bare index).
    """
    from agent.runner import _extract_target_label
    el = _FakeInteractedElement(node_name="DIV", attributes={})
    assert _extract_target_label(el) is None


def test_extract_target_label_handles_none_and_empty():
    from agent.runner import _extract_target_label
    assert _extract_target_label(None) is None
    assert _extract_target_label(_FakeInteractedElement()) is None


def test_extract_target_label_truncates_long_labels():
    """Long ARIA descriptions get clipped to keep narration rows + LoRA
    lines readable. Truncation marker is the ellipsis character.
    """
    from agent.runner import _extract_target_label
    label = "A very long accessibility description " * 5  # ~190 chars
    out = _extract_target_label(_FakeInteractedElement(ax_name=label))
    assert out is not None
    assert len(out) <= 80
    assert out.endswith("…")


def test_extract_target_label_accepts_dict_shape():
    """Tests and other fixtures may pass a dict instead of the dataclass."""
    from agent.runner import _extract_target_label
    assert _extract_target_label({"ax_name": "Submit"}) == "Submit"


async def test_log_step_records_action_target_label(training_dir):
    """log_step must extract the element label from interacted_element and
    write it as `action_target_label` in the JSONL record.
    """
    import json
    import types
    from agent.runner import log_step

    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: [{
            "click": {"index": 12},
            "interacted_element": _FakeInteractedElement(ax_name="Search button"),
        }],
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    state = types.SimpleNamespace(last_result=[])
    fake_agent = types.SimpleNamespace(history=history, state=state)

    await log_step(fake_agent, run_id="r1", provider="ollama", duration_ms=0)

    record = json.loads((training_dir / "runs.jsonl").read_text().strip())
    assert record["action_target_label"] == "Search button"


async def test_log_step_action_target_label_null_when_no_element(training_dir):
    """When interacted_element is missing the field is explicit None, not
    omitted — keeps the JSONL schema stable for the LoRA converter.
    """
    import json
    from agent.runner import log_step

    await log_step(_make_fake_agent(), run_id="r1", provider="ollama", duration_ms=0)

    record = json.loads((training_dir / "runs.jsonl").read_text().strip())
    assert "action_target_label" in record
    assert record["action_target_label"] is None
