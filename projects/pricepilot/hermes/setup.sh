#!/usr/bin/env bash
# PricePilot — one-shot Hermes + Daytona setup
# Run inside your Daytona workspace after cloning.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PRICEPILOT_DIR="$REPO_ROOT/projects/pricepilot"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "==> Installing Hermes agent (NousResearch)..."
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

echo "==> Installing Python deps..."
pip install -q -r "$PRICEPILOT_DIR/requirements.txt"

echo "==> Writing Hermes config..."
mkdir -p "$HERMES_HOME"
cp "$PRICEPILOT_DIR/hermes/hermes-config.yaml" "$HERMES_HOME/config.yaml"

echo "==> Setting model (custom LiteLLM provider)..."
hermes config set model qwen35-35b 2>/dev/null || true

echo "==> Installing PricePilot skills..."
mkdir -p "$HERMES_HOME/skills/pricepilot"
cp -r "$PRICEPILOT_DIR/skills/"* "$HERMES_HOME/skills/pricepilot/"

echo "==> Preparing ~/.hermes/.env..."
if [ ! -f "$HERMES_HOME/.env" ]; then
  cp "$PRICEPILOT_DIR/hermes/env.template" "$HERMES_HOME/.env"
  echo ""
  echo "  !! Fill in $HERMES_HOME/.env with your API keys before starting the gateway."
  echo ""
else
  echo "  ~/.hermes/.env already exists — skipping (check env.template for any new vars)"
fi

# Auto-set PRICEPILOT_DIR so Hermes skills can find tool scripts
grep -q "^PRICEPILOT_DIR=" "$HERMES_HOME/.env" || \
  echo "PRICEPILOT_DIR=$PRICEPILOT_DIR" >> "$HERMES_HOME/.env"
sed -i "s|^PRICEPILOT_DIR=.*|PRICEPILOT_DIR=$PRICEPILOT_DIR|" "$HERMES_HOME/.env"

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Edit $HERMES_HOME/.env — add OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, NIMBLE_API_KEY,"
echo "     CLICKHOUSE_*, SENSO_* values (teammates provide their keys)"
echo ""
echo "  2. Validate tool chain:"
echo "     bash $PRICEPILOT_DIR/hermes/validate.sh"
echo ""
echo "  3. Start gateway:"
echo "     bash $PRICEPILOT_DIR/hermes/start.sh"
