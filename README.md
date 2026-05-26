# PricePilot

- **Live product:** https://pricepilot-sepia.vercel.app
- **Paid agent endpoint:** `POST /find_cheapest`
- **Price:** `$0.05` per successful check via x402 or MPP

PricePilot is a paid shopping tool for AI agents. It was built at the **Agentic Engineering Hackathon NYC 2026** to explore what commerce looks like when agents can discover a tool, pay for it, and get back a structured answer they can trust.

The product answers a simple question: **where should I buy this exact product right now?**

Instead of asking an agent to guess from stale search snippets, PricePilot gives the agent a narrow API: send a product spec, pay a small fee, and receive a receipt-style response with the cheapest verified buyable offer.

## What It Is

PricePilot is a productized hackathon prototype with two connected surfaces:

- A public Vercel app that explains the product and exposes the paid API.
- A Hermes-powered shopping assistant flow that can answer shopper requests, track products, and send price-drop alerts.

The Vercel deployment is the main product surface. It includes the homepage, paid endpoint, OpenAPI metadata, agent skill file, and LLM-readable docs so another agent can understand how to call it.

## Why It Matters

Shopping agents are only useful if they can act on current, specific, buyable data. A normal web search result may show the wrong variant, an old price, an out-of-stock listing, or an estimated marketplace price.

PricePilot treats a product lookup like a paid job:

1. The agent states the exact product.
2. PricePilot checks supported retailers.
3. It filters for buyable, in-stock offers.
4. It returns a structured receipt the agent can show to the user or use in another workflow.

That turns live price discovery into a reusable agent tool instead of a one-off scrape.

## How It Works

An agent calls:

```text
POST https://pricepilot-sepia.vercel.app/find_cheapest
```

with a request like:

```json
{
  "brand": "Sony",
  "model": "WH-1000XM5",
  "color": "black",
  "condition": "new",
  "postal_code": "10001",
  "source_scope": "retail"
}
```

If no payment is attached, PricePilot returns `402 Payment Required`. A payment-aware agent retries with either an x402 payment credential or an MPP payment header. Once paid, the endpoint returns the cheapest verified offer.

Example response shape:

```json
{
  "product_id": "sony-wh-1000xm5",
  "best": {
    "source": "amazon",
    "price": 328,
    "currency": "USD",
    "in_stock": true,
    "seller": "Amazon.com",
    "url": "https://www.amazon.com/dp/B09XS7JWHH"
  },
  "all_offers": [
    {
      "source": "amazon",
      "price": 328,
      "in_stock": true,
      "url": "https://www.amazon.com/dp/B09XS7JWHH"
    },
    {
      "source": "walmart",
      "price": 348,
      "in_stock": true,
      "url": "https://www.walmart.com/ip/Sony-WH-1000XM5/"
    }
  ],
  "missing_sources": ["target"],
  "checked_at": "2026-05-23T15:42:11Z"
}
```

## Agent Flow

At a high level, PricePilot works like this:

```text
Shopper or agent asks for the best price
  -> PricePilot receives a structured product spec
  -> payment is verified through x402 or MPP
  -> retailer offers are checked and ranked
  -> the cheapest buyable offer is returned as receipt JSON
```

For the hackathon assistant demo, Hermes handled the conversational layer:

```text
Telegram shopper
  -> Hermes agent
  -> PricePilot lookup
  -> retailer price check
  -> ClickHouse price history
  -> Telegram answer or price-drop alert
```

## Hermes Agent Support

Yes, PricePilot has the pieces needed to work with Hermes as a skill.

For a hosted skill, Hermes can read:

```text
https://pricepilot-sepia.vercel.app/skill.md
```

That skill file describes when to use PricePilot, how to call `POST /find_cheapest`, what fields to send, how payment works, and how to format the response.

For the original hackathon assistant, the repo also includes a local Hermes skill pack for best-price search, direct URL checks, product tracking, price history, and scheduled price alerts. That path is useful when Hermes is running the full Telegram assistant and can call local tools.

What is still required is runtime configuration, not more product copy:

- A Hermes runtime that can install or read the skill.
- A payment-capable HTTP client for x402 or MPP if calling the hosted paid endpoint.
- API credentials for the full local assistant flow: LLM, Telegram, retailer lookup, ClickHouse, and optional report generation.

So the short answer is: **yes for the Hermes skill/plugin contract; the hosted endpoint is discoverable today, and the fuller assistant works when the required credentials and Hermes runtime are configured.**

## Live URLs

- Product: https://pricepilot-sepia.vercel.app
- Paid endpoint: https://pricepilot-sepia.vercel.app/find_cheapest
- OpenAPI: https://pricepilot-sepia.vercel.app/openapi.json
- Agent skill: https://pricepilot-sepia.vercel.app/skill.md
- LLM docs: https://pricepilot-sepia.vercel.app/llms.txt
- Health check: https://pricepilot-sepia.vercel.app/health

## Demo

Agent endpoint demo:

1. Visit https://pricepilot-sepia.vercel.app.
2. Inspect `/openapi.json` or `/skill.md` to see how an agent discovers the tool.
3. Call `POST /find_cheapest` with a product spec.
4. Receive a `402` challenge, pay with x402 or MPP, and retry.
5. Get a receipt with the cheapest verified offer.

Hermes assistant demo:

1. Ask in Telegram: `find the best price for Crocs Classic Clog white size 10`.
2. Hermes structures the request and calls the PricePilot toolchain.
3. PricePilot checks retailer data and returns the best buyable result.
4. A shopper can also track a product below a target price and receive an alert later.

## Prototype Status

PricePilot is a hackathon prototype, not a finished shopping platform. The important product idea is the agent-commerce loop: a discoverable tool, a small per-call payment, a live product check, and a structured answer that another agent can use.

The Vercel surface demonstrates the paid endpoint and agent metadata. The fuller hackathon workflow explored Telegram, Hermes, retailer lookup, ClickHouse price history, and alerting.

## Team and Sponsors

Built at the **Agentic Engineering Hackathon NYC 2026** with Nimble, ClickHouse, Senso.ai, Daytona, Hermes, x402, MPP, and AgentCash.
