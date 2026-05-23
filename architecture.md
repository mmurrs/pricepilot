# PricePilot — MVP Architecture

> Autonomous price monitoring agent: tracks Amazon/Walmart prices, stores history in ClickHouse, alerts via Telegram, publishes grounded reports via Senso.ai.

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                     USER INTERFACE                       │
│              Telegram Bot  (@PricePilotBot)               │
│   "Track amazon.com/dp/X  alert me when under $89"      │
└─────────────────────────┬────────────────────────────────┘
                          │ inbound message (webhook)
                          ▼
┌──────────────────────────────────────────────────────────┐
│              HERMES AGENT  (Daytona Sandbox)              │
│                                                          │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │Intent Parser│──▶│  Tool Router │──▶│Resp Composer │  │
│  └─────────────┘   └──────┬───────┘   └──────────────┘  │
│                           │                              │
│         ┌─────────────────┼──────────────────┐          │
│         │                 │                  │          │
│   track_product    check_price(s)     get_history       │
│   (url, target)    [polling loop]    (product_id)        │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌──────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    NIMBLE    │  │   CLICKHOUSE    │  │    SENSO.AI      │
│              │  │                 │  │                  │
│ Pre-built    │  │ price_events    │  │ generate_report( │
│ Amazon +     │─▶│ ┌─────────────┐ │  │   product_name,  │
│ Walmart      │  │ │product_id   │ │─▶│   price_history, │
│ scrapers     │  │ │price        │ │  │   sources=[...]  │
│              │  │ │source       │ │  │ )                │
│ → price,     │  │ │timestamp    │ │  │ → published_url  │
│   title,     │  │ └─────────────┘ │  │   on cited.md    │
│   currency   │  │                 │  │                  │
└──────────────┘  └─────────────────┘  └────────┬────────┘
                                                 │
                           ┌─────────────────────┘
                           ▼
              Hermes → Telegram alert:
              "Price dropped to $79! Analysis: [url]"
```

---

## User Intent → Agent Flows

### Flow 1: Register a product to track

```
User:  "Track amazon.com/dp/B0XYZ alert me when under $89"

Hermes: parse_intent()
  → { action: "track", url: "...", threshold: 89.00 }
  → Nimble: scrape_price(url)
      ← { price: 109.99, title: "Sony WH-1000XM5", source: "amazon" }
  → ClickHouse: INSERT INTO price_events + tracked_products
  → Telegram: "Tracking Sony WH-1000XM5 @ $109.99.
               I'll alert you when it drops below $89."
```

### Flow 2: Polling loop (every 10 min, Daytona scheduler)

```
Scheduler triggers: check_all_tracked()

  → ClickHouse: SELECT * FROM tracked_products
  → for each product:
      → Nimble: scrape_price(url)         ← cross-check Amazon + Walmart
      → ClickHouse: INSERT price_event
      → if price < threshold:
          → Senso.ai: generate_report(
                product_name, price_history[last 24h],
                sources=[amazon_url, walmart_url]
              )
              ← { report_url: "cited.md/report/abc123" }
          → Telegram: "🚨 Drop! Sony XM5 is $79.99 (was $109.99).
                       Full price analysis: {report_url}"
```

### Flow 3: On-demand history query

```
User: "What's the price history for my items?"

  → ClickHouse: SELECT product_id, MIN(price), MAX(price),
                        price, timestamp
                FROM price_events
                WHERE user_id = ?
                ORDER BY timestamp DESC
  → Hermes: format summary
  → Telegram: table of current vs. lowest recorded price per product
```

---

## Sponsor Tool Roles

| Tool | Role | Why it's compelling to judges |
|------|------|-------------------------------|
| **Nimble** | Real-time price scraping from Amazon + Walmart | Cross-platform comparison = autonomous data gathering; uses pre-built retailer scrapers |
| **ClickHouse** | Time-series store for `price_events`; historical trend queries | Analytical queries over agent-generated data — the ClickHouse sweet spot |
| **Senso.ai** | Generates a grounded, cited price-drop report and publishes it | Closes the loop: "ingestion alone won't qualify" — publishes to cited.md, making content agent-discoverable |

---

## ClickHouse Schema

```sql
CREATE TABLE price_events (
  user_id      String,
  product_id   String,
  product_name String,
  url          String,
  source       Enum('amazon', 'walmart'),
  price        Float64,
  currency     String DEFAULT 'USD',
  timestamp    DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (product_id, timestamp);

CREATE TABLE tracked_products (
  user_id      String,
  product_id   String,
  product_name String,
  amazon_url   String,
  walmart_url  String,
  threshold    Float64,
  active       UInt8 DEFAULT 1
) ENGINE = MergeTree()
ORDER BY (user_id, product_id);
```

---

## Hermes Tool Definitions

```python
tools = [
  track_product(url: str, threshold: float, user_id: str),
  check_price(product_id: str) -> PriceResult,        # calls Nimble
  get_price_history(product_id: str) -> List[Price],  # queries ClickHouse
  generate_report(product_id: str) -> str,            # calls Senso → URL
  send_alert(user_id: str, message: str, url: str),   # Telegram
]
```

---

## Team Division of Work

| Person | Focus | Deliverable |
|--------|-------|-------------|
| **Kishore** | Hermes agent in Daytona: intent parser, tool routing, polling loop, Telegram webhook | Working agent that calls the other 3 functions |
| **Nimble** | Pre-built Amazon/Walmart scrapers | `check_price(url) → {price, title, source}` |
| **ClickHouse** | Schema creation, INSERT/SELECT helpers | `store_price(event)`, `get_history(product_id)`, `get_tracked()` |
| **Senso** | Report generation + publish | `generate_report(product, price_history) → published_url` |

> Integration contract: each person exposes **one Python function**. Hermes imports them all.

---

## Judging Criteria Alignment

| Criterion (20% each) | How we hit it |
|----------------------|---------------|
| **Autonomy** | Polling loop runs without user intervention; alerts fire on its own |
| **Idea** | Real consumer value — saves money on purchases over $100 |
| **Technical implementation** | Hermes orchestration + 3 integrated sponsor APIs |
| **Tool use** | Nimble + ClickHouse + Senso.ai = 3 sponsor tools |
| **Presentation** | Demo: user tracks a product → price drop triggers → Senso report published → Telegram alert fires |

---

## MVP Scope (ship by 4:30 PM)

- [x] Telegram bot receives and parses user intent
- [ ] Nimble scrapes Amazon price for a given URL
- [ ] ClickHouse stores price events and tracked products
- [ ] Hermes polling loop checks prices every 10 minutes
- [ ] Senso.ai generates and publishes a price-drop report
- [ ] Telegram alert fires with report URL on price drop
- [ ] On-demand history query returns price table

### Out of scope for MVP
- Walmart cross-check (add if time permits)
- Landing page / web UI
- Voice interface
- Credit card points optimization
- Computer vision for in-store prices
