"""
Tool-call definitions for the Search project.

Hermes-facing contract:
  find_cheapest_product(...)

The public tool takes an explicit shoe spec. Hermes is responsible for turning
user language into these fields and asking follow-up questions when required.
This module is responsible for validating the spec, resolving retailer variants,
ranking buyable offers, and persisting observations.

Rollout is controlled by source_scope:
  amazon  -> Amazon only, first demo path
  retail  -> Amazon + Walmart
  all     -> Amazon + Walmart + StockX when the spec is likely a sneaker

Read ./LEARNINGS.md before implementing platform resolvers, especially:
  - Don't scrape Amazon HTML for prices; use amazon_pdp.
  - SERP price is the default-rendered size, not the requested size.
  - Resolve to the child ASIN/item_id before reporting a price.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Category = Literal["shoes"]
Condition = Literal["new", "used", "ds", "any"]
Gender = Literal["men", "women", "kids", "unisex"]
Source = Literal["amazon", "walmart", "stockx"]
SourceScope = Literal["amazon", "retail", "all"]


@dataclass
class SizeSpec:
    system: Literal["US"]
    gender: Gender
    value: float


@dataclass
class ProductSpec:
    brand: str
    model: str
    size: SizeSpec
    category: Category = "shoes"
    color: Optional[str] = None
    condition: Condition = "new"
    postal_code: str = "10001"
    source_scope: SourceScope = "amazon"
    query: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class Offer:
    source: Source
    price: float
    currency: str
    url: str
    in_stock: bool
    seller: str
    shipping_cost: float
    observed_at: str  # ISO 8601 UTC
    title: str = ""
    condition: Condition = "new"
    total_price: Optional[float] = None
    confidence: float = 1.0


@dataclass
class MissingSource:
    source: Source
    reason: str


@dataclass
class CheapestOfferResponse:
    spec: ProductSpec
    best: Optional[Offer]
    all_offers: list[Offer]
    missing_sources: list[MissingSource]
    observation_ids: list[str]


# ---------------------------------------------------------------------------
# LLM tool-call schema
# ---------------------------------------------------------------------------

_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Original user query for traceability, e.g. "
                "'Nike Killshot 2 Sail Lucid Green size 11.5'."
            ),
        },
        "user_id": {
            "type": "string",
            "description": "Stable Hermes/Telegram user id for ClickHouse history.",
        },
        "category": {
            "type": "string",
            "enum": ["shoes"],
            "default": "shoes",
            "description": "Product category. V1 supports shoes only.",
        },
        "brand": {"type": "string", "description": "Shoe brand, e.g. 'Nike'."},
        "model": {
            "type": "string",
            "description": "Model or product line, e.g. 'Killshot 2'.",
        },
        "color": {
            "type": "string",
            "description": "Colorway. Optional for demo, but strongly recommended.",
        },
        "size": {
            "type": "object",
            "properties": {
                "system": {"type": "string", "enum": ["US"], "default": "US"},
                "gender": {
                    "type": "string",
                    "enum": ["men", "women", "kids", "unisex"],
                    "default": "men",
                },
                "value": {
                    "type": "number",
                    "description": "Decimal shoe size, e.g. 11.5.",
                },
            },
            "required": ["value"],
            "description": "Requested shoe size. Hermes should make this explicit.",
        },
        "condition": {
            "type": "string",
            "enum": ["new", "used", "ds", "any"],
            "default": "new",
        },
        "postal_code": {
            "type": "string",
            "default": "10001",
            "description": "Used for localized price, availability, and shipping.",
        },
        "source_scope": {
            "type": "string",
            "enum": ["amazon", "retail", "all"],
            "default": "amazon",
            "description": (
                "Internal rollout switch. Use 'amazon' for the first demo, "
                "'retail' for Amazon+Walmart, 'all' for sneaker resale stretch."
            ),
        },
    },
    "required": ["brand", "model", "size"],
}

TOOL_SCHEMAS = [
    {
        "name": "find_cheapest_product",
        "description": (
            "Find the cheapest currently buyable offer for an explicitly specified "
            "shoe. Hermes should parse or ask for brand, model, size, and preferably "
            "color before calling. V1 defaults to Amazon only via source_scope='amazon'."
        ),
        "input_schema": _INPUT_SCHEMA,
    },
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def build_product_spec(
    *,
    brand: str,
    model: str,
    size: SizeSpec | dict[str, Any] | float | int | None = None,
    size_us_men: Optional[float] = None,
    category: Category = "shoes",
    color: Optional[str] = None,
    condition: Condition = "new",
    postal_code: str = "10001",
    source_scope: SourceScope = "amazon",
    query: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ProductSpec:
    """Normalize Hermes JSON into a ProductSpec and raise ValueError on bad input."""
    spec = ProductSpec(
        brand=_require_text(brand, "brand"),
        model=_require_text(model, "model"),
        size=_normalize_size(size, size_us_men=size_us_men),
        category=category,
        color=_optional_text(color),
        condition=condition,
        postal_code=_require_text(postal_code, "postal_code"),
        source_scope=source_scope,
        query=_optional_text(query),
        user_id=_optional_text(user_id),
    )
    _validate_product_spec(spec)
    return spec


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional text fields must be strings when provided")
    stripped = value.strip()
    return stripped or None


def _normalize_size(
    size: SizeSpec | dict[str, Any] | float | int | None,
    *,
    size_us_men: Optional[float] = None,
) -> SizeSpec:
    if isinstance(size, SizeSpec):
        return size

    if isinstance(size, dict):
        raw_value = size.get("value")
        raw_system = size.get("system", "US")
        raw_gender = size.get("gender", "men")
    elif isinstance(size, (int, float)):
        raw_value = size
        raw_system = "US"
        raw_gender = "men"
    elif size_us_men is not None:
        raw_value = size_us_men
        raw_system = "US"
        raw_gender = "men"
    else:
        raise ValueError("size.value is required")

    if raw_system != "US":
        raise ValueError("only US shoe sizes are supported in v1")
    if raw_gender not in {"men", "women", "kids", "unisex"}:
        raise ValueError("size.gender must be men, women, kids, or unisex")

    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("size.value must be a number") from exc

    return SizeSpec(system="US", gender=raw_gender, value=value)


def _validate_product_spec(spec: ProductSpec) -> None:
    if spec.category != "shoes":
        raise ValueError("category must be 'shoes' in v1")
    if spec.condition not in {"new", "used", "ds", "any"}:
        raise ValueError("condition must be new, used, ds, or any")
    if spec.source_scope not in {"amazon", "retail", "all"}:
        raise ValueError("source_scope must be amazon, retail, or all")
    if not (0 < spec.size.value < 25):
        raise ValueError("shoe size must be greater than 0 and less than 25")


# ---------------------------------------------------------------------------
# Per-platform resolvers
# ---------------------------------------------------------------------------

async def _amazon_offer(spec: ProductSpec) -> Optional[Offer]:
    """
    Resolve an Amazon offer for the given spec.

    1. amazon_serp(keyword=f"{brand} {model} {color}") -> parent ASINs.
    2. Pick parent whose title best matches brand/model/color.
    3. amazon_pdp(asin=parent_asin) -> dimensionValuesDisplayData.
    4. Find child ASIN where (size, color) == requested.
    5. amazon_pdp(asin=child_asin, zip_code=postal_code) -> price + in-stock.
    6. Return Offer or None if OOS / no match.
    """
    query = _amazon_query(spec)

    serp = await _nimble_agent_run(
        "amazon_serp",
        params={"keyword": query, "zip_code": spec.postal_code},
        formats=["markdown", "html"],
    )
    candidate_asins = _rank_amazon_serp_asins(spec, serp)
    if not candidate_asins:
        return None

    offers: list[Offer] = []
    for color_asin in candidate_asins[:5]:
        offer = await _amazon_offer_for_candidate(spec, color_asin)
        if offer:
            offers.append(offer)

    return min(offers, key=_offer_total) if offers else None


async def _amazon_offer_for_candidate(spec: ProductSpec, color_asin: str) -> Optional[Offer]:
    parent = await _nimble_agent_run(
        "amazon_pdp",
        params={"asin": color_asin, "zip_code": spec.postal_code},
        formats=["html"],
    )
    child_asin = _pick_amazon_variant_asin(spec, parent) or color_asin

    pdp = await _nimble_agent_run(
        "amazon_pdp",
        params={"asin": child_asin, "zip_code": spec.postal_code},
    )
    parsing = _nimble_parsing(pdp)
    if not parsing:
        return None

    price = _to_float(parsing.get("web_price"))
    if price is None:
        return None

    actual_size = str(parsing.get("size") or parsing.get("option_name") or "")
    actual_color = str(parsing.get("color") or "")
    if actual_size and not _size_matches(actual_size, spec.size.value):
        return None
    if spec.color and actual_color and _token_score(spec.color, actual_color) <= 0:
        return None
    if not _pdp_matches_spec(spec, parsing):
        return None

    shipping_cost = _parse_shipping(parsing.get("shipping_amount"))
    availability = parsing.get("availability")
    in_stock = bool(availability) if availability is not None else True
    if not in_stock:
        return None

    return Offer(
        source="amazon",
        title=str(parsing.get("product_title") or ""),
        price=price,
        shipping_cost=shipping_cost,
        total_price=price + shipping_cost,
        currency="USD",
        url=str(parsing.get("product_url") or f"https://www.amazon.com/dp/{child_asin}"),
        in_stock=True,
        condition="new" if spec.condition in {"new", "any"} else spec.condition,
        seller=str(parsing.get("sold_by") or parsing.get("ships_from") or "Amazon"),
        observed_at=_now_iso(),
        confidence=_amazon_confidence(spec, parsing),
    )


async def _walmart_offer(spec: ProductSpec) -> Optional[Offer]:
    """
    Resolve a Walmart offer for the given spec.

    1. google_search(query + site:walmart.com) -> product_id.
       Current tests found no walmart_search agent; see test_nimble.py.
    2. walmart_pdp(product_id=..., zipcode=postal_code) -> variantFieldsMap.
    3. Find item_id for (size, color).
    4. walmart_pdp(product_id=child_item_id, zipcode=postal_code) -> price.
    5. Return Offer or None.
    """
    raise NotImplementedError("Wire up Nimble google_search + walmart_pdp here")


async def _stockx_offer(spec: ProductSpec) -> Optional[Offer]:
    """
    Resolve a StockX lowest-ask offer.

    Only valid for likely-sneaker brands and condition in {'new', 'ds', 'any'}.
    See LEARNINGS.md §11 — fail soft, return None on error.
    """
    if spec.condition not in {"new", "ds", "any"}:
        return None
    if not _is_likely_sneaker(spec):
        return None
    raise NotImplementedError("Wire up StockX unofficial GraphQL here")


_SNEAKER_BRANDS = {
    "nike", "adidas", "jordan", "new balance", "asics",
    "on", "puma", "reebok", "converse", "vans", "yeezy",
}


def _is_likely_sneaker(spec: ProductSpec) -> bool:
    return spec.brand.lower() in _SNEAKER_BRANDS


# ---------------------------------------------------------------------------
# Nimble helpers
# ---------------------------------------------------------------------------

async def _nimble_agent_run(
    agent: str,
    *,
    params: dict[str, object],
    formats: Optional[list[str]] = None,
) -> Any:
    api_key = os.environ.get("NIMBLE_API_KEY")
    if not api_key:
        raise RuntimeError("NIMBLE_API_KEY is required")

    from nimble_python import AsyncNimble

    client = AsyncNimble(api_key=api_key)
    kwargs: dict[str, Any] = {"agent": agent, "params": params}
    if formats:
        kwargs["formats"] = formats
    return await client.agent.run(**kwargs)


def _nimble_data(resp: Any) -> dict[str, Any]:
    data = getattr(resp, "data", None)
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    # Avoid pydantic model_dump here: Nimble's SERP `parsing` can be a list even
    # though the generated SDK type expects a union, which emits noisy warnings.
    return {
        "html": getattr(data, "html", None),
        "markdown": getattr(data, "markdown", None),
        "parsing": getattr(data, "parsing", None),
        "links": getattr(data, "links", None),
        "headers": getattr(data, "headers", None),
    }


def _nimble_parsing(resp: Any) -> dict[str, Any]:
    parsing = _nimble_data(resp).get("parsing")
    if isinstance(parsing, dict):
        return parsing
    return {}


def _amazon_query(spec: ProductSpec) -> str:
    parts = [spec.brand, spec.model]
    if spec.color:
        parts.append(spec.color)
    if spec.category == "shoes":
        if spec.size.gender == "men":
            parts.append("mens")
        elif spec.size.gender == "women":
            parts.append("womens")
        elif spec.size.gender == "kids":
            parts.append("kids")
        parts.append(f"size {spec.size.value:g}")
    return " ".join(parts)


def _rank_amazon_serp_asins(spec: ProductSpec, resp: Any) -> list[str]:
    data = _nimble_data(resp)
    markdown = data.get("markdown") or ""
    html = data.get("html") or ""

    candidates = _amazon_link_candidates(markdown) or _amazon_link_candidates(html)
    if not candidates:
        return []

    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, candidate in enumerate(candidates):
        asin = candidate["asin"]
        if asin in seen:
            continue
        seen.add(asin)
        label = candidate["label"]
        brand_score = _brand_score(spec.brand, label)
        model_score = _model_score(spec.model, label)
        color_score = _token_score(spec.color, label) if spec.color else 0
        if spec.color:
            if brand_score <= 0 and model_score <= 0 and color_score <= 0:
                continue
        elif brand_score <= 0 or model_score <= 0:
            continue
        score = (
            3 * brand_score
            + 4 * model_score
            + 6 * color_score
        )
        if score > 0:
            scored.append((score, -position, asin))

    if not scored:
        return [candidates[0]["asin"]]
    scored.sort(reverse=True)
    return [asin for _, _, asin in scored]


def _pick_amazon_serp_asin(spec: ProductSpec, resp: Any) -> Optional[str]:
    ranked = _rank_amazon_serp_asins(spec, resp)
    return ranked[0] if ranked else None


def _amazon_link_candidates(text: str) -> list[dict[str, str]]:
    if not text:
        return []

    candidates: list[dict[str, str]] = []

    # Markdown links from Nimble's SERP output.
    for match in re.finditer(
        r"\[([^\]]{2,180})\]\((https?://(?:www\.)?amazon\.com/[^)]*/dp/(B[A-Z0-9]{9})[^)]*)\)",
        text,
    ):
        candidates.append(
            {
                "label": _strip_markdown(match.group(1)),
                "url": match.group(2),
                "asin": match.group(3),
            }
        )

    # HTML fallback; enough for Amazon result cards and color swatches.
    for match in re.finditer(
        r"(?:aria-label|alt)=\"([^\"]{2,180})\"[^>]+href=\"([^\"]*/dp/(B[A-Z0-9]{9})[^\"]*)\"",
        text,
    ):
        candidates.append(
            {
                "label": _strip_html(match.group(1)),
                "url": match.group(2),
                "asin": match.group(3),
            }
        )

    return candidates


def _pick_amazon_variant_asin(spec: ProductSpec, resp: Any) -> Optional[str]:
    html = _nimble_data(resp).get("html") or ""
    dimension_map = _extract_dimension_values_display_data(html)
    if not dimension_map:
        return None

    best: Optional[tuple[int, int, str]] = None
    for position, (asin, values) in enumerate(dimension_map.items()):
        if not isinstance(values, list) or len(values) < 2:
            continue
        size_raw = str(values[0])
        color_raw = str(values[1])
        if not _size_matches(size_raw, spec.size.value):
            continue
        color_score = _token_score(spec.color, color_raw) if spec.color else 1
        if color_score <= 0:
            continue
        candidate = (color_score, -position, asin)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _extract_dimension_values_display_data(html: str) -> dict[str, list[str]]:
    marker = '"dimensionValuesDisplayData"'
    marker_pos = html.find(marker)
    if marker_pos == -1:
        return {}

    start = html.find("{", marker_pos)
    if start == -1:
        return {}

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(html)):
        ch = html[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = html[start : idx + 1]
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
    return {}


def _amazon_confidence(spec: ProductSpec, parsing: dict[str, Any]) -> float:
    title = str(parsing.get("product_title") or "")
    color = str(parsing.get("color") or "")
    score = (
        _brand_score(spec.brand, " ".join([title, str(parsing.get("brand") or "")]))
        + _model_score(spec.model, title)
        + (_token_score(spec.color, color) if spec.color else 1)
    )
    return min(1.0, max(0.2, score / 8))


def _pdp_matches_spec(spec: ProductSpec, parsing: dict[str, Any]) -> bool:
    title = str(parsing.get("product_title") or "")
    brand_text = " ".join([title, str(parsing.get("brand") or ""), str(parsing.get("manufacturer") or "")])
    if _brand_score(spec.brand, brand_text) <= 0:
        return False
    if _model_score(spec.model, title) <= 0:
        return False
    if spec.color:
        color = str(parsing.get("color") or "")
        if color and _token_score(spec.color, color) <= 0:
            return False
    return True


# ---------------------------------------------------------------------------
# Public Hermes tool
# ---------------------------------------------------------------------------

async def find_cheapest_product(
    *,
    brand: str,
    model: str,
    size: SizeSpec | dict[str, Any] | float | int | None = None,
    category: Category = "shoes",
    color: Optional[str] = None,
    condition: Condition = "new",
    postal_code: str = "10001",
    source_scope: SourceScope = "amazon",
    query: Optional[str] = None,
    user_id: Optional[str] = None,
    size_us_men: Optional[float] = None,
) -> CheapestOfferResponse:
    spec = build_product_spec(
        brand=brand,
        model=model,
        size=size,
        size_us_men=size_us_men,
        category=category,
        color=color,
        condition=condition,
        postal_code=postal_code,
        source_scope=source_scope,
        query=query,
        user_id=user_id,
    )
    return await _find_with_scope(spec)


async def _find_with_scope(spec: ProductSpec) -> CheapestOfferResponse:
    if spec.source_scope == "amazon":
        return _rank_and_persist(
            spec,
            await _run_resolvers([("amazon", _amazon_offer(spec))]),
        )

    resolvers: list[tuple[Source, Any]] = [
        ("amazon", _amazon_offer(spec)),
        ("walmart", _walmart_offer(spec)),
    ]
    if spec.source_scope == "all" and _is_likely_sneaker(spec):
        resolvers.append(("stockx", _stockx_offer(spec)))

    return _rank_and_persist(spec, await _run_resolvers(resolvers))


async def _run_resolvers(
    resolvers: list[tuple[Source, Any]],
) -> tuple[list[Offer], list[MissingSource]]:
    results = await asyncio.gather(
        *(coro for _, coro in resolvers),
        return_exceptions=True,
    )

    offers: list[Offer] = []
    missing: list[MissingSource] = []
    for (source, _), result in zip(resolvers, results):
        if isinstance(result, Offer):
            if result.in_stock:
                offers.append(result)
            else:
                missing.append(MissingSource(source=source, reason="out_of_stock"))
        elif result is None:
            missing.append(MissingSource(source=source, reason="no_offer"))
        elif isinstance(result, NotImplementedError):
            missing.append(MissingSource(source=source, reason="not_implemented"))
        elif isinstance(result, Exception):
            missing.append(MissingSource(source=source, reason=type(result).__name__))
        else:
            missing.append(MissingSource(source=source, reason="invalid_resolver_result"))
    return offers, missing


# ---------------------------------------------------------------------------
# Legacy phase wrappers
# ---------------------------------------------------------------------------

async def find_cheapest_amazon(
    brand: str,
    model: str,
    size_us_men: float,
    color: Optional[str] = None,
    condition: Condition = "new",
) -> CheapestOfferResponse:
    return await find_cheapest_product(
        brand=brand,
        model=model,
        size_us_men=size_us_men,
        color=color,
        condition=condition,
        source_scope="amazon",
    )


async def find_cheapest_retail(
    brand: str,
    model: str,
    size_us_men: float,
    color: Optional[str] = None,
    condition: Condition = "new",
) -> CheapestOfferResponse:
    return await find_cheapest_product(
        brand=brand,
        model=model,
        size_us_men=size_us_men,
        color=color,
        condition=condition,
        source_scope="retail",
    )


async def find_cheapest_all(
    brand: str,
    model: str,
    size_us_men: float,
    color: Optional[str] = None,
    condition: Condition = "new",
) -> CheapestOfferResponse:
    return await find_cheapest_product(
        brand=brand,
        model=model,
        size_us_men=size_us_men,
        color=color,
        condition=condition,
        source_scope="all",
    )


# ---------------------------------------------------------------------------
# Ranking + persistence
# ---------------------------------------------------------------------------

def _rank_and_persist(
    spec: ProductSpec,
    resolved: tuple[list[Offer], list[MissingSource]],
) -> CheapestOfferResponse:
    offers, missing_sources = resolved
    sorted_offers = sorted(offers, key=_offer_total)
    observation_ids = [_persist_observation(spec, o) for o in sorted_offers]
    return CheapestOfferResponse(
        spec=spec,
        best=sorted_offers[0] if sorted_offers else None,
        all_offers=sorted_offers,
        missing_sources=missing_sources,
        observation_ids=observation_ids,
    )


def _offer_total(offer: Offer) -> float:
    if offer.total_price is not None:
        return offer.total_price
    return offer.price + (offer.shipping_cost or 0)


def _persist_observation(spec: ProductSpec, offer: Offer) -> str:
    """
    Insert one row into ClickHouse listings_observations and return the row id.

    Schema: ../clickhouse-setup.sql.

    Demo behavior: return a stable-looking id even when ClickHouse credentials or
    clickhouse-connect are unavailable. That keeps Hermes runnable while the DB
    integration is wired separately.
    """
    observation_id = str(uuid.uuid4())
    if not os.environ.get("CLICKHOUSE_HOST"):
        return f"local:{observation_id}"

    try:
        import clickhouse_connect
    except ModuleNotFoundError:
        return f"local:{observation_id}"

    client = clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ.get("CLICKHOUSE_USER", "nimble_loader"),
        password=os.environ["CLICKHOUSE_PASSWORD"],
        database=os.environ.get("CLICKHOUSE_DATABASE", "scraping"),
        secure=True,
    )
    client.insert(
        "amazon_products",
        [
            [
                _asin_from_url(offer.url) or "",
                offer.title,
                spec.brand,
                offer.price,
                None,
                offer.currency,
                1 if offer.in_stock else 0,
                None,
                None,
                "Shoes",
                offer.seller,
                spec.postal_code,
                offer.url,
                observation_id,
                json.dumps({"spec": _spec_to_dict(spec), "offer": _offer_to_dict(offer)}),
            ]
        ],
        column_names=[
            "asin",
            "product_title",
            "brand",
            "web_price",
            "list_price",
            "currency",
            "availability",
            "average_of_reviews",
            "number_of_reviews",
            "category",
            "seller",
            "zip_code",
            "url",
            "task_id",
            "raw",
        ],
    )
    return observation_id


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if match:
            return float(match.group(0))
    return None


def _parse_shipping(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().lower()
    if not text or "free" in text:
        return 0.0
    parsed = _to_float(text)
    return parsed if parsed is not None else 0.0


def _size_matches(raw_size: str, requested: float) -> bool:
    candidates = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw_size)]
    return any(abs(candidate - requested) < 0.01 for candidate in candidates)


def _token_score(needle: Optional[str], haystack: str) -> int:
    if not needle:
        return 0
    needle_tokens = _tokens(needle)
    if not needle_tokens:
        return 0
    haystack_tokens = _tokens(haystack)
    return sum(1 for token in needle_tokens if token in haystack_tokens)


def _brand_score(brand: str, haystack: str) -> int:
    normalized_brand = brand.strip().lower()
    normalized_haystack = haystack.strip().lower()
    if normalized_brand == "on":
        return 1 if re.search(r"(^|[^a-z0-9])on([^a-z0-9]|$)", normalized_haystack) else 0
    return _token_score(brand, haystack)


def _model_score(model: str, haystack: str) -> int:
    model_tokens = _tokens(model) - _GENERIC_PRODUCT_TOKENS
    if not model_tokens:
        model_tokens = _tokens(model)
    haystack_tokens = _tokens(haystack)
    return sum(1 for token in model_tokens if token in haystack_tokens)


_GENERIC_PRODUCT_TOKENS = {
    "casual",
    "dress",
    "fashion",
    "leather",
    "men",
    "mens",
    "running",
    "shoe",
    "shoes",
    "sneaker",
    "sneakers",
    "women",
    "womens",
}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", text.lower())
        if token and token not in {"the", "and", "for", "men", "mens", "women", "womens"}
    }


def _strip_markdown(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("##", "")).strip()


def _strip_html(value: str) -> str:
    value = (
        value.replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"\s+", " ", value).strip()


def _asin_from_url(url: str) -> Optional[str]:
    match = re.search(r"/dp/(B[A-Z0-9]{9})", url)
    return match.group(1) if match else None


def _spec_to_dict(spec: ProductSpec) -> dict[str, Any]:
    return {
        "brand": spec.brand,
        "model": spec.model,
        "category": spec.category,
        "color": spec.color,
        "size": {
            "system": spec.size.system,
            "gender": spec.size.gender,
            "value": spec.size.value,
        },
        "condition": spec.condition,
        "postal_code": spec.postal_code,
        "source_scope": spec.source_scope,
        "query": spec.query,
        "user_id": spec.user_id,
    }


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
        "condition": offer.condition,
        "confidence": offer.confidence,
        "observed_at": offer.observed_at,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
