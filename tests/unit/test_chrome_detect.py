"""Tests for agent/chrome_detect.py (DIST-02).

Chrome detection: present/absent on darwin; passthrough on non-darwin.
"""
from __future__ import annotations

import sys

import pytest


def test_chrome_present(monkeypatch):
    """When Chrome binary exists on darwin, chrome_is_installed() returns True."""
    monkeypatch.setattr(sys, "platform", "darwin")

    import agent.chrome_detect as cd_mod
    monkeypatch.setattr(cd_mod.os.path, "exists", lambda path: True)

    assert cd_mod.chrome_is_installed() is True


def test_chrome_missing(monkeypatch):
    """When Chrome binary does not exist on darwin, chrome_is_installed() returns False."""
    monkeypatch.setattr(sys, "platform", "darwin")

    import agent.chrome_detect as cd_mod
    monkeypatch.setattr(cd_mod.os.path, "exists", lambda path: False)

    assert cd_mod.chrome_is_installed() is False


def test_non_darwin_passthrough(monkeypatch):
    """On non-darwin platforms, chrome_is_installed() returns True (deferred to PLAT-02)."""
    monkeypatch.setattr(sys, "platform", "linux")

    import agent.chrome_detect as cd_mod
    assert cd_mod.chrome_is_installed() is True
