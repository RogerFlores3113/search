"""Tests for agent/launcher.py and frozen __main__.py (DIST-03)."""
from __future__ import annotations

import sys
import threading
import time

import pytest


def test_schedule_browser_open_returns_timer():
    """schedule_browser_open() returns a threading.Timer instance with daemon=True."""
    from agent.launcher import schedule_browser_open

    t = schedule_browser_open(delay=9999.0)  # long delay so it doesn't fire during test
    try:
        assert isinstance(t, threading.Timer)
        assert t.daemon is True
    finally:
        t.cancel()


def test_schedule_browser_open_calls_webbrowser(monkeypatch):
    """When the timer fires, webbrowser.open is called with the URL."""
    opened_urls = []

    import agent.launcher as launcher_mod
    monkeypatch.setattr(launcher_mod.webbrowser, "open", lambda url: opened_urls.append(url))

    t = launcher_mod.schedule_browser_open(url="http://127.0.0.1:8080", delay=0.01)
    # Wait long enough for the timer to fire
    t.join(timeout=2.0)

    assert opened_urls == ["http://127.0.0.1:8080"]


def test_main_redirects_paths_when_frozen(monkeypatch):
    """When sys.frozen=True, calling main() triggers path redirect side-effects."""
    import importlib
    import platformdirs

    monkeypatch.setattr(sys, "frozen", True, raising=False)

    # Stub uvicorn.run so it doesn't actually start a server
    import agent.__main__ as main_mod
    importlib.reload(main_mod)

    monkeypatch.setattr(main_mod.uvicorn, "run", lambda *a, **kw: None)
    # Stub schedule_browser_open so timer doesn't fire
    monkeypatch.setattr(main_mod, "schedule_browser_open", lambda **kw: None)
    # Stub chrome_is_installed so it doesn't do OS calls
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: True)

    main_mod.main()

    # After frozen main() runs, DB_PATH and TRAINING_FILE should point under user_data_dir
    import agent.db as db_mod
    import agent.runner as runner_mod
    user_dir = platformdirs.user_data_dir("local-browser-agent")

    assert str(db_mod.DB_PATH).startswith(user_dir)
    assert str(runner_mod.TRAINING_FILE).startswith(user_dir)


def test_main_sets_chrome_missing_flag_when_chrome_absent(monkeypatch):
    """When chrome_is_installed returns False, main() sets app.state.chrome_missing=True."""
    import importlib

    monkeypatch.delattr(sys, "frozen", raising=False)

    import agent.__main__ as main_mod
    importlib.reload(main_mod)

    monkeypatch.setattr(main_mod.uvicorn, "run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "schedule_browser_open", lambda **kw: None)
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: False)

    main_mod.main()

    from agent.main import app
    assert app.state.chrome_missing is True

    # Cleanup
    app.state.chrome_missing = False
