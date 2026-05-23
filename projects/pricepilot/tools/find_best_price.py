#!/usr/bin/env python3
"""CLI: search Amazon + Walmart by keyword and return ranked prices.
Usage: python tools/find_best_price.py "crocs size 10 white male"
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.nimble_client import search_and_price

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: find_best_price.py <search query>"}))
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    results = search_and_price(query)

    if not results:
        print(json.dumps({"error": f"No results found for: {query}"}))
        sys.exit(1)

    print(json.dumps([{
        "title": r.title,
        "price": r.price,
        "currency": r.currency,
        "source": r.source,
        "url": r.url,
    } for r in results]))
