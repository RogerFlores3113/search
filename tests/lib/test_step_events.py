"""StepCompletedEvent delivery, preflight hook and control-state accessors (fakes only)."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import local_browser_agent.runner as runner_mod
from local_browser_agent import AgentConfig, BrowserAgent, JsonlTraceSink, ModelConfig, QueueSink
from local_browser_agent.events import StepCompletedEvent


class FakeBrowser:
    async def take_screenshot(self, **kw):
        return b"jpg"

    async def kill(self):
        pass

    async def stop(self):
        pass


def make_agent_cls(*, usage=None, calc=None, has_errors=False):
    class FakeAgent:
        def __init__(self, **kw):
            self.kw = kw
            self.state = SimpleNamespace(stopped=False, last_result=[])
            self.actions = []
            self.token_cost_service = SimpleNamespace(usage_history=[], calculate_cost=calc)
            self.history = SimpleNamespace(
                number_of_steps=lambda: len(self.actions), model_actions=lambda: self.actions,
                screenshots=lambda: ["SHOT1", "SHOT2"][: len(self.actions)], has_errors=lambda: has_errors,
                urls=lambda: ["https://a.com"], final_result=lambda: "ok", is_successful=lambda: True)

        def pause(self): ...
        def resume(self): ...
        def stop(self):
            self.state.stopped = True

        async def run(self, max_steps, on_step_end):
            cb = self.kw["register_new_step_callback"]
            for i in (1, 2):
                await cb(None, SimpleNamespace(thinking=f"think{i}", evaluation_previous_goal="",
                                               next_goal=f"goal{i}", memory="m"), i)
                self.actions.append({"click": {"index": 7}, "interacted_element": {"ax_name": "Go"}})
                self.state.last_result = [SimpleNamespace(error="boom")] if i == 2 else []
                if usage:
                    await usage(self, i)
                await on_step_end(self)
            return self.history

    return FakeAgent


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: object())
    monkeypatch.setattr(runner_mod, "build_browser_session", lambda b, s: FakeBrowser())

    def install(**kw):
        monkeypatch.setattr(runner_mod, "Agent", make_agent_cls(**kw))

    return install


class Collector:
    wants_screenshots = False
    wants_step_events = True

    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


async def test_step_events_only_reach_opted_in_sinks(patched, tmp_path):
    patched()
    col, plain = Collector(), []
    q = asyncio.Queue()
    trace = JsonlTraceSink(tmp_path / "t.jsonl")

    async def plain_sink(e):
        plain.append(e)

    plain_sink.wants_screenshots = False
    res = await BrowserAgent(AgentConfig(), sinks=[col, plain_sink, QueueSink(q), trace]).run("t")
    steps = [e for e in col.events if isinstance(e, StepCompletedEvent)]
    assert [s.step for s in steps] == [1, 2] and res.run_id == steps[0].run_id
    assert not any(isinstance(e, StepCompletedEvent) for e in plain)
    assert not any(isinstance(e, StepCompletedEvent) for e in list(q._queue))
    assert "step_completed" not in (tmp_path / "t.jsonl").read_text()


async def test_step_event_contents(patched):
    patched()
    col = Collector()
    await BrowserAgent(AgentConfig(), sinks=[col]).run("t")
    s1, s2 = [e for e in col.events if isinstance(e, StepCompletedEvent)]
    assert s1.screenshot_b64 == "SHOT1" and s2.screenshot_b64 == "SHOT2"
    # the interacted_element skip-key idiom: action_type is the action, not "interacted_element"
    assert s1.action_type == "click" and s1.target == "7" and s1.target_label == "Go"
    assert (s1.thinking, s1.next_goal, s1.memory) == ("think1", "goal1", "m")
    assert s1.evaluation_previous_goal is None  # empty string normalised to None
    assert s1.error is None and s2.error == "boom"  # per-step error
    assert s1.duration_ms is not None and s1.run_has_errors is False


async def test_run_has_errors_is_cumulative(patched):
    patched(has_errors=True)
    col = Collector()
    await BrowserAgent(AgentConfig(), sinks=[col]).run("t")
    s1 = next(e for e in col.events if isinstance(e, StepCompletedEvent))
    assert s1.run_has_errors is True and s1.error is None


async def test_ollama_steps_have_no_token_fields(patched):
    async def usage(agent, i):
        agent.token_cost_service.usage_history.append(
            SimpleNamespace(model="m", usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)))

    patched(usage=usage)
    col = Collector()
    await BrowserAgent(AgentConfig(), sinks=[col]).run("t")
    s1 = next(e for e in col.events if isinstance(e, StepCompletedEvent))
    assert (s1.prompt_tokens, s1.completion_tokens, s1.cost_usd) == (None, None, None)


async def test_api_provider_steps_carry_tokens_and_cost(patched):
    async def usage(agent, i):
        agent.token_cost_service.usage_history.append(
            SimpleNamespace(model="m", usage=SimpleNamespace(prompt_tokens=10 * i, completion_tokens=5)))

    async def calc(model, u):
        return SimpleNamespace(total_cost=0.01)

    patched(usage=usage, calc=calc)
    col = Collector()
    cfg = AgentConfig(model=ModelConfig(provider="anthropic", api_key=SecretStr("k")))
    await BrowserAgent(cfg, sinks=[col]).run("t")
    s1, s2 = [e for e in col.events if isinstance(e, StepCompletedEvent)]
    assert (s1.prompt_tokens, s1.completion_tokens, s1.cost_usd) == (10, 5, 0.01)
    assert s2.prompt_tokens == 20  # only the new usage entries of that step


async def test_preflight_failure_is_error_status_and_skips_browser(monkeypatch):
    built = []
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: built.append("llm") or object())
    events = []

    async def sink(e):
        events.append(e)

    async def preflight():
        raise RuntimeError("Ollama unreachable")

    res = await BrowserAgent(AgentConfig(), sinks=[sink], preflight=preflight).run("t")
    assert res.status == "error" and res.errors == ["Ollama unreachable"] and not built
    kinds = [e.type for e in events]
    assert kinds[:2] == ["state", "model_info"] and kinds[-3:] == ["error_msg", "state", "done"]


async def test_is_active_and_paused_accessors(patched):
    patched()
    ba = BrowserAgent(AgentConfig())
    assert not ba.is_active and not ba.is_paused
    ba.pause()  # no run: no-op
    assert not ba.is_paused
    await ba.run("t")
    assert not ba.is_active and not ba.is_paused


async def test_timeout_message(patched, monkeypatch):
    class Slow:
        def __init__(self, **kw): ...
        state = SimpleNamespace(stopped=False, last_result=[])
        history = None

        async def run(self, max_steps, on_step_end):
            await asyncio.sleep(1)

    monkeypatch.setattr(runner_mod, "Agent", Slow)
    res = await BrowserAgent(AgentConfig(timeout_s=0.05)).run("t")
    assert res.status == "timeout" and res.errors[-1] == "Session timeout (0.05s)"
