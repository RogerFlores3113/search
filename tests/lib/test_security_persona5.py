"""Persona 5 security round: irreversible actions, generic confirm buttons, URL gaps, strict preset."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from local_browser_agent import GuardedTools, SafetyPolicy
from local_browser_agent.browser import blocked_patterns
from local_browser_agent.safety import (
    SAFETY_DEFAULTS,
    SAFETY_DEFAULTS_COUNT,
    ActionRequest,
    host_is_blocked,
    is_commerce_context_url,
    is_commerce_label,
    is_commerce_url,
    is_irreversible_label,
)


def node(tag="button", attrs=None, text="", parent=None):
    return NS(node_name=tag, attributes=attrs or {}, ax_node=None, node_value="", parent_node=parent,
              get_all_children_text=lambda: text, backend_node_id=None)


class Sess:
    def __init__(self, n, url):
        self.n, self.url = n, url

    async def get_current_page_url(self):
        return self.url

    async def get_element_by_index(self, i):
        return self.n


async def classify(n, url="https://app.example/settings", **kw):
    return await GuardedTools(**kw)._lba_classify("click", {"index": 1}, Sess(n, url))


IRREVERSIBLE = [
    "Delete account", "Delete my account", "Close account", "Close my account", "Deactivate account",
    "Delete my data", "Cancel subscription", "Cancel my membership", "Cancel plan", "End subscription",
    "Withdraw", "Withdraw funds", "Withdraw money", "Transfer funds", "Transfer money", "Transfer balance",
    "Send money", "Send payment", "Wire", "Wire transfer", "Authorize payment", "Confirm transfer",
    "Confirm withdrawal", "Close position", "Sell all", "Yes, delete my account", "CANCEL SUBSCRIPTION",
]
NOT_IRREVERSIBLE = [
    "Allow", "Allow all cookies", "Accept", "Submit", "Continue", "Confirm", "Post", "Publish",
    "Send message", "Unsubscribe", "Delete", "Cancel", "Authorize", "How to delete your account",
    "Cancel subscription policy", "Withdrawal history", "Wire frame", "Sell", "Save", "Close",
]


@pytest.mark.parametrize("label", IRREVERSIBLE)
def test_irreversible_label_gates(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", NOT_IRREVERSIBLE)
def test_irreversible_label_does_not_gate(label):
    assert not is_irreversible_label(label)


def test_bare_authorize_only_on_pay_urls():
    assert is_irreversible_label("Authorize", "https://bank.example/pay/auth")
    assert is_irreversible_label("Authorize", "https://x.example/oauth/consent")
    assert not is_irreversible_label("Authorize", "https://x.example/apps")
    assert is_irreversible_label("Authorize payment", "https://x.example/apps")


@pytest.mark.parametrize("label", IRREVERSIBLE)
async def test_click_on_irreversible_asks_with_kind(label):
    req = await classify(node(text=label))
    # A few (send money, withdraw funds, ...) were already caught by the commerce patterns.
    assert isinstance(req, ActionRequest) and req.kind in ("irreversible", "commerce")
    if label in ("Delete account", "Cancel subscription", "Withdraw", "Close position", "Sell all"):
        assert req.kind == "irreversible"


@pytest.mark.parametrize("label", NOT_IRREVERSIBLE)
async def test_click_on_non_irreversible_passes(label):
    assert await classify(node(text=label)) is None


async def test_irreversible_gate_can_be_disabled_and_commerce_kind_default():
    assert await classify(node(text="Delete account"), gate_irreversible=False) is None
    req = await classify(node(text="Buy now"))
    assert req is not None and req.kind == "commerce"
    assert ActionRequest("click").kind == "commerce"


async def test_input_value_and_span_child_irreversible():
    assert (await classify(node("input", {"type": "submit", "value": "Delete account"}))).kind == "irreversible"
    child = node("span", text="Cancel subscription", parent=node("button", text="Cancel subscription"))
    assert (await classify(child)).kind == "irreversible"


GENERIC = ["Confirm", "Submit", "Continue", "Complete", "Finish", "Done", "Next"]
COMMERCE_PAGES = [
    "https://shop.example/checkout", "https://shop.example/cart", "https://shop.example/basket",
    "https://shop.example/bag", "https://shop.example/review", "https://shop.example/order",
    "https://shop.example/secure/pay", "https://shop.example/pay/now", "https://shop.example/pay",
    "https://shop.example/payment", "https://shop.example/payments", "https://shop.example/orders/new",
    "https://shop.example/orderconfirm", "https://shop.example/order-confirm", "https://shop.example/co/shipping",
    "https://shop.example/co/payment", "https://shop.example/billing", "https://shop.example/gp/buy/spc/x.html",
]
NON_COMMERCE_PAGES = [
    "https://x.example/settings", "https://x.example/news/bag-of-tricks", "https://x.example/blog/cart-tips",
    "https://x.example/news/billing", "https://www.amazon.com/gp/cart/view.html", "https://x.example/",
    "https://x.example/co/about", "https://github.com/org/cart",
]


@pytest.mark.parametrize("url", COMMERCE_PAGES)
@pytest.mark.parametrize("label", ["Confirm", "Continue", "Next"])
async def test_generic_button_gated_on_commerce_page(url, label):
    for n in (node(text=label), node("div", {"role": "button"}, text=label),
              node("input", {"type": "submit", "value": label})):
        req = await classify(n, url)
        assert req is not None and req.kind == "commerce", (url, label)


@pytest.mark.parametrize("label", GENERIC)
async def test_all_generic_labels_gated_on_checkout(label):
    assert await classify(node(text=label), "https://shop.example/checkout") is not None


@pytest.mark.parametrize("url", NON_COMMERCE_PAGES)
@pytest.mark.parametrize("label", GENERIC)
async def test_generic_button_not_gated_elsewhere(url, label):
    assert await classify(node(text=label), url) is None


async def test_generic_button_in_form_posting_to_order_url():
    form = node("form", {"action": "/orders/new"})
    assert await classify(node(text="Confirm", attrs={"type": "submit"}, parent=form)) is not None
    assert await classify(node(text="Confirm", parent=node("form", {"action": "/profile"}))) is None


def test_context_url_helper():
    for u in COMMERCE_PAGES:
        assert is_commerce_context_url(u), u
    for u in NON_COMMERCE_PAGES:
        assert not is_commerce_context_url(u), u


@pytest.mark.parametrize("url", [
    "https://a.example/secure/pay", "https://a.example/pay/now", "https://a.example/orders/new",
    "https://a.example/orderconfirm", "https://a.example/co/shipping", "https://a.example/co/review",
    "https://a.example/gp/buy/spc/handlers/display.html",
])
def test_commerce_urls_new_shapes(url):
    assert is_commerce_url(url)


@pytest.mark.parametrize("url", [
    "https://a.example/gp/cart/view.html", "https://a.example/news/pay/now", "https://a.example/blog/orders/new",
    "https://a.example/co/about", "https://a.example/cart", "https://a.example/news/billing",
])
def test_non_commerce_urls_stay(url):
    assert not is_commerce_url(url)


@pytest.mark.parametrize("label", ["Buy‑now", "Buy‐now", "Buy−now", "Buy﹣now", "Buy－now",
                                   "Place‑order"])
def test_hyphen_variants_fold(label):
    assert is_commerce_label(label)


def test_blocklist_additions_and_count():
    for h in ("zelle.com", "binance.us", "login.gov", "secure.login.gov", "id.me", "www.id.me"):
        assert host_is_blocked(h, SAFETY_DEFAULTS), h
    for h in ("icloud.com", "dropbox.com", "mail.google.com"):
        assert not host_is_blocked(h, SAFETY_DEFAULTS), h
    assert SAFETY_DEFAULTS_COUNT == len(SAFETY_DEFAULTS)
    assert len(blocked_patterns(SAFETY_DEFAULTS)) == 2 * SAFETY_DEFAULTS_COUNT


def test_strict_preset():
    p = SafetyPolicy.strict(allowed_domains=["example.com"], gate_commerce_clicks=False)
    assert p.gate_commerce_clicks and not p.allow_evaluate and p.allowed_domains == ["example.com"]
    assert SafetyPolicy.strict("example.com").allowed_domains == ["example.com"]
    for bad in ([], [" "], None):
        with pytest.raises(ValueError):
            SafetyPolicy.strict(allowed_domains=bad)
