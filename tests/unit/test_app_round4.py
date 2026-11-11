"""Round-4 web-app fixes: boot task through the tracked start path, notices, run ids,
task-length message, --no-browser alias, /healthz."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import local_browser_agent.app.main as main_mod
import local_browser_agent.app.runner as runner_mod
from local_browser_agent.app.events import ModelInfoEvent, StateEvent

REPO = Path(__file__).resolve().parents[2]


def _cookies() -> dict[str, str]:
    return {main_mod.DISCLAIMER_COOKIE_NAME: main_mod._disclaimer_serializer().dumps("1")}


@pytest.fixture
def blocking_run(monkeypatch):
    """Replace run_agent with one that blocks until released; yields (started, release, calls)."""
    monkeypatch.setattr(main_mod, "_active_task", None)
    started, release, calls = asyncio.Event(), asyncio.Event(), []

    async def fake_run_agent(task, **kwargs):
        calls.append(task)
        started.set()
        await release.wait()

    monkeypatch.setattr(main_mod, "run_agent", fake_run_agent)
    yield started, release, calls
    release.set()


# ------------------------------------------------------------------ boot task

async def test_boot_task_with_disclaimer_is_tracked_and_blocks_run(monkeypatch, blocking_run):
    started, release, calls = blocking_run
    monkeypatch.setattr(main_mod.app.state, "pending_task", "boot task", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        assert (await c.get("/")).status_code == 200
        await asyncio.wait_for(started.wait(), 2)
        assert calls == ["boot task"]
        assert main_mod._active_task is not None and not main_mod._active_task.done()
        assert main_mod._active_queue is not None
        r = await c.post("/run", data={"task": "second"})
        assert r.status_code == 409
        # consumed: another page load does not start it again
        assert getattr(main_mod.app.state, "pending_task", None) is None
        release.set()
        await asyncio.wait_for(main_mod._active_task, 2)


async def test_boot_task_without_disclaimer_is_only_prefilled(monkeypatch, blocking_run):
    started, release, calls = blocking_run
    monkeypatch.setattr(main_mod.app.state, "pending_task", "find <b>cats</b>", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "find &lt;b&gt;cats&lt;/b&gt;" in r.text
    await asyncio.sleep(0.05)
    assert calls == [] and main_mod._active_task is None


async def test_run_clears_unconsumed_boot_task(monkeypatch, blocking_run):
    started, release, calls = blocking_run
    monkeypatch.setattr(main_mod.app.state, "pending_task", "boot", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        assert (await c.post("/run", data={"task": "manual"})).status_code == 200
        assert getattr(main_mod.app.state, "pending_task", None) is None
        release.set()
        await asyncio.wait_for(main_mod._active_task, 2)
    assert calls == ["manual"]


def test_help_documents_boot_task_behaviour():
    from local_browser_agent.app.__main__ import build_parser
    text = " ".join(build_parser().format_help().split())
    assert "pre-filled" in text and "--no-browser" in text


# ------------------------------------------------------------------ misc

def test_no_browser_alias_for_no_open(monkeypatch):
    import local_browser_agent.app.__main__ as entry
    calls = []
    monkeypatch.setattr(entry, "schedule_browser_open", lambda **k: calls.append(k))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(entry, "_port_free", lambda h, p: True)
    assert entry.main(["--no-browser", "--port", "9124"]) == 0
    assert calls == []
    assert entry.build_parser().parse_args(["--no-browser"]).no_open is True


async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_too_long_task_message_states_limit(monkeypatch, blocking_run):
    started, release, calls = blocking_run
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        r = await c.post("/run", data={"task": "x" * 2001})
        ok = await c.post("/run", data={"task": "x" * 2000})
    assert r.status_code == 422
    assert "2000" in r.json()["detail"] and "2001" in r.json()["detail"]
    assert ok.status_code == 200


async def test_page_has_char_counter():
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        html = (await c.get("/")).text
    assert "taskLen" in html and "/ 2000" in html


def test_notice_only_cleared_by_run_or_accept_and_lost_connection_sticks():
    html = (REPO / "local_browser_agent/app/templates/index.html").read_text(encoding="utf-8")
    assert "if (e.detail && e.detail.successful) lbaHideNotice();" not in html
    assert "path === '/run'" in html and "path === '/accept-disclaimer'" in html
    assert "lbaConnectionLost" in html and "source.onopen" in html


# ------------------------------------------------------------------ run ids on app-side events

async def test_app_sink_keeps_run_id_on_model_info_and_stopped():
    data_q, ctrl_q = asyncio.Queue(), asyncio.Queue()
    sink = runner_mod._AppQueueSink(data_q, ctrl_q, "openai", stopped_before_start=lambda: True)
    await sink(ModelInfoEvent(provider="litellm", model_name="m", run_id="run-123"))
    await sink(StateEvent(state="error", run_id="run-123"))
    events = [ctrl_q.get_nowait(), ctrl_q.get_nowait()]
    assert [e.run_id for e in events] == ["run-123", "run-123"]
    assert events[0].provider == "openai" and events[1].state == "stopped"


# ------------------------------------------------------------------ security headers

@pytest.mark.parametrize("path,host", [("/healthz", "test"), ("/", "test"), ("/nope", "test"),
                                        ("/healthz", "evil.example")])
async def test_security_headers_on_every_response(path, host):
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.get(path, headers={"host": host})
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"


def test_existing_csp_is_merged_not_replaced():
    from fastapi.responses import Response
    r = Response(headers={"Content-Security-Policy": "default-src 'self'"})
    main_mod._add_security_headers(r)
    assert r.headers["content-security-policy"] == "default-src 'self'; frame-ancestors 'none'"
    r2 = Response(headers={"Content-Security-Policy": "frame-ancestors 'self'"})
    main_mod._add_security_headers(r2)
    assert r2.headers["content-security-policy"] == "frame-ancestors 'self'"
