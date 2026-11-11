"""The eval CI workflow runs the suite on PRs and skips cleanly without a key."""
from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "evals.yml"


def _load() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_runs_on_pull_requests_and_manually():
    on = _load()["on"]
    assert "pull_request" in on and "workflow_dispatch" in on


def test_every_step_after_key_check_is_gated():
    steps = _load()["jobs"]["evals"]["steps"]
    assert steps[0]["id"] == "key"
    for step in steps[1:]:
        assert "steps.key.outputs.present == 'true'" in step["if"], step.get("name")


def test_run_step_gates_on_safety_and_uses_secret_by_name():
    steps = _load()["jobs"]["evals"]["steps"]
    run = next(s for s in steps if s.get("name") == "Run eval suite")["run"]
    assert "--fail-on-violation" in run
    assert "--api-key-env ANTHROPIC_API_KEY" in run
    assert "--self-test" in next(s for s in steps if s.get("name") == "Harness self-test")["run"]


def test_model_is_configurable():
    env = _load()["jobs"]["evals"]["env"]
    assert "vars.EVAL_MODEL" in env["EVAL_MODEL"]
    assert "vars.EVAL_FAIL_UNDER" in env["EVAL_FAIL_UNDER"]
