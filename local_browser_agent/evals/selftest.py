"""Harness self-test: proves fixtures and checkers are sound without a browser or an LLM."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from .server import SITE_DIR, FixtureServer
from .tasks import TASKS


@dataclass
class TaskOutcome:
    task_id: str
    safety: bool
    oracle_passed: bool = False
    oracle_score: float = 0.0
    null_failed: bool = False
    null_score: float = 1.0
    reckless_failed: bool | None = None  # None for non-safety tasks
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.oracle_passed
            and self.oracle_score == 1.0
            and self.null_failed
            and (self.reckless_failed is not False)
        )


@dataclass
class SelfTestResult:
    outcomes: list[TaskOutcome]
    site_problems: list[str]

    @property
    def ok(self) -> bool:
        return bool(self.outcomes) and not self.site_problems and all(o.ok for o in self.outcomes)


def scan_site_for_external_resources() -> list[str]:
    """Fixture pages must be self-contained: no CDN, no external src/href (except the off-site trap)."""
    problems: list[str] = []
    for f in sorted(SITE_DIR.rglob("*")):
        if f.suffix not in {".html", ".css", ".js"}:
            continue
        text = f.read_text(encoding="utf-8").replace("__OFFSITE_URL__", "")
        for m in re.finditer(r"(?:src|href)\s*=\s*[\"'](https?:)?//[^\"']+|url\(\s*[\"']?(https?:)?//", text):
            problems.append(f"{f.relative_to(SITE_DIR)}: external reference {m.group(0)!r}")
    return problems


def run_self_test() -> SelfTestResult:
    outcomes: list[TaskOutcome] = []
    problems = scan_site_for_external_resources()
    ids = [t.id for t in TASKS]
    if len(ids) != len(set(ids)):
        problems.append("duplicate task ids")

    with FixtureServer() as server, httpx.Client(base_url=server.base_url, timeout=10) as client:
        for task in TASKS:
            out = TaskOutcome(task_id=task.id, safety=task.safety)
            # start page must be served
            server.reset()
            r = client.get(task.start_path)
            if r.status_code != 200:
                problems.append(f"{task.id}: start_path {task.start_path} returned {r.status_code}")
            if "{base_url}" in task.render(server.base_url):
                problems.append(f"{task.id}: unrendered template in instruction")

            # (a) oracle passes with score 1.0
            server.reset()
            try:
                answer = task.oracle(client, server.base_url)
                res = task.check(server.state, answer)
                out.oracle_passed, out.oracle_score = res.passed, res.score
                if not res.passed:
                    out.notes.append(f"oracle failed: {res.notes}")
                # (c) reckless action after oracle must fail
                if task.safety:
                    if task.reckless is None:
                        out.reckless_failed = False
                        out.notes.append("safety task has no reckless()")
                    else:
                        task.reckless(client, server.base_url)
                        res2 = task.check(server.state, answer)
                        out.reckless_failed = (not res2.passed) and res2.violation
                        if not out.reckless_failed:
                            out.notes.append(f"reckless run still passed or no violation flagged: {res2.notes}")
            except Exception as exc:  # noqa: BLE001
                out.notes.append(f"oracle/reckless raised {type(exc).__name__}: {exc}")

            # (b) null agent fails
            server.reset()
            res0 = task.check(server.state, "")
            out.null_failed, out.null_score = (not res0.passed), res0.score
            if res0.passed:
                out.notes.append("null agent passed")
            outcomes.append(out)

    return SelfTestResult(outcomes=outcomes, site_problems=problems)
