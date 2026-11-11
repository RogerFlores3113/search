"""Tests for local_browser_agent/app/paths.py — frozen-aware path resolution (DIST-01)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _restore_path_modules(monkeypatch, tmp_path):
    """Tests here reload paths/db/training_sink under altered env; restore them afterwards."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))  # never touch the real HOME
    yield
    monkeypatch.undo()
    import local_browser_agent.app.paths as p
    import local_browser_agent.app.db as d
    import local_browser_agent.app.training_sink as t
    for m in (p, d, t):
        importlib.reload(m)


def _fresh_paths(monkeypatch, *, frozen=False):
    monkeypatch.delenv("LBA_DATA_DIR", raising=False)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    import local_browser_agent.app.paths as paths_mod
    return importlib.reload(paths_mod)


def test_source_checkout_uses_repo_data_dir_regardless_of_cwd(tmp_path, monkeypatch):
    """From a source checkout the data dir is <repo>/data, an absolute path, whatever the cwd."""
    monkeypatch.chdir(tmp_path)
    paths_mod = _fresh_paths(monkeypatch)
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: None)  # do not create <repo>/data
    result = paths_mod.get_user_data_dir()
    assert result == REPO_ROOT / "data"
    assert result.is_absolute()
    assert not (tmp_path / "data").exists()


def test_installed_package_uses_platformdirs(tmp_path, monkeypatch):
    """Without a project checkout (site-packages install) the platformdirs dir is used."""
    import platformdirs
    paths_mod = _fresh_paths(monkeypatch)
    monkeypatch.setattr(paths_mod, "_source_checkout_root", lambda: None)
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda appname=None, *a, **k: str(tmp_path / "ud" / (appname or "")))
    result = paths_mod.get_user_data_dir()
    assert result == tmp_path / "ud" / "local-browser-agent"
    assert result.is_dir()


def test_checkout_detection_needs_matching_project_name(tmp_path, monkeypatch):
    paths_mod = _fresh_paths(monkeypatch)
    fake_pkg = tmp_path / "other" / "local_browser_agent" / "app"
    fake_pkg.mkdir(parents=True)
    (tmp_path / "other" / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    monkeypatch.setattr(paths_mod, "__file__", str(fake_pkg / "paths.py"))
    assert paths_mod._source_checkout_root() is None
    (tmp_path / "other" / "pyproject.toml").write_text('[project]\nname = "local-browser-agent"\n')
    assert paths_mod._source_checkout_root() == tmp_path / "other"


@pytest.mark.parametrize("frozen", [False, True])
def test_env_override_wins_in_every_mode(tmp_path, monkeypatch, frozen):
    paths_mod = _fresh_paths(monkeypatch, frozen=frozen)
    monkeypatch.setenv("LBA_DATA_DIR", str(tmp_path / "custom"))
    result = paths_mod.get_user_data_dir()
    assert result == (tmp_path / "custom").resolve()
    assert result.is_dir()
    assert paths_mod.get_secret_key() == paths_mod.get_secret_key()
    assert (result / "secret.bin").is_file()


def test_frozen_mode_returns_platformdirs(tmp_path, monkeypatch):
    """In frozen mode (sys.frozen=True), get_user_data_dir() returns the platformdirs path."""
    import platformdirs
    monkeypatch.delenv("LBA_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    import local_browser_agent.app.paths as paths_mod
    importlib.reload(paths_mod)
    result = paths_mod.get_user_data_dir()
    expected = Path(platformdirs.user_data_dir("local-browser-agent"))
    assert result == expected


def test_idempotent_mkdir(tmp_path, monkeypatch):
    """Calling get_user_data_dir() twice does not raise even if the dir already exists."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    import local_browser_agent.app.paths as paths_mod
    importlib.reload(paths_mod)
    paths_mod.get_user_data_dir()
    paths_mod.get_user_data_dir()  # Second call must not raise


def test_db_path_uses_user_data_dir_when_frozen(tmp_path, monkeypatch):
    """When sys.frozen=True and local_browser_agent.app.db is reloaded, DB_PATH resolves under user_data_dir."""
    import platformdirs
    monkeypatch.delenv("LBA_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    # Reload local_browser_agent.app.paths so frozen branch is active
    import local_browser_agent.app.paths as paths_mod
    importlib.reload(paths_mod)

    # Reload local_browser_agent.app.db to re-evaluate module-level DB_PATH constant
    import local_browser_agent.app.db as db_mod
    importlib.reload(db_mod)

    expected = Path(platformdirs.user_data_dir("local-browser-agent")) / "history.db"
    assert db_mod.DB_PATH == expected


def test_training_file_uses_user_data_dir_when_frozen(tmp_path, monkeypatch):
    """When sys.frozen=True and local_browser_agent.app.training_sink is reloaded, TRAINING_FILE resolves under user_data_dir."""
    import platformdirs
    monkeypatch.delenv("LBA_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    import local_browser_agent.app.paths as paths_mod
    importlib.reload(paths_mod)

    import local_browser_agent.app.training_sink as runner_mod
    importlib.reload(runner_mod)

    expected = Path(platformdirs.user_data_dir("local-browser-agent")) / "training" / "runs.jsonl"
    assert runner_mod.TRAINING_FILE == expected


def test_resource_path_helper_uses_meipass_when_frozen(monkeypatch):
    """_resource_path returns sys._MEIPASS / relative when frozen.

    Dev mode (Phase 9 update): resolves the path against the project root
    (parent of the `agent` package) so callers that chdir away from the
    project root — e.g., pytest fixtures using tmp_path for the /runs
    JSONL aggregator integration tests — still find bundled resources
    like local_browser_agent/app/templates and local_browser_agent/app/static. Falls back to the raw relative
    string when the candidate does not exist.
    """
    fake_meipass = "/fake/meipass"

    # Test frozen branch
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", fake_meipass, raising=False)

    import local_browser_agent.app.main as main_mod
    importlib.reload(main_mod)

    result = main_mod._resource_path("local_browser_agent/app/templates")
    assert result == str(Path(fake_meipass) / "local_browser_agent/app/templates")

    # Test dev branch — Phase 9: resolves against project root
    monkeypatch.delattr(sys, "frozen", raising=False)
    importlib.reload(main_mod)

    result_dev = main_mod._resource_path("local_browser_agent/app/templates")
    project_root = Path(main_mod.__file__).resolve().parent.parent.parent
    expected_dev = str(project_root / "local_browser_agent/app/templates")
    assert result_dev == expected_dev

    # Non-existent relative path falls back to the raw string
    result_missing = main_mod._resource_path("definitely/not/here")
    assert result_missing == "definitely/not/here"
