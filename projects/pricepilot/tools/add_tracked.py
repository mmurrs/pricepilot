#!/usr/bin/env python3
"""CLI: register a product for tracking. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import add_tracked_product
from integrations.nimble_client import product_id_from_url

if __name__ == "__main__":
    # args: user_id product_id title url threshold [walmart_url]
    if len(sys.argv) < 6:
        print(json.dumps({"error": "Usage: add_tracked.py <user_id> <product_id> <title> <url> <threshold> [walmart_url]"}))
        sys.exit(1)

    _, user_id, product_id, title, url, threshold_str, *rest = sys.argv
    walmart_url = rest[0] if rest else ""
    amazon_url = url if "amazon" in url else ""
    if not walmart_url and "walmart" in url:
        walmart_url = url

    add_tracked_product(
        user_id=user_id,
        product_id=product_id,
        product_name=title,
        amazon_url=amazon_url,
        threshold=float(threshold_str),
        walmart_url=walmart_url,
    )
    print(json.dumps({"status": "tracking_started", "product_id": product_id, "threshold": float(threshold_str)}))
