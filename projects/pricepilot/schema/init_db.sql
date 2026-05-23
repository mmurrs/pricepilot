CREATE DATABASE IF NOT EXISTS pricepilot;

CREATE TABLE IF NOT EXISTS pricepilot.price_events (
  user_id      String,
  product_id   String,
  product_name String,
  url          String,
  source       LowCardinality(String),
  price        Float64,
  currency     String DEFAULT 'USD',
  timestamp    DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (product_id, timestamp);

CREATE TABLE IF NOT EXISTS pricepilot.tracked_products (
  user_id      String,
  product_id   String,
  product_name String,
  amazon_url   String,
  walmart_url  String DEFAULT '',
  threshold    Float64,
  active       UInt8 DEFAULT 1
) ENGINE = ReplacingMergeTree()
ORDER BY (user_id, product_id);
