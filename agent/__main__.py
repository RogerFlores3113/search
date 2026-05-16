from __future__ import annotations

import sys

import uvicorn

from agent.main import app


def main() -> None:
    """Launch the web UI on 127.0.0.1:8080.

    With no arguments: starts the server idle — open http://127.0.0.1:8080 and
    start runs from the UI.
    With a task string: pre-queues that task so the agent starts immediately on
    server boot.
    """
    args = sys.argv[1:]
    if args:
        app.state.pending_task = " ".join(args)
    else:
        print("Open http://127.0.0.1:8080 to start a run.")
    uvicorn.run("agent.main:app", host="127.0.0.1", port=8080, log_level="info")


if __name__ == "__main__":
    main()
