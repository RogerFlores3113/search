"""Round 8: structural destructive-page rule, currency-less money, regex DoS, URL precision, matcher robustness."""
from __future__ import annotations

import time
from types import SimpleNamespace as NS

import pytest

from local_browser_agent import GuardedTools
from local_browser_agent.safety import is_commerce_label, is_destructive_url, is_irreversible_label

DESTRUCTIVE_PAGES = [
    "https://x.example/account/delete", "https://x.example/settings/delete-account",
    "https://x.example/account/close", "https://x.example/subscription/cancel",
]


def _node(text="", tag="button", attrs=None, parent=None):
    return NS(node_name=tag, attributes=attrs or {}, ax_node=None, node_value="", parent_node=parent,
              get_all_children_text=lambda: text, backend_node_id=None)


class Sess:
    def __init__(self, n=None, url="https://app.example/settings"):
        self.n, self.url = n, url

    async def get_current_page_url(self):
        return self.url

    async def get_element_by_index(self, i):
        return self.n


async def _click(node, url):
    return await GuardedTools()._lba_classify("click", {"index": 1}, Sess(node, url))


# ---- 1. structural rule on destructive pages
@pytest.mark.parametrize("url", DESTRUCTIVE_PAGES)
@pytest.mark.parametrize("label", ["Delete", "Yes, delete", "Remove", "Confirm cancellation", "Cancel anyway",
                                   "Proceed", "Save", "Whatever"])
async def test_every_button_gated_on_destructive_page(label, url):
    req = await _click(_node(label, "button", {"type": "submit"}), url)
    assert req is not None and req.kind == "irreversible"


@pytest.mark.parametrize("node", [
    _node("Whatever", "input", {"type": "submit"}), _node("Whatever", "input", {"type": "button"}),
    _node("Whatever", "div", {"role": "button"}), _node("", "button"),
])
async def test_other_button_like_controls_gated(node):
    req = await _click(node, "https://x.example/account/delete")
    assert req is not None and req.kind == "irreversible"


@pytest.mark.parametrize("label", ["Cancel", "No", "Back", "Keep", "Keep my account", "Keep subscription", "Go back",
                                   "Never mind", "Not now", "Close"])
async def test_backing_out_labels_not_gated(label):
    assert await _click(_node(label), "https://x.example/account/delete") is None


async def test_plain_link_to_safe_url_not_gated_on_destructive_page():
    assert await _click(_node("Learn more", "a", {"href": "/home"}), "https://x.example/account/delete") is None


async def test_enter_space_and_select_on_destructive_page():
    t = GuardedTools()

    async def live_focused(_s):
        return "ok", _node("Whatever")

    t._lba_live_focused = live_focused
    for keys in ("Enter", "Space"):
        req = await t._lba_classify("send_keys", {"keys": keys}, Sess(None, "https://x.example/account/close"))
        assert req is not None and req.kind == "irreversible"
    req = await GuardedTools()._lba_classify("select_dropdown", {"index": 1, "text": "Other reason"},
                                             Sess(None, "https://x.example/account/delete"))
    assert req is not None and req.kind == "irreversible"
    assert await GuardedTools()._lba_classify("select_dropdown", {"index": 1, "text": "Other reason"}, Sess()) is None


async def test_normal_pages_unchanged():
    for label in ("Delete", "Cancel", "Yes, delete", "Post", "Publish", "Send message", "Allow", "Accept",
                  "Delete comment", "Close dialog", "End call"):
        assert await _click(_node(label), "https://app.example/settings") is None
    assert await _click(_node("Continue"), "https://www.nytimes.com/2024/05/05/arts/review/film.html") is None
    assert await _click(_node("Next"), "https://x.example/orders?page=2") is None


@pytest.mark.parametrize("label", ["Confirm cancellation", "Complete cancellation", "Finalize cancellation",
                                   "Cancel anyway", "Yes, cancel", "Yes, cancel it", "Yes, delete account",
                                   "Yes, delete subscription"])
def test_cancellation_labels_gate_anywhere(label):
    assert is_irreversible_label(label)


def test_bare_yes_delete_on_normal_page_ungated():
    assert not is_irreversible_label("Yes, delete")


# ---- 2. money without a currency symbol
@pytest.mark.parametrize("label", [
    "Transfer 500 to savings", "Withdraw 500 to bank", "Withdraw 500", "Send 1,000 USD", "Send 0.5 BTC",
    "Send 500 to Alex", "Send 500 INR", "Send Rs 500", "Send ₹500", "Send 20 USDC", "Send 0.1 ETH", "Send 5 usdt",
    "Transfer 1 000 to savings", "Transfer 100% of balance", "Withdraw max", "Withdraw maximum",
    "Transfer full balance", "Transfer entire balance", "Wire 5000 to John",
])
def test_money_gates(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", ["Send 5 photos", "Transfer files", "Send invoice", "Send", "Transfer",
                                   "Send 3", "Transfer 3 files", "Send 2 messages", "Transfer 5 tickets"])
def test_money_does_not_gate(label):
    assert not is_irreversible_label(label)


# ---- 3. quadratic regexes
@pytest.mark.parametrize("label", ["a" + " " * 50000 + "b", "a" + "." * 50000 + "b", "a" + "(" * 50000,
                                   "delete " + " " * 50000 + "account", "a" + "!" * 50000 + "b"])
def test_pathological_labels_are_fast(label):
    t = time.perf_counter()
    is_irreversible_label(label)
    is_commerce_label(label)
    assert time.perf_counter() - t < 0.5


async def test_pathological_select_is_fast():
    t0 = time.perf_counter()
    await GuardedTools()._lba_classify("select_dropdown", {"index": 1, "text": "a" + " " * 50000 + "b",
                                                            "value": "a" + "." * 50000 + "b"}, Sess())
    assert time.perf_counter() - t0 < 0.5


# ---- 4. destructive URL precision
@pytest.mark.parametrize("url", [
    "https://shop.com/account/delete-address?id=3", "https://shop.com/account/delete_card/12",
    "https://x.com/account/close-notification", "https://x.com/account/deactivate-2fa",
    "https://x.com/account/delete-comment/5", "https://x.com/devices/9/deactivate",
    "https://x.com/sessions/terminate", "https://news.com/world/close-account-of-bank",
    "https://x.com/settings/billing/cancel", "https://x.com/account/remove",
])
def test_url_false_positives_fixed(url):
    assert not is_destructive_url(url)


@pytest.mark.parametrize("url", [
    "https://x.com/cancelsubscription", "https://x.com/myaccount/delete", "https://x.com/user/delete",
    "https://x.com/profile/delete", "https://x.com/delete?type=account", "https://x.com/settings?action=delete_account",
    "https://x.com/account/delete/12", "https://x.com/account/delete/confirm", "https://x.com/deleteAccount",
    "https://x.com/close_account.php", "https://x.com/settings?intent=close&type=account",
    "https://x.com/deactivate", "https://x.com/account/terminate", "https://x.com/settings/delete-my-account",
    "https://x.com/subscriptions/cancel/step-2",
])
def test_url_misses_fixed(url):
    assert is_destructive_url(url)


# ---- 5. matcher robustness
@pytest.mark.parametrize("label", [
    "Delete (all data)", "Cancel (subscription)", "Delete account – cannot be undone",
    "Delete account. This cannot be undone", "Delete account: this is permanent", "Delete account; no undo",
    "Delete account - cannot be undone", "Delete account & data", "Close account and delete data",
    "Delete my account and everything", "Delete account (cannot be undone)",
])
def test_robust_gates(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", ["Delete (3)", "Delete comment & draft", "Close profile", "Remove profile picture",
                                   "Cancel plan change", "Delete draft", "Delete file", "Close dialog",
                                   "Delete account policy - read more", "Send 0.5 photos"])
def test_robust_does_not_gate(label):
    assert not is_irreversible_label(label)
