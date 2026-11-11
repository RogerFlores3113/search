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
    assert restrict_domains(["*.a.com"], ["a.com", "x.a.com", "*.x.a.com", "evil.com", "nota.com"]) == [
        "a.com", "x.a.com", "*.x.a.com"]
    assert restrict_domains(["a.com"], ["a.com", "www.a.com", "x.a.com", "evil.com", "nota.com"]) == [
        "a.com", "www.a.com"]
    assert restrict_domains(["a.com"], ["evil.com"]) == []


def test_restrict_domains_wildcard_call_does_not_widen_plain_server():
    from local_browser_agent.mcp_server import restrict_domains

    # browser-use: a plain "a.com" does not cover arbitrary subdomains, so "*.a.com" would widen it
    assert restrict_domains(["a.com"], ["*.a.com"]) == []
    assert restrict_domains(["a.com"], ["*.a.com", "a.com"]) == ["a.com"]
    assert restrict_domains(["*.a.com"], ["*.a.com"]) == ["*.a.com"]
    assert restrict_domains(["*.x.a.com"], ["*.a.com"]) == []


def _fake_run(monkeypatch, seen):
    from local_browser_agent import mcp_server

    async def fake(task, cfg=None, **kw):
        seen["cfg"] = cfg
        return RunResult(run_id="r", task=task, status="failed", success=False, errors=["nope"])

    monkeypatch.setattr(mcp_server, "run_task", fake)


def test_mcp_server_allowlist_not_widened(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_ALLOWED_DOMAINS", "*.a.com")
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


_RUN_KEYS = {"run_id", "task", "status", "success", "final_result", "steps", "step_count", "duration_s",
             "cost_usd", "errors", "urls_visited", "blocked_actions", "error_kind"}


def _assert_error_envelope(res, kind, text=None):
    assert res.isError is True
    sc = res.structuredContent
    assert set(sc) >= _RUN_KEYS and sc["status"] == "error" and sc["success"] is None
    assert sc["error_kind"] == kind and sc["errors"] and sc["steps"] == []
    assert json.loads(res.content[0].text) == sc
    if text:
        assert text in sc["errors"][0]


def test_mcp_every_failure_has_the_runresult_envelope(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    monkeypatch.delenv("LBA_ALLOWED_DOMAINS", raising=False)
    server = mcp_server.build_server()

    def call(args):
        return asyncio.run(server.call_tool("run_browser_task", args))

    # schema violations go through FastMCP's own validation and are wrapped
    for bad, text in (({"max_steps": 0}, "max_steps"), ({"max_steps": 10_000}, "max_steps"),
                      ({"allowed_domains": []}, "allowed_domains")):
        _assert_error_envelope(call({"task": "t", **bad}), "invalid_argument", text)
    _assert_error_envelope(call({}), "invalid_argument", "task")
    # handler-level rejections
    for args in ({"task": "   "},
                 {"task": "t", "start_url": "file:///etc/passwd"},
                 {"task": "t", "start_url": "javascript:alert(1)"},
                 {"task": "t", "start_url": "https://"}):
        _assert_error_envelope(call(args), "invalid_argument")
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    res = call({"task": "t"})
    _assert_error_envelope(res, "config", "max_steps")
    assert "errors.pydantic.dev" not in res.structuredContent["errors"][0]
    assert "validation error for" not in res.structuredContent["errors"][0]


def test_mcp_empty_intersection_is_enveloped(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_ALLOWED_DOMAINS", "a.com")
    seen = {}
    _fake_run(monkeypatch, seen)
    res = asyncio.run(mcp_server.run_browser_task("t", allowed_domains=["*.a.com"]))
    _assert_error_envelope(res, "invalid_argument", "LBA_ALLOWED_DOMAINS")
    assert "cfg" not in seen


def test_mcp_schemas_instructions_and_structured_config(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    server = mcp_server.build_server()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    run = tools["run_browser_task"]
    assert run.inputSchema["properties"]["max_steps"]["anyOf"][0]["maximum"] == 200
    assert "only one task" in run.description.lower()
    assert set(run.outputSchema["properties"]) == _RUN_KEYS
    assert tools["get_agent_config"].outputSchema is not None
    assert "LBA_ALLOWED_DOMAINS" in server.instructions and "ONE task" in server.instructions

    monkeypatch.setenv("LBA_PROVIDER", "openai")
    monkeypatch.setenv("LBA_API_KEY", "sk-hidden")
    res = asyncio.run(server.call_tool("get_agent_config", {}))
    assert res.isError is False and res.structuredContent["model"]["api_key"] == "set"
    monkeypatch.setenv("LBA_MAX_STEPS", "abc")
    res = asyncio.run(server.call_tool("get_agent_config", {}))
    assert res.isError is True and res.structuredContent["error_kind"] == "config"


def test_mcp_start_url_validated_before_runner(monkeypatch):
    pytest.importorskip("mcp.server.fastmcp")
    from local_browser_agent import mcp_server

    seen = {}
    _fake_run(monkeypatch, seen)
    res = asyncio.run(mcp_server.run_browser_task("t", start_url="ftp://x.com"))
    _assert_error_envelope(res, "invalid_argument", "start_url")
    assert "cfg" not in seen
    asyncio.run(mcp_server.run_browser_task("t", start_url="https://x.com/a"))
    assert "cfg" in seen


def test_serve_exits_2_on_bad_config(monkeypatch, capsys):
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    monkeypatch.setattr(mcp_server, "build_server", lambda: pytest.fail("must not start"))
    assert mcp_server.serve() == 2
    err = capsys.readouterr().err
    assert "invalid configuration" in err and "max_steps" in err and "errors.pydantic.dev" not in err
    monkeypatch.delenv("LBA_MAX_STEPS")
    monkeypatch.setenv("LBA_PROVIDER", "nope")
    assert cli.main(["mcp"]) == 2


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
