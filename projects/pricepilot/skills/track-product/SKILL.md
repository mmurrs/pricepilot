---
name: track-product
description: Track an Amazon or Walmart product URL and alert when price drops below a threshold
version: 1.0.0
metadata:
  hermes:
    tags: [price, shopping, ecommerce, monitoring]
    category: productivity
    requires_toolsets: [terminal]
required_environment_variables:
  - name: PRICEPILOT_DIR
    prompt: Path to the pricepilot project directory
    required_for: running price tools
  - name: NIMBLE_API_KEY
    prompt: Your Nimble API key
    required_for: price scraping
  - name: CLICKHOUSE_HOST
    prompt: ClickHouse Cloud host
    required_for: price history storage
---

# Track Product

## When to Use

Invoke when a user shares an Amazon or Walmart product URL and wants price monitoring.

Trigger phrases: "track", "monitor", "watch", "alert me when under", "notify me when cheaper than"

Examples:
- "Track https://amazon.com/dp/B09XS7JWHH alert me when under $89"
- "Watch this product: https://walmart.com/ip/headphones/123456 when below $50"

## Procedure

1. **Extract URL and threshold** from the user's message.
   - URL: any `https://amazon.com` or `https://walmart.com` product link
   - Threshold: dollar amount after "under", "below", "cheaper than" — if absent, default to 10% below current price

2. **Check current price** via terminal:
   ```bash
   cd $PRICEPILOT_DIR && python tools/check_price.py "<url>"
   ```
   Returns JSON: `{"title": "...", "price": 99.99, "source": "amazon", "currency": "USD"}`

3. **Compute effective threshold**: use user's value if given, else `round(price * 0.9, 2)`

4. **Store price event** in ClickHouse:
   ```bash
   cd $PRICEPILOT_DIR && python tools/store_price.py "<user_id>" "<product_id>" "<title>" "<url>" "<source>" <price>
   ```

5. **Register product for tracking**:
   ```bash
   cd $PRICEPILOT_DIR && python tools/add_tracked.py "<user_id>" "<product_id>" "<title>" "<url>" <threshold>
   ```

6. **Reply to user**:
   > "✅ Tracking **[product name]** — currently **$[current_price]**. I'll alert you when it drops below **$[threshold]**."

## Pitfalls

- If the URL is a search results page (not a product), ask the user for the direct product URL
- If `check_price.py` returns `{"error": ...}`, tell the user the URL couldn't be scraped and ask them to verify it
- Amazon ASIN is in the URL as `/dp/XXXXXXXXXX` — use that as product_id
- Walmart item ID is the trailing number in the URL — use that as product_id

## Verification

After tracking, confirm by running:
```bash
cd $PRICEPILOT_DIR && python tools/get_tracked.py "<user_id>"
```
Show the user their full tracking list.
