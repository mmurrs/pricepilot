"""
Hermes — intent parser + tool router.

Takes a free-form user message (Telegram text), asks Claude to choose ONE
tool from TOOL_SCHEMAS (find_cheapest_product or find_cheapest_flight),
dispatches, and returns a structured response the caller can render.

No anthropic SDK dependency — uses urllib directly so it runs in any
sandbox without `pip install`. Matches the pattern in projects/senso/run.py.

Env:
  ANTHROPIC_API_KEY — required for live routing.
  HERMES_MODEL      — optional override; defaults to claude-sonnet-4-6.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

# Make search/ importable when running from repo root.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from search.tools import (  # noqa: E402
    TOOL_SCHEMAS,
    find_cheapest_product,
    find_cheapest_flight,
    CheapestOfferResponse,
    Offer,
)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-6"

ResponseKind = Literal["offers", "error", "clarification"]


@dataclass
class HermesResponse:
    kind: ResponseKind
    text: str                                 # Telegram-ready
    tool: Optional[str] = None                # 'find_cheapest_product' | 'find_cheapest_flight'
    spec: dict[str, Any] = field(default_factory=dict)
    offers: list[dict[str, Any]] = field(default_factory=list)
    best: Optional[dict[str, Any]] = None
    missing_sources: list[dict[str, Any]] = field(default_factory=list)


_SYSTEM_PROMPT = (
    "You are Hermes, a price-finder agent. Parse the user's message and call "
    "exactly one tool.\n\n"
    "Tool selection:\n"
    "  - find_cheapest_flight — any travel intent: flights, fares, "
    "airline routes. Required: origin (IATA), destination (IATA), depart_date "
    "(YYYY-MM-DD). One-way only for now.\n"
    "  - find_cheapest_product — physical goods (shoes, electronics, etc). "
    "Required: brand, model, size.\n\n"
    "Rules:\n"
    "  - If the user gives a city name (e.g. 'New York'), use the most likely "
    "IATA code (JFK for New York, LAX for Los Angeles, ORD for Chicago, ...).\n"
    "  - If the user says 'next Friday' or similar relative date, compute the "
    "absolute YYYY-MM-DD against today's date provided in the user message.\n"
    "  - Never invent missing required fields. If the user hasn't given them, "
    "respond in plain text asking for what's missing — do not call any tool."
)


async def handle_message(
    text: str,
    *,
    user_id: str,
    today: Optional[str] = None,
    model: Optional[str] = None,
) -> HermesResponse:
    """
    Route a single inbound user message to a tool and execute it.
    `today` (YYYY-MM-DD) anchors relative-date parsing — pass the bot's
    current date so the model can resolve 'next Friday' etc.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return HermesResponse(
            kind="error",
            text="Hermes is offline — ANTHROPIC_API_KEY is not set.",
        )

    user_payload = text if not today else f"[today={today}] {text}"

    body = {
        "model": model or os.environ.get("HERMES_MODEL", DEFAULT_MODEL),
        "max_tokens": 1024,
        "system": _SYSTEM_PROMPT,
        "tools": TOOL_SCHEMAS,
        "messages": [{"role": "user", "content": user_payload}],
    }

    try:
        response = await asyncio.to_thread(_post_anthropic, body, api_key)
    except RuntimeError as exc:
        return HermesResponse(kind="error", text=f"Claude API error: {exc}")

    tool_use = _first_tool_use(response)
    if tool_use is None:
        # Model declined to call a tool — likely a clarification ask.
        return HermesResponse(
            kind="clarification",
            text=_first_text(response) or "Need more details to search.",
        )

    spec = dict(tool_use.get("input") or {})
    spec.setdefault("user_id", user_id)
    tool_name = tool_use.get("name") or ""

    if tool_name == "find_cheapest_flight":
        result = await find_cheapest_flight(
            origin=spec.get("origin", ""),
            destination=spec.get("destination", ""),
            depart_date=spec.get("depart_date", ""),
            query=spec.get("query") or text,
            user_id=spec.get("user_id"),
        )
        return _format_flight_response(spec, result)

    if tool_name == "find_cheapest_product":
        result = await find_cheapest_product(
            brand=spec.get("brand", ""),
            model=spec.get("model", ""),
            size=spec.get("size"),
            color=spec.get("color"),
            condition=spec.get("condition", "new"),
            postal_code=spec.get("postal_code", "10001"),
            source_scope=spec.get("source_scope", "amazon"),
            query=spec.get("query") or text,
            user_id=spec.get("user_id"),
        )
        return _format_product_response(spec, result)

    return HermesResponse(
        kind="error",
        text=f"Unknown tool '{tool_name}' requested by model.",
    )


def _post_anthropic(body: dict[str, Any], api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code}: {body_text}") from exc


def _first_tool_use(response: dict[str, Any]) -> Optional[dict[str, Any]]:
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return block
    return None


def _first_text(response: dict[str, Any]) -> str:
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "").strip()
    return ""


def _format_flight_response(
    spec: dict[str, Any],
    result: CheapestOfferResponse,
) -> HermesResponse:
    origin = spec.get("origin", "?")
    destination = spec.get("destination", "?")
    depart = spec.get("depart_date", "?")

    if not result.all_offers:
        missing = ", ".join(
            f"{m.source}({m.reason})" for m in result.missing_sources
        ) or "no offers returned"
        return HermesResponse(
            kind="offers",
            tool="find_cheapest_flight",
            spec=spec,
            text=(
                f"No bookable {origin} → {destination} on {depart} right now. "
                f"Sources: {missing}."
            ),
            missing_sources=[asdict(m) for m in result.missing_sources],
        )

    lines = [f"Cheapest {origin} → {destination} on {depart}:"]
    medals = ["🥇", "🥈", "🥉"]
    for i, offer in enumerate(result.all_offers[:3]):
        prefix = medals[i] if i < len(medals) else "  "
        total = offer.total_price if offer.total_price is not None else offer.price
        title = offer.title or offer.source
        lines.append(f"{prefix} ${total:.2f} {offer.source} — {title}\n   {offer.url}")
    if result.missing_sources:
        gaps = ", ".join(f"{m.source}({m.reason})" for m in result.missing_sources)
        lines.append(f"(no data from: {gaps})")

    return HermesResponse(
        kind="offers",
        tool="find_cheapest_flight",
        spec=spec,
        text="\n".join(lines),
        offers=[_offer_to_dict(o) for o in result.all_offers],
        best=_offer_to_dict(result.best) if result.best else None,
        missing_sources=[asdict(m) for m in result.missing_sources],
    )


def _format_product_response(
    spec: dict[str, Any],
    result: CheapestOfferResponse,
) -> HermesResponse:
    name = " ".join(part for part in [spec.get("brand"), spec.get("model")] if part)
    if not result.all_offers:
        missing = ", ".join(
            f"{m.source}({m.reason})" for m in result.missing_sources
        ) or "no offers returned"
        return HermesResponse(
            kind="offers",
            tool="find_cheapest_product",
            spec=spec,
            text=f"No buyable offers for {name}. Sources: {missing}.",
            missing_sources=[asdict(m) for m in result.missing_sources],
        )

    lines = [f"Cheapest {name}:"]
    medals = ["🥇", "🥈", "🥉"]
    for i, offer in enumerate(result.all_offers[:3]):
        prefix = medals[i] if i < len(medals) else "  "
        total = offer.total_price if offer.total_price is not None else offer.price
        lines.append(
            f"{prefix} ${total:.2f} {offer.source} — {offer.title or offer.seller}\n   {offer.url}"
        )

    return HermesResponse(
        kind="offers",
        tool="find_cheapest_product",
        spec=spec,
        text="\n".join(lines),
        offers=[_offer_to_dict(o) for o in result.all_offers],
        best=_offer_to_dict(result.best) if result.best else None,
        missing_sources=[asdict(m) for m in result.missing_sources],
    )


def _offer_to_dict(offer: Offer) -> dict[str, Any]:
    return {
        "source": offer.source,
        "title": offer.title,
        "price": offer.price,
        "shipping_cost": offer.shipping_cost,
        "total_price": offer.total_price,
        "currency": offer.currency,
        "url": offer.url,
        "in_stock": offer.in_stock,
        "seller": offer.seller,
        "observed_at": offer.observed_at,
    }


if __name__ == "__main__":
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="User message to route")
    parser.add_argument("--user-id", default="cli-demo")
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args()

    resp = asyncio.run(
        handle_message(args.message, user_id=args.user_id, today=args.today)
    )
    print(json.dumps(asdict(resp), indent=2, default=str))
