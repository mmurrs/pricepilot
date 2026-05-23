-- 007 — Create pricepilot.tracked_flights
--
-- Flight watchlist. Sibling to tracked_products (003) — kept separate
-- per D1 hybrid: the time-series log is universal, but tracking
-- semantics diverge (flights have a hard expiry at depart_date, products
-- don't; flights key on origin/dest/date, products on SKU).
--
-- flight_id format: 'flight:JFK-LAX:2026-07-15' (one-way only, v1).
--
-- expires_at: poller stops checking after this DateTime. Set by the
-- caller to depart_date 00:00 UTC (or local — the poller compares with
-- now() in the same TZ for "is the flight in the past?").
--
-- cabin/passengers columns exist now for forward-compat, but the v1
-- Hermes tool hardcodes them to 'economy' / 1.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS — safe to re-run.
-- Depends on: 001

CREATE TABLE IF NOT EXISTS pricepilot.tracked_flights
(
    user_id      String,
    flight_id    String,                    -- canonical key: 'flight:JFK-LAX:2026-07-15'
    origin       LowCardinality(String),    -- IATA, e.g. 'JFK'
    destination  LowCardinality(String),
    depart_date  Date,
    cabin        LowCardinality(String) DEFAULT 'economy',
    passengers   UInt8 DEFAULT 1,
    threshold    Float64,
    expires_at   DateTime,
    active       UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree()
ORDER BY (user_id, flight_id);
