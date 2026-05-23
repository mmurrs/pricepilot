-- =====================================================================
-- ClickHouse Cloud — recurring ops queries (safe to re-run anytime)
--
-- Initial provisioning (DB/table DDL, user/role/grants) lives in
-- clickhouse-setup.sql. This file only holds read-only checks and the
-- per-source/per-product queries the agent flow relies on.
--
-- Target DB: `pricepilot` (legacy `scraping` is untouched).
-- Run each numbered block as a separate statement in the SQL Console.
-- =====================================================================


-- =====================================================================
-- VERIFICATION — schema/grants drift checks
-- =====================================================================

-- V1: database exists
SELECT name FROM system.databases WHERE name = 'pricepilot';
-- expected: 1 row, name = 'pricepilot'

-- V2: price_events has the 8 columns from architecture.md
SELECT name, type
FROM system.columns
WHERE database = 'pricepilot' AND table = 'price_events'
ORDER BY position;
-- expected: 8 rows in this order:
--   user_id String, product_id String, product_name String,
--   url String, source LowCardinality(String),
--   price Float64, currency String, timestamp DateTime

-- V3: tracked_products has 7 columns
SELECT name, type
FROM system.columns
WHERE database = 'pricepilot' AND table = 'tracked_products'
ORDER BY position;
-- expected: 7 rows: user_id, product_id, product_name,
--   amazon_url, walmart_url, threshold, active

-- V4: engines and sort keys are correct
SELECT name, engine, sorting_key
FROM system.tables
WHERE database = 'pricepilot' AND name IN ('price_events', 'tracked_products')
ORDER BY name;
-- expected:
--   price_events     | MergeTree          | product_id, source, timestamp
--   tracked_products | ReplacingMergeTree | user_id, product_id

-- V5: human-readable grants summary
SHOW GRANTS FOR nimble_loader;
SHOW GRANTS FOR scraper_writer;
-- expected: SELECT, INSERT, SHOW TABLES on scraping.* AND pricepilot.*


-- =====================================================================
-- POST-LAUNCH — run while the agent is writing rows
-- =====================================================================

-- P1: per-source row counts and freshness
SELECT source,
       count() AS rows,
       max(timestamp) AS most_recent
FROM pricepilot.price_events
GROUP BY source
ORDER BY source;

-- P2: 24h data-quality check (>0.95 expected for each retailer)
SELECT source,
       countIf(price > 0) / count() AS pct_with_price
FROM pricepilot.price_events
WHERE timestamp > now() - INTERVAL 1 DAY
GROUP BY source
ORDER BY source;

-- P3: cross-source price comparison for a given product (swap in real product_id)
SELECT source,
       argMax(price, timestamp) AS current_price,
       argMax(url, timestamp) AS url,
       max(timestamp) AS observed_at
FROM pricepilot.price_events
WHERE product_id = '<paste-a-product_id-here>'
GROUP BY source
ORDER BY current_price ASC;

-- P4: active watchlist size
SELECT count() AS active_tracked
FROM pricepilot.tracked_products FINAL
WHERE active = 1;
