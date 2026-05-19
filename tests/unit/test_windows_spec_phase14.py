"""Tests for local-browser-agent-windows.spec (WIN-01, Phase 14).

Covers: spec file exists, contains EXE+COLLECT blocks, no BUNDLE() block,
hiddenimports list matches macOS spec, upx=False, console=False.

RED run command:
    uv run pytest tests/unit/test_windows_spec_phase14.py -x -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_windows_spec_file_exists():
    """WIN-01: Windows spec file must exist at project root."""
    assert Path("local-browser-agent-windows.spec").exists(), (
        "local-browser-agent-windows.spec not found — create it before running Plan 01"
    )


def test_windows_spec_has_exe_and_collect():
    """WIN-01: Windows spec must contain EXE() and COLLECT() blocks."""
    content = Path("local-browser-agent-windows.spec").read_text(encoding="utf-8")
    assert "exe = EXE(" in content, "Windows spec missing 'exe = EXE(' block"
    assert "coll = COLLECT(" in content, "Windows spec missing 'coll = COLLECT(' block"


def test_windows_spec_has_no_bundle():
    """WIN-01: Windows spec must NOT contain BUNDLE() — that is macOS-only."""
    content = Path("local-browser-agent-windows.spec").read_text(encoding="utf-8")
    assert "BUNDLE(" not in content, (
        "BUNDLE() is macOS-only; must not appear in Windows spec"
    )


def test_windows_spec_upx_false():
    """WIN-01: Windows spec must set upx=False in both EXE and COLLECT blocks."""
    content = Path("local-browser-agent-windows.spec").read_text(encoding="utf-8")
    upx_false_count = content.count("upx=False")
    assert upx_false_count >= 2, (
        f"Expected at least 2 occurrences of 'upx=False' (EXE + COLLECT), found {upx_false_count}"
    )


def test_windows_spec_console_false():
    """WIN-01: Windows spec must set console=False (no terminal window)."""
    content = Path("local-browser-agent-windows.spec").read_text(encoding="utf-8")
    assert "console=False" in content, "Windows spec missing 'console=False'"


def test_hiddenimports_match():
    """WIN-01: hiddenimports in Windows spec must match macOS spec exactly."""
    def extract_hiddenimports(path: str) -> set[str]:
        text = Path(path).read_text(encoding="utf-8")
        m = re.search(r"hiddenimports=\[(.*?)\]", text, re.DOTALL)
        assert m, f"hiddenimports not found in {path}"
        return set(re.findall(r'"([^"]+)"', m.group(1)))

    mac = extract_hiddenimports("local-browser-agent.spec")
    win = extract_hiddenimports("local-browser-agent-windows.spec")
    assert mac == win, (
        f"hiddenimports mismatch:\n"
        f"Mac only: {mac - win}\n"
        f"Win only: {win - mac}"
    )
