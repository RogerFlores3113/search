#!/usr/bin/env bash
set -euo pipefail

# local-browser-agent — launch script for Linux/macOS
# Requires: uv (https://docs.astral.sh/uv/)
#
# First run: uv sync (downloads deps into .venv automatically)
# Subsequent runs: starts instantly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv &> /dev/null; then
    echo "uv is required but not installed."
    echo "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

exec uv run python -m agent "$@"
