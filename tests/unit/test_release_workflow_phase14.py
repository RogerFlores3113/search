"""Tests for .github/workflows/release.yml WIN-04 additions (Phase 14).

Covers: build-mac and build-windows jobs exist, both depend on test job,
both have if: startsWith condition, both have permissions: contents: write,
correct runners, and Windows spec filename referenced.

RED run command:
    uv run pytest tests/unit/test_release_workflow_phase14.py -x -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # PyYAML — available as pytest transitive dep (yaml.safe_load only)


def _load_workflow() -> dict:
    """Load and parse release.yml using yaml.safe_load (safe — no arbitrary object construction)."""
    return yaml.safe_load(
        Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    )


def test_build_mac_and_windows_jobs_exist():
    """WIN-04: release.yml must contain both build-mac and build-windows jobs."""
    wf = _load_workflow()
    assert "build-mac" in wf["jobs"], (
        "build-mac job not found in release.yml — add it in Plan 03"
    )
    assert "build-windows" in wf["jobs"], (
        "build-windows job not found in release.yml — add it in Plan 03"
    )


def test_jobs_depend_on_test():
    """WIN-04: both build jobs must declare needs: test."""
    wf = _load_workflow()
    for job_name in ("build-mac", "build-windows"):
        needs = wf["jobs"][job_name].get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "test" in needs, (
            f"{job_name} must declare 'needs: test'; currently: {needs!r}"
        )


def test_jobs_have_tag_condition():
    """WIN-04: both build jobs must only run on tag pushes."""
    wf = _load_workflow()
    for job_name in ("build-mac", "build-windows"):
        cond = wf["jobs"][job_name].get("if", "")
        assert "startsWith(github.ref, 'refs/tags/v')" in cond, (
            f"{job_name} missing if: startsWith(github.ref, 'refs/tags/v'); got: {cond!r}"
        )


def test_jobs_have_write_permissions():
    """WIN-04: both build jobs need permissions: contents: write for artifact upload."""
    wf = _load_workflow()
    for job_name in ("build-mac", "build-windows"):
        perms = wf["jobs"][job_name].get("permissions", {})
        assert perms.get("contents") == "write", (
            f"{job_name} missing 'permissions: contents: write'; got: {perms!r}"
        )


def test_build_windows_uses_windows_runner():
    """WIN-04: build-windows job must run on windows-latest."""
    wf = _load_workflow()
    runs_on = wf["jobs"]["build-windows"].get("runs-on", "")
    assert runs_on == "windows-latest", (
        f"build-windows runs-on={runs_on!r}, expected 'windows-latest'"
    )


def test_build_mac_uses_macos_runner():
    """WIN-04: build-mac job must run on macos-latest."""
    wf = _load_workflow()
    runs_on = wf["jobs"]["build-mac"].get("runs-on", "")
    assert runs_on == "macos-latest", (
        f"build-mac runs-on={runs_on!r}, expected 'macos-latest'"
    )


def test_build_windows_uses_windows_spec():
    """WIN-04: build-windows job steps must reference local-browser-agent-windows.spec."""
    wf = _load_workflow()
    steps = wf["jobs"]["build-windows"].get("steps", [])
    steps_str = str(steps)
    assert "local-browser-agent-windows.spec" in steps_str, (
        "build-windows steps do not reference local-browser-agent-windows.spec"
    )
