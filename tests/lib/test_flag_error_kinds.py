"""`lba run` and `lba eval` agree: a bad flag value is "usage", a bad LBA_* environment value is "config"."""
from __future__ import annotations

import argparse
import json
import os

import pytest

from local_browser_agent import cli as lba_cli
from local_browser_agent.evals import cli as eval_cli

RUN_BAD_FLAGS = [
    ["--provider", "nope"],
    ["--base-url", "notaurl"],
    ["--max-steps", "0"],
    ["--timeout", "0"],
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in list(os.environ):
        if k.startswith("LBA_"):
            monkeypatch.delenv(k)


@pytest.mark.parametrize("flag", RUN_BAD_FLAGS)
def test_run_bad_flag_is_usage(flag, capsys):
    assert lba_cli.main(["run", "t", "--json", "--no-preflight", *flag]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"


def test_run_bad_env_is_config(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    assert lba_cli.main(["run", "t", "--json", "--no-preflight"]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "config"


def test_run_bad_env_and_bad_flag_is_config(monkeypatch, capsys):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    assert lba_cli.main(["run", "t", "--json", "--provider", "nope"]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "config"


@pytest.mark.parametrize("flag", [["--provider", "nope", "--model", "m"],
                                  ["--provider", "ollama", "--model", "m", "--base-url", "notaurl"]])
def test_eval_bad_flag_is_usage(flag, capsys, tmp_path):
    assert eval_cli.main(["--json", "--out", str(tmp_path), *flag]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "usage"


def test_eval_bad_env_is_config(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("LBA_MAX_STEPS", "0")
    assert eval_cli.main(["--json", "--out", str(tmp_path), "--provider", "nope", "--model", "m"]) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "config"


def test_env_only_args_clears_every_config_flag():
    ns = argparse.Namespace(provider="x", model="m", base_url="b", cdp_url="c", max_steps=1, timeout=2.0,
                            allowed_domains=["a"], start_url="s", api_key_env="K", headless=True, task="t")
    clean = lba_cli._env_only_args(ns)
    assert clean.task == "t"
    assert not any([clean.provider, clean.model, clean.base_url, clean.cdp_url, clean.allowed_domains,
                    clean.start_url, clean.api_key_env, clean.headless])
    assert clean.max_steps is None and clean.timeout is None
