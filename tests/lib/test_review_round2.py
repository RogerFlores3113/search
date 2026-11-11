"""Round-2 review fixes: allow-list normalisation, blocked navigation, URL gating shape,
evaluate denial text, Cloudflare interstitials and browser channel discovery."""
from __future__ import annotations

import pytest
from browser_use.agent.views import ActionResult
from pydantic import ValidationError

import local_browser_agent.chrome as chrome_mod
from local_browser_agent.browser import build_browser_profile
from local_browser_agent.captcha import looks_like_captcha
from local_browser_agent.chrome import find_chrome
from local_browser_agent.config import BrowserConfig, SafetyPolicy
from local_browser_agent.mcp_server import restrict_domains
from local_browser_agent.safety import GuardedTools, is_commerce_url, normalize_allowed_domain
from tests.lib.test_safety_gate import Act, Session, run  # noqa: F401  (fixtures reused below)
from tests.lib.test_safety_gate import base_act  # noqa: F401

# ---- allow-list normalisation ---------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("Example.COM", "example.com"), ("https://example.com/path?q=1", "example.com"),
    ("example.com:443", "example.com"), ("*.example.com", "*.example.com"),
    ("https://*.example.com:8443/x", "*.example.com"), ("example.com.", "example.com"),
    ("localhost", "localhost"),
])
def test_normalize_allowed_ok(raw, want):
    assert normalize_allowed_domain(raw) == want


@pytest.mark.parametrize("raw", ["*", "*.com", "paypal.*", "*paypal.com", "pay*.com", "a.*.com", "", "user@x.com",
                                 "https://*", "ex ample.com", "http*://x.com"])
def test_normalize_allowed_rejects(raw):
    with pytest.raises(ValueError):
        normalize_allowed_domain(raw)


@pytest.mark.parametrize("raw", ["*", "*.com", "paypal.*"])
def test_policy_rejects_globs(raw):
    with pytest.raises(ValidationError):
        SafetyPolicy(allowed_domains=[raw])


@pytest.mark.parametrize("raw", ["https://paypal.com", "paypal.com:443", "*.paypal.com", "www.paypal.com/x"])
def test_policy_drops_blocked_variants(raw):
    p = SafetyPolicy(allowed_domains=["ok.com", raw])
    assert p.allowed_domains == ["ok.com"]
    with pytest.raises(ValueError):
        SafetyPolicy(allowed_domains=[raw])


def test_policy_wildcard_covering_blocked_subdomain_dropped():
    p = SafetyPolicy(blocked_domains=["login.corp.com"], allowed_domains=["ok.com", "*.corp.com", "corp.com"])
    assert p.allowed_domains == ["ok.com", "corp.com"] or p.allowed_domains == ["ok.com"]
    assert "*.corp.com" not in p.allowed_domains


def test_policy_model_copy_renormalises():
    p = SafetyPolicy().model_copy(update={"allowed_domains": ["https://ok.com/", "paypal.com"]})
    assert p.allowed_domains == ["ok.com"]
    with pytest.raises(ValueError):
        SafetyPolicy().model_copy(update={"allowed_domains": ["*"]})


def test_restrict_domains_normalises_and_rejects_globs():
    assert restrict_domains(None, ["https://a.com/x", "b.com:80"]) == ["a.com", "b.com"]
    for bad in ("*", "*.com"):
        with pytest.raises(ValueError):
            restrict_domains(None, [bad])
        with pytest.raises(ValueError):
            restrict_domains(["a.com"], [bad])
    assert restrict_domains(["*.a.com"], ["https://x.a.com/p", "evil.com"]) == ["x.a.com"]


def test_profile_never_allows_blocked(monkeypatch):
    monkeypatch.setattr("local_browser_agent.browser.find_chrome", lambda channel="chrome": "/usr/bin/fake-chrome")
    # model_construct skips validation; browser.py re-checks.
    safety = SafetyPolicy.model_construct(allowed_domains=["ok.com", "paypal.com", "*.paypal.com"])
    prof = build_browser_profile(BrowserConfig(), safety)
    assert list(prof.allowed_domains) == ["ok.com"]
    with pytest.raises(ValueError):
        build_browser_profile(BrowserConfig(), SafetyPolicy.model_construct(allowed_domains=["paypal.com"]))
    with pytest.raises(ValueError):
        build_browser_profile(BrowserConfig(), SafetyPolicy.model_construct(allowed_domains=["*"]))


def test_profile_does_not_pass_channel_with_executable_path(monkeypatch):
    monkeypatch.setattr("local_browser_agent.browser.find_chrome", lambda channel="chrome": "/usr/bin/fake-chrome")
    prof = build_browser_profile(BrowserConfig(channel="chrome"), SafetyPolicy())
    assert prof.channel is None and str(prof.executable_path).endswith("fake-chrome")


# ---- GuardedTools: blocked navigation -------------------------------------------------

@pytest.mark.parametrize("url", ["https://paypal.com/signin", "https://www.PayPal.com./x", "https://a.b.chase.com/"])
async def test_blocked_navigation_denied(base_act, url):
    approvals = []

    async def yes(req):
        approvals.append(req)
        return True

    for act in (Act(navigate={"url": url}), Act(go_to_url={"url": url}), Act(navigate={"url": url, "new_tab": True})):
        t, r = await run(act, Session({}), approval=yes)
        assert r.error and "blocked domain" in r.error and t.blocked_actions
    assert not base_act and not approvals  # no approval can lift a blocked domain


async def test_blocked_navigation_honours_custom_set_and_allows_others(base_act):
    t, r = await run(Act(navigate={"url": "https://evil.example/x"}), Session({}), blocked_domains=["evil.example"])
    assert r.error
    t, r = await run(Act(navigate={"url": "https://notpaypal.com/"}), Session({}))
    assert r.extracted_content == "ok"
    t, r = await run(Act(navigate={"url": "https://news.example/"}), Session({}))
    assert r.extracted_content == "ok"


# ---- evaluate denial text -------------------------------------------------------------

async def test_evaluate_denial_does_not_tell_agent_to_give_up(base_act):
    t, r = await run(Act(evaluate={"code": "1+1"}), Session({}))
    assert "LBA_ALLOW_EVALUATE=true" in r.error and "continue the task" in r.error
    for bad in ("success=False", "purchase", "Do not retry"):
        assert bad not in r.error

    async def no(req):
        return False

    t, r = await run(Act(evaluate={"code": "1+1"}), Session({}), approval=no)
    assert "continue the task" in r.error and "success=False" not in r.error
    assert t.blocked_actions  # still recorded


# ---- commerce URL shape ---------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://x.example/wiki/Donation", "https://x.example/wiki/Payment", "https://x.example/help/payment-methods",
    "https://x.example/blog/billing-tips", "https://x.example/pricing", "https://x.example/subscriptions",
    "https://x.example/wiki/Pay", "https://x.example/articles/donate-to-charity", "https://x.example/payments-faq",
])
def test_informational_urls_not_gated(url):
    assert not is_commerce_url(url), url


@pytest.mark.parametrize("url", [
    "https://x.example/checkout", "https://x.example/cart/checkout", "https://x.example/cart/confirm",
    "https://x.example/payment/confirm", "https://x.example/payment/process", "https://x.example/payment",
    "https://x.example/pay", "https://x.example/pay/12345", "https://x.example/order/place",
    "https://x.example/order/review", "https://x.example/subscribe/confirm", "https://x.example/donate",
    "https://x.example/en/payment/submit", "https://checkout.x.example/anything",
])
def test_transactional_urls_gated(url):
    assert is_commerce_url(url), url


def test_broad_matching_still_available_for_form_actions():
    assert is_commerce_url("/wiki/Donation", broad=True)
    assert not is_commerce_url("/wiki/Donation")


async def test_wiki_page_does_not_gate_clicks_or_enter(base_act):
    from tests.lib.test_safety_gate import Node
    s = Session({1: Node("a", {"href": "/wiki/History"}, "History"), 2: Node("button", {}, "")},
                url="https://x.example/wiki/Donation")
    assert (await run(Act(click={"index": 1}), s))[1].extracted_content == "ok"
    assert (await run(Act(click={"index": 2}), s))[1].extracted_content == "ok"
    assert (await run(Act(send_keys={"keys": "Enter"}), s))[1].extracted_content == "ok"
    assert (await run(Act(navigate={"url": "https://x.example/wiki/Payment"}), s))[1].extracted_content == "ok"


async def test_form_action_still_broadly_gated(base_act):
    from tests.lib.test_safety_gate import Node
    form = Node("form", {"action": "/donation/submit-form"})
    s = Session({1: Node("input", {"type": "submit", "value": "Go"}, parent=form)})
    assert (await run(Act(click={"index": 1}), s))[1].error


# ---- captcha --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Just a moment...", "Checking your browser before accessing example.com", "cf-challenge-running",
    "Attention Required! | Cloudflare",
])
def test_cloudflare_interstitial_detected(text):
    assert looks_like_captcha(text)


@pytest.mark.parametrize("text", ["Access Denied", "access denied by cloudflare", "challenge", "TLS challenge failed"])
def test_generic_words_not_captcha(text):
    assert not looks_like_captcha(text)


# ---- find_chrome channels -------------------------------------------------------------

def _exists_only(monkeypatch, *paths):
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: p in paths)


def test_find_chrome_macos_user_applications(monkeypatch):
    monkeypatch.setattr(chrome_mod.sys, "platform", "darwin")
    monkeypatch.setattr(chrome_mod.os.path, "expanduser", lambda p: p.replace("~", "/Users/me"))
    user = "/Users/me/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    _exists_only(monkeypatch, user)
    assert find_chrome() == user
    _exists_only(monkeypatch)
    assert find_chrome() is None


@pytest.mark.parametrize("channel,app", [
    ("chrome-beta", "Google Chrome Beta"), ("chrome-dev", "Google Chrome Dev"),
    ("chrome-canary", "Google Chrome Canary"), ("msedge", "Microsoft Edge"),
])
def test_find_chrome_macos_channels(monkeypatch, channel, app):
    monkeypatch.setattr(chrome_mod.sys, "platform", "darwin")
    path = f"/Applications/{app}.app/Contents/MacOS/{app}"
    _exists_only(monkeypatch, path, chrome_mod.CHROME_PATH_MACOS)
    assert find_chrome(channel) == path
    assert find_chrome("chrome") == chrome_mod.CHROME_PATH_MACOS


@pytest.mark.parametrize("channel,binary", [
    ("chrome-beta", "google-chrome-beta"), ("chrome-dev", "google-chrome-unstable"),
    ("msedge", "microsoft-edge"),
])
def test_find_chrome_linux_channels(monkeypatch, channel, binary):
    monkeypatch.setattr(chrome_mod.sys, "platform", "linux")
    _exists_only(monkeypatch)  # hermetic: ignore browsers installed on the CI runner
    monkeypatch.setattr(chrome_mod.shutil, "which", lambda n: f"/usr/bin/{n}" if n in (binary, "google-chrome") else None)
    assert find_chrome(channel) == f"/usr/bin/{binary}"
    assert find_chrome() == "/usr/bin/google-chrome"
    monkeypatch.setattr(chrome_mod.shutil, "which", lambda n: "/usr/bin/google-chrome" if n == "google-chrome" else None)
    assert find_chrome(channel) is None  # no silent fallback to a different channel


@pytest.mark.parametrize("channel,parts", [
    ("chrome-beta", ("Google", "Chrome Beta", "Application", "chrome.exe")),
    ("chrome-canary", ("Google", "Chrome SxS", "Application", "chrome.exe")),
    ("msedge", ("Microsoft", "Edge", "Application", "msedge.exe")),
    ("chrome", ("Google", "Chrome", "Application", "chrome.exe")),
])
def test_find_chrome_windows_channels(monkeypatch, channel, parts):
    monkeypatch.setattr(chrome_mod.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMFILES", "PF")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setattr(chrome_mod.os.path, "exists", lambda p: True)
    assert find_chrome(channel) == chrome_mod.os.path.join("PF", *parts)
