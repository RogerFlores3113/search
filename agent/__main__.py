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

import multiprocessing
import sys

import uvicorn

from agent.chrome_detect import chrome_is_installed
from agent.launcher import schedule_browser_open
from agent.main import app


def redirect_data_paths() -> None:
    """Patch module-level path constants to user_data_dir when running frozen.

    Must be called before any async code uses agent.db or agent.runner.
    In dev mode this is a no-op — paths stay as get_user_data_dir() already set.
    """
    if not getattr(sys, "frozen", False):
        return

    from agent.paths import get_user_data_dir
    user_dir = get_user_data_dir()

    import agent.db as db_module
    db_module.DB_PATH = user_dir / "history.db"

    import agent.runner as runner_module
    runner_module.TRAINING_FILE = user_dir / "training" / "runs.jsonl"
    (user_dir / "training").mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Launch the web UI on 127.0.0.1:8080.

    With no arguments: starts the server idle — open http://127.0.0.1:8080 and
    start runs from the UI.
    With a task string: pre-queues that task so the agent starts immediately on
    server boot (dev-mode convenience, backward compatible).

    Frozen-app behavior:
      - redirect_data_paths() moves DB and JSONL writes to user_data_dir
      - Logging is set up to user_data_dir/app.log so errors are visible with console=False
    """
    # (a) Redirect writable paths when running as frozen .app bundle
    redirect_data_paths()

    # (e) Set up file logging when frozen so startup errors are visible (Pitfall 6)
    if getattr(sys, "frozen", False):
        import logging
        from agent.paths import get_user_data_dir
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

    # (a) Preserve existing dev-mode sys.argv task-string behavior
    args = sys.argv[1:]
    if args:
        app.state.pending_task = " ".join(args)
    else:
        if not getattr(sys, "frozen", False):
            print("Open http://127.0.0.1:8080 to start a run.")

    # (c) Chrome detection — always, not only when frozen — so dev-mode also flags it
    app.state.chrome_missing = not chrome_is_installed()

    # (d) Schedule browser auto-open ~2s after uvicorn starts binding
    schedule_browser_open(url="http://127.0.0.1:8080", delay=2.0)

    # Blocks until server exits
    uvicorn.run(
        "agent.main:app",
        host="127.0.0.1",
        port=8080,
        log_level="info",
        use_colors=False,  # Required: prevents ColourizedFormatter crash on Windows frozen
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()  # MUST be first — prevents endless spawn loop on Windows
    main()
