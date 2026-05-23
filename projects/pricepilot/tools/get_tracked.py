#!/usr/bin/env python3
"""CLI: list tracked products for a user. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import get_tracked_products

if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    products = get_tracked_products()
    if user_id:
        products = [p for p in products if p["user_id"] == user_id]
    print(json.dumps(products))
