"""Round-5: eval/CLI exit codes (3 = environment), --json on failure, compare validation, run-flag misuse."""
from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace

import pytest

from local_browser_agent import RunResult, cli as lba_cli
from local_browser_agent.evals import cli
from local_browser_agent.evals.compare import CompareError, compare_results, load_results
from local_browser_agent.evals.runner import RunRecord, SuiteResult
from tests.evals.test_strictness import doc, entry, fake_config, run_compare


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("LBA_"):
            monkeypatch.delenv(k)


# ---- eval exit codes / --json on failure ------------------------------------------------------


def test_preflight_failure_json_document(tmp_path, capsys):
    rc = cli.main(["--json", "--out", str(tmp_path)], config=fake_config(),
                  preflight=lambda c: ["provider is down"])
    out = capsys.readouterr()
    assert rc == 3
    d = json.loads(out.out)
    assert d["status"] == "error" and d["error_kind"] == "preflight"
    assert d["errors"] == ["provider is down"]
    assert "pre-flight failed" in out.err


def test_chrome_missing_kind(tmp_path, capsys):
    from local_browser_agent.chrome import CHROME_NOT_FOUND_MESSAGE

    rc = cli.main(["--json", "--out", str(tmp_path)], config=fake_config(), preflight=lambda c: [CHROME_NOT_FOUND_MESSAGE])
    assert rc == 3 and json.loads(capsys.readouterr().out)["error_kind"] == "chrome_missing"


def test_config_error_json_exit_2(capsys):
    rc = cli.main(["--json"])  # no provider/model
    d = json.loads(capsys.readouterr().out)
    assert rc == 2 and d["status"] == "error" and d["error_kind"] == "config"


def test_usage_error_json(capsys):
    rc = cli.main(["--json", "--repeats", "0"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 2 and d["error_kind"] == "usage"


def test_argparse_error_under_json(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--json", "--repeats", "x"])
    assert e.value.code == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"


def test_compare_invalid_input_json(tmp_path, capsys):
    p = tmp_path / "x.json"
    p.write_text("nope")
    assert cli.main(["--json", "--compare", str(p), str(p)]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "invalid_input"


# ---- eval --cdp-url / --max-steps -------------------------------------------------------------


def test_eval_rejects_bad_cdp_url_and_max_steps(capsys):
    assert cli.main(["--cdp-url", "ftp://x"]) == 2
    assert "--cdp-url" in capsys.readouterr().err
    assert cli.main(["--max-steps", "0"]) == 2
    assert cli.main(["--max-steps", "501"]) == 2


def test_eval_build_config_cdp_url(monkeypatch):
    monkeypatch.setenv("LBA_PROVIDER", "ollama")
    monkeypatch.setenv("LBA_MODEL", "m")
    args = cli.build_parser().parse_args(["--cdp-url", " http://127.0.0.1:9222 "])
    cfg = cli._build_config(args, None)
    assert cfg.browser.cdp_url == "http://127.0.0.1:9222"


async def test_max_steps_passthrough():
    from local_browser_agent.evals.runner import run_suite

    seen = []

    async def fake(instruction, config, *, start_url):
        seen.append(config.max_steps)
        return SimpleNamespace(status="success", final_result="", step_count=1, duration_s=0.1, cost_usd=None,
                               errors=[], blocked_actions=[], error_kind=None)

    cfgobj = SimpleNamespace(model=SimpleNamespace(provider="f", model="m"),
                             safety=SimpleNamespace(allowed_domains=[]), timeout_s=60, max_steps=25)
    res = await run_suite(cfgobj, task_ids=["table-max-row"], out_dir=None, run_fn=fake, max_steps=7)
    assert seen == [7] and res.meta["max_steps"] == {"table-max-row": 7}


# ---- compare: validation ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    entry(pass_rate=1.5), entry(n=3, passes=9, pass_rate=1.0), entry(n=3, passes=0, pass_rate=1.0),
    entry(pass_rate=-0.1), entry(n=2.5), entry(n=-1),
])
def test_compare_rejects_corrupt_entries(tmp_path, bad, capsys):
    good = doc({"t1": entry()})
    assert run_compare(tmp_path, good, doc({"t1": bad})) == 2
    assert "error:" in capsys.readouterr().err


def test_load_results_corrupt(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(doc({"t1": entry(n=3, passes=9, pass_rate=1.0)})))
    with pytest.raises(CompareError, match="passes"):
        load_results(p)


@pytest.mark.parametrize("flags", [["--tolerance", "-1"], ["--score-tolerance", "-0.5"], ["--tolerance", "2"],
                                   ["--tolerance", "nan"], ["--min-n", "0"]])
def test_compare_rejects_bad_tolerances(tmp_path, flags, capsys):
    a = doc({"t1": entry()})
    assert run_compare(tmp_path, a, a, *flags) == 2
    assert "lba eval: error:" in capsys.readouterr().err


@pytest.mark.parametrize("flags", [["--provider", "x"], ["--tasks", "t1"], ["--model", "m"], ["--repeats", "3"],
                                   ["--headed"], ["--cdp-url", "http://x:1"], ["--max-steps", "5"], ["--out", "o"]])
def test_compare_with_run_flags_is_usage_error(tmp_path, flags, capsys):
    a = doc({"t1": entry()})
    assert run_compare(tmp_path, a, a, *flags) == 2
    assert "would be ignored" in capsys.readouterr().err


def test_compare_n_rule():
    a, b = doc({"t1": entry(n=3)}), doc({"t1": entry(n=1)})
    assert compare_results(a, b).exit_code == 2
    assert compare_results(a, b, min_n=1).exit_code == 0
    # a candidate with more runs than the baseline is fine
    assert compare_results(b, a).exit_code == 0


def test_compare_n0_display_and_count(tmp_path, capsys):
    nan = float("nan")
    a = doc({"t1": entry(), "t2": entry()})
    b = doc({"t1": entry(n=0, passes=0, pass_rate=nan), "t2": entry(n=0, passes=0, pass_rate=nan)})
    assert run_compare(tmp_path, a, b) == 2
    out = capsys.readouterr().out
    assert "nan" not in out and "2 invalid task(s)" in out
    assert "runs differ" not in out


# ---- all-infra JSON ---------------------------------------------------------------------------


def _rec(**kw):
    base = dict(task_id="t", category="c", safety=False, repeat=1, passed=False, score=0.0, status="error",
                steps=0, duration_s=0.0, cost_usd=None, safety_violation=False, notes="", answer="", error_kind="chrome_missing")
    base.update(kw)
    return RunRecord(**base)


def test_all_infra_json_null_rates():
    d = SuiteResult(runs=[_rec(), _rec(repeat=2)]).to_dict()
    assert d["summary"]["success_rate"] is None and d["summary"]["mean_score"] is None
    ok = SuiteResult(runs=[_rec(passed=True, score=1.0, status="success", error_kind=None)]).to_dict()
    assert ok["summary"]["success_rate"] == 1.0


# ---- lba run ----------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["  "], [""], ["t", "--allowed-domain", ""], ["t", "--allowed-domain", "  "]])
def test_run_rejects_empty_task_and_domain(argv, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not preflight")

    monkeypatch.setattr("local_browser_agent.models.check_provider", boom)
    assert lba_cli.main(["run", *argv]) == 2
    assert "lba run: error:" in capsys.readouterr().err


def test_run_rejects_empty_task_json(capsys):
    assert lba_cli.main(["run", " ", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"


def test_config_errors_one_line_each_and_no_repeated_field(capsys):
    rc = lba_cli.main(["run", "t", "--max-steps", "9999", "--timeout", "-1"])
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 2 and len(err) >= 2
    assert all(ln.startswith("lba run: error: invalid configuration: ") for ln in err)


def test_config_problems_strips_field_repeat():
    from pydantic import ValidationError

    from local_browser_agent.config import BrowserConfig

    with pytest.raises(ValidationError) as e:
        BrowserConfig(cdp_url="nope")
    (line,) = lba_cli._config_problems(e.value)
    assert line.startswith("cdp_url: ") and not line.startswith("cdp_url: cdp_url")


def test_failed_run_message_printed_once(monkeypatch):
    lib = logging.getLogger("local_browser_agent")

    async def fake_run_task(task, cfg, **kw):
        lib.warning("run %s failed: %s", "rid", "boom")
        lib.warning("run %s failed (%s)", "rid", "agent_error")
        return RunResult(run_id="rid", task=task, status="error", success=False, errors=["boom"])

    import local_browser_agent

    monkeypatch.setattr(local_browser_agent, "run_task", fake_run_task)
    seen = []
    handler = logging.Handler()
    handler.emit = seen.append  # type: ignore[method-assign]
    lib.addHandler(handler)
    try:
        rc = lba_cli.main(["run", "do it", "--no-preflight"])
    finally:
        lib.removeHandler(handler)
    assert rc == 1
    assert not [r for r in seen if r.msg in ("run %s failed: %s", "run %s failed (%s)")]


@pytest.mark.parametrize("flag", ["--jso", "--js", "--json"])
def test_argparse_error_under_json_abbreviation(capsys, flag):
    with pytest.raises(SystemExit):
        cli.main([flag, "--repeats", "x"])
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"
