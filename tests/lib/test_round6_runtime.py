"""Round 6: sink limit validation, short failure log, import-time quiet filters, MCP degraded mode."""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from local_browser_agent import mcp_server
from local_browser_agent import runner as runner_mod
from local_browser_agent.config import AgentConfig
from local_browser_agent.runner import BrowserAgent, run_task, run_task_sync


# ---- 1. sink limit validation -----------------------------------------------------
@pytest.mark.parametrize("kw", [
    {"sink_timeout_s": 0}, {"sink_timeout_s": -1}, {"sink_timeout_s": float("nan")},
    {"sink_timeout_s": float("inf")}, {"sink_timeout_s": "5"}, {"sink_timeout_s": True},
    {"sink_max_timeouts": 0}, {"sink_max_timeouts": -2}, {"sink_max_timeouts": 1.5},
    {"sink_max_timeouts": True},
])
def test_invalid_sink_limits_raise(kw):
    with pytest.raises(ValueError, match="sink_"):
        BrowserAgent(AgentConfig(), **kw)
    with pytest.raises(ValueError, match="sink_"):
        run_task_sync("x", AgentConfig(), **kw)
    with pytest.raises(ValueError, match="sink_"):
        asyncio.run(run_task("x", AgentConfig(), **kw))


def test_valid_sink_limits_accepted():
    a = BrowserAgent(AgentConfig(), sink_timeout_s=0.5, sink_max_timeouts=1)
    assert (a.sink_timeout_s, a.sink_max_timeouts) == (0.5, 1)
    BrowserAgent(AgentConfig(), sink_timeout_s=3)


# ---- 2. short failure log ---------------------------------------------------------
async def test_failed_run_logs_short_warning(monkeypatch, caplog):
    def boom(b, s):
        raise ValueError("a very long distinctive failure message")

    monkeypatch.setattr(runner_mod, "build_browser_session", boom)
    with caplog.at_level(logging.DEBUG, logger="local_browser_agent"):
        res = await run_task("x", AgentConfig())
    assert res.status == "error"
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "failed" in r.getMessage()]
    assert len(warns) == 1
    assert warns[0].getMessage() == f"run {res.run_id} failed ({res.error_kind})"
    assert "distinctive" not in warns[0].getMessage()
    assert any("distinctive" in r.getMessage() and r.levelno == logging.DEBUG for r in caplog.records)


# ---- 3. import-time quiet filters -------------------------------------------------
class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


@pytest.fixture
def root_handler():
    from local_browser_agent.log import install_quiet_filters, uninstall_quiet_filters

    install_quiet_filters()  # no longer installed on import: a run (or the CLI / MCP entry point) holds it
    h = _Collect()
    root = logging.getLogger()
    root.addHandler(h)
    bu = logging.getLogger("browser_use")
    old = (bu.level, bu.propagate)
    bu.propagate = True  # an earlier configure_logging() may have cut it off from the root
    utils = logging.getLogger("browser_use.utils")
    saved = list(utils.filters)  # configure_logging() may have added its own _DomainListWarning
    from local_browser_agent.log import _QuietUnlessVerbose
    utils.filters[:] = [f for f in saved if isinstance(f, _QuietUnlessVerbose)]
    yield h
    utils.filters[:] = saved
    root.removeHandler(h)
    bu.setLevel(old[0])
    bu.propagate = old[1]
    uninstall_quiet_filters()


def _emit_noise():
    logging.getLogger("browser_use.utils").warning("Optimizing domain list with 166 items to set")
    sess = logging.getLogger("browser_use.BrowserSession-ab12 test-instance")
    sess.error("[BrowserSession.on_BrowserStartEvent(#1)] Failed (0.05s): ConnectError")
    sess.error("CDP failed due to AssertionError: Root CDP client not initialized")
    agent = logging.getLogger("browser_use.Agent-1234 test-instance")
    agent.error("Agent run failed with exception: boom", exc_info=True)
    sess.error("a genuinely useful error")


def test_noise_dropped_for_any_root_handler(root_handler):
    logging.getLogger("browser_use").setLevel(logging.NOTSET)
    _emit_noise()
    assert root_handler.msgs == ["a genuinely useful error"]


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_noise_kept_when_host_sets_browser_use_verbose(root_handler, level):
    logging.getLogger("browser_use").setLevel(level)
    _emit_noise()
    assert len(root_handler.msgs) == 5


def test_quiet_filters_idempotent():
    from local_browser_agent.log import install_quiet_filters

    install_quiet_filters()
    install_quiet_filters()
    from local_browser_agent.log import _QuietUnlessVerbose

    mine = [f for f in logging.getLogger("browser_use.utils").filters if isinstance(f, _QuietUnlessVerbose)]
    assert len(mine) == 2


# ---- 4. bubus level on the MCP server ---------------------------------------------
def test_build_server_silences_bubus_deadlock_warning():
    pytest.importorskip("mcp")
    bubus = logging.getLogger("bubus")
    old = bubus.level
    try:
        bubus.setLevel(logging.WARNING)
        mcp_server.build_server()
        assert bubus.level == logging.ERROR
        bubus.setLevel(logging.DEBUG)  # operator asked for verbose: untouched
        mcp_server.build_server()
        assert bubus.level == logging.DEBUG
    finally:
        bubus.setLevel(old)


# ---- 5. MCP degraded mode ---------------------------------------------------------
def test_serve_degraded_on_bad_config(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    monkeypatch.setenv("LBA_TIMEOUT_S", "-5")
    monkeypatch.delenv("LBA_MCP_STRICT", raising=False)
    ran = []

    class FakeServer:
        def run(self, transport):
            ran.append(transport)

    monkeypatch.setattr(mcp_server, "build_server", lambda: FakeServer())
    assert mcp_server.serve() == 0
    assert ran == ["stdio"]
    lines = [ln for ln in capsys.readouterr().err.splitlines() if "invalid configuration" in ln]
    assert len(lines) >= 2 and any("max_steps" in ln for ln in lines) and any("timeout_s" in ln for ln in lines)


@pytest.mark.parametrize("how", ["arg", "env"])
def test_serve_strict_exits_2(monkeypatch, how):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    monkeypatch.setattr(mcp_server, "build_server", lambda: pytest.fail("must not start"))
    if how == "env":
        monkeypatch.setenv("LBA_MCP_STRICT", "1")
        assert mcp_server.serve() == 2
    else:
        assert mcp_server.serve(strict=True) == 2


async def test_degraded_tools_return_config_envelope(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.shared.memory import create_connected_server_and_client_session

    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    monkeypatch.setenv("LBA_TIMEOUT_S", "-5")
    server = mcp_server.build_server()
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert names == {"run_browser_task", "get_agent_config"}
        res = await client.call_tool("run_browser_task", {"task": "t"})
        d = res.structuredContent
        assert res.isError and d["status"] == "error" and d["error_kind"] == "config"
        assert len(d["errors"]) >= 2 and all(e.startswith("invalid configuration: ") for e in d["errors"])
        assert any("max_steps" in e for e in d["errors"]) and any("timeout_s" in e for e in d["errors"])
        cfg = await client.call_tool("get_agent_config", {})
        assert cfg.isError and cfg.structuredContent["error_kind"] == "config"
        assert len(cfg.structuredContent["errors"]) >= 2
        json.dumps(cfg.structuredContent)
