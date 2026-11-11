"""All-infra exit code, out-dir handling, multiple preflight kinds, null rates."""
import json
from types import SimpleNamespace

from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE
from local_browser_agent.evals import cli
from local_browser_agent.evals.compare import compare_results, render_comparison
from local_browser_agent.evals.report import render_markdown
from local_browser_agent.evals.runner import RunRecord, SuiteResult
from local_browser_agent.evals.tasks import CHECKER_VERSION


def make_config():
    return SimpleNamespace(
        model=SimpleNamespace(provider="fake", model="m-1"),
        safety=SimpleNamespace(allowed_domains=["x.example"]),
        timeout_s=600,
        max_steps=25,
    )


def infra_res(kind="cdp_connect"):
    return SimpleNamespace(status="error", final_result="", step_count=0, duration_s=0.1, cost_usd=None,
                           errors=["cannot reach CDP"], blocked_actions=[], error_kind=kind)


def _rec(**kw):
    base = dict(task_id="t", category="c", safety=False, repeat=1, passed=False, score=0.0, status="error",
                steps=0, duration_s=0.0, cost_usd=None, safety_violation=False, notes="", answer="",
                error_kind="cdp_connect")
    base.update(kw)
    return RunRecord(**base)


def test_checker_version_bumped():
    assert CHECKER_VERSION == "8"


def test_all_infra_below_threshold_exits_3_and_leaves_no_out_dir(tmp_path, capsys):
    async def fake(instruction, config, *, start_url):
        return infra_res()

    out = tmp_path / "res"
    rc = cli.main(["--tasks", "table-max-row", "--json", "--out", str(out)], run_fn=fake, config=make_config())
    cap = capsys.readouterr()
    assert rc == 3
    doc = json.loads(cap.out)
    assert doc["status"] == "error" and doc["error_kind"] == "cdp_connect"
    assert not out.exists()


def test_preexisting_out_dir_is_kept_on_all_infra(tmp_path):
    async def fake(instruction, config, *, start_url):
        return infra_res()

    assert cli.main(["--tasks", "table-max-row", "--out", str(tmp_path)], run_fn=fake, config=make_config()) == 3
    assert tmp_path.exists()


def test_preflight_failure_does_not_create_out_dir(tmp_path, capsys):
    out = tmp_path / "res"
    rc = cli.main(["--json", "--out", str(out)], config=make_config(),
                  preflight=lambda c: [CHROME_NOT_FOUND_MESSAGE, "Anthropic API key is invalid"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and not out.exists()
    assert doc["error_kind"] == "chrome_missing" and doc["error_kinds"] == ["chrome_missing", "preflight"]


def test_success_prints_out_path_to_stderr_and_json(tmp_path, capsys):
    async def ok(instruction, config, *, start_url):
        return SimpleNamespace(status="success", final_result="", step_count=1, duration_s=0.1, cost_usd=None,
                               errors=[], blocked_actions=[])

    out = tmp_path / "res"
    cli.main(["--tasks", "table-max-row", "--json", "--out", str(out)], run_fn=ok, config=make_config())
    cap = capsys.readouterr()
    assert json.loads(cap.out)["out"] == str(out.resolve())
    assert str(out.resolve()) in cap.err


def test_null_rates_per_category_and_properties():
    res = SuiteResult(runs=[_rec(category="a"),
                            _rec(category="b", passed=True, score=1.0, status="success", error_kind=None)])
    assert res.category_pass_rates == {"a": None, "b": 1.0}
    assert res.to_dict()["summary"]["category_pass_rates"] == {"a": None, "b": 1.0}
    assert SuiteResult(runs=[]).success_rate is None and SuiteResult(runs=[]).mean_score is None
    allinfra = SuiteResult(runs=[_rec()])
    assert allinfra.success_rate is None and allinfra.mean_score is None
    md = render_markdown(allinfra)
    assert "n/a" in md and "None" not in md


def test_compare_invalid_task_delta_is_dash():
    def doc(rate, n, infra):
        return {"schema_version": 1, "meta": {"taskset_hash": "h", "complete": True},
                "tasks": {"t": {"category": "c", "n": n, "passes": round(rate * n), "pass_rate": rate,
                                "mean_score": rate, "mean_steps": 1, "cost_usd": None, "safety_violations": 0,
                                "infra_errors": infra}},
                "runs": [{"task_id": "t", "status": "error", "error_kind": "cdp_connect"}] * infra}

    cmp = compare_results(doc(1.0, 2, 0), doc(0.0, 2, 2))
    text = render_comparison(cmp)
    assert "INVALID" in text and "-100pp" not in text
    assert cmp.to_dict()["tasks"][0]["delta"] is None
