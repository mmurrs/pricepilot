"""
ClickHouse integration client.

Reads connection settings from env vars:
  CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER,
  CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE
"""
import os
from contextlib import contextmanager
from datetime import datetime, timezone

import clickhouse_connect


def _get_settings() -> dict:
    return dict(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        database=os.environ.get("CLICKHOUSE_DATABASE", "pricepilot"),
        secure=True,
        verify=False,
    )


def _table() -> str:
    return os.environ.get("CLICKHOUSE_TABLE", "price_events")


@contextmanager
def get_client():
    """Yield a live clickhouse_connect client, close on exit."""
    client = clickhouse_connect.get_client(**_get_settings())
    try:
        yield client
    finally:
        client.close()


def store_price_event(
    user_id: str,
    product_id: str,
    product_name: str,
    url: str,
    source: str,
    price: float,
    currency: str = "USD",
) -> None:
    with get_client() as client:
        client.insert(
            _table(),
            [[user_id, product_id, product_name, url, source, price, currency,
              datetime.now(timezone.utc)]],
            column_names=["user_id", "product_id", "product_name", "url",
                          "source", "price", "currency", "timestamp"],
        )


def get_price_history(product_id: str, hours: int = 24) -> list[dict]:
    with get_client() as client:
        rows = client.query(
            f"""
            SELECT price, toString(timestamp) AS timestamp, source
            FROM {_table()}
            WHERE product_id = {{product_id:String}}
              AND timestamp >= now() - INTERVAL {{hours:UInt32}} HOUR
            ORDER BY timestamp DESC
            """,
            parameters={"product_id": product_id, "hours": hours},
        ).named_results()
    return list(rows)


def add_tracked_product(
    user_id: str,
    product_id: str,
    product_name: str,
    amazon_url: str,
    threshold: float,
    walmart_url: str = "",
) -> None:
    tracked_table = os.environ.get("CLICKHOUSE_TRACKED_TABLE", "tracked_products")
    with get_client() as client:
        client.insert(
            tracked_table,
            [[user_id, product_id, product_name, amazon_url, walmart_url,
              threshold, 1, datetime.now(timezone.utc)]],
            column_names=["user_id", "product_id", "product_name", "amazon_url",
                          "walmart_url", "threshold", "active", "created_at"],
        )


def get_tracked_products() -> list[dict]:
    with get_client() as client:
        tracked_table = os.environ.get("CLICKHOUSE_TRACKED_TABLE", "tracked_products")
        rows = client.query(
            f"""
            SELECT user_id, product_id, product_name, amazon_url, walmart_url,
                   threshold, active
            FROM {tracked_table}
            WHERE active = 1
            ORDER BY created_at DESC
            """,
        ).named_results()
    return list(rows)
