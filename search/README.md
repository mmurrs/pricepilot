# Search — Cheapest Product Tool

Tool the Hermes agent calls to answer **"find me the cheapest X."**

V1 supports explicit shoe demos and generic product searches: Hermes parses user
language into brand/model/category/color/size when available, calls one tool,
and receives a ranked offer response.

| Scope | Sources | Status |
|---|---|---|
| `source_scope="amazon"` | Amazon | implemented |
| `source_scope="retail"` | Amazon + Walmart | implemented |
| `source_scope="all"` | Amazon + Walmart + StockX | StockX stubbed |

Files in this folder:

- `tools.py` — Hermes-facing tool schema + Python implementation.
- `demo_find_cheapest.py` — local explicit demo runner.
- `LEARNINGS.md` — scraping/Nimble watchouts and schema rationale.

The shared ClickHouse schema lives in [`../clickhouse-setup.sql`](../clickhouse-setup.sql). The agent flow that calls this tool lives in [`../architecture.md`](../architecture.md).

---

## Hermes-Facing Tool

Hermes should expose exactly one search tool:

```python
find_cheapest_product(
    brand: str,
    model: str,
    size: {"system": "US", "gender": "men", "value": 11.5} | None = None,
    category: "shoes" | "electronics" | "toys" | "generic" = "generic",
    color: str | None = None,
    condition: "new" | "used" | "ds" | "any" = "new",
    postal_code: str = "10001",
    source_scope: "amazon" | "retail" | "all" = "amazon",
    query: str | None = None,
    user_id: str | None = None,
) -> CheapestOfferResponse
```

For the demo, use `source_scope="amazon"` or `source_scope="retail"` and require
explicit `brand` and `model`. `size` is optional so the tool can support generic
product searches, but Hermes should include it when the user asks for an exact
shoe variant. `color` is optional in the schema but should be present for shoes
when the user gives it, because it drastically reduces ambiguity.

### Python Integration

Hermes can import the schema and function directly:

```python
from search.tools import TOOL_SCHEMAS, find_cheapest_product

# Register this with the LLM/tool router.
tools = TOOL_SCHEMAS

# Call after Hermes has parsed the user message.
result = await find_cheapest_product(
    brand="Nike",
    model="Killshot 2",
    color="Sail/Lucid Green",
    size={"system": "US", "gender": "men", "value": 11.5},
    condition="new",
    postal_code="10001",
    source_scope="amazon",
    query="Find the cheapest Nike Killshot 2 Sail/Lucid Green men's size 11.5",
    user_id="telegram:123",
)
```

Hermes should treat `result.best is None` as "no verified buyable offer found."
Do not present unverified SERP prices.

### Example Tool Call

```json
{
  "brand": "Nike",
  "model": "Killshot 2",
  "color": "Sail/Lucid Green",
  "size": { "system": "US", "gender": "men", "value": 11.5 },
  "condition": "new",
  "postal_code": "10001",
  "source_scope": "amazon",
  "query": "Nike Killshot 2 Sail/Lucid Green size 11.5",
  "user_id": "telegram:123"
}
```

### Example Response

```json
{
  "spec": {
    "brand": "Nike",
    "model": "Killshot 2",
    "size": { "system": "US", "gender": "men", "value": 11.5 },
    "category": "shoes",
    "color": "Sail/Lucid Green",
    "condition": "new",
    "postal_code": "10001",
    "source_scope": "amazon"
  },
  "best": {
    "source": "amazon",
    "price": 74.96,
    "shipping_cost": 0,
    "total_price": 74.96,
    "currency": "USD",
    "url": "https://www.amazon.com/dp/B07SSV4CTT",
    "in_stock": true,
    "seller": "Liquidation Stations",
    "title": "Nike Mens Killshot 2 Leather",
    "confidence": 0.75,
    "observed_at": "2026-05-23T18:48:02+00:00"
  },
  "all_offers": [
    {
      "source": "amazon",
      "price": 74.96,
      "shipping_cost": 0,
      "total_price": 74.96,
      "currency": "USD",
      "url": "https://www.amazon.com/dp/B07SSV4CTT",
      "in_stock": true,
      "seller": "Liquidation Stations",
      "title": "Nike Mens Killshot 2 Leather"
    }
  ],
  "missing_sources": [],
  "observation_ids": ["local:..."]
}
```

`observation_ids` are ClickHouse row IDs when persistence is configured. During
demo runs without ClickHouse, the tool returns `local:<uuid>` so Hermes can keep
moving.

---

## Amazon V1 Implementation

The implemented Amazon path is:

1. Build a search query from brand/model/color, plus shoe gender and size when provided.
   Example: `On Cloud running shoes mens size 11`.
2. `amazon_serp(keyword=query, zip_code=postal_code, formats=["markdown", "html"])`.
3. Parse SERP markdown/html for ranked candidate ASINs.
4. Try the top ranked candidates, not just the first one.
5. `amazon_pdp(asin=color_asin, formats=["html"])`.
6. Parse Amazon `dimensionValuesDisplayData` from PDP HTML.
7. Resolve the exact child ASIN where `(size, color)` matches the request when size is provided.
8. `amazon_pdp(asin=child_asin, zip_code=postal_code)`.
9. Return the cheapest verified offer that still matches brand/model/color and, when provided, size.

Hard rule: never return a SERP price as the final price. SERP price is often for
the default-rendered size, not the requested size.

---

## Walmart Status

`source_scope="retail"` now runs Amazon + Walmart. Walmart uses this path:

1. `google_search(query + " site:walmart.com", country="US")`.
2. Extract Walmart `/ip/.../<product_id>` from ranked matching results.
3. `walmart_pdp(product_id=..., zipcode=postal_code)`.
4. Parse Walmart variant data for requested color and, when provided, shoe size.
5. Fetch the child item PDP and return a normal `Offer`.

The older docs mentioned a `walmart_search` agent. The live probe in
`test_nimble.py` found that this agent is not currently available in our Nimble
account, so use `google_search -> walmart_pdp` instead.

### Walmart / Retail Scope Example

This is the call shape Hermes should use for Amazon + Walmart:

```json
{
  "brand": "Nike",
  "model": "Killshot 2",
  "color": "Sail/Lucid Green",
  "size": { "system": "US", "gender": "men", "value": 11.5 },
  "condition": "new",
  "postal_code": "10001",
  "source_scope": "retail",
  "query": "Nike Killshot 2 Sail/Lucid Green size 11.5",
  "user_id": "telegram:123"
}
```

If Walmart has no verified in-stock matching offer, the response reports
`{"source": "walmart", "reason": "no_offer"}` in `missing_sources`.

---

## Local Demo

```bash
cd /Users/matt/agenticenghack
set -a && source .env.local && set +a
.venv/bin/python search/demo_find_cheapest.py \
  --brand Nike \
  --model "Killshot 2" \
  --color "Sail/Lucid Green" \
  --size 11.5
```

Validated live on 2026-05-23:

```text
Amazon: Nike Mens Killshot 2 Leather
Size/color: US men 11.5, Sail/Lucid Green
Best total: $74.96
URL: https://www.amazon.com/dp/B07SSV4CTT
```

Also validated:

```bash
.venv/bin/python search/demo_find_cheapest.py \
  --brand On \
  --model "Cloud running shoes" \
  --size 11
```

```text
Amazon: On Men's Cloud 6 Sneakers
Size: US men 11
Best total: $160.00
URL: https://www.amazon.com/dp/B0F7D5VHMP
```

---

## Hermes Responsibilities

Hermes should:

1. Parse user intent into the explicit fields above.
2. Ask a follow-up if the user asks for an exact shoe variant and `size` is missing.
3. Pass `user_id` and original `query` for traceability.
4. Use `source_scope="amazon"` for Amazon-only demo flows or `source_scope="retail"` for Amazon + Walmart.
5. Call `find_cheapest_product`.
6. Present `best` first, then optionally summarize `all_offers` and `missing_sources`.

Field guidance:

- `size.value` is optional. Include it for exact shoe pricing; omit it for generic product searches.
- `size.gender` should be explicit when `size` is provided. Defaulting to `"men"` is acceptable only when the user says "men's" or the demo prompt implies it.
- `color` is optional but should be filled when present in the user request.
- `postal_code` defaults to `10001`; set it from the user's location when available.
- If `best` is `null`, tell the user no verified in-stock offer was found and ask for color/model refinement.

For the demo, a good user prompt is:

```text
Find the cheapest Nike Killshot 2 Sail/Lucid Green in men's size 11.5
```

Hermes should structure that into the example JSON call above.
