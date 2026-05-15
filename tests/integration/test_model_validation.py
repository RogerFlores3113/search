"""Integration tests for pre_flight_check in agent/runner.py (MODEL-04 requirements)."""
from __future__ import annotations

import pytest

from agent.config import Settings
from agent.runner import PreFlightError


async def test_preflight_passes_when_ollama_up_and_model_pulled(mock_ollama_tags_ok):
    """pre_flight_check must return normally when Ollama is up and model is available."""
    from agent.runner import pre_flight_check

    # Should NOT raise PreFlightError or any exception
    await pre_flight_check(Settings())


async def test_preflight_exits_with_actionable_msg_when_ollama_down(
    mock_ollama_unreachable, capsys
):
    """pre_flight_check must raise PreFlightError and print 'ollama serve' when daemon is unreachable."""
    from agent.runner import pre_flight_check

    with pytest.raises(PreFlightError):
        await pre_flight_check(Settings())

    captured = capsys.readouterr()
    assert "ollama serve" in captured.out, (
        f"Expected 'ollama serve' in stdout. Got: {captured.out!r}"
    )


async def test_preflight_exits_with_pull_instruction_when_model_missing(
    mock_ollama_model_missing, capsys
):
    """pre_flight_check must raise PreFlightError and print 'ollama pull qwen3-vl:8b' when model absent."""
    from agent.runner import pre_flight_check

    with pytest.raises(PreFlightError):
        await pre_flight_check(Settings())

    captured = capsys.readouterr()
    assert "ollama pull qwen3-vl:8b" in captured.out, (
        f"Expected 'ollama pull qwen3-vl:8b' in stdout. Got: {captured.out!r}"
    )
