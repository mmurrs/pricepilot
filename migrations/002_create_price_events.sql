-- 002 — Create pricepilot.price_events
--
-- Append-only time-series: one row per retailer/check. Read the
-- latest price per retailer per product with:
--   argMax(price, timestamp) BY (product_id, source)
--
-- Anonymous searches may pass user_id = '' or a session UUID — the
-- column is just a String.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS — safe to re-run.
-- Depends on: 001

CREATE TABLE IF NOT EXISTS pricepilot.price_events
(
    user_id      String,
    product_id   String,                    -- canonical key
    product_name String,
    url          String,                    -- exact URL scraped for THIS observation
    source       LowCardinality(String),    -- 'amazon' | 'walmart' | ...
    price        Float64,
    currency     String DEFAULT 'USD',
    timestamp    DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (product_id, source, timestamp);
