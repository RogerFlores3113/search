"""Logging setup for the CLI and MCP server (browser-use is very chatty by default).

Importing this module configures nothing; call :func:`configure_logging` from an entry point.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

LEVELS = ("debug", "info", "warning", "error")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+\\s?")
_OWN_LOGGER = "local_browser_agent"
_THIRD_PARTY_LOGGERS = ("browser_use", "bubus")
_LOGGER_NAMES = (*_THIRD_PARTY_LOGGERS, _OWN_LOGGER)
_OFF = logging.CRITICAL + 10
_TAG = "_lba_handler"


class _StripAnsi(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if "\x1b" in msg:
            record.msg, record.args = _ANSI_RE.sub("", msg), None
        return True


class _StripEmoji(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        cleaned = _EMOJI_RE.sub("", msg)
        if cleaned != msg:
            record.msg, record.args = cleaned, None
        return True


class _StderrHandler(logging.Handler):
    """Writes to whatever ``sys.stderr`` is at emit time (so redirection and capture work)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


class _NoTraceFormatter(logging.Formatter):
    """Formats records without exception tracebacks (third-party tracebacks are noise for users)."""

    def format(self, record: logging.LogRecord) -> str:
        record.exc_info = record.exc_text = None
        record.stack_info = None
        return super().format(record)


def _is_browser_use_handler(h: logging.Handler, shared: set[int]) -> bool:
    if id(h) in shared or getattr(h, _TAG, False):
        return True
    fmt = h.formatter
    return fmt is not None and type(fmt).__module__.startswith("browser_use")


def _tagged(h: logging.Handler) -> logging.Handler:
    setattr(h, _TAG, True)
    return h


def configure_logging(level: str = "warning", *, color: bool | None = None,
                      third_party: str | None = None) -> None:
    """Set library / browser-use log levels and strip ANSI codes when not on a TTY.

    ``level`` applies to this package's logger (``local_browser_agent``). ``third_party`` sets
    the level for browser-use and its event bus: one of :data:`LEVELS`, ``"off"`` (nothing,
    not even errors or tracebacks), or ``None`` for "same as ``level``". Any handler browser-use
    installed on the root logger is removed and replaced by one plain stderr handler, so no
    emoji-decorated or traceback-laden browser-use output leaks through. ``color=None`` means
    "colour only when stderr is a terminal". Safe to call repeatedly; intended for entry points
    (CLI / MCP server), never called on import.
    """
    name = (level or "warning").lower()
    if name not in LEVELS:
        raise ValueError(f"invalid log level {level!r}; choose from {', '.join(LEVELS)}")
    tp = name if third_party is None else third_party.lower()
    if tp != "off" and tp not in LEVELS:
        raise ValueError(f"invalid third-party log level {third_party!r}; choose from off, {', '.join(LEVELS)}")
    numeric = getattr(logging, name.upper())
    tp_numeric = _OFF if tp == "off" else getattr(logging, tp.upper())
    if color is None:
        try:
            color = sys.stderr.isatty()
        except Exception:
            color = False
    # browser-use reads this when it is first imported.
    os.environ["BROWSER_USE_LOGGING_LEVEL"] = tp if tp in ("debug", "info") else "result"
    try:
        import browser_use.logging_config  # noqa: F401  (importing browser_use sets up its handlers)
    except Exception:
        pass

    if logging.getLevelName(35) != "RESULT":  # browser-use's level; may be unregistered if it never set up logging
        logging.addLevelName(35, "RESULT")
    root = logging.getLogger()
    root_ids = {id(h) for h in root.handlers}
    shared: set[int] = set()  # browser-use attaches one console handler to root and to its own loggers
    for lname in _THIRD_PARTY_LOGGERS:
        shared.update(id(h) for h in logging.getLogger(lname).handlers if id(h) in root_ids)
    # Drop browser-use's console handler (and our own earlier ones) from the root logger.
    for h in list(root.handlers):
        if _is_browser_use_handler(h, shared):
            root.removeHandler(h)

    def own_handler(formatter: logging.Formatter, lvl: int, *filters: logging.Filter) -> logging.Handler:
        h = _tagged(_StderrHandler(lvl))
        h.setFormatter(formatter)
        for f in filters:
            h.addFilter(f)
        return h

    plain = "%(levelname)s: %(message)s"
    for lname in _THIRD_PARTY_LOGGERS:
        lg = logging.getLogger(lname)
        for h in list(lg.handlers):  # replace browser-use's console handler with ours
            if _is_browser_use_handler(h, shared):
                lg.removeHandler(h)
        lg.setLevel(tp_numeric)
        lg.propagate = False
        if tp != "off":
            lg.addHandler(own_handler(_NoTraceFormatter(plain), tp_numeric, _StripAnsi(), _StripEmoji()))
        for h in lg.handlers:  # handlers someone else added keep working, minus colour codes
            h.setLevel(tp_numeric)
            if not color and not any(isinstance(f, _StripAnsi) for f in h.filters):
                h.addFilter(_StripAnsi())

    own = logging.getLogger(_OWN_LOGGER)
    own.setLevel(numeric)
    for h in list(own.handlers):
        if getattr(h, _TAG, False):
            own.removeHandler(h)
    for h in own.handlers:
        h.setLevel(numeric)
        if not color and not any(isinstance(f, _StripAnsi) for f in h.filters):
            h.addFilter(_StripAnsi())
    # Our logger propagates to root. If the host application has its own root handlers they get
    # the records; otherwise ours does.
    if not [h for h in root.handlers if not getattr(h, _TAG, False)]:
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(own_handler(logging.Formatter(plain), logging.NOTSET, _StripAnsi()))
    for h in root.handlers:
        if not getattr(h, _TAG, False):
            h.setLevel(logging.NOTSET)
            if not color and not any(isinstance(f, _StripAnsi) for f in h.filters):
                h.addFilter(_StripAnsi())


def format_validation_error(exc: BaseException) -> str:
    """One ``field: message`` line per problem, without pydantic's header and docs-URL boilerplate."""
    errors: Any = None
    try:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            errors = exc.errors()
    except Exception:  # pragma: no cover
        pass
    if errors is not None:
        lines = []
        for e in errors:
            loc = ".".join(str(p) for p in e.get("loc", ()))
            msg = str(e.get("msg", "")).removeprefix("Value error, ")
            lines.append(f"{loc}: {msg}" if loc else msg)
        return "\n".join(dict.fromkeys(lines)) or "invalid value"
    text = str(exc)
    text = re.sub(r"^\d+ validation errors? for \w+\s*\n?", "", text)
    text = re.sub(r"\n?\s*For further information visit \S+", "", text)
    text = re.sub(r"\s*\[type=[^\]]*\]", "", text)
    return text.strip() or exc.__class__.__name__
