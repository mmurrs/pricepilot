#!/usr/bin/env python3
"""CLI: check all tracked products for price drops. Called by Hermes price-alert skill."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import get_tracked_products, store_price_event
from integrations.nimble_client import check_price

drops = []

for product in get_tracked_products():
    url = product.get("amazon_url") or product.get("walmart_url", "")
    if not url:
        continue

    result = check_price(url)
    if result is None:
        continue

    store_price_event(
        user_id=product["user_id"],
        product_id=product["product_id"],
        product_name=product["product_name"],
        url=url,
        source=result.source,
        price=result.price,
    )

    if result.price < product["threshold"]:
        drops.append({
            "user_id": product["user_id"],
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "current_price": result.price,
            "threshold": product["threshold"],
            "url": url,
        })

print(json.dumps(drops))
