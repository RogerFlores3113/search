"""Regression tests for the PR 3 review fixes."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from local_browser_agent.browser import LOCAL_HOST_PATTERNS, build_browser_profile, is_local_host
from local_browser_agent.config import AgentConfig, BrowserConfig, SafetyPolicy
from local_browser_agent.log import configure_logging
from local_browser_agent.safety import ActionRequest, GuardedTools, _host_is_local, navigation_denial


class _Action:
    def __init__(self, name, **params):
        self._d = {name: params}

    def model_dump(self, exclude_unset=True):
        return self._d


def _tools(**kw):
    return GuardedTools(**kw)


# 1 -------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", [r"https:\paypal.com", r"https:/\paypal.com", "https:///paypal.com",
                                 "paypal.com/login", "//paypal.com/"])
async def test_malformed_scheme_blocked_domain(url):
    t = _tools()
    res = await t.act(_Action("navigate", url=url), SimpleNamespace())
    assert res.error and "blocked domain" in res.error
    assert t.blocked_actions


@pytest.mark.parametrize("url", ["https://", "http:///", "https:///?x=1"])
def test_no_host_denied(url):
    assert navigation_denial(url, True)


def test_schemeless_public_ok():
    assert navigation_denial("example.com/path") is None


# 2 -------------------------------------------------------------------------------------
class _Session:
    def __init__(self, node, url="https://shop.example.com/item", live="fail"):
        self.node, self.url, self.live = node, url, live

    async def get_current_page_url(self):
        return self.url

    async def get_element_by_index(self, i):
        return self.node

    async def cdp_client_for_node(self, node):
        raise RuntimeError("detached")


def _node(tag, label="Learn more", **attrs):
    return SimpleNamespace(node_name=tag, attributes=attrs, ax_node=None, node_value="", parent_node=None,
                           backend_node_id=5, get_all_children_text=lambda: label)


async def _classify(node, url="https://shop.example.com/item"):
    t = _tools(approval=None)
    return await t._lba_classify_click("click", {"index": 1}, _Session(node, url))


async def test_failed_live_read_gates_buttons_and_links():
    for n in (_node("button"), _node("a", href="/x"), _node("input", type="submit", value="Go"),
              _node("div", role="button")):
        assert await _classify(n) is not None, n.node_name


async def test_failed_live_read_gates_on_commerce_url():
    req = await _classify(_node("div", label="Accept"), "https://shop.example.com/checkout")
    assert req is not None


async def test_failed_live_read_passes_checkbox():
    assert await _classify(_node("input", label="Remember me", type="checkbox")) is None
    assert await _classify(_node("input", label="Name", type="text")) is None


async def test_unavailable_warns_once(caplog):
    class S(_Session):
        cdp_client_for_node = None

    t = _tools()
    s = S(_node("button", label="Learn more"))
    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        for _ in range(3):
            await t._lba_classify_click("click", {"index": 1}, s)
    assert sum("re-read is unavailable" in r.message for r in caplog.records) == 1


# 3 / 4 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["printer.local", "a.internal", "nas.lan", "x.home.arpa", "h.localdomain",
                                  "wiki.intranet", "intranet", "printer"])
def test_local_names_denied(host):
    assert navigation_denial(f"http://{host}/") is not None
    assert navigation_denial(f"http://{host}/", True) is None
    assert _host_is_local(host)
    assert is_local_host(host)


def test_nat64_private():
    assert _host_is_local("64:ff9b::7f00:1")
    assert _host_is_local("64:ff9b::a00:1")
    assert not _host_is_local("64:ff9b::808:808")


@pytest.mark.parametrize("url", ["http://8.8.8.8/", "http://[::1]/", "http://2130706433/", "http://10.0.0.1:8080/"])
def test_ip_literal_message(url):
    msg = navigation_denial(url)
    assert msg and "IP-address URLs" in msg and "LBA_ALLOW_LOCAL_NETWORK=1" in msg
    assert navigation_denial(url, True) is None or "IP-address" not in navigation_denial(url, True)


def test_profile_patterns_cover_suffixes(monkeypatch):
    for s in ("*.local", "*.internal", "*.lan", "*.home.arpa", "*.localdomain", "*.intranet"):
        assert s in LOCAL_HOST_PATTERNS
    p = build_browser_profile(BrowserConfig(cdp_url="http://127.0.0.1:9222"), SafetyPolicy())
    assert "*.lan" in p.prohibited_domains
    p = build_browser_profile(BrowserConfig(cdp_url="http://127.0.0.1:9222"), SafetyPolicy(allow_local_network=True))
    assert "*.lan" not in p.prohibited_domains


# 5 -------------------------------------------------------------------------------------
def _req():
    return ActionRequest(action_name="click", params={}, element_label="Buy", url="https://x.com", reason="r")


def test_approval_timeout_config():
    assert SafetyPolicy().approval_timeout_s == 120.0
    assert SafetyPolicy(approval_timeout_s=None).approval_timeout_s is None
    with pytest.raises(ValueError):
        SafetyPolicy(approval_timeout_s=-1)
    cfg = AgentConfig.from_env(env={"LBA_APPROVAL_TIMEOUT_S": "7.5"})
    assert cfg.safety.approval_timeout_s == 7.5
    with pytest.raises(ValueError):
        AgentConfig.from_env(env={"LBA_APPROVAL_TIMEOUT_S": "abc"})


async def test_own_timeout_vs_callback_timeout():
    async def slow(req):
        await asyncio.sleep(10)

    async def raises(req):
        raise TimeoutError("inner")

    t = _tools(approval=slow, approval_timeout_s=0.05)
    res = await t._lba_ask(_req())
    assert "timed out" in res.error

    log: list[str] = []
    t = _tools(approval=raises, approval_timeout_s=5, blocked_log=log)
    res = await t._lba_ask(_req())
    assert "timed out" not in res.error and "Blocked by safety policy" in res.error
    assert log


async def test_zero_timeout_waits_and_approves():
    async def later(req):
        await asyncio.sleep(0.05)
        return True

    assert await _tools(approval=later, approval_timeout_s=0)._lba_ask(_req()) is None


# 7 -------------------------------------------------------------------------------------
async def test_cancel_during_approval_recorded():
    async def never(req):
        await asyncio.sleep(100)

    log: list[str] = []
    t = _tools(approval=never, approval_timeout_s=None, blocked_log=log)
    task = asyncio.ensure_future(t._lba_ask(_req()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert log and "stopped while awaiting approval" in log[0]


# 6 -------------------------------------------------------------------------------------
@pytest.mark.parametrize("tp,passes", [("info", True), ("off", False)])
def test_third_party_level_applies(tp, passes, capsys):
    configure_logging("warning", third_party=tp)
    logging.getLogger("browser_use.agent.service").info("hello-from-bu")
    err = capsys.readouterr().err
    assert ("hello-from-bu" in err) is passes
