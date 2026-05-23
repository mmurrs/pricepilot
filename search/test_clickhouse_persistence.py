from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tools


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.insert_calls = []

    def insert(self, table, rows, *, column_names):
        self.insert_calls.append(
            {
                "table": table,
                "rows": rows,
                "column_names": column_names,
            }
        )


def _spec() -> tools.ProductSpec:
    return tools.build_product_spec(
        brand="Nike",
        model="Killshot 2",
        color="Sail/Lucid Green",
        size={"system": "US", "gender": "men", "value": 11.5},
        source_scope="retail",
        user_id="telegram:123",
    )


def _offer(source: tools.Source, url: str, observed_at: str) -> tools.Offer:
    return tools.Offer(
        source=source,
        title="Nike Mens Killshot 2 Leather",
        price=74.96,
        shipping_cost=0.0,
        total_price=74.96,
        currency="USD",
        url=url,
        in_stock=True,
        seller="Retailer",
        observed_at=observed_at,
    )


class ClickHousePersistenceTest(unittest.TestCase):
    def test_build_price_event_matches_clickhouse_schema(self) -> None:
        event = tools.build_clickhouse_price_event(
            _spec(),
            _offer("amazon", "https://www.amazon.com/dp/B07SSV4CTT", "2026-05-23T18:48:02+00:00"),
        )

        self.assertEqual(tuple(event.keys()), tools.CLICKHOUSE_PRICE_EVENTS_COLUMNS)
        self.assertEqual(event["user_id"], "telegram:123")
        self.assertEqual(event["product_id"], "shoes-nike-killshot-2-sail-lucid-green-us-men-11-5")
        self.assertEqual(event["source"], "amazon")
        self.assertEqual(event["timestamp"], datetime(2026, 5, 23, 18, 48, 2))

    def test_store_price_events_bulk_inserts_rows_in_schema_order(self) -> None:
        spec = _spec()
        offers = [
            _offer("amazon", "https://www.amazon.com/dp/B07SSV4CTT", "2026-05-23T18:48:02+00:00"),
            _offer("walmart", "https://www.walmart.com/ip/Nike-Killshot/123456789", "2026-05-23T18:49:02Z"),
        ]
        client = FakeClickHouseClient()

        with patch.dict(tools.os.environ, {}, clear=True):
            observation_ids = tools.store_price_events(spec, offers, client=client)

        self.assertEqual(len(observation_ids), 2)
        self.assertFalse(any(observation_id.startswith("local:") for observation_id in observation_ids))
        self.assertEqual(len(client.insert_calls), 1)
        call = client.insert_calls[0]
        self.assertEqual(call["table"], "price_events")
        self.assertEqual(call["column_names"], list(tools.CLICKHOUSE_PRICE_EVENTS_COLUMNS))
        self.assertEqual(len(call["rows"]), 2)
        self.assertEqual(call["rows"][0][1], call["rows"][1][1])
        self.assertEqual(call["rows"][0][4], "amazon")
        self.assertEqual(call["rows"][1][4], "walmart")

    def test_store_price_events_returns_local_ids_without_clickhouse_config(self) -> None:
        with patch.dict(tools.os.environ, {}, clear=True):
            observation_ids = tools.store_price_events(
                _spec(),
                [_offer("amazon", "https://www.amazon.com/dp/B07SSV4CTT", "2026-05-23T18:48:02+00:00")],
            )

        self.assertEqual(len(observation_ids), 1)
        self.assertTrue(observation_ids[0].startswith("local:"))


if __name__ == "__main__":
    unittest.main()
