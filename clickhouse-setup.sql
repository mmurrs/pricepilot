-- =====================================================================
-- ClickHouse Cloud setup — PricePilot schema (database: pricepilot)
-- Source of truth: ./architecture.md  (## ClickHouse Schema)
--
-- PricePilot is a price tracking + alert app:
--   tracked_products → user's watchlist (product + per-retailer URLs +
--                      price threshold)
--   price_events     → time-series log of observed prices, per retailer
--
Already done in an earlier iteration:
--   - database `scraping` (with `amazon_products`, `amazon_serp`) from
--     the v1 schema — kept on disk but DEAD; no role/user has grants on
--     it after STEP 5 below
--   - SQL user `nimble_loader` + role `scraper_writer` (default-role'd)
--   - password lives in 1Password vault "agenticenghack"
--
-- This file holds the remaining migration to get PricePilot live.
-- Run each numbered block as a separate statement in the SQL Console.
-- =====================================================================


-- ---------------------------------------------------------------------
-- STEP 1 — Database (idempotent)
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS pricepilot;


-- ---------------------------------------------------------------------
-- STEP 2 — price_events: time-series of every retailer/check
-- ---------------------------------------------------------------------
-- Append-only. One row per successful retailer fetch. Use
-- `argMax(price, timestamp) BY (product_id, source)` for "current
-- price per retailer."
--
-- Anonymous searches (no logged-in user) can pass user_id = '' or
-- a session UUID — the column is just a String.
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


-- ---------------------------------------------------------------------
-- STEP 3 — tracked_products: user watchlist with threshold
-- ---------------------------------------------------------------------
-- Upsert by (user_id, product_id); ReplacingMergeTree dedupes on the
-- ORDER BY key during merges, so re-INSERTs of the same row collapse.
-- Per-retailer URLs live here so the poller can fan out without
-- re-resolving products on every tick.
CREATE TABLE IF NOT EXISTS pricepilot.tracked_products
(
    user_id      String,
    product_id   String,
    product_name String,
    amazon_url   String,
    walmart_url  String DEFAULT '',
    threshold    Float64,
    active       UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree()
ORDER BY (user_id, product_id);


-- ---------------------------------------------------------------------
-- STEP 4 — Extend role grants to pricepilot.*
-- ---------------------------------------------------------------------
-- nimble_loader / scraper_writer were created earlier with grants on
-- scraping.*; add the same on pricepilot.* so the pipeline can write
-- to the new DB. Default role is already set on the user.
GRANT SELECT, INSERT, SHOW TABLES ON pricepilot.* TO scraper_writer;


-- ---------------------------------------------------------------------
-- STEP 5 — Sever the legacy `scraping` database from all roles/users
-- ---------------------------------------------------------------------
-- `scraping` is dead. We keep the data on disk but nothing should be
-- able to read/write it. Wildcard REVOKE catches both the role-level
-- grant (SELECT, INSERT, SHOW TABLES ON scraping.* to scraper_writer)
-- AND any direct table-level grants on nimble_loader (e.g.
-- scraping.amazon_products, scraping.amazon_serp).
REVOKE ALL ON scraping.* FROM scraper_writer;
REVOKE ALL ON scraping.* FROM nimble_loader;


-- ---------------------------------------------------------------------
-- STEP 6 — UI-only steps (NOT runnable in SQL Console)
-- ---------------------------------------------------------------------
-- 6a. Settings → Network → whitelist hermes' egress IP.
--     curl -s https://api.ipify.org   (from hermes)
-- 6b. Top of cluster page → "Connect" button → copy hostname into
--     CLICKHOUSE_HOST in .env.local.


-- =====================================================================
-- VERIFICATION — run after STEP 5 to confirm everything landed
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

-- V5: grants — should reference ONLY pricepilot.* (no scraping.* anywhere)
SHOW GRANTS FOR nimble_loader;
SHOW GRANTS FOR scraper_writer;
-- expected for scraper_writer: SELECT, INSERT, SHOW TABLES on pricepilot.*
-- expected for nimble_loader:  GRANT scraper_writer (and nothing on scraping.*)
-- if you still see any scraping.* row, STEP 5 didn't fully land — re-run it.
