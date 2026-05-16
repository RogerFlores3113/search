#!/usr/bin/env bash
# sign.sh — ad-hoc codesign a .app bundle for local distribution
#
# Usage: bash build_scripts/sign.sh dist/local-browser-agent.app
#
# Notes:
#   - Ad-hoc signing (--sign -) does NOT require an Apple Developer account.
#   - Users on macOS Sequoia must go to System Settings → Privacy & Security → Open Anyway.
#   - browser-use 0.12.6 uses cdp-use (pure Python CDP over WebSocket), not playwright.
#     There is no Playwright Node.js driver binary to sign.
set -euo pipefail

APP="${1:?Usage: sign.sh <path-to-app>}"

echo "Ad-hoc signing entire bundle: $APP"
codesign --sign - --force --deep "$APP"

echo "Re-signing embedded shared libraries..."
find "$APP" -type f \( -name '*.so' -o -name '*.dylib' \) -print0 \
    | xargs -0 -I{} codesign --sign - --force {}

echo "Sign complete: $APP"
