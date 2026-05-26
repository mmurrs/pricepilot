# PricePilot

- **Live product:** https://pricepilot-sepia.vercel.app
- **Paid agent endpoint:** `POST /find_cheapest`
- **Price:** `$0.05` per successful check via x402 or MPP

PricePilot is a productized hackathon prototype for agent commerce. It was built for the Agentic Engineering Hackathon (NYC 2026) around a narrow question: if an autonomous agent is going to tell someone where to buy a product, how does it verify the current buyable price instead of guessing from stale search snippets?

The answer is a shopping receipt API. An agent sends a precise product spec, PricePilot checks retailer availability, ranks in-stock offers, and returns the cheapest verified buy link as structured JSON. The Vercel deployment turns that into a paid tool that other agents can discover, pay for, and call on demand.

The live Vercel app at https://pricepilot-sepia.vercel.app is the product surface: it explains the tool, exposes the API contract, publishes agent-readable metadata, and demonstrates the payment flow. The hackathon assistant also includes a Hermes + Telegram workflow for natural-language shopping, price tracking, and alerts.

## Product Overview

PricePilot is designed for three users:

- **Shoppers** ask for the cheapest place to buy a specific item and get a receipt-style answer with the retailer, price, seller, and buy link.
- **Agents** call a typed endpoint instead of scraping the open web themselves. The response is predictable enough to use inside a checkout, alerting, or recommendation flow.
- **Builders** can monetize expensive live price checks with HTTP 402 payments, while still giving agents a clean OpenAPI and skill interface.

The core product promise is simple: name the exact product, pay a small fee, get the cheapest currently buyable offer across supported retailers.

## What It Does

- Accepts a structured product spec: `brand`, `model`, optional `color`, `size`, `condition`, `postal_code`, and `source_scope`.
- Resolves the product against Amazon and Walmart coverage.
- Filters for exact-enough variants so a shopper asking for a shoe size, colorway, storage capacity, or condition does not get a near miss.
- Returns a receipt JSON object with `product_id`, `best`, `all_offers`, `missing_sources`, and `checked_at`.
- Publishes discovery surfaces for agents: `/openapi.json`, `/.well-known/x402`, `/skill.md`, and `/llms.txt`.
- Supports paid access through both x402 and MPP, so agents can pay using the payment rail they already have.
- In the Hermes workflow, stores observations in ClickHouse and can trigger Telegram alerts when tracked products drop below a target price.

## Live Vercel Surface

The deployed product lives at:

- Homepage: https://pricepilot-sepia.vercel.app
- Paid endpoint: `POST https://pricepilot-sepia.vercel.app/find_cheapest`
- OpenAPI: https://pricepilot-sepia.vercel.app/openapi.json
- Agent skill: https://pricepilot-sepia.vercel.app/skill.md
- LLM metadata: https://pricepilot-sepia.vercel.app/llms.txt
- Health check: https://pricepilot-sepia.vercel.app/health

The homepage is intentionally not just a marketing page. It is the public contract for the tool: what it costs, what the endpoint expects, how an agent should pay, and what shape comes back.

## How the Paid Endpoint Works

1. An agent sends a product request to `POST /find_cheapest`.
2. `dual402.js` protects the route and returns `402 Payment Required` when no valid payment is attached.
3. The agent retries with either an x402 payment credential or an MPP `Authorization: Payment ...` header.
4. After payment verification, PricePilot runs the offer lookup and returns the cheapest verified buyable offer.
5. The response includes a stable `product_id` so future checks and price history can refer to the same item.

Example request:

```bash
curl -i -X POST https://pricepilot-sepia.vercel.app/find_cheapest \
  -H 'content-type: application/json' \
  -d '{
    "brand": "Sony",
    "model": "WH-1000XM5",
    "color": "black",
    "condition": "new",
    "postal_code": "10001",
    "source_scope": "retail"
  }'
```

Without payment, the expected first response is a `402` challenge. A payment-aware client uses that challenge to retry and receive the JSON receipt.

Example success shape:

```json
{
  "product_id": "sony-wh-1000xm5",
  "best": {
    "source": "amazon",
    "price": 328,
    "currency": "USD",
    "in_stock": true,
    "seller": "Amazon.com",
    "url": "https://www.amazon.com/dp/B09XS7JWHH",
    "variant": {
      "color": "black"
    }
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

## Hackathon Architecture

PricePilot had two connected surfaces during the hackathon: a user-facing Hermes assistant and a productized HTTP API.

```text
Telegram shopper
  -> Hermes gateway
  -> PricePilot skills
  -> Python tools
  -> Nimble retailer lookup
  -> ClickHouse price events
  -> Senso report URL
  -> Telegram answer or alert

Agent or paid client
  -> Vercel Express app
  -> dual402 payment middleware
  -> /find_cheapest contract
  -> offer resolver
  -> receipt JSON
```

The Hermes side proved the agent experience: a shopper could ask in natural language, track products, and receive alerts. The Vercel side packaged the valuable part as a reusable agent tool: a paid, typed, discoverable endpoint that any shopping bot could call.

## Core Components

- `index.html` - product page for the Vercel deployment.
- `server.js` - Express app serving the landing page, discovery routes, health check, and paid `/find_cheapest` endpoint.
- `dual402.js` - payment middleware that accepts both x402 and MPP on the same route.
- `api/index.js` - Vercel serverless entrypoint.
- `tools/find_cheapest.py` - Hermes CLI path for Nimble-backed product lookup.
- `tools/find_cheapest_stub.js` - Vercel demo resolver with the same response contract as the paid endpoint.
- `integrations/nimble_client.py` - retailer scraping/search integration.
- `integrations/clickhouse_client.py` - price event and tracking storage.
- `integrations/senso_client.py` - report-generation interface used by alert flows.
- `skills/` - Hermes skills for best-price search, URL checks, tracking, history, and price alerts.
- `hermes/` - setup, config, validation, and runtime scripts for the Telegram assistant.

## Demo Flow

**Agent endpoint demo**

1. Visit https://pricepilot-sepia.vercel.app.
2. Inspect `/openapi.json` or `/skill.md` to see how an agent discovers the tool.
3. Call `POST /find_cheapest` with a product spec.
4. Receive a `402` challenge, pay with x402 or MPP, and retry.
5. Get a receipt with the cheapest verified offer.

**Hermes shopping assistant demo**

1. Send Telegram: `find the best price for Crocs Classic Clog white size 10`.
2. Hermes selects the best-price skill and calls the PricePilot toolchain.
3. Nimble checks retailer pages, PricePilot ranks offers, and Hermes replies with the best buyable result.
4. Send Telegram: `track https://amazon.com/dp/B0015259Z8 under $30`.
5. ClickHouse stores the target and price history.
6. The price-alert skill polls on a schedule and sends a Telegram alert when the product crosses the threshold.

## Prototype Status

This repo reflects the hackathon build, so the important distinction is:

- The Vercel deployment is the productized paid API surface: landing page, payment challenge, OpenAPI, x402 discovery, skill metadata, and receipt contract.
- The Hermes workflow contains the fuller agent assistant path: Telegram routing, Nimble-backed lookup tools, ClickHouse persistence, and scheduled alerts.
- `tools/find_cheapest_stub.js` keeps the Vercel paid route testable and marketplace-indexable while the live Nimble resolver is being wired into that route.
- Senso report generation is represented by an integration interface/stub and is used by the alert flow design.

## Running Locally

Install the Vercel/API dependencies:

```bash
npm install
```

Start the local Express app:

```bash
RECIPIENT_WALLET=0x1111111111111111111111111111111111111111 \
MPP_SECRET_KEY=dev-secret \
BASE_URL=http://localhost:3000 \
node server.js
```

Check the local server:

```bash
curl http://localhost:3000/health
```

The paid endpoint will return a `402` challenge unless the request includes a valid x402 or MPP payment credential.

## Hermes Runtime

The Hermes assistant was run from the original hackathon workspace layout where this directory lived at `projects/pricepilot`. The scripts in `hermes/` document that workflow and may need path adjustments if this repo is cloned standalone.

- `hermes/setup.sh` installs Hermes, Python dependencies, config, and skills.
- `hermes/validate.sh` checks the toolchain.
- `hermes/start.sh` launches the Telegram gateway and scheduled price polling.
- `hermes/deploy.sh` syncs updated skills and restarts the gateway.

Required services for the full assistant:

- OpenAI-compatible LiteLLM endpoint for Hermes.
- Telegram bot token.
- Nimble API key for retailer data.
- ClickHouse Cloud database for price events and tracked products.
- Senso.ai API credentials for report URLs.
- Wallet/payment environment for x402 and MPP.

## Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

The Python tests focus on the storage/client contract and mock external services where possible. The Vercel endpoint can be smoke-tested with `/health`, `/openapi.json`, and an unpaid `POST /find_cheapest` that should return a payment challenge.

## Team and Sponsors

Built by the PricePilot hackathon team with Nimble, ClickHouse, Senso.ai, Daytona, Hermes, x402, MPP, and AgentCash.
