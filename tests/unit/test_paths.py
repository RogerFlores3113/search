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


def test_db_path_uses_user_data_dir_when_frozen(tmp_path, monkeypatch):
    """When sys.frozen=True and agent.db is reloaded, DB_PATH resolves under user_data_dir."""
    import platformdirs
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    # Reload agent.paths so frozen branch is active
    import agent.paths as paths_mod
    importlib.reload(paths_mod)

    # Reload agent.db to re-evaluate module-level DB_PATH constant
    import agent.db as db_mod
    importlib.reload(db_mod)

    expected = Path(platformdirs.user_data_dir("local-browser-agent")) / "history.db"
    assert db_mod.DB_PATH == expected


def test_training_file_uses_user_data_dir_when_frozen(tmp_path, monkeypatch):
    """When sys.frozen=True and agent.runner is reloaded, TRAINING_FILE resolves under user_data_dir."""
    import platformdirs
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    import agent.paths as paths_mod
    importlib.reload(paths_mod)

    import agent.runner as runner_mod
    importlib.reload(runner_mod)

    expected = Path(platformdirs.user_data_dir("local-browser-agent")) / "training" / "runs.jsonl"
    assert runner_mod.TRAINING_FILE == expected


def test_resource_path_helper_uses_meipass_when_frozen(monkeypatch):
    """_resource_path returns sys._MEIPASS / relative when frozen.

    Dev mode (Phase 9 update): resolves the path against the project root
    (parent of the `agent` package) so callers that chdir away from the
    project root — e.g., pytest fixtures using tmp_path for the /runs
    JSONL aggregator integration tests — still find bundled resources
    like agent/templates and agent/static. Falls back to the raw relative
    string when the candidate does not exist.
    """
    fake_meipass = "/fake/meipass"

    # Test frozen branch
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)

    import agent.main as main_mod
    importlib.reload(main_mod)

    result = main_mod._resource_path("agent/templates")
    assert result == str(Path(fake_meipass) / "agent/templates")

    # Test dev branch — Phase 9: resolves against project root
    monkeypatch.delattr(sys, "frozen", raising=False)
    importlib.reload(main_mod)

    result_dev = main_mod._resource_path("agent/templates")
    project_root = Path(main_mod.__file__).resolve().parent.parent
    expected_dev = str(project_root / "agent/templates")
    assert result_dev == expected_dev

    # Non-existent relative path falls back to the raw string
    result_missing = main_mod._resource_path("definitely/not/here")
    assert result_missing == "definitely/not/here"
