"""Round 5: MCP progress/schema/error classes and library runtime hygiene (no real browser)."""
from __future__ import annotations

import asyncio
import gc
import logging
from unittest import mock

import pytest

from local_browser_agent import mcp_server
from local_browser_agent import runner as runner_mod
from local_browser_agent.config import AgentConfig, BrowserConfig
from local_browser_agent.events import ActionDetailEvent, ProgressEvent
from local_browser_agent.runner import BrowserAgent, RunResult

pytest.importorskip("mcp")
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402


def _fake_run_task(emit_steps=3):
    async def fake(task, cfg=None, *, sinks=(), start_url=None, **kw):
        for i in range(1, emit_steps + 1):
            for s in sinks:
                await s(ActionDetailEvent(step=i, action_type="click", target_label=f"btn{i}"))
                await s(ProgressEvent(step=i, max_steps=10))
        return RunResult(run_id="r", task=task, status="success", success=True, final_result="ok")
    return fake


async def _call(args, progress_callback=None):
    server = mcp_server.build_server()
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        return await client.call_tool("run_browser_task", args, progress_callback=progress_callback)


async def test_progress_notifications_sent_with_token(monkeypatch):
    monkeypatch.setattr(mcp_server, "run_task", _fake_run_task())
    seen = []

    async def cb(progress, total, message):
        seen.append((progress, total, message))

    res = await _call({"task": "x"}, progress_callback=cb)
    assert not res.isError
    await asyncio.sleep(0.05)
    assert [p for p, _, _ in seen] == [1, 2, 3]
    assert all(t == 10 for _, t, _ in seen)
    assert seen[0][2] == "Step 1/10: click: btn1"


async def test_no_progress_token_no_sink(monkeypatch):
    got = {}

    async def fake(task, cfg=None, **kw):
        got.update(kw)
        return RunResult(run_id="r", task=task, status="success", success=True)

    monkeypatch.setattr(mcp_server, "run_task", fake)
    res = await _call({"task": "x"})
    assert not res.isError and "sinks" not in got


async def test_input_schema_forbids_additional_properties():
    server = mcp_server.build_server()
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == {"run_browser_task", "get_agent_config"}
    for t in tools:
        assert t.inputSchema.get("additionalProperties") is False
    run = next(t for t in tools if t.name == "run_browser_task")
    assert "ctx" not in run.inputSchema["properties"]
    res = await _call({"task": "x", "bogus": 1})
    assert res.structuredContent["error_kind"] == "invalid_argument"


async def test_wildcard_tld_is_invalid_argument(monkeypatch):
    monkeypatch.setattr(mcp_server, "run_task", _fake_run_task(0))
    d = await mcp_server._run("x", None, None, ["*.com"])
    assert d["error_kind"] == "invalid_argument" and d["status"] == "error"


def test_unlisted_tool_warning_silenced():
    mcp_server.build_server()
    assert logging.getLogger("mcp.server.lowlevel.server").level >= logging.ERROR


# ---- runner ---------------------------------------------------------------
async def test_cdp_connect_timeout_classified():
    msg = ("connect() timed out after 15s — CDP connection to http://127.0.0.1:39222 "
           "is too slow or unresponsive")
    a = BrowserAgent(AgentConfig(browser=BrowserConfig(cdp_url="http://127.0.0.1:39222")))
    with mock.patch.object(runner_mod, "build_llm", return_value=object()), \
            mock.patch.object(runner_mod, "build_browser_session", return_value=object()), \
            mock.patch.object(runner_mod, "Agent", side_effect=RuntimeError(msg)):
        res = await a.run("x")
    assert res.status == "error" and res.error_kind == "cdp_connect"
    assert "Timed out connecting to Chrome" in res.errors[0]


async def test_cancelled_run_leaves_no_unretrieved_exception(monkeypatch, caplog):
    from local_browser_agent import chrome

    monkeypatch.setattr(chrome, "find_chrome", lambda *a, **k: None)
    loop = asyncio.get_running_loop()
    contexts = []
    loop.set_exception_handler(lambda lp, c: contexts.append(c))
    caplog.set_level(logging.DEBUG)
    try:
        for delay in (0, 0.001):
            t = asyncio.create_task(BrowserAgent(AgentConfig()).run("x"))
            await asyncio.sleep(delay)
            t.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t
        for _ in range(3):
            gc.collect()
            await asyncio.sleep(0.01)
    finally:
        loop.set_exception_handler(None)
    assert not [c for c in contexts if "never retrieved" in str(c.get("message", ""))]
    assert "never retrieved" not in caplog.text


async def test_retrieve_exception_helper_on_pending_task():
    async def boom():
        await asyncio.sleep(0)
        raise ValueError("x")

    t = asyncio.ensure_future(boom())
    runner_mod._retrieve_exception(t)
    await asyncio.sleep(0.01)
    assert t.done()


def test_package_logger_has_null_handler():
    lg = logging.getLogger("local_browser_agent")
    assert any(isinstance(h, logging.NullHandler) for h in lg.handlers)


async def test_sink_timeout_configurable():
    calls = []

    async def slow(ev):
        calls.append(ev)
        await asyncio.sleep(1)

    a = BrowserAgent(AgentConfig(), sinks=[slow], sink_timeout_s=0.01, sink_max_timeouts=2)
    for _ in range(4):
        await a._emit(ProgressEvent(step=1))
    assert len(calls) == 2  # dropped after two timeouts


def test_log_filter_hides_start_failure_noise_unless_verbose(capsys):
    from local_browser_agent.log import configure_logging

    lg = logging.getLogger("browser_use.browser.session")
    configure_logging("warning")
    lg.error("CDP connected ... due to AssertionError: Root CDP client not initialized")
    lg.error("some other real error")
    err = capsys.readouterr().err
    assert "Root CDP client" not in err and "some other real error" in err
    configure_logging("info", third_party="info")
    lg.error("CDP connected ... due to AssertionError: Root CDP client not initialized")
    assert "Root CDP client" in capsys.readouterr().err
    configure_logging("warning")


async def test_second_cancel_during_cleanup_is_not_swallowed():
    started = asyncio.Event()

    class SlowCancelAgent:
        history = None

        def __init__(self, *a, **k):
            pass

        def stop(self):
            pass

        async def run(self, *a, **k):
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)  # slow cleanup; a second cancel lands here
                raise

    browser = mock.MagicMock()
    browser.kill = mock.AsyncMock()
    browser.stop = mock.AsyncMock()
    a = BrowserAgent(AgentConfig(browser=BrowserConfig(cdp_url="http://127.0.0.1:39222")))
    with mock.patch.object(runner_mod, "build_llm", return_value=object()), \
            mock.patch.object(runner_mod, "build_browser_session", return_value=browser), \
            mock.patch.object(runner_mod, "Agent", SlowCancelAgent):
        t = asyncio.create_task(a.run("x"))
        await asyncio.wait_for(started.wait(), 5)
        t.cancel()
        await asyncio.sleep(0.05)
        t.cancel()  # second cancellation while the bounded cleanup wait is running
        with pytest.raises(asyncio.CancelledError):
            await t
    assert t.cancelled()
