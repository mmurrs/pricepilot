-- 005 — Sever the legacy `scraping` database
--
-- `scraping` is dead. We keep the data on disk but nothing should
-- be able to read or write it. Wildcard REVOKE catches both the
-- role-level grant on `scraping.*` AND the direct table-level
-- grants on nimble_loader (scraping.amazon_products,
-- scraping.amazon_serp).
--
-- Idempotent: revoking what's not there is a no-op.
-- Depends on: 004 (run AFTER scraper_writer has pricepilot.* grants,
-- so nimble_loader doesn't briefly end up with no usable grants).

REVOKE ALL ON scraping.* FROM scraper_writer;
REVOKE ALL ON scraping.* FROM nimble_loader;
