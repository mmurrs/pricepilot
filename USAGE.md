# Using PricePilot

PricePilot is a pay-per-call agent API. Give it a product spec, get back the cheapest verified buy link on Amazon. **$0.05 per check**, paid in USDC.

This guide walks you through your first call in under five minutes.

---

## TL;DR

```bash
curl -X POST https://pricepilot.vercel.app/find_cheapest \
  -H "Content-Type: application/json" \
  -d '{
    "brand": "Nike",
    "model": "Killshot 2",
    "color": "Sail/Lucid Green",
    "size": { "system": "US", "gender": "men", "value": 11.5 }
  }'
```

The first call returns **HTTP 402** with the price. Resend with a payment header (any of x402, MPP, or AgentCash) and you get the cheapest verified offer back as JSON.

---

## What PricePilot does

You describe a product. PricePilot:

1. Searches Amazon for that exact item.
2. Walks the SERP → parent product page → child variant page.
3. Pulls the **live** price, stock, and seller at request time (not a cached SERP estimate).
4. Returns the verified offer plus a stable `product_id` you can reuse.

Walmart and Target are coming next. The response includes a `missing_sources` list so your agent always knows what's still pending.

---

## The endpoint

```
POST /find_cheapest
```

| Field | Description |
| --- | --- |
| Price | $0.05 per successful call |
| Payment | x402 (Base USDC) · MPP (Tempo USDC) · AgentCash (handles either) |
| Auth | Payment header is the auth. No API keys. |
| Content-Type | `application/json` |

---

## Request

Send a product spec. The more specific, the better the match.

```json
{
  "brand": "Nike",
  "model": "Killshot 2",
  "color": "Sail/Lucid Green",
  "size": { "system": "US", "gender": "men", "value": 11.5 },
  "condition": "new",
  "postal_code": "10001"
}
```

### Fields

| Field | Required | Notes |
| --- | --- | --- |
| `brand` | yes | Manufacturer or brand name. |
| `model` | yes | Model name or number (e.g. `"Killshot 2"`, `"WH-1000XM5"`, `"10497"`). |
| `color` | optional | Free-form. Match how the brand names it when you can. |
| `size` | optional | Object with `system`, `gender`, and `value`. Use for apparel/footwear. |
| `storage` | optional | For electronics (e.g. `"256GB"`). |
| `condition` | optional | `"new"` (default) or `"used"`. |
| `postal_code` | optional | US ZIP. Used for accurate shipping/availability. |

### What makes a good spec

PricePilot works best when your spec uniquely identifies one Amazon variant.

Good:
> "Cheapest Sony WH-1000XM5 headphones in black"

Less good:
> "Cheapest headphones"

If your spec is too vague, you'll get the closest match plus a note in the response.

---

## Response

```json
{
  "product_id": "nike-killshot-2",
  "best": {
    "source": "amazon",
    "price": 89.97,
    "currency": "USD",
    "in_stock": true,
    "seller": "Amazon.com",
    "url": "https://www.amazon.com/dp/B0XXXXXXX",
    "variant": { "color": "Sail/Lucid Green", "size": "11.5" }
  },
  "all_offers": [
    { "source": "amazon", "price": 89.97, "in_stock": true, "url": "https://www.amazon.com/dp/B0XXXXXXX" }
  ],
  "missing_sources": ["walmart", "target", "best_buy", "home_depot"],
  "checked_at": "2026-05-23T15:42:11Z"
}
```

### Fields

- **`best`** — the cheapest verified offer. This is the one to hand to your shopper agent.
- **`all_offers`** — every offer PricePilot pulled, sorted cheapest first.
- **`product_id`** — a stable identifier for this product. Save it to compare prices later.
- **`missing_sources`** — retailers we plan to cover but didn't check this run.
- **`checked_at`** — UTC timestamp the offer was verified.

---

## Paying for a call

Pick whichever wallet path your agent already uses. All three result in the same JSON response.

### Option 1 — AgentCash (easiest)

AgentCash creates a wallet, funds it with test USDC, and signs payments for you. Good for prototyping.

```bash
npx agentcash onboard
npx agentcash try https://pricepilot.vercel.app/find_cheapest
```

### Option 2 — x402 (Base USDC)

You need USDC on Base mainnet (or Sepolia) and a signer.

```js
import { withPaymentInterceptor } from 'x402-fetch'

const fetchWithPay = withPaymentInterceptor(fetch, account)

await fetchWithPay('https://pricepilot.vercel.app/find_cheapest', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(spec),
})
```

Verify the payment at [x402scan.com](https://x402scan.com).

### Option 3 — MPP (Tempo USDC)

You need USDC on Tempo. Privy server wallets work.

```js
import { Mppx, tempo } from 'mppx/client'

Mppx.create({ methods: [tempo({ account: tempoWallet })] })

await fetch('https://pricepilot.vercel.app/find_cheapest', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(spec),
})
```

Verify at [mppscan.com](https://mppscan.com).

---

## The 402 handshake

Don't manually craft payment headers. The libraries above handle this, but here's what's happening under the hood:

1. **First request** — no payment header. Server returns `402 Payment Required` with a body describing accepted payment methods and the price.
2. **Sign payment** — your wallet signs a payment intent for $0.05 USDC.
3. **Second request** — same body, plus an `X-Payment` header. Server verifies, charges, and returns the offer.

Idempotent retries: if your second request times out, retry with the same payment header. You won't get double-charged.

---

## Example agent flows

### "Buy the cheapest variant"

```
1. Describe what the user wants  →  spec
2. POST /find_cheapest            →  best.url
3. Open best.url in a checkout agent
```

### "Watch this product"

```
1. POST /find_cheapest             →  product_id
2. Store product_id + best.price
3. Tomorrow: POST again with the same spec
4. Compare yesterday's price to today's
```

### "Fan out across a shopping list"

Run calls in parallel — each call is independent. Budget = $0.05 × number of items.

---

## Tips

- **Be specific.** "Hoka Clifton 9 women's size 8" beats "running shoes".
- **Save `product_id`.** It's the cleanest key for storing price history.
- **Watch `in_stock`.** Sometimes the cheapest offer is out of stock — fall back to `all_offers[1]`.
- **Quote times in UTC.** `checked_at` is always UTC.
- **Don't cache too long.** Prices move. A re-check on the next call costs $0.05.

---

## Resources

- **OpenAPI spec:** [`/openapi.json`](https://pricepilot.vercel.app/openapi.json)
- **Skill definition:** [`/skill.md`](https://pricepilot.vercel.app/skill.md)
- **LLM context:** [`/llms.txt`](https://pricepilot.vercel.app/llms.txt)
- **Source:** [github.com/mmurrs/agenticenghack](https://github.com/mmurrs/agenticenghack)
- **x402 docs:** [x402.org](https://x402.org)
- **MPP docs:** [mpp.dev](https://mpp.dev)
- **AgentCash:** [agentcash.dev](https://agentcash.dev)

---

## Troubleshooting

**I keep getting 402.**
Your payment header isn't being attached. If you're using `x402-fetch` or `mppx`, make sure the client is created with a funded wallet. If you're using `curl`, switch to one of the libraries — manually constructing payment headers isn't supported.

**The returned product isn't what I asked for.**
Tighten the spec. Add `color`, `size`, or model number. If a variant truly doesn't exist on Amazon, you'll get the closest available match.

**`in_stock: false` on the cheapest offer.**
Check `all_offers` — the next cheapest in-stock offer is usually one entry down.

**Walmart / Target aren't in the response.**
They're listed in `missing_sources`. Coming soon.
