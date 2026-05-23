"""
Live probe — Nimble Amazon + Walmart for "Nike Killshot 2 white size 11.5".

Real param names confirmed via agent.get():
  amazon_serp:    keyword (REQ), page, zip_code
  amazon_pdp:     asin (REQ), zip_code
  walmart_pdp:    product_id (REQ), zipcode
  google_search:  query (REQ), country
  (no walmart_search agent — use google_search "site:walmart.com ..." to find product_id)

Run:
    cd /Users/matt/agenticenghack
    set -a && source .env.local && set +a
    .venv/bin/python search/test_nimble.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

KEYWORD = "nike killshot 2 white"
ZIP = "10001"
OUT_DIR = Path("/tmp")


def _dump(name: str, payload) -> Path:
    p = OUT_DIR / f"nimble_{name}.json"
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def _section(label: str) -> None:
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)


def _data(resp) -> dict:
    """Pull the data dict out of an AgentRunResponse, however it's shaped."""
    d = getattr(resp, "data", None)
    if d is None:
        return {}
    if hasattr(d, "model_dump"):
        return d.model_dump()
    if isinstance(d, dict):
        return d
    return {"_raw": str(d)}


def main() -> int:
    api_key = os.environ.get("NIMBLE_API_KEY")
    if not api_key:
        print("ERROR: NIMBLE_API_KEY not set. Source .env.local first.", file=sys.stderr)
        return 2

    from nimble_python import Nimble
    c = Nimble(api_key=api_key)

    # ------------------------------------------------------------------
    # 1. Amazon SERP
    # ------------------------------------------------------------------
    _section(f"1. amazon_serp(keyword='{KEYWORD}', zip_code='{ZIP}')")
    serp = c.agent.run(
        agent="amazon_serp",
        params={"keyword": KEYWORD, "zip_code": ZIP},
    )
    serp_data = _data(serp)
    _dump("amazon_serp", serp_data)

    # The result list lives under one of these keys; try them in order.
    results = (
        serp_data.get("results")
        or serp_data.get("organic")
        or serp_data.get("products")
        or []
    )
    print(f"  top-level keys: {sorted(serp_data.keys())[:20]}")
    print(f"  result count:   {len(results)}")
    for i, r in enumerate(results[:5]):
        print(f"  [{i}] {r.get('product_name','?')[:60]:<60} ${r.get('price','?')} asin={r.get('asin','?')}")

    if not results:
        print("\n  ERROR: no SERP results — dump saved to /tmp/nimble_amazon_serp.json")
        return 1

    top = results[0]
    asin = top.get("asin")
    print(f"\n  → using top hit asin={asin}")

    # ------------------------------------------------------------------
    # 2. Amazon PDP for the top hit
    # ------------------------------------------------------------------
    _section(f"2. amazon_pdp(asin='{asin}', zip_code='{ZIP}')")
    pdp = c.agent.run(agent="amazon_pdp", params={"asin": asin, "zip_code": ZIP})
    pdp_data = _data(pdp)
    _dump("amazon_pdp", pdp_data)

    print(f"  top-level keys: {sorted(pdp_data.keys())[:30]}")
    for k in ("product_title", "title", "web_price", "price", "list_price", "availability", "in_stock", "brand", "url"):
        if k in pdp_data:
            v = pdp_data[k]
            v_str = (v if not isinstance(v, str) else v[:100])
            print(f"  {k:<18} = {v_str}")

    # ------------------------------------------------------------------
    # 3. Walmart — find a product_id via google_search
    # ------------------------------------------------------------------
    _section(f"3. google_search(query='{KEYWORD} site:walmart.com')")
    gs = c.agent.run(
        agent="google_search",
        params={"query": f"{KEYWORD} site:walmart.com", "country": "US"},
    )
    gs_data = _data(gs)
    _dump("google_search_walmart", gs_data)
    print(f"  top-level keys: {sorted(gs_data.keys())[:20]}")

    # Walmart product URLs look like .../ip/<slug>/<numeric-id>
    walmart_results = (
        gs_data.get("results")
        or gs_data.get("organic")
        or gs_data.get("organic_results")
        or []
    )
    print(f"  result count: {len(walmart_results)}")

    walmart_id = None
    walmart_url = None
    for r in walmart_results[:10]:
        u = r.get("url") or r.get("link") or ""
        m = re.search(r"walmart\.com/ip/[^/]+/(\d+)", u)
        if m:
            walmart_id = m.group(1)
            walmart_url = u
            print(f"  → matched: {u}\n  → product_id={walmart_id}")
            break
        else:
            print(f"  - {u[:90]}")

    # ------------------------------------------------------------------
    # 4. Walmart PDP
    # ------------------------------------------------------------------
    _section(f"4. walmart_pdp(product_id='{walmart_id}', zipcode='{ZIP}')")
    if not walmart_id:
        print("  skipped — no Walmart product_id found in google_search results")
    else:
        wpdp = c.agent.run(
            agent="walmart_pdp",
            params={"product_id": walmart_id, "zipcode": ZIP},
        )
        wpdp_data = _data(wpdp)
        _dump("walmart_pdp", wpdp_data)
        print(f"  top-level keys: {sorted(wpdp_data.keys())[:30]}")
        for k in ("title", "product_title", "price", "web_price", "list_price", "availability", "in_stock", "brand", "url"):
            if k in wpdp_data:
                v = wpdp_data[k]
                v_str = (v if not isinstance(v, str) else v[:100])
                print(f"  {k:<18} = {v_str}")

    _section("Done — full responses in /tmp/nimble_*.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
