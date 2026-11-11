"""Verb x object irreversible labels, keyboard/select gating, and tightened commerce-context URLs."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from local_browser_agent import GuardedTools
from local_browser_agent.safety import is_commerce_context_url, is_irreversible_label

GATE = [
    "Cancel your subscription", "Cancel your membership", "End your subscription", "Cancel auto-renewal",
    "Delete this account", "Close this account", "Delete account and all associated data", "Delete forever",
    "Delete data", "Delete all data", "Remove account", "Terminate account", "Deactivate", "Delete account?",
    "Withdraw consent", "Erase my data", "Permanently delete account", "Delete your profile",
]
NOT_GATE = [
    "Post", "Publish", "Send message", "Allow", "Accept", "Unsubscribe", "Delete", "Cancel", "Authorize",
    "Remove from cart", "Delete comment", "Close", "How to delete your account", "Delete account policy",
    "Wire transfer history", "Cancel subscription policy", "Withdraw application",
]


@pytest.mark.parametrize("label", GATE)
def test_label_gates(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", NOT_GATE)
def test_label_does_not_gate(label):
    assert not is_irreversible_label(label)


def _node(text, tag="button"):
    return NS(node_name=tag, attributes={}, ax_node=None, node_value="", parent_node=None,
              get_all_children_text=lambda: text, backend_node_id=None)


class Sess:
    def __init__(self, n=None, url="https://app.example/settings"):
        self.n, self.url = n, url

    async def get_current_page_url(self):
        return self.url

    async def get_element_by_index(self, i):
        return self.n


def _tools(focused, **kw):
    t = GuardedTools(**kw)

    async def live_focused(_s):
        return "ok", focused

    t._lba_live_focused = live_focused
    return t


@pytest.mark.parametrize("keys", ["Enter", "Space"])
async def test_key_activation_gates_irreversible(keys):
    req = await _tools(_node("Delete account"))._lba_classify("send_keys", {"keys": keys}, Sess())
    assert req is not None and req.kind == "irreversible"


async def test_key_activation_bare_delete_and_disabled_pass():
    assert await _tools(_node("Delete"))._lba_classify("send_keys", {"keys": "Enter"}, Sess()) is None
    assert await _tools(_node("Delete account"), gate_irreversible=False)._lba_classify(
        "send_keys", {"keys": "Enter"}, Sess()) is None


async def test_select_option_gates_irreversible():
    t = GuardedTools()
    req = await t._lba_classify("select_dropdown", {"index": 1, "text": "Delete account"}, Sess())
    assert req is not None and req.kind == "irreversible"
    assert await t._lba_classify("select_dropdown", {"index": 1, "text": "Delete"}, Sess()) is None


NOT_CONTEXT = [
    "https://www.nytimes.com/2024/05/05/arts/review/film.html", "https://www.theguardian.com/books/review",
    "https://www.reuters.com/world/order", "https://www.nytimes.com/section/business/pay",
    "https://example.com/jobs/review", "https://x.com/orders?page=2",
]
CONTEXT = [
    "https://shop.example/checkout/review", "https://shop.example/cart", "https://shop.example/order/confirm",
    "https://shop.example/billing", "https://shop.example/orders/new", "https://shop.example/account/billing",
]


@pytest.mark.parametrize("url", NOT_CONTEXT)
@pytest.mark.parametrize("label", ["Continue", "Next", "Submit", "Done"])
async def test_generic_button_not_gated_on_content_pages(url, label):
    assert not is_commerce_context_url(url)
    assert await GuardedTools()._lba_classify("click", {"index": 1}, Sess(_node(label), url)) is None


@pytest.mark.parametrize("url", CONTEXT)
def test_real_checkout_flows_still_context(url):
    assert is_commerce_context_url(url)


@pytest.mark.parametrize("label", [
    "Remove profile picture", "Close account menu", "Cancel plan change", "Delete data saver",
    "End plan selection", "Remove account from this device", "Close profile", "Remove data filter",
    "Cancel subscription renewal reminder", "Edit profile",
])
def test_reversible_neighbours_of_irreversible_labels_do_not_gate(label):
    assert not is_irreversible_label(label)


@pytest.mark.parametrize("label", [
    "Cancel my subscription now", "Close my account", "Delete all my data", "Confirm delete account",
    "Deactivate my account", "Yes, delete my account", "Cancel membership",
])
def test_irreversible_labels_still_gate(label):
    assert is_irreversible_label(label)
