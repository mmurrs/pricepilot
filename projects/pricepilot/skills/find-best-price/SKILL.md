---
name: find-best-price
description: Search Amazon and Walmart by product keywords and return the best (lowest) price. Use when the user asks "find best price for X", "how much does X cost?", "where can I buy X cheapest?", or any open-ended price discovery question without a specific URL.
triggers:
  - "find best price"
  - "best price for"
  - "cheapest"
  - "how much does"
  - "where can I buy"
  - "price of"
  - "search for price"
---

# find-best-price

Search Amazon and Walmart for a product by keyword and return the best available price.

## When to use

Use this skill when the user asks about prices WITHOUT providing a specific product URL. Examples:
- "find the best price for Crocs size 10 male white"
- "how much are AirPods Pro?"
- "where's the cheapest iPhone 15?"

For tracking a product at a URL, use `track-product` instead.

## Steps

1. Extract the product search query from the user's message (include size, color, model specifics).

2. Run the search tool:

```
cd $PRICEPILOT_DIR && python tools/find_best_price.py "<query>"
```

3. Parse the JSON array of results (sorted lowest price first).

4. Present results to the user in a clear table format:

```
🏷️ Best prices for: **<query>**

| # | Store | Price | Product |
|---|-------|-------|---------|
| 1 | Amazon | $XX.XX | <title> |
| 2 | Walmart | $XX.XX | <title> |
...

💡 Best deal: **$XX.XX** on <store> → [link](<url>)

Want me to track this product and alert you when it drops below a target price? Just say "track <url> under $XX"
```

5. If no results found, tell the user and suggest they provide a direct Amazon/Walmart URL.

## Error handling

- If `find_best_price.py` returns an error, apologize and suggest using a direct product URL with the `check-price` skill.
- If price is 0.0, note that the price couldn't be determined and provide the URL for the user to check manually.
