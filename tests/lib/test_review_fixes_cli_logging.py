"""Review fixes: --out preserved on all-infra, `lba mcp --strict`, no logging mutation on import."""
import asyncio
import json
import logging
import subprocess
import sys
from types import SimpleNamespace

import pytest

from local_browser_agent import cli, log
from local_browser_agent.evals import cli as eval_cli


def _cfg():
    return SimpleNamespace(model=SimpleNamespace(provider="fake", model="m"),
                           safety=SimpleNamespace(allowed_domains=["x.example"]), timeout_s=600, max_steps=25)


def _infra():
    return SimpleNamespace(status="error", final_result="", step_count=0, duration_s=0.1, cost_usd=None,
                           errors=["cdp"], blocked_actions=[], error_kind="cdp_connect")


def test_preexisting_out_keeps_old_files_on_all_infra(tmp_path):
    out = tmp_path / "res"
    out.mkdir()
    (out / "results.json").write_text('{"good":"previous run"}')
    (out / "results.jsonl").write_text('{"x":1}\n')

    async def fake(instruction, config, *, start_url):
        return _infra()

    assert eval_cli.main(["--tasks", "table-max-row", "--out", str(out)], run_fn=fake, config=_cfg()) == 3
    assert {p.name: p.read_text() for p in out.iterdir()} == {
        "results.json": '{"good":"previous run"}', "results.jsonl": '{"x":1}\n'}
    assert not [p for p in tmp_path.iterdir() if "staging" in p.name]  # staging dir cleaned up


def test_preexisting_out_replaced_when_kept(tmp_path):
    out = tmp_path / "res"
    out.mkdir()
    (out / "results.json").write_text("old")
    calls = []

    async def fake(instruction, config, *, start_url):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(status="complete", final_result="", step_count=1, duration_s=0.1, cost_usd=None,
                                   errors=[], blocked_actions=[], error_kind=None)
        return _infra()

    rc = eval_cli.main(["--tasks", "table-max-row", "--repeats", "3", "--max-infra-errors", "2", "--json",
                        "--out", str(out)], run_fn=fake, config=_cfg())
    assert rc == 3
    assert (out / "results.json").read_text() != "old"
    assert json.loads((out / "results.json").read_text())
    assert (out / "results.jsonl").exists()
    assert not [p for p in tmp_path.iterdir() if "staging" in p.name]  # staging dir cleaned up


def test_no_preexisting_out_leaves_no_dir(tmp_path):
    async def fake(instruction, config, *, start_url):
        return _infra()

    out = tmp_path / "res"
    assert eval_cli.main(["--tasks", "table-max-row", "--out", str(out)], run_fn=fake, config=_cfg()) == 3
    assert not out.exists() and not [p for p in tmp_path.iterdir() if "staging" in p.name]


def test_mcp_strict_flag(monkeypatch):
    from local_browser_agent import mcp_server

    seen = {}
    monkeypatch.setattr(mcp_server, "serve", lambda *a, **k: seen.update(k) or 0)
    assert cli.main(["mcp", "--strict"]) == 0
    assert seen["strict"] is True
    assert cli.main(["mcp"]) == 0
    assert seen["strict"] is None


def test_mcp_strict_flag_exits_2(monkeypatch, capsys):
    from local_browser_agent import mcp_server

    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    monkeypatch.delenv("LBA_MCP_STRICT", raising=False)
    monkeypatch.setattr(mcp_server, "build_server", lambda: pytest.fail("must not start"))
    assert cli.main(["mcp", "--strict"]) == 2
    assert "invalid configuration" in capsys.readouterr().err


def test_import_leaves_logger_class_untouched():
    code = ("import logging; before = logging.Logger.manager.loggerClass; import local_browser_agent; "
            "import local_browser_agent.runner; "
            "assert logging.Logger.manager.loggerClass is before, logging.Logger.manager.loggerClass")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_run_installs_then_restores(monkeypatch):
    from local_browser_agent import runner

    mgr = logging.Logger.manager
    before = mgr.loggerClass
    seen = {}

    async def fake_run(self, task, start_url):
        seen["during"] = mgr.loggerClass
        return "ok"

    monkeypatch.setattr(runner.BrowserAgent, "_run", fake_run)
    agent = runner.BrowserAgent(SimpleNamespace(model=SimpleNamespace(provider="x")))
    assert asyncio.run(agent.run("t")) == "ok"
    assert getattr(seen["during"], "_lba_factory", False)
    assert mgr.loggerClass is before


def test_ref_counted_nesting_and_host_class_honoured():
    mgr = logging.Logger.manager
    before = mgr.loggerClass
    orig_global = logging.getLoggerClass()

    class MyL(logging.Logger):
        pass

    pre = logging.getLogger("browser_use.preexisting_x")
    try:
        logging.setLoggerClass(MyL)
        log.install_quiet_filters()
        log.install_quiet_filters()
        lg = logging.getLogger("browser_use.created_during_run")
        assert isinstance(lg, MyL)
        assert any(isinstance(f, log._QuietUnlessVerbose) for f in lg.filters)
        assert any(isinstance(f, log._QuietUnlessVerbose) for f in pre.filters)
        other = logging.getLogger("zz.other_during_run")
        assert isinstance(other, MyL) and not other.filters
        log.uninstall_quiet_filters()
        assert getattr(mgr.loggerClass, "_lba_factory", False)  # still held by the outer run
        log.uninstall_quiet_filters()
        assert mgr.loggerClass is before
        assert not [f for f in lg.filters if isinstance(f, log._QuietUnlessVerbose)]
        assert not [f for f in pre.filters if isinstance(f, log._QuietUnlessVerbose)]
    finally:
        logging.setLoggerClass(orig_global)
        for n in ("browser_use.created_during_run", "browser_use.preexisting_x", "zz.other_during_run"):
            logging.Logger.manager.loggerDict.pop(n, None)


def test_non_class_previous_does_not_break():
    mgr = logging.Logger.manager
    before = mgr.loggerClass
    mgr.loggerClass = lambda name: logging.Logger(name)  # a host-installed factory function
    try:
        with log.quiet_filters():
            lg = logging.getLogger("browser_use.fn_prev")
            assert any(isinstance(f, log._QuietUnlessVerbose) for f in lg.filters)
            assert type(logging.getLogger("plain.fn_prev")) is logging.Logger
    finally:
        mgr.loggerClass = before
        for n in ("browser_use.fn_prev", "plain.fn_prev"):
            mgr.loggerDict.pop(n, None)
