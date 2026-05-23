#!/usr/bin/env bash
# PricePilot — Hermes + Daytona setup script
# Run this inside your Daytona workspace after cloning the repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PRICEPILOT_DIR="$REPO_ROOT/projects/pricepilot"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "==> Installing Hermes agent..."
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

echo "==> Installing pricepilot Python dependencies..."
pip install -r "$PRICEPILOT_DIR/requirements.txt"

echo "==> Configuring Hermes environment..."
mkdir -p "$HERMES_HOME"

if [ ! -f "$HERMES_HOME/.env" ]; then
  cp "$PRICEPILOT_DIR/hermes/env.template" "$HERMES_HOME/.env"
  echo ""
  echo "  !! Fill in $HERMES_HOME/.env with your API keys before running hermes gateway start"
  echo ""
else
  echo "  ~/.hermes/.env already exists — skipping (merge env.template manually if needed)"
fi

echo "==> Writing Hermes config..."
cp "$PRICEPILOT_DIR/hermes/hermes-config.yaml" "$HERMES_HOME/config.yaml"

echo "==> Installing PricePilot skills into ~/.hermes/skills/..."
mkdir -p "$HERMES_HOME/skills/pricepilot"
cp -r "$PRICEPILOT_DIR/skills/"* "$HERMES_HOME/skills/pricepilot/"

echo "==> Setting PRICEPILOT_DIR in ~/.hermes/.env..."
grep -q "^PRICEPILOT_DIR=" "$HERMES_HOME/.env" || \
  echo "PRICEPILOT_DIR=$PRICEPILOT_DIR" >> "$HERMES_HOME/.env"

echo ""
echo "Setup complete. Next steps:"
echo "  1. Fill in $HERMES_HOME/.env (API keys, Telegram token, LiteLLM URL)"
echo "  2. hermes gateway setup    # interactive Telegram config"
echo "  3. hermes gateway start    # start the bot"
echo ""
echo "Test the agent locally first:"
echo "  hermes -q '/track-product https://amazon.com/dp/B09XS7JWHH under \$89'"
