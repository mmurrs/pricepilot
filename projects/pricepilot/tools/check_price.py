#!/usr/bin/env python3
"""CLI: scrape current price for a product URL. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.nimble_client import check_price

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: check_price.py <url>"}))
        sys.exit(1)

    result = check_price(sys.argv[1])
    if result is None:
        print(json.dumps({"error": "Could not scrape price — check URL or Nimble key"}))
        sys.exit(1)

    print(json.dumps({
        "title": result.title,
        "price": result.price,
        "currency": result.currency,
        "source": result.source,
        "url": result.url,
    }))
