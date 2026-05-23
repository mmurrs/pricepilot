#!/usr/bin/env python3
"""CLI: store a price event in ClickHouse. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import store_price_event

if __name__ == "__main__":
    # args: user_id product_id title url source price [currency]
    if len(sys.argv) < 7:
        print(json.dumps({"error": "Usage: store_price.py <user_id> <product_id> <title> <url> <source> <price> [currency]"}))
        sys.exit(1)

    _, user_id, product_id, title, url, source, price_str, *rest = sys.argv
    currency = rest[0] if rest else "USD"

    store_price_event(
        user_id=user_id,
        product_id=product_id,
        product_name=title,
        url=url,
        source=source,
        price=float(price_str),
        currency=currency,
    )
    print(json.dumps({"status": "stored"}))
