import json
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _wf():
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def _names(job):
    return [s.get("name", "") for s in job["steps"]]


def test_codesign_precedes_smoke():
    names = _names(_wf()["jobs"]["build-mac"])
    cs = next(i for i, n in enumerate(names) if "codesign" in n.lower())
    smokes = [i for i, n in enumerate(names) if "smoke" in n.lower()]
    assert smokes and all(cs < i for i in smokes)


def test_version_check_in_build_jobs():
    jobs = _wf()["jobs"]
    for key in ("build-mac", "build-windows"):
        runs = " ".join(s.get("run", "") for s in jobs[key]["steps"])
        assert "tomllib" in runs and "github.ref_name" in runs


def test_single_publish_job_needs_both_builds():
    jobs = _wf()["jobs"]
    publishers = [k for k, j in jobs.items()
                  if any("action-gh-release" in s.get("uses", "") for s in j["steps"])]
    assert publishers == ["publish"]
    assert set(jobs["publish"]["needs"]) == {"build-mac", "build-windows"}
    for key in ("build-mac", "build-windows"):
        assert any("upload-artifact" in s.get("uses", "") for s in jobs[key]["steps"])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes only")
def test_settings_json_mode_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("LBA_DATA_DIR", str(tmp_path))
    from local_browser_agent.app import settings
    settings.save_settings_json({"a": 1})
    p = tmp_path / "settings.json"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert json.loads(p.read_text()) == {"a": 1}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes only")
def test_migrated_settings_mode_0600(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    legacy = cfg / "settings.json"
    legacy.write_text("{}")
    legacy.chmod(0o644)
    monkeypatch.setattr("platformdirs.user_config_dir", lambda *a, **k: str(cfg))
    monkeypatch.setenv("LBA_DATA_DIR", str(tmp_path / "data"))
    from local_browser_agent.app import paths
    p = paths.get_settings_path()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
