"""Round-2 gate hardening: URL shapes, label false positives, i18n, keys, approval, navigation."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from local_browser_agent.safety import (
    is_commerce_label,
    is_commerce_url,
    navigation_denial,
)
from tests.lib.test_safety_gate import Act, Node, Session, base_act, run  # noqa: F401


@pytest.mark.parametrize("url", [
    "https://shop.example/12345/checkouts/abc123def", "https://www.amazon.com/gp/buy/spc/handlers/display.html?x=1",
    "https://www.amazon.com/gp/buy/", "https://shop.example/checkout.php", "https://shop.example/Checkout.aspx",
    "https://shop.example/order/pay", "https://shop.example/basket/payment", "https://shop.example/cart/payment",
    "https://shop.example/cart?step=payment", "https://shop.example/x?step=review_order",
    "https://shop.example/x?checkout_step=2",
])
def test_more_platform_urls_gated(url):
    assert is_commerce_url(url), url


@pytest.mark.parametrize("url", [
    "https://en.wikipedia.org/wiki/Checkout", "https://github.com/org/checkout", "https://www.reddit.com/r/checkout",
    "https://stackoverflow.com/questions/1/checkout", "https://medium.com/@a/checkout-flow",
    "https://shop.example/cart?step=1", "https://shop.example/blog/checkout-tips",
])
def test_content_urls_clean(url):
    assert not is_commerce_url(url), url


def test_content_host_does_not_exempt_form_actions():
    assert is_commerce_url("https://github.com/checkout", broad=True)


@pytest.mark.parametrize("label", [
    "Pay attention", "How to pay", "Pay per click", "Purchase history", "Buy now, pay later explained",
    "Payment methods we accept", "Checkout guide FAQ", "Learn about purchase protection",
])
def test_label_false_positives(label):
    assert not is_commerce_label(label), label


@pytest.mark.parametrize("label", [
    "Pay", "Pay now", "Pay $20.00", "Pay with card", "Pay & continue", "Purchase", "Checkout", "Proceed to checkout",
    "Secure checkout", "Place order guide", "Complete purchase", "Buy now",
    "Рay now", "Pаy", "Buy nοw",  # Cyrillic / Greek look-alikes
    "Купить", "Оплатить", "Оформить заказ", "Купити", "Оформити замовлення", "شراء", "ادفع", "إتمام الطلب",
    "खरीदें", "भुगतान करें", "Satın al", "Öde", "Kup teraz", "Zapłać", "Köp", "Betala", "Beli", "Bayar",
    "Mua ngay", "Thanh toán", "ซื้อเลย", "ชำระเงิน",
])
def test_label_gated_i18n_and_context(label):
    assert is_commerce_label(label), label


@pytest.mark.parametrize("label", ["Купить историю", "ประวัติการซื้อ", "Köp guide"])
def test_i18n_clean(label):
    assert not is_commerce_label(label), label


async def test_denied_message_does_not_demand_failure(base_act):
    t, r = await run(Act(navigate={"url": "https://shop.example/checkout"}), Session({}))
    assert "success=False" not in r.error and "approval" in r.error and "continue" in r.error.lower()


@pytest.mark.parametrize("ret", ["no", "false", 1, {"approved": False}, object(), None, SimpleNamespace(a=1)])
async def test_truthy_non_true_not_approved(base_act, ret):
    async def cb(req):
        return ret

    t, r = await run(Act(navigate={"url": "https://shop.example/checkout"}), Session({}), approval=cb)
    assert r.error and not base_act


@pytest.mark.parametrize("ret", [True, {"approved": True}])
async def test_explicit_approval_forms(base_act, ret):
    async def cb(req):
        return ret

    t, r = await run(Act(navigate={"url": "https://shop.example/checkout"}), Session({}), approval=cb)
    assert r.extracted_content == "ok"


async def test_approval_timeout(base_act):
    async def slow(req):
        await asyncio.sleep(5)
        return True

    t, r = await run(Act(navigate={"url": "https://shop.example/checkout"}), Session({}), approval=slow,
                     approval_timeout_s=0.05)
    assert r.error and "timed out" in r.error and not base_act and t.blocked_actions


# ---- keys / input ---------------------------------------------------------------------------
@pytest.mark.parametrize("keys", ["\n", "\r", "\\n", "Control+Enter", "Meta+Return", "Enter"])
async def test_enter_variants_gated_on_checkout(base_act, keys):
    s = Session({}, url="https://shop.example/checkout")
    assert (await run(Act(send_keys={"keys": keys}), s))[1].error


@pytest.mark.parametrize("text", ["123\n ", "123\r\n", "123\n\t \n", "123\r"])
async def test_input_trailing_newline_whitespace(base_act, text):
    form_node = Node("input", {"type": "text"}, parent=Node("form", {"action": "/checkout/confirm"}))
    assert (await run(Act(input={"index": 1, "text": text}), Session({1: form_node})))[1].error


class FocusSession(Session):
    def __init__(self, focused, **kw):
        super().__init__({}, **kw)
        self.focused = focused

    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        focused = self.focused

        class Runtime:
            @staticmethod
            async def evaluate(params, session_id=None):
                return {"result": {"objectId": "o1"}}

            @staticmethod
            async def callFunctionOn(params, session_id=None):
                return {"result": {"value": json.dumps(focused)}}

        send = SimpleNamespace(Runtime=Runtime)
        return SimpleNamespace(session_id="s", cdp_client=SimpleNamespace(send=send))


async def test_space_on_focused_buy_button(base_act):
    buy = {"tag": "button", "attrs": {}, "text": "Place order", "form": None}
    assert (await run(Act(send_keys={"keys": "Space"}), FocusSession(buy)))[1].error
    assert (await run(Act(send_keys={"keys": " "}), FocusSession(buy)))[1].error
    ok = {"tag": "button", "attrs": {}, "text": "Next slide", "form": None}
    assert (await run(Act(send_keys={"keys": "Space"}), FocusSession(ok)))[1].extracted_content == "ok"
    # unknown focus: only gated on a checkout page
    assert (await run(Act(send_keys={"keys": "Space"}), Session({})))[1].extracted_content == "ok"
    assert (await run(Act(send_keys={"keys": "Space"}), Session({}, url="https://s.example/checkout")))[1].error


# ---- click: url unreadable / live read ----------------------------------------------------------
async def test_click_url_unreadable_only_blocks_ambiguous(base_act):
    labelled = Node("button", {}, "Next page")
    submit = Node("button", {"type": "submit"}, "")
    s = Session({1: labelled, 2: submit}, url_raises=True)
    assert (await run(Act(click={"index": 1}), s))[1].extracted_content == "ok"
    assert (await run(Act(click={"index": 2}), s))[1].error


class LiveSession(Session):
    def __init__(self, nodes, live, fail=False, **kw):
        super().__init__(nodes, **kw)
        self.live, self.fail = live, fail

    async def cdp_client_for_node(self, node):
        if self.fail:
            raise RuntimeError("target closed")
        live = self.live

        class DOM:
            @staticmethod
            async def resolveNode(params, session_id=None):
                return {"object": {"objectId": "o"}}

        class Runtime:
            @staticmethod
            async def callFunctionOn(params, session_id=None):
                return {"result": {"value": json.dumps(live)}}

        send = SimpleNamespace(DOM=DOM, Runtime=Runtime)
        return SimpleNamespace(session_id="s", cdp_client=SimpleNamespace(send=send))


def _cached(text="Learn more"):
    n = Node("button", {}, text)
    n.backend_node_id = 7
    return n


async def test_live_label_swap_is_caught(base_act):
    swapped = {"tag": "button", "attrs": {}, "text": "Place order", "form": None}
    t, r = await run(Act(click={"index": 1}), LiveSession({1: _cached()}, swapped))
    assert r.error and not base_act
    same = {"tag": "button", "attrs": {}, "text": "Learn more", "form": None}
    assert (await run(Act(click={"index": 1}), LiveSession({1: _cached()}, same)))[1].extracted_content == "ok"


async def test_live_swap_to_buy_handler_attr(base_act):
    swapped = {"tag": "a", "attrs": {"href": "https://shop.example/checkouts/abc"}, "text": "Learn more", "form": None}
    assert (await run(Act(click={"index": 1}), LiveSession({1: _cached()}, swapped)))[1].error


async def test_live_read_failure_fails_closed_only_if_ambiguous(base_act):
    amb = Node("button", {"type": "submit"}, "")
    amb.backend_node_id = 7
    assert (await run(Act(click={"index": 1}), LiveSession({1: amb}, {}, fail=True)))[1].error
    assert (await run(Act(click={"index": 1}), LiveSession({1: _cached()}, {}, fail=True)))[1].extracted_content == "ok"


# ---- navigation guard ------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "chrome://settings", "chrome-extension://abc/page.html", "devtools://devtools/bundled/x.html",
    "view-source:https://example.com", "data:text/html,<script>1</script>", "file:///etc/passwd",
    "javascript:alert(1)", "about:config", "JaVaScRiPt:alert(1)", "java\tscript:alert(1)", "ftp://example.com/x",
])
def test_bad_schemes_denied(url):
    assert navigation_denial(url, allow_local_network=True), url


@pytest.mark.parametrize("url", [
    "http://localhost:8000/", "http://foo.localhost/", "http://127.0.0.1/", "http://127.5.6.7:80", "http://[::1]/",
    "http://10.1.2.3/", "http://172.16.0.1/", "http://172.31.255.255", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[fc00::1]/", "http://[fd12::1]/", "http://0.0.0.0/",
    "http://[::ffff:127.0.0.1]/", "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://127.1/",
    "localhost:3000", "//localhost/x", "http://metadata.google.internal/", "http://LOCALHOST./",
])
def test_local_denied_unless_allowed(url):
    assert navigation_denial(url), url
    assert navigation_denial(url, allow_local_network=True) is None, url


@pytest.mark.parametrize("url", [
    "https://example.com/", "http://8.8.8.8/", "about:blank", "https://172.32.0.1/", "https://[2606:4700::1111]/",
    "example.com/path", "https://notlocalhost.com/", "https://localhost.example.com/",
])
def test_public_allowed(url):
    assert navigation_denial(url) is None, url


async def test_guarded_tools_navigation_guard(base_act):
    s = Session({})
    for url in ("chrome://settings", "http://169.254.169.254/", "file:///etc/passwd", "http://localhost/"):
        for act in (Act(navigate={"url": url}), Act(go_to_url={"url": url}),
                    Act(navigate={"url": url, "new_tab": True})):
            t, r = await run(act, s)
            assert r.error and t.blocked_actions, url
    assert not base_act
    t, r = await run(Act(navigate={"url": "http://localhost:8000/"}), s, allow_local_network=True)
    assert r.extracted_content == "ok"
    t, r = await run(Act(navigate={"url": "chrome://settings"}), s, allow_local_network=True)
    assert r.error
    # independent of the commerce gate switch
    t, r = await run(Act(navigate={"url": "file:///etc/passwd"}), s, gate_commerce_clicks=False)
    assert r.error
