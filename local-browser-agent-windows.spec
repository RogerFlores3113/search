# local-browser-agent-windows.spec — PyInstaller spec for Windows .exe (onedir)
#
# Source: pyinstaller.org/en/stable/spec-files.html
# Pattern: mirrors local-browser-agent.spec minus the macOS-only BUNDLE block
#
# upx=False: UPX not installed by default on Windows CI runners; can break binaries.
# onedir mode: EXE + COLLECT, no onefile — avoids antivirus false positives and slow startup.
# console=False: no terminal window; stdout/stderr redirected to app.log in __main__.py.

import sys

block_cipher = None

a = Analysis(
    ["agent/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=[
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
        # browser_use submodules (CDP-based, no playwright dependency)
        "browser_use.browser.session",
        "browser_use.browser.profile",
        "browser_use.agent.service",
        "browser_use.controller.service",
        "browser_use.dom.service",
        "cdp_use",
        "cdp_use.client",
        "cdp_use.cdp",
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
    upx=False,      # UPX disabled — not installed by default on Windows CI runners; can break binaries
    console=False,  # No terminal window — windowed .exe; stdout/stderr redirected to app.log in __main__.py
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

# NOTE: No macOS BUNDLE block here — that is macOS-only. Windows produces dist\local-browser-agent\local-browser-agent.exe
