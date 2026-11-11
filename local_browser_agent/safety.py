"""Safety policy primitives: default blocked domains, guardrail prompt, commerce click gate."""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

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

# Click-type tool actions whose target is an element index.
CLICK_ACTIONS = frozenset({"click", "click_element_by_index", "click_element"})


@dataclass
class ActionRequest:
    """Describes a gated action for an approval callback."""

    action_name: str
    params: dict[str, Any] = field(default_factory=dict)
    element_label: str | None = None
    url: str | None = None


ApprovalCallback = Callable[[ActionRequest], Awaitable[bool]]


def is_commerce_label(label: str | None, patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS) -> bool:
    """True when ``label`` contains any pattern as a whole-word phrase (case-insensitive).

    Word boundaries avoid substring false positives ("payment history" does not
    match "pay"; "repay" does not match "pay"; "Pay now" and "Pay" do).
    "payment" is intentionally not a pattern, so account/payment-settings links pass.
    """
    if not label:
        return False
    text = " ".join(label.lower().split())
    for p in patterns:
        p = " ".join(p.lower().split())
        if not p:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text):
            return True
    return False


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


class GuardedTools(Tools):
    """Tools whose click actions are gated when the target looks like a commerce CTA."""

    def __init__(
        self,
        *args: Any,
        patterns: Iterable[str] = DEFAULT_COMMERCE_PATTERNS,
        gate_commerce_clicks: bool = True,
        approval: ApprovalCallback | None = None,
        blocked_log: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._lba_patterns = tuple(patterns)
        self._lba_gate = gate_commerce_clicks
        self._lba_approval = approval
        self.blocked_actions: list[str] = blocked_log if blocked_log is not None else []

    async def _lba_resolve(self, params: dict[str, Any], browser_session: Any) -> tuple[str | None, str | None]:
        """Return (label, url) for the click target; both best-effort."""
        label = None
        url = None
        try:
            index = params.get("index")
            if index is not None:
                node = await browser_session.get_element_by_index(index)
                label = element_label(node)
        except Exception as e:
            logger.debug("element label lookup failed: %s", e)
        try:
            url = await browser_session.get_current_page_url()
        except Exception:
            url = None
        return label, url

    async def act(self, action: Any, browser_session: Any, *args: Any, **kwargs: Any) -> ActionResult:
        if self._lba_gate:
            try:
                dumped = action.model_dump(exclude_unset=True)
            except Exception:
                dumped = {}
            for name, params in dumped.items():
                if name not in CLICK_ACTIONS or not isinstance(params, dict):
                    continue
                label, url = await self._lba_resolve(params, browser_session)
                if not is_commerce_label(label, self._lba_patterns):
                    continue
                approved = False
                if self._lba_approval is not None:
                    try:
                        approved = bool(await self._lba_approval(
                            ActionRequest(action_name=name, params=dict(params), element_label=label, url=url)
                        ))
                    except Exception as e:
                        logger.warning("approval callback failed, denying: %s", e)
                        approved = False
                if not approved:
                    desc = f"{name} on {label!r}" + (f" at {url}" if url else "")
                    self.blocked_actions.append(desc)
                    return ActionResult(
                        error=(
                            f"Blocked by safety policy: {desc} looks like a purchase/commerce action "
                            "and was not approved. Do not retry; finish with success=False and report it."
                        )
                    )
        return await super().act(action, browser_session, *args, **kwargs)
