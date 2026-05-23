# Nimble — Cross-Marketplace Price Index

One-line: given `(brand, model, color, size)`, return the cheapest live offer across Amazon, Walmart, StockX, and eBay — and persist every observation to ClickHouse so price history is queryable over time.

**Team:** Matt
**Sponsor tools:** Nimble (search/scrape), ClickHouse (storage + analytics)
**Demo video:** _TBD_

Canonical query: **"I want to purchase a Nike shoe size 10.5 color white."**

---

## Architecture

Two-layer scrape per platform:

1. **SERP layer** — keyword → list of candidate parent listings. Cheap, structured.
2. **Detail layer** — pick the right parent, resolve to the *child* SKU for the requested size+color, fetch buybox/in-stock/offers.

Persist every detail-layer response as one row in ClickHouse `listings_observations`.

```
[user spec] -> SERP search -> [parent listing(s)]
                                    |
                                    v
                       resolve color+size -> child SKU
                                    |
                                    v
                            product detail call
                                    |
                                    v
                          one row per observation -> ClickHouse
```

## Build order (easiest → hardest)

| Phase | Platforms | Why this order |
|---|---|---|
| v1 | Amazon + Walmart | Both have clean SERP + per-SKU APIs. Validates schema. |
| v2 | + StockX | Sneaker pricing truth, but bot-walled; needs unofficial GraphQL or scraping. |
| v3 | + eBay | Official Browse API is free and clean — easier than StockX — but variants are aspect-based and noisy, so push to last. |

## Per-platform capability matrix

| Platform | SERP source | Detail source | Variant model | Notes |
|---|---|---|---|---|
| Amazon | Surf `/api/v1/amazon/search` (~$0.005) | Surf `/api/v1/amazon/product` (~$0.01) | Parent ASIN + child ASIN per (size × color) | Use the product API. Do **not** scrape HTML PDPs. |
| Walmart | Surf or Hirescrape | Per-item endpoint | `item_id` + `variantFieldsMap` | Field names differ from Amazon; same flow. |
| StockX | Scrape only (bot-walled) | Unofficial GraphQL by product URN | Size = variant; condition implicit (new/DS) | Selectors break often. Cache aggressively. |
| eBay | Official Browse API (app key) | Official `itemId` endpoint | Aspect-based variants, inconsistent | Active listings easy; sold/comps require Marketplace Insights API. |

## Exact-color search flow (canonical)

Input: `{brand, model, color, size_us_men}`

1. SERP search with `"{brand} {model} {color}"` (e.g. `"nike killshot 2 lucid green"`).
2. From SERP results, pick the parent listing whose title/description matches the requested color.
3. Pull the variant map from that parent (Amazon: `dimensionValuesDisplayData`; Walmart: `variantFieldsMap`; etc.).
4. Find the child SKU where `(size, color) == requested`.
5. Call the platform's product-detail endpoint on that child SKU.
6. Insert one row into `listings_observations`.

## Color normalization

Color strings differ wildly across platforms. Keep both:

- `color_raw` — exactly what the platform returned.
- `color_normalized` — canonical slug.

Examples for Killshot 2 "Sail/Lucid Green":

| Platform | color_raw |
|---|---|
| Amazon | `Sail Lucid Green Gum Yellow 432997 111` |
| StockX | `Sail/Lucid Green-Gum Yellow` |
| Nike | `White/Lucid Green` |
| Canonical | `sail-lucid-green` |

Maintain a separate `color_aliases` table mapping `(platform, color_raw) → color_normalized`. Build it incrementally as new colorways appear.

---

## ClickHouse schema

One row per observation (per scrape). **Don't dedupe** — price history is the point.

```sql
CREATE TABLE listings_observations (
  observed_at        DateTime64(3, 'UTC'),
  source             LowCardinality(String),  -- 'amazon','walmart','stockx','ebay'
  source_listing_id  String,                  -- ASIN, item_id, URN, etc.
  parent_listing_id  String,                  -- parent ASIN / product group

  brand              LowCardinality(String),
  model              String,
  model_normalized   String,                  -- 'killshot-2'
  color_raw          String,
  color_normalized   LowCardinality(String),  -- 'sail-lucid-green'
  size_raw           String,
  size_us_men        Decimal(4,1),

  price              Decimal(10,2),
  currency           LowCardinality(String),
  original_price     Decimal(10,2),           -- strikethrough/MSRP; NULL if none
  in_stock           UInt8,
  condition          LowCardinality(String),  -- 'new','used','ds'
  seller_id          String,
  seller_name        String,
  is_buybox          UInt8,
  shipping_cost      Decimal(10,2),
  url                String,

  raw_payload        String CODEC(ZSTD(3))    -- full JSON, for re-parsing later
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(observed_at)
ORDER BY (source, model_normalized, color_normalized, size_us_men, observed_at)
TTL observed_at + INTERVAL 2 YEAR;
```

Companion dim table for cross-platform joins:

```sql
CREATE TABLE products (
  canonical_id       String,
  brand              LowCardinality(String),
  model_normalized   String,
  color_normalized   LowCardinality(String),
  size_us_men        Decimal(4,1)
) ENGINE = ReplacingMergeTree
ORDER BY (brand, model_normalized, color_normalized, size_us_men);
```

### Schema design notes

- **Keep `raw_payload`.** Schemas drift; back-filling new fields is free if you stored the raw response.
- **One row per scrape, never UPDATE.** "Current price" = `argMax(price, observed_at) GROUP BY canonical_id, source`.
- **`size_us_men` as Decimal(4,1)** so 11.5 sorts correctly. Keep `size_raw` for women's, EU, kids.
- **`is_buybox`** matters on Amazon (3rd-party offers) and eBay (multiple listings of the same SKU). On StockX it's always 1.

### Common queries

```sql
-- Cheapest live price for a SKU across platforms
SELECT source, argMax(price, observed_at) AS current_price, max(observed_at) AS last_seen
FROM listings_observations
WHERE model_normalized = 'killshot-2'
  AND color_normalized = 'sail-lucid-green'
  AND size_us_men = 11.5
  AND in_stock = 1
GROUP BY source
ORDER BY current_price ASC;

-- Price history for one SKU on one platform
SELECT toStartOfHour(observed_at) AS t, min(price) AS min_price
FROM listings_observations
WHERE source = 'amazon'
  AND source_listing_id = 'B0DVFCSZGR'
GROUP BY t ORDER BY t;
```

---

## Learnings & watchouts

From the 2026-05-23 Killshot 2 size-11.5 dry run.

### Things that worked

- **Surf `/amazon/search` was perfect for SERP.** Clean JSON, ASIN + price + rating + review count, ~$0.005/call.
- **The conceptual flow (SERP → variant map → child SKU) is correct.** When child ASINs were live, prices came back accurately.

### Watchouts

1. **Don't scrape Amazon HTML for prices — use the product API.**
   Scraping 10+ HTML pages (~1MB each) and regex-hunting for `priceToPay` / `corePriceDisplay` / `apex_desktop` is a dead end. Amazon loads per-variant offers via XHR, so the static HTML often shows "currently unavailable" even when the SKU is buyable. Surf's `/api/v1/amazon/product` returns buybox + offer listing in clean JSON. **Rule:** never scrape an Amazon PDP if a structured product endpoint exists.

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

9. **Size is decimal, not integer or string.**
   `Decimal(4,1)` for `size_us_men` so 11.5 sorts between 11 and 12. Keep `size_raw` for women's / EU / kids.

10. **Watch for `payment: null` on paid x402 calls.**
    First Surf call returned `protocol: x402, network: base, price: $0.005, payment: null` — call worked but no on-chain settlement was recorded. Confirm with AgentCash whether this is a free tier / cached response before relying on per-call cost forecasts.

## Open questions

- Surf endpoint for Walmart parity, or Hirescrape's scraper for Walmart too?
- StockX: live with unofficial GraphQL, or wait for paid API access?
- eBay: sold-comp data (Marketplace Insights API requires approval), or only active listings for v1?
- Scrape frequency: hourly per SKU? Daily? Only on user request? Affects ClickHouse volume + cost.

## How to run locally

_TBD — once ingestion script lands, document `.env.local` keys (`NIMBLE_API_KEY`, `CLICKHOUSE_URL`) and the entrypoint command here._
