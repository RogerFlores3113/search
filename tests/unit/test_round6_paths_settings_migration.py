import logging
from pathlib import Path

import platformdirs

from local_browser_agent.app import paths


def test_settings_copied_from_default_config_dir_once(monkeypatch, tmp_path, caplog):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda appname=None, *a, **k: str(cfg / (appname or "")))
    monkeypatch.setenv("LBA_DATA_DIR", str(data))
    legacy = cfg / paths.APP_NAME / "settings.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"a": 1}')
    lg = logging.getLogger(paths.__name__)
    monkeypatch.setattr(lg, "propagate", True)
    monkeypatch.setattr(lg, "disabled", False)
    caplog.set_level(logging.INFO, logger=paths.__name__)
    p = paths.get_settings_path()
    assert p == (data / "settings.json").resolve() or p == data / "settings.json"
    assert p.read_text() == '{"a": 1}' and "Copied existing settings" in caplog.text
    p.write_text('{"a": 2}')  # later edits are never overwritten
    assert paths.get_settings_path().read_text() == '{"a": 2}'


def test_no_copy_when_target_exists_or_no_legacy(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    data = tmp_path / "data"
    monkeypatch.setattr(platformdirs, "user_config_dir", lambda appname=None, *a, **k: str(cfg / (appname or "")))
    monkeypatch.setenv("LBA_DATA_DIR", str(data))
    assert not paths.get_settings_path().exists()
    legacy = Path(cfg / paths.APP_NAME / "settings.json")
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old")
    (data / "settings.json").write_text("new")
    assert paths.get_settings_path().read_text() == "new"
