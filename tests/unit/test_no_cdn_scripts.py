"""Regression guard for Issue #6: the index page must not load JS from a
public CDN.

If `templates/index.html` ever references `https://unpkg.com/...`,
`https://cdn.jsdelivr.net/...`, or any other public CDN, this suite
fails. The three required client deps are vendored into
`agent/static/vendor/` (see that directory's README.md) and served
locally via the FastAPI `/static/` mount.
"""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient


_INDEX = Path("agent/templates/index.html")
_VENDOR = Path("agent/static/vendor")
_REQUIRED_VENDOR_FILES = (
    "htmx.min.js",
    "htmx-ext-sse.js",
    "alpinejs.min.js",
)


def test_index_template_references_no_public_cdn():
    """index.html must NOT contain any `https://` script src that points
    at a known CDN host. Local /static/ paths only.
    """
    html = _INDEX.read_text()
    forbidden = ("unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com")
    for host in forbidden:
        assert host not in html, (
            f"index.html must not load scripts from {host}; vendor them under "
            f"agent/static/vendor/ instead. See agent/static/vendor/README.md."
        )


def test_index_template_references_local_vendor_files():
    """The template must reference each vendored file under /static/vendor/."""
    html = _INDEX.read_text()
    for fname in _REQUIRED_VENDOR_FILES:
        assert f"/static/vendor/{fname}" in html, (
            f"index.html must reference /static/vendor/{fname}; replaced a CDN "
            f"link without updating the local path?"
        )


def test_vendor_files_present_on_disk():
    """Each vendored file must exist and be non-empty so the served-from-
    static contract is honored.
    """
    assert _VENDOR.is_dir(), f"missing vendor directory: {_VENDOR}"
    for fname in _REQUIRED_VENDOR_FILES:
        path = _VENDOR / fname
        assert path.is_file(), f"missing vendored file: {path}"
        assert path.stat().st_size > 0, f"empty vendored file: {path}"


def test_static_mount_serves_vendor_files():
    """The FastAPI /static/ mount actually delivers each vendored file
    with a JS content-type. Catches a regression where the file exists
    on disk but is shadowed by a misconfigured mount.
    """
    from agent.main import app

    client = TestClient(app, raise_server_exceptions=True)
    for fname in _REQUIRED_VENDOR_FILES:
        resp = client.get(f"/static/vendor/{fname}")
        assert resp.status_code == 200, (
            f"/static/vendor/{fname} returned {resp.status_code}; check "
            f"the StaticFiles mount in agent/main.py"
        )
        ctype = resp.headers.get("content-type", "")
        assert "javascript" in ctype, (
            f"/static/vendor/{fname} content-type={ctype!r}; expected javascript"
        )
        assert len(resp.content) > 0, f"served {fname} body is empty"
