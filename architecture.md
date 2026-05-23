# PricePilot — Architecture

## System Overview

PricePilot is an autonomous price-monitoring agent delivered as a Telegram bot. Users send natural-language messages; the Hermes agent framework interprets intent, calls tool scripts, and replies with real price data.

```
User (Telegram)
      │
      ▼
Hermes Gateway v0.14       ← runs in Daytona sandbox (ubuntu 22.04)
  LLM: qwen35-35b          ← via LiteLLM proxy (OpenAI-compatible API)
  Platform: Telegram polling
      │
      ├── find-best-price skill ──▶ tools/find_best_price.py
      │                                 └──▶ Nimble API (keyword search + scrape)
      │                                         returns: ranked PriceResult list
      │
      ├── check-price skill ──────▶ tools/check_price.py
      │                                 └──▶ Nimble API (single URL scrape)
      │
      ├── track-product skill ────▶ tools/check_price.py  → Nimble
      │                             tools/store_price.py  → ClickHouse Cloud
      │                             tools/add_tracked.py  → ClickHouse Cloud
      │
      ├── price-history skill ────▶ tools/get_tracked.py  → ClickHouse Cloud
      │                             tools/get_history.py  → ClickHouse Cloud
      │
      └── price-alert skill ──────▶ tools/poll.py              → Nimble + ClickHouse
           (cron every 10 min)      tools/generate_report.py   → Senso.ai
                                    → sends TG alert on drop
```

---

## Component Map

| Component | File(s) | Owner | Status |
|---|---|---|---|
| Hermes skills | `skills/*/SKILL.md` | Kishore | ✅ 5 skills deployed |
| Tool scripts | `tools/*.py` | Kishore | ✅ All working |
| Nimble client | `integrations/nimble_client.py` | Nimble teammate | ✅ Real (Bearer auth) |
| ClickHouse client | `integrations/clickhouse_client.py` | ClickHouse teammate | ✅ Real (clickhouse_connect) |
| Senso client | `integrations/senso_client.py` | Senso teammate | ⚠️ Stub |
| Hermes setup | `hermes/setup.sh`, `hermes/start.sh` | Kishore | ✅ Working |
| Daytona config | `.daytona.yaml` | Kishore | ✅ ubuntu 22.04 |
| DB schema | `schema/init_db.sql` | Kishore | ✅ Deployed to ClickHouse Cloud |

---

## Data Flow — Price Discovery

```
User: "find the best price for Crocs size 10 white"
  │
  ▼ Hermes selects find-best-price skill
  ▼ python tools/find_best_price.py "crocs size 10 white"
  ▼ nimble_client.search_and_price("crocs size 10 white")
      ├── GET https://www.amazon.com/s?k=crocs+size+10+white  (via Nimble)
      │     parse /dp/ ASINs → scrape product pages → PriceResult[]
      └── GET https://www.walmart.com/search?q=...  (via Nimble)
            parse JSON-LD → PriceResult[]
  ▼ sort by price asc
  ▼ return JSON to Hermes
  ▼ Hermes formats table → sends to Telegram
```

---

## Data Flow — Price Alert

```
Cron every 10 min → price-alert skill
  ▼ python tools/poll.py
      ▼ clickhouse_client.get_tracked_products()
      ▼ for each product:
          nimble_client.check_price(url) → current price
          clickhouse_client.store_price_event(...)
          if current_price < threshold:
              python tools/generate_report.py  →  senso_client.generate_report()
              Hermes sends TG alert with Senso report URL
```

---

## External Services

| Service | Endpoint | Auth | Used for |
|---|---|---|---|
| LiteLLM proxy | `https://spark-2bc4.tail3a01e2.ts.net/v1` | Bearer `OPENAI_API_KEY` | LLM inference (qwen35-35b) |
| Nimble Web API | `https://api.webit.live/api/v1/realtime/web` | Bearer `NIMBLE_API_KEY` | Amazon + Walmart scraping |
| ClickHouse Cloud | `<host>:8443` (TLS) | user/pass | Price event storage + queries |
| Senso.ai | `SENSO_BASE_URL` | Bearer `SENSO_API_KEY` | Grounded report generation |
| Telegram Bot API | `https://api.telegram.org` | `TELEGRAM_BOT_TOKEN` | User messaging |
| Daytona | `https://app.daytona.io` | `DAYTONA_KEY` | Sandbox provisioning |

---

## Hermes Configuration

`~/.hermes/config.yaml` (written by `setup.sh`):

```yaml
model:
  provider: custom       # OpenAI-compatible custom endpoint
  model: qwen35-35b
  base_url: https://spark-2bc4.tail3a01e2.ts.net/v1

skills:
  external_dirs:
    - ~/.hermes/skills/pricepilot

terminal:
  env: local

agent:
  max_iterations: 30
```

---

## Judging Alignment

| Criterion | How PricePilot addresses it |
|---|---|
| **Nimble** | Real price scraping via web extraction API — both product pages and search results |
| **ClickHouse** | All price events and tracked products persisted; history queries over time window |
| **Senso.ai** | Report generation on price drop events (stub → teammate integrates real API) |
| **Hermes** | Full agent runtime: skills, terminal tool, LiteLLM routing, Telegram gateway |
| **Daytona** | Sandbox provisioned via SDK/API; all code runs inside sandbox |
| **Agentic** | Multi-step reasoning: search → scrape → compare → store → alert |
