-- =====================================================================
-- ClickHouse Cloud setup for the Nimble → ClickHouse scraping pipeline
-- Source of truth: ../SETUP.md  (the "ClickHouse Cloud (SQL Console)" section)
--
-- Run each numbered block as a separate statement in the SQL Console.
-- The Console runs one statement at a time; do not try to execute the
-- whole file in one go.
-- =====================================================================


-- ---------------------------------------------------------------------
-- STEP 1 — Generate a strong password
-- ---------------------------------------------------------------------
-- Run this ALONE first. Copy the value from the result column.
-- IMMEDIATELY save it to your secrets manager (1Password / Vault / .env
-- on hermes). ClickHouse stores only the sha256 hash, so if you lose
-- this string you cannot recover it — only rotate.
SELECT replaceAll(base64Encode(randomString(24)), '=', '') AS password;


-- ---------------------------------------------------------------------
-- STEP 2 — Create the database
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS scraping;


-- ---------------------------------------------------------------------
-- STEP 3 — Create the amazon_products table
-- ---------------------------------------------------------------------
-- Schema mirrors SETUP.md exactly. Append-only, partitioned by month,
-- ordered by (asin, scraped_at) so price history queries are cheap.
CREATE TABLE IF NOT EXISTS scraping.amazon_products
(
    asin               String,
    scraped_at         DateTime DEFAULT now(),
    product_title      String,
    brand              LowCardinality(String),
    web_price          Nullable(Float64),
    list_price         Nullable(Float64),
    currency           LowCardinality(String) DEFAULT 'USD',
    availability       Nullable(UInt8),
    average_of_reviews Nullable(Float32),
    number_of_reviews  Nullable(UInt32),
    category           LowCardinality(String),
    seller             String,
    zip_code           LowCardinality(String),
    url                String,
    task_id            String,
    raw                String CODEC(ZSTD(3))
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(scraped_at)
ORDER BY (asin, scraped_at);


-- ---------------------------------------------------------------------
-- STEP 4 — Create the SQL user
-- ---------------------------------------------------------------------
-- IMPORTANT (from SETUP.md gotcha #1): the password MUST be a string
-- literal. `CREATE USER ... BY (SELECT ...)` does NOT work. Paste the
-- value from STEP 1 in place of <<PASTE_PASSWORD_HERE>> below.
--
-- (Also: do NOT use the "Users and roles" UI in ClickHouse Cloud for
--  this — that UI manages console human-users only. SQL is the only
--  way to create a programmatic SQL user.)
CREATE USER nimble_loader
  IDENTIFIED WITH sha256_password BY '<<PASTE_PASSWORD_HERE>>';


-- ---------------------------------------------------------------------
-- STEP 5 — Create role and grants
-- ---------------------------------------------------------------------
-- Role-based grants make rotation/audit easier than granting directly
-- to the user.
CREATE ROLE IF NOT EXISTS scraper_writer;
GRANT SELECT, INSERT, SHOW TABLES ON scraping.* TO scraper_writer;
GRANT scraper_writer TO nimble_loader;

-- Make the role active by default for the user (otherwise the client
-- has to SET ROLE on each connection, which clickhouse-connect does
-- not do automatically).
SET DEFAULT ROLE scraper_writer TO nimble_loader;


-- ---------------------------------------------------------------------
-- STEP 6 — UI-only steps (NOT runnable in SQL Console)
-- ---------------------------------------------------------------------
-- 6a. Settings → Network → whitelist hermes' egress IP.
--     Get the IP from the hermes box:
--         curl -s https://api.ipify.org
-- 6b. Top of the cluster page → "Connect" button → copy the hostname
--     (format: xxx.<region>.aws.clickhouse.cloud). Put it in the
--     .env on hermes as CLICKHOUSE_HOST.


-- =====================================================================
-- VERIFICATION — run these after STEP 5 to confirm everything landed
-- =====================================================================

-- V1: database exists
SELECT name FROM system.databases WHERE name = 'scraping';
-- expected: 1 row, name = 'scraping'

-- V2: table exists with all 16 columns from SETUP.md
SELECT name, type
FROM system.columns
WHERE database = 'scraping' AND table = 'amazon_products'
ORDER BY position;
-- expected: 16 rows in this exact order:
--   asin String, scraped_at DateTime, product_title String,
--   brand LowCardinality(String), web_price Nullable(Float64),
--   list_price Nullable(Float64), currency LowCardinality(String),
--   availability Nullable(UInt8), average_of_reviews Nullable(Float32),
--   number_of_reviews Nullable(UInt32), category LowCardinality(String),
--   seller String, zip_code LowCardinality(String), url String,
--   task_id String, raw String

-- V3: table engine + partitioning are correct
SELECT engine, partition_key, sorting_key
FROM system.tables
WHERE database = 'scraping' AND name = 'amazon_products';
-- expected: engine='MergeTree',
--           partition_key='toYYYYMM(scraped_at)',
--           sorting_key='asin, scraped_at'

-- V4: user exists with sha256_password auth
SELECT name, auth_type FROM system.users WHERE name = 'nimble_loader';
-- expected: 1 row, auth_type contains 'sha256_password'

-- V5: role exists
SELECT name FROM system.roles WHERE name = 'scraper_writer';
-- expected: 1 row

-- V6: role grants are correct (3 privileges on scraping.*)
SELECT access_type, database, table
FROM system.grants
WHERE role_name = 'scraper_writer'
ORDER BY access_type;
-- expected: 3 rows — INSERT, SELECT, SHOW TABLES, all on database='scraping' table=NULL

-- V7: user is granted the role
SELECT user_name, granted_role_name, with_admin_option
FROM system.role_grants
WHERE user_name = 'nimble_loader';
-- expected: 1 row, granted_role_name='scraper_writer'

-- V8: the human-readable summary (what SETUP.md tells you to run)
SHOW GRANTS FOR nimble_loader;
-- expected (verbatim):
--   GRANT scraper_writer TO nimble_loader
SHOW GRANTS FOR scraper_writer;
-- expected (verbatim):
--   GRANT SHOW TABLES, SELECT, INSERT ON scraping.* TO scraper_writer

-- V9: default role is set
SELECT user_name, granted_role_name, with_admin_option, granted_role_is_default
FROM system.role_grants
WHERE user_name = 'nimble_loader';
-- expected: granted_role_is_default = 1


-- =====================================================================
-- POST-LAUNCH (run AFTER hermes does its first manual scrape)
-- =====================================================================

-- P1: confirm rows are landing
SELECT count() AS rows, max(scraped_at) AS most_recent
FROM scraping.amazon_products;

-- P2: 24h data-quality check (from SETUP.md — should be >0.95)
SELECT countIf(web_price IS NOT NULL) / count() AS pct_with_price
FROM scraping.amazon_products
WHERE scraped_at > now() - INTERVAL 1 DAY;

-- P3: per-ASIN freshness — every ASIN in asins.txt should appear in last 24h
SELECT asin, count() AS scrapes_24h, max(scraped_at) AS last_seen
FROM scraping.amazon_products
WHERE scraped_at > now() - INTERVAL 1 DAY
GROUP BY asin
ORDER BY last_seen DESC;
