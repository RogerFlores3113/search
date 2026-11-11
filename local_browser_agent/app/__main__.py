"""Frozen-aware entrypoint for local-browser-agent (DIST-01, DIST-02, DIST-03).

When running as a frozen .app bundle (sys.frozen=True):
  - Redirects DB_PATH and TRAINING_FILE to ~/Library/Application Support/local-browser-agent/
  - Sets up logging to user_data_dir / "app.log" (errors visible even with console=False)

Always:
  - Checks Chrome installation and sets app.state.chrome_missing accordingly
  - Schedules browser auto-open 2s after uvicorn binds
  - Preserves backward-compatible sys.argv task-string behavior for dev mode

Source: PyInstaller runtime docs + platformdirs docs + playwright detection research
See: .planning/phases/04-distribution/04-RESEARCH.md "Code Examples" section
"""
from __future__ import annotations

import argparse
import multiprocessing
import socket
import sys

import uvicorn

from local_browser_agent.app.chrome_detect import chrome_is_installed
from local_browser_agent.app.launcher import schedule_browser_open
from local_browser_agent.app.main import app


def redirect_data_paths() -> None:
    """Patch module-level path constants to user_data_dir when running frozen.

    Must be called before any async code uses local_browser_agent.app.db or local_browser_agent.app.training_sink.
    In dev mode this is a no-op — paths stay as get_user_data_dir() already set.
    """
    if not getattr(sys, "frozen", False):
        return

    from local_browser_agent.app.paths import get_user_data_dir
    user_dir = get_user_data_dir()

    import local_browser_agent.app.db as db_module
    db_module.DB_PATH = user_dir / "history.db"

    import local_browser_agent.app.training_sink as training_sink_module
    training_sink_module.TRAINING_FILE = user_dir / "training" / "runs.jsonl"
    (user_dir / "training").mkdir(parents=True, exist_ok=True)


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

REQUIRED_TEMPLATES = ("index.html", "no_chrome.html", "runs_fragment.html")
REQUIRED_STATIC = (
    "style.css",
    "vendor/htmx.min.js",
    "vendor/htmx-ext-sse.js",
    "vendor/alpinejs.min.js",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lba-app",
        allow_abbrev=False,
        description=(
            "Start the local-browser-agent web UI. It drives your own Chrome from this "
            "machine; the server only accepts requests addressed to localhost."
        ),
    )
    parser.add_argument(
        "task", nargs="*",
        help="optional task to run immediately when the server starts (dev convenience); "
             "put -- before a task that starts with a dash",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (loopback only; default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="port to listen on (default: 8080)")
    parser.add_argument("--no-open", action="store_true",
                        help="do not open the UI in your default browser")
    parser.add_argument("--smoke", action="store_true",
                        help="check that every module, template, static file and browser-use "
                             "prompt file is present, then exit 0 (non-zero on failure); "
                             "starts no server and no browser")
    return parser


def _port_free(host: str, port: int) -> bool:
    """True when ``host:port`` can be bound right now (same options uvicorn binds with)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def smoke_check() -> list[str]:
    """Return a list of problems (empty when the install looks complete).

    Imports every module the app needs and checks bundled resources exist. Used by
    ``--smoke`` and by CI to validate frozen (PyInstaller) builds. Never starts a
    server or a browser.
    """
    import importlib
    from pathlib import Path

    from local_browser_agent.app.main import _resource_path

    problems: list[str] = []
    for mod in (
        "local_browser_agent",
        "local_browser_agent.cli",
        "local_browser_agent.runner",
        "local_browser_agent.app.main",
        "local_browser_agent.app.runner",
        "local_browser_agent.app.db",
        "local_browser_agent.app.settings",
        "local_browser_agent.app.training_sink",
        "uvicorn",
        "fastapi",
        "jinja2",
        "aiosqlite",
        "browser_use",
        "browser_use.agent.service",
        "browser_use.browser.session",
        "browser_use.browser.profile",
        "browser_use.tools.service",
        "browser_use.dom.service",
    ):
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            problems.append(f"import {mod} failed: {type(e).__name__}: {e}")

    templates_dir = Path(_resource_path("local_browser_agent/app/templates"))
    for name in REQUIRED_TEMPLATES:
        if not (templates_dir / name).is_file():
            problems.append(f"missing template: {templates_dir / name}")
    static_dir = Path(_resource_path("local_browser_agent/app/static"))
    for name in REQUIRED_STATIC:
        if not (static_dir / name).is_file():
            problems.append(f"missing static file: {static_dir / name}")

    try:
        import browser_use

        prompts_dir = Path(browser_use.__file__).resolve().parent / "agent" / "system_prompts"
        if not (prompts_dir / "system_prompt.md").is_file():
            problems.append(f"missing browser_use prompt file: {prompts_dir / 'system_prompt.md'}")
        elif not list(prompts_dir.glob("*.md")):
            problems.append(f"no browser_use prompt files in {prompts_dir}")
    except Exception as e:  # noqa: BLE001
        problems.append(f"browser_use prompt check failed: {type(e).__name__}: {e}")
    return problems


def run_smoke() -> int:
    problems = smoke_check()
    report = "smoke: OK" if not problems else "smoke: FAILED\n" + "\n".join(f"  - {p}" for p in problems)
    if sys.stdout is not None:  # None in windowed (console=False) frozen builds
        print(report)
    if getattr(sys, "frozen", False):
        # Windowed frozen builds have no console: leave the report where CI can read it.
        try:
            from local_browser_agent.app.paths import get_user_data_dir
            (get_user_data_dir() / "smoke.log").write_text(report + "\n", encoding="utf-8")
        except OSError:
            pass
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    """Launch the web UI (default 127.0.0.1:8080).

    With no task: starts the server idle - open the printed URL and start runs from the
    UI. With a task string: pre-queues that task so the agent starts immediately on server
    boot (dev-mode convenience, backward compatible).

    Frozen-app behavior:
      - redirect_data_paths() moves DB and JSONL writes to user_data_dir
      - Logging is set up to user_data_dir/app.log so errors are visible with console=False
    """
    parser = build_parser()
    # parse_args (not parse_known_args): a typo such as "--prot 18769" must be an error,
    # not a silently ignored flag or a task string.
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.host not in LOCAL_HOSTS:
        parser.error("--host must be a loopback address (127.0.0.1, localhost or ::1)")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    task = " ".join(args.task).strip()
    if args.task and not task:
        parser.error("the task is empty; give a task or omit it")

    if args.smoke:
        return run_smoke()

    # (a) Redirect writable paths when running as frozen .app bundle
    redirect_data_paths()

    # (e) Set up file logging when frozen so startup errors are visible (Pitfall 6)
    if getattr(sys, "frozen", False):
        import logging
        from local_browser_agent.app.paths import get_user_data_dir
        log_path = get_user_data_dir() / "app.log"
        # Redirect stdout/stderr BEFORE uvicorn starts.
        # On Windows with console=False, PyInstaller sets these to None.
        # Any print() or stream access without this redirect crashes the process.
        sys.stdout = open(log_path, "a", encoding="utf-8")  # noqa: WPS515
        sys.stderr = sys.stdout
        logging.basicConfig(
            filename=str(log_path),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

    host_for_url = "[::1]" if args.host == "::1" else args.host
    url = f"http://{host_for_url}:{args.port}"

    # Detect a busy port before anything else: otherwise uvicorn only logs the bind error
    # and a browser would still be opened on whatever else is listening there.
    if not _port_free(args.host, args.port):
        message = (
            f"Port {args.port} is already in use, so the app cannot start. local-browser-agent "
            f"may already be running at {url}. Close the other copy, or choose another "
            f"port with --port."
        )
        if sys.stderr is not None:
            print(message, file=sys.stderr)
        if getattr(sys, "frozen", False):
            import logging
            logging.getLogger(__name__).error(message)
        return 1

    # (a) Preserve existing dev-mode task-string behavior
    if task:
        app.state.pending_task = task
    elif not getattr(sys, "frozen", False):
        print(f"Open {url} to start a run.")

    # (c) Chrome detection - always, not only when frozen - so dev-mode also flags it
    app.state.chrome_missing = not chrome_is_installed()

    # (d) Schedule browser auto-open ~2s after uvicorn starts binding
    if not args.no_open:
        schedule_browser_open(url=url, delay=2.0)

    # Blocks until server exits
    uvicorn.run(
        "local_browser_agent.app.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
        use_colors=False,  # Required: prevents ColourizedFormatter crash on Windows frozen
    )
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # MUST be first — prevents endless spawn loop on Windows
    sys.exit(main())
