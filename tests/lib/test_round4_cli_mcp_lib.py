"""Round-4 minors: sink failure logging, run_task_sync in a loop, MCP validation order / unknown args,
CLI --trace / --start-url / --json errors / exit codes, configure_logging export and domain-list filter."""
import asyncio
import json
import logging

import pytest

import local_browser_agent
from local_browser_agent import AgentConfig, BrowserAgent, RunResult, cli
from local_browser_agent.events import StateEvent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    import os

    for k in list(os.environ):
        if k.startswith("LBA_"):
            monkeypatch.delenv(k)


# ---- sink failure logging --------------------------------------------------------
async def test_broken_sink_traceback_only_once(caplog):
    def boom(event):
        raise RuntimeError("kaput")

    agent = BrowserAgent(AgentConfig(), sinks=[boom])
    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        for _ in range(4):
            await agent._emit(StateEvent(state="running"))
    recs = [r for r in caplog.records if "event sink" in r.getMessage()]
    assert len(recs) == 4
    assert recs[0].exc_info and "failed on" in recs[0].getMessage()
    for n, r in enumerate(recs[1:], start=2):
        assert not r.exc_info and f"#{n}" in r.getMessage() and "'state'" in r.getMessage()


# ---- run_task_sync ---------------------------------------------------------------
async def test_run_task_sync_inside_loop_raises_cleanly(recwarn):
    with pytest.raises(RuntimeError, match="cannot be called from a running event loop"):
        local_browser_agent.run_task_sync("x")
    import gc

    gc.collect()
    assert not [w for w in recwarn if "never awaited" in str(w.message)]


# ---- configure_logging export / filter ------------------------------------------
def test_configure_logging_exported():
    assert "configure_logging" in local_browser_agent.__all__
    from local_browser_agent.log import configure_logging

    assert local_browser_agent.configure_logging is configure_logging


def test_domain_list_warning_filtered_except_debug():
    from local_browser_agent.log import configure_logging

    lg = logging.getLogger("browser_use.utils")
    rec = logging.LogRecord("browser_use.utils", logging.WARNING, __file__, 1,
                            "Optimizing domain list with 120 items to set", (), None)
    other = logging.LogRecord("browser_use.utils", logging.WARNING, __file__, 1, "something else", (), None)
    try:
        configure_logging("warning")
        assert not lg.filter(rec) and lg.filter(other)
        configure_logging("info")
        assert not lg.filter(rec)
        configure_logging("debug")
        assert lg.filter(rec)
        configure_logging("warning", third_party="debug")
        assert lg.filter(rec)
    finally:
        configure_logging("warning")


# ---- MCP -------------------------------------------------------------------------
def test_mcp_invalid_call_reported_even_when_busy(monkeypatch):
    from local_browser_agent import mcp_server

    gate = asyncio.Event()

    async def slow(task, cfg=None, **kw):
        await gate.wait()
        return RunResult(run_id="r", task=task, status="success", success=True)

    monkeypatch.setattr(mcp_server, "run_task", slow)

    async def scenario():
        first = asyncio.create_task(mcp_server._run("one", None, None, None))
        await asyncio.sleep(0.05)
        bad_steps = await mcp_server._run("two", None, 0, None)
        bad_url = await mcp_server._run("two", "ftp://x", None, None)
        monkeypatch.setenv("LBA_MAX_STEPS", "0")
        bad_cfg = await mcp_server._run("two", None, None, None)
        monkeypatch.delenv("LBA_MAX_STEPS")
        monkeypatch.setenv("LBA_ALLOWED_DOMAINS", "a.com")
        not_allowed = await mcp_server._run("two", None, None, ["evil.com"])
        monkeypatch.delenv("LBA_ALLOWED_DOMAINS")
        busy = await mcp_server._run("two", None, None, None)
        gate.set()
        await first
        return bad_steps, bad_url, bad_cfg, not_allowed, busy

    bad_steps, bad_url, bad_cfg, not_allowed, busy = asyncio.run(scenario())
    assert bad_steps["error_kind"] == "invalid_argument"
    assert bad_url["error_kind"] == "invalid_argument"
    assert bad_cfg["error_kind"] == "config"
    assert not_allowed["error_kind"] == "invalid_argument"
    assert busy["error_kind"] == "busy"


def test_mcp_unknown_arguments_rejected():
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    server = mcp_server.build_server()

    async def call(name, args):
        return await server.call_tool(name, args)

    res = asyncio.run(call("run_browser_task", {"task": "x", "bogus": 1, "other": 2}))
    sc = res.structuredContent if hasattr(res, "structuredContent") else res[1]
    assert sc["status"] == "error" and sc["error_kind"] == "invalid_argument"
    assert "bogus" in sc["errors"][0] and "other" in sc["errors"][0] and sc["task"] == "x"
    res = asyncio.run(call("get_agent_config", {"nope": 1}))
    sc = res.structuredContent if hasattr(res, "structuredContent") else res[1]
    assert sc["error_kind"] == "invalid_argument" and "nope" in sc["error"]


def test_agent_config_model_is_typed_and_matches_public_config():
    from local_browser_agent import mcp_server

    schema = mcp_server.AgentConfigModel.model_json_schema()
    defs = schema["$defs"]
    assert {"_ModelSection", "_BrowserSection", "_SafetySection"} <= set(defs)
    d = mcp_server.public_config(AgentConfig())
    parsed = mcp_server.AgentConfigModel.model_validate(d)
    assert parsed.model.provider == "ollama" and parsed.browser.channel == "chrome"
    assert parsed.safety.blocked_domains
    # every key of the real dump is declared (not just tolerated as an extra)
    for section, model in (("model", mcp_server._ModelSection), ("browser", mcp_server._BrowserSection),
                           ("safety", mcp_server._SafetySection)):
        assert set(d[section]) <= set(model.model_fields), section


def test_serve_error_prefix(monkeypatch, capsys):
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    assert mcp_server.serve(strict=True) == 2
    err = capsys.readouterr().err
    assert err.startswith("lba mcp: error: invalid configuration")
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert lines and all(ln.startswith("lba mcp: error: invalid configuration: ") for ln in lines)
    assert any("max_steps" in ln for ln in lines)


# ---- CLI -------------------------------------------------------------------------
def test_trace_missing_parent_dir_not_created(tmp_path, capsys):
    target = tmp_path / "nope" / "t.jsonl"
    rc = cli.main(["run", "x", "--no-preflight", "--trace", str(target)])
    err = capsys.readouterr().err
    assert rc == 2 and "cannot write --trace" in err and "directory does not exist" in err
    assert err.startswith("lba run: error:")
    assert not target.parent.exists()


@pytest.mark.parametrize("url", ["notaurl", "ftp://h/x", "http://", "file:///etc/passwd", "javascript:alert(1)"])
def test_cli_rejects_bad_start_url(url, capsys):
    rc = cli.main(["run", "x", "--no-preflight", "--start-url", url])
    assert rc == 2 and "invalid --start-url" in capsys.readouterr().err


def test_cli_policy_blocked_start_url_is_runtime_exit_1(monkeypatch, capsys):
    async def fake(task, cfg=None, **kw):
        return RunResult(run_id="r", task=task, status="error", success=None, errors=["blocked"],
                         error_kind="start_url_blocked")

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    assert cli.main(["run", "x", "--no-preflight", "--start-url", "https://chase.com"]) == 1


def test_cli_json_config_errors_one_entry_per_problem(capsys):
    rc = cli.main(["run", "x", "--json", "--max-steps", "0", "--timeout", "-1"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 2 and out["error_kind"] == "config"
    assert len(out["errors"]) == 2
    assert any(e.startswith("max_steps:") for e in out["errors"])
    assert any(e.startswith("timeout_s:") for e in out["errors"])
    assert not any("invalid configuration" in e or "\n" in e for e in out["errors"])
    assert cap.err.startswith("lba run: error: invalid configuration")


def test_cli_parser_prog_names():
    p = cli._build_parser()
    sub = next(a for a in p._actions if getattr(a, "choices", None) and "run" in a.choices)
    assert sub.choices["run"].prog == "lba run" and sub.choices["mcp"].prog == "lba mcp"
    assert "exit codes" in sub.choices["run"].format_help()


@pytest.mark.parametrize("kind", ["chrome_missing", "preflight", "cdp_connect"])
def test_cli_environment_failures_exit_3(kind, monkeypatch):
    async def fake(task, cfg=None, **kw):
        return RunResult(run_id="r", task=task, status="error", success=None, errors=["env"], error_kind=kind)

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    assert cli.main(["run", "x", "--no-preflight"]) == 3


@pytest.mark.parametrize("kind", ["agent_error", "timeout", "config", "captcha", None])
def test_cli_other_failures_exit_1(kind, monkeypatch):
    async def fake(task, cfg=None, **kw):
        return RunResult(run_id="r", task=task, status="failed", success=False, errors=["x"], error_kind=kind)

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    assert cli.main(["run", "x", "--no-preflight"]) == 1
