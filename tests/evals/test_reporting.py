"""Results schema, per-task aggregation, incremental output, timeouts, --compare and env config."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from local_browser_agent.evals import cli, runner
from local_browser_agent.evals.compare import compare_results, load_results
from local_browser_agent.evals.runner import SCHEMA_VERSION, run_suite
from local_browser_agent.evals.tasks import TASKS, taskset_hash


def make_config():
    return SimpleNamespace(
        model=SimpleNamespace(provider="fake", model="m-1"),
        safety=SimpleNamespace(allowed_domains=["x.example"]),
        timeout_s=600,
        max_steps=25,
    )


def res(answer="", steps=3, cost=None):
    return SimpleNamespace(
        status="success", final_result=answer, step_count=steps, duration_s=1.0, cost_usd=cost, errors=[], blocked_actions=[]
    )


async def test_schema_meta_and_task_block(tmp_path):
    seen = []

    async def fake(instruction, config, *, start_url):
        seen.append(config.timeout_s)
        return res("nope", steps=4, cost=0.5)

    await run_suite(
        make_config(), task_ids=["table-max-row", "delayed-content"], repeats=2, out_dir=tmp_path, run_fn=fake, timeout_s=77
    )
    assert seen == [77] * 4
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["schema_version"] == SCHEMA_VERSION
    meta = data["meta"]
    assert meta["repeats"] == 2 and meta["timeout_s"] == 77 and meta["complete"] is True
    assert meta["provider"] == "fake" and meta["model"] == "m-1"
    assert meta["taskset_hash"] == taskset_hash([t for t in TASKS if t.id in {"table-max-row", "delayed-content"}])
    assert meta["max_steps"]["table-max-row"] == 8
    assert "git_sha" in meta and "lba_version" in meta
    t = data["tasks"]["table-max-row"]
    assert t["n"] == 2 and t["passes"] == 0 and t["pass_rate"] == 0.0
    assert t["mean_steps"] == 4 and t["cost_usd"] == pytest.approx(1.0)
    md = (tmp_path / "results.md").read_text()
    assert "## Per-task summary" in md and "0/2" in md and "Per-task runs" in md


async def test_taskset_hash_changes_with_instructions():
    a = taskset_hash()
    import dataclasses

    changed = [dataclasses.replace(TASKS[0], instruction=TASKS[0].instruction + "!")] + TASKS[1:]
    assert taskset_hash(changed) != a and taskset_hash() == a


async def test_results_are_written_incrementally(tmp_path):
    calls = []

    def progress(rec):
        calls.append(rec.task_id)
        if len(calls) == 3:
            raise RuntimeError("crash mid-suite")

    async def fake(instruction, config, *, start_url):
        return res("x")

    with pytest.raises(RuntimeError):
        await run_suite(
            make_config(), task_ids=["table-max-row", "delayed-content"], repeats=2, out_dir=tmp_path, run_fn=fake,
            progress=progress,
        )
    lines = (tmp_path / "results.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["task_id"] == "table-max-row"
    # results.json was rewritten after the first completed task, and says it is partial
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["meta"]["complete"] is False and data["summary"]["total_runs"] == 2


async def test_per_run_timeout_stops_a_wedged_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_HARD_STOP_GRACE_S", 0.05)

    async def hang(instruction, config, *, start_url):
        await asyncio.sleep(30)

    out = await run_suite(make_config(), task_ids=["table-max-row"], out_dir=tmp_path, run_fn=hang, timeout_s=0.05)
    r = out.runs[0]
    assert r.status == "timeout" and not r.passed and "timeout" in r.errors[0]
    assert "run error" in r.notes


async def test_budget_stops_new_runs(tmp_path):
    async def fake(instruction, config, *, start_url):
        return res("x")

    out = await run_suite(make_config(), repeats=2, out_dir=tmp_path, run_fn=fake, budget_s=0)
    assert out.total_runs == 0 and out.meta["complete"] is False and out.meta["stopped_reason"] == "budget"
    assert json.loads((tmp_path / "results.json").read_text())["meta"]["complete"] is False


def test_cli_budget_incomplete_exits_1(tmp_path, capsys):
    async def fake(instruction, config, *, start_url):
        return res("x")

    rc = cli.main(["--tasks", "table-max-row", "--budget-minutes", "0.0000001", "--out", str(tmp_path)],
                  run_fn=fake, config=make_config())
    assert rc == 1 and "partial" in capsys.readouterr().err


def test_cli_rejects_bad_timeout(capsys):
    assert cli.main(["--timeout", "0"]) == 2
    assert cli.main(["--budget-minutes", "-1"]) == 2


# ---- --compare ---------------------------------------------------------------------------


def results_file(tmp_path, name, tasks, **meta):
    full = {
        tid: {"category": "x", "safety": v.get("viol") is not None, "n": 2, "passes": round(v["rate"] * 2),
              "pass_rate": v["rate"], "mean_score": v["rate"], "mean_steps": 3, "mean_duration_s": 1,
              "cost_usd": None, "safety_violations": v.get("viol", 0)}
        for tid, v in tasks.items()
    }
    d = tmp_path / name
    d.mkdir()
    p = d / "results.json"
    p.write_text(json.dumps({"schema_version": 1, "meta": {"taskset_hash": "h", **meta}, "tasks": full}))
    return str(p)


def test_compare_ok_and_deltas(tmp_path, capsys):
    a = results_file(tmp_path, "a", {"t1": {"rate": 0.5}, "t2": {"rate": 1.0}})
    b = results_file(tmp_path, "b", {"t1": {"rate": 1.0}, "t2": {"rate": 1.0}, "t3": {"rate": 0.0}})
    assert cli.main(["--compare", a, b]) == 0
    out = capsys.readouterr().out
    assert "+50pp" in out and "new task" in out and "0 regression(s)" in out


def test_compare_regression_exits_1(tmp_path, capsys):
    a = results_file(tmp_path, "a", {"t1": {"rate": 1.0}})
    b = results_file(tmp_path, "b", {"t1": {"rate": 0.5}}, taskset_hash="other")
    assert cli.main(["--compare", a, b]) == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out and "-50pp" in out and "task set differs" in out


def test_compare_new_safety_violation_exits_1(tmp_path, capsys):
    a = results_file(tmp_path, "a", {"s1": {"rate": 1.0, "viol": 0}})
    b = results_file(tmp_path, "b", {"s1": {"rate": 1.0, "viol": 1}})
    assert cli.main(["--compare", a, b]) == 1
    assert "NEW SAFETY VIOLATION" in capsys.readouterr().out
    cmp = compare_results(load_results(a), load_results(b))
    assert [d.task_id for d in cmp.new_violations] == ["s1"] and not cmp.regressions


def test_compare_rejects_old_or_missing_files(tmp_path, capsys):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"summary": {}, "runs": []}))
    good = results_file(tmp_path, "g", {"t": {"rate": 1.0}})
    assert cli.main(["--compare", str(old), good]) == 2
    assert cli.main(["--compare", str(tmp_path / "missing.json"), good]) == 2
    assert "schema_version" in capsys.readouterr().err


# ---- environment configuration -------------------------------------------------------------


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def test_build_config_reads_lba_env_and_flags_override(monkeypatch):
    for k in ("LBA_PROVIDER", "LBA_MODEL", "LBA_BASE_URL", "LBA_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LBA_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LBA_MODEL", "env-model")
    monkeypatch.setenv("LBA_BASE_URL", "http://env:1234")
    monkeypatch.setenv("LBA_API_KEY", "env-key")

    cfg = cli._build_config(parse(), None)
    assert (cfg.model.provider, cfg.model.model, cfg.model.base_url) == ("openai_compatible", "env-model", "http://env:1234")
    assert cfg.model.api_key.get_secret_value() == "env-key"
    assert cfg.browser.headless is True

    cfg = cli._build_config(parse("--model", "flag-model", "--base-url", "http://flag", "--headed"), "flag-key")
    assert (cfg.model.model, cfg.model.base_url) == ("flag-model", "http://flag")
    assert cfg.model.api_key.get_secret_value() == "flag-key" and cfg.browser.headless is False


def test_provider_and_model_may_come_from_env(monkeypatch, capsys):
    monkeypatch.delenv("LBA_PROVIDER", raising=False)
    monkeypatch.delenv("LBA_MODEL", raising=False)
    assert cli.main(["--provider", "x"]) == 2  # model missing from flags and env
    assert "LBA_MODEL" in capsys.readouterr().err
