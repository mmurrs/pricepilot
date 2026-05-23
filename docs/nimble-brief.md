# Nimble — Hackathon Brief

> Reference/prep doc for PricePilot. Goal: zero-to-first-call as fast as possible. All snippets verbatim from Nimble docs.

---

## Languages — not just Python

| Surface | Use when |
|---|---|
| **Python SDK** (`pip install nimble-python`) | Default for Hermes / our backend |
| **Node SDK** | If Hermes is JS |
| **Go SDK** | If anyone wants compiled |
| **CLI** | One-off scrapes, debugging, demo screenshots |
| **MCP server** (`https://mcp.nimbleway.com/mcp`, Bearer auth) | Lets Claude / Cursor / any MCP client call Nimble as native tools — zero glue code |
| **REST + curl** | Anything else |

Connectors with first-class support: Anthropic SDK, Claude AI Connectors, Google ADK, LangChain, OpenAI, Smithery, Databricks.

---

## 60-second setup

```bash
# 1. Sign up — free 5,000 pages, no card
open https://online.nimbleway.com/signup

# 2. Get key
open https://online.nimbleway.com/account-settings/api-keys

# 3. Export
export NIMBLE_API_KEY=nbl_xxx

# 4a. Python
pip install nimble-python

# 4b. Node
npm install @nimbleway/sdk

# 4c. Or skip SDK entirely — MCP server
# Add to ~/.cursor/mcp.json or claude config:
# {
#   "nimble": {
#     "url": "https://mcp.nimbleway.com/mcp",
#     "headers": {"Authorization": "Bearer $NIMBLE_API_KEY"}
#   }
# }
```

---

## Pre-built retail agents (the moat)

| Agent | Input | Output highlights |
|---|---|---|
| `amazon_pdp` | `asin`, `zip_code`(opt) | `web_price`, `list_price`, `product_title`, `brand`, `average_of_reviews`, `availability`, `image_url` |
| `amazon_serp` | search query | paginated results w/ ASINs |
| `amazon_category` | category | paginated |
| `walmart_pdp` | URL | localized price |
| `walmart_search` | query | paginated |
| `target_pdp` | URL | localized |
| `best_buy_pdp` | URL | localized |
| `home_depot_pdp` | URL | localized |
| `google_search` | query | SERP |
| `google_search_aio` | query | AI Overview |
| `google_maps_search` | query | maps results |

No pre-built: eBay, StockX, Mercari, Poshmark, Etsy, AliExpress, Newegg, B&H, Costco. Use `agent.generate()` (below).

---

## The fan-out (Python, async)

```python
import asyncio, os
from nimble_python import AsyncNimble

client = AsyncNimble(api_key=os.environ["NIMBLE_API_KEY"])

async def find_cheapest(query: str) -> list[dict]:
    # Parallel discovery
    a_search, w_search = await asyncio.gather(
        client.agent.run(agent="amazon_serp",    params={"query": query}),
        client.agent.run(agent="walmart_search", params={"query": query}),
    )
    asin       = a_search.data["results"][0]["asin"]
    walmart_url = w_search.data["results"][0]["url"]

    # Parallel PDPs (authoritative price)
    pdps = await asyncio.gather(
        client.agent.run(agent="amazon_pdp",  params={"asin": asin, "zip_code": "10001"}),
        client.agent.run(agent="walmart_pdp", params={"url": walmart_url}),
    )
    return [
        {"retailer": "amazon",  "price": pdps[0].data["web_price"], "url": f"https://amazon.com/dp/{asin}", "title": pdps[0].data["product_title"]},
        {"retailer": "walmart", "price": pdps[1].data["price"],     "url": walmart_url},
    ]
```

To extend to Target / Best Buy / Home Depot, resolve the URL via `google_search` first (`query + site:target.com`), then call the matching `*_pdp` agent.

---

## Resale stretch — generate custom agents at boot

```python
client.agent.generate(
    url="https://www.ebay.com/sch/i.html?_nkw=sony+wh-1000xm5",
    prompt="Extract title, price, condition, seller_rating, url per listing card",
    agent_name="ebay_search",
    output_schema={
        "type": "object",
        "properties": {
            "results": {"type": "array", "items": {"type": "object", "properties": {
                "title":         {"type": "string"},
                "price":         {"type": "number"},
                "condition":     {"type": "string"},
                "seller_rating": {"type": "number"},
                "url":           {"type": "string"},
            }}}
        },
    },
)
# Then:
ebay = await client.agent.run(agent="ebay_search", params={"query": "Sony WH-1000XM5"})
```

Same pattern for `stockx_search`, `mercari_search`, etc. **This is the demo flex** — pre-built agents for retail, AI-generated agents for the long tail, all in one app.

---

## Pricing math (back-of-envelope)

| API | Rate | Per "find_cheapest" call (5 PDPs) |
|---|---|---|
| WSA Nimble-managed (most retail) | $1.75 / 1k | $0.0088 |
| WSA community/custom | $1.60 / 1k | $0.008 |
| Search API | $1.00 / 1k inputs | n/a unless using `google_search` |

Free trial: **5,000 pages = ~1,000 fan-out queries.** Plenty for hackathon + demo.

Only **successful requests** are charged.

---

## Common gotchas

1. **Async by default**: `client.agent.run_async()` returns a `task_id` — poll `client.tasks.get(task_id)` until `status == "succeeded"`. For demo latency use `client.agent.run()` (sync) which blocks until done.
2. **ASIN vs URL**: `amazon_pdp` wants ASIN, others want URL. Get ASIN from `amazon_serp` results.
3. **Localization**: pass `localization=True` and country/zip for accurate prices (defaults to `90210`).
4. **Formats**: append `formats=["markdown", "screenshot"]` to any `agent.run` for free debugging artifacts.

---

## Useful links

- Signup: https://online.nimbleway.com/signup
- API keys: https://online.nimbleway.com/account-settings/api-keys
- Studio (visual builder): https://online.nimbleway.com/studio
- Docs index: https://docs.nimbleway.com/llms.txt
- MCP: https://mcp.nimbleway.com/mcp
- Pricing: https://docs.nimbleway.com/nimble-sdk/admin/pricing

---

## What to do right now

1. Sign up, grab key, `export NIMBLE_API_KEY=...`
2. `pip install nimble-python`
3. Run the `find_cheapest()` snippet above against a real product (`"Sony WH-1000XM5"`)
4. If it returns prices — wire it into Hermes as the `find_cheapest` tool
5. Stretch: `agent.generate()` an `ebay_search` agent for the resale demo
