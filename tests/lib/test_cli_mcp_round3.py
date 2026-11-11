"""Round-3 fixes: MCP busy regression, CLI flag validation, trace/cdp checks, quiet logging, error text."""
import asyncio
import json
import logging

import pytest

from local_browser_agent import RunResult, cli
from local_browser_agent.log import configure_logging, format_validation_error


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("LBA_"):
            monkeypatch.delenv(k)


@pytest.fixture(autouse=True)
def _bare_root_logger():
    """A real CLI process has no root handlers; pytest's capture handlers would hide ours."""
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    saved_loggers = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level,
                         logging.getLogger(n).propagate) for n in ("browser_use", "bubus", "local_browser_agent")}
    root.handlers = []
    yield
    root.handlers, root.level = saved, level
    for n, (hs, lvl, prop) in saved_loggers.items():
        lg = logging.getLogger(n)
        lg.handlers, lg.level, lg.propagate = hs, lvl, prop


def _bare():
    """pytest re-adds its capture handler to root for the call phase; drop it for stderr assertions."""
    logging.getLogger().handlers = []


# ---- MCP busy path --------------------------------------------------------
def test_mcp_busy_regression_two_concurrent_calls(monkeypatch):
    from local_browser_agent import mcp_server

    gate = asyncio.Event()
    calls = []

    async def slow_run_task(task, cfg=None, **kw):
        calls.append(task)
        await gate.wait()
        return RunResult(run_id="r", task=task, status="success", success=True, final_result="ok")

    monkeypatch.setattr(mcp_server, "run_task", slow_run_task)

    async def scenario():
        first = asyncio.create_task(mcp_server._run("one", None, None, None))
        await asyncio.sleep(0.05)
        busy = await mcp_server._run("two", None, None, None)
        gate.set()
        return busy, await first

    busy, first = asyncio.run(scenario())
    assert calls == ["one"]  # the second call never reached the runner
    assert busy["status"] == "error" and busy["error_kind"] == "busy" and busy["task"] == "two"
    assert "busy" in busy["errors"][0] and busy["steps"] == [] and busy["success"] is None
    assert first["status"] == "success"
    # the lock is released afterwards


# ---- CLI flag validation --------------------------------------------------
@pytest.mark.parametrize("flags,needle", [
    (["--max-steps", "0"], "max_steps"),
    (["--max-steps", "-3"], "max_steps"),
    (["--max-steps", "9999"], "max_steps"),
    (["--timeout", "-1"], "timeout_s"),
    (["--timeout", "0"], "timeout_s"),
])
def test_cli_flag_validation_not_bypassed(flags, needle, capsys):
    rc = cli.main(["run", "x", "--no-preflight", *flags])
    err = capsys.readouterr().err
    assert rc == 2 and needle in err
    assert "errors.pydantic.dev" not in err and "validation error for" not in err


@pytest.mark.parametrize("url", ["notaurl", "", "ftp://h/x", "http://", "ws://"])
def test_cli_rejects_bad_cdp_url(url, capsys):
    rc = cli.main(["run", "x", "--no-preflight", "--cdp-url", url])
    assert rc == 2 and "invalid --cdp-url" in capsys.readouterr().err


def test_cli_accepts_good_cdp_url_and_flags(monkeypatch, capsys):
    import local_browser_agent

    seen = {}

    async def fake(task, cfg=None, **kw):
        seen["cfg"] = cfg
        return RunResult(run_id="r", task=task, status="success", success=True)

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    rc = cli.main(["run", "x", "--no-preflight", "--cdp-url", "ws://127.0.0.1:9222/devtools/browser/abc",
                   "--max-steps", "7", "--timeout", "30", "--allowed-domain", "a.com", "--headless"])
    assert rc == 0
    cfg = seen["cfg"]
    assert cfg.max_steps == 7 and cfg.timeout_s == 30 and cfg.browser.headless
    assert cfg.safety.allowed_domains == ["a.com"] and cfg.browser.cdp_url.startswith("ws://127.0.0.1")


def test_cli_provider_override_picks_up_provider_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    args = cli._build_parser().parse_args(["run", "x", "--provider", "Anthropic"])
    cfg = cli._config_from_args(args)
    assert cfg.model.provider == "anthropic" and cfg.model.api_key.get_secret_value() == "sk-ant-x"


def test_cli_config_error_json_has_run_id_and_clean_message(capsys):
    rc = cli.main(["run", "x", "--json", "--max-steps", "0"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 2 and out["status"] == "error" and out["run_id"]
    assert "max_steps:" in out["errors"][0] and "errors.pydantic.dev" not in out["errors"][0]


# ---- --trace --------------------------------------------------------------
def test_cli_unwritable_trace_exits_2(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    rc = cli.main(["run", "x", "--no-preflight", "--trace", str(blocker / "sub" / "t.jsonl")])
    err = capsys.readouterr().err
    assert rc == 2 and "--trace" in err


def test_preflight_failure_trace_uses_json_run_id(monkeypatch, capsys, tmp_path):
    from local_browser_agent import models

    async def boom(cfg):
        raise models.PreFlightError("Ollama is not running")

    monkeypatch.setattr(models, "check_provider", boom)
    trace = tmp_path / "t.jsonl"
    rc = cli.main(["run", "x", "--json", "--trace", str(trace)])
    out = json.loads(capsys.readouterr().out)
    recs = [json.loads(line) for line in trace.read_text().splitlines()]
    assert rc == 3 and len(recs) == 3
    assert {r["run_id"] for r in recs} == {out["run_id"]}


def test_human_mode_errors_on_stderr_summary_on_stdout(monkeypatch, capsys):
    import local_browser_agent

    async def fake(task, cfg=None, **kw):
        return RunResult(run_id="r", task=task, status="failed", success=False, errors=["boom happened"])

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    rc = cli.main(["run", "x", "--no-preflight"])
    cap = capsys.readouterr()
    assert rc == 1 and "status:   failed" in cap.out and "boom happened" not in cap.out
    assert "boom happened" in cap.err


# ---- logging --------------------------------------------------------------
def test_format_validation_error_strips_boilerplate():
    from local_browser_agent import AgentConfig

    with pytest.raises(Exception) as ei:
        AgentConfig(max_steps=0, timeout_s=-1)
    msg = format_validation_error(ei.value)
    assert "max_steps: " in msg and "timeout_s: " in msg
    assert "errors.pydantic.dev" not in msg and "validation error" not in msg
    assert format_validation_error(ValueError("plain\nFor further information visit https://errors.pydantic.dev/x")) == "plain"


def _stderr_after(capsys, fn):
    capsys.readouterr()
    fn()
    return capsys.readouterr().err


def test_quiet_mode_silences_third_party_and_tracebacks(capsys):
    _bare()
    configure_logging("error", third_party="off", color=False)
    bu, own = logging.getLogger("browser_use"), logging.getLogger("local_browser_agent")

    def emit():
        try:
            raise RuntimeError("cdp down")
        except RuntimeError:
            bu.error("\U0001F6A8 connect failed", exc_info=True)
            logging.getLogger("browser_use.sub").exception("boom")
        own.warning("own warning")
        own.error("own error")

    err = _stderr_after(capsys, emit)
    assert "own error" in err and "own warning" not in err
    assert "connect failed" not in err and "Traceback" not in err and "boom" not in err


def test_third_party_visible_without_traceback_or_emoji_when_enabled(capsys):
    _bare()
    configure_logging("info", color=False)
    bu = logging.getLogger("browser_use")

    def emit():
        try:
            raise RuntimeError("x")
        except RuntimeError:
            bu.error("\U0001F6A8 visible", exc_info=True)

    err = _stderr_after(capsys, emit)
    assert "visible" in err and "Traceback" not in err and "\U0001F6A8" not in err


def test_configure_logging_removes_browser_use_root_handler(capsys):
    from browser_use.logging_config import setup_logging

    root = logging.getLogger()
    _bare()
    setup_logging(force_setup=True)
    configure_logging("error", third_party="off", color=False)
    assert not any(type(h.formatter).__module__.startswith("browser_use")
                   for h in root.handlers if h.formatter is not None)
    err = _stderr_after(capsys, lambda: logging.getLogger("local_browser_agent").error("only me"))
    assert err.count("only me") == 1


def test_json_mode_defaults_to_quiet_logging(monkeypatch, capsys):
    _bare()
    import local_browser_agent

    async def fake(task, cfg=None, **kw):
        logging.getLogger("browser_use").error("third party noise")
        logging.getLogger("local_browser_agent").warning("run failed: chrome missing")
        return RunResult(run_id="r", task=task, status="error", success=None, errors=["chrome missing"])

    monkeypatch.setattr(local_browser_agent, "run_task", fake)
    rc = cli.main(["run", "x", "--no-preflight", "--json"])
    cap = capsys.readouterr()
    assert rc == 1 and json.loads(cap.out)["status"] == "error"
    assert "noise" not in cap.err and "chrome missing" not in cap.err
