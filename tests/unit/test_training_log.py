"""Unit tests for the training JSONL sink in agent/training_sink.py (RUN-03 schema contract).

The sink consumes the library's StepCompletedEvent and writes one record per step to
training/runs.jsonl (it replaced the old `log_step` on_step_end callback, which read the
browser-use Agent directly; the event is built by BrowserAgent, see tests/lib).
"""
from __future__ import annotations

import json

import pytest

from agent.training_sink import TrainingSink
from local_browser_agent.events import StepCompletedEvent


def _event(**kw) -> StepCompletedEvent:
    base = dict(run_id="test-run-id", step=1, screenshot_b64="iVBORw0KGgo=", action_type="click",
                target="#btn", value="", duration_ms=0)
    base.update(kw)
    return StepCompletedEvent(**base)


async def _log(event, provider="ollama", model_name="m"):
    await TrainingSink(provider, model_name)(event)


async def test_log_step_writes_jsonl_line(training_dir):
    """The sink must write exactly one JSONL record with all nine D-09 schema fields."""
    await _log(_event())

    jsonl_file = training_dir / "runs.jsonl"
    assert jsonl_file.exists(), "training/runs.jsonl must be created by the sink"

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
    assert record["step_index"] == 0 and record["action_target"] == "#btn"
    assert record["narration"] == "Step 1: click" and record["step_success"] is True


async def test_log_step_creates_training_dir(training_dir):
    """The sink must create the training/ directory if it does not exist."""
    import shutil

    shutil.rmtree(training_dir)
    assert not training_dir.exists()

    await _log(_event())

    assert training_dir.exists(), "sink must create training/ dir if missing"
    assert (training_dir / "runs.jsonl").exists()


async def test_log_step_appends_not_overwrites(training_dir):
    """Two steps must produce exactly 2 JSONL lines (append, not overwrite)."""
    await _log(_event())
    await _log(_event(step=2))

    lines = (training_dir / "runs.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"


async def test_sink_ignores_other_events(training_dir):
    from local_browser_agent.events import ProgressEvent, ScreenshotEvent

    await TrainingSink("ollama", "m")(ProgressEvent(step=1))
    await TrainingSink("ollama", "m")(ScreenshotEvent(b64="x"))
    assert not (training_dir / "runs.jsonl").exists()


def test_sink_opts_in_to_step_events_only():
    sink = TrainingSink("ollama", "m")
    assert sink.wants_step_events is True and sink.wants_screenshots is False


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
    """The sink must write the event's element label as `action_target_label`."""
    await _log(_event(target="12", target_label="Search button"), provider="ollama")

    record = json.loads((training_dir / "runs.jsonl").read_text().strip())
    assert record["action_target_label"] == "Search button"


async def test_log_step_action_target_label_null_when_no_element(training_dir):
    """When there is no label the field is explicit None, not omitted — keeps the
    JSONL schema stable for the LoRA converter.
    """
    await _log(_event())

    record = json.loads((training_dir / "runs.jsonl").read_text().strip())
    assert "action_target_label" in record
    assert record["action_target_label"] is None
