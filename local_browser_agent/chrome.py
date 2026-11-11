"""Locate a locally installed Chrome/Chromium without ever launching or installing one."""
from __future__ import annotations

import os
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


def windows_chrome_paths() -> list[str]:
    """Candidate Chrome paths on Windows (env vars may be absent, so use ``.get``)."""
    out = []
    for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "ProgramFiles(x86)"):
        base = os.environ.get(env_var)
        if base:
            out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return out


def find_chrome(channel: str | None = "chrome") -> str | None:
    """Return the path of an installed Chrome (or Chromium on Linux/macOS), else ``None``.

    ``channel`` is accepted for symmetry with ``BrowserConfig.channel``; a ``chromium*``
    channel prefers Chromium names, anything else prefers Google Chrome.
    """
    prefer_chromium = bool(channel) and str(channel).lower().startswith("chromium")
    if sys.platform == "darwin":
        paths = [CHROMIUM_PATH_MACOS, CHROME_PATH_MACOS] if prefer_chromium else [CHROME_PATH_MACOS, CHROMIUM_PATH_MACOS]
        return next((p for p in paths if os.path.exists(p)), None)
    if sys.platform == "win32":
        return next((p for p in windows_chrome_paths() if os.path.exists(p)), None)
    names = _LINUX_NAMES
    if prefer_chromium:
        names = tuple(n for n in _LINUX_NAMES if n.startswith("chromium")) + tuple(
            n for n in _LINUX_NAMES if not n.startswith("chromium"))
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in _LINUX_FIXED if os.path.exists(p)), None)
