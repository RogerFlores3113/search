"""Chrome installation detection for local-browser-agent (DIST-02).

Checks whether Google Chrome is installed at its standard macOS path.
Non-macOS platforms return True — detection deferred to PLAT-01/02.

Source: gist.github.com/primaryobjects/d5346bf7a173dbded1a70375ff7461b4
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 3
"""
from __future__ import annotations

import os
import sys

CHROME_PATH_MACOS = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_is_installed() -> bool:
    """Return True if Google Chrome is found at its standard macOS path.

    On non-macOS platforms, returns True without checking (deferred to PLAT-01/02).
    This avoids blocking the app on platforms where the Chrome path is different;
    Playwright will surface a useful error if Chrome is truly missing.
    """
    if sys.platform == "darwin":
        return os.path.exists(CHROME_PATH_MACOS)
    # Windows/Linux paths for future PLAT-01/02 — placeholder
    return True  # Non-Mac: don't block, let Playwright fail with its own error
