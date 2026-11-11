"""Round-3 hardening: hedged/negated/competing answers, FINAL mid-line, strict --compare, preflight."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from local_browser_agent.evals import cli, tasks
from local_browser_agent.evals.compare import CompareError, compare_results, load_results
from local_browser_agent.evals.runner import run_suite
from local_browser_agent.evals.tasks import TASKS, TASKS_BY_ID, final_answer, taskset_hash


def check(server, task_id, answer):
    return TASKS_BY_ID[task_id].check(server.state, answer)


def visit(client, *paths):
    for p in paths:
        client.get(p)


# ---- checkers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "FINAL: 73 MB is wrong",
        "FINAL: could be 73 MB",
        "FINAL: likely 73 MB",
        "FINAL: it seems 73 MB",
        "FINAL: less than 73",
        "FINAL: between 12 and 73 MB",
        "FINAL: 73 / 12",
        "FINAL: about 73 MB",
        "FINAL: approximately 73 MB",
        "FINAL: ~73 MB",
        "FINAL: 73 MB and 12 MB",
        "FINAL: 73 MB isn't right",
        "FINAL: 73 MB is incorrect",
        "FINAL: over 73 MB",
    ],
)
def test_hedged_negated_or_competing_final_fails(server, client, answer):
    visit(client, "/docs/guides/deployment/limits.html")
    assert not check(server, "docs-nested-nav", answer).passed


def test_negated_postfix_name_fails(server, client):
    visit(client, "/regions.html")
    assert not check(server, "table-max-row", "FINAL: Baltic is NOT the highest").passed
    assert not check(server, "table-max-row", "Baltic is not the highest in Q3").passed


def test_approximation_tolerated_in_prose_only(server, client):
    visit(client, "/product-lamp.html")
    assert check(server, "read-product-fact", "It lasts about 17 hours.").passed
    assert not check(server, "read-product-fact", "FINAL: about 17 hours").passed
    assert not check(server, "read-product-fact", "It could be 17 hours").passed


def test_cookie_code_with_space(server, client):
    visit(client, "/cafe.html")
    client.post("/api/consent", json={"choice": "accept"})
    client.post("/api/discount")
    assert check(server, "cookie-banner", "FINAL: SAVE 3917").passed


def test_comparison_after_the_answer_is_not_a_distractor(server, client):
    visit(client, "/hotels-a.html", "/hotels-b.html")
    assert check(server, "second-cheapest-hotel", "FINAL: Beacon Suites over Dockside Motel").passed
    assert not check(server, "second-cheapest-hotel", "FINAL: Dockside Motel over Beacon Suites").passed


def test_parenthetical_aside_in_final(server, client):
    visit(client, "/regions.html")
    assert check(server, "table-max-row", "FINAL: Baltic (Nordics was top in Q2)").passed
    assert not check(server, "table-max-row", "FINAL: Nordics (Baltic was Q3)").passed


def test_unlike_clause_without_final(server, client):
    visit(client, "/docs/guides/deployment/limits.html")
    assert check(server, "docs-nested-nav", "The upload limit is 73 MB, unlike the API limit of 12 MB.").passed


def test_final_after_text_on_same_line(server, client):
    assert final_answer("The result is 73 MB. FINAL: 73 MB") == "73 MB"
    assert final_answer("The final: not at line start") is None
    assert final_answer("a FINAL: 1\nlater FINAL: 2") == "2"
    visit(client, "/docs/guides/deployment/limits.html")
    assert check(server, "docs-nested-nav", "The result is 73 MB. FINAL: 73 MB").passed
    assert not check(server, "docs-nested-nav", "The limit is 73 MB. FINAL: 12 MB").passed


def test_list_shows_final_suffix(capsys):
    assert cli.main(["--list"]) == 0
    assert capsys.readouterr().out.count("FINAL: <answer>") == len(TASKS)


# ---- registry and hash ----------------------------------------------------------------------


def test_duplicate_task_ids_raise():
    with pytest.raises(ValueError, match="duplicate eval task id"):
        tasks._index_tasks([TASKS[0], TASKS[0]])
    assert len(tasks._index_tasks(TASKS)) == len(TASKS)


def test_hash_covers_checker_version_and_fixtures(monkeypatch):
    base = taskset_hash()
    with monkeypatch.context() as m:
        m.setattr(tasks, "CHECKER_VERSION", tasks.CHECKER_VERSION + "x")
        assert taskset_hash() != base
    with monkeypatch.context() as m:
        m.setattr(tasks, "_fixture_digest", lambda: "different pages")
        assert taskset_hash() != base
    assert taskset_hash() == base


# ---- compare --------------------------------------------------------------------------------


def entry(rate=1.0, n=2, **kw):
    e = {"category": "x", "safety": False, "n": n, "passes": round(rate * n), "pass_rate": rate, "mean_score": rate,
         "mean_steps": 4.0, "mean_duration_s": 1.0, "cost_usd": 0.01, "safety_violations": 0}
    e.update(kw)
    return e


def doc(tasks_, **meta):
    return {"schema_version": 1, "meta": {"taskset_hash": "h", "complete": True, **meta}, "tasks": tasks_}


def write(tmp_path, name, d):
    p = tmp_path / name / "results.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(d))
    return str(p)


def run_compare(tmp_path, a, b, *flags):
    return cli.main(["--compare", write(tmp_path, "a", a), write(tmp_path, "b", b), *flags])


def test_compare_missing_task_exits_1(tmp_path, capsys):
    a = doc({"t1": entry(), "t2": entry()})
    assert run_compare(tmp_path, a, doc({"t1": entry()})) == 1
    assert "MISSING" in capsys.readouterr().out


def test_compare_incomplete_exits_1(tmp_path):
    a = doc({"t1": entry()})
    assert run_compare(tmp_path, a, doc({"t1": entry()}, complete=False)) == 1


def test_compare_taskset_change_exits_2_unless_allowed(tmp_path, capsys):
    a, b = doc({"t1": entry()}), doc({"t1": entry()}, taskset_hash="other")
    assert run_compare(tmp_path, a, b) == 2
    assert "task set differs" in capsys.readouterr().out
    assert run_compare(tmp_path, a, b, "--allow-taskset-change") == 0


def test_compare_infra_errors_are_invalid_not_regressions(tmp_path, capsys):
    a = doc({"t1": entry()})
    b = doc({"t1": entry(0.0)})
    b["runs"] = [{"task_id": "t1", "status": "error", "error_kind": "chrome_missing"},
                 {"task_id": "t1", "status": "failed", "error_kind": "preflight"}]
    assert run_compare(tmp_path, a, b) == 2
    out = capsys.readouterr().out
    assert "INVALID" in out and "REGRESSION" not in out
    # the summary field alone is enough too
    assert run_compare(tmp_path, a, doc({"t1": entry(0.0, infra_errors=2)})) == 2
    # a minority of infra errors is an ordinary regression
    assert run_compare(tmp_path, a, doc({"t1": entry(0.5, n=4, infra_errors=1)})) == 1


def test_compare_score_tolerance_and_pass_tolerance(tmp_path):
    a = doc({"t1": entry(1.0)})
    assert run_compare(tmp_path, a, doc({"t1": entry(1.0, mean_score=0.95)})) == 0  # within the default 0.1
    b = doc({"t1": entry(1.0, mean_score=0.7)})
    assert run_compare(tmp_path, a, b) == 1
    assert run_compare(tmp_path, a, b, "--score-tolerance", "0.5") == 0
    b = doc({"t1": entry(0.5)})
    assert run_compare(tmp_path, a, b, "--tolerance", "0.5", "--score-tolerance", "0.6") == 0
    assert run_compare(tmp_path, a, b) == 1


def test_compare_steps_and_cost_warn_only_unless_strict(tmp_path, capsys):
    a = doc({"t1": entry()})
    b = doc({"t1": entry(mean_steps=7.0, cost_usd=0.02)})
    assert run_compare(tmp_path, a, b) == 0
    out = capsys.readouterr().out
    assert "mean steps rose" in out and "cost rose" in out
    assert run_compare(tmp_path, a, b, "--strict") == 1


def test_compare_flags_differing_n_and_min_n(tmp_path, capsys):
    a, b = doc({"t1": entry(n=3)}), doc({"t1": entry(n=1)})
    assert run_compare(tmp_path, a, b) == 0
    assert "runs differ (3 vs 1)" in capsys.readouterr().out
    assert run_compare(tmp_path, a, b, "--min-n", "2") == 2


def test_compare_malformed_task_entries_exit_2(tmp_path, capsys):
    good = doc({"t1": entry()})
    for bad in ({"t1": {"n": 2}}, {"t1": "nope"}, {"t1": entry(pass_rate="x")}):
        assert run_compare(tmp_path, good, doc(bad)) == 2
        err = capsys.readouterr().err
        assert "error:" in err and "Traceback" not in err
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"schema_version": 1, "tasks": []}))
    with pytest.raises(CompareError):
        load_results(p)


def test_compare_api_returns_exit_code():
    a, b = doc({"t1": entry()}), doc({"t1": entry(0.0)})
    assert compare_results(a, b).exit_code == 1 and compare_results(a, a).exit_code == 0


# ---- preflight and exit codes ---------------------------------------------------------------


def fake_config(**browser):
    return SimpleNamespace(
        model=SimpleNamespace(provider="fake", model="m"),
        safety=SimpleNamespace(allowed_domains=[]),
        browser=SimpleNamespace(channel="chrome", executable_path=None, cdp_url=None, **browser),
    )


def test_preflight_failure_runs_nothing_and_exits_2(tmp_path, capsys):
    calls = []

    async def fake(instruction, config, *, start_url):
        calls.append(1)

    rc = cli.main(["--tasks", "table-max-row", "--out", str(tmp_path)], run_fn=fake, config=fake_config(),
                  preflight=lambda cfg: ["Google Chrome was not found."])
    assert rc == 2 and not calls
    assert "pre-flight failed" in capsys.readouterr().err


def test_preflight_problems_checks_chrome(monkeypatch, tmp_path):
    import local_browser_agent.chrome as chrome

    cfg = fake_config()
    cfg.model = None
    monkeypatch.setattr(chrome, "find_chrome", lambda channel="chrome": None)
    assert cli.preflight_problems(cfg)
    monkeypatch.setattr(chrome, "find_chrome", lambda channel="chrome": "/usr/bin/chrome")
    assert cli.preflight_problems(cfg) == []
    cfg.browser.executable_path = str(tmp_path / "nope")
    assert "does not exist" in cli.preflight_problems(cfg)[0]
    cfg.browser.executable_path = None
    cfg.browser.cdp_url = "http://127.0.0.1:9222"
    monkeypatch.setattr(chrome, "find_chrome", lambda channel="chrome": None)
    assert cli.preflight_problems(cfg) == []  # attaching, so no local Chrome needed


def test_preflight_reports_provider_problem(monkeypatch):
    import local_browser_agent.models as models

    async def bad(cfg):
        raise models.PreFlightError("Anthropic API key is invalid")

    cfg = fake_config()
    cfg.browser.cdp_url = "http://127.0.0.1:9222"
    monkeypatch.setattr(models, "check_provider", bad)
    assert cli.preflight_problems(cfg) == ["Anthropic API key is invalid"]


def test_all_runs_errored_exits_1_even_without_fail_under(tmp_path, capsys):
    async def boom(instruction, config, *, start_url):
        raise RuntimeError("no browser")

    rc = cli.main(["--tasks", "table-max-row,delayed-content", "--out", str(tmp_path)], run_fn=boom,
                  config=fake_config())
    assert rc == 1
    assert "every run errored" in capsys.readouterr().err


async def test_error_kind_recorded(tmp_path):
    async def run(instruction, config, *, start_url):
        return SimpleNamespace(status="failed", final_result="", step_count=0, duration_s=0.0, cost_usd=None,
                               error_kind="chrome_missing")

    res = await run_suite(fake_config(), task_ids=["table-max-row"], out_dir=tmp_path, run_fn=run)
    assert res.runs[0].error_kind == "chrome_missing" and res.runs[0].infra_error
    assert res.task_summaries()["table-max-row"]["infra_errors"] == 1
    assert json.loads((tmp_path / "results.json").read_text())["runs"][0]["error_kind"] == "chrome_missing"


def test_invalid_flag_values_exit_2(monkeypatch, capsys):
    monkeypatch.delenv("LBA_BASE_URL", raising=False)
    rc = cli.main(["--provider", "openai_compatible", "--model", "m"])  # base_url is required
    assert rc == 2 and "invalid configuration" in capsys.readouterr().err
    cfg = cli._build_config(cli.build_parser().parse_args(
        ["--provider", "openai_compatible", "--model", "m", "--base-url", "http://x:1"]), "k")
    assert cfg.model.base_url == "http://x:1" and cfg.browser.headless is True
