"""Chrome installation detection for local-browser-agent (DIST-02, WIN-03).

Checks whether Google Chrome is installed at its standard path.
Covers darwin (macOS) and win32 (Windows via LOCALAPPDATA / PROGRAMFILES / ProgramFiles(x86)).
Linux/other platforms return True — detection not needed for supported platforms.

Source: gist.github.com/primaryobjects/d5346bf7a173dbded1a70375ff7461b4
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 3
See: .planning/phases/14-windows-distribution/14-RESEARCH.md Pattern 3
"""
from __future__ import annotations

import os
import sys

CHROME_PATH_MACOS = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _windows_chrome_paths() -> list[str]:
    """Return ordered list of candidate Chrome paths for Windows.

    Uses os.environ.get() (not os.environ[]) — safe in frozen context where
    env vars may be absent in non-standard corporate configurations.
    """
    candidates = []
    for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            candidates.append(
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            )
    return candidates


def chrome_is_installed() -> bool:
    """Return True if Google Chrome is found at its standard installation path.

    Covers darwin (macOS standard path) and win32 (LOCALAPPDATA / PROGRAMFILES /
    ProgramFiles(x86) in priority order). Linux/other platforms return True without
    checking — Playwright will surface a useful error if Chrome is truly missing.
    """
    if sys.platform == "darwin":
        return os.path.exists(CHROME_PATH_MACOS)
    if sys.platform == "win32":
        return any(os.path.exists(p) for p in _windows_chrome_paths())
    return True  # Linux/other: don't block
