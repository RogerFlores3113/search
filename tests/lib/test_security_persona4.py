"""Security persona round: ancestor-aware commerce gating, label evasion, URL gaps, blocklist, uploads."""
from __future__ import annotations

import logging
from types import SimpleNamespace as NS

import pytest
from browser_use.browser.watchdogs.security_watchdog import SecurityWatchdog

from local_browser_agent import BrowserConfig, GuardedTools, SafetyPolicy
from local_browser_agent.browser import build_browser_session
from local_browser_agent.safety import (
    PUBLIC_SUFFIXES,
    SAFETY_DEFAULTS,
    _node_from_live,
    element_risk,
    host_is_blocked,
    is_commerce_label,
    is_commerce_url,
    normalize_allowed_domain,
)


def node(tag="button", attrs=None, text="", parent=None, ax=None):
    return NS(node_name=tag, attributes=attrs or {}, ax_node=NS(name=ax) if ax else None, node_value="",
              parent_node=parent, get_all_children_text=lambda: text, backend_node_id=None)


class Sess:
    def __init__(self, n, url="https://shop.com/product"):
        self.n, self.url = n, url

    async def get_current_page_url(self):
        return self.url

    async def get_element_by_index(self, i):
        return self.n

    async def get_dom_element_at_coordinates(self, x, y):
        return self.n


async def classify(n, url="https://shop.com/product", name="click", params=None):
    r = await GuardedTools()._lba_classify(name, params or {"index": 1}, Sess(n, url))
    return r.reason if r else None


# ---- MAJOR 1: ancestors ---------------------------------------------------------------------------
def _span_in_checkout_link():
    return node("span", text="Continue", parent=node("a", {"href": "/checkout"}, text="Continue"))


def _span_in_place_order_button():
    return node("span", text="", parent=node("button", {"type": "submit"}, text="Place order"))


def _img_in_submit_in_checkout_form():
    return node("img", {"alt": ""}, parent=node("button", {"type": "submit"}, text="",
                                                  parent=node("form", {"action": "/checkout/confirm"})))


def _two_up_link():
    return node("span", text="Go", parent=node("div", {"onclick": "x"},
                                               parent=node("a", {"href": "https://shop.com/checkout"})))


def _deep_link(levels):
    n = node("img")
    cur = n
    for _ in range(levels):
        cur.parent_node = node("div")
        cur = cur.parent_node
    cur.parent_node = node("a", {"href": "/checkout"})
    return n


def _span_in_formaction_button():
    return node("span", parent=node("button", {"type": "submit", "formaction": "/pay/now"}, text="Go"))


@pytest.mark.parametrize("make", [
    _span_in_checkout_link, _span_in_place_order_button, _img_in_submit_in_checkout_form, _two_up_link,
    lambda: _deep_link(14), _span_in_formaction_button,
    lambda: node("svg", parent=node("div", {"role": "button", "aria-label": "Buy now"}, text="")),
], ids=["link-checkout", "place-order-button", "img-submit-form", "two-up", "depth-15", "formaction", "role-button"])
async def test_click_on_child_of_commerce_control_is_gated(make):
    assert await classify(make()) is not None


async def test_ancestor_walk_limit_is_16():
    assert await classify(_deep_link(14)) is not None
    assert await classify(_deep_link(40)) is None


@pytest.mark.parametrize("make", [
    lambda: node("span", text="Details", parent=node("a", {"href": "/products/42"}, text="Details")),
    lambda: node("span", text="Next", parent=node("button", {"type": "submit"}, text="Next",
                                                  parent=node("form", {"action": "/search"}))),
    # a page wrapper's text must not label the click target
    lambda: node("span", text="Hi", parent=node("div", text="Buy now Place order everything",
                                                parent=node("main", text="Buy now"))),
], ids=["plain-link", "search-form", "wrapper-text"])
async def test_child_of_ordinary_control_is_not_gated(make):
    assert await classify(make()) is None


def test_element_risk_reads_enclosing_label():
    n = _span_in_place_order_button()
    assert "Place order" in element_risk(n, "https://shop.com/", None)


def test_live_chain_carries_ancestor_labels_and_urls():
    live = _node_from_live({
        "tag": "span", "attrs": {}, "text": "", "form": None,
        "chain": [{"tag": "button", "attrs": {"type": "submit"}, "text": "Place order"},
                  {"tag": "form", "attrs": {"action": "/checkout/confirm"}}],
    })
    assert element_risk(live, "https://shop.com/", None) is not None
    live = _node_from_live({"tag": "img", "attrs": {}, "text": "", "form": None,
                            "chain": [{"tag": "a", "attrs": {"href": "https://shop.com/checkout"}, "text": ""}]})
    assert element_risk(live, "https://shop.com/", None) is not None


# ---- MAJOR 2: label evasion -----------------------------------------------------------------------
MUST_GATE = [
    "bUY", "BuY NoW", "bUyNoW", "Bu y now", "Pa y now", "BUYNOW", "buynow", "placeorder", "Buy\u200bnow",
    "Place\u200border", "Pay\u200bnow", "Buy now details", "Buy now FAQ", "Learn more. Buy now",
    "Buy now - see terms", "Buy now (help)", "How it works: Buy now", "Order status: Buy now", "bUY NOW",
    "ʙᴜʏ ɴᴏᴡ", "Bսy now", "ƁUY NOW", "Buy now", "Place order", "Checkout", "Check out", "Check-out", "CHECKOUT",
    "Proceed to checkout", "Go to checkout", "Secure checkout", "Checkout with PayPal", "Checkout (3)",
    "Start free trial", "Start my free trial", "Send payment", "Pay bill", "Agree and pay", "Authorize payment",
    "Approve payment", "Apple Pay", "G Pay", "Google Pay", "Upgrade", "Upgrade now", "Upgrade plan",
    "Withdraw funds", "Transfer funds", "Rent now", "Αγορά", "αγορά", "اشتري", "Satın al", "Comprar",
    "Jetzt kaufen", "Acheter", "Buy", "Buy 2 for $20", "Donate $50", "Pay $20.00", "Complete purchase",
    "Place order guide", "Buy ticket", "Book now", "Pay now", "Purchase",
]
MUST_NOT_GATE = [
    "Pay attention", "Purchase history", "Add to cart", "Add to bag", "Book 3", "Book a demo", "Buy-in",
    "Buy vs lease", "Buy side analysis", "Checkout page design", "Place order tracking", "Check out our blog",
    "Check out our menu", "Check out this article", "Check out the docs", "Checkout our blog",
    "Checkout process explained", "Checking out", "Buy now, pay later explained", "How to pay", "Pay per click",
    "Upgrade your browser", "Order history", "Subscribe to newsletter", "Payment history", "Pay stub",
    "Pay it forward", "Get tickets", "Order status", "Track order", "Billing history", "Buyer reviews",
    "Buying guide", "Search", "Learn more",
]


@pytest.mark.parametrize("label", MUST_GATE)
def test_label_must_gate(label):
    assert is_commerce_label(label), label


@pytest.mark.parametrize("label", MUST_NOT_GATE)
def test_label_must_not_gate(label):
    assert not is_commerce_label(label), label


async def test_get_tickets_gated_only_with_checkout_target():
    plain = node("a", {"href": "/events/42"}, text="Get tickets")
    assert await classify(plain) is None
    assert await classify(node("a", {"href": "/checkout?event=42"}, text="Get tickets")) is not None


# ---- MAJOR 3 / blocklist --------------------------------------------------------------------------
NEW_BLOCKED = [
    "accounts.google.com", "myaccount.google.com", "appleid.apple.com", "login.microsoftonline.com",
    "login.live.com", "account.microsoft.com", "schwab.com", "fidelity.com", "vanguard.com", "etrade.com",
    "robinhood.com", "coinbase.com", "kraken.com", "binance.com", "capitalone.com", "americanexpress.com",
    "discover.com", "usbank.com", "cash.app", "venmo.com", "wise.com", "zellepay.com", "intuit.com",
    "turbotax.com", "paypal.me", "paypal.co.uk", "paypal.de", "console.aws.amazon.com",
    "signin.aws.amazon.com",
]


def test_defaults_contain_new_domains():
    assert set(NEW_BLOCKED) <= SAFETY_DEFAULTS
    assert len(SAFETY_DEFAULTS) > 29


def test_path_level_sites_stay_reachable():
    assert not host_is_blocked("github.com", SAFETY_DEFAULTS)
    assert not host_is_blocked("mail.google.com", SAFETY_DEFAULTS)
    assert not host_is_blocked("aws.amazon.com", SAFETY_DEFAULTS)
    assert not host_is_blocked("www.amazon.com", SAFETY_DEFAULTS)


def _watchdog(**safety):
    s = build_browser_session(BrowserConfig(executable_path="/bin/true"), SafetyPolicy(**safety))
    assert isinstance(s.browser_profile.prohibited_domains, list)
    return SecurityWatchdog.model_construct(browser_session=s)


@pytest.mark.parametrize("url", [f"https://{d}/" for d in NEW_BLOCKED[:12]] + [
    "https://www.schwab.com/login", "https://client.schwab.com./", "https://eu.paypal.co.uk/x",
    "https://signin.aws.amazon.com/", "https://console.aws.amazon.com/ec2"])
def test_watchdog_blocks_new_defaults(url):
    assert _watchdog()._is_url_allowed(url) is False


def test_watchdog_new_defaults_do_not_break_other_rules():
    w = _watchdog()
    assert w._is_url_allowed("https://github.com/settings/tokens") is True
    assert w._is_url_allowed("https://example.com/") is True
    assert w._is_url_allowed("http://localhost/") is False
    assert w._is_url_allowed("chrome://settings") is False
    w2 = _watchdog(allow_local_network=True)
    assert w2._is_url_allowed("http://printer.local/") is True
    assert w2._is_url_allowed("https://accounts.google.com/") is False


@pytest.mark.parametrize("entry", ["github.io", "*.github.io", "herokuapp.com", "blogspot.com", "*.pages.dev",
                                   "vercel.app", "netlify.app", "web.app", "firebaseapp.com", "azurewebsites.net",
                                   "cloudfront.net", "appspot.com"])
def test_shared_hosting_suffixes_rejected(entry):
    with pytest.raises(ValueError):
        normalize_allowed_domain(entry)


def test_shared_hosting_suffix_but_specific_site_ok():
    assert normalize_allowed_domain("me.github.io") == "me.github.io"
    assert "github.io" in PUBLIC_SUFFIXES


def test_dropped_allow_entries_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="local_browser_agent"):
        p = SafetyPolicy(allowed_domains=["example.com", "*.google.com"])
    assert p.allowed_domains == ["example.com"]
    assert any("*.google.com" in r.getMessage() for r in caplog.records)


def test_all_dropped_raises_naming_entries():
    with pytest.raises(ValueError, match="google.com"):
        SafetyPolicy(allowed_domains=["*.google.com"])


# ---- MINOR: URLs ---------------------------------------------------------------------------------
URL_GATE = [
    "https://shop.com/%63heckout", "https://shop.com/checkout;jsessionid=1", "https://shop.com/x?next=/checkout",
    "https://shop.com/x?redirect=https://shop.com/checkout", "https://shop.com/express-checkout",
    "https://shop.com/onestepcheckout", "https://shop.com/CheckoutView",
    "https://shop.com/webapp/wcs/stores/servlet/CheckoutView", "https://shop.com/buy", "https://shop.com/buy/123",
    "https://buy.stripe.com/abc", "https://checkout.stripe.com/c/pay/cs_live_x", "https://shop.com/%EF%BC%8Fcheckout",
    "https://shop.com/en-us/checkout", "https://shop.com/cart/checkout", "https://shop.com/shop/checkout/payment",
    "https://shop.com/checkout/", "https://shop.com/api/checkout", "https://paypal.com/checkoutnow",
]
URL_NO_GATE = [
    "https://shop.com/blog/checkout-our-new-feature", "https://shop.com/news/checkout",
    "https://shop.com/x?q=/checkout", "https://shop.com/x?next=/about", "https://shop.com/blog/checkout/our-launch",
    "https://shop.com/buy-side", "https://shop.com/buy/used-cars", "https://shop.com/products/buy-guide",
    "https://shop.com/docs/checkout", "https://en.wikipedia.org/wiki/Checkout", "https://shop.com/cart",
]


@pytest.mark.parametrize("url", URL_GATE)
def test_url_must_gate(url):
    assert is_commerce_url(url), url


@pytest.mark.parametrize("url", URL_NO_GATE)
def test_url_must_not_gate(url):
    assert not is_commerce_url(url), url


# ---- MINOR: upload and dropdown --------------------------------------------------------------------
async def test_upload_file_needs_approval():
    seen = []

    async def deny(req):
        seen.append(req)
        return False

    t = GuardedTools(approval=deny)
    r = await t._lba_classify("upload_file", {"index": 1, "path": "/home/me/secret/taxes.pdf"}, Sess(node("input")))
    assert r is not None and r.element_label == "taxes.pdf" and "uploads" in r.reason
    assert await t._lba_ask(r) is not None
    assert seen


async def test_upload_denied_without_approval_callback():
    t = GuardedTools()
    r = await t._lba_classify("upload_file", {"index": 1, "path": "/x/y.txt"}, Sess(node("input")))
    assert await t._lba_ask(r) is not None


async def test_select_dropdown_commerce_option_gated():
    assert await classify(node("select"), name="select_dropdown", params={"index": 1, "text": "Buy now"}) is not None
    assert await classify(node("select"), name="select_dropdown", params={"index": 1, "text": "Medium"}) is None
