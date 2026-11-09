"""CAPTCHA / human-verification handling in BrowserAgent (fakes only, no browser)."""
import asyncio
from types import SimpleNamespace

import pytest

import local_browser_agent.runner as runner_mod
from local_browser_agent import AgentConfig, BrowserAgent, CallbackSink
from local_browser_agent.captcha import looks_like_captcha
from local_browser_agent.events import HumanNeededEvent, StateEvent


class FakeBrowser:
    async def take_screenshot(self, **kw):
        return b"jpg"

    async def kill(self):
        pass

    async def stop(self):
        pass


class FakeHistory:
    def __init__(self, actions, final="done", success=True):
        self._a, self._f, self._s = actions, final, success

    def number_of_steps(self):
        return len(self._a)

    def model_actions(self):
        return self._a

    def final_result(self):
        return self._f

    def is_successful(self):
        return self._s

    def urls(self):
        return ["about:blank", "https://shop.example/login"]


def make_agent_cls(*, captcha_on_step=1, steps=3, ran=None):
    class FakeAgent:
        def __init__(self, **kw):
            self.state = SimpleNamespace(stopped=False, last_result=[])
            self.actions = []
            self.history = FakeHistory(self.actions)
            self.token_cost_service = SimpleNamespace(usage_history=[], calculate_cost=None)
            self.paused = False
            self.paused_waits = 0

        def stop(self):
            self.state.stopped = True

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        async def run(self, max_steps, on_step_end):
            for i in range(1, steps + 1):
                # browser-use blocks before the next step while paused
                while self.paused and not self.state.stopped:
                    self.paused_waits += 1
                    await asyncio.sleep(0.01)
                if self.state.stopped:
                    break
                self.actions.append({"click": {"index": i}, "interacted_element": None})
                self.state.last_result = (
                    [SimpleNamespace(error="Blocked by reCAPTCHA challenge")] if i == captcha_on_step else []
                )
                if ran is not None:
                    ran.append(i)
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


def test_looks_like_captcha():
    assert looks_like_captcha("Please solve the CAPTCHA to continue")
    assert looks_like_captcha("Access Denied by Cloudflare")
    assert not looks_like_captcha("element not found")
    assert not looks_like_captcha(None)


def test_on_captcha_defaults_to_fail():
    assert AgentConfig().on_captcha == "fail"


async def test_captcha_fail_ends_run_failed(patched):
    ran = []
    patched(ran=ran)
    events = []
    res = await BrowserAgent(AgentConfig(), sinks=[CallbackSink(events.append)]).run("t")
    assert res.status == "failed" and res.success is False
    assert any("human verification" in e.lower() for e in res.errors)
    assert ran == [1]  # the run did not go on to later steps
    needed = [e for e in events if isinstance(e, HumanNeededEvent)]
    assert len(needed) == 1 and needed[0].reason == "captcha" and needed[0].url == "https://shop.example/login"
    assert events[-1].type == "done" and any(e.type == "error_msg" for e in events)


async def test_captcha_pause_waits_for_resume_then_continues(patched):
    ran = []
    patched(ran=ran)
    events = []
    ba = BrowserAgent(AgentConfig(on_captcha="pause"), sinks=[CallbackSink(events.append)])
    t = asyncio.create_task(ba.run("t"))
    await asyncio.sleep(0.2)
    assert not t.done() and ba.is_paused and ran == [1]  # waiting for the human
    assert any(isinstance(e, HumanNeededEvent) for e in events)
    assert any(isinstance(e, StateEvent) and e.state == "paused" for e in events)
    ba.resume()
    res = await asyncio.wait_for(t, 2)
    assert ran == [1, 2, 3]
    assert res.status == "success" and not ba.is_paused
    states = [e.state for e in events if isinstance(e, StateEvent)]
    assert states.index("paused") < states.index("running", 1) and states[-1] == "complete"


async def test_captcha_pause_stop_ends_run_stopped(patched):
    patched()
    ba = BrowserAgent(AgentConfig(on_captcha="pause"))
    t = asyncio.create_task(ba.run("t"))
    await asyncio.sleep(0.15)
    assert ba.is_paused
    ba.stop()
    res = await asyncio.wait_for(t, 2)
    assert res.status == "stopped"


async def test_no_captcha_no_event(patched):
    patched(captcha_on_step=99)
    events = []
    res = await BrowserAgent(AgentConfig(), sinks=[CallbackSink(events.append)]).run("t")
    assert res.status == "success"
    assert not any(isinstance(e, HumanNeededEvent) for e in events)
