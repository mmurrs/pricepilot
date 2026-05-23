#!/usr/bin/env python3
"""CLI: generate a Senso.ai price-drop report. Used by Hermes skills via terminal."""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()

from integrations.clickhouse_client import get_price_history
from integrations.senso_client import generate_report
from integrations.nimble_client import check_price

if __name__ == "__main__":
    # args: product_id product_name current_price threshold url
    if len(sys.argv) < 6:
        print(json.dumps({"error": "Usage: generate_report.py <product_id> <product_name> <current_price> <threshold> <url>"}))
        sys.exit(1)

    _, product_id, product_name, current_price_str, threshold_str, url = sys.argv

    history = get_price_history(product_id, hours=24)
    report_url = generate_report(
        product_name=product_name,
        price_history=history,
        sources=[url],
        current_price=float(current_price_str),
        threshold=float(threshold_str),
    )

    if report_url:
        print(json.dumps({"report_url": report_url}))
    else:
        print(json.dumps({"error": "Senso report generation failed"}))
        sys.exit(1)
