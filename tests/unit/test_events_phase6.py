"""Phase 6 RED gate test suite: ThoughtEvent and ActionDetailEvent contract.

All tests in this file are RED (failing) until Plan 02 wires agent/events.py
and agent/runner.py. Tests cover every row in 06-RESEARCH.md Phase
Requirements -> Test Map.

Requirements covered: TRANS-01, TRANS-02, TRANS-03

Phase 6 boundary: ThoughtEvent fires before each action via
register_new_step_callback; ActionDetailEvent replaces NarrationEvent in
_log_step. No UI wiring — Phase 9 renders these events.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.events import ThoughtEvent, ActionDetailEvent, StateEvent


# ---------------------------------------------------------------------------
# Dataclass shape contract — TRANS-01, TRANS-03
# ---------------------------------------------------------------------------

def test_thought_event_shape():
    """ThoughtEvent defaults and keyword construction match D-03 field spec.

    TRANS-01: model evaluation fields must be present with correct names.
    """
    # Default instantiation
    evt = ThoughtEvent()
    assert evt.type == "thought"
    assert evt.step == 0
    assert evt.thinking is None
    assert evt.evaluation_previous_goal is None
    assert evt.next_goal is None
    assert evt.memory is None

    # Keyword construction with all non-type fields
    evt2 = ThoughtEvent(
        step=3,
        thinking="I see the page",
        evaluation_previous_goal="Previous goal was met",
        next_goal="Click the search button",
        memory="Found 5 results",
    )
    assert evt2.step == 3
    assert evt2.thinking == "I see the page"
    assert evt2.evaluation_previous_goal == "Previous goal was met"
    assert evt2.next_goal == "Click the search button"
    assert evt2.memory == "Found 5 results"


def test_thought_event_null_fields():
    """dataclasses.asdict(ThoughtEvent(step=1)) must include null-eligible keys with value None.

    Pins ROADMAP success criterion 4: ThoughtEvent fields are null (not missing
    keys) when the model returns no thought text.

    TRANS-01: evaluation_previous_goal field must be present as null.
    """
    evt = ThoughtEvent(step=1)
    asdict_result = dataclasses.asdict(evt)

    # Each optional field must be PRESENT in the dict (not absent)
    assert "thinking" in asdict_result
    assert asdict_result["thinking"] is None

    assert "evaluation_previous_goal" in asdict_result
    assert asdict_result["evaluation_previous_goal"] is None

    assert "next_goal" in asdict_result
    assert asdict_result["next_goal"] is None

    assert "memory" in asdict_result
    assert asdict_result["memory"] is None


def test_thought_event_type_literal():
    """ThoughtEvent().type must equal the string 'thought'.

    TRANS-01: event type discriminator for SSE deserialization.
    """
    assert ThoughtEvent().type == "thought"


def test_action_detail_event_shape():
    """ActionDetailEvent defaults and keyword construction match D-07 field spec.

    TRANS-03: action_type, target, value, url, success fields must all be present.
    """
    # Default instantiation
    evt = ActionDetailEvent()
    assert evt.type == "action_detail"
    assert evt.step == 0
    assert evt.action_type == "unknown"
    assert evt.target is None
    assert evt.value is None
    assert evt.url is None
    assert evt.success is None
    assert evt.step_duration_ms is None

    # Keyword construction with all fields populated
    evt2 = ActionDetailEvent(
        step=2,
        action_type="click_element",
        target="5",
        value=None,
        url=None,
        success=None,
        step_duration_ms=250,
    )
    assert evt2.step == 2
    assert evt2.action_type == "click_element"
    assert evt2.target == "5"
    assert evt2.value is None
    assert evt2.url is None
    assert evt2.success is None
    assert evt2.step_duration_ms == 250


def test_action_detail_event_null_fields():
    """dataclasses.asdict(ActionDetailEvent(step=1, action_type='click_element'))
    must include optional keys with value None.

    TRANS-03: optional fields must emit null, not be absent from SSE JSON.
    """
    evt = ActionDetailEvent(step=1, action_type="click_element")
    asdict_result = dataclasses.asdict(evt)

    assert "target" in asdict_result
    assert asdict_result["target"] is None

    assert "value" in asdict_result
    assert asdict_result["value"] is None

    assert "url" in asdict_result
    assert asdict_result["url"] is None

    assert "success" in asdict_result
    assert asdict_result["success"] is None

    assert "step_duration_ms" in asdict_result
    assert asdict_result["step_duration_ms"] is None


def test_action_detail_event_type_literal():
    """ActionDetailEvent().type must equal the string 'action_detail'.

    TRANS-03: event type discriminator for SSE deserialization.
    """
    assert ActionDetailEvent().type == "action_detail"


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

def _make_agent_output(
    thinking="I analyzed the page",
    evaluation_previous_goal="Goal was achieved",
    next_goal="Click search button",
    memory="Found 3 results",
):
    """Return a SimpleNamespace mimicking AgentOutput with the four thought fields.

    The action attribute is a placeholder — _pre_step does not read it.
    """
    return types.SimpleNamespace(
        thinking=thinking,
        evaluation_previous_goal=evaluation_previous_goal,
        next_goal=next_goal,
        memory=memory,
        action=[types.SimpleNamespace()],  # placeholder; _pre_step does not read this
    )


def _make_fake_agent_history(actions=None):
    """Return a fake agent instance shaped like browser-use's Agent object.

    The model_actions return value uses the real browser-use format:
    outer key = action name, inner dict = params, interacted_element added.

    Args:
        actions: list of action dicts to return from model_actions(). Defaults
                 to a single click_element action.
    """
    if actions is None:
        actions = [{"click_element": {"index": 5}, "interacted_element": None}]
    action_list = actions  # capture for lambda

    token_cost_service = types.SimpleNamespace(
        usage_history=[],
        calculate_cost=AsyncMock(return_value=None),
    )
    history = types.SimpleNamespace(
        number_of_steps=lambda: 1,
        model_actions=lambda: action_list,
        screenshots=lambda: ["iVBORw0KGgo="],
        has_errors=lambda: False,
    )
    state = types.SimpleNamespace(last_result=[])
    return types.SimpleNamespace(
        history=history,
        state=state,
        token_cost_service=token_cost_service,
    )


class FakeAgentWithCallback:
    """Fake Agent that captures register_new_step_callback and invokes it before on_step_end.

    Simulates the browser-use step lifecycle:
    1. register_new_step_callback(_pre_step) fires before action (TRANS-02)
    2. on_step_end(_log_step) fires after action

    Args:
        agent_output: SimpleNamespace mimicking AgentOutput. Defaults to _make_agent_output().
        step_num: step counter value passed to the callback. Defaults to 1.
        actions: model_actions list for the fake history. Defaults to click_element.
    """

    def __init__(self, agent_output=None, step_num=1, actions=None, **kwargs):
        self._callback = kwargs.get("register_new_step_callback")
        self._agent_output = agent_output if agent_output is not None else _make_agent_output()
        self._step_num = step_num
        self._fake_agent = _make_fake_agent_history(actions=actions)

    async def run(self, max_steps, on_step_end):
        # 1. Pre-action: invoke register_new_step_callback if wired (TRANS-02)
        if self._callback is not None:
            if inspect.iscoroutinefunction(self._callback):
                await self._callback(MagicMock(), self._agent_output, self._step_num)
            else:
                self._callback(MagicMock(), self._agent_output, self._step_num)
        # 2. Post-action: invoke on_step_end
        await on_step_end(self._fake_agent)
        result = MagicMock()
        result.final_result.return_value = "done"
        return result


# ---------------------------------------------------------------------------
# TRANS-01 / TRANS-02 — _pre_step wiring and ThoughtEvent emission
# ---------------------------------------------------------------------------

async def test_run_agent_passes_register_new_step_callback_kwarg(training_dir, monkeypatch_env):
    """run_agent must construct Agent with register_new_step_callback as a coroutine function kwarg.

    TRANS-02: _pre_step closure must be wired via register_new_step_callback so
    ThoughtEvent fires before each action.
    """
    from agent.runner import run_agent

    captured_kwargs: dict = {}

    class CapturingAgentClass:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        async def run(self, max_steps, on_step_end):
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", CapturingAgentClass):
        await run_agent("test task")

    assert "register_new_step_callback" in captured_kwargs, (
        f"Agent must receive register_new_step_callback kwarg; got keys: {list(captured_kwargs.keys())}"
    )
    callback = captured_kwargs["register_new_step_callback"]
    assert inspect.iscoroutinefunction(callback), (
        f"register_new_step_callback must be a coroutine function (async def); "
        f"got {type(callback)}"
    )


async def test_pre_step_emits_thought_event(training_dir, monkeypatch_env):
    """_pre_step must emit exactly one ThoughtEvent with all four thought fields populated.

    TRANS-01: evaluation_previous_goal carried to user.
    TRANS-02: ThoughtEvent fires before action (via register_new_step_callback).
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    agent_output = _make_agent_output(
        thinking="I analyzed the page",
        evaluation_previous_goal="Goal was achieved",
        next_goal="Click search button",
        memory="Found 3 results",
    )

    class _Fake(FakeAgentWithCallback):
        def __init__(self, **kwargs):
            super().__init__(agent_output=agent_output, step_num=1, **kwargs)

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _Fake):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
    assert len(thought_events) == 1, (
        f"Expected exactly 1 ThoughtEvent; got {len(thought_events)}. "
        f"All event types: {[type(e).__name__ for e in events]}"
    )
    t = thought_events[0]
    assert t.step == 1, f"ThoughtEvent.step must be 1; got {t.step}"
    assert t.thinking == "I analyzed the page", f"thinking mismatch: {t.thinking!r}"
    assert t.evaluation_previous_goal == "Goal was achieved", (
        f"evaluation_previous_goal mismatch: {t.evaluation_previous_goal!r}"
    )
    assert t.next_goal == "Click search button", f"next_goal mismatch: {t.next_goal!r}"
    assert t.memory == "Found 3 results", f"memory mismatch: {t.memory!r}"


async def test_thought_event_null_when_model_omits_thinking(training_dir, monkeypatch_env):
    """ThoughtEvent fields must be None (null) when AgentOutput returns None or empty string.

    Covers ROADMAP success criterion 4: null not missing keys.
    Empty string memory must be normalized to None via 'or None' guard (RESEARCH.md Pitfall 2).

    TRANS-01: null fields still present as null in event payload.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    agent_output_no_thinking = _make_agent_output(
        thinking=None,
        evaluation_previous_goal="Previous goal met",
        next_goal="Navigate",
        memory="",  # empty string — must be normalized to None
    )

    class _Fake(FakeAgentWithCallback):
        def __init__(self, **kwargs):
            super().__init__(agent_output=agent_output_no_thinking, step_num=1, **kwargs)

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _Fake):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
    assert len(thought_events) >= 1, (
        f"Expected at least 1 ThoughtEvent; got {[type(e).__name__ for e in events]}"
    )
    t = thought_events[0]
    assert t.thinking is None, (
        f"ThoughtEvent.thinking must be None when AgentOutput.thinking is None; got {t.thinking!r}"
    )
    assert t.memory is None, (
        f"ThoughtEvent.memory must be None when AgentOutput.memory is '' (empty string normalized "
        f"via 'or None' guard per RESEARCH.md Pitfall 2); got {t.memory!r}"
    )


async def test_thought_event_step_matches_callback_step_num(training_dir, monkeypatch_env):
    """ThoughtEvent.step must equal the step_num parameter from register_new_step_callback.

    Do NOT use agent.history.number_of_steps() for ThoughtEvent.step — that
    returns the count of completed steps (off by one pre-action, per RESEARCH.md Pitfall 3).

    TRANS-02: step counter flows from callback parameter, not post-action history.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    class _Fake(FakeAgentWithCallback):
        def __init__(self, **kwargs):
            super().__init__(step_num=3, **kwargs)  # step_num=3 to verify it flows through

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _Fake):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
    assert len(thought_events) >= 1, "Expected at least 1 ThoughtEvent"
    assert thought_events[0].step == 3, (
        f"ThoughtEvent.step must equal the step_num from callback (3); "
        f"got {thought_events[0].step}"
    )


async def test_thought_event_fires_before_action_detail(training_dir, monkeypatch_env):
    """ThoughtEvent index in the queue must be strictly less than ActionDetailEvent index.

    TRANS-02: next goal surfaced BEFORE action executes.
    This test pins the ordering invariant that register_new_step_callback fires
    before on_step_end in the browser-use step lifecycle.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    class _Fake(FakeAgentWithCallback):
        def __init__(self, **kwargs):
            super().__init__(step_num=1, **kwargs)

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _Fake):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    thought_indices = [i for i, e in enumerate(events) if isinstance(e, ThoughtEvent)]
    action_detail_indices = [i for i, e in enumerate(events) if isinstance(e, ActionDetailEvent)]

    assert len(thought_indices) >= 1, (
        f"Expected at least 1 ThoughtEvent; got {[type(e).__name__ for e in events]}"
    )
    assert len(action_detail_indices) >= 1, (
        f"Expected at least 1 ActionDetailEvent; got {[type(e).__name__ for e in events]}"
    )
    assert thought_indices[0] < action_detail_indices[0], (
        f"ThoughtEvent (index {thought_indices[0]}) must come before "
        f"ActionDetailEvent (index {action_detail_indices[0]}) — TRANS-02"
    )


# ---------------------------------------------------------------------------
# TRANS-03 — ActionDetailEvent extraction
# ---------------------------------------------------------------------------

async def test_log_step_emits_action_detail_event(training_dir, monkeypatch_env):
    """_log_step must emit exactly one ActionDetailEvent with correct action_type and target.

    For click_element action with index=5: action_type='click_element', target='5'.

    TRANS-03: richer action label showing action type and target element.
    D-05: ActionDetailEvent replaces NarrationEvent in _log_step.
    D-07: action_type, target, value, url, success fields extracted from model_actions().
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history(
        actions=[{"click_element": {"index": 5}, "interacted_element": None}]
    )

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_events) == 1, (
        f"Expected exactly 1 ActionDetailEvent; got {len(action_events)}. "
        f"All event types: {[type(e).__name__ for e in events]}"
    )
    a = action_events[0]
    assert a.action_type == "click_element", (
        f"ActionDetailEvent.action_type must be 'click_element'; got {a.action_type!r}"
    )
    assert a.target == "5", (
        f"ActionDetailEvent.target must be str(index)='5'; got {a.target!r}"
    )
    assert a.step == 1, f"ActionDetailEvent.step must be 1; got {a.step}"


async def test_action_type_excludes_interacted_element(training_dir, monkeypatch_env):
    """action_type must be the non-'interacted_element' outer key from model_actions() dict.

    RESEARCH.md Pitfall 4: model_actions() appends interacted_element after model_dump().
    The first key in the dict should be the action name, but using list(d.keys())[0] is
    brittle. Must use next(k for k in d if k != 'interacted_element', 'unknown').

    TRANS-03: correct action type extraction.
    D-06: outer key of model_actions()[-1] dict = action type name.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history(
        actions=[{"navigate": {"url": "https://example.com"}, "interacted_element": {"some": "data"}}]
    )

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_events) >= 1, "Expected at least 1 ActionDetailEvent"
    assert action_events[0].action_type == "navigate", (
        f"action_type must be 'navigate' (not 'interacted_element'); "
        f"got {action_events[0].action_type!r}"
    )


async def test_action_detail_navigate_url(training_dir, monkeypatch_env):
    """navigate action must produce ActionDetailEvent with url field populated.

    TRANS-03: navigate action carries url in the structured event.
    D-06: url param from inner action params dict.
    D-07: ActionDetailEvent.url field carries the navigation target.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history(
        actions=[{"navigate": {"url": "https://example.com", "new_tab": False}, "interacted_element": None}]
    )

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_events) >= 1, "Expected at least 1 ActionDetailEvent"
    a = action_events[0]
    assert a.action_type == "navigate", f"action_type must be 'navigate'; got {a.action_type!r}"
    assert a.url == "https://example.com", (
        f"ActionDetailEvent.url must be 'https://example.com'; got {a.url!r}"
    )
    assert a.target is None, f"ActionDetailEvent.target must be None for navigate; got {a.target!r}"
    assert a.value is None, f"ActionDetailEvent.value must be None for navigate; got {a.value!r}"


async def test_action_detail_input_text_value(training_dir, monkeypatch_env):
    """input_text action must produce ActionDetailEvent with target (index) and value (text).

    TRANS-03: input_text action carries target element index and typed text.
    D-06: index param -> target (str), text param -> value.
    D-07: ActionDetailEvent.value carries user-typed text.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history(
        actions=[{"input_text": {"index": 3, "text": "search query", "clear": True}, "interacted_element": None}]
    )

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_events) >= 1, "Expected at least 1 ActionDetailEvent"
    a = action_events[0]
    assert a.action_type == "input_text", f"action_type must be 'input_text'; got {a.action_type!r}"
    assert a.target == "3", (
        f"ActionDetailEvent.target must be str(index)='3'; got {a.target!r}"
    )
    assert a.value == "search query", (
        f"ActionDetailEvent.value must be 'search query'; got {a.value!r}"
    )
    assert a.url is None, f"ActionDetailEvent.url must be None for input_text; got {a.url!r}"


async def test_action_detail_success_is_none_midrun(training_dir, monkeypatch_env):
    """ActionDetailEvent.success must be None for non-final (mid-run) steps.

    browser-use ActionResult.success is only True when is_done=True (validation
    constraint in views.py lines 339-347). Unit tests never simulate the final
    done step, so success must always be None here.

    TRANS-03: success field emits null for non-final steps.
    D-07: success: Optional[bool] = None for mid-run steps.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()
    fake_agent = _make_fake_agent_history()  # default click_element action

    class FakeAgentClass:
        def __init__(self, **kwargs):
            self._fake = fake_agent

        async def run(self, max_steps, on_step_end):
            await on_step_end(self._fake)
            result = MagicMock()
            result.final_result.return_value = "done"
            return result

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", FakeAgentClass):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]
    assert len(action_events) >= 1, "Expected at least 1 ActionDetailEvent"
    assert action_events[0].success is None, (
        f"ActionDetailEvent.success must be None for mid-run steps; "
        f"got {action_events[0].success!r}"
    )


async def test_thought_and_action_share_step_when_both_fire(training_dir, monkeypatch_env):
    """ThoughtEvent.step and ActionDetailEvent.step must equal the same browser step number.

    When register_new_step_callback fires with step_num=1 and model_actions()
    returns 1 completed action (number_of_steps()=1), both events share step=1.

    TRANS-02: thought and action events correspond to the same browser step.
    TRANS-03: ActionDetailEvent.step matches ThoughtEvent.step for the same action.
    """
    from agent.runner import run_agent

    queue: asyncio.Queue = asyncio.Queue()

    class _Fake(FakeAgentWithCallback):
        def __init__(self, **kwargs):
            super().__init__(step_num=1, **kwargs)

    mock_browser = MagicMock()
    mock_browser.kill = AsyncMock()

    with patch("agent.runner.pre_flight_check", AsyncMock()), \
         patch("agent.runner.BrowserSession", return_value=mock_browser), \
         patch("agent.runner.ChatOllama", MagicMock()), \
         patch("agent.runner.Agent", _Fake):
        await run_agent("test task", queue=queue)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    thought_events = [e for e in events if isinstance(e, ThoughtEvent)]
    action_events = [e for e in events if isinstance(e, ActionDetailEvent)]

    assert len(thought_events) >= 1, "Expected at least 1 ThoughtEvent"
    assert len(action_events) >= 1, "Expected at least 1 ActionDetailEvent"

    assert thought_events[0].step == action_events[0].step, (
        f"ThoughtEvent.step ({thought_events[0].step}) must equal "
        f"ActionDetailEvent.step ({action_events[0].step}) for the same browser step"
    )
    assert thought_events[0].step == 1, (
        f"Both events must have step=1; got ThoughtEvent.step={thought_events[0].step}"
    )
