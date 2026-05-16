#!/usr/bin/env bash
# build_mac.sh — local developer one-liner that mirrors the CI build steps
#
# Usage: bash build_scripts/build_mac.sh
#
# Produces: dist/local-browser-agent-dev-mac.zip (same shape as CI artifact)
#
# Requirements:
#   - uv installed (https://docs.astral.sh/uv/)
#   - macOS (codesign is macOS-only)
#   - uv.lock is committed and up to date
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "==> Syncing dependencies (frozen lockfile)..."
uv sync --frozen

echo "==> Building .app bundle with PyInstaller..."
uv run pyinstaller --clean --noconfirm local-browser-agent.spec

echo "==> Ad-hoc signing the bundle..."
bash build_scripts/sign.sh dist/local-browser-agent.app

echo "==> Zipping artifact..."
cd dist
zip -r9 "local-browser-agent-dev-mac.zip" local-browser-agent.app

echo ""
echo "Build complete: dist/local-browser-agent-dev-mac.zip"
