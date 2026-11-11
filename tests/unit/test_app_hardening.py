"""Web-app hardening: request security, stream replay, friendly errors, history, stop in
pre-flight, settings, entry point (--help/--smoke) and frozen-build spec/CI checks."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import local_browser_agent.app.main as main_mod
from local_browser_agent.app.events import ErrorEvent, StateEvent, SummaryEvent

REPO = Path(__file__).resolve().parents[2]


def _cookies() -> dict[str, str]:
    return {main_mod.DISCLAIMER_COOKIE_NAME: main_mod._disclaimer_serializer().dumps("1")}


def _client(base_url: str = "http://127.0.0.1:8080", **kw) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=main_mod.app), base_url=base_url, **kw)


# --------------------------------------------------------------------------- security

@pytest.fixture
def strict(monkeypatch):
    """Turn the real request security back on (conftest relaxes it)."""
    monkeypatch.setattr(main_mod, "_EXTRA_ALLOWED_HOSTS", set())
    monkeypatch.setattr(main_mod, "_REQUIRE_TOKEN", True)


async def test_foreign_host_rejected(strict):
    async with _client("http://evil.example:8080") as c:
        assert (await c.get("/")).status_code == 403
        assert (await c.get("/api/settings")).status_code == 403
        assert (await c.get("/stream")).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "localhost:9000", "localhost", "[::1]:8080"])
async def test_local_hosts_accepted(strict, host):
    async with _client(f"http://{host}") as c:
        assert (await c.get("/api/settings")).status_code == 200


async def test_post_requires_token(strict):
    async with _client() as c:
        r = await c.post("/accept-disclaimer")
        assert r.status_code == 403
        r = await c.post("/accept-disclaimer", headers={"X-LBA-Token": "wrong"})
        assert r.status_code == 403
        r = await c.post("/accept-disclaimer", headers={"X-LBA-Token": main_mod.SECURITY_TOKEN})
        assert r.status_code == 200


async def test_cross_origin_post_rejected_even_with_token(strict):
    good = {"X-LBA-Token": main_mod.SECURITY_TOKEN}
    async with _client() as c:
        for hdrs in (
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
            {"Referer": "https://evil.example/page"},
        ):
            r = await c.post("/accept-disclaimer", headers={**good, **hdrs})
            assert r.status_code == 403, hdrs
        r = await c.post("/accept-disclaimer", headers={**good, "Origin": "http://127.0.0.1:8080"})
        assert r.status_code == 200
        r = await c.post("/accept-disclaimer", headers={**good, "Referer": "http://127.0.0.1:8080/"})
        assert r.status_code == 200


async def test_index_embeds_token_for_htmx_and_fetch(strict):
    async with _client() as c:
        body = (await c.get("/")).text
    assert main_mod.SECURITY_TOKEN in body
    assert "hx-headers" in body and 'name="lba-token"' in body
    assert "lbaHeaders()" in body


# --------------------------------------------------------------------------- stream replay

async def test_fast_failure_is_replayed_to_late_client(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)
    monkeypatch.setattr(main_mod, "_active_control_queue", None)

    async def failing_run(task, *, queue=None, control_queue=None, **kw):
        await control_queue.put(StateEvent(state="running"))
        await control_queue.put(ErrorEvent(message="No Anthropic API key is set. Open Settings"))
        await control_queue.put(StateEvent(state="error"))

    monkeypatch.setattr(main_mod, "run_agent", failing_run)
    async with _client(cookies=_cookies()) as c:
        r = await c.post("/run", data={"task": "x"})
        assert r.status_code == 200
        await main_mod._active_task if main_mod._active_task else None
        await asyncio.sleep(0.05)
        assert main_mod._active_queue is None  # queues torn down before the client connects
        body = (await c.get("/stream")).text
        assert "event: error_msg" in body and "Open Settings" in body
        assert '"state": "error"' in body or '"state":"error"' in body
        assert "event: done" in body
        # delivered once: a later connection (page reload) is idle again
        again = (await c.get("/stream")).text
        assert "error_msg" not in again and "idle" in again


async def test_crashing_run_surfaces_error(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)

    async def boom(task, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(main_mod, "run_agent", boom)
    async with _client(cookies=_cookies()) as c:
        await c.post("/run", data={"task": "x"})
        await asyncio.sleep(0.05)
        body = (await c.get("/stream")).text
    assert "kaboom" in body


async def test_summary_replayed(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    monkeypatch.setattr(main_mod, "_active_queue", None)

    async def ok(task, *, queue=None, control_queue=None, **kw):
        await control_queue.put(SummaryEvent(text="all good"))
        await control_queue.put(StateEvent(state="complete"))

    monkeypatch.setattr(main_mod, "run_agent", ok)
    async with _client(cookies=_cookies()) as c:
        await c.post("/run", data={"task": "x"})
        await asyncio.sleep(0.05)
        body = (await c.get("/stream")).text
    assert "all good" in body and "complete" in body


# --------------------------------------------------------------------------- index wiring

def test_index_reconnects_stream_and_has_human_banner():
    html = (REPO / "local_browser_agent/app/templates/index.html").read_text()
    assert "addEventListener('streamStarted'" in html
    assert "handleHumanNeeded" in html and "human_needed" in html
    assert "Resume" in html and "CAPTCHA" in html
    assert "check your config" not in html


# --------------------------------------------------------------------------- friendly errors

async def test_missing_key_message_points_to_settings(monkeypatch_env):
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    monkeypatch_env.setenv("PROVIDER", "anthropic")
    with pytest.raises(PreFlightError) as ei:
        await pre_flight_check(Settings())
    assert "Settings" in str(ei.value) and ".env" not in str(ei.value)


async def test_network_failure_is_not_reported_as_invalid_key(monkeypatch_env):
    import anthropic
    import httpx
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    monkeypatch_env.setenv("PROVIDER", "anthropic")
    monkeypatch_env.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    client = MagicMock()
    client.models.list = AsyncMock(side_effect=anthropic.APIConnectionError(
        request=httpx.Request("GET", "https://api.anthropic.com")))
    with patch("anthropic.AsyncAnthropic", return_value=client):
        with pytest.raises(PreFlightError) as ei:
            await pre_flight_check(Settings())
    msg = str(ei.value).lower()
    assert "internet connection" in msg and "invalid" not in msg and "rejected" not in msg


async def test_ollama_messages_are_actionable(mock_ollama_unreachable):
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError) as ei:
        await pre_flight_check(Settings())
    assert "ollama serve" in str(ei.value) and "ollama pull" in str(ei.value)


async def test_ollama_model_missing_message(mock_ollama_model_missing):
    from local_browser_agent.app.config import Settings
    from local_browser_agent.app.runner import PreFlightError, pre_flight_check

    with pytest.raises(PreFlightError) as ei:
        await pre_flight_check(Settings())
    assert "ollama pull" in str(ei.value)


async def _run_and_collect(monkeypatch, preflight=None, chrome=True):
    import local_browser_agent.app.runner as runner_mod

    monkeypatch.setattr(runner_mod, "chrome_is_installed", lambda: chrome)
    if preflight is not None:
        monkeypatch.setattr(runner_mod, "pre_flight_check", preflight)
    inserted: dict = {}

    async def fake_insert(**kw):
        inserted.update(kw)

    monkeypatch.setattr(runner_mod.history_db, "insert_run", fake_insert)
    monkeypatch.setattr(runner_mod.training_sink, "backfill_run_success", AsyncMock())
    return runner_mod, inserted


async def test_chrome_missing_shows_plain_message_with_link(monkeypatch, training_dir):
    runner_mod, inserted = await _run_and_collect(monkeypatch, preflight=AsyncMock(), chrome=False)
    data_q: asyncio.Queue = asyncio.Queue()
    ctrl_q: asyncio.Queue = asyncio.Queue()
    with patch("local_browser_agent.runner.build_browser_session") as launch:
        await runner_mod.run_agent("t", queue=data_q, control_queue=ctrl_q)
        launch.assert_not_called()
    events = [ctrl_q.get_nowait() for _ in range(ctrl_q.qsize())]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors and "https://www.google.com/chrome/" in errors[0].message
    assert inserted["status"] == "error" and "chrome" in inserted["error"].lower()


async def test_friendly_preflight_message_reaches_ui_and_history(monkeypatch, training_dir):
    from local_browser_agent.app.runner import PreFlightError

    async def failing(cfg):
        raise PreFlightError("Ollama is not running. Start it with: ollama serve")

    runner_mod, inserted = await _run_and_collect(monkeypatch, preflight=failing)
    ctrl_q: asyncio.Queue = asyncio.Queue()
    with patch("local_browser_agent.runner.build_browser_session") as launch:
        await runner_mod.run_agent("t", queue=asyncio.Queue(), control_queue=ctrl_q)
        launch.assert_not_called()
    events = [ctrl_q.get_nowait() for _ in range(ctrl_q.qsize())]
    assert any(isinstance(e, ErrorEvent) and "ollama serve" in e.message for e in events)
    assert "ollama serve" in inserted["error"]


# --------------------------------------------------------------------------- stop in pre-flight

async def test_stop_cancels_run_in_preflight(monkeypatch, training_dir):
    started = asyncio.Event()

    async def hang(cfg):
        started.set()
        await asyncio.sleep(60)

    runner_mod, inserted = await _run_and_collect(monkeypatch, preflight=hang)
    holder: dict = {}
    ctrl_q: asyncio.Queue = asyncio.Queue()
    with patch("local_browser_agent.runner.build_browser_session") as launch:
        task = asyncio.create_task(runner_mod.run_agent(
            "t", queue=asyncio.Queue(), control_queue=ctrl_q,
            on_agent=lambda a: holder.__setitem__("agent", a) if a else None))
        await asyncio.wait_for(started.wait(), 5)
        agent = holder["agent"]
        assert agent.is_active is False  # still in pre-flight
        runner_mod.stop_agent(agent)
        await asyncio.wait_for(task, 5)
        launch.assert_not_called()
    assert inserted["status"] == "stopped" and inserted["error"] is None


async def test_stop_endpoint_works_during_preflight_and_pause_does_not_400(monkeypatch):
    agent = MagicMock()
    agent.is_active = False
    monkeypatch.setattr(main_mod, "_active_agent", agent)
    stop_agent = MagicMock()
    monkeypatch.setattr(main_mod, "stop_agent", stop_agent)
    async with _client(cookies=_cookies()) as c:
        r = await c.post("/stop")
        assert r.status_code == 200 and r.json()["status"] == "stopped"
        stop_agent.assert_called_once_with(agent)
        r = await c.post("/pause")
        assert r.status_code == 409 and r.json()["status"] == "starting"
    monkeypatch.setattr(main_mod, "_active_agent", None)
    async with _client(cookies=_cookies()) as c:
        assert (await c.post("/stop")).status_code == 400


# --------------------------------------------------------------------------- history

async def test_db_error_column_migration_and_listing(tmp_path, monkeypatch):
    import aiosqlite
    from local_browser_agent.app import db

    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    async with aiosqlite.connect(path) as conn:  # a DB created before the error column existed
        await conn.execute(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, "
            "task TEXT NOT NULL, status TEXT NOT NULL, summary TEXT, started_at TEXT NOT NULL, "
            "completed_at TEXT)")
        await conn.execute("INSERT INTO runs (run_id, task, status, started_at) VALUES ('o','t','error','2026-01-01T00:00:00+00:00')")
        await conn.commit()
    await db.init_db()
    await db.insert_run(run_id="n", task="t2", status="error", summary=None,
                        started_at="2026-02-01T00:00:00+00:00", completed_at="2026-02-01T00:00:01+00:00",
                        error="Ollama is not running")
    rows = await db.list_runs()
    assert rows[0]["error"] == "Ollama is not running"
    assert rows[1]["error"] is None


def test_history_fragment_shows_reason_and_readable_time():
    from fastapi.templating import Jinja2Templates

    t = Jinja2Templates(directory=str(REPO / "local_browser_agent/app/templates"))
    t.env.filters["humantime"] = main_mod._humantime
    html = t.env.get_template("runs_fragment.html").render(runs=[{
        "task": "do it", "status": "error", "started_at": "2026-03-05T14:07:09.123456+00:00",
        "error": "No Anthropic API key is set.",
    }])
    assert "Reason: No Anthropic API key is set." in html
    assert "T14:07:09" not in html.split("</time>")[0].split(">")[-1]
    assert "2026" in html.split("<time")[1].split("</time>")[0]


def test_humantime_formats():
    assert main_mod._humantime("2026-03-05T14:07:09+00:00").startswith("Mar ")
    assert "T" not in main_mod._humantime("2026-03-05T14:07:09+00:00")
    assert main_mod._humantime("not a date") == "not a date"
    assert main_mod._humantime(None) == ""


async def test_run_agent_records_error_reason(monkeypatch, training_dir):
    from local_browser_agent.app.runner import PreFlightError

    async def failing(cfg):
        raise PreFlightError("No OpenAI API key is set. Open Settings")

    runner_mod, inserted = await _run_and_collect(monkeypatch, preflight=failing)
    await runner_mod.run_agent("t", queue=asyncio.Queue(), control_queue=asyncio.Queue())
    assert inserted["status"] == "error"
    assert inserted["error"] == "No OpenAI API key is set. Open Settings"


# --------------------------------------------------------------------------- settings

async def test_saving_without_prompts_keeps_saved_prompts(tmp_path, monkeypatch, monkeypatch_env):
    monkeypatch.setattr("local_browser_agent.app.settings.get_settings_path", lambda: tmp_path / "settings.json")
    import local_browser_agent.app.config as cfg_mod

    saved = [{"id": "p1", "name": "P", "content": "be brief"}]
    original = list(cfg_mod.config.prompts)
    try:
        async with _client() as c:
            r = await c.post("/api/settings", data={"provider": "ollama", "prompts_json": json.dumps(saved)})
            assert r.status_code == 200
            r = await c.post("/api/settings", data={"provider": "ollama"})
            assert r.status_code == 200
            assert (await c.get("/api/settings")).json()["prompts"] == saved
        assert json.loads((tmp_path / "settings.json").read_text())["prompts"] == saved
        assert cfg_mod.config.prompts == saved
    finally:
        cfg_mod.config.prompts = original


# --------------------------------------------------------------------------- entry point

def test_help_does_not_start_server(monkeypatch, capsys):
    import local_browser_agent.app.__main__ as entry

    run = MagicMock()
    monkeypatch.setattr(entry.uvicorn, "run", run)
    with pytest.raises(SystemExit) as ei:
        entry.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--host", "--port", "--no-open", "--smoke"):
        assert flag in out
    run.assert_not_called()


def test_host_port_no_open_passed_through(monkeypatch):
    import local_browser_agent.app.__main__ as entry

    run = MagicMock()
    opener = MagicMock()
    monkeypatch.setattr(entry.uvicorn, "run", run)
    monkeypatch.setattr(entry, "schedule_browser_open", opener)
    monkeypatch.setattr(entry, "chrome_is_installed", lambda: True)
    entry.main(["--port", "9123", "--no-open"])
    assert run.call_args.kwargs["port"] == 9123 and run.call_args.kwargs["host"] == "127.0.0.1"
    opener.assert_not_called()
    entry.main(["--port", "9123"])
    assert opener.call_args.kwargs["url"] == "http://127.0.0.1:9123"


def test_non_loopback_host_rejected(monkeypatch):
    import local_browser_agent.app.__main__ as entry

    monkeypatch.setattr(entry.uvicorn, "run", MagicMock())
    with pytest.raises(SystemExit) as ei:
        entry.main(["--host", "0.0.0.0"])
    assert ei.value.code == 2


def test_smoke_passes_in_dev_tree_without_server(monkeypatch, capsys):
    import local_browser_agent.app.__main__ as entry

    run = MagicMock()
    monkeypatch.setattr(entry.uvicorn, "run", run)
    assert entry.main(["--smoke"]) == 0
    assert "smoke: OK" in capsys.readouterr().out
    run.assert_not_called()


def test_smoke_reports_missing_files(monkeypatch, tmp_path, capsys):
    import local_browser_agent.app.__main__ as entry
    import local_browser_agent.app.main as m

    monkeypatch.setattr(m, "_resource_path", lambda rel: str(tmp_path / rel))
    problems = entry.smoke_check()
    assert any("missing template" in p for p in problems)
    assert any("missing static file" in p for p in problems)
    monkeypatch.setattr(entry, "smoke_check", lambda: problems)
    assert entry.main(["--smoke"]) == 1


# --------------------------------------------------------------------------- frozen build

@pytest.mark.parametrize("spec", ["local-browser-agent.spec", "local-browser-agent-windows.spec"])
def test_specs_bundle_browser_use_data_and_valid_hidden_imports(spec):
    text = (REPO / spec).read_text()
    assert 'collect_data_files("browser_use")' in text
    assert "browser_use.controller.service" not in text
    import importlib.util

    for line in text.splitlines():
        line = line.strip().strip(",").strip('"')
        if line.startswith("browser_use."):
            assert importlib.util.find_spec(line) is not None, f"hidden import {line} does not exist"


def test_release_workflow_runs_smoke_for_both_binaries():
    text = (REPO / ".github/workflows/release.yml").read_text()
    assert text.count("--smoke") >= 2
    mac = text.split("build-mac:")[1].split("build-windows:")[0]
    win = text.split("build-windows:")[1]
    assert "--smoke" in mac and "--smoke" in win
    assert mac.index("--smoke") > mac.index("pyinstaller")
    assert win.index("--smoke") > win.index("pyinstaller")


def test_browser_use_prompt_files_exist_in_venv():
    import browser_use

    prompts = Path(browser_use.__file__).parent / "agent" / "system_prompts"
    assert (prompts / "system_prompt.md").is_file()


@pytest.mark.parametrize("browser_kw", [{"cdp_url": "http://127.0.0.1:9222"}, {"executable_path": "/x/chrome"}])
async def test_preflight_skips_chrome_check_with_cdp_or_executable(monkeypatch, training_dir, browser_kw):
    from local_browser_agent.app.runner import PreFlightError
    from local_browser_agent.config import AgentConfig, BrowserConfig

    async def sentinel(cfg):
        raise PreFlightError("reached provider check")

    runner_mod, inserted = await _run_and_collect(monkeypatch, preflight=sentinel, chrome=False)
    monkeypatch.setattr(runner_mod, "build_agent_config",
                        lambda *a, **k: AgentConfig(browser=BrowserConfig(**browser_kw)))
    with patch("local_browser_agent.runner.build_browser_session") as launch:
        await runner_mod.run_agent("t", queue=asyncio.Queue(), control_queue=asyncio.Queue())
        launch.assert_not_called()
    assert "reached provider check" in inserted["error"]
