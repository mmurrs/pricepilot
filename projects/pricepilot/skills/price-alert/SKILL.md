---
name: price-alert
description: Polling skill — check all tracked products for price drops and fire alerts with Senso.ai reports
version: 1.0.0
metadata:
  hermes:
    tags: [price, alert, monitoring, senso, clickhouse, nimble]
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
    required_for: price storage and history
  - name: SENSO_API_KEY
    prompt: Your Senso.ai API key
    required_for: generating price drop reports
---

# Price Alert (Polling)

## When to Use

This skill is invoked by the Hermes scheduler every 10 minutes to check all tracked products.
It can also be invoked manually.

Trigger phrases: "check prices now", "run price check", "poll prices"

For automated use, configure via Hermes cron:
```
/schedule price-alert every 10 minutes
```

## Procedure

1. **Run the full polling check**:
   ```bash
   cd $PRICEPILOT_DIR && python tools/poll.py
   ```
   This script:
   - Loads all tracked products from ClickHouse
   - Scrapes current price via Nimble for each
   - Stores the new price event in ClickHouse
   - Returns a JSON list of any products that dropped below threshold:
     ```json
     [
       {
         "user_id": "123456",
         "product_name": "Sony WH-1000XM5",
         "current_price": 79.99,
         "threshold": 89.00,
         "url": "https://amazon.com/dp/...",
         "product_id": "B09XS7JWHH"
       }
     ]
     ```

2. **For each price drop**, generate a Senso.ai report:
   ```bash
   cd $PRICEPILOT_DIR && python tools/generate_report.py "<product_id>" "<product_name>" <current_price> <threshold>
   ```
   Returns JSON: `{"report_url": "https://cited.md/report/..."}`

3. **Send alert to each user** via the Hermes messaging gateway for their `user_id`:
   > 🚨 **Price Drop!**
   >
   > **[product name]** dropped to **$[current_price]** (your target: $[threshold])
   >
   > 📊 [Full price analysis]([report_url])

4. **If no drops found**, log silently: "Price check complete — no drops detected."

## Pitfalls

- If `poll.py` fails for a product (scrape error), skip it and continue — don't abort the whole run
- If Senso report generation fails, still send the alert but without the report URL
- Rate-limit: don't send more than one alert per product per hour to avoid spam

## Notes

This skill is the autonomy centerpiece — it runs without user intervention and is what
demonstrates the "Autonomy" judging criterion at full points.
