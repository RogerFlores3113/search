"""Logging setup for the CLI and MCP server (browser-use is very chatty by default).

Importing this module configures nothing; call :func:`configure_logging` from an entry point.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import threading
from collections.abc import Iterator
from typing import Any

LEVELS = ("debug", "info", "warning", "error")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+\\s?")
_OWN_LOGGER = "local_browser_agent"
_THIRD_PARTY_LOGGERS = ("browser_use", "bubus")
_LOGGER_NAMES = (*_THIRD_PARTY_LOGGERS, _OWN_LOGGER)
_DOMAIN_LIST_LOGGER = "browser_use.utils"
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


class _DomainListWarning(logging.Filter):
    """Drops browser-use's "Optimizing domain list ... pattern matching is not supported for lists >= 100"
    warning: wildcard entries are handled by this project itself, so the hint is misleading."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "Optimizing domain list" not in record.getMessage()
        except Exception:
            return True


_START_FAILURE_MARKERS = ("BrowserSession.on_BrowserStartEvent", "Root CDP client not initialized",
                          "Agent run failed with exception")


class _StartFailureNoise(logging.Filter):
    """Drops browser-use's multi-line ERROR records about a failed browser start / agent run.

    The same failure is always reported once, cleanly, in ``RunResult.errors`` / ``error_kind``; the
    raw records ("Root CDP client not initialized", ...) only repeat it. Used for quiet third-party
    levels (warning and above); at info / debug they are kept."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.ERROR:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(m in msg for m in _START_FAILURE_MARKERS)


class _QuietUnlessVerbose(logging.Filter):
    """Wraps a noise filter so it only applies while ``browser_use`` is at WARNING or above.

    Installed on browser-use's own loggers while a run is in flight (see :func:`install_quiet_filters`),
    independent of any handler the host application has; a host that sets ``browser_use`` to INFO
    or DEBUG still sees everything."""

    def __init__(self, inner: logging.Filter) -> None:
        super().__init__()
        self.inner = inner

    def filter(self, record: logging.LogRecord) -> bool:
        if logging.getLogger("browser_use").getEffectiveLevel() <= logging.INFO:
            return True
        return bool(self.inner.filter(record))


_QUIET_ATTR = "_lba_quiet_filters"
_quiet_lock = threading.RLock()
_quiet_count = 0
_quiet_state: dict[str, Any] = {}


def _quiet_filters() -> list[logging.Filter]:
    return [_QuietUnlessVerbose(_DomainListWarning()), _QuietUnlessVerbose(_StartFailureNoise())]


def _is_bu(name: str) -> bool:
    return name == "browser_use" or name.startswith("browser_use.")


def _quiet(lg: logging.Logger) -> None:
    if not getattr(lg, _QUIET_ATTR, False):
        for f in _quiet_filters():
            lg.addFilter(f)
        setattr(lg, _QUIET_ATTR, True)


def _unquiet(lg: logging.Logger) -> None:
    for f in [f for f in lg.filters if isinstance(f, _QuietUnlessVerbose)]:
        lg.removeFilter(f)
    try:
        delattr(lg, _QUIET_ATTR)
    except AttributeError:
        pass


def install_quiet_filters() -> None:
    """Drop browser-use's redundant failure noise regardless of the host's logging handlers.

    Logger-level filters only see records created on that exact logger, and browser-use logs from
    ``browser_use.utils`` (the "Optimizing domain list" warning) and from per-instance loggers named
    ``browser_use.BrowserSession...`` / ``browser_use.Agent...`` (the start-failure ERROR records and
    the "Agent run failed with exception" traceback). The per-instance ones are created on demand, so
    new ``browser_use.*`` loggers get the filters through the logger manager's factory.

    Reference counted: every call must be paired with :func:`uninstall_quiet_filters` (or use
    :func:`quiet_filters`); the manager's previous ``loggerClass`` is restored and the filters removed
    when the count reaches zero. Never called on import; the library's run paths hold it while a run
    is in flight and the CLI / MCP entry points hold it for the process lifetime."""
    global _quiet_count
    with _quiet_lock:
        _quiet_count += 1
        mgr = logging.Logger.manager
        if _quiet_count == 1:
            previous = mgr.loggerClass

            def factory(name: str) -> logging.Logger:
                # Defer to the manager's own class if it had one, else to whatever class the host set
                # with setLoggerClass (looked up now, so a later call is honoured). ``previous`` may be
                # any callable, so the logger is built first and the filters attached afterwards.
                lg = (previous or logging.getLoggerClass())(name)
                if _is_bu(name):
                    _quiet(lg)
                return lg

            factory._lba_factory = True  # type: ignore[attr-defined]
            _quiet_state["previous"] = previous
            _quiet_state["factory"] = factory
            mgr.loggerClass = factory  # type: ignore[assignment]
        for lname, lg in list(mgr.loggerDict.items()):  # loggers created before this ran
            if isinstance(lg, logging.Logger) and _is_bu(lname):
                _quiet(lg)


def uninstall_quiet_filters() -> None:
    """Undo one :func:`install_quiet_filters`; the last one restores the logging state."""
    global _quiet_count
    with _quiet_lock:
        if _quiet_count == 0:
            return
        _quiet_count -= 1
        if _quiet_count:
            return
        mgr = logging.Logger.manager
        if mgr.loggerClass is _quiet_state.get("factory"):  # a host that replaced it since keeps its choice
            mgr.loggerClass = _quiet_state.get("previous")  # type: ignore[assignment]
        _quiet_state.clear()
        for lname, lg in list(mgr.loggerDict.items()):
            if isinstance(lg, logging.Logger) and (_is_bu(lname) or getattr(lg, _QUIET_ATTR, False)):
                _unquiet(lg)


@contextlib.contextmanager
def quiet_filters() -> Iterator[None]:
    """Hold :func:`install_quiet_filters` for the duration of the ``with`` block."""
    install_quiet_filters()
    try:
        yield
    finally:
        uninstall_quiet_filters()


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
    # browser-use reads this only when its own logging setup runs (BROWSER_USE_SETUP_LOGGING is
    # off by default here); the levels below are what actually applies.
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
    # browser-use emits it from the `browser_use.utils` logger (BrowserProfile's validator). A filter
    # on a logger only sees records logged directly on it, so attach to that exact logger.
    src = logging.getLogger(_DOMAIN_LIST_LOGGER)
    for f in [f for f in src.filters if isinstance(f, _DomainListWarning)]:
        src.removeFilter(f)
    if tp_numeric > logging.DEBUG:
        src.addFilter(_DomainListWarning())
    for lname in _THIRD_PARTY_LOGGERS:
        lg = logging.getLogger(lname)
        for h in list(lg.handlers):  # replace browser-use's console handler with ours
            if _is_browser_use_handler(h, shared):
                lg.removeHandler(h)
        lg.setLevel(tp_numeric)
        lg.propagate = False
        if tp != "off":
            extra = (_StartFailureNoise(),) if tp_numeric >= logging.WARNING else ()
            lg.addHandler(own_handler(_NoTraceFormatter(plain), tp_numeric, _StripAnsi(), _StripEmoji(), *extra))
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
