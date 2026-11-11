import pytest
from browser_use.agent.views import ActionResult
from pydantic import BaseModel

from local_browser_agent import ActionRequest, BrowserConfig, GuardedTools, SafetyPolicy, is_commerce_label
from local_browser_agent.browser import build_browser_profile


def test_profile_headless_and_domains():
    prof = build_browser_profile(BrowserConfig(headless=True, user_data_dir="/tmp/x"),
                                 SafetyPolicy(blocked_domains=["bad.com"], allowed_domains=["ok.com"]))
    assert prof.headless is True
    assert "bad.com" in prof.prohibited_domains and "paypal.com" in prof.prohibited_domains
    assert list(prof.allowed_domains) == ["ok.com"]
    # browser-use maps window_size to viewport when headless
    size = prof.window_size or prof.viewport
    assert (size.width, size.height) == (1280, 800)


def test_profile_cdp_attach():
    prof = build_browser_profile(BrowserConfig(cdp_url="http://127.0.0.1:9222"), SafetyPolicy())
    assert prof.cdp_url == "http://127.0.0.1:9222"


def test_session_screenshot_size():
    from local_browser_agent.browser import build_browser_session
    s = build_browser_session(BrowserConfig(headless=True), SafetyPolicy())
    assert tuple(s.llm_screenshot_size) == (1024, 640)


@pytest.mark.parametrize("label", [
    "Buy Now", "buy now", "Place your order", "PLACE ORDER", "Checkout", "Proceed to checkout",
    "Pay", "Pay now", "Complete Purchase", "Submit order", "Confirm order", "Purchase", "Subscribe and pay",
])
def test_commerce_positive(label):
    assert is_commerce_label(label)


@pytest.mark.parametrize("label", [
    "Payment history", "Repay", "Paypal settings", "Add to cart", "Search", "Submit", "Subscribe to newsletter",
    "Display", "Prepay info", "", None,
])
def test_commerce_negative(label):
    assert not is_commerce_label(label)


class FakeNode:
    def __init__(self, name):
        self.attributes = {"aria-label": name}
        self.ax_node = None
        self.node_value = ""

    def get_all_children_text(self):
        return ""


class FakeSession:
    def __init__(self, labels):
        self.labels = labels

    async def get_element_by_index(self, i):
        return FakeNode(self.labels[i]) if i in self.labels else None

    async def get_current_page_url(self):
        return "https://shop.example/cart"


class ClickModel(BaseModel):
    click: dict | None = None
    navigate: dict | None = None


@pytest.fixture
def base_act(monkeypatch):
    calls = []

    async def fake_act(self, action, browser_session, *a, **k):
        calls.append(action)
        return ActionResult(extracted_content="ok")

    from browser_use.tools.service import Tools
    monkeypatch.setattr(Tools, "act", fake_act)
    return calls


SESSION = FakeSession({1: "Buy Now", 2: "Read more"})


async def test_blocks_without_approval(base_act):
    log = []
    t = GuardedTools(blocked_log=log)
    r = await t.act(ClickModel(click={"index": 1}), SESSION)
    assert r.error and "Blocked by safety policy" in r.error
    assert not base_act and len(log) == 1 and "Buy Now" in log[0]
    assert t.blocked_actions is log


async def test_allows_when_approved(base_act):
    seen = []

    async def approve(req: ActionRequest):
        seen.append(req)
        return True

    t = GuardedTools(approval=approve)
    r = await t.act(ClickModel(click={"index": 1}), SESSION)
    assert r.extracted_content == "ok" and len(base_act) == 1 and not t.blocked_actions
    assert seen[0].element_label == "Buy Now" and seen[0].url == "https://shop.example/cart"
    assert seen[0].action_name == "click" and seen[0].params == {"index": 1}


async def test_blocks_when_denied_or_raises(base_act):
    async def deny(req):
        return False

    async def boom(req):
        raise RuntimeError("x")

    for cb in (deny, boom):
        t = GuardedTools(approval=cb)
        r = await t.act(ClickModel(click={"index": 1}), SESSION)
        assert r.error and len(t.blocked_actions) == 1
    assert not base_act


async def test_non_commerce_and_other_actions_delegate(base_act):
    t = GuardedTools()
    assert (await t.act(ClickModel(click={"index": 2}), SESSION)).extracted_content == "ok"
    assert (await t.act(ClickModel(navigate={"url": "https://x"}), SESSION)).extracted_content == "ok"
    assert len(base_act) == 2 and not t.blocked_actions
    # unknown element fails closed
    assert (await t.act(ClickModel(click={"index": 99}), SESSION)).error


async def test_gate_off(base_act):
    t = GuardedTools(gate_commerce_clicks=False)
    assert (await t.act(ClickModel(click={"index": 1}), SESSION)).extracted_content == "ok"
