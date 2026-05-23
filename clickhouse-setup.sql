-- =====================================================================
-- ClickHouse Cloud setup — UNIFIED multi-source schema
-- Source of truth: ./architecture.md  (## ClickHouse Schema)
--
-- Supersedes the per-retailer `scraping.amazon_products` table that
-- earlier versions of this file used to create. The unified
-- `price_events` table stores rows for ALL retailers (amazon, walmart,
-- target, best_buy, home_depot, ebay, stockx) distinguished by the
-- `source` column. `tracked_products` holds the user → product
-- watchlist for the alert/poller flow.
--
-- Run each numbered block as a separate statement in the SQL Console.
-- =====================================================================


-- ---------------------------------------------------------------------
-- STEP 1 — Generate a strong password (run ALONE, copy the value)
-- ---------------------------------------------------------------------
-- Save to the shared 1Password vault immediately. ClickHouse stores
-- only the sha256 hash; lose this string and you can only rotate.
SELECT replaceAll(base64Encode(randomString(24)), '=', '') AS password;


-- ---------------------------------------------------------------------
-- STEP 2 — Database (idempotent)
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS scraping;


-- ---------------------------------------------------------------------
-- STEP 3 — Drop the v1 per-retailer table (DESTRUCTIVE)
-- ---------------------------------------------------------------------
-- Earlier this file created `scraping.amazon_products` (Amazon-only,
-- denormalized). The architecture moved to a unified `price_events`
-- table; the old one is now an orphan.
--
-- SAFE TO RUN IF: the table is empty or holds only throwaway test rows.
-- If you've already INSERTed real data you want to keep, SKIP this step
-- and run a backfill first:
--   INSERT INTO scraping.price_events (product_id, source, url, price, ...)
--   SELECT asin, 'amazon', url, web_price, ...
--   FROM scraping.amazon_products;
DROP TABLE IF EXISTS scraping.amazon_products;


-- ---------------------------------------------------------------------
-- STEP 4 — price_events: time-series of every retailer/check
-- ---------------------------------------------------------------------
-- Schema mirrors architecture.md lines 230-243. Append-only. The agent
-- writes one row per successful retailer fetch, regardless of source.
-- Use `argMax(price, timestamp) BY (product_id, source)` for "current
-- price per retailer."
--
-- Anonymous searches (no logged-in user, e.g. the search/ Phase-1 flow)
-- can pass user_id = '' or a session UUID — the column is just a String.
CREATE TABLE IF NOT EXISTS scraping.price_events
(
    user_id      String,
    product_id   String,                    -- canonical key: lower(brand + ' ' + model_token)
    product_name String,
    query        String,                    -- original user query for traceability
    url          String,
    source       LowCardinality(String),    -- 'amazon' | 'walmart' | 'target' | 'best_buy' | 'home_depot' | 'ebay' | 'stockx'
    price        Float64,
    currency     String DEFAULT 'USD',
    in_stock     UInt8,
    is_resale    UInt8 DEFAULT 0,           -- 0 = new-retail, 1 = secondary market (ebay/stockx)
    timestamp    DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (product_id, source, timestamp);


-- ---------------------------------------------------------------------
-- STEP 5 — tracked_products: user → product watchlist with thresholds
-- ---------------------------------------------------------------------
-- Schema mirrors architecture.md lines 245-253. Upsert by (user_id,
-- product_id); ReplacingMergeTree dedupes on the ORDER BY key during
-- merges, so re-INSERTs of the same row collapse.
CREATE TABLE IF NOT EXISTS scraping.tracked_products
(
    user_id      String,
    product_id   String,
    product_name String,
    threshold    Float64,
    active       UInt8 DEFAULT 1,
    created_at   DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree()
ORDER BY (user_id, product_id);


-- ---------------------------------------------------------------------
-- STEP 6 — Create the SQL user
-- ---------------------------------------------------------------------
-- Password MUST be a string literal (CH gotcha — no subquery here).
-- Paste the value from STEP 1.
CREATE USER nimble_loader
  IDENTIFIED WITH sha256_password BY '<<PASTE_PASSWORD_HERE>>';


-- ---------------------------------------------------------------------
-- STEP 7 — Role + grants (covers BOTH tables via scraping.*)
-- ---------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS scraper_writer;
GRANT SELECT, INSERT, SHOW TABLES ON scraping.* TO scraper_writer;
GRANT scraper_writer TO nimble_loader;

-- Make the role active by default; otherwise clients have to SET ROLE
-- on each connection.
SET DEFAULT ROLE scraper_writer TO nimble_loader;


-- ---------------------------------------------------------------------
-- STEP 8 — UI-only steps (NOT runnable in SQL Console)
-- ---------------------------------------------------------------------
-- 8a. Settings → Network → whitelist hermes' egress IP.
--     curl -s https://api.ipify.org   (from hermes)
-- 8b. Top of cluster page → "Connect" button → copy hostname into
--     CLICKHOUSE_HOST in .env.local.


-- =====================================================================
-- VERIFICATION — run after STEP 7 to confirm everything landed
-- =====================================================================

-- V1: database exists
SELECT name FROM system.databases WHERE name = 'scraping';
-- expected: 1 row, name = 'scraping'

-- V2: old v1 table is gone
SELECT count() AS amazon_products_still_exists
FROM system.tables
WHERE database = 'scraping' AND name = 'amazon_products';
-- expected: 0

-- V3: price_events exists with the 11 columns from architecture.md
SELECT name, type
FROM system.columns
WHERE database = 'scraping' AND table = 'price_events'
ORDER BY position;
-- expected: 11 rows in this exact order:
--   user_id String, product_id String, product_name String,
--   query String, url String, source LowCardinality(String),
--   price Float64, currency String, in_stock UInt8,
--   is_resale UInt8, timestamp DateTime

-- V4: tracked_products exists with 6 columns
SELECT name, type
FROM system.columns
WHERE database = 'scraping' AND table = 'tracked_products'
ORDER BY position;
-- expected: 6 rows: user_id, product_id, product_name, threshold,
--   active, created_at

-- V5: engines and sort keys are correct
SELECT name, engine, sorting_key
FROM system.tables
WHERE database = 'scraping' AND name IN ('price_events', 'tracked_products')
ORDER BY name;
-- expected:
--   price_events     | MergeTree          | product_id, source, timestamp
--   tracked_products | ReplacingMergeTree | user_id, product_id

-- V6: user exists with sha256_password auth
SELECT name, auth_type FROM system.users WHERE name = 'nimble_loader';
-- expected: 1 row, auth_type contains 'sha256_password'

-- V7: role exists
SELECT name FROM system.roles WHERE name = 'scraper_writer';
-- expected: 1 row

-- V8: role has the 3 expected grants on scraping.*
SELECT access_type, database, table
FROM system.grants
WHERE role_name = 'scraper_writer'
ORDER BY access_type;
-- expected: 3 rows — INSERT, SELECT, SHOW TABLES, all on database='scraping', table=NULL

-- V9: user is granted the role and it's the default
SELECT user_name, granted_role_name, granted_role_is_default, with_admin_option
FROM system.role_grants
WHERE user_name = 'nimble_loader';
-- expected: 1 row, granted_role_name='scraper_writer', granted_role_is_default=1

-- V10: human-readable summary (matches what architecture.md shows)
SHOW GRANTS FOR nimble_loader;
SHOW GRANTS FOR scraper_writer;

-- V11: smoke INSERT (will be deleted in V12)
INSERT INTO scraping.price_events
  (user_id, product_id, product_name, query, url, source, price, in_stock, is_resale)
VALUES
  ('', 'test:setup-smoke', 'setup smoke test', 'unit test', 'about:blank', 'amazon', 0.01, 0, 0);

-- V12: confirm INSERT landed, then DELETE the smoke row
SELECT count() AS smoke_rows
FROM scraping.price_events
WHERE product_id = 'test:setup-smoke';
-- expected: 1
ALTER TABLE scraping.price_events
  DELETE WHERE product_id = 'test:setup-smoke';


-- =====================================================================
-- POST-LAUNCH — run AFTER the agent starts writing real rows
-- =====================================================================

-- P1: per-source row counts and freshness
SELECT source,
       count() AS rows,
       max(timestamp) AS most_recent,
       countIf(in_stock = 1) AS in_stock_rows
FROM scraping.price_events
GROUP BY source
ORDER BY source;

-- P2: 24h data-quality check (>0.95 expected for each retailer)
SELECT source,
       countIf(price > 0) / count() AS pct_with_price
FROM scraping.price_events
WHERE timestamp > now() - INTERVAL 1 DAY
GROUP BY source
ORDER BY source;

-- P3: cross-source price comparison for a given product (swap in real product_id)
SELECT source,
       argMax(price, timestamp) AS current_price,
       argMax(in_stock, timestamp) AS in_stock,
       argMax(url, timestamp) AS url,
       max(timestamp) AS observed_at
FROM scraping.price_events
WHERE product_id = '<paste-a-product_id-here>'
GROUP BY source
ORDER BY current_price ASC;

-- P4: active watchlist size
SELECT count() AS active_tracked
FROM scraping.tracked_products FINAL
WHERE active = 1;
