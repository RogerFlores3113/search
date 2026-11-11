"""Round-4 hardening: trailing hedges, multi-code answers, checker-aware hash, ranges, compare validity,
infra fail-fast, --json/--quiet and the ``lba eval:`` error prefix."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from local_browser_agent.evals import cli, tasks
from local_browser_agent.evals.compare import compare_results
from local_browser_agent.evals.runner import run_suite
from local_browser_agent.evals.tasks import TASKS_BY_ID, task_hash, taskset_hash


def run_oracle_then_check(server, client, task_id, answer):
    t = TASKS_BY_ID[task_id]
    t.oracle(client, server.base_url)
    return t.check(server.state, answer).passed


# ---- golden verdicts: any change to a verdict shows up in review --------------------------------

GOLDEN = [
    # read-product-fact (73 MB)
    ("docs-nested-nav", "FINAL: 73 MB", True),
    ("docs-nested-nav", "FINAL: 73 MB (the API limit is 12 MB)", True),
    ("docs-nested-nav", "The limit is 73 MB.\nFINAL: 73 MB", True),
    ("docs-nested-nav", "FINAL: 73 MB maybe", False),
    ("docs-nested-nav", "FINAL: 73 MB probably", False),
    ("docs-nested-nav", "FINAL: 73 MB (I think)", False),
    ("docs-nested-nav", "FINAL: 73 MB, I guess", False),
    ("docs-nested-nav", "FINAL: 73 MB - not sure", False),
    ("docs-nested-nav", "FINAL: 73 MB, unsure", False),
    ("docs-nested-nav", "FINAL: 73 MB seems right", False),
    ("docs-nested-nav", "FINAL: 73 MB cannot be confirmed", False),
    ("docs-nested-nav", "FINAL: 73 MB (unverified)", False),
    ("docs-nested-nav", "FINAL: I could not verify, but 73 MB", False),
    ("docs-nested-nav", "FINAL: 73 MB was in a search result", False),
    ("docs-nested-nav", "FINAL: 60-73 MB", False),
    ("docs-nested-nav", "FINAL: 73-80 MB", False),
    ("docs-nested-nav", "73 MB? Maybe.", False),
    ("docs-nested-nav", "73 MB could be the limit", False),
    ("docs-nested-nav", "The file limit is 73 MB.", True),
    # pagination (Baltic)
    ("table-max-row", "FINAL: Baltic (Nordics was top in Q2)", True),
    ("table-max-row", "FINAL: Baltic (maybe)", False),
    # table-max-row (SAVE-3917)
    ("cookie-banner", "FINAL: SAVE-3917", True),
    ("cookie-banner", "FINAL: SAVE 3917", True),
    ("cookie-banner", "FINAL: SAVE-3917 or SAVE-3918", False),
    ("cookie-banner", "FINAL: SAVE-3917, SAVE-1111", False),
    ("cookie-banner", "FINAL: SAVE-3917 and also SAVE-2222", False),
]


@pytest.mark.parametrize("task_id,answer,expected", GOLDEN, ids=[f"{t}-{a}" for t, a, _ in GOLDEN])
def test_golden_verdicts(server, client, task_id, answer, expected):
    assert run_oracle_then_check(server, client, task_id, answer) is expected


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("FINAL: RPT-40817", True),
        ("FINAL: RPT-40817 or REF-5521", False),
        ("FINAL: RPT-40817, RPT-40818", False),
    ],
)
def test_report_code_competitors(server, client, answer, expected):
    assert run_oracle_then_check(server, client, "delayed-content", answer) is expected


def test_time_ranges_still_accepted(server, client):
    # time answers are exempt from the range rule ("7:30 - 13:45" lists two different times)
    assert run_oracle_then_check(server, client, "safety-offsite-link", "Saturday 7:30 - 13:45")


# ---- taskset hash covers checker source ------------------------------------------------------


def test_hash_changes_with_checker_source(monkeypatch):
    base, one = taskset_hash(), task_hash(TASKS_BY_ID["table-max-row"])
    monkeypatch.setattr(tasks, "_checker_digest", lambda: "edited")
    assert taskset_hash() != base
    assert task_hash(TASKS_BY_ID["table-max-row"]) != one


def test_hash_ignores_line_endings(tmp_path, monkeypatch):
    src = tasks.Path(tasks.__file__).read_bytes()
    lf = tmp_path / "lf.py"
    crlf = tmp_path / "crlf.py"
    lf.write_bytes(src.replace(b"\r\n", b"\n"))
    crlf.write_bytes(src.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    monkeypatch.setattr(tasks, "__file__", str(lf))
    a = taskset_hash()
    monkeypatch.setattr(tasks, "__file__", str(crlf))
    assert taskset_hash() == a


# ---- compare validity ------------------------------------------------------------------------


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


def test_compare_zero_runs_is_invalid():
    cmp = compare_results(doc({"t": entry()}), doc({"t": entry(0.0, n=0)}))
    assert cmp.exit_code == 2 and not cmp.regressions


@pytest.mark.parametrize("field", ["pass_rate", "mean_score"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_compare_non_finite_is_invalid(field, bad):
    cmp = compare_results(doc({"t": entry()}), doc({"t": entry(**{field: bad})}))
    assert cmp.exit_code == 2 and not cmp.regressions


def test_compare_some_infra_no_passes_is_invalid():
    # 1 infra error of 3 runs, 0 passes, 2 real failures: infra < failures -> ordinary regression
    reg = compare_results(doc({"t": entry(1.0)}), doc({"t": entry(0.0, n=3, infra_errors=1)}))
    assert reg.exit_code == 1
    # 2 infra errors, 0 passes, 1 real failure: infra >= failures -> invalid
    inv = compare_results(doc({"t": entry(1.0)}), doc({"t": entry(0.0, n=3, infra_errors=2)}))
    assert inv.exit_code == 2
    # 1 infra error, 1 pass: not invalid
    ok = compare_results(doc({"t": entry(1.0)}), doc({"t": entry(0.5, n=2, infra_errors=1)}))
    assert ok.exit_code == 1 and not ok.invalid


def test_compare_headers_are_distinct(tmp_path, capsys):
    a = write(tmp_path, "run1", doc({"t": entry()}))
    b = write(tmp_path, "run2", doc({"t": entry()}))
    assert cli.main(["--compare", a, b]) == 0
    head = capsys.readouterr().out.splitlines()[0]
    assert "run1/results" in head and "run2/results" in head
    same = tmp_path / "x" / "results.json"
    assert cli._labels(str(same), str(same)) == ("baseline", "candidate")


def test_compare_subset_with_matching_task_hashes(tmp_path, capsys):
    full = doc({"t1": entry(), "t2": entry()}, taskset_hash="full", task_hashes={"t1": "a", "t2": "b"})
    sub = doc({"t1": entry()}, taskset_hash="sub", task_hashes={"t1": "a"})
    cmp = compare_results(full, sub)
    assert cmp.exit_code == 0 and [d.task_id for d in cmp.deltas] == ["t1"]
    assert any("subset" in w for w in cmp.warnings)


def test_compare_subset_with_other_hashes_gives_specific_message():
    full = doc({"t1": entry(), "t2": entry()}, taskset_hash="full", task_hashes={"t1": "a", "t2": "b"})
    sub = doc({"t1": entry()}, taskset_hash="sub", task_hashes={"t1": "CHANGED"})
    cmp = compare_results(full, sub)
    assert cmp.exit_code == 2
    assert cmp.invalid_reasons == [
        "candidate ran a subset of tasks; rerun the full suite or pass --allow-taskset-change"
    ]
    assert compare_results(full, sub, allow_taskset_change=True).exit_code == 1  # t2 missing


def test_run_records_per_task_hashes(tmp_path):
    async def fake(instruction, config, *, start_url):
        return SimpleNamespace(status="success", final_result="x", step_count=1, duration_s=1.0, cost_usd=None,
                               errors=[], blocked_actions=[])

    import asyncio

    out = asyncio.run(run_suite(make_config(), task_ids=["table-max-row"], out_dir=None, run_fn=fake))
    assert out.meta["task_hashes"] == {"table-max-row": task_hash(TASKS_BY_ID["table-max-row"])}


# ---- infra fail-fast -------------------------------------------------------------------------


def make_config():
    return SimpleNamespace(
        model=SimpleNamespace(provider="fake", model="m-1"),
        safety=SimpleNamespace(allowed_domains=["x.example"]),
        timeout_s=600,
        max_steps=25,
    )


def infra_res(kind="cdp_connect"):
    return SimpleNamespace(status="error", final_result="", step_count=0, duration_s=0.1, cost_usd=None,
                           errors=["boom"], blocked_actions=[], error_kind=kind)


async def test_run_aborts_after_consecutive_infra_errors(tmp_path):
    calls = []

    async def fake(instruction, config, *, start_url):
        calls.append(1)
        return infra_res()

    out = await run_suite(make_config(), repeats=3, out_dir=tmp_path, run_fn=fake)
    assert len(calls) == 2 and out.meta["complete"] is False and out.meta["stopped_reason"] == "infra_errors"
    saved = json.loads((tmp_path / "results.json").read_text())
    assert saved["meta"]["complete"] is False and "infra_abort" in saved["meta"]


async def test_non_consecutive_infra_errors_do_not_abort():
    kinds = iter(["cdp_connect", None, "cdp_connect", None])

    async def fake(instruction, config, *, start_url):
        k = next(kinds)
        return infra_res(k) if k else SimpleNamespace(status="success", final_result="x", step_count=1,
                                                      duration_s=1.0, cost_usd=None, errors=[], blocked_actions=[])

    out = await run_suite(make_config(), task_ids=["table-max-row"], repeats=4, out_dir=None, run_fn=fake)
    assert out.total_runs == 4 and out.meta["complete"] is True


def test_cli_infra_abort_exit_2_one_line_no_zero_percent(tmp_path, capsys):
    async def fake(instruction, config, *, start_url):
        return infra_res("chrome_missing")

    rc = cli.main(["--repeats", "5", "--out", str(tmp_path)], run_fn=fake, config=make_config())
    cap = capsys.readouterr()
    assert rc == 2
    assert "no valid runs (infra errors)" in cap.out and "success rate" not in cap.out
    assert cap.out.count("[INFRA]") == 2 and "Traceback" not in cap.out + cap.err
    assert "consecutive infrastructure errors" in cap.err


def test_cli_max_infra_errors_flag(tmp_path):
    calls = []

    async def fake(instruction, config, *, start_url):
        calls.append(1)
        return infra_res()

    cli.main(["--tasks", "table-max-row", "--repeats", "6", "--max-infra-errors", "4", "--out", str(tmp_path)],
             run_fn=fake, config=make_config())
    assert len(calls) == 4


# ---- exclusive modes, --json, --quiet, prefix --------------------------------------------------


@pytest.mark.parametrize("argv", [["--list", "--self-test"], ["--compare", "a", "b", "--list"], ["--self-test", "--compare", "a", "b"]])
def test_exclusive_modes_exit_2(argv, capsys):
    assert cli.main(argv) == 2
    assert "lba eval: error: choose one of --compare, --list, --self-test" in capsys.readouterr().err


def test_error_prefix_and_prog(capsys):
    assert cli.main(["--repeats", "0"]) == 2
    assert capsys.readouterr().err.startswith("lba eval: error: ")
    with pytest.raises(SystemExit):
        cli.main(["--bogus"])
    assert "lba eval: error:" in capsys.readouterr().err
    assert cli.build_parser().prog == "lba eval"


def test_json_list_and_compare(tmp_path, capsys):
    assert cli.main(["--list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {t["id"] for t in data} == set(TASKS_BY_ID)
    a = write(tmp_path, "a", doc({"t": entry()}))
    b = write(tmp_path, "b", doc({"t": entry(0.0)}))
    assert cli.main(["--compare", a, b, "--json"]) == 1
    cap = capsys.readouterr()
    parsed = json.loads(cap.out)
    assert parsed["exit_code"] == 1 and "REGRESSION" in cap.err


def test_json_and_quiet_run(tmp_path, capsys):
    async def fake(instruction, config, *, start_url):
        return SimpleNamespace(status="success", final_result="nope", step_count=1, duration_s=1.0, cost_usd=None,
                               errors=[], blocked_actions=[])

    cli.main(["--tasks", "table-max-row", "--json", "--out", str(tmp_path)], run_fn=fake, config=make_config())
    cap = capsys.readouterr()
    assert json.loads(cap.out)["schema_version"] == 1
    assert "[FAIL]" in cap.err and "success rate" in cap.err

    cli.main(["--tasks", "table-max-row", "-q", "--out", str(tmp_path)], run_fn=fake, config=make_config())
    cap = capsys.readouterr()
    assert cap.out == "" and "[FAIL]" not in cap.err
