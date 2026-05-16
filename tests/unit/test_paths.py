"""Tests for agent/paths.py — frozen-aware path resolution (DIST-01)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_dev_mode_returns_local_data_dir(tmp_path, monkeypatch):
    """In dev mode (sys.frozen unset), get_user_data_dir() returns Path('data')."""
    monkeypatch.chdir(tmp_path)
    # Ensure frozen is NOT set
    monkeypatch.delattr(sys, "frozen", raising=False)
    import agent.paths as paths_mod
    importlib.reload(paths_mod)
    result = paths_mod.get_user_data_dir()
    assert result == Path("data")
    assert result.exists()


def test_frozen_mode_returns_platformdirs(tmp_path, monkeypatch):
    """In frozen mode (sys.frozen=True), get_user_data_dir() returns the platformdirs path."""
    import platformdirs
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    import agent.paths as paths_mod
    importlib.reload(paths_mod)
    result = paths_mod.get_user_data_dir()
    expected = Path(platformdirs.user_data_dir("local-browser-agent"))
    assert result == expected


def test_idempotent_mkdir(tmp_path, monkeypatch):
    """Calling get_user_data_dir() twice does not raise even if the dir already exists."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    import agent.paths as paths_mod
    importlib.reload(paths_mod)
    paths_mod.get_user_data_dir()
    paths_mod.get_user_data_dir()  # Second call must not raise
