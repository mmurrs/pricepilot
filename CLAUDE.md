# CLAUDE.md — PricePilot Hackathon Project

## What this is

PricePilot is an autonomous price-monitoring Telegram bot built for the Agentic Engineering Hackathon (NYC 2026, Datadog office). Tracks Amazon/Walmart product prices, alerts on drops, publishes Senso.ai reports.

**Submission deadline: 2026-05-23 4:30 PM ET**

## Agent runtime

The agent is the **Hermes binary** (NousResearch v0.14), not a custom Python loop. Hermes runs in a Daytona sandbox and processes Telegram messages via `hermes gateway run`. Skills are `.md` files in `skills/`; tools are CLI Python scripts in `tools/`.

**Do not add a custom agent loop.** Hermes handles orchestration, LLM calls, and Telegram.

## Key files

```
projects/pricepilot/
├── skills/*/SKILL.md          # Hermes skill definitions (natural-language triggers)
├── tools/*.py                 # CLI tool scripts called by skills (print JSON, exit)
├── integrations/
│   ├── nimble_client.py       # Nimble Web API — real, Bearer auth
│   ├── clickhouse_client.py   # ClickHouse Cloud — real, clickhouse_connect
│   └── senso_client.py        # Senso.ai — STUB, teammate fills in
├── hermes/
│   ├── setup.sh               # Install Hermes, copy skills, write config
│   ├── start.sh               # Start gateway
│   ├── validate.sh            # Smoke-test all tool scripts
│   ├── hermes-config.yaml     # Config template (provider: custom, model: qwen35-35b)
│   └── env.template           # Env var template → copy to ~/.hermes/.env
├── schema/init_db.sql         # ClickHouse schema (run once against Cloud instance)
├── .env.example               # Env var docs — NO real keys, safe to commit
└── requirements.txt
```

## How Hermes skills call tools

Each skill is a `SKILL.md` with a YAML header. When triggered, Hermes uses its terminal tool to run the matching script, e.g.:

```bash
cd $PRICEPILOT_DIR && python tools/find_best_price.py "crocs size 10 white"
```

Scripts must: load `.env` via `dotenv`, read from `integrations/`, and print valid JSON.

## Team division of work

| Teammate | Owns | Contract |
|---|---|---|
| Kishore | Hermes skills, tool scripts, Daytona setup, Telegram | Don't touch |
| Nimble | `integrations/nimble_client.py` body only | Signatures frozen |
| ClickHouse | `integrations/clickhouse_client.py` body only | Signatures frozen |
| Senso | `integrations/senso_client.py` body only | Signatures frozen |

Never change function signatures in `integrations/`. Only replace function bodies.

## Sandbox (Daytona)

- Sandbox ID: `103a145d-d55b-46de-8124-0a4604a8a8d6`
- Hermes config at: `~/.hermes/config.yaml`
- Credentials at: `~/.hermes/.env` (gitignored, managed separately)
- Skills installed at: `~/.hermes/skills/pricepilot/`
- Gateway log: `~/.hermes/gateway.log`

## Hermes provider config

The LiteLLM proxy requires `model.provider: custom` in `config.yaml` (not `openrouter`). The OPENAI_API_KEY in `.env` is passed as a Bearer token.

```yaml
model:
  provider: custom
  model: qwen35-35b
  base_url: https://spark-2bc4.tail3a01e2.ts.net/v1
```

## Nimble auth

Nimble uses **Bearer token** auth (not HTTP Basic):
```python
headers = {"Authorization": f"Bearer {NIMBLE_API_KEY}"}
```

## ClickHouse connection

Uses TLS on port 8443 with `clickhouse_connect`. Table names are configurable via `CLICKHOUSE_TABLE` and `CLICKHOUSE_TRACKED_TABLE` env vars.

## What NOT to do

- Don't commit `.env`, `~/.hermes/.env`, or any file with real API keys
- Don't add `agent/` or `bot/` Python modules (superseded by Hermes)
- Don't run `hermes gateway start` inside Docker/containers — use `hermes gateway run`
- Don't restart the gateway unnecessarily (each restart triggers a Telegram polling conflict for ~20 seconds)
- Don't change function signatures in `integrations/`
- Don't install Playwright browsers (use `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`)
