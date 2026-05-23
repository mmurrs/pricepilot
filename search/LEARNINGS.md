# Search — Learnings & Watchouts

From the 2026-05-23 Killshot 2 size-11.5 dry run plus prior Surf/Nimble experimentation. Read before implementing the tool calls in [`tools.py`](./tools.py).

## Things that worked

- **Surf `/amazon/search` was perfect for SERP.** Clean JSON: ASIN + price + rating + review count, ~$0.005/call.
- **The conceptual flow (SERP → variant map → child SKU → price) is correct.** When child ASINs were live, prices came back accurately.
- **Nimble's `amazon_pdp` returns structured fields** (`web_price`, `list_price`, `availability`, `product_title`). Use this, not HTML.

## Path validation (2026-05-23, `nike killshot 2 white`)

Ran [`test_all_paths.py`](./test_all_paths.py) across 13 candidate paths to find which actually return real Amazon SERP data. Summary table:

| Path | OK | Time | Bytes | ASINs | Cost |
|---|---|---|---|---|---|
| Nimble `amazon_serp` baseline (formats=md+html) | ✓ | 12.2s | 2.0MB | 136 | tbd |
| Nimble `amazon_serp` localization=True | ✓ | 9.6s | 2.3MB | 139 | tbd |
| Nimble `amazon_serp` driver=wsa-vx10 | ✓ | 9.9s | 2.0MB | 127 | tbd |
| Nimble `amazon_serp` driver=wsa-vx6 | ✗ | 3.0s | 2.3KB | 0 | (Akamai stub) |
| Nimble `amazon_serp` driver=wsa-12m | ✓ | 16.1s | 2.2MB | 134 | tbd |
| Nimble `amazon_serp` unblocker=True | ✓ | 8.4s | 1.9MB | 137 | tbd |
| Nimble `amazon_serp` proxy=residential | ✓ | 10.7s | 2.3MB | 133 | tbd |
| Nimble `amazon_serp` country=US | ✓ | 7.1s | 2.1MB | 138 | tbd |
| Nimble `google_search → amazon.com` | ✓ | 5.7s | 0.7MB | 16 | tbd |
| **Firecrawl via AgentCash** | ✓ | <2s | 326KB | 141 | $0.0126 |

### Calibration of the "bot wall" claim

My earlier read — "Nimble is bot-walled by Akamai" — was **wrong**. The 2.3KB `bm-verify` stub only appeared when:

- `formats=["markdown"]` (without `html`)
- driver was `wsa-vx6` (the cheap tier)

When `formats=["markdown","html"]` is set on the same agent, Nimble returns the full ~2MB Amazon SERP with 130+ ASINs. The empty `data.parsing` list (48 success-shells with `entities=None`) is a *different* issue — Nimble's structured parser couldn't fill its schema, but the underlying HTML/markdown fetch is good.

### Implications for tool design

- **Don't trust the structured `parsing` field on `amazon_serp`** — it returns 48 empty shells. Use the markdown/html and parse client-side.
- **Always request `formats=["markdown","html"]`** — the SDK defaults can be misleading.
- **Firecrawl is faster (<2s vs 7-16s) and cheaper to reason about** ($0.0126 known cost vs Nimble's per-page billing). Tradeoff: smaller payload means fewer products surfaced (141 vs 130-140 — basically a wash).
- **`wsa-vx6` is genuinely bot-walled.** Don't fall back to it even for cost reasons.

### What changed in the test rig

The first version of the test broke because I called `.keys()` on `parsing`, which is a list, not a dict. After fixing, every Nimble config except `wsa-vx6` returned real data. The 2.3KB Akamai stub is real but rare.

## Watchouts

1. **Don't scrape Amazon HTML for prices — use the product API.**
   Scraping 10+ HTML pages (~1MB each) and regex-hunting for `priceToPay` / `corePriceDisplay` / `apex_desktop` is a dead end. Amazon loads per-variant offers via XHR, so the static HTML often shows "currently unavailable" even when the SKU is buyable. Surf's `/api/v1/amazon/product` (or Nimble's `amazon_pdp` agent) returns buybox + offer listing in clean JSON.
   **Rule:** never scrape an Amazon PDP if a structured product endpoint exists.

2. **The SERP price is the *default-rendered* size, not your size.**
   A "$39.99" SERP row can resolve to $79+ at size 11.5, or to "currently unavailable." Always resolve to the child ASIN before reporting a price.

3. **`dimensionValuesDisplayData` is the variant map on Amazon.**
   Format: `"<child_asin>": ["<size>", "<color_string>"]`. Pull it from the parent product API response, filter to `(size, color)`, fetch that child ASIN.

4. **Many child ASINs return "currently unavailable" via static fetch.**
   Real signal *sometimes* (truly OOS), false negative *sometimes* (per-variant offers gated behind XHR). The product API resolves both cases.

5. **"Cheapest" is ambiguous — pin the spec before searching.**
   Cheapest by colorway? Buybox only, or 3rd-party offers? New only, or used? Always require `color` + `condition` in the input spec. Exact-color-first removes most of this ambiguity.

6. **Amazon HTML pages are 600KB–1.1MB each.**
   Auto-persisted to disk by the scraper, but slow and expensive to chain. Prefer structured endpoints; reserve HTML scraping for platforms with no API (StockX).

7. **Don't dedupe on write.**
   One row per scrape. Use `argMax(price, observed_at)` for "current price." That's how price history gets built for free.

8. **Color normalization is its own subsystem.**
   Don't try to clean color strings on write. Store `color_raw`, maintain `color_aliases`, normalize at query time or in a materialized view. Platforms invent new color suffixes constantly.

   Example for Killshot 2 "Sail/Lucid Green":

   | Platform | color_raw |
   |---|---|
   | Amazon | `Sail Lucid Green Gum Yellow 432997 111` |
   | StockX | `Sail/Lucid Green-Gum Yellow` |
   | Nike | `White/Lucid Green` |
   | Canonical | `sail-lucid-green` |

9. **Size is decimal, not integer or string.**
   `Decimal(4,1)` for `size_us_men` so 11.5 sorts between 11 and 12. Keep `size_raw` for women's / EU / kids variants.

10. **Watch for `payment: null` on paid x402 calls.**
    First Surf call returned `protocol: x402, network: base, price: $0.005, payment: null` — call worked but no on-chain settlement was recorded. Confirm with AgentCash whether this is a free tier / cached response before relying on per-call cost forecasts.

11. **StockX is hard. Defer it.**
    No official API at the tier we have. Unofficial GraphQL works but selectors break. Bot-walling is aggressive — prepare to cache, retry with backoff, and fail soft (`return None`, never raise into the agent loop). Also: lowest "ask" is the cheapest *seller offer*, not a guaranteed-shippable buybox. Don't conflate.

12. **eBay is deferred behind StockX even though the API is cleaner.**
    eBay's official Browse API is free with an app key and returns clean JSON. The reason it's deferred: variants are "aspect-based" — every seller defines their own aspect names (`"Shoe Size"` vs `"US Size"` vs `"Men's Size"`), so resolving to a canonical `(size, color)` is an alias-table problem. Worth doing, just not on day 1.

## Build-order rationale

| Phase | Why this order |
|---|---|
| Amazon only | Single platform proves the SERP → variant → child → price → ClickHouse path. If this doesn't work, nothing else will. |
| + Walmart | Same shape, different field names. Validates the *abstraction* of the per-platform resolver. |
| + StockX | Sneaker pricing truth-source, but bot-walled. Add only after the abstraction is solid so failures are isolated. |
| (future) eBay | Aspect-based variants need an alias table. Tractable, just expensive vs. payoff for a 1-day hackathon. |

## Open questions

- Surf endpoint for Walmart parity, or do we lean on Nimble's `walmart_pdp` agent (the team's current bet per [`../architecture.md`](../architecture.md))?
- StockX: live with unofficial GraphQL today, or wait for paid API access?
- eBay sold-comp data (Marketplace Insights API requires approval) — out of scope for hack day.
- Scrape frequency: hourly per SKU? Daily? Only on user request? Affects ClickHouse volume + cost.
- The team's v1 ClickHouse schema is `scraping.amazon_products` (Amazon-only, denormalized). When does it migrate to the multi-source `listings_observations` shape? Probably at the v2 boundary when Walmart lands.
