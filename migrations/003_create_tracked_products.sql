-- 003 — Create pricepilot.tracked_products
--
-- User watchlist. ReplacingMergeTree dedupes on the ORDER BY key
-- during merges, so re-INSERTs of (user_id, product_id) collapse.
-- Per-retailer URLs live here so the poller doesn't need to
-- re-resolve products on every tick. Adding a retailer = adding a
-- <retailer>_url column.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS — safe to re-run.
-- Depends on: 001

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
