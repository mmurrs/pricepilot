# Senso — PricePilot Report Generator

Generates and publishes grounded, cited price-drop reports via [Senso.ai](https://senso.ai). Called by the Hermes agent when a tracked product hits its price threshold.

## What it does

Exposes one function to Hermes:

```python
generate_report(product_name: str, price_history: list, sources: list[str]) -> str
# returns a published report URL (cited.md/report/...)
```

## Setup

```bash
cd projects/senso
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
```

Set your API key in the repo root `.env`:

```
SENSO_API_KEY=your_senso_api_key_here
```

Verify access:

```bash
npx senso whoami
npx senso org get
```

## Sponsor tool

**Senso.ai** — grounded content generation with citations. Best use prize: $3K in credits.
