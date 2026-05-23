---
name: check-price
description: Check the current price of an Amazon or Walmart product URL right now
version: 1.0.0
metadata:
  hermes:
    tags: [price, shopping, ecommerce]
    category: productivity
    requires_toolsets: [terminal]
required_environment_variables:
  - name: PRICEPILOT_DIR
    prompt: Path to the pricepilot project directory
    required_for: running price tools
  - name: NIMBLE_API_KEY
    prompt: Your Nimble API key
    required_for: price scraping
---

# Check Price

## When to Use

Invoke when a user asks for the current price of a product without wanting to set up ongoing monitoring.

Trigger phrases: "what's the price of", "how much is", "check the price", "current price for"

Examples:
- "What's the price of https://amazon.com/dp/B09XS7JWHH right now?"
- "Check https://walmart.com/ip/headphones/123 for me"

## Procedure

1. **Extract the product URL** from the user's message.

2. **Scrape current price** via terminal:
   ```bash
   cd $PRICEPILOT_DIR && python tools/check_price.py "<url>"
   ```
   Returns JSON: `{"title": "...", "price": 99.99, "source": "amazon", "currency": "USD"}`

3. **Reply to user** with the result:
   > "**[product name]** is currently **$[price]** on [source]."

4. **Offer to track**: If the user seems interested, offer:
   > "Want me to monitor this and alert you when it drops? Just say a target price."

## Pitfalls

- If the URL is not a product page, ask for the direct product link
- If scraping fails, suggest the user try again or check the URL

## Notes

This skill does NOT store data in ClickHouse — it's a one-shot lookup.
Use `track-product` for persistent monitoring.
