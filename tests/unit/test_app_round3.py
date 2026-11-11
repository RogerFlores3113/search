"""Round-3 web-app fixes: strict Host parsing, whitespace task, stop-in-preflight state,
CLI flag strictness, busy port, stale-page error handling in the template, frozen specs."""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import local_browser_agent.app.main as main_mod
from local_browser_agent.app.events import ErrorEvent, StateEvent

REPO = Path(__file__).resolve().parents[2]


def _cookies() -> dict[str, str]:
    return {main_mod.DISCLAIMER_COOKIE_NAME: main_mod._disclaimer_serializer().dumps("1")}


# --------------------------------------------------------------------------- host parsing

@pytest.mark.parametrize("netloc,expected", [
    ("localhost:8080", "localhost"),
    ("127.0.0.1", "127.0.0.1"),
    ("[::1]:8080", "[::1]"),
    ("LocalHost", "localhost"),
    ("localhost:1@evil.com", ""),
    ("localhost:8080, evil.com", ""),
    ("evil.com@localhost", ""),
    ("localhost:abc", ""),
    ("localhost:", ""),
    ("localhost/x", ""),
    ("[::1", ""),
    ("[::1]x", ""),
    ("", ""),
    (":8080", ""),
    ("localhost evil.com", ""),
])
def test_hostname_of_is_strict(netloc, expected):
    assert main_mod._hostname_of(netloc) == expected


@pytest.mark.parametrize("host", ["localhost:1@evil.com", "localhost:8080, evil.com"])
async def test_tricky_host_headers_rejected(monkeypatch, host):
    monkeypatch.setattr(main_mod, "_EXTRA_ALLOWED_HOSTS", set())
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://127.0.0.1:8080") as c:
        r = await c.get("/api/settings", headers={"host": host})
    assert r.status_code == 403


# --------------------------------------------------------------------------- run validation

async def test_whitespace_only_task_rejected(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    started = MagicMock()
    monkeypatch.setattr(main_mod, "run_agent", started)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        r = await c.post("/run", data={"task": "   \n\t "})
    assert r.status_code == 422 and "task" in r.json()["detail"].lower()
    started.assert_not_called()


async def test_task_is_stripped_before_running(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    seen: dict = {}
    done = asyncio.Event()

    async def stub(task, **kw):
        seen["task"] = task
        done.set()

    monkeypatch.setattr(main_mod, "run_agent", stub)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        r = await c.post("/run", data={"task": "  find cats  "})
        await asyncio.wait_for(done.wait(), 2)
    assert r.status_code == 200 and seen["task"] == "find cats"


async def test_error_responses_carry_detail(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_agent", None)
    fake = MagicMock()
    fake.done.return_value = False
    monkeypatch.setattr(main_mod, "_active_task", fake)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        for path, status in (("/run", 409), ("/pause", 400), ("/stop", 400)):
            r = await c.post(path, data={"task": "x"})
            assert r.status_code == status and r.json().get("detail")
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test") as c:
        r = await c.post("/run", data={"task": "x"})
    assert r.status_code == 403 and r.json()["detail"]


# --------------------------------------------------------------------------- stop in pre-flight

async def test_stop_in_preflight_is_stopped_not_error(monkeypatch, training_dir):
    import local_browser_agent.app.runner as runner_mod

    started = asyncio.Event()

    async def hang(cfg):
        started.set()
        await asyncio.sleep(60)

    async def noop(*a, **kw):
        return None

    monkeypatch.setattr(runner_mod, "pre_flight_check", hang)
    monkeypatch.setattr(runner_mod.history_db, "insert_run", noop)
    monkeypatch.setattr(runner_mod.training_sink, "backfill_run_success", noop)
    holder: dict = {}
    ctrl_q: asyncio.Queue = asyncio.Queue()
    with patch("local_browser_agent.runner.build_browser_session"):
        task = asyncio.create_task(runner_mod.run_agent(
            "t", queue=asyncio.Queue(), control_queue=ctrl_q,
            on_agent=lambda a: holder.__setitem__("agent", a) if a else None))
        await asyncio.wait_for(started.wait(), 5)
        runner_mod.stop_agent(holder["agent"])
        await asyncio.wait_for(task, 5)
    events = [ctrl_q.get_nowait() for _ in range(ctrl_q.qsize())]
    assert not [e for e in events if isinstance(e, ErrorEvent)]
    states = [e.state for e in events if isinstance(e, StateEvent)]
    assert states[-1] == "stopped" and "error" not in states


# --------------------------------------------------------------------------- entry point

@pytest.fixture
def entry(monkeypatch):
    import local_browser_agent.app.__main__ as e

    monkeypatch.setattr(e.uvicorn, "run", MagicMock())
    monkeypatch.setattr(e, "schedule_browser_open", MagicMock())
    monkeypatch.setattr(e, "chrome_is_installed", lambda: True)
    monkeypatch.setattr(e, "_port_free", lambda h, p: True)
    return e


@pytest.mark.parametrize("argv", [["--prot", "18769"], ["--bogus"], ["--po", "9000"], ["--port", "x"], ["--port", "0"]])
def test_unknown_or_bad_flags_rejected(entry, argv):
    with pytest.raises(SystemExit) as ei:
        entry.main(argv)
    assert ei.value.code == 2
    entry.uvicorn.run.assert_not_called()


def test_task_after_double_dash_is_accepted(entry):
    from local_browser_agent.app.main import app

    entry.main(["--no-open", "--", "--weird", "task"])
    assert app.state.pending_task == "--weird task"
    app.state.pending_task = None


def test_blank_task_rejected(entry):
    with pytest.raises(SystemExit) as ei:
        entry.main(["   "])
    assert ei.value.code == 2


def test_busy_port_exits_nonzero_without_opening_browser(entry, monkeypatch, capsys):
    monkeypatch.setattr(entry, "_port_free", lambda h, p: False)
    assert entry.main(["--port", "8123"]) == 1
    assert "8123" in capsys.readouterr().err
    entry.uvicorn.run.assert_not_called()
    entry.schedule_browser_open.assert_not_called()


def test_port_free_detects_listener():
    import local_browser_agent.app.__main__ as e

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert e._port_free("127.0.0.1", port) is False
    assert e._port_free("127.0.0.1", port) is True


# --------------------------------------------------------------------------- templates / specs

def test_index_has_stale_page_and_connection_handlers():
    html = (REPO / "local_browser_agent/app/templates/index.html").read_text()
    assert "htmx:responseError" in html and "htmx:sendError" in html
    assert "This page is out of date. Reload to continue." in html
    assert "Lost connection to the app" in html and "source.onerror" in html
    assert "agentActive" in html and "Starting" in html
    assert "'stopped'" in html


def test_no_chrome_page_has_check_again():
    assert "Check again" in (REPO / "local_browser_agent/app/templates/no_chrome.html").read_text()


@pytest.mark.parametrize("spec", ["local-browser-agent.spec", "local-browser-agent-windows.spec"])
def test_specs_collect_all_package_submodules(spec):
    assert 'collect_submodules("local_browser_agent")' in (REPO / spec).read_text()
