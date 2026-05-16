# local-browser-agent.spec — PyInstaller spec for macOS .app bundle
#
# Source: pyinstaller.org/en/stable/spec-files.html
# Patterns: .planning/phases/04-distribution/04-RESEARCH.md Pattern 2 (Playwright driver),
#           .planning/phases/04-distribution/04-RESEARCH.md Pattern 6 (spec structure)
#
# Open Question 2: Playwright v6 hook incompatibility on macOS
#   The playwright docs note the hook is "not compatible with PyInstaller v6 on linux and macOS".
#   This likely refers to bundled Chromium scenarios; we use channel="chrome" (system Chrome, no
#   bundled Chromium) so this incompatibility may not apply. Verify in Task 6 checkpoint by
#   checking `find dist/local-browser-agent.app -name "node" -path "*playwright*"` after build.
#   If driver is missing, fall back to manual --add-data for the driver path.
#
# upx=False: UPX is not installed by default on macOS runners and can break codesign.
#   Explicitly disabled per anti-patterns guidance in 04-RESEARCH.md.

from PyInstaller.utils.hooks import collect_data_files
import sys

block_cipher = None

a = Analysis(
    ["agent/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # Playwright driver (node binary + cli.js) — required even for channel="chrome"
        # (Playwright needs its own Node.js subprocess to orchestrate CDP).
        # See: 04-RESEARCH.md Pattern 2 + Pitfall 2
        *collect_data_files("playwright"),
        # Jinja2 templates — served by FastAPI at runtime
        ("agent/templates", "agent/templates"),
        # Static files (CSS + any other static assets)
        ("agent/static", "agent/static"),
    ],
    hiddenimports=[
        # uvicorn internals not auto-discovered by PyInstaller
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # aiosqlite — async SQLite driver
        "aiosqlite",
        # platformdirs — user data directory resolution
        "platformdirs",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="local-browser-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,      # UPX disabled — not installed by default on macOS; can break codesign
    console=False,  # No terminal window — windowed .app; errors go to app.log in user_data_dir
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,      # UPX disabled — see EXE above
    upx_exclude=[],
    name="local-browser-agent",
)

app = BUNDLE(
    coll,
    name="local-browser-agent.app",
    icon=None,      # Deferred to Wave 2 of Phase 4 (Open Question 3 in 04-RESEARCH.md)
    bundle_identifier="com.localagent.browser",
    version="0.1.0",
    info_plist={
        "NSHighResolutionCapable": True,
        "LSUIElement": False,   # Show in Dock — user expects visible app
    },
)
