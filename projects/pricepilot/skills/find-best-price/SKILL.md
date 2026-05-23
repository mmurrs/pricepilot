---
name: find-best-price
description: Find the cheapest price for any product using Nimble agents. Use when the user asks "find best price for X", "how much does X cost?", "where can I buy X cheapest?", or any open-ended price discovery question without a specific URL.
triggers:
  - "find best price"
  - "best price for"
  - "cheapest"
  - "how much does"
  - "where can I buy"
  - "find price"
  - "search for price"
  - "price of"
---

# find-best-price

> **MANDATORY**: Do NOT write custom Python scripts. Do NOT use web search. Run ONLY the `find_cheapest.py` command in Step 2 — nothing else.

Search Amazon for the cheapest offer for any product (shoes, electronics, clothing, accessories, etc.) using Nimble's agent-based search.

## When to use

Use this skill when the user asks about prices WITHOUT providing a specific product URL. For a known URL, use `check-price` or `track-product` instead.

## Step 1 — Extract structured fields

Parse the user's message into these fields.

| Field | Required | Notes |
|-------|----------|-------|
| `brand` | yes | e.g. "Sony", "Nike", "Crocs", "Apple" |
| `model` | yes | e.g. "WH-1000XM5", "Killshot 2", "Classic Clog" |
| `size` | **only for footwear/clothing** | numeric US size, e.g. 10 or 11.5 — ask if missing for shoes |
| `gender` | no (shoes only) | "men" / "women" / "kids" / "unisex" — default "men" |
| `color` | no | strongly recommended for accuracy |
| `category` | no | "shoes", "electronics", "clothing", "general" — default "general" |

**Size rules:**
- For footwear or clothing: ask for size if not provided — "What size are you looking for? (US size, e.g. 10)"
- For electronics, headphones, cameras, appliances, or any non-sized product: **do not ask for size**, omit `--size` entirely.

## Step 2 — Run the search tool

**For non-shoe products (electronics, headphones, etc.):**
```
cd $PRICEPILOT_DIR && python tools/find_cheapest.py \
  --brand "<brand>" \
  --model "<model>" \
  --category "<category>" \
  --query "<original user query>"
```

**For footwear/clothing (size is known):**
```
cd $PRICEPILOT_DIR && python tools/find_cheapest.py \
  --brand "<brand>" \
  --model "<model>" \
  --size <size> \
  --gender <gender> \
  --category shoes \
  --color "<color>" \
  --query "<original user query>"
```

Omit `--color` if not provided. The tool prints a JSON object (`CheapestOfferResponse`).

## Step 3 — Format the response

**If a best offer is found** (`best` key is not null):

For non-shoe products:
```
🏷️ Best price for **<brand> <model>**:

**$<best.price>** on <best.source> — [<best.title>](<best.url>)
Total with shipping: $<best.total_price>
In stock: ✅

Other offers checked:
| Store | Price | Title |
|-------|-------|-------|
| <source> | $<price> | <title> |
...

Want me to track this and alert you when it drops below a target? Say "track <url> under $X"
```

For shoes:
```
🏷️ Best price for **<brand> <model>** (Size <size>, <gender>):

**$<best.price>** on <best.source> — [<best.title>](<best.url>)
Total with shipping: $<best.total_price>
In stock: ✅

Other offers checked:
| Store | Price | Title |
|-------|-------|-------|
| <source> | $<price> | <title> |
...

Want me to track this and alert you when it drops below a target? Say "track <url> under $X"
```

**If no best offer** (`best` is null):

```
I couldn't find a buyable offer for **<brand> <model>** on Amazon right now.
Try:
- A slightly different color or model variant
- Pasting a direct Amazon/Walmart URL (I can check that with `check-price`)
```

## Error handling

- If the tool prints `{"error": "..."}`, apologize and suggest checking a direct product URL with `check-price`.
- If `size.value` is not recognized (shoes only), ask the user to clarify (whole or half size).
- The `missing_sources` array in the response lists sources that had no offer or are not yet wired — ignore those silently unless all sources failed.
