"""Logging setup for the CLI and MCP server (browser-use is very chatty by default)."""
from __future__ import annotations

import logging
import os
import re
import sys

LEVELS = ("debug", "info", "warning", "error")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOGGER_NAMES = ("browser_use", "bubus", "local_browser_agent")


class _StripAnsi(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if "\x1b" in msg:
            record.msg, record.args = _ANSI_RE.sub("", msg), None
        return True


def configure_logging(level: str = "warning", *, color: bool | None = None) -> None:
    """Set browser-use / library log levels and strip ANSI codes when not on a TTY.

    ``color=None`` means "colour only when stderr is a terminal". Safe to call repeatedly.
    """
    name = (level or "warning").lower()
    if name not in LEVELS:
        raise ValueError(f"invalid log level {level!r}; choose from {', '.join(LEVELS)}")
    numeric = getattr(logging, name.upper())
    if color is None:
        try:
            color = sys.stderr.isatty()
        except Exception:
            color = False
    # browser-use reads this when it is first imported.
    os.environ["BROWSER_USE_LOGGING_LEVEL"] = name if name in ("debug", "info") else "result"
    try:
        import browser_use.logging_config  # noqa: F401  (importing browser_use sets up its handlers)
    except Exception:
        pass
    for lname in _LOGGER_NAMES:
        lg = logging.getLogger(lname)
        lg.setLevel(numeric)
        for h in lg.handlers:
            h.setLevel(numeric)
            if not color and not any(isinstance(f, _StripAnsi) for f in h.filters):
                h.addFilter(_StripAnsi())
    # Handlers shared with the root logger (browser-use attaches one console handler everywhere).
    for h in logging.getLogger().handlers:
        h.setLevel(numeric)
        if not color and not any(isinstance(f, _StripAnsi) for f in h.filters):
            h.addFilter(_StripAnsi())
