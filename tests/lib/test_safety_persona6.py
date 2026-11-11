"""Persona 6 red-team fixes: invisible/decorated/fused labels, money movement, destructive URLs."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from local_browser_agent import GuardedTools
from local_browser_agent.safety import ActionRequest, is_destructive_url, is_irreversible_label

ZW, SHY, ACUTE = "\u200b", "\u00ad", "\u0301"

GATE = [
    f"Delete{ZW}account", f"Cancel{SHY}subscription", "Deleteaccount", "Cancelsubscription", "Closemyaccount",
    "Cancel Subscription \u2192", "Delete account \U0001F5D1", "\U0001F5D1 Delete account",
    "Cancel subscription (required)", "Delete account [required]", f"Delete account{ACUTE}",
    "Send $500", "Send funds", "Withdraw all", "Cash out", "Transfer $1,000 to savings", "Transfer 200 USD",
    "Transfer all", "Wire $5,000", "Withdraw 500", "Close my Chase account", "Delete my google account",
    "Permanently delete", "Delete everything", "Turn off auto-renewal", "Turn off auto renew",
    "Stop subscription", "Unsubscribe and delete account", "I want to delete my account permanently",
    "Delete acc0unt", "Cancel plan",
]
NOT_GATE = [
    "Post", "Publish", "Send message", "Allow", "Accept", "Unsubscribe", "Delete", "Cancel", "Close profile",
    "Remove profile picture", "Cancel plan change", "Delete comment", "Delete draft", "Delete file",
    "Close dialog", "Close account menu", "Remove account from this device", "Transfer", "Send", "Delete all",
    "Send 3 messages", "Send all", "How to delete my account", "Delete account instructions",
    "Close my account menu",
]


@pytest.mark.parametrize("label", GATE)
def test_label_gates(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", NOT_GATE)
def test_label_does_not_gate(label):
    assert not is_irreversible_label(label)


@pytest.mark.parametrize("url", [
    "https://x.example/settings/delete-account", "https://x.example/account/close", "https://x.example/account/delete",
    "https://x.example/subscription/cancel", "https://x.example/membership/cancel",
    "https://x.example/cancel-subscription", "https://x.example/deactivate", "https://x.example/close-account",
    "https://x.example/#/account/delete", "https://x.example/cancel-membership",
])
def test_destructive_urls(url):
    assert is_destructive_url(url)


@pytest.mark.parametrize("url", [
    "https://x.example/comments/123/delete", "https://x.example/cart/cancel-item", "https://x.example/cancel",
    "https://x.example/delete", "https://x.example/help/delete-account", "https://x.example/settings",
    "https://x.example/account/delete/success", None, "",
])
def test_non_destructive_urls(url):
    assert not is_destructive_url(url)


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


@pytest.mark.parametrize("label", ["Confirm", "Continue", "Yes", "Submit", "OK"])
@pytest.mark.parametrize("url", [
    "https://x.example/settings/delete-account", "https://x.example/account/close",
    "https://x.example/subscription/cancel", "https://x.example/membership/cancel",
    "https://x.example/cancel-subscription", "https://x.example/deactivate",
])
async def test_generic_confirm_on_destructive_page_gates(label, url):
    req = await _click(_node(label), url)
    assert req is not None and req.kind == "irreversible"


@pytest.mark.parametrize("href,label", [("/account/delete", "Continue"), ("/subscription/cancel", "Go"),
                                         ("https://x.example/settings/delete-account", "Yes")])
async def test_destructive_href_gates_any_label(href, label):
    req = await _click(_node(label, "a", {"href": href}), "https://app.example/settings")
    assert req is not None and req.kind == "irreversible"


async def test_destructive_form_action_and_ancestor_href_gate():
    form = _node("", "form", {"action": "/account/delete"})
    req = await _click(_node("Go", "button", {"type": "submit"}, parent=form), "https://app.example/settings")
    assert req is not None and req.kind == "irreversible"
    link = _node("", "a", {"href": "/subscription/cancel"})
    req = await _click(_node("Next", "span", parent=link), "https://app.example/settings")
    assert req is not None and req.kind == "irreversible"


async def test_bare_cancel_delete_paths_not_gated():
    assert await _click(_node("Continue", "a", {"href": "/comments/123/delete"}), "https://x.example/p") is None
    assert await _click(_node("Go", "a", {"href": "/cart/cancel-item"}), "https://x.example/cart/view") is None
    assert await _click(_node("Confirm"), "https://x.example/comments/123/delete") is None


async def test_existing_must_not_rows_still_pass():
    assert await _click(_node("Continue"), "https://www.nytimes.com/2024/05/05/arts/review/film.html") is None
    assert await _click(_node("Next"), "https://x.example/orders?page=2") is None


async def test_upload_kind_and_select_value():
    t = GuardedTools()
    req = await t._lba_classify("upload_file", {"index": 1, "path": "/tmp/a.txt"}, Sess())
    assert req is not None and req.kind == "upload"
    req = await t._lba_classify("select_dropdown", {"index": 1, "text": "Choose", "value": "Delete account"}, Sess())
    assert req is not None and req.kind == "irreversible"
    req = await t._lba_classify("select_dropdown", {"index": 1, "text": "Choose", "value": "Buy now"}, Sess())
    assert req is not None and req.kind == "commerce"
    assert await t._lba_classify("select_dropdown", {"index": 1, "text": "Red", "value": "red"}, Sess()) is None


def test_action_request_default_kind():
    assert ActionRequest(action_name="click").kind == "commerce"
