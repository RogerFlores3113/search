"""Table-driven tests for the hardened commerce/irreversible-action gate."""
from types import SimpleNamespace

import pytest
from browser_use.agent.views import ActionResult
from pydantic import BaseModel

from local_browser_agent import ActionRequest, GuardedTools
from local_browser_agent.safety import element_risk, is_commerce_label, is_commerce_url, normalize_text

GATED_LABELS = [
    "Kaufen", "Comprar", "Acheter", "Payer", "Buy", "Order now", "Subscribe", "Donate $50", "Send money",
    "Book now", "Make payment", "Finalize order", "Confirm payment", "BuyNow", "Buy-now", "buy_now",
    "B​uy N​ow", "Ｂｕｙ Ｎｏｗ", "Pay now",
    "购买", "支付", "注文する", "결제", "Jetzt kaufen", "Zur Kasse", "Acquista ora", "Finalizar compra",
    "Nu betalen", "Passer la commande", "Confirmar pagamento", "Bestellung abschließen", "お支払い",
    "立即购买", "Buy 2 for $20", "Place Order", "Subscribe now",
]
CLEAN_LABELS = [
    "Add to cart", "View cart", "Book details", "Order history", "Subscribe to newsletter", "Search",
    "Read more", "Payment history", "Repay", "注文履歴", "订单历史", "Donation report", "Booking guide",
    "", None,
]


@pytest.mark.parametrize("label", GATED_LABELS)
def test_labels_gated(label):
    assert is_commerce_label(label), label


@pytest.mark.parametrize("label", CLEAN_LABELS)
def test_labels_clean(label):
    assert not is_commerce_label(label), label


def test_normalize():
    assert normalize_text("Buy​-Now") == normalize_text("BuyNow") == "buy now"
    assert normalize_text("ＢＵＹ") == "buy"


@pytest.mark.parametrize("url", [
    "https://shop.example/checkout", "https://shop.example/checkout/confirm", "https://shop.example/cart/confirm",
    "https://shop.example/payment", "https://shop.example/pay", "https://shop.example/order/place",
    "https://shop.example/place_order", "https://shop.example/subscribe", "https://shop.example/donate",
    "https://shop.example/billing", "https://shop.example/en/Checkout/", "https://checkout.shop.example/x",
    "https://shop.example/placeOrder",
])
def test_url_gated(url):
    assert is_commerce_url(url), url


@pytest.mark.parametrize("url", [
    "https://shop.example/cart", "https://shop.example/", "https://shop.example/orders/history",
    "https://shop.example/account/payment-methods", "https://shop.example/help/payment", "", None,
    "https://shop.example/products/buy-one", "https://checkout.com/",
])
def test_url_clean(url):
    assert not is_commerce_url(url), url


class Node:
    def __init__(self, tag="button", attrs=None, text="", parent=None):
        self.node_name = tag
        self.attributes = attrs or {}
        self.ax_node = None
        self.node_value = ""
        self.parent_node = parent
        self._text = text

    def get_all_children_text(self):
        return self._text


class Session:
    def __init__(self, nodes, url="https://shop.example/cart", url_raises=False, lookup_raises=False):
        self.nodes, self.url, self.url_raises, self.lookup_raises = nodes, url, url_raises, lookup_raises

    async def get_element_by_index(self, i):
        if self.lookup_raises:
            raise RuntimeError("cdp down")
        return self.nodes.get(i)

    async def get_dom_element_at_coordinates(self, x, y):
        return self.nodes.get("xy")

    async def get_current_page_url(self):
        if self.url_raises:
            raise RuntimeError("no page")
        return self.url


class Act(BaseModel):
    click: dict | None = None
    navigate: dict | None = None
    go_to_url: dict | None = None
    send_keys: dict | None = None
    input: dict | None = None
    evaluate: dict | None = None


@pytest.fixture
def base_act(monkeypatch):
    calls = []

    async def fake_act(self, action, browser_session, *a, **k):
        calls.append(action)
        return ActionResult(extracted_content="ok")

    from browser_use.tools.service import Tools
    monkeypatch.setattr(Tools, "act", fake_act)
    return calls


async def run(action, session, approval=None, **kw):
    t = GuardedTools(approval=approval, **kw)
    return t, await t.act(action, session)


def checkout_form():
    return Node("form", {"action": "/checkout/confirm"})


CLICK_GATED = {
    "submit-in-checkout-form": Node("input", {"type": "submit", "value": "Continue"}, parent=checkout_form()),
    "href-continue": Node("a", {"href": "https://shop.example/checkout/confirm"}, "Continue"),
    "formaction": Node("button", {"formaction": "/payment"}, "Next"),
    "icon-only-in-form": Node("button", {"type": "submit"}, "", parent=checkout_form()),
    "confirm-payment-submit": Node("input", {"type": "submit", "value": "Confirm payment"}),
    "aria-label-only": Node("button", {"aria-label": "Acheter"}),
    "name-attr": Node("button", {"name": "place_order"}),
    "id-attr": Node("button", {"id": "btnBuyNow"}),
    "cjk-text": Node("button", {}, "购买"),
    "form-id": Node("button", {"type": "submit"}, "Go", parent=Node("form", {"id": "checkout-form"})),
}
CLICK_CLEAN = {
    "add-to-cart": Node("button", {}, "Add to cart"),
    "view-cart": Node("a", {"href": "/cart"}, "View cart"),
    "book-details": Node("a", {"href": "/books/42"}, "Book details"),
    "order-history": Node("a", {"href": "/orders/history"}, "Order history"),
    "search-submit": Node("button", {"type": "submit"}, "", parent=Node("form", {"action": "/search"})),
    "continue-plain": Node("a", {"href": "/about"}, "Continue"),
}


@pytest.mark.parametrize("key", list(CLICK_GATED))
async def test_click_gated(base_act, key):
    r = await run(Act(click={"index": 1}), Session({1: CLICK_GATED[key]}))
    assert r[1].error and "Blocked by safety policy" in r[1].error and not base_act


@pytest.mark.parametrize("key", list(CLICK_CLEAN))
async def test_click_clean(base_act, key):
    r = await run(Act(click={"index": 1}), Session({1: CLICK_CLEAN[key]}))
    assert r[1].extracted_content == "ok" and len(base_act) == 1


async def test_click_on_checkout_page_gates_controls(base_act):
    s = Session({1: Node("button", {}, "Continue"), 2: Node("button", {})}, url="https://shop.example/checkout")
    assert (await run(Act(click={"index": 1}), s))[1].error
    assert (await run(Act(click={"index": 2}), s))[1].error
    assert not base_act


async def test_click_fail_closed(base_act):
    # unknown index, lookup raising, coordinate click with no node: all gated, denied without approval
    for s, p in [(Session({}), {"index": 5}), (Session({}, lookup_raises=True), {"index": 5}),
                 (Session({}), {"coordinate_x": 1, "coordinate_y": 2})]:
        t, r = await run(Act(click=p), s)
        assert r.error and t.blocked_actions
    assert not base_act


async def test_fail_closed_can_be_approved_and_describes(base_act):
    seen = []

    async def ok(req: ActionRequest):
        seen.append(req)
        return True

    t, r = await run(Act(click={"index": 5}), Session({}), approval=ok)
    assert r.extracted_content == "ok" and seen[0].action_name == "click"
    assert seen[0].reason and seen[0].url == "https://shop.example/cart"


async def test_approval_description_for_click(base_act):
    seen = []

    async def ok(req):
        seen.append(req)
        return True

    await run(Act(click={"index": 1}), Session({1: CLICK_GATED["href-continue"]}), approval=ok)
    req = seen[0]
    assert req.element_label == "Continue" and req.url == "https://shop.example/cart"
    assert "href" in req.reason and req.params == {"index": 1}


async def test_send_keys(base_act):
    co = Session({}, url="https://shop.example/checkout")
    plain = Session({}, url="https://shop.example/search")
    for keys in ("Enter", "Return", "enter", "Control+Enter"):
        assert (await run(Act(send_keys={"keys": keys}), co))[1].error, keys
    assert not base_act
    assert (await run(Act(send_keys={"keys": "Enter"}), plain))[1].extracted_content == "ok"
    assert (await run(Act(send_keys={"keys": "PageDown"}), co))[1].extracted_content == "ok"
    assert (await run(Act(send_keys={"keys": "Enter"}), Session({}, url_raises=True)))[1].error


async def test_input_newline(base_act):
    form_node = Node("input", {"type": "text"}, parent=checkout_form())
    plain_node = Node("input", {"type": "text"}, parent=Node("form", {"action": "/search"}))
    s = Session({1: form_node, 2: plain_node})
    assert (await run(Act(input={"index": 1, "text": "4242\n"}), s))[1].error
    assert (await run(Act(input={"index": 1, "text": "4242"}), s))[1].extracted_content == "ok"
    assert (await run(Act(input={"index": 2, "text": "shoes\n"}), s))[1].extracted_content == "ok"
    co = Session({2: plain_node}, url="https://x.example/checkout")
    assert (await run(Act(input={"index": 2, "text": "shoes\n"}), co))[1].error
    assert (await run(Act(input={"index": 9, "text": "x\n"}), s))[1].error  # unknown target, fail closed


async def test_evaluate_gated_by_default(base_act):
    seen = []

    async def deny(req):
        seen.append(req)
        return False

    t, r = await run(Act(evaluate={"code": "document.forms[0].submit()"}), Session({}), approval=deny)
    assert r.error and "submit()" in seen[0].element_label and not base_act
    t, r = await run(Act(evaluate={"code": "1+1"}), Session({}))
    assert r.error  # no approval callback: deny
    t, r = await run(Act(evaluate={"code": "1+1"}), Session({}), allow_evaluate=True)
    assert r.extracted_content == "ok"


async def test_navigate(base_act):
    s = Session({})
    for url in ("https://shop.example/checkout/confirm", "https://shop.example/pay", "https://shop.example/order/place"):
        assert (await run(Act(navigate={"url": url}), s))[1].error, url
        assert (await run(Act(go_to_url={"url": url}), s))[1].error, url
    assert not base_act
    assert (await run(Act(navigate={"url": "https://shop.example/cart"}), s))[1].extracted_content == "ok"


async def test_navigate_approval_request(base_act):
    seen = []

    async def ok(req):
        seen.append(req)
        return True

    await run(Act(navigate={"url": "https://shop.example/checkout"}), Session({}), approval=ok)
    assert seen[0].url == "https://shop.example/checkout" and seen[0].action_name == "navigate"


async def test_gate_off_disables_everything(base_act):
    t = GuardedTools(gate_commerce_clicks=False)
    s = Session({})
    for a in (Act(click={"index": 9}), Act(evaluate={"code": "x"}), Act(navigate={"url": "https://s.example/checkout"})):
        assert (await t.act(a, s)).extracted_content == "ok"


def test_bare_nodes_tolerated():
    assert element_risk(SimpleNamespace(), None, None) is None


def test_allow_evaluate_flows_from_config():
    from local_browser_agent.config import AgentConfig, SafetyPolicy

    assert SafetyPolicy().allow_evaluate is False
    cfg = AgentConfig.from_env(env={"LBA_ALLOW_EVALUATE": "true"})
    assert cfg.safety.allow_evaluate is True
