"""Locate a locally installed Chrome/Chromium without ever launching or installing one."""
from __future__ import annotations

import os
import posixpath
import shutil
import sys

from local_browser_agent.models import PreFlightError

CHROME_PATH_MACOS = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROMIUM_PATH_MACOS = "/Applications/Chromium.app/Contents/MacOS/Chromium"
_LINUX_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
_LINUX_FIXED = ("/opt/google/chrome/chrome",)

CHROME_NOT_FOUND_MESSAGE = (
    "Google Chrome was not found. Install it from https://www.google.com/chrome/ or set "
    "BrowserConfig.executable_path / cdp_url (LBA_EXECUTABLE_PATH / LBA_CDP_URL)."
)


class ChromeNotFoundError(PreFlightError):
    """No Chrome/Chromium executable could be located on this machine."""

    def __init__(self, message: str = CHROME_NOT_FOUND_MESSAGE) -> None:
        super().__init__(message)


_MAC_APPS = {
    "chrome": "Google Chrome.app/Contents/MacOS/Google Chrome",
    "chrome-beta": "Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "chrome-dev": "Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
    "chrome-canary": "Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "msedge": "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "chromium": "Chromium.app/Contents/MacOS/Chromium",
}
# Path under a LocalAppData / Program Files base, per channel on Windows.
_WIN_APPS = {
    "chrome": ("Google", "Chrome", "Application", "chrome.exe"),
    "chrome-beta": ("Google", "Chrome Beta", "Application", "chrome.exe"),
    "chrome-dev": ("Google", "Chrome Dev", "Application", "chrome.exe"),
    "chrome-canary": ("Google", "Chrome SxS", "Application", "chrome.exe"),
    "msedge": ("Microsoft", "Edge", "Application", "msedge.exe"),
}
_LINUX_CHANNEL_NAMES = {
    "chrome": _LINUX_NAMES,
    "chrome-beta": ("google-chrome-beta",),
    "chrome-dev": ("google-chrome-unstable",),
    "chrome-canary": (),
    "msedge": ("microsoft-edge", "microsoft-edge-stable"),
    "chromium": ("chromium", "chromium-browser"),
}
_LINUX_CHANNEL_FIXED = {
    "chrome": _LINUX_FIXED,
    "chrome-beta": ("/opt/google/chrome-beta/chrome",),
    "chrome-dev": ("/opt/google/chrome-unstable/chrome",),
    "msedge": ("/opt/microsoft/msedge/msedge",),
}


def _channel_key(channel: str | None) -> str:
    c = (channel or "chrome").strip().lower()
    if c.startswith("chromium"):
        return "chromium"
    return c if c in _MAC_APPS else "chrome"


def windows_chrome_paths(channel: str | None = "chrome") -> list[str]:
    """Candidate browser paths on Windows (env vars may be absent, so use ``.get``)."""
    rel = _WIN_APPS.get(_channel_key(channel))
    if rel is None:
        return []
    out = []
    for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            out.append(os.path.join(base, *rel))
    return out


def find_chrome(channel: str | None = "chrome") -> str | None:
    """Return the path of an installed browser for ``channel``, else ``None``.

    Channels: ``chrome`` (default; on Linux/macOS also falls back to Chromium), ``chrome-beta``,
    ``chrome-dev``, ``chrome-canary``, ``msedge`` and ``chromium*`` (prefers Chromium, then
    Chrome). Unknown channels behave like ``chrome``. Never launches or installs anything.
    """
    key = _channel_key(channel)
    if sys.platform == "darwin":
        names = [_MAC_APPS[key]]
        if key == "chrome":
            names.append(_MAC_APPS["chromium"])
        elif key == "chromium":
            names.append(_MAC_APPS["chrome"])
        roots = ("/Applications", os.path.expanduser("~/Applications"))
        # macOS paths are POSIX; posixpath keeps them correct even when tests simulate darwin elsewhere.
        paths = [posixpath.join(r, n) for n in names for r in roots]
        return next((p for p in paths if os.path.exists(p)), None)
    if sys.platform == "win32":
        return next((p for p in windows_chrome_paths(key) if os.path.exists(p)), None)
    names = _LINUX_CHANNEL_NAMES.get(key, ())
    fixed = _LINUX_CHANNEL_FIXED.get(key, ())
    if key == "chromium":
        names, fixed = names + _LINUX_NAMES, _LINUX_FIXED
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in fixed if os.path.exists(p)), None)
