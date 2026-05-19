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


# --- WIN-03: Windows Chrome detection ---


def test_windows_localappdata_found(monkeypatch):
    """chrome_is_installed() returns True when LOCALAPPDATA/Google/Chrome path exists."""
    monkeypatch.setattr(sys, "platform", "win32")
    import agent.chrome_detect as cd_mod
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    monkeypatch.setattr(cd_mod.os.path, "exists", lambda p: "AppData\\Local" in p)
    assert cd_mod.chrome_is_installed() is True


def test_windows_programfiles_fallback(monkeypatch):
    """When LOCALAPPDATA Chrome missing, falls back to PROGRAMFILES."""
    monkeypatch.setattr(sys, "platform", "win32")
    import agent.chrome_detect as cd_mod
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    # Only PROGRAMFILES path exists
    monkeypatch.setattr(
        cd_mod.os.path, "exists",
        lambda p: "Program Files" in p and "AppData" not in p,
    )
    assert cd_mod.chrome_is_installed() is True


def test_windows_x86_fallback(monkeypatch):
    """When LOCALAPPDATA and PROGRAMFILES missing, falls back to ProgramFiles(x86)."""
    monkeypatch.setattr(sys, "platform", "win32")
    import agent.chrome_detect as cd_mod
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.setattr(cd_mod.os.path, "exists", lambda p: "Program Files (x86)" in p)
    assert cd_mod.chrome_is_installed() is True


def test_windows_chrome_missing(monkeypatch):
    """chrome_is_installed() returns False when none of the three Windows paths exist."""
    monkeypatch.setattr(sys, "platform", "win32")
    import agent.chrome_detect as cd_mod
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    monkeypatch.setenv("PROGRAMFILES", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.setattr(cd_mod.os.path, "exists", lambda p: False)
    assert cd_mod.chrome_is_installed() is False
