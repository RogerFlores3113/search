from __future__ import annotations

import sys

import uvicorn

from agent.main import app


def main() -> None:
    """Parse sys.argv[1:] as task string, set app.state.pending_task, launch uvicorn."""
    args = sys.argv[1:]
    if not args:
        print('Usage: python -m agent "<task>"')
        sys.exit(2)

    task = " ".join(args)
    app.state.pending_task = task
    uvicorn.run("agent.main:app", host="127.0.0.1", port=8080, log_level="info")


if __name__ == "__main__":
    main()
