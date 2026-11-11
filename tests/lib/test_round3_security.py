"""Round-3 security fixes: dead blocklist at runtime, host canonicalisation, link targets, label folding."""
from urllib.parse import urlsplit

import pytest
from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

from local_browser_agent import BrowserConfig, GuardedTools, SafetyPolicy
from local_browser_agent.browser import build_browser_profile, build_browser_session, start_url_problem
from local_browser_agent.safety import (
    canonical_host,
    host_is_blocked,
    is_commerce_label,
    is_commerce_url,
    navigation_denial,
    normalize_allowed_domain,
)
from tests.lib.test_gate_round2 import FocusSession, LiveSession
from tests.lib.test_safety_gate import Act, Node, Session, base_act, run  # noqa: F401


def _watchdog(session):
    return SecurityWatchdog.model_construct(browser_session=session)


def _session(**safety):
    return build_browser_session(BrowserConfig(executable_path="/bin/true"), SafetyPolicy(**safety))


# ---- B1: blocklist survives BrowserSession ----------------------------------------------------
BLOCKED_URLS = [
    "https://login.chase.com/", "https://secure.paypal.com/", "https://chase.com/", "https://www.chase.com/",
    "https://a.b.irs.gov/", "https://chase.com./", "https://x.chase.com./", "chrome://settings/passwords",
    "chrome-extension://abc/page.html", "https://foo.localhost/", "http://printer.local/", "http://localhost/",
]


def test_default_policy_stays_a_list_under_threshold():
    prof = build_browser_profile(BrowserConfig(executable_path="/bin/true"), SafetyPolicy())
    assert isinstance(prof.prohibited_domains, list) and len(prof.prohibited_domains) < 100


@pytest.mark.parametrize("extra", [[], [f"d{i}.example" for i in range(150)]])
def test_session_watchdog_blocks_wildcards(extra):
    s = _session(blocked_domains=extra)
    assert isinstance(s.browser_profile.prohibited_domains, list)
    w = _watchdog(s)
    for url in BLOCKED_URLS:
        assert w._is_url_allowed(url) is False, url
    assert w._is_url_allowed("https://example.com/") is True
    if extra:
        assert w._is_url_allowed("https://x.d7.example/") is False


def test_session_large_allow_list_keeps_wildcards():
    allowed = [f"*.site{i}.example" for i in range(120)]
    s = _session(allowed_domains=allowed)
    assert isinstance(s.browser_profile.allowed_domains, list)
    w = _watchdog(s)
    assert w._is_url_allowed("https://a.site5.example/") is True
    assert w._is_url_allowed("https://other.example/") is False


def test_profile_permissions_and_downloads_off_by_default():
    p = build_browser_profile(BrowserConfig(executable_path="/bin/true"), SafetyPolicy())
    assert p.permissions == [] and p.accept_downloads is False and p.auto_download_pdfs is False
    p = build_browser_profile(BrowserConfig(executable_path="/bin/true", allow_downloads=True), SafetyPolicy())
    assert p.accept_downloads is True


# ---- B2: host canonicalisation -----------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://pay%70al.com/", "https://ｐａｙｐａｌ.com/", "https://pay​pal.com/", "https://pay­pal.com/",
    "https://paypal。com/", "https://paypal．com/", "https://paypal｡com/", "https://paypal.com./",
    "https://secure.pay%70al.com/", "https://PAYPAL.COM/",
])
def test_obfuscated_blocked_hosts_denied(url):
    assert host_is_blocked(urlsplit(url).hostname, {"paypal.com"}), url


@pytest.mark.parametrize("url", [
    "http://%31%32%37%2e0.0.1/", "http://127.0.0.1​/", "http://１２７.０.０.１/", "http://127。0。0。1/",
    "http://127.0.0.1./", "http://[::1]/", "http://0x7f.1/", "https://foo%2elocalhost/",
])
def test_obfuscated_local_hosts_denied(url):
    assert navigation_denial(url) is not None, url


def test_canonical_host_cases():
    assert canonical_host("Bücher.example.") == "xn--bcher-kva.example"
    assert canonical_host("a..b") is None
    assert canonical_host("a%2fb.com") is None
    assert canonical_host("exa mple.com") is None
    assert canonical_host("[::1]") == "::1"
    assert host_is_blocked("a..b", {"paypal.com"}) is True


async def test_tool_denies_obfuscated_blocked_navigation(base_act):
    for url in ("https://pay%70al.com/", "https://ｐａｙｐａｌ.com", "https://pay​pal.com",
                "http://%31%32%37%2e0.0.1/"):
        t, r = await run(Act(navigate={"url": url}), Session({}))
        assert r.error and not base_act, url


def test_start_url_problem_canonicalises():
    assert start_url_problem("https://pay%70al.com/", SafetyPolicy())
    assert start_url_problem("https://example.com/", SafetyPolicy()) is None


def test_commerce_url_uses_canonical_host():
    assert is_commerce_url("https://checkout.sh%6fp.example/x")


# ---- B2b: clicked href / form action ----------------------------------------------------------
@pytest.mark.parametrize("href", [
    "https://secure.paypal.com/pay", "https://login.chase.com/", "chrome://settings", "chrome://settings/passwords",
    "view-source:https://example.com", "//secure.paypal.com/x", "http://127.0.0.1:8000/admin",
    "https://pay%70al.com/", "file:///etc/passwd", "http://printer.local/", "devtools://devtools/bundled/x.html",
])
async def test_click_on_forbidden_link_denied(base_act, href):
    t, r = await run(Act(click={"index": 1}), Session({1: Node("a", {"href": href}, "Read more")}))
    assert r.error and not base_act and t.blocked_actions, href


async def test_click_on_form_action_denied(base_act):
    form = Node("form", {"action": "https://secure.paypal.com/"})
    btn = Node("button", {"type": "submit"}, "Continue", parent=form)
    t, r = await run(Act(click={"index": 1}), Session({1: btn}))
    assert r.error and not base_act


@pytest.mark.parametrize("href", ["/about", "https://example.org/x", "#top", "javascript:void(0)", "mailto:a@b.c", ""])
async def test_click_on_harmless_link_allowed(base_act, href):
    t, r = await run(Act(click={"index": 1}), Session({1: Node("a", {"href": href}, "Read more")}))
    assert r.extracted_content == "ok", href


async def test_click_local_link_allowed_with_local_network(base_act):
    t, r = await run(Act(click={"index": 1}), Session({1: Node("a", {"href": "http://127.0.0.1:8000/"}, "Docs")}),
                     allow_local_network=True)
    assert r.extracted_content == "ok"


# ---- B3: per-part label classification ---------------------------------------------------------
@pytest.mark.parametrize("name,title", [
    ("Buy", "help details"), ("Pay", "help details"), ("Donate", "tax receipt info"),
    ("Subscribe", "terms and conditions faq"), ("Buy now", "Help"), ("Kaufen", "help details"), ("Buy", "faq details"),
])
async def test_info_title_does_not_hide_cta(base_act, name, title):
    n = Node("button", {"title": title}, name)
    t, r = await run(Act(click={"index": 1}), Session({1: n}, url="https://x.com/dp/1"))
    assert r.error and not base_act, (name, title)


async def test_info_only_button_still_clickable(base_act):
    n = Node("button", {"title": "help details"}, "Learn more")
    assert (await run(Act(click={"index": 1}), Session({1: n}, url="https://x.com/dp/1")))[1].extracted_content == "ok"


# ---- B4: Enter / Space on a focused control ----------------------------------------------------
class DeadFocusSession(Session):
    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        raise RuntimeError("cdp gone")


BUY = {"tag": "button", "attrs": {}, "text": "Buy now", "form": None}


@pytest.mark.parametrize("keys", ["Enter", "Control+Enter", "\n", "NumpadEnter", "Space", " "])
async def test_keys_on_focused_buy_gated(base_act, keys):
    s = FocusSession(BUY, url="https://x.com/dp/1")
    assert (await run(Act(send_keys={"keys": keys}), s))[1].error and not base_act


async def test_enter_in_search_box_allowed(base_act):
    box = {"tag": "input", "attrs": {"type": "search"}, "text": "", "form": {"action": "/search"}}
    r = (await run(Act(send_keys={"keys": "Enter"}), FocusSession(box, url="https://x.com/")))[1]
    assert r.extracted_content == "ok"


async def test_failed_focus_read_fails_closed_unless_text_field_known(base_act):
    s = DeadFocusSession({1: Node("input", {"type": "text"}, "")}, url="https://x.com/dp/1")
    assert (await run(Act(send_keys={"keys": "Enter"}), s))[1].error
    assert (await run(Act(send_keys={"keys": "Space"}), s))[1].error
    # type into a field (input action), then Enter: allowed even though the live read is dead
    t = GuardedTools()
    assert not (await t.act(Act(input={"index": 1, "text": "shoes"}), s)).error
    assert not (await t.act(Act(send_keys={"keys": "Enter"}), s)).error
    # a click on a button moves focus off the field again
    other = DeadFocusSession({2: Node("button", {}, "Next")}, url="https://x.com/dp/1")
    await t.act(Act(click={"index": 2}), other)
    assert (await t.act(Act(send_keys={"keys": "Enter"}), s)).error


async def test_clickable_div_failed_live_read_gated(base_act):
    div = Node("div", {"onclick": "go()"}, "Learn more")
    div.backend_node_id = 7
    assert (await run(Act(click={"index": 1}), LiveSession({1: div}, {}, fail=True, url="https://x.com/")))[1].error
    plain = Node("div", {}, "Learn more")
    plain.backend_node_id = 7
    ok = await run(Act(click={"index": 1}), LiveSession({1: plain}, {}, fail=True, url="https://x.com/"))
    assert ok[1].extracted_content == "ok"
    assert (await run(Act(click={"index": 1}), LiveSession({1: plain}, {}, fail=True, url="https://x.com/checkout")))[1].error


# ---- minor: label folding ---------------------------------------------------------------------
@pytest.mark.parametrize("label", [
    "SATIN AL", "SİPARİŞ VER", "ŞİMDİ ÖDE", "satın al", "Páy now", "Pa̶y now", "Cómprar", "B u y n o w",
    "B u y   n o w", "Buy⠀now", "Buyㅤnow", "Buyᅟnow", "Buy now", "Complete your purchase",
    "Place my order", "Pay invoice", "Submit payment", "Order & Pay", "Proceed to Buy (2 items)", "1-Click Buy",
    "Upgrade now", "Place bid", "P a y", "Ｐａｙ ｎｏｗ",
])
def test_more_labels_gated(label):
    assert is_commerce_label(label), label


@pytest.mark.parametrize("label", [
    "Add to cart", "Order history", "Subscribe to newsletter", "Payment history", "Repay", "Read more",
    "Upgrade guide", "Bid history", "How to pay", "A B C", "Continue shopping",
])
def test_more_labels_clean(label):
    assert not is_commerce_label(label), label


# ---- minor: URL shapes ------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://shop.example/#/checkout", "https://shop.example/app#/pay", "https://shop.example/app#!/payment",
    "https://shop.example/#/payment?id=1", "https://shop.example/payments/new", "https://shop.example/subscribe/pro",
    "https://shop.example/billing/update", "https://shop.example/make-payment",
])
def test_more_urls_gated(url):
    assert is_commerce_url(url), url


@pytest.mark.parametrize("url", [
    "https://shop.example/#section", "https://shop.example/#/about", "https://shop.example/help/payments/new",
    "https://shop.example/blog/make-payment-easy-tips",
])
def test_more_urls_clean(url):
    assert not is_commerce_url(url), url


# ---- minor: public suffixes -------------------------------------------------------------------
@pytest.mark.parametrize("entry", ["*.co.uk", "co.uk", "*.com.au", "https://co.jp/", "*.gov.uk", "*.CO.UK."])
def test_public_suffix_rejected(entry):
    with pytest.raises(ValueError):
        normalize_allowed_domain(entry)
    with pytest.raises(ValueError):
        SafetyPolicy(allowed_domains=[entry])


def test_specific_multipart_site_allowed():
    assert normalize_allowed_domain("*.example.co.uk") == "*.example.co.uk"
    assert normalize_allowed_domain("Bücher.de") == "xn--bcher-kva.de"


@pytest.mark.parametrize("url", [
    "http://%31%32%37%2e0.0.1/",
    "http://127.0.0.1．/",
    "https://ｐａｙｐａｌ.com/",
    "https://pay​pal.com/",
])
def test_start_url_uses_canonical_host(url):
    from local_browser_agent.browser import start_url_problem
    from local_browser_agent.config import SafetyPolicy
    assert start_url_problem(url, SafetyPolicy()) is not None
