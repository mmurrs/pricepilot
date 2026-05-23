-- 004 — Grant scraper_writer access to pricepilot.*
--
-- nimble_loader inherits via role membership (already in place).
-- Idempotent: re-granting an existing grant is a no-op.
-- Depends on: 001, 002, 003 (database + tables must exist).

GRANT SELECT, INSERT, SHOW TABLES ON pricepilot.* TO scraper_writer;
