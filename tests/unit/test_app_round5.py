"""Boot-task cross-site guard, LBA_DATA_DIR holding settings.json, release workflow."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import local_browser_agent.app.main as main_mod
import local_browser_agent.app.paths as paths_mod

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(main_mod, "_active_task", None)
    seen: list[str] = []

    async def fake_start(task, prompt_id):
        seen.append(task)
        return True

    monkeypatch.setattr(main_mod, "_start_run", fake_start)
    return seen


def _cookies():
    return {main_mod.DISCLAIMER_COOKIE_NAME: main_mod._disclaimer_serializer().dumps("1")}


@pytest.mark.parametrize("headers", [
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Origin": "http://evil.example"},
    {"Referer": "http://evil.example/page"},
])
async def test_cross_site_load_does_not_start_boot_task(monkeypatch, calls, headers):
    monkeypatch.setattr(main_mod.app.state, "pending_task", "boot", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        r = await c.get("/", headers=headers)
    assert r.status_code == 200
    assert calls == []
    assert "boot" in r.text  # pre-filled
    assert main_mod.app.state.pending_task == "boot"  # still pending for a real load


@pytest.mark.parametrize("headers", [
    {}, {"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": "same-origin"},
    {"Origin": "http://test"},
])
async def test_user_initiated_load_starts_boot_task(monkeypatch, calls, headers):
    monkeypatch.setattr(main_mod.app.state, "pending_task", "boot", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        assert (await c.get("/", headers=headers)).status_code == 200
    assert calls == ["boot"]
    assert main_mod.app.state.pending_task is None


def test_settings_path_follows_lba_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LBA_DATA_DIR", str(tmp_path / "data"))
    assert paths_mod.get_settings_path() == (tmp_path / "data").resolve() / "settings.json"


def test_settings_path_default_uses_config_dir(monkeypatch):
    monkeypatch.delenv("LBA_DATA_DIR", raising=False)
    p = paths_mod.get_settings_path()
    assert p.name == "settings.json" and "user-config" in str(p)


def test_settings_roundtrip_in_data_dir(monkeypatch, tmp_path):
    from local_browser_agent.app.settings import load_settings_json, save_settings_json
    monkeypatch.setenv("LBA_DATA_DIR", str(tmp_path / "d"))
    save_settings_json({"provider": "ollama"})
    assert (tmp_path / "d" / "settings.json").is_file()
    assert load_settings_json() == {"provider": "ollama"}


def test_release_workflow_mac_polls_healthz():
    import yaml
    wf = yaml.safe_load((REPO / ".github/workflows/release.yml").read_text())
    for job in ("build-mac", "build-windows"):
        runs = " ".join(s.get("run", "") for s in wf["jobs"][job]["steps"])
        assert "/healthz" in runs, job


@pytest.mark.parametrize("headers", [{}, {"Sec-Fetch-Site": "none"}])
async def test_chrome_missing_settings_view_keeps_boot_task(monkeypatch, calls, headers):
    monkeypatch.setattr(main_mod, "chrome_is_installed", lambda: False)
    monkeypatch.setattr(main_mod.app.state, "pending_task", "boot", raising=False)
    async with AsyncClient(transport=ASGITransport(app=main_mod.app), base_url="http://test",
                           cookies=_cookies()) as c:
        r = await c.get("/?settings=1", headers=headers)
    assert r.status_code == 200
    assert calls == []
    assert main_mod.app.state.pending_task == "boot"
