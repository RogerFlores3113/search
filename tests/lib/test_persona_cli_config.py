"""Persona-review fixes: JSON usage errors, usage vs config kinds, collected env errors, MCP URL redaction."""
from __future__ import annotations

import json

import pytest

from local_browser_agent import cli as lba_cli
from local_browser_agent.config import AgentConfig
from local_browser_agent.mcp_server import _ProgressSink


@pytest.mark.parametrize("argv", [
    ["run", "--json", "--bogus", "x", "task"],
    ["run", "--bogus", "x", "task", "--json"],
    ["run", "--jso", "--bogus", "task"],
    ["run", "--json"],  # missing task
])
def test_run_json_argparse_error_is_one_document(argv, capsys):
    assert lba_cli.main(argv) == 2
    out = capsys.readouterr()
    doc = json.loads(out.out)
    assert doc["status"] == "error" and doc["error_kind"] == "usage"
    assert doc["success"] is None and doc["errors"]
    assert "usage:" in out.err


def test_run_argparse_error_without_json_has_empty_stdout(capsys):
    assert lba_cli.main(["run", "--bogus", "task"]) == 2
    out = capsys.readouterr()
    assert out.out == "" and "unrecognized arguments" in out.err


@pytest.mark.parametrize("flag,val", [("--cdp-url", "nope"), ("--start-url", "ftp://x")])
def test_bad_flag_value_is_usage(flag, val, capsys):
    assert lba_cli.main(["run", "t", "--json", flag, val]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"


def test_bad_env_is_config(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "abc")
    assert lba_cli.main(["run", "t", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "config"


def test_from_env_collects_all_problems():
    with pytest.raises(ValueError) as ei:
        AgentConfig.from_env(env={"LBA_MAX_STEPS": "abc", "LBA_TIMEOUT_S": "-5",
                              "LBA_PROVIDER": "bogus", "LBA_HEADLESS": "maybe"})
    problems = lba_cli._config_problems(ei.value)
    joined = "\n".join(problems)
    assert len(problems) >= 4
    for needle in ("LBA_MAX_STEPS", "timeout_s", "provider", "LBA_HEADLESS"):
        assert needle in joined


def test_from_env_single_problem_message_unchanged():
    with pytest.raises(ValueError, match="LBA_MAX_STEPS must be an integer, got 'abc'"):
        AgentConfig.from_env(env={"LBA_MAX_STEPS": "abc"})


class _Ev:
    def __init__(self, **kw):
        self.action_type = kw.get("action_type", "type")
        self.target_label = kw.get("target_label")
        self.value = kw.get("value")
        self.url = kw.get("url")


def test_progress_redacts_embedded_urls():
    a = _ProgressSink._describe(_Ev(value="see https://ex.com/cb?access_token=SECRET ok"))
    assert "SECRET" not in a and "ex.com/cb" in a
    b = _ProgressSink._describe(_Ev(target_label="Link to https://ex.com/?key=SECRET"))
    assert "SECRET" not in b
    c = _ProgressSink._describe(_Ev(url="https://u:pw@ex.com/p?a=1"))
    assert "pw" not in c and "a=1" not in c
