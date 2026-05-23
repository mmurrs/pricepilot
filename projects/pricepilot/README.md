# PricePilot

Autonomous price-monitoring agent for the Agentic Engineering Hackathon (NYC 2026).

Tracks Amazon and Walmart product prices, alerts on price drops via Telegram, and publishes grounded reports via Senso.ai. Built on the **Hermes** agent framework running in a **Daytona** sandbox.

**Team:** Kishore · Nimble teammate · ClickHouse teammate · Senso teammate  
**Sponsor tools:** Nimble · ClickHouse · Senso.ai  
**Agent runtime:** Hermes v0.14 (NousResearch) + LiteLLM → qwen35-35b  
**Infra:** Daytona sandbox (ubuntu 22.04)

---

## Architecture

```
Telegram user
     │
     ▼
Hermes gateway (polling)
     │
     ├─ find-best-price skill  → tools/find_best_price.py → Nimble API (search + scrape)
     ├─ check-price skill      → tools/check_price.py     → Nimble API (single URL)
     ├─ track-product skill    → tools/add_tracked.py     → ClickHouse
     │                           tools/store_price.py    → ClickHouse
     ├─ price-history skill    → tools/get_history.py     → ClickHouse
     └─ price-alert skill      → tools/poll.py            → Nimble + ClickHouse
          (cron every 10 min)    tools/generate_report.py → Senso.ai
                                 → Telegram alert
```

Hermes receives natural language messages, selects the right skill, and calls the tool scripts as shell commands. Each script prints JSON and exits.

---

## Skills

| Skill | Trigger phrase | What it does |
|---|---|---|
| `find-best-price` | "find best price for X" | Searches Amazon + Walmart by keyword via Nimble, returns ranked results |
| `check-price` | "check price of \<URL\>" | One-shot Nimble lookup for a specific product URL |
| `track-product` | "track \<URL\> under $X" | Scrapes price, stores in ClickHouse, registers threshold |
| `price-history` | "what am I tracking?" | Queries ClickHouse, formats table |
| `price-alert` | Cron every 10 min | Polls all tracked products, fires Senso report + TG alert on drops |

---

## Quick Start (Daytona workspace)

```bash
# 1. Clone into Daytona (or open via daytona.yaml)
daytona create https://github.com/kishorebhatia/agenticenghackNYC2026

# 2. Setup Hermes + skills
bash projects/pricepilot/hermes/setup.sh

# 3. Fill in credentials
nano ~/.hermes/.env
#   OPENAI_API_KEY=<litellm-key>
#   TELEGRAM_BOT_TOKEN=<from @BotFather>
#   NIMBLE_API_KEY=<bearer-token>
#   CLICKHOUSE_HOST=...  CLICKHOUSE_USER=...  CLICKHOUSE_PASSWORD=...
#   CLICKHOUSE_DATABASE=...  CLICKHOUSE_TABLE=price_events
#   SENSO_API_KEY=...    SENSO_BASE_URL=...

# 4. Validate tool chain
bash projects/pricepilot/hermes/validate.sh

# 5. Start
bash projects/pricepilot/hermes/start.sh
```

Hermes listens on Telegram and routes messages to skills automatically.

---

## Integration Contracts

Each teammate owns one integration file. **Signatures are frozen** — only replace the function body.

### Nimble → `integrations/nimble_client.py`

```python
@dataclass
class PriceResult:
    title: str; price: float; currency: str; source: str; url: str

def check_price(url: str) -> PriceResult | None: ...
def search_and_price(query: str) -> list[PriceResult]: ...   # keyword search
def product_id_from_url(url: str) -> str: ...
```

**Status:** Real implementation using Bearer auth (`Authorization: Bearer <NIMBLE_API_KEY>`). Endpoint: `https://api.webit.live/api/v1/realtime/web`.

### ClickHouse → `integrations/clickhouse_client.py`

```python
def store_price_event(user_id, product_id, product_name, url, source, price, currency="USD") -> None
def get_price_history(product_id, hours=24) -> list[dict]   # keys: price, timestamp, source
def add_tracked_product(user_id, product_id, product_name, amazon_url, threshold, walmart_url="") -> None
def get_tracked_products() -> list[dict]
```

**Status:** Real implementation using `clickhouse_connect`. Table/database configurable via env vars (`CLICKHOUSE_TABLE`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_USER`).

### Senso → `integrations/senso_client.py`

```python
def generate_report(product_name, price_history, sources, current_price, threshold) -> str | None
# returns a public URL (cited.md or equivalent)
```

**Status:** Stub — teammate needs to replace body with real Senso.ai API call.

---

## ClickHouse Schema

```bash
clickhouse-client --host $CLICKHOUSE_HOST --port 9440 \
  --user $CLICKHOUSE_USER --password $CLICKHOUSE_PASSWORD \
  --secure < schema/init_db.sql
```

---

## Demo Flow

1. Send to Telegram bot: `find the best price for Crocs Classic Clog white size 10`
2. Bot searches Amazon + Walmart via Nimble, returns ranked price table
3. Send: `Track https://amazon.com/dp/B0015259Z8 alert me when under $30`
4. Bot confirms: product name + current price + threshold stored in ClickHouse
5. On next price-alert poll (or `check prices now`): price drop → Senso report → TG alert
6. Send: `What am I tracking?` → ClickHouse history table in chat

---

## Running Tests

```bash
cd projects/pricepilot
pip install -r requirements.txt
pytest tests/ -v
```

Tests mock external services — no API keys needed.

---

## Vercel Landing Page

The `index.html` / `vercel.json` in this folder serve a static landing page advertising the `/find_cheapest` API endpoint ($0.05/check, x402 + MPP payment).

```bash
# Preview locally
python3 -m http.server 8088

# Deploy
npx vercel --prod
```

Root directory for Vercel: `projects/pricepilot`. Framework preset: Other.
