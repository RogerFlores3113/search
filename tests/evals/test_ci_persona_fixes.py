"""One infra definition; LBA_* validated first, named, and unknown names warned about."""
from __future__ import annotations

import json

import pytest

from local_browser_agent.config import AgentConfig, unknown_env_warnings
from local_browser_agent.evals import cli
from local_browser_agent.evals.runner import RunRecord, SuiteResult, is_infra_error


def _rec(status, kind, passed=False):
    return RunRecord("t", "c", False, 1, passed, 0.0, status, 1, 0.1, None, False, "", "", error_kind=kind)


def test_is_infra_error_definition():
    assert is_infra_error("error", "chrome_missing")
    assert is_infra_error("error", "config")
    assert is_infra_error("error", None)  # old result files
    assert not is_infra_error("error", "agent_error")
    assert not is_infra_error("timeout", "timeout")
    assert not is_infra_error("success", None)


def test_agent_error_counts_as_valid_and_labels_agree(capsys):
    res = SuiteResult(runs=[_rec("error", "agent_error")])
    assert res.n_valid == 1
    cli._print_summary(res)
    assert "no valid runs" not in capsys.readouterr().out
    assert cli._all_infra_kinds(res) == []
    assert cli._all_infra_kinds(SuiteResult(runs=[_rec("error", "preflight")])) == ["preflight"]


def test_env_problems_all_reported_first(monkeypatch, capsys):
    for k in ("LBA_MODEL", "LBA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LBA_PROVIDER", "nope")
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    code = cli._main(["--json"])
    assert code == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["error_kind"] == "config"
    text = "\n".join(doc["errors"])
    assert "LBA_PROVIDER" in text and "LBA_MAX_STEPS" in text
    assert "required for a real run" not in text


def test_env_error_names_variable_and_flag_does_not_override(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    with pytest.raises(ValueError) as ei:
        AgentConfig.from_env()
    assert "LBA_MAX_STEPS (max_steps)" in str(ei.value) and "got 0" in str(ei.value)
    monkeypatch.setenv("LBA_PROVIDER", "ollama")
    monkeypatch.setenv("LBA_MODEL", "m")
    assert cli._main(["--max-steps", "5", "--json"]) == 2
    assert "LBA_MAX_STEPS" in capsys.readouterr().out


def test_unknown_env_warnings():
    out = unknown_env_warnings(env={"LBA_TIMEOUT": "1", "LBA_DATA_DIR": "x", "LBA_MCP_STRICT": "1",
                                    "LBA_ALLOW_TELEMETRY": "1", "LBA_MODEL": "m", "OTHER": "1"})
    assert len(out) == 1 and "LBA_TIMEOUT_S" in out[0] and "LBA_TIMEOUT " in out[0]
    assert unknown_env_warnings(env={"LBA_ZZZZQ": "1"})[0].endswith("is ignored")


def test_warn_is_stderr_only(monkeypatch, capsys):
    from local_browser_agent import cli as main_cli

    monkeypatch.setenv("LBA_TIMEOUT", "5")
    main_cli.warn_unknown_env()
    cap = capsys.readouterr()
    assert cap.out == "" and "LBA_TIMEOUT_S" in cap.err
