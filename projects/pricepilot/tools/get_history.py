#!/usr/bin/env python3
"""CLI: fetch price history for a product from ClickHouse. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import get_price_history

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: get_history.py <product_id> [hours]"}))
        sys.exit(1)

    product_id = sys.argv[1]
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    history = get_price_history(product_id, hours=hours)
    print(json.dumps(history))
