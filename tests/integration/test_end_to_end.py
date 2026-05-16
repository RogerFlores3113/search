"""End-to-end integration tests for the local-browser-agent Walking Skeleton.

These tests boot the real FastAPI app in-process via TestClient (which fires the
FastAPI lifespan in an anyio portal) and use unittest.mock to patch out
browser_use.Agent, browser_use.ChatOllama, and BrowserSession at their import
sites inside agent.runner — so no live Chrome or Ollama is needed.

What is proven here:
  - The asyncio plumbing: lifespan startup → create_task → on_step_end callback
    → JSONL write → browser.kill → lifespan shutdown.
  - The /run endpoint wires a new task from an HTTP POST.

This is the targeted answer to ROADMAP critical pitfall #3 (sync browser code
inside FastAPI's asyncio event loop): the structural correctness of the loop
is proven without requiring a browser.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — shared fake objects
# ---------------------------------------------------------------------------

def _make_fake_history(num_steps: int = 2) -> MagicMock:
    """Minimal AgentHistoryList stand-in that log_step can read."""
    history = MagicMock()
    # Track call count for number_of_steps so successive calls return 1, 2, ...
    # We return a fixed count equal to num_steps for simplicity; log_step only
    # reads the *current* step index on each on_step_end invocation.
    history.number_of_steps.return_value = num_steps
    history.model_actions.return_value = [
        {
            "action_type": "navigate",
            "action_target": "https://example.com",
            "action_value": "",
        }
    ]
    history.screenshots.return_value = ["base64fakedata"]
    history.has_errors.return_value = False
    history.final_result.return_value = "done"
    return history


def _make_fake_agent(history: MagicMock) -> SimpleNamespace:
    """Minimal Agent stand-in that on_step_end (log_step) can introspect."""
    # state.last_result must be present for the CAPTCHA detection branch in log_step
    state = SimpleNamespace(last_result=[])
    return SimpleNamespace(history=history, state=state, pause=MagicMock())


def _make_browser_session_class() -> tuple[type, MagicMock]:
    """Return (MockBrowserSession class, instance mock) that log_step can track."""
    instance = MagicMock()
    instance.kill = AsyncMock()

    class MockBrowserSession:
        def __init__(self, **kwargs):
            self._kwargs = kwargs
            # Copy attributes to instance so assertions can read them
            instance._init_kwargs = kwargs

        async def kill(self):
            await instance.kill()

    # Make it a MagicMock so we can assert call arguments
    cls = MagicMock(return_value=instance)
    return cls, instance


def _make_agent_class(history: MagicMock, fake_agent: SimpleNamespace) -> MagicMock:
    """Return a MockAgent class whose .run() calls on_step_end twice then returns history.

    The mock invokes on_step_end with fake_agent to exercise the real log_step
    code path, producing JSONL output in training/runs.jsonl.
    """
    async def fake_run(max_steps, on_step_end=None):
        if on_step_end is not None:
            await on_step_end(fake_agent)
            await on_step_end(fake_agent)
        return history

    agent_instance = MagicMock()
    agent_instance.run = fake_run

    MockAgent = MagicMock(return_value=agent_instance)
    return MockAgent, agent_instance


# ---------------------------------------------------------------------------
# Scenario A — lifespan sets pending_task; full plumbing exercised end-to-end
# ---------------------------------------------------------------------------

def test_lifespan_runs_full_agent_loop_with_mocks(monkeypatch, tmp_path):
    """Boot FastAPI via TestClient; lifespan fires run_agent from pending_task.

    Proves: lifespan startup → asyncio.create_task(run_agent) → pre_flight_check
    → BrowserSession(channel=chrome) → ChatOllama(num_ctx=32000) →
    Agent.run(on_step_end=log_step) → on_step_end invoked twice → JSONL written
    → browser.kill() in finally.
    """
    from starlette.testclient import TestClient

    from agent.config import config
    from agent.main import app

    # Redirect file writes so runs.jsonl lands in tmp_path instead of cwd.
    monkeypatch.chdir(tmp_path)

    history = _make_fake_history(num_steps=2)
    fake_agent = _make_fake_agent(history)

    MockBrowserSession, browser_instance = _make_browser_session_class()
    MockAgent, agent_instance = _make_agent_class(history, fake_agent)
    MockChatOllama = MagicMock()

    # Clear any state from previous tests
    if hasattr(app.state, "pending_task"):
        del app.state.pending_task
    app.state.pending_task = "test task"

    MockBrowserProfile = MagicMock(return_value=MagicMock())

    with patch("agent.runner.pre_flight_check", new=AsyncMock()), \
         patch("agent.runner.BrowserProfile", MockBrowserProfile), \
         patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):

        with TestClient(app) as client:
            # One request to confirm the server is up; the event loop has already
            # started the agent task during lifespan startup.
            response = client.get("/nonexistent")
            # 404 is expected — we only care that the server responded
            assert response.status_code in (200, 404, 405)

        # TestClient.__exit__ triggers lifespan shutdown, which waits for the task
        # to complete (or cancels it). Since Agent.run() returns instantly in
        # the mock, the task finishes before the cancel fires.

    # --- Assertions ---

    # BrowserProfile was constructed with prohibited_domains and browser settings
    assert MockBrowserProfile.called, "BrowserProfile was never instantiated"
    profile_kwargs = MockBrowserProfile.call_args.kwargs
    assert profile_kwargs.get("channel") == "chrome"
    assert profile_kwargs.get("headless") is False
    assert profile_kwargs.get("keep_alive") is False
    assert "prohibited_domains" in profile_kwargs

    # BrowserSession was constructed with browser_profile=
    MockBrowserSession.assert_called_once_with(
        browser_profile=MockBrowserProfile.return_value,
    )
    assert browser_instance.llm_screenshot_size == (1024, 640)

    # ChatOllama was constructed with ollama_options={"num_ctx": 32000} and the configured model
    MockChatOllama.assert_called_once_with(
        model=config.ollama_model,
        ollama_options={"num_ctx": 32000},
    )

    # Agent was instantiated (task= argument and others come from run_agent)
    assert MockAgent.called, "Agent class was never instantiated"

    # browser.kill() was awaited in the finally block of run_agent
    browser_instance.kill.assert_awaited()

    # JSONL training data written — exactly 2 lines (one per on_step_end call)
    jsonl_path: Path = tmp_path / "training" / "runs.jsonl"
    assert jsonl_path.exists(), f"runs.jsonl not found at {jsonl_path}"

    lines = jsonl_path.read_text().splitlines()
    assert len(lines) == 2, f"Expected 2 JSONL lines, got {len(lines)}: {lines}"

    # Validate all nine D-09 keys are present in each record
    required_keys = {
        "timestamp",
        "run_id",
        "step_index",
        "screenshot_b64",
        "action_type",
        "action_target",
        "action_value",
        "narration",
        "step_success",
    }
    for i, line in enumerate(lines):
        record = json.loads(line)
        missing = required_keys - record.keys()
        assert not missing, f"Line {i} missing keys: {missing}. Record: {record}"


# ---------------------------------------------------------------------------
# Scenario B — POST /run endpoint triggers run_agent for a new task
# ---------------------------------------------------------------------------

def test_post_run_endpoint_starts_agent(monkeypatch, tmp_path):
    """POST /run must return {status: started} and start the agent as a background task.

    Proves: the /run HTTP endpoint calls asyncio.create_task(run_agent(task)) and
    returns 200 immediately; Agent is instantiated with the given task string.
    """
    from starlette.testclient import TestClient

    from agent.main import app

    monkeypatch.chdir(tmp_path)

    history = _make_fake_history(num_steps=2)
    fake_agent = _make_fake_agent(history)

    MockBrowserSession, browser_instance = _make_browser_session_class()
    MockAgent, agent_instance = _make_agent_class(history, fake_agent)
    MockChatOllama = MagicMock()

    # Ensure no pending_task from a previous test leaks in
    if hasattr(app.state, "pending_task"):
        del app.state.pending_task

    MockBrowserProfile = MagicMock(return_value=MagicMock())

    with patch("agent.runner.pre_flight_check", new=AsyncMock()), \
         patch("agent.runner.BrowserProfile", MockBrowserProfile), \
         patch("agent.runner.BrowserSession", MockBrowserSession), \
         patch("agent.runner.ChatOllama", MockChatOllama), \
         patch("agent.runner.Agent", MockAgent):

        with TestClient(app) as client:
            response = client.post("/run", data={"task": "another task"})
            assert response.status_code == 200
            assert response.json() == {"status": "started"}

    # Agent was instantiated with task="another task" and guardrail prompt
    from agent.runner import GUARDRAIL_PROMPT
    MockAgent.assert_called_once_with(
        task="another task",
        llm=MockChatOllama.return_value,
        browser_session=MockBrowserSession.return_value,
        extend_system_message=GUARDRAIL_PROMPT,
    )
