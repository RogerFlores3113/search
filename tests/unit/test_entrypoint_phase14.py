"""Tests for agent/__main__.py WIN-02 changes (Phase 14).

Covers: freeze_support placement (AST), stdout/stderr redirect in frozen guard,
and uvicorn.run() use_colors=False.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest


def test_freeze_support_is_first():
    """freeze_support() must be the very first call in if __name__ == '__main__': block."""
    source = Path("agent/__main__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the if __name__ == '__main__': block at module level
    main_block = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        # Match: __name__ == "__main__"
        if not isinstance(test, ast.Compare):
            continue
        if not (
            isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            continue
        main_block = node
        break

    assert main_block is not None, "Could not find 'if __name__ == \"__main__\":' block"
    assert len(main_block.body) >= 1, "if __name__ == '__main__': block has no statements"

    # First statement must be an Expr (call statement)
    first_stmt = main_block.body[0]
    assert isinstance(first_stmt, ast.Expr), (
        f"First statement is {type(first_stmt).__name__}, expected ast.Expr (call)"
    )
    call = first_stmt.value
    assert isinstance(call, ast.Call), (
        f"First statement value is {type(call).__name__}, expected ast.Call"
    )

    # Call must be multiprocessing.freeze_support()
    func = call.func
    assert isinstance(func, ast.Attribute), (
        f"First call func is {type(func).__name__}, expected ast.Attribute "
        "(multiprocessing.freeze_support)"
    )
    assert func.attr == "freeze_support", (
        f"First call is .{func.attr}(), expected .freeze_support()"
    )
    assert isinstance(func.value, ast.Name), (
        f"First call object is {type(func.value).__name__}, expected ast.Name (multiprocessing)"
    )
    assert func.value.id == "multiprocessing", (
        f"First call object is {func.value.id}, expected multiprocessing"
    )


def test_stdout_redirect_in_frozen_guard(monkeypatch, tmp_path):
    """When frozen=True, main() redirects sys.stdout/stderr to app.log before uvicorn starts."""
    # Pre-import agent.__main__ so agent.main is cached in sys.modules BEFORE
    # frozen=True is set (avoids _MEIPASS lookup during cold import).
    import agent.__main__ as main_mod
    importlib.reload(main_mod)

    # Save original streams for cleanup
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    try:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        importlib.reload(main_mod)

        # Patch get_user_data_dir to return tmp_path so log lands in test temp dir
        import agent.paths as paths_mod
        monkeypatch.setattr(paths_mod, "get_user_data_dir", lambda: tmp_path)

        monkeypatch.setattr(main_mod.uvicorn, "run", lambda *a, **kw: None)
        monkeypatch.setattr(main_mod, "schedule_browser_open", lambda **kw: None)
        monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: True)

        main_mod.main()

        # app.log must have been created under tmp_path
        log_file = tmp_path / "app.log"
        assert log_file.exists(), f"app.log not created at {log_file}"

        # sys.stderr must equal sys.stdout (redirect happened)
        assert sys.stderr is sys.stdout, (
            "sys.stderr was not redirected to sys.stdout inside frozen guard"
        )
    finally:
        # Restore streams unconditionally so test runner is not broken
        sys.stdout = original_stdout
        sys.stderr = original_stderr


def test_uvicorn_use_colors_false(monkeypatch):
    """uvicorn.run() must be called with use_colors=False (prevents ColourizedFormatter crash)."""
    calls: list[dict] = []

    monkeypatch.delattr(sys, "frozen", raising=False)

    import agent.__main__ as main_mod
    importlib.reload(main_mod)

    monkeypatch.setattr(main_mod.uvicorn, "run", lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(main_mod, "schedule_browser_open", lambda **kw: None)
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: True)

    main_mod.main()

    assert calls, "uvicorn.run() was never called"
    assert calls[0].get("use_colors") is False, (
        f"uvicorn.run() called with use_colors={calls[0].get('use_colors')!r}, expected False"
    )
