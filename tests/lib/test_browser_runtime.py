"""Browser runtime hardening: Chrome discovery, blocklist, redaction, timeouts (fakes only)."""
import asyncio
import logging
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import local_browser_agent.chrome as chrome_mod
import local_browser_agent.runner as runner_mod
from local_browser_agent import (
    AgentConfig,
    BrowserAgent,
    BrowserConfig,
    CallbackSink,
    ModelConfig,
    SafetyPolicy,
)
from local_browser_agent.browser import build_browser_profile
from local_browser_agent.chrome import (
    CHROME_NOT_FOUND_MESSAGE,
    ChromeNotFoundError,
    find_chrome,
)
from local_browser_agent.models import PreFlightError
from local_browser_agent.redact import redact, redact_url

# ---- find_chrome ---------------------------------------------------------

def test_find_chrome_linux_which(monkeypatch):
    monkeypatch.setattr(chrome_mod.sys, "platform", "linux")
    monkeypatch.setattr(chrome_mod.shutil, "which", lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert find_chrome() == "/usr/bin/chromium"


def test_find_chrome_linux_opt_and_missing(monkeypatch):
    monkeypatch.setattr(chrome_mod.sys, "platform", "linux")
    monkeypatch.setattr(chrome_mod.shutil, "which", lambda n: None)
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: p == "/opt/google/chrome/chrome")
    assert find_chrome() == "/opt/google/chrome/chrome"
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: False)
    assert find_chrome() is None


def test_find_chrome_macos_and_windows(monkeypatch):
    monkeypatch.setattr(chrome_mod.sys, "platform", "darwin")
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: p == chrome_mod.CHROME_PATH_MACOS)
    assert find_chrome() == chrome_mod.CHROME_PATH_MACOS
    monkeypatch.setattr(chrome_mod.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", "PF")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: True)
    assert "chrome.exe" in find_chrome()


def test_chrome_not_found_is_preflight_error():
    assert issubclass(ChromeNotFoundError, PreFlightError)
    assert "https://www.google.com/chrome/" in str(ChromeNotFoundError())


# ---- build_browser_profile ----------------------------------------------

def test_profile_passes_executable_path_and_disables_extensions():
    prof = build_browser_profile(BrowserConfig(headless=True), SafetyPolicy())
    assert prof.executable_path is not None and str(prof.executable_path).endswith("fake-chrome")
    assert prof.enable_default_extensions is False


def test_profile_respects_explicit_executable_path_and_cdp():
    prof = build_browser_profile(BrowserConfig(executable_path="/x/chrome"), SafetyPolicy())
    assert str(prof.executable_path) == "/x/chrome"
    prof = build_browser_profile(BrowserConfig(cdp_url="http://127.0.0.1:9222"), SafetyPolicy())
    assert prof.cdp_url == "http://127.0.0.1:9222" and prof.enable_default_extensions is False


def test_profile_raises_when_chrome_missing(monkeypatch):
    monkeypatch.setattr("local_browser_agent.browser.find_chrome", lambda channel="chrome": None)
    with pytest.raises(ChromeNotFoundError) as e:
        build_browser_profile(BrowserConfig(), SafetyPolicy())
    assert str(e.value) == CHROME_NOT_FOUND_MESSAGE
    # cdp_url / executable_path do not need discovery
    build_browser_profile(BrowserConfig(cdp_url="http://127.0.0.1:9222"), SafetyPolicy())
    build_browser_profile(BrowserConfig(executable_path="/x/chrome"), SafetyPolicy())


def test_blocked_domains_cover_subdomains_and_case():
    prof = build_browser_profile(BrowserConfig(), SafetyPolicy(blocked_domains=["Evil.COM.", "bad.org"]))
    pd = set(prof.prohibited_domains)
    assert {"evil.com", "*.evil.com", "bad.org", "*.bad.org", "paypal.com", "*.paypal.com"} <= pd


def test_allow_list_cannot_reenable_blocked():
    prof = build_browser_profile(
        BrowserConfig(), SafetyPolicy(blocked_domains=["bad.org"],
                                      allowed_domains=["ok.com", "paypal.com", "login.PayPal.com.", "*.bad.org"]))
    assert list(prof.allowed_domains) == ["ok.com"]
    prof = build_browser_profile(BrowserConfig(), SafetyPolicy(allowed_domains=["paypal.com"]))
    assert "paypal.com" not in prof.allowed_domains and prof.allowed_domains  # never "allow everything"


def test_large_blocklist_keeps_wildcards():
    prof = build_browser_profile(
        BrowserConfig(), SafetyPolicy(blocked_domains=[f"d{i}.example" for i in range(150)]))
    assert isinstance(prof.prohibited_domains, list) and "*.d7.example" in prof.prohibited_domains


# ---- redact --------------------------------------------------------------

def test_redact():
    assert redact("bad key abcdef123456 here", ["abcdef123456"]) == "bad key *** here"
    assert redact("short abc", ["abc"]) == "short abc"  # < 6 chars is never masked
    assert "sk-ant-api03-ABCDEFGHIJ" not in redact("401 for sk-ant-api03-ABCDEFGHIJ", [])
    assert "Bearer" not in redact("Authorization: Bearer abcdefghijkl", []) or "***" in redact("Bearer abcdefghijkl", [])
    assert "hunter2xyz" not in redact("api_key=hunter2xyz failed", [])
    assert redact("plain error", []) == "plain error" and redact("", ["x" * 8]) == ""


def test_redact_url():
    assert redact_url("ws://user:pw@127.0.0.1:9222/devtools?token=abc#f") == "ws://127.0.0.1:9222/devtools"


# ---- runner --------------------------------------------------------------

class FakeBrowser:
    def __init__(self, hang_kill=False):
        self.hang_kill = hang_kill
        self.killed = False

    async def take_screenshot(self, **kw):
        return b"jpg"

    async def kill(self):
        if self.hang_kill:
            await asyncio.sleep(3600)
        self.killed = True

    async def stop(self):
        await self.kill()


class OkHistory:
    def number_of_steps(self):
        return 0

    def model_actions(self):
        return []

    final_result = lambda self: "done"
    is_successful = lambda self: True
    urls = lambda self: []


def agent_cls(run):
    class FakeAgent:
        def __init__(self, **kw):
            self.state = SimpleNamespace(stopped=False, last_result=[])
            self.history = OkHistory()
            self.token_cost_service = SimpleNamespace(usage_history=[])
            self.paused = False

        def stop(self):
            self.state.stopped = True

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

        async def run(self, max_steps, on_step_end):
            return await run(self, on_step_end)

    return FakeAgent


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: object())
    box = {"browser": FakeBrowser()}
    monkeypatch.setattr(runner_mod, "build_browser_session", lambda b, s: box["browser"])

    def install(run):
        monkeypatch.setattr(runner_mod, "Agent", agent_cls(run))

    install.box = box
    return install


async def test_chrome_missing_errors_before_any_session(monkeypatch):
    monkeypatch.setattr("local_browser_agent.browser.find_chrome", lambda channel="chrome": None)
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: object())
    created = []
    monkeypatch.setattr("local_browser_agent.browser.BrowserSession", lambda **kw: created.append(kw))
    monkeypatch.setattr(runner_mod, "Agent", lambda **kw: created.append(kw))
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.status == "error" and res.errors == [CHROME_NOT_FOUND_MESSAGE]
    assert created == []


async def test_inner_timeout_error_is_not_reported_as_session_timeout(patched):
    async def run(agent, cb):
        raise TimeoutError("CDP command timed out")

    patched(run)
    res = await BrowserAgent(AgentConfig(timeout_s=600)).run("t")
    assert res.status == "error"
    assert res.errors == ["CDP command timed out"] and "Session timeout" not in "".join(res.errors)


async def test_real_timeout_still_reported(patched):
    async def run(agent, cb):
        await asyncio.sleep(10)

    patched(run)
    res = await BrowserAgent(AgentConfig(timeout_s=0.2)).run("t")
    assert res.status == "timeout" and res.errors[-1] == "Session timeout (0.2s)"


async def test_timeout_covers_preflight(patched):
    async def slow_preflight():
        await asyncio.sleep(10)

    patched(lambda a, cb: asyncio.sleep(0))
    res = await asyncio.wait_for(
        BrowserAgent(AgentConfig(timeout_s=0.2), preflight=slow_preflight).run("t"), 3)
    assert res.status == "timeout"


async def test_timeout_clock_paused_while_paused(patched):
    release = asyncio.Event()

    async def run(agent, cb):
        await release.wait()
        return agent.history

    patched(run)
    ba = BrowserAgent(AgentConfig(timeout_s=0.5))
    t = asyncio.create_task(ba.run("t"))
    await asyncio.sleep(0.15)
    ba.pause()
    await asyncio.sleep(0.9)  # longer than timeout_s, but the clock is paused
    assert not t.done()
    ba.resume()
    release.set()
    res = await asyncio.wait_for(t, 3)
    assert res.status == "success"


async def test_cdp_connection_error_is_mapped_and_url_redacted(patched):
    async def run(agent, cb):
        raise ConnectionError("All connection attempts failed")

    patched(run)
    cfg = AgentConfig(browser=BrowserConfig(cdp_url="http://127.0.0.1:9222/?token=SECRET123"))
    res = await BrowserAgent(cfg).run("t")
    assert res.status == "error"
    assert res.errors == ["Could not connect to Chrome at http://127.0.0.1:9222/. "
                          "Is Chrome running with --remote-debugging-port?"]


async def test_cdp_connection_error_in_step_result_is_mapped(patched):
    async def run(agent, cb):
        agent.actions = [{"click": {"index": 1}}]
        agent.history = SimpleNamespace(
            number_of_steps=lambda: 1, model_actions=lambda: agent.actions, final_result=lambda: None,
            is_successful=lambda: False, urls=list, screenshots=list, has_errors=lambda: True)
        agent.state.last_result = [SimpleNamespace(error="All connection attempts failed")]
        await cb(agent)
        return agent.history

    patched(run)
    cfg = AgentConfig(browser=BrowserConfig(cdp_url="http://127.0.0.1:9222"))
    res = await BrowserAgent(cfg).run("t")
    assert res.status == "error" and res.errors[0].startswith("Could not connect to Chrome at http://127.0.0.1:9222")


async def test_page_connection_error_not_mapped_without_cdp(patched):
    async def run(agent, cb):
        raise ConnectionError("All connection attempts failed")

    patched(run)
    res = await BrowserAgent(AgentConfig()).run("t")
    assert res.errors == ["All connection attempts failed"]


async def test_secrets_redacted_from_errors_events_and_logs(patched, caplog):
    key = "sk-test-0123456789abcdef"

    async def run(agent, cb):
        agent.actions = [{"click": {"index": 1}}]
        agent.history = SimpleNamespace(
            number_of_steps=lambda: 1, model_actions=lambda: agent.actions, final_result=lambda: None,
            is_successful=lambda: False, urls=list, screenshots=list, has_errors=lambda: True)
        agent.state.last_result = [SimpleNamespace(error=f"auth failed for {key}")]
        await cb(agent)
        raise RuntimeError(f"401 invalid key {key}")

    patched(run)
    events = []
    cfg = AgentConfig(model=ModelConfig(provider="anthropic", api_key=SecretStr(key)))
    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        res = await BrowserAgent(cfg, sinks=[CallbackSink(events.append)]).run("t")
    blob = repr(res.to_dict()) + repr(events) + caplog.text
    assert key not in blob and "***" in blob


async def test_hung_sink_is_dropped(patched, monkeypatch):
    monkeypatch.setattr(runner_mod, "SINK_TIMEOUT_S", 0.1)
    patched(lambda a, cb: asyncio.sleep(0, result=a.history))

    async def hung(event):
        await asyncio.sleep(3600)

    res = await asyncio.wait_for(BrowserAgent(AgentConfig(), sinks=[hung]).run("t"), 5)
    assert res.status in ("success", "failed")


async def test_hung_browser_kill_is_bounded(patched, monkeypatch):
    monkeypatch.setattr(runner_mod, "TEARDOWN_TIMEOUT_S", 0.2)
    patched.box["browser"] = FakeBrowser(hang_kill=True)
    patched(lambda a, cb: asyncio.sleep(0, result=a.history))
    res = await asyncio.wait_for(BrowserAgent(AgentConfig()).run("t"), 5)
    assert res.status == "success"


async def test_stop_during_preflight_builds_nothing(monkeypatch):
    built = []
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: built.append("llm"))
    monkeypatch.setattr(runner_mod, "build_browser_session", lambda b, s: built.append("browser"))
    monkeypatch.setattr(runner_mod, "Agent", lambda **kw: built.append("agent"))
    started = asyncio.Event()

    async def preflight():
        started.set()
        await asyncio.sleep(0.3)

    ba = BrowserAgent(AgentConfig(), preflight=preflight)
    t = asyncio.create_task(ba.run("t"))
    await started.wait()
    ba.stop()
    res = await asyncio.wait_for(t, 3)
    assert res.status == "stopped" and built == []


async def test_stop_before_preflight_returns_builds_nothing(monkeypatch):
    built = []
    monkeypatch.setattr(runner_mod, "build_llm", lambda cfg: built.append("llm"))
    monkeypatch.setattr(runner_mod, "Agent", lambda **kw: built.append("agent"))
    ba = BrowserAgent(AgentConfig())

    async def preflight():
        ba.stop()  # swallowed by a preflight that ignores cancellation-free completion

    ba.preflight = preflight
    res = await ba.run("t")
    assert res.status == "stopped" and built == []


async def test_calculate_cost_follows_config(patched, monkeypatch):
    seen = {}

    class A:
        def __init__(self, **kw):
            seen.update(kw)
            self.state = SimpleNamespace(stopped=False, last_result=[])
            self.history = OkHistory()

        async def run(self, max_steps, on_step_end):
            return self.history

    monkeypatch.setattr(runner_mod, "Agent", A)
    await BrowserAgent(AgentConfig(calculate_cost=False)).run("t")
    assert seen["calculate_cost"] is False
