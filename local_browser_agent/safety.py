"""Safety policy primitives: default blocked domains, guardrail prompt, commerce click gate."""
from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools

logger = logging.getLogger("local_browser_agent")

SAFETY_DEFAULTS: frozenset[str] = frozenset({
    # Banking
    "chase.com", "wellsfargo.com", "bankofamerica.com", "citi.com", "usbank.com",
    # Payment
    "paypal.com", "venmo.com", "stripe.com", "square.com", "braintree.com",
    # Government
    "irs.gov", "ssa.gov", "healthcare.gov", "va.gov", "dhs.gov",
    "state.gov", "fbi.gov", "whitehouse.gov",
    # Medical
    "labcorp.com", "questdiagnostics.com", "epic.com", "mychart.com",
    # Credential / Identity
    "lastpass.com", "1password.com", "bitwarden.com", "dashlane.com",
    "nordpass.com", "okta.com", "auth0.com",
})

GUARDRAIL_PROMPT = (
    "\nSAFETY GUARDRAILS — override everything else:\n"
    "1. NEVER click Buy Now, Purchase, Checkout, Pay, Place Order, Confirm Order, "
    "Complete Purchase, or any equivalent commerce CTA.\n"
    "2. NEVER submit forms containing credit card numbers, CVVs, bank account details, "
    "Social Security Numbers, or passwords on any site the user did not explicitly name.\n"
    "3. NEVER submit credentials (username/password) on any site not explicitly named.\n"
    "4. If you encounter such an element, set is_done=True, success=False, explain what you found.\n"
)

DEFAULT_COMMERCE_PATTERNS: tuple[str, ...] = (
    "buy now",
    "buy it now",
    "purchase",
    "checkout",
    "check out",
    "pay",
    "pay now",
    "place order",
    "place your order",
    "confirm order",
    "confirm purchase",
    "complete purchase",
    "complete order",
    "submit order",
    "subscribe and pay",
    "start subscription",
)

# Click-type tool actions whose target is an element index (or coordinates).
CLICK_ACTIONS = frozenset({"click", "click_element_by_index", "click_element"})
INPUT_ACTIONS = frozenset({"input", "input_text", "input_text_by_index"})
KEY_ACTIONS = frozenset({"send_keys"})
EVAL_ACTIONS = frozenset({"evaluate", "execute_js", "execute_javascript"})
NAVIGATE_ACTIONS = frozenset({"navigate", "go_to_url"})

# Phrases matched as whole words (Latin scripts), after normalisation.
MULTILINGUAL_COMMERCE_PATTERNS: tuple[str, ...] = (
    # en
    "order now", "buy again", "make payment", "make a payment", "finalize order", "finalise order",
    "confirm payment", "send money", "book now", "reserve now", "complete payment", "proceed to payment",
    "proceed to pay", "pay securely", "pay with", "donate now", "subscribe now",
    "confirm and pay", "confirm booking", "complete booking", "confirm your order", "complete checkout",
    # de
    "kaufen", "jetzt kaufen", "zahlen", "bezahlen", "jetzt bezahlen", "zur kasse", "kasse",
    "bestellen", "jetzt bestellen", "kostenpflichtig bestellen", "zahlungspflichtig bestellen",
    "bestellung abschliessen", "bestellung abschließen", "zahlung bestaetigen", "zahlung bestätigen",
    "geld senden", "jetzt buchen", "jetzt spenden", "abonnieren", "kauf abschliessen",
    # es
    "comprar", "comprar ahora", "pagar", "pagar ahora", "realizar pedido", "finalizar compra",
    "finalizar pedido", "confirmar pedido", "confirmar pago", "confirmar compra", "tramitar pedido",
    "enviar dinero", "reservar ahora", "suscribirse", "suscríbete", "ir a pagar", "donar ahora",
    # fr
    "acheter", "acheter maintenant", "payer", "payer maintenant", "commander", "passer la commande",
    "valider la commande", "finaliser la commande", "confirmer le paiement", "confirmer la commande",
    "envoyer de l'argent", "faire un don", "réserver maintenant", "s'abonner",
    "passer à la caisse", "procéder au paiement",
    # it
    "acquista", "acquista ora", "compra ora", "paga", "paga ora", "ordina", "ordina ora",
    "conferma ordine", "conferma l'ordine", "conferma il pagamento", "completa l'ordine",
    "completa ordine", "invia denaro", "prenota ora", "abbonati", "vai alla cassa",
    # pt
    "comprar agora", "confirmar pagamento", "fazer pedido", "enviar dinheiro", "reservar agora",
    "assinar agora", "doar agora",
    # nl
    "kopen", "nu kopen", "betalen", "nu betalen", "bestelling plaatsen", "bestelling afronden",
    "afrekenen", "bevestig betaling", "betaling bevestigen", "geld versturen", "nu boeken",
    "nu bestellen", "abonneren", "nu doneren",
)

# Whole-label matches (label must equal one of these once digits/currency/punctuation are
# removed). Keeps "Subscribe to newsletter", "Book details", "Order history" ungated.
EXACT_COMMERCE_LABELS: frozenset[str] = frozenset({
    "buy", "order", "book", "subscribe", "donate", "pay", "purchase", "reserve", "place order",
    "spenden", "buchen", "donar", "reservar", "suscribirse", "réserver", "reserver",
    "prenota", "dona", "assinar", "doar", "boeken", "doneren",
})

# Start-of-label matches ("Buy 2 for $20", "Donate $50").
_STARTS_WITH = ("buy ", "donate ", "kaufen ", "comprar ", "acheter ", "acquista ")

# CJK keywords are matched as substrings (no word boundaries in those scripts).
CJK_COMMERCE_KEYWORDS: tuple[str, ...] = (
    # ja
    "購入", "注文", "支払", "決済", "申し込", "申込", "寄付", "送金", "予約", "レジに進", "お会計",
    # zh
    "购买", "購買", "支付", "付款", "结算", "結算", "下单", "下單", "提交订单", "提交訂單",
    "订阅", "訂閱", "捐款", "捐赠", "捐贈", "转账", "轉賬", "汇款", "匯款", "预订", "預訂", "预定",
    # ko
    "구매", "결제", "주문", "구독", "후원", "기부", "송금", "예약",
)
_CJK_NEGATIVE = (
    "履歴", "履歷", "历史", "歷史", "歴史", "내역", "기록", "詳細", "详情", "詳情", "상세", "一覧",
    "ガイド", "指南", "帮助", "幫助", "도움말", "キャンセル", "取消", "취소",
)

# --- Transactional URL signals ---------------------------------------------------------
# Broad token matching: only used for form actions / formaction attributes, where a stray
# match is cheap. Page and link URLs use the stricter path-shape rules below so that
# /wiki/Donation or /help/payment-methods never gate a whole page.
_URL_TOKENS = frozenset({
    "checkout", "payment", "payments", "pay", "placeorder", "subscribe", "subscription", "donate",
    "donation", "donations", "billing", "purchase", "buynow", "paynow", "confirmpayment",
    "kasse", "caisse", "cassa", "zahlung", "paiement", "pagamento", "betaling",
})
_URL_BIGRAMS = frozenset({
    ("cart", "confirm"), ("cart", "checkout"), ("cart", "pay"), ("order", "place"), ("order", "confirm"),
    ("order", "submit"), ("order", "complete"), ("order", "review"), ("place", "order"),
    ("confirm", "order"), ("confirm", "payment"), ("confirm", "purchase"), ("complete", "purchase"),
    ("complete", "order"), ("buy", "now"), ("send", "money"), ("money", "transfer"),
})
_URL_NEGATIVE_TOKENS = frozenset({
    "history", "faq", "help", "policy", "policies", "terms", "methods", "settings", "docs", "blog",
})
_URL_HOST_LABELS = frozenset({"checkout", "pay", "payments", "billing", "donate"})
# A path segment (separators removed) that is transactional wherever it appears.
_URL_CHECKOUT_SEGMENTS = frozenset({
    "checkout", "placeorder", "buynow", "paynow", "confirmpayment",
    "kasse", "caisse", "cassa",
})
# Segments that are transactional only as the first path segment (after an optional locale),
# either alone, followed by an id, or followed by an action word.
_URL_ROOT_SEGMENTS = frozenset({
    "pay", "payment", "payments", "billing", "subscribe", "donate", "purchase",
    "zahlung", "paiement", "pagamento", "betaling",
})
_URL_ROOT_ACTIONS = frozenset({
    "confirm", "submit", "process", "checkout", "pay", "complete", "review", "place",
})
_LOCALE_RE = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$")
_ID_RE = re.compile(r"^[\w-]*\d[\w-]*$")

# --- Domain helpers ------------------------------------------------------------------
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_HOST_RE = re.compile(r"^[^\W_](?:[\w-]*[^\W_])?(?:\.[^\W_](?:[\w-]*[^\W_])?)*$")


def normalize_allowed_domain(raw: Any) -> str:
    """Normalise an allow-list entry to a plain hostname or ``"*." + hostname``.

    A scheme, port, path, query or fragment is stripped. Bare ``*``, TLD-only wildcards
    (``*.com``), mid-label globs (``paypal.*``) and anything else that is not a hostname
    are rejected, because browser-use treats ``*`` patterns as globs and ignores its
    blocklist whenever an allow-list is set.

    Raises:
        ValueError: when the entry is not a plain hostname or ``*.hostname``.
    """
    d = str(raw).strip().lower()
    d = _SCHEME_RE.sub("", d)
    for sep in "/?#":
        d = d.split(sep, 1)[0]
    if "@" in d:
        raise ValueError(f"allowed domain {raw!r} must not contain credentials")
    d = re.sub(r":\d+$", "", d).rstrip(".")
    wildcard = d.startswith("*.")
    host = d[2:] if wildcard else d
    if not host or "*" in host or not _HOST_RE.match(host):
        raise ValueError(
            f"allowed domain {raw!r} must be a hostname like 'example.com' or '*.example.com'")
    if wildcard and "." not in host:
        raise ValueError(f"allowed domain {raw!r} is a top-level wildcard; name a specific site")
    return ("*." + host) if wildcard else host


def host_is_blocked(host: str | None, blocked: Iterable[str]) -> bool:
    """True when ``host`` is, or is a subdomain of, a blocked domain."""
    h = (host or "").strip().lower().rstrip(".")
    return bool(h) and any(h == b or h.endswith("." + b) for b in (x.strip().lower().rstrip(".") for x in blocked) if b)


def allowed_matches_blocked(entry: str, blocked: Iterable[str]) -> bool:
    """True when a normalised allow-list ``entry`` would let browser-use reach a blocked domain.

    browser-use matches ``*.d`` against ``d`` and its subdomains, and a plain ``d`` against
    ``d`` and ``www.d``. The entry is unsafe when it covers a blocked domain or sits under one.
    """
    wildcard = entry.startswith("*.")
    base = entry[2:] if wildcard else entry
    for b in blocked:
        b = b.strip().lower().rstrip(".")
        if not b:
            continue
        if base == b or base.endswith("." + b):
            return True
        if wildcard and b.endswith("." + base):
            return True
        if not wildcard and b == "www." + base:
            return True
    return False


_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060-\u2064\ufeff\u00ad\u180e]")
_SEPARATORS_RE = re.compile(r"[\-_./\\|:;,+*~·•–—]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SUBMIT_TYPES = frozenset({"submit", "image", "button"})


@dataclass
class ActionRequest:
    """Describes a gated action for an approval callback.

    ``element_label`` is the click target's label (or the key sequence / script snippet for
    non-click actions); ``url`` is the current page (or the destination for navigation);
    ``reason`` says why the action was gated.
    """

    action_name: str
    params: dict[str, Any] = field(default_factory=dict)
    element_label: str | None = None
    url: str | None = None
    reason: str | None = None


ApprovalCallback = Callable[[ActionRequest], Awaitable[bool]]


def normalize_text(text: str | None) -> str:
    """NFKC, drop zero-width/control chars, split camelCase, fold separators, casefold."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = _ZERO_WIDTH_RE.sub("", t)
    t = "".join(" " if unicodedata.category(c) in ("Cc", "Zs", "Zl", "Zp") else c
                for c in t if unicodedata.category(c) != "Cf")
    t = _CAMEL_RE.sub(" ", t)
    t = _SEPARATORS_RE.sub(" ", t)
    return " ".join(t.casefold().split())


def _phrase_in(phrase: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _core(text: str) -> str:
    """Normalised label with digits, currency symbols and punctuation removed."""
    t = "".join(c for c in text if unicodedata.category(c)[0] in ("L", "M", "Z") or c == "'")
    return " ".join(t.split())


def is_commerce_label(label: str | None, patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> bool:
    """True when ``label`` looks like a purchase/payment/subscribe/donate call to action.

    The label is normalised (NFKC, zero-width removal, camelCase and separator folding,
    casefold) so "BuyNow", "Buy-now" and fullwidth/zero-width variants match. Latin phrases
    match as whole words ("payment history" does not match "pay"); CJK keywords match as
    substrings; bare generic verbs ("Buy", "Subscribe", "Donate") match only as the whole
    label so "Subscribe to newsletter", "Book details" and "Order history" pass.
    """
    if not label:
        return False
    text = normalize_text(label)
    if not text:
        return False
    for p in (*patterns, *MULTILINGUAL_COMMERCE_PATTERNS):
        p = normalize_text(p)
        if p and _phrase_in(p, text):
            return True
    if _core(text) in EXACT_COMMERCE_LABELS:
        return True
    if any(text.startswith(s) for s in _STARTS_WITH):
        return True
    return any(k in text for k in CJK_COMMERCE_KEYWORDS) and not any(n in text for n in _CJK_NEGATIVE)


def _path_tokens(path: str) -> list[str]:
    path = unicodedata.normalize("NFKC", path or "")
    return [t for t in re.split(r"[\W_]+", _CAMEL_RE.sub(" ", path).casefold()) if t]


def is_commerce_url(url: str | None, broad: bool = False) -> bool:
    """True when a URL looks transactional.

    By default a URL counts only when it has a transactional shape: a ``checkout.*`` style
    host, a ``/checkout`` (or ``/place-order``, ...) segment, ``/cart/confirm``,
    ``/order/place``, or a first segment such as ``/pay``, ``/payment``, ``/billing``,
    ``/subscribe`` or ``/donate`` that is alone, followed by an id, or followed by an action
    (``/payment/confirm``). ``/wiki/Payment``, ``/help/payment-methods`` or ``/subscriptions``
    do not match. With ``broad=True`` any path token such as "payment" or "donation" matches
    (used for form actions, where the URL is the submit target).
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if host.split(".")[0] in _URL_HOST_LABELS and host.count(".") >= 2:
        return True
    tokens = _path_tokens(parts.path)
    if not tokens or any(t in _URL_NEGATIVE_TOKENS for t in tokens):
        return False
    if any(pair in _URL_BIGRAMS for pair in zip(tokens, tokens[1:], strict=False)):
        return True
    if broad:
        return any(t in _URL_TOKENS for t in tokens)
    segments = [seg for seg in unicodedata.normalize("NFKC", parts.path or "").split("/") if seg]
    joined = ["".join(_path_tokens(seg)) for seg in segments]
    if any(j in _URL_CHECKOUT_SEGMENTS for j in joined):
        return True
    if joined and _LOCALE_RE.match(segments[0].casefold()):
        joined = joined[1:]
        segments = segments[1:]
    if not joined or joined[0] not in _URL_ROOT_SEGMENTS:
        return False
    rest = joined[1:]
    if not rest:
        return True
    return len(rest) == 1 and (rest[0] in _URL_ROOT_ACTIONS or bool(_ID_RE.match(segments[1].casefold())))


def _attrs(node: Any) -> dict[str, str]:
    a = getattr(node, "attributes", None)
    return a if isinstance(a, dict) else {}


def _tag(node: Any) -> str:
    return str(getattr(node, "node_name", "") or "").lower()


def _ancestor_form(node: Any) -> Any | None:
    cur = node
    for _ in range(40):
        if cur is None:
            return None
        if _tag(cur) == "form":
            return cur
        cur = getattr(cur, "parent_node", None)
    return None


def _is_submit_like(node: Any) -> bool:
    typ = str(_attrs(node).get("type", "")).lower()
    tag = _tag(node)
    if tag == "button":
        return typ in ("", "submit")
    if tag == "input":
        return typ in ("submit", "image")
    return False


def _is_clickable_control(node: Any) -> bool:
    a = _attrs(node)
    return _tag(node) in ("button", "a") or str(a.get("role", "")).lower() in ("button", "link") or (
        _tag(node) == "input" and str(a.get("type", "")).lower() in _SUBMIT_TYPES
    )


def form_looks_transactional(node: Any) -> bool:
    """True when the enclosing <form> of ``node`` has a transactional action/id/name."""
    form = _ancestor_form(node)
    if form is None:
        return False
    fa = _attrs(form)
    if is_commerce_url(fa.get("action"), broad=True):
        return True
    return any(is_commerce_label(fa.get(k)) for k in ("id", "name", "aria-label"))


def element_risk(node: Any, page_url: str | None, label: str | None,
                 patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> str | None:
    """Return a reason string when a click target looks transactional, else None."""
    if is_commerce_label(label, patterns):
        return f"label {label!r} looks like a purchase/commerce action"
    a = _attrs(node)
    for key in ("href", "formaction", "data-href", "data-url"):
        if is_commerce_url(a.get(key), broad=key == "formaction"):
            return f"{key} {a.get(key)!r} points to a checkout/payment URL"
    for key in ("name", "id", "aria-label", "title", "value", "data-testid", "data-action"):
        if is_commerce_label(a.get(key), patterns):
            return f"attribute {key}={a.get(key)!r} looks like a purchase/commerce action"
    if _is_submit_like(node) and form_looks_transactional(node):
        return "submit button inside a checkout/payment/order form"
    if is_commerce_url(page_url) and _is_clickable_control(node):
        return "clickable control on a checkout/payment page"
    if not label and is_commerce_url(page_url):
        return "unlabeled control on a checkout/payment page"
    return None


def element_label(node: Any, max_len: int = 200) -> str | None:
    """Best-effort human label for a browser-use DOM node (never raises)."""
    if node is None:
        return None
    try:
        parts: list[str] = []
        ax = getattr(node, "ax_node", None)
        ax_name = getattr(ax, "name", None) if ax is not None else None
        if isinstance(ax_name, str) and ax_name.strip():
            parts.append(ax_name)
        attrs = getattr(node, "attributes", None) or {}
        if isinstance(attrs, dict):
            for key in ("aria-label", "title", "value", "alt", "name"):
                v = attrs.get(key)
                if isinstance(v, str) and v.strip():
                    parts.append(v)
        getter = getattr(node, "get_all_children_text", None)
        if callable(getter):
            try:
                text = getter()
            except Exception:
                text = ""
            if isinstance(text, str) and text.strip():
                parts.append(text)
        nv = getattr(node, "node_value", None)
        if isinstance(nv, str) and nv.strip():
            parts.append(nv)
        label = " | ".join(dict.fromkeys(" ".join(p.split()) for p in parts))
        return label[:max_len] or None
    except Exception:  # pragma: no cover - defensive
        return None


def _keys_press_enter(keys: Any) -> bool:
    if not isinstance(keys, str):
        return False
    return any(tok.strip().lower() in ("enter", "return", "numpadenter") for tok in re.split(r"[+\s]+", keys))


class GuardedTools(Tools):
    """Tools that gate irreversible actions: commerce clicks, Enter/newline submits on
    checkout pages, JavaScript evaluation and navigation to checkout/payment URLs.

    Lookup failures fail closed: an unresolvable click target is treated as gated, and with
    no approval callback a gated action is denied. ``allow_evaluate=True`` disables the
    always-gate on ``evaluate``.
    """

    def __init__(
        self,
        *args: Any,
        patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS,
        gate_commerce_clicks: bool = True,
        approval: ApprovalCallback | None = None,
        blocked_log: list[str] | None = None,
        allow_evaluate: bool = False,
        blocked_domains: Iterable[str] = SAFETY_DEFAULTS,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lba_patterns = tuple(patterns)
        self._lba_gate = gate_commerce_clicks
        self._lba_approval = approval
        self._lba_allow_evaluate = allow_evaluate
        self._lba_blocked = frozenset(SAFETY_DEFAULTS | {str(d).strip().lower().rstrip(".") for d in blocked_domains})
        self.blocked_actions: list[str] = blocked_log if blocked_log is not None else []

    async def _lba_url(self, browser_session: Any) -> tuple[str | None, bool]:
        """Return (url, ok); ok is False when the lookup failed."""
        try:
            url = await browser_session.get_current_page_url()
            return (url if isinstance(url, str) else None), True
        except Exception:
            return None, False

    async def _lba_node(self, params: dict[str, Any], browser_session: Any) -> tuple[Any, bool]:
        """Return (node, ok). ok is False when the target could not be resolved."""
        try:
            index = params.get("index")
            if index is not None:
                node = await browser_session.get_element_by_index(index)
            else:
                x, y = params.get("coordinate_x"), params.get("coordinate_y")
                if x is None or y is None:
                    return None, False
                node = await browser_session.get_dom_element_at_coordinates(x, y)
            return node, node is not None
        except Exception as e:
            logger.debug("element lookup failed: %s", e)
            return None, False

    async def _lba_ask(self, req: ActionRequest) -> ActionResult | None:
        """Ask for approval; return an error ActionResult when denied, None when approved."""
        approved = False
        if self._lba_approval is not None:
            try:
                approved = bool(await self._lba_approval(req))
            except Exception as e:
                logger.warning("approval callback failed, denying: %s", e)
                approved = False
        if approved:
            return None
        desc = req.action_name + (f" on {req.element_label!r}" if req.element_label else "") + (
            f" at {req.url}" if req.url else "")
        self.blocked_actions.append(desc)
        why = f" ({req.reason})" if req.reason else ""
        if req.action_name in EVAL_ACTIONS:
            if self._lba_approval is None:
                msg = ("JavaScript evaluation is disabled in this session (set LBA_ALLOW_EVALUATE=true to allow). "
                       "Use click, input, scroll or extract instead and continue the task.")
            else:
                msg = ("JavaScript evaluation was not approved. "
                       "Use click, input, scroll or extract instead and continue the task.")
            return ActionResult(error=msg)
        return ActionResult(
            error=(
                f"Blocked by safety policy: {desc}{why} looks like a purchase/irreversible action "
                "and was not approved. Do not retry; finish with success=False and report it."
            )
        )

    def _lba_blocked_navigation(self, action: Any) -> ActionResult | None:
        """Hard-deny navigation (including new-tab) to a blocked domain; no approval can lift it."""
        try:
            dumped = action.model_dump(exclude_unset=True)
        except Exception:
            return None
        for name, params in dumped.items():
            if name not in NAVIGATE_ACTIONS or not isinstance(params, dict):
                continue
            dest = params.get("url")
            if not isinstance(dest, str):
                continue
            try:
                host = urlsplit(dest.strip()).hostname
            except ValueError:
                continue
            if host_is_blocked(host, self._lba_blocked):
                self.blocked_actions.append(f"{name} at {dest}")
                return ActionResult(error=f"Blocked by safety policy: {host} is a blocked domain. "
                                          "Do not navigate there; choose another site.")
        return None

    async def act(self, action: Any, browser_session: Any, *args: Any, **kwargs: Any) -> ActionResult:
        denied_nav = self._lba_blocked_navigation(action)
        if denied_nav is not None:
            return denied_nav
        if self._lba_gate:
            try:
                dumped = action.model_dump(exclude_unset=True)
            except Exception:
                dumped = {}
            for name, params in dumped.items():
                if not isinstance(params, dict):
                    continue
                req = await self._lba_classify(name, params, browser_session)
                if req is None:
                    continue
                denied = await self._lba_ask(req)
                if denied is not None:
                    return denied
        return await super().act(action, browser_session, *args, **kwargs)

    async def _lba_classify(self, name: str, params: dict[str, Any], browser_session: Any) -> ActionRequest | None:
        """Return an ActionRequest when the action must be approved, else None."""
        if name in CLICK_ACTIONS:
            node, ok = await self._lba_node(params, browser_session)
            url, _ = await self._lba_url(browser_session)
            label = element_label(node) if ok else None
            if not ok:
                reason: str | None = "target element could not be resolved (failing closed)"
            else:
                try:
                    reason = element_risk(node, url, label, self._lba_patterns)
                except Exception as e:  # pragma: no cover - defensive
                    reason = f"element inspection failed ({e}); failing closed"
            if reason is None:
                return None
            return ActionRequest(action_name=name, params=dict(params), element_label=label, url=url, reason=reason)
        if name in NAVIGATE_ACTIONS:
            dest = params.get("url")
            if isinstance(dest, str) and is_commerce_url(dest):
                return ActionRequest(action_name=name, params=dict(params), url=dest,
                                     reason="navigation to a checkout/payment URL")
            return None
        if name in EVAL_ACTIONS:
            if self._lba_allow_evaluate:
                return None
            code = params.get("code")
            snippet = " ".join(str(code).split())[:200] if code is not None else None
            url, _ = await self._lba_url(browser_session)
            return ActionRequest(action_name=name, params=dict(params), element_label=snippet, url=url,
                                 reason="arbitrary JavaScript can submit forms or click anything")
        if name in KEY_ACTIONS:
            if not _keys_press_enter(params.get("keys")):
                return None
            url, ok = await self._lba_url(browser_session)
            if not ok:
                reason = "page URL could not be read (failing closed)"
            elif is_commerce_url(url):
                reason = "Enter pressed on a checkout/payment page"
            else:
                return None
            return ActionRequest(action_name=name, params=dict(params), element_label=str(params.get("keys")),
                                 url=url, reason=reason)
        if name in INPUT_ACTIONS:
            text = params.get("text")
            if not isinstance(text, str) or not text.endswith(("\n", "\r")):
                return None
            node, ok = await self._lba_node(params, browser_session)
            url, url_ok = await self._lba_url(browser_session)
            if not ok:
                reason = "input target could not be resolved (failing closed)"
            elif form_looks_transactional(node) or is_commerce_url(url):
                reason = "text ending in a newline submits a checkout/payment form"
            elif not url_ok:
                reason = "page URL could not be read (failing closed)"
            else:
                return None
            return ActionRequest(action_name=name, params=dict(params),
                                 element_label=element_label(node) if ok else None, url=url, reason=reason)
        return None
