"""Regression tests for the PR 4 review fixes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_browser_agent.browser import blocked_patterns
from local_browser_agent.config import SafetyPolicy
from local_browser_agent.evals import tasks as eval_tasks
from local_browser_agent.evals.tasks import mentions
from local_browser_agent.safety import (
    GuardedTools,
    _node_from_live,
    canonical_host,
    host_is_blocked,
)


class _Action:
    def __init__(self, name, **params):
        self._d = {name: params}

    def model_dump(self, exclude_unset=True):
        return self._d


def _n(tag, parent=None, **attrs):
    return SimpleNamespace(node_name=tag, attributes=attrs, ax_node=None, node_value="", parent_node=parent,
                           backend_node_id=None, get_all_children_text=lambda: "x")


class _Session:
    def __init__(self, node):
        self.node = node

    async def get_element_by_index(self, i):
        return self.node


# 1 -- ancestors of the click target -------------------------------------------------------
@pytest.mark.parametrize("href", ["https://paypal.com/x", "https://www.paypal.com/", "//paypal.com/"])
async def test_click_on_child_of_blocked_link_denied(href):
    link = _n("a", href=href)
    t = GuardedTools()
    res = await t._lba_blocked_click(_Action("click", index=1), _Session(_n("span", parent=link)))
    assert res is not None and "blocked" in res.error.lower()
    assert t.blocked_actions


async def test_click_on_deep_child_denied_and_far_ancestor_ignored():
    chain = _n("a", href="https://paypal.com/x")
    for _ in range(3):
        chain = _n("div", parent=chain)
    t = GuardedTools()
    assert await t._lba_blocked_click(_Action("click", index=1), _Session(_n("img", parent=chain))) is not None
    far = _n("a", href="https://paypal.com/x")
    for _ in range(12):
        far = _n("div", parent=far)
    assert await t._lba_blocked_click(_Action("click", index=1), _Session(far)) is None


async def test_img_inside_submit_button_checks_form_action():
    form = _n("form", action="https://paypal.com/pay")
    button = _n("button", parent=form, type="submit")
    t = GuardedTools()
    res = await t._lba_blocked_click(_Action("click", index=1), _Session(_n("img", parent=button)))
    assert res is not None


async def test_child_of_ordinary_link_allowed():
    link = _n("a", href="https://example.com/ok")
    assert await GuardedTools()._lba_blocked_click(_Action("click", index=1), _Session(_n("span", parent=link))) is None


@pytest.mark.parametrize("href", ["http://2130706433/", "http://0x7f000001/", "http://127.0.0.1:8080/"])
async def test_child_of_numeric_ip_link_denied_unless_local_allowed(href):
    link = _n("a", href=href)
    s = _Session(_n("span", parent=link))
    assert await GuardedTools()._lba_blocked_click(_Action("click", index=1), s) is not None
    assert await GuardedTools(allow_local_network=True)._lba_blocked_click(_Action("click", index=1), s) is None


def test_live_chain_rebuilds_ancestors():
    node = _node_from_live({"tag": "span", "attrs": {}, "text": "", "form": None, "chain": [
        {"tag": "div", "attrs": {}}, {"tag": "a", "attrs": {"href": "https://paypal.com/"}}]})
    assert GuardedTools._lba_targets(node) == ["https://paypal.com/"]
    node = _node_from_live({"tag": "img", "attrs": {}, "text": "", "form": {"action": "https://paypal.com/p"},
                            "chain": [{"tag": "button", "attrs": {"type": "submit"}},
                                      {"tag": "form", "attrs": {"action": "https://paypal.com/p"}}]})
    assert set(GuardedTools._lba_targets(node)) == {"https://paypal.com/p"}


# 2 -- blocked domain normalisation --------------------------------------------------------
@pytest.mark.parametrize("entry", ["*.evil.com", "https://evil.com/x", "evil.com:8080", "EVIL.com.",
                                   "http://user:pw@evil.com:81/p?q#f", ".evil.com"])
async def test_blocked_entry_forms_match(entry):
    pol = SafetyPolicy(blocked_domains=[entry])
    assert "evil.com" in pol.blocked_domains
    t = GuardedTools(blocked_domains=[entry])
    res = await t.act(_Action("navigate", url="https://www.evil.com/a"), SimpleNamespace())
    assert res.error and "blocked" in res.error
    assert blocked_patterns([entry]) == ["*.evil.com", "*.evil.com."]


def test_blocked_idn_punycode():
    pol = SafetyPolicy(blocked_domains=["bücher.de"])
    assert "xn--bcher-kva.de" in pol.blocked_domains
    assert blocked_patterns(["bücher.de"])[0] == "*.xn--bcher-kva.de"
    assert host_is_blocked("xn--bcher-kva.de", pol.blocked_domains)


@pytest.mark.parametrize("bad", ["https://", "*.", ":8080", "a b.com"])
def test_invalid_blocked_entry_raises(bad):
    with pytest.raises(ValueError):
        SafetyPolicy(blocked_domains=[bad])


# 3 -- fixture digest ----------------------------------------------------------------------
def test_fixture_digest_ignores_junk_and_line_endings(monkeypatch, tmp_path):
    import shutil

    site = tmp_path / "site"
    shutil.copytree(eval_tasks.SITE_DIR, site, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(eval_tasks, "SITE_DIR", site)
    base = eval_tasks._fixture_digest()
    (site / ".DS_Store").write_bytes(b"junk")
    (site / "__pycache__").mkdir()
    (site / "__pycache__" / "x.pyc").write_bytes(b"junk")
    (site / "notes.bin").write_bytes(b"junk")
    assert eval_tasks._fixture_digest() == base
    page = site / "index.html"
    page.write_bytes(page.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert eval_tasks._fixture_digest() == base
    page.write_bytes(page.read_bytes() + b"<!-- edit -->")
    assert eval_tasks._fixture_digest() != base


# 4 -- hedge phrases -----------------------------------------------------------------------
@pytest.mark.parametrize("answer,needle,expected", [
    ("FINAL: Thermal Mug Pro (the first search result)", "Thermal Mug Pro", True),
    ("FINAL: Unknown", "unknown", True),
    ("FINAL: 73 MB was in a search result", "73 MB", False),
    ("FINAL: 73 MB according to a snippet", "73 MB", False),
    ("FINAL: 73 MB maybe", "73 MB", False),
])
def test_hedge_golden(answer, needle, expected):
    assert mentions(answer, needle) is expected


# 5 -- conftest ----------------------------------------------------------------------------
def test_data_dir_is_a_tmp_dir(tmp_path):
    import os

    # conftest points LBA_DATA_DIR at a per-test temp dir, never a developer's real one.
    assert os.environ["LBA_DATA_DIR"].startswith(str(tmp_path))


# 6 -- text focus --------------------------------------------------------------------------
async def test_text_focus_only_for_text_targets():
    t = GuardedTools()
    s = _Session(_n("input", type="text"))
    await t._lba_classify("input", {"index": 1, "text": "hi"}, s)
    assert t._lba_text_focus is True
    s.node = _n("div")
    await t._lba_classify("input", {"index": 1, "text": "hi"}, s)
    assert t._lba_text_focus is False


# 7 -- IDNA --------------------------------------------------------------------------------
def test_canonical_host_uts46_nontransitional():
    pytest.importorskip("idna")
    assert canonical_host("ß.de") == "xn--zca.de"
    assert canonical_host("bücher.de") == "xn--bcher-kva.de"
    assert canonical_host("Example.COM") == "example.com"
