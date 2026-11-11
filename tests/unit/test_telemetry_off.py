"""browser-use telemetry and cloud sync must be off by default (privacy promise)."""
import importlib
import os


def test_importing_app_disables_browser_use_telemetry(monkeypatch):
    monkeypatch.delenv("ANONYMIZED_TELEMETRY", raising=False)
    monkeypatch.delenv("BROWSER_USE_CLOUD_SYNC", raising=False)
    import local_browser_agent.app as app_pkg
    importlib.reload(app_pkg)
    from browser_use.config import CONFIG
    assert CONFIG.ANONYMIZED_TELEMETRY is False
    assert CONFIG.BROWSER_USE_CLOUD_SYNC is False


def test_inherited_telemetry_flag_is_overridden(monkeypatch):
    monkeypatch.delenv("LBA_ALLOW_TELEMETRY", raising=False)
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "true")
    import local_browser_agent.app as app_pkg
    importlib.reload(app_pkg)
    assert os.environ["ANONYMIZED_TELEMETRY"] == "false"


def test_explicit_opt_in_is_respected(monkeypatch):
    monkeypatch.setenv("LBA_ALLOW_TELEMETRY", "1")
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "true")
    import local_browser_agent.app as app_pkg
    importlib.reload(app_pkg)
    assert os.environ["ANONYMIZED_TELEMETRY"] == "true"
