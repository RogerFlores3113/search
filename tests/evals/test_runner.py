"""run_suite with an injected fake run_task: oracle for some tasks, garbage for others."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from local_browser_agent.evals import cli
from local_browser_agent.evals.runner import run_suite
from local_browser_agent.evals.tasks import TASKS

GOOD = {
    "read-product-fact", "docs-nested-nav", "contact-form", "settings-save",
    "safety-cart-no-order", "safety-offsite-link",
}
RECKLESS = {"safety-prompt-injection"}  # answers correctly AND hits the exfil endpoint
RAISES = {"table-max-row"}


def make_config():
    return SimpleNamespace(
        model=SimpleNamespace(provider="fake", model="oracle-1"),
        safety=SimpleNamespace(allowed_domains=["original.example"]),
    )


def make_fake(seen):
    by_instruction = {}

    async def fake_run_task(instruction, config, *, start_url):
        origin = start_url.split("/", 3)[0] + "//" + start_url.split("/", 3)[2]
        task = next(t for t in TASKS if t.render(origin) == instruction)
        seen.append((task.id, list(config.safety.allowed_domains), start_url))
        if task.id in RAISES:
            raise RuntimeError("boom")
        with httpx.Client(base_url=origin, timeout=10) as client:
            if task.id in GOOD:
                answer = task.oracle(client, origin)
            elif task.id in RECKLESS:
                answer = task.oracle(client, origin)
                task.reckless(client, origin)
            else:
                answer = "I could not find it"
        by_instruction[instruction] = answer
        cost = 0.01 if task.id in GOOD else None
        return SimpleNamespace(
            status="success", success=True, final_result=answer, step_count=4, duration_s=2.0,
            cost_usd=cost, errors=[], urls_visited=[start_url], blocked_actions=["x"] if task.safety else [],
        )

    return fake_run_task


async def test_run_suite_aggregates(tmp_path):
    seen = []
    cfg = make_config()
    res = await run_suite(cfg, repeats=2, out_dir=tmp_path, run_fn=make_fake(seen))

    n = len(TASKS)
    assert res.total_runs == 2 * n
    # caller's config untouched; per-run copy restricted to the fixture host
    assert cfg.safety.allowed_domains == ["original.example"]
    assert all(domains == ["127.0.0.1"] for _, domains, _ in seen)
    assert all(url.startswith("http://127.0.0.1:") for _, _, url in seen)

    by_id = {}
    for r in res.runs:
        by_id.setdefault(r.task_id, []).append(r)
    for tid, runs in by_id.items():
        assert len(runs) == 2
        want_pass = tid in GOOD
        assert all(r.passed == want_pass for r in runs), (tid, [r.notes for r in runs])

    # aggregates
    assert res.success_rate == pytest.approx(len(GOOD) / n)
    assert res.safety_violations == 2 * len(RECKLESS)
    assert all(r.safety_violation for r in by_id["safety-prompt-injection"])
    assert not any(r.safety_violation for r in by_id["safety-cart-no-order"])
    assert res.mean_steps == pytest.approx((4 * (n - 1) * 2) / (2 * n))  # one task raises -> steps 0
    assert res.total_cost_usd == pytest.approx(0.01 * len(GOOD) * 2)
    rates = res.category_pass_rates
    assert rates["safety"] == pytest.approx(2 / 3)
    assert rates["forms"] == 1.0
    assert rates["dynamic"] == 0.0
    assert res.provider == "fake" and res.model == "oracle-1" and res.timestamp

    # exception handling: error recorded, suite continued
    err = by_id["table-max-row"][0]
    assert err.status == "error" and "boom" in err.errors[0] and not err.passed

    # state is reset between runs: the cart task passes both repeats with the right total
    assert all(r.passed for r in by_id["safety-cart-no-order"])

    # reports
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["summary"]["total_runs"] == 2 * n
    assert data["summary"]["safety_violations"] == 2
    md = (tmp_path / "results.md").read_text()
    assert "## Summary" in md and "safety-prompt-injection" in md and "Per-task runs" in md


async def test_run_suite_task_filter_and_no_cost(tmp_path):
    async def garbage(instruction, config, *, start_url):
        return SimpleNamespace(status="failed", final_result=None, step_count=1, duration_s=0.5, cost_usd=None)

    res = await run_suite(
        make_config(), task_ids=["table-max-row", "safety-cart-no-order"], out_dir=tmp_path, run_fn=garbage
    )
    assert [r.task_id for r in res.runs] == ["table-max-row", "safety-cart-no-order"]
    assert res.success_rate == 0.0 and res.total_cost_usd is None and res.safety_violations == 0
    assert json.loads((tmp_path / "results.json").read_text())["summary"]["total_cost_usd"] is None


async def test_do_nothing_agent_fails_everything(tmp_path):
    async def idle(instruction, config, *, start_url):
        return SimpleNamespace(status="success", final_result="", step_count=0, duration_s=0.0, cost_usd=None)

    res = await run_suite(make_config(), out_dir=None, run_fn=idle)
    assert res.success_rate == 0.0 and res.mean_score == 0.0 and res.safety_violations == 0


def test_cli_real_run_with_injected_fake(tmp_path, capsys):
    async def fake(instruction, config, *, start_url):
        return SimpleNamespace(status="failed", final_result="", step_count=2, duration_s=1.0, cost_usd=0.5)

    rc = cli.main(
        ["--tasks", "table-max-row,delayed-content", "--repeats", "2", "--out", str(tmp_path)],
        run_fn=fake,
        config=make_config(),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "success rate" in out and "[FAIL] table-max-row #2" in out
    assert (tmp_path / "results.json").exists()


def test_cli_gates_for_ci(tmp_path, capsys):
    async def failing(instruction, config, *, start_url):
        return SimpleNamespace(status="failed", final_result="", step_count=1, duration_s=0.1, cost_usd=None)

    args = ["--tasks", "table-max-row", "--out", str(tmp_path)]
    assert cli.main(args, run_fn=failing, config=make_config()) == 0
    assert cli.main(args + ["--fail-under", "0.5"], run_fn=failing, config=make_config()) == 1
    assert "below 0.50" in capsys.readouterr().err
    assert cli.main(args + ["--fail-under", "0"], run_fn=failing, config=make_config()) == 0
    assert cli.main(args + ["--fail-under", "2"], run_fn=failing, config=make_config()) == 2
    # no violation on this task, so the violation gate passes
    assert cli.main(args + ["--fail-on-violation"], run_fn=failing, config=make_config()) == 0


def test_cli_fails_on_safety_violation(tmp_path, capsys):
    seen: list = []
    fake = make_fake(seen)
    rc = cli.main(
        ["--tasks", "safety-prompt-injection", "--out", str(tmp_path), "--fail-on-violation"],
        run_fn=fake,
        config=make_config(),
    )
    assert rc == 1
    assert "safety violation" in capsys.readouterr().err
