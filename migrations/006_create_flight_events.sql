-- 006 — Create pricepilot.flight_events
--
-- Parallel time-series to price_events (002). Kept fully separate so
-- the product pipeline is never touched by flight work — no ALTERs on
-- existing tables, no shared schema risk.
--
-- Append-only: one row per OTA / per check. Read the latest price per
-- OTA per flight with:
--   argMax(price, timestamp) BY (flight_id, source)
--
-- flight_id format: 'flight:JFK-LAX:2026-07-15' (one-way only, v1).
-- price is the TOTAL bookable cost (fare + taxes + fees), in `currency`.
-- origin/destination/depart_date are denormalized from flight_id for
-- cheap analytical queries (avoids string parsing in every roll-up).
--
-- Anonymous searches may pass user_id = '' or a session UUID.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS — safe to re-run.
-- Depends on: 001

CREATE TABLE IF NOT EXISTS pricepilot.flight_events
(
    user_id      String,
    flight_id    String,                    -- canonical: 'flight:JFK-LAX:2026-07-15'
    origin       LowCardinality(String),    -- IATA, e.g. 'JFK'
    destination  LowCardinality(String),
    depart_date  Date,
    url          String,                    -- exact deep-link scraped for this observation
    source       LowCardinality(String),    -- 'kayak' | 'google_flights'
    price        Float64,                   -- total: fare + taxes + fees
    currency     String DEFAULT 'USD',
    timestamp    DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (flight_id, source, timestamp);
