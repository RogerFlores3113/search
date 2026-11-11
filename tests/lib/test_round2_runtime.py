"""Round 2: runtime/config hardening (local network, start_url, stop, sinks, error_kind, secrets)."""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time

import pytest
from pydantic import ValidationError

import local_browser_agent
import local_browser_agent.runner as runner_mod
from local_browser_agent import (
    AgentConfig, BrowserAgent, BrowserConfig, CallbackSink, ChromeNotFoundError, JsonlTraceSink,
    ModelConfig, PreFlightError, SafetyPolicy,
)
from local_browser_agent.browser import build_browser_profile, is_local_host, start_url_problem
from tests.lib.test_runner_cli_mcp import FakeBrowser, make_agent_cls  # noqa: F401
from tests.lib.test_runner_cli_mcp import patched  # noqa: F401  (fixture)


# ---- 1/2: local network + internal schemes -------------------------------------------------
def _profile(**safety):
    return build_browser_profile(BrowserConfig(executable_path="/bin/true"), SafetyPolicy(**safety))


def test_local_network_blocked_by_default():
    p = _profile()
    assert p.block_ip_addresses is True
    assert {"localhost", "*.localhost"} <= set(p.prohibited_domains)
    assert "chrome://*" in p.prohibited_domains and "chrome-extension://*" in p.prohibited_domains


def test_allow_local_network_opens_it():
    p = _profile(allow_local_network=True)
    assert p.block_ip_addresses is False
    assert "localhost" not in p.prohibited_domains


def test_allowed_local_host_requires_opt_in():
    with pytest.raises(ValueError, match="allow_local_network"):
        _profile(allowed_domains=["127.0.0.1"])
    assert _profile(allowed_domains=["127.0.0.1"], allow_local_network=True).allowed_domains == ["127.0.0.1"]


def test_security_watchdog_semantics_for_blocked_urls():
    from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

    class S:
        browser_profile = _profile()
        logger = logging.getLogger('wd')

    wd = SecurityWatchdog.model_construct(browser_session=S())
    allowed = lambda u: SecurityWatchdog._is_url_allowed(wd, u)
    for u in ("http://127.0.0.1:8080/", "http://169.254.169.254/latest", "http://localhost/",
              "http://[::1]/", "chrome://settings/passwords", "chrome://password-manager",
              "chrome-extension://abc/x.html", "devtools://devtools/bundled/x", "file:///etc/passwd",
              "view-source:https://example.com"):
        assert not allowed(u), u
    assert allowed("https://example.com/")


def test_is_local_host():
    for h in ("localhost", "a.localhost", "127.0.0.1", "10.0.0.5", "::1", "[::1]", "169.254.169.254"):
        assert is_local_host(h)
    for h in ("example.com", "localhost.example.com", None, ""):
        assert not is_local_host(h)


def test_env_allow_local_network():
    cfg = AgentConfig.from_env(env={"LBA_ALLOW_LOCAL_NETWORK": "1"})
    assert cfg.safety.allow_local_network is True
    assert AgentConfig.from_env(env={}).safety.allow_local_network is False


# ---- 3: start_url validation ---------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "chrome://settings/passwords", "file:///etc/passwd", "data:text/html,hi", "javascript:alert(1)",
    "http://127.0.0.1:8080/", "http://localhost/x", "https://paypal.com/", "http://169.254.169.254/",
])
def test_start_url_problem_rejected(url):
    assert start_url_problem(url, SafetyPolicy()) is not None


def test_start_url_problem_ok_and_allowlist():
    assert start_url_problem("https://example.com/a?x=1", SafetyPolicy()) is None
    assert start_url_problem("http://127.0.0.1:1/", SafetyPolicy(allow_local_network=True)) is None
    pol = SafetyPolicy(allowed_domains=["example.com"])
    assert start_url_problem("https://other.org/", pol) and start_url_problem("https://example.com/", pol) is None


def test_start_url_message_hides_credentials():
    msg = start_url_problem("ftp://user:hunter2@h.com/?token=abc123", SafetyPolicy())
    assert "hunter2" not in msg and "abc123" not in msg


async def test_run_rejects_bad_start_url_before_launch(patched, monkeypatch):  # noqa: F811
    created = patched.install()
    pre = []

    async def preflight():
        pre.append(1)

    monkeypatch.setattr(runner_mod, "build_llm", lambda c: pytest.fail("must not build"))
    events = []
    res = await BrowserAgent(AgentConfig(), sinks=[CallbackSink(events.append)], preflight=preflight).run(
        "t", start_url="chrome://settings/passwords")
    assert res.status == "error" and res.error_kind == "start_url_blocked"
    assert "agent" not in created and not pre and not patched.browser.killed
    assert events[-1].type == "done"


# ---- 4: stop cancels the in-flight action; sinks -------------------------------------------
async def test_stop_cancels_in_flight_step(patched, monkeypatch):  # noqa: F811
    monkeypatch.setattr(runner_mod, "STOP_GRACE_S", 0.2)
    patched.install(steps=1, sleep=60)
    agent = BrowserAgent(AgentConfig())
    task = asyncio.create_task(agent.run("t"))
    for _ in range(100):
        if agent.is_active:
            break
        await asyncio.sleep(0.02)
    assert agent.is_active
    t0 = time.monotonic()
    agent.stop()
    res = await asyncio.wait_for(task, 5)
    assert time.monotonic() - t0 < 4
    assert res.status == "stopped" and res.error_kind == "stopped"
    assert patched.browser.killed


async def test_stop_cancels_pending_approval_wait(patched, monkeypatch):  # noqa: F811
    monkeypatch.setattr(runner_mod, "STOP_GRACE_S", 0.1)
    pending = asyncio.Event()
    started = asyncio.Event()

    async def approval_wait(agent, i):
        started.set()
        await pending.wait()  # an approval callback that never answers

    patched.install(steps=1, usage=approval_wait)
    agent = BrowserAgent(AgentConfig())
    task = asyncio.create_task(agent.run("t"))
    await asyncio.wait_for(started.wait(), 3)
    agent.stop()
    res = await asyncio.wait_for(task, 5)
    assert res.status == "stopped"


async def test_sink_dropped_after_three_timeouts(patched, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setattr(runner_mod, "SINK_TIMEOUT_S", 0.02)
    patched.install()
    calls = []

    async def slow(event):
        calls.append(event.type)
        await asyncio.sleep(1)

    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        await BrowserAgent(AgentConfig(), sinks=[slow]).run("t")
    assert len(calls) >= 3  # a concurrent screenshot emit may already be in flight
    warns = [r for r in caplog.records if "timed out" in r.getMessage()]
    assert len(warns) == 1 and "dropping" in warns[0].getMessage()


async def test_sink_failure_warning_names_event_and_has_traceback(patched, caplog):  # noqa: F811
    patched.install()

    def boom(event):
        raise RuntimeError("kaput")

    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        res = await BrowserAgent(AgentConfig(), sinks=[boom]).run("t")
    assert res.status == "success"
    recs = [r for r in caplog.records if "failed on" in r.getMessage()]
    assert recs and "'state'" in recs[0].getMessage() and recs[0].exc_info


async def test_concurrent_run_raises(patched):  # noqa: F811
    patched.install(steps=1, sleep=0.3)
    agent = BrowserAgent(AgentConfig())
    t = asyncio.create_task(agent.run("a"))
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeError):
        await agent.run("b")
    await t
    res = await agent.run("c")  # sequential reuse works
    assert res.status == "success"


# ---- 5: error_kind -------------------------------------------------------------------------
async def test_error_kinds(patched, monkeypatch):  # noqa: F811
    patched.install()

    def kind_of(res):
        return res.status, res.error_kind

    def raiser(exc):
        def f(*a, **k):
            raise exc
        return f

    monkeypatch.setattr(runner_mod, "build_browser_session", raiser(ChromeNotFoundError()))
    assert kind_of(await BrowserAgent(AgentConfig()).run("t")) == ("error", "chrome_missing")
    monkeypatch.setattr(runner_mod, "build_llm", raiser(PreFlightError("no key")))
    assert kind_of(await BrowserAgent(AgentConfig()).run("t")) == ("error", "preflight")
    monkeypatch.setattr(runner_mod, "build_llm", raiser(ValueError("bad cfg")))
    assert kind_of(await BrowserAgent(AgentConfig()).run("t")) == ("error", "config")

    async def bad_pre():
        raise RuntimeError("nope")

    monkeypatch.setattr(runner_mod, "build_llm", lambda c: object())
    assert kind_of(await BrowserAgent(AgentConfig(), preflight=bad_pre).run("t")) == ("error", "preflight")


async def test_error_kind_agent_error_timeout_and_success(patched, monkeypatch):  # noqa: F811
    patched.install(raises=RuntimeError("boom"))
    res = await BrowserAgent(AgentConfig()).run("t")
    assert (res.status, res.error_kind) == ("error", "agent_error")
    patched.install(steps=1, sleep=30)
    res = await BrowserAgent(AgentConfig(timeout_s=0.3)).run("t")
    assert (res.status, res.error_kind) == ("timeout", "timeout")
    patched.install()
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.error_kind is None and "error_kind" in res.to_dict()


async def test_error_kind_cdp_connect(patched):  # noqa: F811
    patched.install(raises=RuntimeError("connect call failed"))
    cfg = AgentConfig(browser=BrowserConfig(cdp_url="http://127.0.0.1:9222"))
    res = await BrowserAgent(cfg).run("t")
    assert (res.status, res.error_kind) == ("error", "cdp_connect")


# ---- 6: one run id -------------------------------------------------------------------------
async def test_every_event_carries_run_id(patched, tmp_path):  # noqa: F811
    patched.install()
    events = []
    trace = tmp_path / "t.jsonl"
    res = await BrowserAgent(AgentConfig(), sinks=[CallbackSink(events.append), JsonlTraceSink(trace)]).run("t")
    assert events and {e.run_id for e in events} == {res.run_id}
    lines = [json.loads(x) for x in trace.read_text().splitlines()]
    assert lines and {r["run_id"] for r in lines} == {res.run_id}


async def test_trace_sink_own_id_for_events_without_one(tmp_path):
    from local_browser_agent.events import StateEvent

    sink = JsonlTraceSink(tmp_path / "t.jsonl")
    await sink(StateEvent(state="running"))
    await sink(StateEvent(state="running", run_id="abc"))
    rows = [json.loads(x) for x in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert rows[0]["run_id"] == sink.run_id and rows[1]["run_id"] == "abc"


# ---- 7/8: validation + secrets -------------------------------------------------------------
def test_validate_assignment():
    cfg = AgentConfig()
    with pytest.raises(ValidationError):
        cfg.max_steps = -5
    with pytest.raises(ValidationError):
        cfg.model.base_url = "ftp://x"
    with pytest.raises(ValidationError):
        cfg.browser.cdp_url = "nonsense"
    cfg.max_steps = 7
    cfg.model.provider = "ANTHROPIC"
    assert cfg.max_steps == 7 and cfg.model.provider == "anthropic"


SECRET_URL = "https://user:hunter2@host.example/v1?token=tok123"


def test_repr_redacts_credentials():
    cfg = AgentConfig(
        model=ModelConfig(provider="openai_compatible", base_url=SECRET_URL, api_key="sk-abcdef123456",
                          extra={"default_headers": {"X-Key": "supersecret"}}),
        browser=BrowserConfig(cdp_url="http://u:cdppw@127.0.0.1:9222/?t=cdptok"),
    )
    r = repr(cfg) + str(cfg) + repr(cfg.model) + repr(cfg.browser)
    for s in ("hunter2", "tok123", "supersecret", "cdppw", "cdptok", "sk-abcdef123456"):
        assert s not in r
    safe = json.dumps(cfg.safe_dump())
    for s in ("hunter2", "tok123", "supersecret", "cdppw", "cdptok", "sk-abcdef123456"):
        assert s not in safe
    assert "host.example" in safe
    # model_dump keeps real values (documented)
    assert "hunter2" in cfg.model.model_dump()["base_url"]


def test_validation_errors_do_not_echo_credentials():
    with pytest.raises(ValidationError) as ei:
        ModelConfig(base_url="ftp://user:pw123456@h/")
    assert "pw123456" not in str(ei.value)
    with pytest.raises(ValidationError) as ei:
        BrowserConfig(cdp_url="ftp://user:pw123456@h/?k=v9999")
    assert "pw123456" not in str(ei.value) and "v9999" not in str(ei.value)
    assert "http(s) or ws(s)" in str(ei.value)


@pytest.mark.parametrize("url", ["ws://127.0.0.1:9222/devtools/browser/x", "https://h.example:9222"])
def test_cdp_url_valid(url):
    assert BrowserConfig(cdp_url=url).cdp_url == url


@pytest.mark.parametrize("url", ["127.0.0.1:9222", "http://", "file:///x", "ftp://h"])
def test_cdp_url_invalid(url):
    with pytest.raises(ValidationError):
        BrowserConfig(cdp_url=url)


# ---- 9/10: import side effects -------------------------------------------------------------
def _sub(code, **env):
    e = {k: v for k, v in os.environ.items()
         if k not in ("BROWSER_USE_SETUP_LOGGING", "BROWSER_USE_CLOUD_SYNC", "LITELLM_LOCAL_MODEL_COST_MAP",
                      "LBA_ALLOW_TELEMETRY", "ANONYMIZED_TELEMETRY")}
    e.update(env)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e, check=False)


def test_import_forces_privacy_env_and_leaves_root_logger_alone():
    code = ("import logging, os, local_browser_agent, browser_use\n"
            "assert logging.getLogger().handlers == [], logging.getLogger().handlers\n"
            "assert os.environ['BROWSER_USE_CLOUD_SYNC']=='false'\n"
            "assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP']=='True'\n")
    r = _sub(code, BROWSER_USE_CLOUD_SYNC="true", LITELLM_LOCAL_MODEL_COST_MAP="False")
    assert r.returncode == 0, r.stderr


def test_user_can_opt_back_into_browser_use_logging():
    code = ("import logging, local_browser_agent, browser_use\n"
            "assert logging.getLogger().handlers\n")
    assert _sub(code, BROWSER_USE_SETUP_LOGGING="true").returncode == 0


def test_exports():
    assert "ChromeNotFoundError" in local_browser_agent.__all__ and "PreFlightError" in local_browser_agent.__all__
