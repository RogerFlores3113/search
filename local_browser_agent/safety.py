"""Safety policy primitives: default blocked domains, guardrail prompt, commerce click gate."""
from __future__ import annotations

import asyncio
import functools
import ipaddress
import json
import logging
import os
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools

from local_browser_agent.redact import redact_url

logger = logging.getLogger("local_browser_agent")

SAFETY_DEFAULTS: frozenset[str] = frozenset({
    # Banking
    "chase.com", "wellsfargo.com", "bankofamerica.com", "citi.com", "usbank.com",
    "capitalone.com", "americanexpress.com", "discover.com",
    # Brokerage / crypto
    "schwab.com", "fidelity.com", "vanguard.com", "etrade.com", "robinhood.com",
    "coinbase.com", "kraken.com", "binance.com",
    # Payment
    "paypal.com", "venmo.com", "stripe.com", "square.com", "braintree.com",
    "cash.app", "wise.com", "zellepay.com",
    # PayPal sibling TLDs (browser-use patterns cannot express ``paypal.*``, so the main ones are listed)
    "paypal.me", "paypal.co.uk", "paypal.de", "paypal.fr", "paypal.it", "paypal.es", "paypal.ca",
    "paypal.com.au", "paypal.nl", "paypal.ch", "paypal.at", "paypal.be", "paypal.pl", "paypal.ie",
    "paypal.co.jp", "paypal.com.br", "paypal.in", "paypal.com.mx",
    # Tax (account pages live under these domains)
    "intuit.com", "turbotax.com",
    # Government
    "irs.gov", "ssa.gov", "healthcare.gov", "va.gov", "dhs.gov",
    "state.gov", "fbi.gov", "whitehouse.gov",
    # Medical
    "labcorp.com", "questdiagnostics.com", "epic.com", "mychart.com",
    # Credential / Identity
    "lastpass.com", "1password.com", "bitwarden.com", "dashlane.com",
    "nordpass.com", "okta.com", "auth0.com",
    # Identity providers and account settings. Path-level pages (github.com/settings, the AWS
    # console under a path) cannot be expressed as domain rules and are deliberately NOT listed:
    # github.com itself stays reachable; the AWS console and sign-in hosts are blocked by host.
    "accounts.google.com", "myaccount.google.com", "appleid.apple.com",
    "login.microsoftonline.com", "login.live.com", "account.microsoft.com",
    "console.aws.amazon.com", "signin.aws.amazon.com",
})

GUARDRAIL_PROMPT = (
    "\nSAFETY GUARDRAILS — override everything else:\n"
    "1. NEVER click Buy Now, Purchase, Checkout, Pay, Place Order, Confirm Order, "
    "Complete Purchase, or any equivalent commerce CTA.\n"
    "2. NEVER submit forms containing credit card numbers, CVVs, bank account details, "
    "Social Security Numbers, or passwords on any site the user did not explicitly name.\n"
    "3. NEVER submit credentials (username/password) on any site not explicitly named.\n"
    "4. If you encounter such an element, do not activate it: stop that step, continue with whatever "
    "does not need it, and report what you found so the user can decide.\n"
)

DEFAULT_COMMERCE_PATTERNS: tuple[str, ...] = (
    "buy now",
    "buy it now",
    "pay now",
    "place order",
    "place your order",
    "confirm order",
    "confirm purchase",
    "complete purchase",
    "purchase now",
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
# Sends a local file to the website: always needs approval.
UPLOAD_ACTIONS = frozenset({"upload_file", "upload_file_to_element"})
SELECT_ACTIONS = frozenset({"select_dropdown", "select_dropdown_option"})

# Phrases matched as whole words (Latin scripts), after normalisation.
MULTILINGUAL_COMMERCE_PATTERNS: tuple[str, ...] = (
    # en
    "order now", "buy again", "make payment", "make a payment", "finalize order", "finalise order",
    "confirm payment", "send money", "book now", "reserve now", "complete payment", "proceed to payment",
    "proceed to pay", "pay securely", "pay with", "donate now", "subscribe now",
    "confirm and pay", "confirm booking", "complete booking", "confirm your order", "complete checkout",
    "complete your purchase", "complete your order", "place my order", "pay invoice", "pay your invoice",
    "submit payment", "order and pay", "proceed to buy", "1 click buy", "one click buy", "1 click order",
    "upgrade now", "place bid", "place a bid", "place your bid",
    "start free trial", "start my free trial", "start your free trial", "send payment", "pay bill", "pay my bill",
    "pay your bill", "agree and pay", "accept and pay", "accept and continue to pay", "sign up and pay",
    "authorize payment", "authorise payment", "approve payment", "apple pay", "google pay", "g pay", "gpay",
    "upgrade plan", "upgrade your plan", "upgrade account", "upgrade to pro", "upgrade to premium",
    "upgrade to plus", "withdraw funds", "transfer funds", "confirm transfer", "rent now", "finish order",
    "continue to payment",
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
    # ru / uk / ar / hi / tr / pl / sv / id / vi (single words that are only a CTA as a whole label)
    "купить", "оплатить", "заказать", "купити", "сплатити", "оплатити", "замовити",
    "شراء", "اشتر", "ادفع", "اطلب", "खरीदें", "भुगतान करें", "ऑर्डर करें",
    "öde", "satın al", "kup", "zapłać", "zamów", "köp", "betala", "beställ", "beli", "bayar", "pesan",
    "mua", "thanh toán", "đặt hàng",
    "αγορά", "αγορα", "اشتري", "upgrade",
})

# Multi-word CTAs in non-Latin-script and other languages, matched as whole phrases.
NON_LATIN_COMMERCE_PATTERNS: tuple[str, ...] = (
    # ru
    "оформить заказ", "купить сейчас", "купить сразу", "оплатить заказ", "оплатить сейчас", "перейти к оплате",
    "подтвердить заказ", "подтвердить оплату", "оформить подписку", "подписаться и оплатить",
    # uk
    "оформити замовлення", "купити зараз", "оплатити зараз", "підтвердити замовлення", "перейти до оплати",
    # ar
    "إتمام الطلب", "اتمام الطلب", "إتمام الشراء", "اتمام الشراء", "اشتر الآن", "اشتري الآن", "ادفع الآن",
    "شراء الآن", "تأكيد الطلب", "تأكيد الدفع", "الدفع الآن", "تقديم الطلب",
    # hi
    "अभी खरीदें", "अभी भुगतान करें", "ऑर्डर दें", "ऑर्डर पक्का करें", "भुगतान करें",
    # tr
    "hemen satın al", "ödeme yap", "şimdi öde", "siparişi tamamla", "sipariş ver", "ödemeye geç",
    # pl
    "kup teraz", "zapłać teraz", "złóż zamówienie", "zamawiam i płacę", "do kasy", "przejdź do płatności",
    # sv
    "köp nu", "betala nu", "slutför köp", "lägg beställning", "till kassan", "slutför beställningen",
    # id
    "beli sekarang", "bayar sekarang", "pesan sekarang", "lanjut ke pembayaran", "selesaikan pembayaran",
    # vi
    "mua ngay", "thanh toán ngay", "đặt hàng ngay", "đặt mua", "tiến hành thanh toán",
)

# Start-of-label matches ("Buy 2 for $20", "Donate $50").
_STARTS_WITH = ("buy ", "donate ", "kaufen ", "comprar ", "acheter ", "acquista ")
_STARTS_WITH_MAX_WORDS = 6

# CJK keywords are matched as substrings (no word boundaries in those scripts).
CJK_COMMERCE_KEYWORDS: tuple[str, ...] = (
    # ja
    "購入", "注文", "支払", "決済", "申し込", "申込", "寄付", "送金", "予約", "レジに進", "お会計",
    # zh
    "购买", "購買", "支付", "付款", "结算", "結算", "下单", "下單", "提交订单", "提交訂單",
    "订阅", "訂閱", "捐款", "捐赠", "捐贈", "转账", "轉賬", "汇款", "匯款", "预订", "預訂", "预定",
    # ko
    "구매", "결제", "주문", "구독", "후원", "기부", "송금", "예약",
    # th (no word breaks)
    "ซื้อ", "ชำระเงิน", "สั่งซื้อ", "สมัครสมาชิก", "จ่ายเงิน",
)
_CJK_NEGATIVE = (
    "履歴", "履歷", "历史", "歷史", "歴史", "내역", "기록", "詳細", "详情", "詳情", "상세", "一覧",
    "ガイド", "指南", "帮助", "幫助", "도움말", "キャンセル", "取消", "취소",
    "ประวัติ", "รายละเอียด", "วิธี", "ยกเลิก",
)

# Labels that are informational, not a purchase CTA. They suppress the weaker matches when the
# label starts like a how-to/explainer or ends in one of these words ("Buy now, pay later
# explained", "Purchase history"). Strong phrases ("place order", "pay now", ...) are never
# suppressed so a CTA cannot be hidden by appending a word.
_INFO_PREFIXES = ("how to ", "how do ", "what is ", "what are ", "why ", "learn ", "about ", "when to ")
_INFO_SUFFIXES = frozenset({
    "explained", "history", "guide", "faq", "faqs", "policy", "policies", "details", "info", "information",
    "tutorial", "help", "terms", "report", "reports", "accepted", "methods", "attention", "tips",
    "tracking", "status", "page", "pages", "design", "process", "analysis", "article", "blog",
})
# Nouns that turn a CTA phrase into a topic ("Place order tracking", "Buy now history"): they suppress a
# CTA that starts the label. The weaker ones above ("details", "faq", "info", "help", "terms") are what an
# attacker appends to a real button, so they only suppress when the label is longer and clearly an explainer.
_NOUN_MODIFIERS = frozenset({
    "explained", "history", "policy", "policies", "methods", "attention", "tracking", "status", "page",
    "pages", "design", "process", "analysis", "article", "blog",
})
# Second words that make "Buy ..."/"Donate ..." a topic instead of a CTA ("Buy-in", "Buy side analysis").
_STARTS_WITH_TOPIC_WORDS = frozenset({"in", "vs", "versus", "side", "guide", "guides", "tips", "hub", "button"})
# Exact labels that are ordinary words once a bare number is attached ("Book 3", "Order 2").
_AMBIGUOUS_EXACT = frozenset({"book", "order", "reserve", "buchen", "boeken", "réserver", "reserver", "reservar", "prenota"})
_CURRENCY_RE = re.compile(r"[$€£¥₹₩₽]")
# Phrases matched as whole squeezed tokens ("Bu y now", "BUYNOW", "Buy\u200bnow", "Buy now details").
_CHECKOUT_PHRASES = ("proceed to checkout", "go to checkout", "secure checkout", "express checkout",
                     "continue to checkout", "guest checkout", "complete checkout")
_STRONG_PHRASES = frozenset({
    "place order", "place your order", "confirm order", "complete purchase", "complete order",
    "submit order", "confirm purchase", "confirm payment", "pay now", "complete payment",
})
# Bare verbs that are a CTA only in a payment-shaped context, never as a loose word.
_BARE_VERBS = ("pay", "purchase", "checkout", "check out")
_BARE_PREFIXES = ("proceed to ", "secure ", "express ", "go to ", "continue to ", "guest ", "quick ", "instant ")
_AMOUNT_RE = re.compile(r"[\d$€£¥₹₩₽]")

# Cyrillic / Greek look-alikes folded to Latin so "Рay" (Cyrillic Р) still reads "pay".
_HOMOGLYPHS = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ӏ": "l", "ᴀ": "a", "ɡ": "g",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "η": "n", "μ": "u", "ω": "w", "ς": "s",
    # Armenian look-alikes and IPA / small-cap letters that NFKC leaves alone ("ʙᴜʏ ɴᴏᴡ", "Bսy now").
    "ս": "u", "օ": "o", "ց": "g", "ɓ": "b", "ƀ": "b", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f",
    "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n", "ᴏ": "o", "ᴘ": "p", "ʀ": "r",
    "ꜱ": "s", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w", "ʏ": "y", "ᴢ": "z",
})

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
    ("order", "pay"), ("order", "payment"), ("basket", "payment"), ("basket", "checkout"),
    ("basket", "pay"), ("cart", "payment"), ("gp", "buy"),
})
# Content sites where a path like /wiki/Checkout or /org/checkout (a repo) is not a payment page.
# Only URL-shape signals are skipped there; labels and form actions still count.
_CONTENT_HOSTS = frozenset({
    "wikipedia.org", "wikimedia.org", "wikimedia.com", "github.com", "gitlab.com", "reddit.com",
    "stackoverflow.com", "stackexchange.com", "medium.com", "news.ycombinator.com", "youtube.com",
})
_URL_STEP_VALUES = frozenset({
    "payment", "pay", "review_order", "revieworder", "place_order", "placeorder", "billing_payment",
    "payment_method", "payment_info",
})
_URL_STEP_KEYS = frozenset({"step", "checkout_step", "checkoutstep", "checkout-step"})
_PAGE_EXT_RE = re.compile(r"\.(?:php|aspx?|html?|jsp|do|cgi|action)$", re.IGNORECASE)
_URL_NEGATIVE_TOKENS = frozenset({
    "history", "faq", "help", "policy", "policies", "terms", "methods", "settings", "docs", "blog",
    "news", "article", "articles", "press", "tutorial", "tutorials",
})
_URL_HOST_LABELS = frozenset({"checkout", "pay", "payments", "billing", "donate"})
_URL_COMMERCE_HOSTS = frozenset({"buy.stripe.com", "checkout.stripe.com"})
# Query parameters whose value is where the visitor lands next (``?next=/checkout``).
_URL_REDIRECT_KEYS = frozenset({
    "next", "return", "return_to", "returnto", "return_url", "returnurl", "redirect", "redirect_to",
    "redirectto", "redirect_url", "redirecturl", "redirect_uri", "continue", "goto", "dest", "destination",
})
# Segments that make a following "checkout" segment part of a store, not of an article path.
_URL_SHOP_PRECEDERS = frozenset({
    "cart", "carts", "store", "stores", "shop", "shops", "basket", "bag", "secure", "order", "orders",
    "my", "account", "mycart", "onepage", "servlet",
})
# A path segment (separators removed) that is transactional wherever it appears.
_URL_CHECKOUT_SEGMENTS = frozenset({
    "checkout", "checkouts", "placeorder", "buynow", "paynow", "confirmpayment",
    "kasse", "caisse", "cassa", "makepayment", "makeapayment", "securepayment",
    "expresscheckout", "onestepcheckout", "onepagecheckout", "guestcheckout", "checkoutview", "checkoutnow",
    "checkoutstep",
})
_URL_CHECKOUT_STEP_RE = re.compile(r"^checkoutstep\d*$")
# Segments that are transactional only as the first path segment (after an optional locale),
# either alone, followed by an id, or followed by an action word.
_URL_ROOT_SEGMENTS = frozenset({
    "pay", "payment", "payments", "billing", "subscribe", "donate", "purchase", "buy",
    "zahlung", "paiement", "pagamento", "betaling",
})
_URL_ROOT_ACTIONS = frozenset({
    "confirm", "submit", "process", "checkout", "pay", "complete", "review", "place",
    "new", "update", "upgrade", "add", "change", "start", "authorize",
})
_LOCALE_RE = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$")
_ID_RE = re.compile(r"^[\w-]*\d[\w-]*$")

# --- Domain helpers ------------------------------------------------------------------
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_HOST_RE = re.compile(r"^[^\W_](?:[\w-]*[^\W_])?(?:\.[^\W_](?:[\w-]*[^\W_])?)*$")


_HOST_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": ".", "\u2024": "."})
_HOST_FORBIDDEN_RE = re.compile(r"[\s/\\?#@%<>^|\"'`{}\[\]]")


def _idna_encode(h: str) -> str:
    """IDNA-encode like Chrome (UTS46 non-transitional, so ``ß`` stays ``xn--zca``) when ``idna`` is available."""
    if h.isascii():
        return h.encode("idna").decode("ascii")
    try:
        import idna  # noqa: PLC0415
    except ImportError:
        return h.encode("idna").decode("ascii")
    try:
        return idna.encode(h, uts46=True, transitional=False).decode("ascii")
    except idna.IDNAError as e:
        raise UnicodeError(str(e)) from e


def canonical_host(host: str | None) -> str | None:
    """Canonical form of a URL host, the way Chrome resolves it. None when it cannot be canonicalised.

    Percent-decodes, applies NFKC, drops format (Cf) characters such as zero-width spaces and soft
    hyphens, maps ideographic/fullwidth dots to ``.``, lowercases, strips trailing dots and
    IDNA-encodes (punycode for non-ASCII). IPv6 literals are only lowercased and lose any zone id.
    Callers must treat None for a non-empty host as "deny".
    """
    if host is None:
        return None
    h = str(host).strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if ":" in h:  # IPv6 literal (urlsplit already removed any port)
        h = h.split("%", 1)[0].lower()
        try:
            return str(ipaddress.ip_address(h))
        except ValueError:
            return None
    for _ in range(2):  # decode, then reject anything that is still encoded
        h2 = unquote(h)
        if h2 == h:
            break
        h = h2
    h = h.translate(_HOST_DOTS)
    h = unicodedata.normalize("NFKC", h)
    h = "".join(c for c in h if unicodedata.category(c) != "Cf" and c != "\u00ad")
    h = h.translate(_HOST_DOTS).lower().rstrip(".")
    if not h or _HOST_FORBIDDEN_RE.search(h) or any(unicodedata.category(c) in ("Cc", "Zs", "Zl", "Zp") for c in h):
        return None
    try:
        h = _idna_encode(h)
    except (UnicodeError, ValueError):
        return None
    return h.lower().rstrip(".") or None


# Common multi-part public suffixes (ICANN section); an allow-list entry equal to one of these
# would open every registrant under it.
PUBLIC_SUFFIXES: frozenset[str] = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "sch.uk", "nhs.uk", "police.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "asn.au", "id.au",
    "co.nz", "org.nz", "net.nz", "govt.nz", "ac.nz", "school.nz",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp", "ad.jp", "ed.jp", "gr.jp", "lg.jp",
    "co.in", "net.in", "org.in", "gov.in", "ac.in", "edu.in", "res.in", "firm.in", "gen.in", "ind.in",
    "com.br", "net.br", "org.br", "gov.br", "edu.br",
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.mx", "org.mx", "gob.mx", "edu.mx", "com.ar", "org.ar", "gob.ar", "com.co", "com.pe", "com.ve", "com.uy",
    "com.tr", "org.tr", "net.tr", "gov.tr", "edu.tr", "com.sg", "edu.sg", "gov.sg", "com.hk", "org.hk", "gov.hk",
    "com.tw", "org.tw", "gov.tw", "edu.tw", "com.my", "gov.my", "edu.my", "com.ph", "gov.ph", "com.vn", "gov.vn",
    "com.ua", "gov.ua", "co.za", "org.za", "gov.za", "ac.za", "co.il", "org.il", "gov.il", "ac.il",
    "co.kr", "or.kr", "go.kr", "ac.kr", "co.id", "or.id", "go.id", "ac.id", "co.th", "or.th", "go.th", "ac.th",
    "com.eg", "com.sa", "com.pk", "com.ng", "co.ke", "com.gh", "com.bd", "com.lk", "com.np", "com.ru",
    "com.pl", "com.pt", "com.es", "com.gr", "com.cy", "com.de", "co.at", "or.at", "co.hu", "co.ve",
    # Shared hosting / PaaS suffixes: every customer is an unrelated registrant (PSL private section).
    "github.io", "herokuapp.com", "blogspot.com", "pages.dev", "vercel.app", "netlify.app", "web.app",
    "firebaseapp.com", "azurewebsites.net", "cloudfront.net", "appspot.com", "workers.dev", "gitlab.io",
    "onrender.com", "fly.dev", "glitch.me", "repl.co", "surge.sh", "wixsite.com", "weebly.com",
    "myshopify.com", "s3.amazonaws.com", "amazonaws.com", "herokudns.com", "ngrok.io", "ngrok-free.app",
    "trycloudflare.com", "azureedge.net", "blob.core.windows.net", "web.core.windows.net",
})


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
    canon = canonical_host(host)
    if canon is None:
        raise ValueError(f"allowed domain {raw!r} is not a valid hostname")
    host = canon
    if host in PUBLIC_SUFFIXES:
        raise ValueError(f"allowed domain {raw!r} is a public suffix that covers unrelated sites; "
                         "name a specific site like 'example.co.uk'")
    return ("*." + host) if wildcard else host


def normalize_blocked_domain(raw: Any) -> str:
    """Normalise a blocked-domain entry to a bare canonical (punycode) hostname.

    Scheme, userinfo, port, path, query, fragment, a ``*.`` / ``.`` prefix and trailing dots are
    stripped, so ``"*.evil.com"``, ``"https://evil.com/x"`` and ``"evil.com:8080"`` all become
    ``"evil.com"``.

    Raises:
        ValueError: when no valid host remains.
    """
    d = str(raw).strip().lower()
    d = _SCHEME_RE.sub("", d)
    for sep in "/\\?#":
        d = d.split(sep, 1)[0]
    d = d.rsplit("@", 1)[-1]
    if not d.startswith("["):
        d = re.sub(r":\d*$", "", d)
    d = d.rstrip(".")
    while d.startswith(("*.", ".")):
        d = d[2:] if d.startswith("*.") else d[1:]
    canon = canonical_host(d) if d else None
    if not canon or "*" in canon:
        raise ValueError(f"blocked domain {raw!r} has no valid hostname")
    return canon


def try_normalize_blocked_domain(raw: Any) -> str | None:
    """Like :func:`normalize_blocked_domain` but returns None for an empty or invalid entry."""
    try:
        return normalize_blocked_domain(raw)
    except ValueError:
        return None


def host_is_blocked(host: str | None, blocked: Iterable[str]) -> bool:
    """True when ``host`` is, or is a subdomain of, a blocked domain."""
    if not (host or "").strip():
        return False
    h = canonical_host(host)
    if h is None:  # cannot be canonicalised: treat as blocked rather than guess
        return True
    for x in blocked:
        b = canonical_host(x) or str(x).strip().lower().rstrip(".")
        if b and (h == b or h.endswith("." + b)):
            return True
    return False


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
# Invisible "blank" characters that are not Zs/Cf: braille blank, Hangul fillers, Mongolian/Khmer vowels.
_BLANK_RE = re.compile(r"[\u2800\u3164\u115f\u1160\uffa0\u17b4\u17b5\u034f]")
_TURKISH_I = str.maketrans({"\u0131": "i", "\u0130": "I"})
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
    t = unicodedata.normalize("NFKC", str(text)).translate(_TURKISH_I)
    t = _ZERO_WIDTH_RE.sub("", t)
    t = _BLANK_RE.sub(" ", t)
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


_EXACT_NORM = frozenset(normalize_text(x) for x in EXACT_COMMERCE_LABELS)
_EXACT_SQUEEZED = frozenset(x.replace(" ", "") for x in _EXACT_NORM)
_AMBIGUOUS_EXACT = frozenset("".join(normalize_text(x).split()) for x in _AMBIGUOUS_EXACT)


def _strip_marks(text: str) -> str:
    """Drop combining marks ("Páy", "Pa\u0336y") so accented or struck-through letters read as plain."""
    return unicodedata.normalize("NFC", "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"))


def _letterspaced(text: str) -> bool:
    """True for labels spelled one letter at a time ("B u y   n o w")."""
    words = text.split()
    return len(words) >= 3 and sum(len(w) == 1 for w in words) >= 0.7 * len(words)


_CJK_NORM = tuple(normalize_text(k) for k in CJK_COMMERCE_KEYWORDS)
_CJK_NEG_NORM = tuple(normalize_text(k) for k in _CJK_NEGATIVE)


def _fold_homoglyphs(text: str) -> str:
    return text.translate(_HOMOGLYPHS)


_NOISE_WORDS = frozenset({"item", "items", "product", "products", "article", "articles", "x", "qty"})
# Strong phrases that stay gated whenever the label starts with them, even with a topic-like last word.
_GATED_STARTS = ("pay now", "buy now", "place order", "place your order", "complete purchase", "complete order",
                 "confirm purchase", "proceed to checkout")
# Of those, the purchase/order-style ones that "history/tracking/status" turns into a topic.
_TOPIC_EXEMPT_STARTS = frozenset({"place order", "complete purchase", "complete order", "confirm purchase"})
_TOPIC_TAILS = frozenset({"history", "tracking", "status"})


def _is_noise(word: str) -> bool:
    """Counts, prices and quantities that may trail a CTA: "(3", "items)", "$45.00", "x2", "qty"."""
    w = word.strip("()[]{}.,:;!·•")
    return (not w or any(c.isdigit() for c in w) or bool(_CURRENCY_RE.search(w)) or w in _NOISE_WORDS)


def _starts_with_cta_topic(text: str, words: list[str]) -> bool:
    """A label that starts with a strong CTA and ends in a topic noun, but is still the CTA."""
    for ph in _GATED_STARTS:
        if text == ph or text.startswith(ph + " "):
            tail = text[len(ph):].split()
            if len(tail) >= 3:
                return False  # a longer heading: "Pay now pay later policy"
            if len(tail) == 1 and tail[0] in _TOPIC_TAILS and ph in _TOPIC_EXEMPT_STARTS:
                return False  # "Place order tracking"
            return True
    return False


_CHECKOUT_FOLLOWERS = ("now", "with", "securely", "and", "via", "online", "as", "here")


def _bare_verb_cta(text: str) -> bool:
    """True for pay/purchase/checkout used as a call to action rather than as a loose word."""
    for v in _BARE_VERBS:
        if not _phrase_in(v, text):
            continue
        checkout = v in ("checkout", "check out")
        # "pay now", "pay with ...", "pay securely", "pay $20", "pay and continue"; for checkout only these
        # shapes too, so "Check out our blog" or "Checkout page design" are not a CTA.
        if re.match(rf"^{v}(?: (?:{'|'.join(_CHECKOUT_FOLLOWERS)}))\b", text) or (
                not checkout and text.startswith(v + " ") and _AMOUNT_RE.search(text)):
            return True
        if checkout and text.startswith(v + " ") and all(_is_noise(w) for w in text[len(v):].split()):
            return True  # "Checkout - 3 items"
        if checkout and _core(text) == v:
            return True  # the whole label is "Checkout" / "Check out"
        for pre in _BARE_PREFIXES:
            if not text.startswith(pre + v):
                continue
            tail = text[len(pre + v):]
            if tail == "" or (not checkout and tail.startswith(" ")):
                return True
            if checkout and tail.startswith(" ") and all(_is_noise(w) for w in tail.split()):
                return True  # "Checkout - 3 items", "Proceed to checkout ($45.00)"
            if checkout and tail.startswith(" ") and tail.split()[0] in _CHECKOUT_FOLLOWERS:
                return True
    return False


def _squeeze(phrase: str) -> str:
    return "".join(phrase.split())


@functools.lru_cache(maxsize=16)
def _cta_set(pats: tuple[str, ...]) -> tuple[frozenset[str], int]:
    """Squeezed multi-word CTA phrases (spaces removed) and the longest one's length."""
    phrases = {p for p in (*pats, *_STRONG_PHRASES, *(normalize_text(c) for c in _CHECKOUT_PHRASES)) if " " in p}
    ctas = frozenset(_squeeze(p) for p in phrases)
    return ctas, max((len(c) for c in ctas), default=0)


def _cta_run(words: list[str], ctas: frozenset[str], max_len: int) -> tuple[str, int] | None:
    """Find a CTA phrase spelled by a run of whole tokens at the start or end of the label.

    Token runs are concatenated, so "Bu y now", "BUYNOW" and "b UY nOW" all spell ``buynow``.
    Returns ``("whole" | "start" | "end", token_count)`` or None.
    """
    n = len(words)
    best: tuple[str, int] | None = None
    acc = ""
    for i in range(n):
        acc += words[i]
        if len(acc) > max_len:
            break
        if acc in ctas:
            best = ("whole" if i == n - 1 else "start", i + 1)
    if best and best[0] == "whole":
        return best
    acc = ""
    for i in range(n - 1, -1, -1):
        acc = words[i] + acc
        if len(acc) > max_len:
            break
        if acc in ctas:
            return ("end", n - i)
    return best


def _label_hit(text: str, patterns: tuple[str, ...], ctas: frozenset[str] = frozenset(), max_len: int = 0) -> bool:
    """Match one normalised variant of a label; see is_commerce_label."""
    words = text.split()
    if not words:
        return False
    core = _core(text)
    topic = len(words) >= 2 and words[-1] in _NOUN_MODIFIERS
    if topic and _starts_with_cta_topic(text, words):
        return True
    if not topic and (core in _STRONG_PHRASES or any(_phrase_in(p, text) for p in _STRONG_PHRASES)):
        return True
    run = _cta_run(words, ctas, max_len) if ctas else None
    informational = text.startswith(_INFO_PREFIXES) or (len(words) >= 3 and words[-1] in _INFO_SUFFIXES)
    if run is not None:
        where, count = run
        if where in ("whole", "end"):
            return True  # "Learn more. Buy now": a label that ends with a full CTA stays gated
        if topic:
            return False  # "Place order tracking"
        rest = words[count:]
        if sum(w not in _INFO_SUFFIXES and not _is_noise(w) for w in rest) < 2:
            return True  # "Buy now details", "Buy now FAQ": a short info tail cannot hide a CTA
    if informational:
        return False
    for p in patterns:
        if p and _phrase_in(p, text):
            return True
    sq = _squeeze(core)
    if core in _EXACT_NORM or sq in _EXACT_SQUEEZED:
        return not (sq in _AMBIGUOUS_EXACT and any(c.isdigit() for c in text) and not _CURRENCY_RE.search(text))
    if _bare_verb_cta(text):
        return True
    if any(text.startswith(s) for s in _STARTS_WITH) and len(words) <= _STARTS_WITH_MAX_WORDS \
            and words[1] not in _STARTS_WITH_TOPIC_WORDS:
        return True
    return any(k in text for k in _CJK_NORM) and not any(n in text for n in _CJK_NEG_NORM)


def is_commerce_label(label: str | None, patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> bool:
    """True when ``label`` looks like a purchase/payment/subscribe/donate call to action.

    The label is normalised (NFKC, zero-width removal, camelCase and separator folding,
    casefold) so "BuyNow", "Buy-now" and fullwidth/zero-width variants match; Cyrillic and Greek
    look-alike letters are also folded to Latin ("Рay"). Phrases match as whole words, CJK/Thai
    keywords as substrings, and bare generic verbs ("Buy", "Pay", "Purchase", "Subscribe") only as
    the whole label or in a payment-shaped context ("Pay now", "Pay $20"). Informational labels
    ("How to pay", "Pay per click", "Purchase history", "Buy now, pay later explained") pass.
    """
    if not label:
        return False
    text = normalize_text(label).replace("&", " and ")
    text = " ".join(text.split())
    if not text:
        return False
    pats = tuple(p for p in (normalize_text(x) for x in (*patterns, *MULTILINGUAL_COMMERCE_PATTERNS,
                                                          *NON_LATIN_COMMERCE_PATTERNS)) if p)
    stripped = _strip_marks(text)
    variants = dict.fromkeys((text, _fold_homoglyphs(text), stripped, _fold_homoglyphs(stripped)))
    ctas, max_len = _cta_set(pats)
    if any(_label_hit(v, pats, ctas, max_len) for v in variants):
        return True
    if _letterspaced(stripped):
        squeezed = _fold_homoglyphs(stripped).replace(" ", "")
        return squeezed in _EXACT_SQUEEZED or any(
            len(sp := p.replace(" ", "")) >= 5 and sp in squeezed for p in pats)
    return False


def _path_tokens(path: str) -> list[str]:
    path = unicodedata.normalize("NFKC", path or "")
    return [t for t in re.split(r"[\W_]+", _CAMEL_RE.sub(" ", path).casefold()) if t]


def _clean_url_path(path: str) -> str:
    """Percent-decode (twice), NFKC, drop invisible characters and ``;jsessionid``-style matrix params."""
    for _ in range(2):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    path = unicodedata.normalize("NFKC", path)
    path = "".join(c for c in path if unicodedata.category(c) != "Cf")
    return re.sub(r";[^/]*", "", path)


def is_commerce_url(url: str | None, broad: bool = False, _depth: int = 0) -> bool:
    """True when a URL looks transactional.

    By default a URL counts only when it has a transactional shape: a ``checkout.*`` style
    host, a ``/checkout`` (or ``/place-order``, ...) segment, ``/cart/confirm``,
    ``/order/place``, or a first segment such as ``/pay``, ``/payment``, ``/billing``,
    ``/subscribe`` or ``/donate`` that is alone, followed by an id, or followed by an action
    (``/payment/confirm``). ``/wiki/Payment``, ``/help/payment-methods`` or ``/subscriptions``
    do not match. With ``broad=True`` any path token such as "payment" or "donation" matches
    (used for form actions, where the URL is the submit target). The path is percent-decoded
    first (``/%63heckout``) and matrix parameters are dropped (``/checkout;jsessionid=1``). A
    ``checkout`` segment must be the first segment, the last one, or follow a shop-like segment
    (``/cart/checkout``), so ``/blog/checkout/our-launch`` does not match. ``next`` / ``return`` /
    ``redirect`` style query values (``?next=/checkout``) are checked as URLs of their own.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    raw_host = parts.hostname or ""
    host = (canonical_host(raw_host) or raw_host.lower()).rstrip(".")
    if not broad and any(host == d or host.endswith("." + d) for d in _CONTENT_HOSTS):
        return False
    if parts.fragment and re.match(r"^!?/", parts.fragment):  # hash-routed apps: /app#/checkout
        frag = parts.fragment.lstrip("!")
        path, _, query = frag.partition("?")
        if is_commerce_url(urlunsplit((parts.scheme or "https", parts.netloc, path, query, "")), broad, _depth):
            return True
    if host in _URL_COMMERCE_HOSTS or (host.split(".")[0] in _URL_HOST_LABELS and host.count(".") >= 2):
        return True
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        k, v = k.casefold(), v.strip()
        if k in _URL_STEP_KEYS and (v.casefold() in _URL_STEP_VALUES or (k.startswith("checkout") and v)):
            return True
        if k in _URL_REDIRECT_KEYS and _depth == 0 and v.startswith(("/", "http")):
            target = v if not v.startswith("/") else urlunsplit((parts.scheme or "https", parts.netloc, v, "", ""))
            if is_commerce_url(target, broad, _depth + 1):
                return True
    clean = _clean_url_path(parts.path or "")
    tokens = _path_tokens(clean)
    if not tokens or any(t in _URL_NEGATIVE_TOKENS for t in tokens):
        return False
    if any(pair in _URL_BIGRAMS for pair in zip(tokens, tokens[1:], strict=False)):
        return True
    if broad:
        return any(t in _URL_TOKENS for t in tokens)
    segments = [_PAGE_EXT_RE.sub("", seg) for seg in clean.split("/") if seg]
    if segments and _LOCALE_RE.match(segments[0].casefold()):
        segments = segments[1:]
    joined = ["".join(_path_tokens(seg)) for seg in segments]
    last = len(joined) - 1
    for i, j in enumerate(joined):
        if (j in _URL_CHECKOUT_SEGMENTS or _URL_CHECKOUT_STEP_RE.match(j)) and (
                i in (0, last) or joined[i - 1] in _URL_SHOP_PRECEDERS or joined[i - 1].isdigit()):
            return True
    if not joined or joined[0] not in _URL_ROOT_SEGMENTS:
        return False
    rest = joined[1:]
    if not rest:
        return True
    if joined[0] == "subscribe":  # /subscribe/pro, /subscribe/plan/annual, ...
        return len(rest) <= 3
    return len(rest) == 1 and (rest[0] in _URL_ROOT_ACTIONS or bool(_ID_RE.match(segments[1].casefold())))


_TARGET_DEPTH = 16  # ancestor levels inspected for link/form destinations on a click


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


def _click_chain(node: Any, limit: int = 16) -> list[Any]:
    """``node`` followed by its ancestors, nearest first (at most ``limit`` elements in all)."""
    out: list[Any] = []
    cur = node
    while cur is not None and len(out) < limit:
        out.append(cur)
        cur = getattr(cur, "parent_node", None)
    return out


def _label_chain(node: Any, limit: int = 16) -> list[Any]:
    """The elements whose labels describe what a click on ``node`` does: the node itself and, when it
    is a child of a link/button (``<span>`` or ``<img>`` inside ``<button>``), its ancestors up to and
    including the nearest interactive one. Never reaches past it, so a page-wide wrapper's text is not
    mistaken for the click target's label."""
    out: list[Any] = []
    for cur in _click_chain(node, limit):
        out.append(cur)
        if _is_clickable_control(cur):
            return out
    return out[:1]  # no interactive ancestor: only the node's own label counts


def _in_form_submit(node: Any) -> bool:
    """A submit control that sits inside a <form> (ambiguous when its label cannot be trusted), also
    when the click lands on a child of such a control."""
    return any(_is_submit_like(n) and _ancestor_form(n) is not None for n in _label_chain(node))


def _is_clickable_control(node: Any) -> bool:
    a = _attrs(node)
    return _tag(node) in ("button", "a") or str(a.get("role", "")).lower() in ("button", "link") or (
        _tag(node) == "input" and str(a.get("type", "")).lower() in _SUBMIT_TYPES
    )


def attr_is_commerce(value: Any, patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> bool:
    """Like :func:`is_commerce_label` for machine-written attributes (id, name, data-testid, ...):
    ``btn-checkout`` or ``checkout-form`` also count, because nobody reads those as prose."""
    if not isinstance(value, str) or not value.strip():
        return False
    if is_commerce_label(value, patterns):
        return True
    words = normalize_text(value).split()
    return (len(words) <= 4 and ("checkout" in words or "check out" in " ".join(words))
            and words[-1] not in _NOUN_MODIFIERS)


def form_looks_transactional(node: Any) -> bool:
    """True when the enclosing <form> of ``node`` has a transactional action/id/name."""
    form = _ancestor_form(node)
    if form is None:
        return False
    fa = _attrs(form)
    if is_commerce_url(fa.get("action"), broad=True):
        return True
    return any(attr_is_commerce(fa.get(k)) for k in ("id", "name", "aria-label"))


def element_risk(node: Any, page_url: str | None, label: str | None,
                 patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> str | None:
    """Return a reason string when a click target looks transactional, else None."""
    if is_commerce_label(label, patterns):
        return f"label {label!r} looks like a purchase/commerce action"
    # Classify each label part on its own: "Buy | help details" must not be hidden by the info
    # words of a neighbouring title/aria-label.
    for part in label_parts(node):
        if is_commerce_label(part, patterns):
            return f"label {part!r} looks like a purchase/commerce action"
    a = _attrs(node)
    for key in ("href", "formaction", "data-href", "data-url"):
        if is_commerce_url(a.get(key), broad=key == "formaction"):
            return f"{key} {a.get(key)!r} points to a checkout/payment URL"
    for key in ("name", "id", "aria-label", "title", "value", "data-testid", "data-action"):
        if attr_is_commerce(a.get(key), patterns):
            return f"attribute {key}={a.get(key)!r} looks like a purchase/commerce action"
    chain = _label_chain(node)
    for anc in _click_chain(node)[1:]:  # a click on a child activates the link/form it sits in
        aa = _attrs(anc)
        for key in ("href", "formaction", "data-href", "data-url"):
            if is_commerce_url(aa.get(key), broad=key == "formaction"):
                return f"ancestor {key} {aa.get(key)!r} points to a checkout/payment URL"
        if _tag(anc) == "form" and is_commerce_url(aa.get("action"), broad=True):
            return f"ancestor form action {aa.get('action')!r} points to a checkout/payment URL"
    for anc in chain[1:]:
        for part in label_parts(anc):
            if is_commerce_label(part, patterns):
                return f"enclosing control label {part!r} looks like a purchase/commerce action"
        aa = _attrs(anc)
        for key in ("name", "id", "aria-label", "title", "value", "data-testid", "data-action"):
            if attr_is_commerce(aa.get(key), patterns):
                return f"enclosing control attribute {key}={aa.get(key)!r} looks like a purchase/commerce action"
    if any(_is_submit_like(n) and form_looks_transactional(n) for n in chain):
        return "submit button inside a checkout/payment/order form"
    if is_commerce_url(page_url) and any(_is_clickable_control(n) for n in chain):
        return "clickable control on a checkout/payment page"
    if not label and is_commerce_url(page_url):
        return "unlabeled control on a checkout/payment page"
    return None


def label_parts(node: Any) -> list[str]:
    """The separate human-readable strings of a node (accessible name, aria-label, title, value, alt,
    name, text, node value), whitespace-collapsed and de-duplicated. Never raises."""
    if node is None:
        return []
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
        return list(dict.fromkeys(" ".join(p.split()) for p in parts))
    except Exception:  # pragma: no cover - defensive
        return []


def element_label(node: Any, max_len: int = 200) -> str | None:
    """Best-effort human label for a browser-use DOM node (never raises)."""
    parts = label_parts(node)
    return (" | ".join(parts)[:max_len] or None) if parts else None


_ENTER_TOKENS = frozenset({"enter", "return", "numpadenter", "\\n", "\\r"})
_SPACE_TOKENS = frozenset({"space", "spacebar"})


def _keys_kind(keys: Any) -> str | None:
    """Classify a send_keys string: "enter" (submits), "space" (activates a focused button) or None."""
    if not isinstance(keys, str):
        return None
    if "\n" in keys or "\r" in keys or "\\n" in keys or "\\r" in keys:
        return "enter"
    toks = [t.strip().lower() for t in re.split(r"[+\s]+", keys) if t.strip()]
    if any(t in _ENTER_TOKENS for t in toks):
        return "enter"
    if any(t in _SPACE_TOKENS for t in toks) or (not toks and " " in keys):
        return "space"
    return None


def _keys_press_enter(keys: Any) -> bool:
    return _keys_kind(keys) == "enter"


_TRAILING_NEWLINE_RE = re.compile(r"[\r\n]\s*\Z")

# --- Navigation guard --------------------------------------------------------------------
_OPAQUE_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.IGNORECASE)
_HOSTPORT_RE = re.compile(r"^\d+(?:[/?#]|$)")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".localdomain", ".home.arpa", ".intranet")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _parse_loose_ipv4(host: str) -> ipaddress.IPv4Address | None:
    """Parse the legacy IPv4 spellings browsers accept (decimal, hex, octal, short forms)."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or any(not p for p in parts):
        return None
    nums: list[int] = []
    for p in parts:
        try:
            if p.lower().startswith("0x"):
                nums.append(int(p[2:] or "0", 16))
            elif len(p) > 1 and p.startswith("0"):
                nums.append(int(p, 8))
            elif p.isdigit():
                nums.append(int(p))
            else:
                return None
        except ValueError:
            return None
    *head, last = nums
    if any(n > 255 for n in head) or last >= 256 ** (4 - len(head)):
        return None
    value = last
    for i, n in enumerate(head):
        value |= n << (8 * (3 - i))
    return ipaddress.IPv4Address(value)


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    h = host.strip().lower().rstrip(".").strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        return _parse_loose_ipv4(h)


def _host_is_local(host: str) -> bool:
    h = host.strip().lower().rstrip(".")
    if not h:
        return True
    if h == "localhost" or h.endswith(_LOCAL_SUFFIXES):
        return True
    ip = _parse_ip(h)
    if ip is None:
        return "." not in h and ":" not in h  # single-label names (intranet, printer) resolve on the LAN
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:  # 64:ff9b::/96 embeds an IPv4 address in the low 32 bits
            ip = ipaddress.IPv4Address(ip.packed[-4:])
    return not ip.is_global or ip.is_multicast


def navigation_candidate(dest: str) -> tuple[str | None, str | None]:
    """Normalise ``dest`` the way Chrome does. Returns ``(candidate_url, denial)``.

    Backslashes become slashes, control characters are dropped, extra slashes after the scheme
    are collapsed and a schemeless address counts as ``https://``. ``candidate_url`` is None for
    ``about:blank`` (always allowed) and when ``denial`` is set (non-http(s) scheme or unparsable).
    """
    raw = "".join(c for c in dest if unicodedata.category(c) != "Cc").strip().replace("\\", "/")
    if not raw or raw.lower() in ("about:blank", "about:blank#"):
        return None, None
    m = _OPAQUE_SCHEME_RE.match(raw)
    if m and not _HOSTPORT_RE.match(raw[m.end():]):
        scheme = m.group(1).lower()
        if scheme not in ("http", "https"):
            return None, (f"Blocked by safety policy: {scheme}: URLs are not allowed. "
                          "Only http(s) websites can be opened; choose another page.")
        candidate = f"{scheme}://" + raw[m.end():].lstrip("/")
    elif raw.startswith("//"):
        candidate = "https:" + raw
    else:
        candidate = "https://" + raw  # schemeless or host:port
    try:
        parts = urlsplit(candidate)
        raw_host = parts.hostname
        port = parts.port
    except ValueError:
        raw_host, parts, port = None, None, None
    if not raw_host or parts is None:
        return None, "Blocked by safety policy: the address could not be parsed. Choose another page."
    host = canonical_host(raw_host)
    if host is None:
        return None, "Blocked by safety policy: the address has an invalid or obfuscated host name. Choose another page."
    netloc = (f"[{host}]" if ":" in host else host) + (f":{port}" if port is not None else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment)), None


def navigation_host(dest: str) -> str | None:
    """Hostname Chrome would navigate to for ``dest`` (None when none can be determined)."""
    candidate, _ = navigation_candidate(dest)
    if candidate is None:
        return None
    try:
        return urlsplit(candidate).hostname
    except ValueError:
        return None


def navigation_denial(dest: str, allow_local_network: bool = False) -> str | None:
    """Return a denial message when ``dest`` must never be opened, else None.

    Non-http(s) schemes (chrome://, file:, data:, javascript:, view-source:, devtools://, about:
    other than about:blank, ...) are always denied. Loopback, private, link-local and other
    non-public addresses (IP literals, localhost, ``*.local``-style suffixes and single-label
    names; no DNS lookups) are denied unless ``allow_local_network`` is True, which also lifts the
    blanket ban on IP-address URLs.
    """
    candidate, denial = navigation_candidate(dest)
    if denial is not None:
        return denial
    if candidate is None:
        return None
    host = urlsplit(candidate).hostname or ""  # already canonical
    if not allow_local_network:
        if _parse_ip(host) is not None:
            return (f"Blocked by safety policy: IP-address URLs ({host}) are blocked by this agent's safety "
                    "policy; use a hostname, or set allow_local_network=True / LBA_ALLOW_LOCAL_NETWORK=1.")
        if _host_is_local(host):
            return (f"Blocked by safety policy: {host} is a local or private network address. "
                    "Only public websites can be opened; choose another page.")
    return None


# --- Live element read -------------------------------------------------------------------
# The DOM snapshot the gate reads is cached from when the agent last looked at the page, so a
# page script can swap a harmless label for a buy handler before the click lands. Just before a
# click we re-read the element's current tag/attributes/text over CDP (DOM.resolveNode +
# Runtime.callFunctionOn on its backend node id). A page can still change the element in the
# milliseconds between this read and browser-use dispatching the click; closing that window
# would need browser-use itself to re-check inside the click.
_LIVE_JS = """function() {
  const el = this;
  const names = (e) => (e && e.getAttributeNames) ? e.getAttributeNames() : [];
  const attrs = (e) => { const o = {}; for (const n of names(e)) o[n] = String(e.getAttribute(n)).slice(0, 300); return o; };
  const a = attrs(el);
  const t = String(el.type || '').toLowerCase();
  if (typeof el.value === 'string' && el.value && ['submit', 'button', 'image', 'reset'].includes(t)) a.value = el.value.slice(0, 300);
  const f = el.closest ? el.closest('form') : null;
  const txt = String(el.innerText || el.textContent || '').slice(0, 300);
  const chain = [];
  const keep = ['href', 'formaction', 'data-href', 'data-url', 'action', 'type', 'role', 'aria-label', 'title', 'value',
                'name', 'id', 'data-testid', 'data-action'];
  const interactive = (e) => {
    const g = String(e.tagName || '').toLowerCase(), r = String(e.getAttribute && e.getAttribute('role') || '').toLowerCase();
    const ty = String(e.getAttribute && e.getAttribute('type') || '').toLowerCase();
    return g === 'a' || g === 'button' || r === 'button' || r === 'link' || (g === 'input' && ['submit', 'image', 'button'].includes(ty));
  };
  let p = el.parentElement;
  let seen = interactive(el);
  for (let i = 0; p && i < 16; i++, p = p.parentElement) {
    const o = {}; for (const k of keep) if (p.hasAttribute && p.hasAttribute(k)) o[k] = String(p.getAttribute(k)).slice(0, 2000);
    const item = {tag: String(p.tagName || '').toLowerCase(), attrs: o};
    if (!seen) { item.text = String(p.innerText || p.textContent || '').slice(0, 300); seen = interactive(p); }
    chain.push(item);
  }
  return JSON.stringify({tag: String(el.tagName || '').toLowerCase(), attrs: a, text: txt, form: f ? attrs(f) : null, chain: chain});
}"""


def _walk_up(node: Any):
    cur = node
    for _ in range(40):
        if cur is None:
            return
        yield cur
        cur = getattr(cur, "parent_node", None)


def _node_from_live(data: dict[str, Any]) -> Any:
    form = None
    if isinstance(data.get("form"), dict):
        form = SimpleNamespace(node_name="form", attributes=data["form"], ax_node=None, node_value="",
                               parent_node=None, get_all_children_text=lambda: "")
    text = str(data.get("text") or "")
    parent = form
    chain = data.get("chain")
    if isinstance(chain, list):  # ancestors, nearest first; rebuild the parent links (closest form kept)
        parent = None
        for item in reversed([c for c in chain if isinstance(c, dict)]):
            item_text = str(item.get("text") or "")
            parent = SimpleNamespace(node_name=str(item.get("tag") or ""), attributes=dict(item.get("attrs") or {}),
                                     ax_node=None, node_value="", parent_node=parent,
                                     get_all_children_text=lambda t=item_text: t)
        if form is not None and not any(_tag(c) == "form" for c in _walk_up(parent)):
            form.parent_node = parent
            parent = form
    return SimpleNamespace(node_name=str(data.get("tag") or ""), attributes=dict(data.get("attrs") or {}),
                           ax_node=None, node_value="", parent_node=parent, get_all_children_text=lambda: text)


async def _read_live_object(cdp: Any, object_id: str) -> Any:
    res = await cdp.cdp_client.send.Runtime.callFunctionOn(
        params={"objectId": object_id, "functionDeclaration": _LIVE_JS, "returnByValue": True},
        session_id=cdp.session_id)
    return _node_from_live(json.loads(res["result"]["value"]))


_NON_COMMERCE_INPUT_TYPES = frozenset({
    "checkbox", "radio", "text", "search", "email", "tel", "url", "password", "number", "date", "range",
    "color", "file", "datetime-local", "month", "week", "time"})


def _commerce_capable(node: Any) -> bool:
    """False only for elements that clearly cannot trigger a purchase (checkbox, text field, ...).

    Buttons, links, submit/button/image inputs, role=button/link elements and anything unknown count
    as capable, so a failed live re-read on them fails closed.
    """
    try:
        tag = str(getattr(node, "node_name", "") or "").lower()
        attrs = getattr(node, "attributes", None) or {}
        role = str(attrs.get("role", "")).lower()
        if role in ("button", "link", "menuitem"):
            return True
        if tag in ("input", "textarea", "select"):
            return tag == "input" and str(attrs.get("type", "text")).lower() not in _NON_COMMERCE_INPUT_TYPES
        if tag in ("div", "span", "p", "li", "label"):
            style = str(attrs.get("style", "")).replace(" ", "").lower()
            snap = getattr(node, "snapshot_node", None)
            return (any(k in attrs for k in ("onclick", "onmousedown", "onmouseup", "tabindex", "jsaction", "ng-click",
                                             "@click", "v-on:click", "data-onclick"))
                    or "cursor:pointer" in style or getattr(snap, "is_clickable", None) is True)
        return True
    except Exception:  # pragma: no cover - defensive
        return True


_TEXT_INPUT_TYPES = frozenset({"text", "search", "email", "tel", "url", "password", "number"})


def _is_text_field(node: Any) -> bool:
    """True for a text-entry element (textarea, contenteditable, or input of a text type)."""
    try:
        tag = str(getattr(node, "node_name", "") or "").lower()
        attrs = getattr(node, "attributes", None) or {}
        if tag == "textarea":
            return True
        if "contenteditable" in attrs and str(attrs.get("contenteditable", "")).lower() in ("", "true", "plaintext-only"):
            return True
        return tag == "input" and str(attrs.get("type", "text")).lower() in _TEXT_INPUT_TYPES
    except Exception:  # pragma: no cover - defensive
        return False


# Actions that cannot move keyboard focus off a text field.
_FOCUS_PRESERVING = frozenset({
    "scroll", "wait", "extract", "extract_content", "screenshot", "find_text", "scroll_to_text", "done",
    "get_dropdown_options", "read_file", "write_file", "replace_file", "todo", "save_as_pdf",
})

# Schemes a link or form must never take the browser to, even though they are not http(s).
_DANGEROUS_SCHEMES = frozenset({
    "chrome", "chrome-extension", "chrome-untrusted", "chrome-search", "chrome-error", "devtools", "edge",
    "brave", "file", "view-source", "about", "filesystem", "ftp",
})


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
        allow_local_network: bool = False,
        approval_timeout_s: float | None = 120.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lba_patterns = tuple(patterns)
        self._lba_gate = gate_commerce_clicks
        self._lba_approval = approval
        self._lba_allow_evaluate = allow_evaluate
        self._lba_allow_local = allow_local_network
        self._lba_approval_timeout = approval_timeout_s if approval_timeout_s and approval_timeout_s > 0 else None
        self._lba_blocked = frozenset(
            SAFETY_DEFAULTS | {n for d in blocked_domains if (n := try_normalize_blocked_domain(d))})
        self._lba_warned_no_live = False
        self._lba_text_focus = False  # last known focused element was a text field
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
        timed_out = False
        desc = req.action_name + (f" on {req.element_label!r}" if req.element_label else "") + (
            f" at {req.url}" if req.url else "")
        if self._lba_approval is not None:
            task: asyncio.Future[Any] | None = None
            try:
                task = asyncio.ensure_future(self._lba_approval(req))
                if self._lba_approval_timeout:
                    await asyncio.wait({task}, timeout=self._lba_approval_timeout)
                else:
                    await asyncio.wait({task})
                if not task.done():  # our own timeout; a TimeoutError raised by the callback lands below
                    logger.warning("approval callback timed out after %ss, denying", self._lba_approval_timeout)
                    timed_out = True
                else:
                    res = task.result()
                    # Only an explicit True (or {"approved": True}) counts; "no", 1 or a Mock do not.
                    approved = res is True or (isinstance(res, dict) and res.get("approved") is True)
            except asyncio.CancelledError:
                self.blocked_actions.append(f"{desc} (run stopped while awaiting approval)")
                raise
            except Exception as e:
                logger.warning("approval callback failed, denying: %s", e)
            finally:
                if task is not None and not task.done():
                    task.cancel()
        if approved:
            return None
        self.blocked_actions.append(desc)
        why = f" ({req.reason})" if req.reason else ""
        if timed_out:
            return ActionResult(error=(
                f"Approval for {desc}{why} timed out after {self._lba_approval_timeout:g}s and was treated as "
                "denied. Do not retry it; continue the task without this step, or report what you found."))
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
                f"Blocked by safety policy: {desc}{why} looks like a purchase/irreversible action. "
                "This step needs the user's approval, which was not given. Do not retry it; continue the task "
                "without it, or report what you found."
            )
        )

    def _lba_dest_denial(self, dest: str) -> str | None:
        """Hard-denial message for navigating to ``dest`` (blocked domain, scheme, local network), else None."""
        denial = navigation_denial(dest, self._lba_allow_local)
        if denial is not None:
            return denial
        host = navigation_host(dest)
        if host_is_blocked(host, self._lba_blocked):
            return (f"Blocked by safety policy: {host} is a blocked domain. "
                    "Do not navigate there; choose another site.")
        return None

    def _lba_link_denial(self, href: Any) -> str | None:
        """Like _lba_dest_denial for a link/form target found on an element. Relative URLs stay on the
        current (already allowed) site; javascript:, mailto:, tel:, data: and blob: are not navigations."""
        if not isinstance(href, str):
            return None
        raw = "".join(c for c in href if unicodedata.category(c) != "Cc").strip().replace("\\", "/")
        if not raw:
            return None
        m = _OPAQUE_SCHEME_RE.match(raw)
        scheme = m.group(1).lower() if m else ""
        if scheme in _DANGEROUS_SCHEMES and not raw.lower().startswith("about:blank"):
            return (f"Blocked by safety policy: {scheme}: URLs are not allowed. "
                    "Only http(s) websites can be opened; choose another page.")
        if scheme in ("http", "https") or raw.startswith("//"):
            return self._lba_dest_denial(raw)
        return None

    def _lba_blocked_navigation(self, action: Any) -> ActionResult | None:
        """Hard-deny navigation (including new-tab) to a blocked domain, a non-http(s) scheme or (unless
        allowed) a local/private address; no approval can lift it."""
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
            denial = self._lba_dest_denial(dest)
            if denial is not None:
                self.blocked_actions.append(f"{name} at {dest}")
                return ActionResult(error=denial)
        return None

    @staticmethod
    def _lba_targets(node: Any) -> list[str]:
        """href / formaction / data-href / form action values on a click target and on its ancestors.

        A click on a child (``<span>``, ``<img>``) of a link or button activates it, so the chain is
        walked up to ``_TARGET_DEPTH`` levels; a submit control found on the way also contributes its form's
        ``action``.
        """
        out: list[str] = []
        cur = node
        for _ in range(_TARGET_DEPTH):
            if cur is None:
                break
            for key in ("href", "formaction", "data-href"):
                v = _attrs(cur).get(key)
                if isinstance(v, str) and v.strip():
                    out.append(v)
            if _tag(cur) == "form":
                v = _attrs(cur).get("action")
                if isinstance(v, str) and v.strip():
                    out.append(v)
            elif _is_submit_like(cur):
                form = _ancestor_form(cur)
                v = _attrs(form).get("action") if form is not None else None
                if isinstance(v, str) and v.strip():
                    out.append(v)
            cur = getattr(cur, "parent_node", None)
        return out

    async def _lba_blocked_click(self, action: Any, browser_session: Any) -> ActionResult | None:
        """Hard-deny a click on a link/button whose target is a blocked domain, a forbidden scheme or a
        local address (a click navigates just like a navigate action)."""
        try:
            dumped = action.model_dump(exclude_unset=True)
        except Exception:
            return None
        for name, params in dumped.items():
            if name not in CLICK_ACTIONS or not isinstance(params, dict):
                continue
            node, ok = await self._lba_node(params, browser_session)
            if not ok:
                continue
            nodes = [node]
            state, live = await self._lba_live(node, browser_session)
            if state == "ok":
                nodes.append(live)
            for n in nodes:
                for target in self._lba_targets(n):
                    denial = self._lba_link_denial(target)
                    if denial is not None:
                        self.blocked_actions.append(f"{name} on a link to {redact_url(target)}")
                        return ActionResult(error=denial)
        return None

    async def act(self, action: Any, browser_session: Any, *args: Any, **kwargs: Any) -> ActionResult:
        denied_nav = self._lba_blocked_navigation(action)
        if denied_nav is not None:
            return denied_nav
        denied_click = await self._lba_blocked_click(action, browser_session)
        if denied_click is not None:
            return denied_click
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

    async def _lba_live(self, node: Any, browser_session: Any) -> tuple[str, Any]:
        """Re-read ``node`` from the live page. Returns ("ok", node) | ("unavailable", None) | ("failed", None)."""
        backend_id = getattr(node, "backend_node_id", None)
        if not callable(getattr(browser_session, "cdp_client_for_node", None)) or not isinstance(backend_id, int):
            return "unavailable", None
        try:
            cdp = await browser_session.cdp_client_for_node(node)
            res = await cdp.cdp_client.send.DOM.resolveNode(
                params={"backendNodeId": backend_id}, session_id=cdp.session_id)
            return "ok", await _read_live_object(cdp, res["object"]["objectId"])
        except Exception as e:
            logger.debug("live element read failed: %s", e)
            return "failed", None

    async def _lba_live_focused(self, browser_session: Any) -> tuple[str, Any]:
        """Read the currently focused element (same return shape as _lba_live)."""
        getter = getattr(browser_session, "get_or_create_cdp_session", None)
        if not callable(getter):
            return "unavailable", None
        try:
            cdp = await getter(None, focus=False)
            res = await cdp.cdp_client.send.Runtime.evaluate(
                params={"expression": "document.activeElement"}, session_id=cdp.session_id)
            object_id = res["result"].get("objectId")
            if not object_id:
                return "failed", None
            return "ok", await _read_live_object(cdp, object_id)
        except Exception as e:
            logger.debug("focused element read failed: %s", e)
            return "failed", None

    async def _lba_classify_click(self, name: str, params: dict[str, Any], browser_session: Any) -> ActionRequest | None:
        node, ok = await self._lba_node(params, browser_session)
        self._lba_text_focus = ok and _is_text_field(node)
        url, url_ok = await self._lba_url(browser_session)
        label = element_label(node) if ok else None
        if not ok:
            reason: str | None = "target element could not be resolved (failing closed)"
        else:
            ambiguous = not label or _in_form_submit(node)
            try:
                reason = element_risk(node, url, label, self._lba_patterns)
            except Exception as e:  # pragma: no cover - defensive
                reason = f"element inspection failed ({e}); failing closed"
            state, live = await self._lba_live(node, browser_session)
            if state == "ok":
                live_label = element_label(live)
                live_reason = element_risk(live, url, live_label, self._lba_patterns)
                if live_reason is not None and reason is None:
                    reason, label = f"live page element changed: {live_reason}", live_label
                ambiguous = ambiguous or not live_label or _in_form_submit(live)
            elif state == "failed" and reason is None and (
                    ambiguous or any(_commerce_capable(n) for n in _label_chain(node)) or is_commerce_url(url)):
                reason = "live element could not be re-read, so its current label is unknown (failing closed)"
            elif state == "unavailable" and not self._lba_warned_no_live:
                self._lba_warned_no_live = True
                logger.warning("live element re-read is unavailable (no CDP session); commerce gating uses the "
                               "cached page snapshot only")
            if reason is None and not url_ok and ambiguous:
                reason = "page URL could not be read for an unlabeled/submit control (failing closed)"
        if reason is None:
            return None
        return ActionRequest(action_name=name, params=dict(params), element_label=label, url=url, reason=reason)

    async def _lba_classify(self, name: str, params: dict[str, Any], browser_session: Any) -> ActionRequest | None:
        """Return an ActionRequest when the action must be approved, else None."""
        if name not in CLICK_ACTIONS | KEY_ACTIONS | INPUT_ACTIONS | _FOCUS_PRESERVING:
            self._lba_text_focus = False  # navigation, tab switches, ... move focus off the field
        if name in CLICK_ACTIONS:
            return await self._lba_classify_click(name, params, browser_session)
        if name in UPLOAD_ACTIONS:
            path = params.get("path") or params.get("file_path")
            url, _ = await self._lba_url(browser_session)
            shown = os.path.basename(str(path)) if path else None
            return ActionRequest(action_name=name, params=dict(params), element_label=shown, url=url,
                                 reason="uploads a local file to the website")
        if name in SELECT_ACTIONS:
            self._lba_text_focus = False
            choice = params.get("text")
            if isinstance(choice, str) and is_commerce_label(choice, self._lba_patterns):
                url, _ = await self._lba_url(browser_session)
                return ActionRequest(action_name=name, params=dict(params), element_label=choice, url=url,
                                     reason=f"dropdown option {choice!r} looks like a purchase/commerce action")
            return None
        if name in NAVIGATE_ACTIONS:
            dest = params.get("url")
            candidate = navigation_candidate(dest)[0] if isinstance(dest, str) else None
            if candidate is not None and is_commerce_url(candidate):
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
            keys = params.get("keys")
            kind = _keys_kind(keys)
            if isinstance(keys, str) and re.search(r"(?i)\btab\b", keys):
                self._lba_text_focus = False
            if kind is None:
                return None
            # Enter and Space both activate a focused button, so both check the live focused element.
            url, ok = await self._lba_url(browser_session)
            state, focused = await self._lba_live_focused(browser_session)
            verb = "Enter" if kind == "enter" else "Space"
            label: str | None = None
            reason: str | None = None
            if state == "ok":
                label = element_label(focused)
                risk = element_risk(focused, url, label, self._lba_patterns)
                if risk is not None:
                    reason = f"{verb} pressed on a focused control: {risk}"
                elif kind == "enter" and form_looks_transactional(focused):
                    reason = "Enter pressed in a checkout/payment form"
                self._lba_text_focus = _is_text_field(focused)
            elif state == "failed" and not self._lba_text_focus:
                reason = f"{verb} pressed but the focused element could not be read (failing closed)"
            if reason is None and kind == "enter":
                if not ok:
                    reason = "page URL could not be read (failing closed)"
                elif is_commerce_url(url):
                    reason = "Enter pressed on a checkout/payment page"
            elif reason is None and state != "ok" and is_commerce_url(url) and not self._lba_text_focus:
                reason = "Space pressed on a checkout/payment page (focused element unknown)"
            if reason is None:
                return None
            return ActionRequest(action_name=name, params=dict(params), element_label=label or str(keys),
                                 url=url, reason=reason)
        if name in INPUT_ACTIONS:
            text = params.get("text")
            node, ok = await self._lba_node(params, browser_session)
            self._lba_text_focus = ok and _is_text_field(node)
            if not isinstance(text, str) or not _TRAILING_NEWLINE_RE.search(text):
                return None
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
