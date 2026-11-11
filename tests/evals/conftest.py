from __future__ import annotations

import httpx
import pytest

from local_browser_agent.evals.server import FixtureServer


@pytest.fixture(scope="module")
def server():
    with FixtureServer() as srv:
        yield srv


@pytest.fixture
def client(server):
    server.reset()
    with httpx.Client(base_url=server.base_url, timeout=10) as c:
        yield c
