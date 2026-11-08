from __future__ import annotations

from local_browser_agent.evals import cli
from local_browser_agent.evals.selftest import run_self_test, scan_site_for_external_resources
from local_browser_agent.evals.tasks import TASKS


def test_task_registry_shape():
    assert len(TASKS) >= 12
    assert len({t.id for t in TASKS}) == len(TASKS)
    safety = [t for t in TASKS if t.safety]
    assert len(safety) >= 3 and all(t.reckless for t in safety)
    assert {"safety"} == {t.category for t in safety}


def test_full_self_test_passes():
    res = run_self_test()
    assert res.ok, [(o.task_id, o.notes) for o in res.outcomes if not o.ok] + res.site_problems
    assert [o.task_id for o in res.outcomes] == [t.id for t in TASKS]
    for o in res.outcomes:
        assert o.oracle_score == 1.0 and o.null_failed
        assert (o.reckless_failed is True) == o.safety


def test_site_has_no_external_resources():
    assert scan_site_for_external_resources() == []


def test_cli_list(capsys):
    assert cli.main(["--list"]) == 0
    out = capsys.readouterr().out
    for t in TASKS:
        assert t.id in out and t.category in out
    assert "Blue Kettle" in out


def test_cli_self_test(capsys):
    assert cli.main(["--self-test"]) == 0
    out = capsys.readouterr().out
    assert "self-test: OK" in out and "safety-cart-no-order" in out


def test_cli_rejects_bad_args(capsys):
    assert cli.main(["--tasks", "nope"]) == 2
    assert cli.main(["--provider", "x"]) == 2  # model missing
    assert cli.main(["--provider", "x", "--model", "y", "--api-key-env", "NO_SUCH_VAR_XYZ"]) == 2
    err = capsys.readouterr().err
    assert "unknown task" in err and "NO_SUCH_VAR_XYZ" in err
