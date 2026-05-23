"""
Tool-call definitions for the Search project.

Hermes-facing contract:
  find_cheapest_product(...)

The public tool takes an explicit product spec. Hermes is responsible for turning
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
from urllib.parse import unquote


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Category = Literal["shoes", "electronics", "toys", "generic"]
Condition = Literal["new", "used", "ds", "any"]
Gender = Literal["men", "women", "kids", "unisex"]
Source = Literal["amazon", "walmart", "stockx"]
SourceScope = Literal["amazon", "retail", "all"]

CLICKHOUSE_PRICE_EVENTS_COLUMNS = (
    "user_id",
    "product_id",
    "product_name",
    "url",
    "source",
    "price",
    "currency",
    "timestamp",
)


@dataclass
class SizeSpec:
    system: Literal["US"]
    gender: Gender
    value: float


@dataclass
class ProductSpec:
    brand: str
    model: str
    size: Optional[SizeSpec] = None
    category: Category = "generic"
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
            "enum": ["shoes", "electronics", "toys", "generic"],
            "default": "generic",
            "description": (
                "Product category hint. Use 'shoes' for exact shoe variants, "
                "'electronics' for items like headphones, 'toys' for LEGO, "
                "and 'generic' when unsure."
            ),
        },
        "brand": {"type": "string", "description": "Product brand, e.g. 'Nike', 'Sony', or 'LEGO'."},
        "model": {
            "type": "string",
            "description": "Model, product line, or specific product name, e.g. 'Killshot 2' or 'WH-1000XM5'.",
        },
        "color": {
            "type": "string",
            "description": "Color or colorway when relevant.",
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
            "description": (
                "Requested shoe size. Optional for generic product searches; "
                "include it when Hermes needs exact shoe variant pricing."
            ),
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
    "required": ["brand", "model"],
}

TOOL_SCHEMAS = [
    {
        "name": "find_cheapest_product",
        "description": (
            "Find the cheapest currently buyable offer for an explicitly specified "
            "product. Hermes should parse brand/model and include size when an exact "
            "shoe variant is requested. V1 defaults to Amazon only via source_scope='amazon'."
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
    category: Optional[Category] = None,
    color: Optional[str] = None,
    condition: Condition = "new",
    postal_code: str = "10001",
    source_scope: SourceScope = "amazon",
    query: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ProductSpec:
    """Normalize Hermes JSON into a ProductSpec and raise ValueError on bad input."""
    normalized_size = _normalize_size(size, size_us_men=size_us_men)
    spec = ProductSpec(
        brand=_require_text(brand, "brand"),
        model=_require_text(model, "model"),
        size=normalized_size,
        category=category or ("shoes" if normalized_size else "generic"),
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
) -> Optional[SizeSpec]:
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
        return None

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
    if spec.category not in {"shoes", "electronics", "toys", "generic"}:
        raise ValueError("category must be shoes, electronics, toys, or generic")
    if spec.condition not in {"new", "used", "ds", "any"}:
        raise ValueError("condition must be new, used, ds, or any")
    if spec.source_scope not in {"amazon", "retail", "all"}:
        raise ValueError("source_scope must be amazon, retail, or all")
    if spec.size is not None and not (0 < spec.size.value < 25):
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
    limit = 5 if spec.size else 2
    for color_asin in candidate_asins[:limit]:
        offer = await _amazon_offer_for_candidate(spec, color_asin)
        if offer:
            offers.append(offer)

    return min(offers, key=_offer_total) if offers else None


async def _amazon_offer_for_candidate(spec: ProductSpec, color_asin: str) -> Optional[Offer]:
    child_asin = color_asin
    if spec.size:
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
    if spec.size and actual_size and not _size_matches(actual_size, spec.size.value):
        return None
    if spec.color and actual_color and not _color_matches(spec.color, actual_color):
        return None
    if not _pdp_matches_spec(spec, parsing):
        return None
    if not _condition_matches(spec.condition, str(parsing.get("product_title") or ""), parsing.get("condition")):
        return None

    shipping_cost = _parse_shipping(parsing.get("shipping_amount"))
    availability = parsing.get("availability")
    in_stock = bool(availability) if availability is not None else True
    if not in_stock:
        return None

    offer = Offer(
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
    return offer if _offer_identity_matches(spec, offer) else None


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
    query = _walmart_query(spec)
    broad_query = _walmart_query(spec, include_gender=False)
    seen_ids: set[str] = set()
    if spec.size:
        search_queries = [f"{query} site:walmart.com"]
        if broad_query != query:
            search_queries.append(f"{broad_query} site:walmart.com/ip")
        search_queries.append(f"{query} site:walmart.com/ip")
    else:
        search_queries = [f"{query} site:walmart.com/ip"]

    for search_index, search_query in enumerate(search_queries):
        google = await _nimble_agent_run(
            "google_search",
            params={"query": search_query, "country": "US"},
            formats=["markdown"],
        )
        candidate_ids = [
            product_id
            for product_id in _rank_walmart_product_ids(spec, google)
            if product_id not in seen_ids
        ]
        seen_ids.update(candidate_ids)
        limit = 4 if spec.size else 2
        offers = await _walmart_offers_for_product_ids(spec, candidate_ids[:limit])
        if offers:
            return min(offers, key=_offer_total)

    return None


async def _walmart_offers_for_product_ids(spec: ProductSpec, product_ids: list[str]) -> list[Offer]:
    if not product_ids:
        return []
    results = await asyncio.gather(
        *(_walmart_offer_for_candidate(spec, product_id) for product_id in product_ids),
        return_exceptions=True,
    )
    return [offer for offer in results if offer]


async def _walmart_offer_for_candidate(spec: ProductSpec, product_id: str) -> Optional[Offer]:
    parent = await _nimble_agent_run(
        "walmart_pdp",
        params={"product_id": product_id, "zipcode": spec.postal_code},
    )
    parent_parsing = _nimble_parsing(parent)
    if not parent_parsing:
        return None

    if not _walmart_pdp_matches_spec(spec, parent_parsing):
        return None

    variants = _walmart_variants(parent_parsing)
    variant = _pick_walmart_variant(spec, parent_parsing)
    if variant is None:
        if variants:
            return None
        if not _walmart_variant_matches_spec(spec, parent_parsing):
            return None
        variant = parent_parsing

    variant_id = _walmart_variant_product_id(variant) or product_id
    child_parsing = parent_parsing
    validated_variant = variant
    validated_from_child_variant = False
    if variant_id != product_id:
        child = await _nimble_agent_run(
            "walmart_pdp",
            params={"product_id": variant_id, "zipcode": spec.postal_code},
        )
        child_parsing = _nimble_parsing(child)
        if not child_parsing:
            return None
        child_variant = _pick_walmart_variant(spec, child_parsing)
        if child_variant:
            validated_variant = child_variant
            validated_from_child_variant = True

    if not validated_from_child_variant and not _walmart_variant_matches_spec(spec, child_parsing):
        return None
    child_availability = _first_present(child_parsing, ("availability", "product_availability", "in_stock"))
    variant_availability = _first_present(validated_variant, ("product_availability", "availability", "in_stock"))
    if not _walmart_in_stock(child_availability) or not _walmart_in_stock(variant_availability):
        return None
    if not _condition_matches(
        spec.condition,
        " ".join(
            text
            for text in [
                _first_text(validated_variant, _WALMART_TITLE_KEYS),
                _first_text(child_parsing, _WALMART_TITLE_KEYS),
                _first_text(validated_variant, ("product_variant",)),
            ]
            if text
        ),
        _first_present(child_parsing, ("condition", "product_condition")),
    ):
        return None

    price = _walmart_price(validated_variant)
    if price is None:
        price = _walmart_price(child_parsing)
    if price is None:
        price = _walmart_price(variant)
    if price is None:
        return None

    shipping_cost = _parse_shipping(_first_present(child_parsing, _WALMART_SHIPPING_KEYS))
    currency = (
        _first_text(validated_variant, _WALMART_CURRENCY_KEYS)
        or _first_text(child_parsing, _WALMART_CURRENCY_KEYS)
        or _first_text(variant, _WALMART_CURRENCY_KEYS)
        or "USD"
    )
    url = (
        _first_text(validated_variant, _WALMART_URL_KEYS)
        or _first_text(child_parsing, _WALMART_URL_KEYS)
        or _first_text(variant, _WALMART_URL_KEYS)
        or f"https://www.walmart.com/ip/{variant_id}"
    )

    offer = Offer(
        source="walmart",
        title=_first_text(validated_variant, _WALMART_TITLE_KEYS) or _first_text(child_parsing, _WALMART_TITLE_KEYS) or "",
        price=price,
        shipping_cost=shipping_cost,
        total_price=price + shipping_cost,
        currency=currency,
        url=url,
        in_stock=True,
        condition="new" if spec.condition in {"new", "any"} else spec.condition,
        seller=_first_text(child_parsing, _WALMART_SELLER_KEYS) or "Walmart",
        observed_at=_now_iso(),
        confidence=_walmart_confidence(spec, child_parsing),
    )
    return offer if _offer_identity_matches(spec, offer) else None


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
        "pages_html": getattr(data, "pages_html", None),
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
    if spec.category == "shoes" and spec.size:
        if spec.size.gender == "men":
            parts.append("mens")
        elif spec.size.gender == "women":
            parts.append("womens")
        elif spec.size.gender == "kids":
            parts.append("kids")
        parts.append(f"size {spec.size.value:g}")
    return " ".join(parts)


def _walmart_query(spec: ProductSpec, *, include_gender: bool = True) -> str:
    brand = "On Running" if spec.brand.strip().lower() == "on" else spec.brand
    parts = [brand, spec.model]
    if spec.color:
        parts.append(spec.color)
    if spec.category == "shoes" and spec.size:
        if include_gender:
            if spec.size.gender == "men":
                parts.append("mens")
            elif spec.size.gender == "women":
                parts.append("womens")
            elif spec.size.gender == "kids":
                parts.append("kids")
        parts.append(f"size {spec.size.value:g}")
    return " ".join(parts)


_WALMART_PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?walmart\.com/ip/(?:(?P<slug>[^/?#\s\)\]\"'<>]+)/)?(?P<id>\d+)"
)
_WALMART_TITLE_KEYS = ("product_title", "title", "name")
_WALMART_URL_KEYS = ("product_url", "url", "canonical_url")
_WALMART_PRICE_KEYS = (
    "price",
    "web_price",
    "current_price",
    "final_price",
    "sale_price",
    "product_price",
    "line_price",
)
_WALMART_CURRENCY_KEYS = ("currency", "price_currency", "product_price_currency")
_WALMART_SHIPPING_KEYS = ("shipping_amount", "shipping_cost", "shipping_price", "delivery_fee")
_WALMART_SELLER_KEYS = ("seller", "seller_name", "seller_display_name", "sold_by", "merchant_name")
_WALMART_TEXT_KEYS = (
    "product_title",
    "title",
    "name",
    "brand",
    "model",
    "category",
    "product_type",
    "product_description",
    "description",
    "color",
    "size",
    "option_name",
    "product_variant",
    "product_url",
    "breadcrumbs",
)
_WALMART_EXPLICIT_SIZE_KEYS = ("size", "option_name", "product_variant")
_WALMART_SIZE_KEYS = _WALMART_EXPLICIT_SIZE_KEYS + ("product_url", "product_title", "title")
_WALMART_COLOR_KEYS = ("color", "color_name", "swatch", "product_variant", "product_url", "product_title", "title")


def _rank_walmart_product_ids(spec: ProductSpec, resp: Any) -> list[str]:
    candidates = _walmart_link_candidates(resp)
    if not candidates:
        return []

    best_by_id: dict[str, tuple[int, int, str]] = {}
    fallback_ids: list[str] = []
    for position, candidate in enumerate(candidates):
        product_id = candidate["product_id"]
        if product_id not in fallback_ids:
            fallback_ids.append(product_id)

        label = candidate["label"]
        if spec.size and not _shoe_gender_matches(spec.size.gender, label):
            continue
        brand_score = _brand_score(spec.brand, label)
        model_score = _model_score(spec.model, label)
        if brand_score <= 0 or model_score <= 0:
            continue

        color_score = _token_score(spec.color, label) if spec.color else 0
        size_score = 1 if spec.size and _size_matches(label, spec.size.value) else 0
        score = (
            4 * brand_score
            + 5 * model_score
            + 6 * color_score
            + 3 * size_score
        )
        ranked = (score, -position, product_id)
        if product_id not in best_by_id or ranked > best_by_id[product_id]:
            best_by_id[product_id] = ranked

    if not best_by_id:
        return fallback_ids

    ranked_ids = [
        product_id
        for _, _, product_id in sorted(best_by_id.values(), reverse=True)
    ]
    return ranked_ids + [product_id for product_id in fallback_ids if product_id not in ranked_ids]


def _walmart_link_candidates(resp: Any) -> list[dict[str, str]]:
    data = _nimble_data(resp)
    candidates: list[dict[str, str]] = []

    parsing = data.get("parsing")
    entities = parsing.get("entities") if isinstance(parsing, dict) else None
    organic = entities.get("OrganicResult") if isinstance(entities, dict) else None
    if isinstance(organic, list):
        for result in organic:
            if not isinstance(result, dict):
                continue
            url = str(result.get("url") or result.get("link") or "")
            product_id = _walmart_product_id_from_url(url)
            if not product_id:
                continue
            label = _strip_html(
                " ".join(
                    str(result.get(key) or "")
                    for key in ("title", "snippet", "displayed_url")
                )
            )
            candidates.append(
                {
                    "label": label or _walmart_label_from_url(url),
                    "url": url,
                    "product_id": product_id,
                }
            )

    raw_text = "\n".join(
        json.dumps(data.get(key), default=str)
        for key in ("parsing", "markdown", "html", "pages_html")
        if data.get(key)
    )
    for match in _WALMART_PRODUCT_URL_RE.finditer(raw_text):
        url = match.group(0)
        product_id = match.group("id")
        candidates.append(
            {
                "label": _walmart_label_from_url(url),
                "url": url,
                "product_id": product_id,
            }
        )

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate["product_id"], candidate["label"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _walmart_product_id_from_url(url: str) -> Optional[str]:
    match = _WALMART_PRODUCT_URL_RE.search(url)
    return match.group("id") if match else None


def _walmart_label_from_url(url: str) -> str:
    match = _WALMART_PRODUCT_URL_RE.search(url)
    if not match:
        return ""
    slug = match.group("slug") or ""
    return _strip_html(unquote(slug).replace("-", " "))


def _walmart_pdp_matches_spec(spec: ProductSpec, parsing: dict[str, Any]) -> bool:
    text = _walmart_item_text(parsing)
    if _brand_score(spec.brand, text) <= 0:
        return False
    if _model_score(spec.model, text) <= 0:
        return False
    if spec.size and not _shoe_gender_matches(spec.size.gender, text):
        return False
    return True


def _pick_walmart_variant(spec: ProductSpec, parsing: dict[str, Any]) -> Optional[dict[str, Any]]:
    best: Optional[tuple[int, int, int, dict[str, Any]]] = None
    for position, variant in enumerate(_walmart_variants(parsing)):
        if not _walmart_variant_matches_spec(spec, variant, parent=parsing):
            continue
        color_score = _token_score(spec.color, _walmart_variant_color_text(variant, parent=parsing)) if spec.color else 0
        price_score = 1 if _walmart_price(variant) is not None else 0
        candidate = (color_score, price_score, -position, variant)
        if best is None or candidate > best:
            best = candidate
    return best[3] if best else None


def _walmart_variants(parsing: dict[str, Any]) -> list[dict[str, Any]]:
    variants = parsing.get("variants")
    if not isinstance(variants, list):
        return []
    return [variant for variant in variants if isinstance(variant, dict)]


def _walmart_variant_matches_spec(
    spec: ProductSpec,
    item: dict[str, Any],
    *,
    parent: Optional[dict[str, Any]] = None,
) -> bool:
    identity_text = _walmart_variant_identity_text(item, parent=parent)
    if _brand_score(spec.brand, identity_text) <= 0:
        return False
    if _model_score(spec.model, identity_text) <= 0:
        return False
    if spec.size and not _shoe_gender_matches(spec.size.gender, identity_text):
        return False

    if spec.size and not _walmart_size_matches(item, spec.size.value):
        return False
    if spec.color and not _color_matches(spec.color, _walmart_variant_color_text(item, parent=parent)):
        return False
    availability = _first_present(item, ("product_availability", "availability", "in_stock"))
    return _walmart_in_stock(availability)


def _walmart_size_matches(item: dict[str, Any], requested: float) -> bool:
    explicit = _walmart_text_for_keys(item, _WALMART_EXPLICIT_SIZE_KEYS)
    if explicit and re.search(r"\d", explicit):
        return _size_matches(explicit, requested)

    fallback = _walmart_text_for_keys(item, ("product_title", "title", "product_url"))
    if not fallback:
        return False
    if _labeled_size_matches(fallback, requested):
        return True
    if _terminal_size_matches(fallback, requested):
        return True

    numeric_values = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", fallback)]
    unique_values = {round(value, 2) for value in numeric_values}
    return len(unique_values) == 1 and any(abs(value - requested) < 0.01 for value in unique_values)


def _walmart_variant_identity_text(
    item: dict[str, Any],
    *,
    parent: Optional[dict[str, Any]] = None,
) -> str:
    item_text = _walmart_item_text(item)
    item_has_identity = any(
        item.get(key)
        for key in (
            "product_title",
            "title",
            "name",
            "brand",
            "model",
            "product_url",
            "category",
            "product_type",
        )
    )
    if item_has_identity:
        return item_text
    return _walmart_item_text(item, parent=parent)


def _walmart_variant_product_id(item: dict[str, Any]) -> Optional[str]:
    for key in ("primary_us_id", "variant_id", "item_id", "product_id"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return str(int(value))
        if isinstance(value, str) and value.isdigit():
            return value
    for key in _WALMART_URL_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            product_id = _walmart_product_id_from_url(value)
            if product_id:
                return product_id
    return None


def _walmart_price(item: dict[str, Any]) -> Optional[float]:
    for key in _WALMART_PRICE_KEYS:
        parsed = _to_float(item.get(key))
        if parsed is not None:
            return parsed

    for nested_key in ("price_info", "priceInfo", "price_data", "priceData"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            parsed = _walmart_price(nested)
            if parsed is not None:
                return parsed
    return None


def _walmart_in_stock(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = str(value).strip().lower()
    if not text:
        return True
    if text in {"false", "0", "no"}:
        return False
    if any(term in text for term in ("out_of_stock", "out of stock", "sold out", "unavailable")):
        return False
    if any(term in text for term in ("in_stock", "in stock", "available", "true", "yes")):
        return True
    return bool(value)


def _walmart_confidence(spec: ProductSpec, parsing: dict[str, Any]) -> float:
    text = _walmart_item_text(parsing)
    score = (
        _brand_score(spec.brand, text)
        + _model_score(spec.model, text)
        + (1 if spec.size and _walmart_size_matches(parsing, spec.size.value) else 0)
        + (1 if spec.size and _shoe_gender_matches(spec.size.gender, text) else 0)
        + (_token_score(spec.color, _walmart_variant_color_text(parsing)) if spec.color else 1)
    )
    return min(1.0, max(0.2, score / 8))


def _walmart_item_text(item: dict[str, Any], *, parent: Optional[dict[str, Any]] = None) -> str:
    parts: list[str] = []
    for source in (parent, item):
        if not isinstance(source, dict):
            continue
        for key in _WALMART_TEXT_KEYS:
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                parts.extend(str(v) for v in value)
            elif value is not None:
                parts.append(str(value))
    return _strip_html(" ".join(parts))


def _walmart_size_text(item: dict[str, Any], *, parent: Optional[dict[str, Any]] = None) -> str:
    return _walmart_text_for_keys(item, _WALMART_SIZE_KEYS, parent=parent)


def _walmart_color_text(item: dict[str, Any], *, parent: Optional[dict[str, Any]] = None) -> str:
    return _walmart_text_for_keys(item, _WALMART_COLOR_KEYS, parent=parent)


def _walmart_variant_color_text(item: dict[str, Any], *, parent: Optional[dict[str, Any]] = None) -> str:
    own_text = _walmart_text_for_keys(item, _WALMART_COLOR_KEYS)
    if own_text:
        return own_text
    return _walmart_color_text(item, parent=parent)


def _walmart_text_for_keys(
    item: dict[str, Any],
    keys: tuple[str, ...],
    *,
    parent: Optional[dict[str, Any]] = None,
) -> str:
    parts: list[str] = []
    for source in (parent, item):
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                parts.extend(str(v) for v in value)
            elif value is not None:
                parts.append(str(value))
    return _strip_html(" ".join(parts))


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
        if spec.size is None:
            continue
        size_raw = str(values[0])
        color_raw = str(values[1])
        if not _size_matches(size_raw, spec.size.value):
            continue
        color_score = _token_score(spec.color, color_raw) if spec.color else 1
        if spec.color and not _color_matches(spec.color, color_raw):
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
    if spec.size and not _shoe_gender_matches(spec.size.gender, title):
        return False
    explicit_title_sizes = _explicit_size_values(title)
    if spec.size and explicit_title_sizes and not any(
        abs(candidate - spec.size.value) < 0.01 for candidate in explicit_title_sizes
    ):
        return False
    if spec.color:
        color = str(parsing.get("color") or "")
        if color and not _color_matches(spec.color, color):
            return False
    return True


def _offer_identity_matches(spec: ProductSpec, offer: Offer) -> bool:
    identity_text = " ".join([offer.title, offer.url])
    if _brand_score(spec.brand, identity_text) <= 0:
        return False
    if _model_score(spec.model, identity_text) <= 0:
        return False
    numeric_model_tokens = {token for token in _tokens(spec.model) if token.isdigit()}
    if numeric_model_tokens and not numeric_model_tokens.issubset(_tokens(identity_text)):
        return False
    if spec.color and not _color_matches(spec.color, identity_text):
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
    category: Optional[Category] = None,
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
    observation_ids = store_price_events(spec, sorted_offers)
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


def build_clickhouse_price_event(spec: ProductSpec, offer: Offer) -> dict[str, Any]:
    """Map one Nimble-derived offer to the pricepilot.price_events schema."""
    return {
        "user_id": spec.user_id or "",
        "product_id": _canonical_product_id(spec),
        "product_name": offer.title or " ".join(part for part in (spec.brand, spec.model) if part),
        "url": offer.url,
        "source": offer.source,
        "price": float(offer.price),
        "currency": offer.currency or "USD",
        "timestamp": _clickhouse_datetime(offer.observed_at),
    }


def store_price_events(
    spec: ProductSpec,
    offers: list[Offer],
    *,
    client: Any = None,
) -> list[str]:
    """
    Bulk insert Nimble offers into ClickHouse pricepilot.price_events.

    Returns generated observation ids. In local/demo mode, when ClickHouse is not
    configured or clickhouse-connect is unavailable, returns local ids without
    failing the user-facing search.
    """
    observation_ids = [str(uuid.uuid4()) for _ in offers]
    if not offers:
        return []

    owns_client = client is None
    if client is None:
        client = _clickhouse_client()
    if client is None:
        return [f"local:{observation_id}" for observation_id in observation_ids]

    events = [build_clickhouse_price_event(spec, offer) for offer in offers]
    rows = [
        [event[column] for column in CLICKHOUSE_PRICE_EVENTS_COLUMNS]
        for event in events
    ]
    try:
        client.insert(
            os.environ.get("CLICKHOUSE_TABLE", "price_events"),
            rows,
            column_names=list(CLICKHOUSE_PRICE_EVENTS_COLUMNS),
        )
    finally:
        if owns_client and hasattr(client, "close"):
            client.close()
    return observation_ids


def _persist_observation(spec: ProductSpec, offer: Offer) -> str:
    """
    Insert one row into ClickHouse pricepilot.price_events and return the row id.

    Schema: ../clickhouse-setup.sql.

    Demo behavior: return a stable-looking id even when ClickHouse credentials or
    clickhouse-connect are unavailable. That keeps Hermes runnable while the DB
    integration is wired separately.
    """
    return store_price_events(spec, [offer])[0]


def _clickhouse_client() -> Any:
    if not os.environ.get("CLICKHOUSE_HOST") or not os.environ.get("CLICKHOUSE_PASSWORD"):
        return None
    try:
        import clickhouse_connect
    except ModuleNotFoundError:
        return None

    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ.get("CLICKHOUSE_USER", "nimble_loader"),
        password=os.environ["CLICKHOUSE_PASSWORD"],
        database=os.environ.get("CLICKHOUSE_DATABASE", "pricepilot"),
        secure=True,
    )


def _canonical_product_id(spec: ProductSpec) -> str:
    parts = [spec.category, spec.brand, spec.model]
    if spec.color:
        parts.append(spec.color)
    if spec.size:
        parts.extend([spec.size.system, spec.size.gender, f"{spec.size.value:g}"])
    slug = re.sub(r"[^a-z0-9]+", "-", " ".join(parts).lower()).strip("-")
    return slug or "product"


def _clickhouse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


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


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
    value = _first_present(item, keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _labeled_size_matches(raw_size: str, requested: float) -> bool:
    return any(abs(candidate - requested) < 0.01 for candidate in _explicit_size_values(raw_size))


def _explicit_size_values(raw_size: str) -> list[float]:
    values: list[float] = []
    text = raw_size.lower()
    patterns = [
        r"(?:shoe|clothing)?[_\-\s]*size[_\-\s]*(?:us[_\-\s]*)?(?:men|mens|women|womens)?[_\-\s]*(\d+(?:[\.-]\d+)?)\b",
        r"\b(?:men|mens|women|womens)[_\-\s]+(?:us[_\-\s]*)?(\d+(?:[\.-]\d+)?)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = _to_float(match.group(1).replace("-", "."))
            if value is not None:
                values.append(value)
    return values


def _terminal_size_matches(raw_size: str, requested: float) -> bool:
    requested_text = re.escape(f"{requested:g}").replace(r"\.", r"[\.-]")
    text = raw_size.lower()
    return bool(re.search(rf"(?:^|[_\-\s]){requested_text}(?:\s*$|[/#?])", text))


def _size_matches(raw_size: str, requested: float) -> bool:
    candidates = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw_size)]
    return any(abs(candidate - requested) < 0.01 for candidate in candidates)


def _shoe_gender_matches(gender: Gender, text: str) -> bool:
    if gender == "unisex":
        return True

    normalized = f" {text.lower()} "
    has_men = bool(re.search(r"(^|[^a-z0-9])(men|men's|mens|man's|male)([^a-z0-9]|$)", normalized))
    has_women = bool(re.search(r"(^|[^a-z0-9])(women|women's|womens|woman's|female|ladies)([^a-z0-9]|$)", normalized))
    has_kids = bool(re.search(r"(^|[^a-z0-9])(kids|kid's|youth|boys|girls|children)([^a-z0-9]|$)", normalized))
    has_unisex = bool(re.search(r"(^|[^a-z0-9])(unisex|adult)([^a-z0-9]|$)", normalized))

    if gender == "men":
        return has_men or has_unisex or not (has_women or has_kids)
    if gender == "women":
        return has_women or has_unisex or not (has_men or has_kids)
    if gender == "kids":
        return has_kids or not (has_men or has_women or has_unisex)
    return True


def _color_matches(requested: str, actual: str) -> bool:
    requested_tokens = _tokens(requested)
    if not requested_tokens:
        return True
    actual_tokens = _tokens(actual)
    return requested_tokens.issubset(actual_tokens)


def _condition_matches(condition: Condition, title: str, raw_condition: Any = None) -> bool:
    if condition == "any":
        return True

    text = " ".join(str(part or "") for part in (title, raw_condition)).lower()
    non_new_terms = (
        "renewed",
        "refurbished",
        "open box",
        "open-box",
        "used",
        "preowned",
        "pre-owned",
        "second hand",
    )
    has_non_new = any(term in text for term in non_new_terms)

    if condition in {"new", "ds"}:
        return not has_non_new
    if condition == "used":
        return has_non_new
    return True


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
        "size": (
            {
                "system": spec.size.system,
                "gender": spec.size.gender,
                "value": spec.size.value,
            }
            if spec.size
            else None
        ),
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
