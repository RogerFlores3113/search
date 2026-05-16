"""Browser auto-open scheduler for local-browser-agent (DIST-03).

Uses threading.Timer to open the user's default browser to localhost:8080
approximately 2 seconds after uvicorn starts binding — without blocking the
main thread.

Source: docs.python.org/3/library/webbrowser.html
See: .planning/phases/04-distribution/04-RESEARCH.md Pattern 4
"""
from __future__ import annotations

import threading
import webbrowser


def schedule_browser_open(
    url: str = "http://127.0.0.1:8080",
    delay: float = 2.0,
) -> threading.Timer:
    """Schedule opening `url` in the default browser after `delay` seconds.

    Returns the Timer so the caller can cancel() it if needed (e.g. in tests).
    The timer thread is daemonized so it does not prevent process exit if the
    server shuts down before the timer fires.

    Args:
        url: The URL to open (default: http://127.0.0.1:8080).
        delay: Seconds to wait before opening (default: 2.0, gives uvicorn
               time to bind the port before the browser hits it).

    Returns:
        The started threading.Timer instance.
    """
    t = threading.Timer(delay, webbrowser.open, args=[url])
    t.daemon = True
    t.start()
    return t
