---
name: price-history
description: Show the price history for a user's tracked products from ClickHouse
version: 1.0.0
metadata:
  hermes:
    tags: [price, history, analytics, clickhouse]
    category: productivity
    requires_toolsets: [terminal]
required_environment_variables:
  - name: PRICEPILOT_DIR
    prompt: Path to the pricepilot project directory
    required_for: running price tools
  - name: CLICKHOUSE_HOST
    prompt: ClickHouse Cloud host
    required_for: price history queries
---

# Price History

## When to Use

Invoke when a user asks to see price trends, history, or what they are currently tracking.

Trigger phrases: "price history", "what am I tracking", "show my tracked", "price trend", "has the price changed", "lowest price"

Examples:
- "What's the price history for my items?"
- "What am I tracking?"
- "Has the Sony headphones price changed?"

## Procedure

1. **Get tracked products** for this user:
   ```bash
   cd $PRICEPILOT_DIR && python tools/get_tracked.py "<user_id>"
   ```
   Returns JSON array of tracked products with `product_id`, `product_name`, `threshold`, `amazon_url`.

2. **For each product, get price history**:
   ```bash
   cd $PRICEPILOT_DIR && python tools/get_history.py "<product_id>"
   ```
   Returns JSON array of `{price, timestamp, source}` objects, most recent first.

3. **Format a summary table** for the user showing:
   - Product name
   - Current price (most recent entry)
   - Lowest recorded price
   - Alert threshold
   - Trend (↑ / ↓ / → compared to first recorded price)

4. **Reply** with the formatted table using Markdown.

## Pitfalls

- If no products are tracked yet, tell the user how to start: "Share an Amazon or Walmart product URL and I'll track it for you."
- If history is empty for a product, show "No history yet — just added."

## Example Output

```
📊 Your tracked products:

| Product | Now | Lowest | Target | Trend |
|---|---|---|---|---|
| Sony WH-1000XM5 | $109.99 | $89.99 | $90.00 | ↓ |
| iPad Air 5 | $549.00 | $549.00 | $499.00 | → |
```
