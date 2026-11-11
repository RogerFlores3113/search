"""CLI --json/--trace on preflight failure, trace metadata, MCP policy and redaction."""
import asyncio
import io
import json
import logging
from datetime import datetime

import pytest

from local_browser_agent import AgentConfig, JsonlTraceSink, ModelConfig, RunResult, cli
from local_browser_agent.events import DoneEvent


def _preflight_fail(monkeypatch, msg="Ollama is not running"):
    from local_browser_agent import models

    async def boom(cfg):
        raise models.PreFlightError(msg)

    monkeypatch.setattr(models, "check_provider", boom)


def test_cli_json_preflight_failure(monkeypatch, capsys, tmp_path):
    _preflight_fail(monkeypatch)
    trace = tmp_path / "t.jsonl"
    rc = cli.main(["run", "x", "--json", "--trace", str(trace)])
    cap = capsys.readouterr()
    assert rc == 1
    out = json.loads(cap.out)
    assert out["status"] == "error" and out["success"] is None and out["errors"] == ["Ollama is not running"]
    assert out["steps"] == [] and out["step_count"] == 0 and out["task"] == "x"
    assert "Ollama is not running" in cap.err
    recs = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [r["type"] for r in recs] == ["error_msg", "state", "done"]
    assert recs[1]["state"] == "error"


def test_cli_human_preflight_failure_stdout_empty(monkeypatch, capsys):
    _preflight_fail(monkeypatch)
    assert cli.main(["run", "x"]) == 1
    cap = capsys.readouterr()
    assert cap.out == "" and "lba: Ollama" in cap.err


def test_cli_config_error_exit_2_json(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    rc = cli.main(["run", "x", "--json"])
    cap = capsys.readouterr()
    assert rc == 2 and json.loads(cap.out)["status"] == "error"


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("lba ")


def test_trace_sink_ts_run_id_and_append(tmp_path):
    p = tmp_path / "t.jsonl"

    async def go():
        a, b = JsonlTraceSink(p), JsonlTraceSink(p)
        await a(DoneEvent())
        await a(DoneEvent())
        await b(DoneEvent())
        return a, b

    a, b = asyncio.run(go())
    recs = [json.loads(line) for line in p.read_text().splitlines()]
    assert len(recs) == 3 and a.run_id != b.run_id
    assert recs[0]["run_id"] == recs[1]["run_id"] == a.run_id and recs[2]["run_id"] == b.run_id
    assert datetime.fromisoformat(recs[0]["ts"]).utcoffset().total_seconds() == 0


def test_configure_logging_levels_and_ansi():
    from local_browser_agent.log import configure_logging

    h = logging.StreamHandler(io.StringIO())
    lg = logging.getLogger("browser_use")
    lg.addHandler(h)
    try:
        configure_logging("error", color=False)
        assert lg.level == logging.ERROR
        lg.error("\x1b[31mred\x1b[0m")
        assert "\x1b" not in h.stream.getvalue() and "red" in h.stream.getvalue()
        with pytest.raises(ValueError):
            configure_logging("loud")
    finally:
        lg.removeHandler(h)


# ---- MCP -------------------------------------------------------------------
def test_restrict_domains():
    from local_browser_agent.mcp_server import restrict_domains

    assert restrict_domains(None, ["a.com"]) == ["a.com"]
    assert restrict_domains(["a.com"], ["a.com", "x.a.com", "evil.com", "nota.com"]) == ["a.com", "x.a.com"]
    assert restrict_domains(["a.com"], ["evil.com"]) == []


def _fake_run(monkeypatch, seen):
    from local_browser_agent import mcp_server

    async def fake(task, cfg=None, **kw):
        seen["cfg"] = cfg
        return RunResult(run_id="r", task=task, status="failed", success=False, errors=["nope"])

    monkeypatch.setattr(mcp_server, "run_task", fake)


def test_mcp_server_allowlist_not_widened(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_ALLOWED_DOMAINS", "a.com")
    seen = {}
    _fake_run(monkeypatch, seen)
    res = asyncio.run(mcp_server.run_browser_task("t", allowed_domains=["evil.com"]))
    assert res.isError and "cfg" not in seen  # not run
    res = asyncio.run(mcp_server.run_browser_task("t", allowed_domains=["sub.a.com", "evil.com"]))
    assert seen["cfg"].safety.allowed_domains == ["sub.a.com"]
    assert res.isError and res.structuredContent["status"] == "failed"  # failures are isError, dict preserved


def test_mcp_no_server_allowlist_uses_call(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    monkeypatch.delenv("LBA_ALLOWED_DOMAINS", raising=False)
    seen = {}
    _fake_run(monkeypatch, seen)
    asyncio.run(mcp_server.run_browser_task("t", allowed_domains=["x.com"]))
    assert seen["cfg"].safety.allowed_domains == ["x.com"]


def test_mcp_rejects_bad_bounds():
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp.exceptions import ToolError

    from local_browser_agent import mcp_server

    server = mcp_server.build_server()
    for bad in ({"max_steps": 0}, {"max_steps": 10_000}, {"allowed_domains": []}):
        with pytest.raises(ToolError):
            asyncio.run(server.call_tool("run_browser_task", {"task": "t", **bad}))
    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "run_browser_task")
    assert tool.inputSchema["properties"]["max_steps"]["anyOf"][0]["maximum"] == 200
    assert "only one task" in tool.description.lower()
    direct = asyncio.run(mcp_server._run("t", None, None, []))
    assert direct["status"] == "error"


def test_public_config_redacts():
    from local_browser_agent.mcp_server import public_config

    cfg = AgentConfig(model=ModelConfig(provider="openai_compatible", api_key="sk-x",
                                        base_url="https://user:pw@host/v1?token=Zq9tok",
                                        extra={"default_headers": {"Authorization": "Bearer zzz"}}))
    cfg.browser.cdp_url = "ws://127.0.0.1:9222/x?token=tok123"
    blob = json.dumps(public_config(cfg))
    for secret in ("sk-x", "user:pw", "pw@", "Zq9tok", "zzz", "tok123"):
        assert secret not in blob
    assert "host/v1" in blob and "default_headers" in blob
