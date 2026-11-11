"""Chrome installation detection for local-browser-agent (DIST-02, WIN-03).

Thin wrapper over :func:`local_browser_agent.chrome.find_chrome`, which covers macOS,
Windows (LOCALAPPDATA / PROGRAMFILES / ProgramFiles(x86)) and Linux (PATH + /opt).
"""
from __future__ import annotations

import os

from local_browser_agent.chrome import CHROME_PATH_MACOS, find_chrome, windows_chrome_paths

__all__ = ["CHROME_PATH_MACOS", "chrome_is_installed", "os"]


def _windows_chrome_paths() -> list[str]:
    return windows_chrome_paths()


def chrome_is_installed() -> bool:
    """Return True if a Chrome/Chromium executable can be found on this machine."""
    return find_chrome() is not None
