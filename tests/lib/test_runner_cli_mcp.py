import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import local_browser_agent.runner as runner_mod
from local_browser_agent import (
    AgentConfig, BrowserAgent, CallbackSink, JsonlTraceSink, ModelConfig, QueueSink, RunResult,
)
from local_browser_agent.events import DoneEvent, ScreenshotEvent, StateEvent


def test_import_does_not_import_app():
    code = ("import sys, local_browser_agent; "
            "bad=[m for m in sys.modules if m=='local_browser_agent.app' or m.startswith('local_browser_agent.app.')]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class FakeBrowser:
    def __init__(self):
        self.killed = self.stopped = False
        self.shots = 0

    async def take_screenshot(self, **kw):
        self.shots += 1
        return b"jpg"

    async def kill(self):
        self.killed = True

    async def stop(self):
        self.stopped = True


class FakeHistory:
    def __init__(self, actions, urls, success, final):
        self._a, self._u, self._s, self._f = actions, urls, success, final

    def number_of_steps(self):
        return len(self._a)

    def model_actions(self):
        return self._a

    def final_result(self):
        return self._f

    def is_successful(self):
        return self._s

    def urls(self):
        return self._u


def make_agent_cls(*, success=True, final="done!", steps=2, sleep=0, raises=None, usage=None, calc=None):
    created = {}

    class FakeAgent:
        def __init__(self, **kw):
            created["kw"] = kw
            created["agent"] = self
            self.state = SimpleNamespace(stopped=False, last_result=[])
            self.actions = []
            self.history = FakeHistory(self.actions, ["about:blank", "https://a.com", "https://a.com"], None, None)
            self.token_cost_service = SimpleNamespace(usage_history=[], calculate_cost=calc)
            self.paused = False

        def stop(self):
            self.state.stopped = True

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        async def run(self, max_steps, on_step_end):
            created["max_steps"] = max_steps
            if raises:
                raise raises
            for i in range(steps):
                if sleep:
                    await asyncio.sleep(sleep)
                self.actions.append({"click": {"index": i + 1},
                                     "interacted_element": {"ax_name": f"Btn{i}"}})
                if i == 1:
                    self.state.last_result = [SimpleNamespace(error="oops")]
                if usage:
                    await usage(self, i)
                await on_step_end(self)
                if self.state.stopped:
                    break
            self.history = FakeHistory(self.actions, ["about:blank", "https://a.com", "https://a.com"], success, final)
            return self.history

    return FakeAgent, created


@pytest.fixture
def patched(monkeypatch):
    browser = FakeBrowser()
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: object())
    monkeypatch.setattr(runner_mod, "build_browser_session", lambda b, s: browser)
    monkeypatch.setattr(runner_mod, "SCREENSHOT_INTERVAL_S", 0.01)

    def install(**kw):
        cls, created = make_agent_cls(**kw)
        monkeypatch.setattr(runner_mod, "Agent", cls)
        return created

    return SimpleNamespace(browser=browser, install=install)


async def test_success(patched):
    created = patched.install()
    events = []
    res = await BrowserAgent(AgentConfig(), sinks=[CallbackSink(events.append)]).run("t", start_url="https://s.com")
    assert res.status == "success" and res.success is True and res.final_result == "done!"
    assert res.step_count == 2 and [s.index for s in res.steps] == [1, 2]
    assert res.steps[0].action_type == "click" and res.steps[0].target_label == "Btn0"
    assert res.steps[1].error == "oops" and res.errors == ["oops"]
    assert res.urls_visited == ["https://a.com"]
    assert res.cost_usd is None  # ollama
    assert patched.browser.killed
    kw = created["kw"]
    assert kw["use_judge"] is False and kw["initial_actions"][0]["navigate"]["url"] == "https://s.com"
    assert "SAFETY GUARDRAILS" in kw["extend_system_message"]
    types = [e.type for e in events]
    assert types[0] == "state" and types[1] == "model_info" and types[-1] == "done"
    assert {"progress", "action_detail", "token", "summary"} <= set(types)
    assert any(isinstance(e, StateEvent) and e.state == "complete" for e in events)
    assert res.to_dict()["status"] == "success"


async def test_failed(patched):
    patched.install(success=False, final="no")
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.status == "failed" and res.success is False


async def test_timeout(patched):
    patched.install(sleep=1)
    events = []
    res = await BrowserAgent(AgentConfig(timeout_s=0.05), sinks=[CallbackSink(events.append)]).run("t")
    assert res.status == "timeout" and res.success is None and res.errors
    assert patched.browser.killed
    assert events[-1].type == "done" and any(e.type == "error_msg" for e in events)


async def test_exception(patched):
    patched.install(raises=RuntimeError("boom"))
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.status == "error" and "boom" in res.errors[-1] and patched.browser.killed


async def test_build_llm_error_is_error_status(monkeypatch):
    def bad(cfg):
        raise ValueError("no key")
    monkeypatch.setattr(runner_mod, "build_llm", bad)
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.status == "error" and "no key" in res.errors[0]


async def test_stop(patched):
    created = patched.install(steps=50, sleep=0.01)
    ba = BrowserAgent(AgentConfig())
    t = asyncio.create_task(ba.run("t"))
    await asyncio.sleep(0.1)
    ba.pause()
    assert created["agent"].paused
    ba.resume()
    ba.stop()
    res = await t
    assert res.status == "stopped" and res.step_count < 50


async def test_cdp_attach_not_killed(patched):
    patched.install()
    cfg = AgentConfig()
    cfg.browser.cdp_url = "http://127.0.0.1:9222"
    await BrowserAgent(cfg).run("t")
    assert patched.browser.stopped and not patched.browser.killed


async def test_cost_for_api_provider(patched):
    async def usage(agent, i):
        agent.token_cost_service.usage_history.append(
            SimpleNamespace(model="m", usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)))

    async def calc(model, u):
        return SimpleNamespace(total_cost=0.01)

    patched.install(usage=usage, calc=calc)
    cfg = AgentConfig(model=ModelConfig(provider="anthropic", api_key=SecretStr("k")))
    res = await BrowserAgent(cfg).run("t")
    assert res.cost_usd == pytest.approx(0.02)


async def test_sinks_failure_isolated_and_queue_and_jsonl(patched, tmp_path):
    patched.install()

    async def bad(event):
        raise RuntimeError("sink down")

    data_q, ctrl_q = asyncio.Queue(), asyncio.Queue()
    trace = tmp_path / "t" / "trace.jsonl"
    res = await BrowserAgent(AgentConfig(), sinks=[bad, QueueSink(data_q, ctrl_q), JsonlTraceSink(trace)]).run("t")
    assert res.status == "success"
    ctrl = []
    while not ctrl_q.empty():
        ctrl.append(ctrl_q.get_nowait())
    assert isinstance(ctrl[-1], DoneEvent) and {e.type for e in ctrl} <= {"state", "model_info", "summary", "error_msg", "done"}
    data = []
    while not data_q.empty():
        data.append(data_q.get_nowait())
    assert any(isinstance(e, ScreenshotEvent) for e in data)  # QueueSink wants screenshots
    assert all(e.type not in ("done", "state") for e in data)
    lines = [json.loads(x) for x in trace.read_text().splitlines()]
    assert lines[-1]["type"] == "done" and all(l["type"] != "screenshot" for l in lines)


async def test_trace_only_sink_skips_screenshot_loop(patched, tmp_path):
    patched.install()
    await BrowserAgent(AgentConfig(), sinks=[JsonlTraceSink(tmp_path / "x.jsonl")]).run("t")
    assert patched.browser.shots == 0


async def test_jsonl_include_screenshots(tmp_path):
    s = JsonlTraceSink(tmp_path / "s.jsonl", include_screenshots=True)
    await s(ScreenshotEvent(b64="abc"))
    assert json.loads((tmp_path / "s.jsonl").read_text())["b64"] == "abc"


async def test_queue_sink_lossy_for_data():
    q = asyncio.Queue(maxsize=1)
    s = QueueSink(q)
    await s(ScreenshotEvent(b64="1"))
    await s(ScreenshotEvent(b64="2"))  # dropped, no raise
    assert q.qsize() == 1


async def test_callback_sink_sync_and_async():
    got = []

    async def a(e):
        got.append(("a", e))

    await CallbackSink(lambda e: got.append(("s", e)))(1)
    await CallbackSink(a)(2)
    assert got == [("s", 1), ("a", 2)]


# ---- CLI -------------------------------------------------------------------
def _fake_result(status="success"):
    return RunResult(run_id="r", task="t", status=status, success=status == "success", final_result="hi")


def test_cli_run_json(monkeypatch, capsys):
    from local_browser_agent import cli
    import local_browser_agent

    captured = {}

    async def fake_run_task(task, config=None, **kw):
        captured.update(task=task, config=config, kw=kw)
        return _fake_result()

    monkeypatch.setattr(local_browser_agent, "run_task", fake_run_task)
    monkeypatch.delenv("LBA_PROVIDER", raising=False)
    rc = cli.main(["run", "do it", "--json", "--no-preflight", "--headless", "--max-steps", "3",
                   "--provider", "ollama", "--model", "m", "--start-url", "https://x.com"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "success" and out["final_result"] == "hi"
    cfg = captured["config"]
    assert cfg.browser.headless and cfg.max_steps == 3 and cfg.model.model == "m"
    assert captured["kw"]["start_url"] == "https://x.com"


def test_cli_failure_exit_code_and_trace(monkeypatch, capsys, tmp_path):
    from local_browser_agent import cli
    import local_browser_agent

    async def fake_run_task(task, config=None, **kw):
        assert isinstance(kw["sinks"][0], JsonlTraceSink)
        return _fake_result("failed")

    monkeypatch.setattr(local_browser_agent, "run_task", fake_run_task)
    rc = cli.main(["run", "x", "--no-preflight", "--trace", str(tmp_path / "t.jsonl")])
    assert rc == 1 and "status:   failed" in capsys.readouterr().out


def test_cli_eval_missing(capsys):
    from local_browser_agent import cli
    try:
        import local_browser_agent.evals.cli  # noqa: F401
        pytest.skip("evals installed")
    except ImportError:
        pass
    assert cli.main(["eval"]) == 2
    assert "not available" in capsys.readouterr().err


# ---- MCP -------------------------------------------------------------------
def test_mcp_registration_and_busy(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    server = mcp_server.build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"run_browser_task", "get_agent_config"}

    gate = asyncio.Event()
    seen = {}

    async def fake_run_task(task, cfg=None, **kw):
        seen.update(task=task, cfg=cfg, kw=kw)
        await gate.wait()
        return _fake_result()

    monkeypatch.setattr(mcp_server, "run_task", fake_run_task)
    monkeypatch.setenv("LBA_API_KEY", "sk-hidden")
    monkeypatch.setenv("LBA_PROVIDER", "openai")

    async def scenario():
        first = asyncio.create_task(mcp_server.run_browser_task(
            "a", start_url="https://s.com", max_steps=4, allowed_domains=["s.com"]))
        await asyncio.sleep(0.05)
        busy = await mcp_server.run_browser_task("b")
        assert busy.isError and busy.structuredContent["status"] == "error" and "busy" in busy.structuredContent["error"]
        gate.set()
        return (await first).structuredContent

    res = asyncio.run(scenario())
    assert res["status"] == "success"
    assert seen["cfg"].max_steps == 4 and seen["cfg"].safety.allowed_domains == ["s.com"]
    assert seen["kw"]["start_url"] == "https://s.com"
    cfg = mcp_server.get_agent_config()
    assert cfg["model"]["api_key"] == "set" and "sk-hidden" not in json.dumps(cfg)


def test_lba_eval_forwards_leading_options(capsys):
    from local_browser_agent import cli

    assert cli.main(["eval", "--list"]) == 0
    out = capsys.readouterr().out
    assert "safety-cart-no-order" in out
