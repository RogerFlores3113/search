"""Persona-7 red-team findings: long labels, brand filler, looser money tails, URL and label gaps."""
from __future__ import annotations

import time

import pytest

from local_browser_agent.safety import is_destructive_url, is_irreversible_label

GATED = [
    "Permanently delete my account and all associated data and content",
    "Delete my account and all of my data from this service permanently",
    "Yes, I want to permanently delete my account and all data",
    "Close my account and delete all of my personal information",
    "Yes, cancel subscription and lose access to all features",
    "Delete account\nThis action is permanent",
    "lorem ipsum dolor sit amet " * 14 + "Delete account",
    "Delete my LinkedIn account", "Close my PayPal account", "Close my Wells Fargo account",
    "Close Chase account", "Delete Apple ID", "Delete my Apple ID", "Delete user", "Delete user account",
    "Send $50 to Alex via Zelle now", "Transfer $50 from checking to savings account now please",
    "Withdraw to bank", "Withdraw balance", "Add funds", "Deposit funds", "Tip $5",
    "Delete acct", "Delete a/c", "Cancel trial", "Cancel renewal", "Close bank account",
    "Unlink bank account", "Delete card",
]
UNGATED = [
    "Remove user from group", "Close account menu", "Remove account from this device",
    "How to delete your account", "Cancel Netflix", "Deposit", "Sell", "Invest", "Swap", "Convert", "Stake",
    "Send all", "Send 100", "Make offer", "Accept offer", "Renew now", "Tip", "Delete", "Delete\nHelp",
    "You can cancel your subscription at any time from your settings page",
    "How to delete your account and all of your data from this service permanently",
]


@pytest.mark.parametrize("label", GATED, ids=[g[:30] for g in GATED])
def test_gated(label):
    assert is_irreversible_label(label)


@pytest.mark.parametrize("label", UNGATED, ids=[g[:30] for g in UNGATED])
def test_not_gated(label):
    assert not is_irreversible_label(label)


def test_long_label_end_is_checked():
    assert is_irreversible_label("a" * 375 + " Delete account")
    assert is_irreversible_label("Delete account " + "z" * 400)


def test_long_labels_stay_fast():
    t = time.perf_counter()
    for label in ("delete " * 20000, "x " * 30000 + "Delete account", "\n".join(["cancel plan"] * 5000)):
        is_irreversible_label(label)
    assert time.perf_counter() - t < 2.0


@pytest.mark.parametrize("path", [
    "/subscriptions/123/cancel", "/users/me/delete", "/settings/privacy/delete-my-data", "/gdpr/delete",
    "/account/erase", "/account/closure", "/membership/end",
])
def test_destructive_urls(path):
    assert is_destructive_url("https://example.com" + path)


@pytest.mark.parametrize("path", [
    "/account/delete-address", "/sessions/terminate", "/devices/9/deactivate", "/comments/1/delete",
    "/help/delete-my-data", "/privacy/policy", "/cart/cancel-item",
])
def test_non_destructive_urls(path):
    assert not is_destructive_url("https://example.com" + path)
