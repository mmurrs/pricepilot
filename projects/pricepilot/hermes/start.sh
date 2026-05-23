#!/usr/bin/env bash
# PricePilot — start Hermes gateway + configure polling schedule
# Run this after setup.sh inside your Daytona workspace.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PRICEPILOT_DIR="$REPO_ROOT/projects/pricepilot"

# Verify .env is populated
if [ ! -f "$HERMES_HOME/.env" ]; then
  echo "ERROR: $HERMES_HOME/.env not found. Run setup.sh first."
  exit 1
fi

source "$HERMES_HOME/.env"

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN not set in $HERMES_HOME/.env"
  exit 1
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY not set in $HERMES_HOME/.env"
  exit 1
fi

echo "==> Refreshing PricePilot skills..."
mkdir -p "$HERMES_HOME/skills/pricepilot"
cp -r "$PRICEPILOT_DIR/skills/"* "$HERMES_HOME/skills/pricepilot/"

echo "==> Installing PricePilot SOUL.md..."
cp "$PRICEPILOT_DIR/hermes/SOUL.md" "$HERMES_HOME/SOUL.md"

echo "==> Setting up Hermes cron for price polling (every 10 minutes)..."
# Write a Hermes cron config entry using the built-in scheduler
# This tells Hermes to invoke the price-alert skill on a schedule
CRON_FILE="$HERMES_HOME/crons.json"
CRON_ENTRY=$(cat <<EOF
{
  "id": "pricepilot-poll",
  "skill": "price-alert",
  "schedule": "*/10 * * * *",
  "description": "PricePilot: check tracked products for price drops",
  "enabled": true
}
EOF
)

if [ -f "$CRON_FILE" ]; then
  # Merge: remove existing pricepilot-poll entry and add fresh one
  python3 -c "
import json, sys
data = json.load(open('$CRON_FILE'))
data = [e for e in data if e.get('id') != 'pricepilot-poll']
data.append(json.loads(sys.argv[1]))
json.dump(data, open('$CRON_FILE', 'w'), indent=2)
" "$CRON_ENTRY"
else
  echo "[$CRON_ENTRY]" > "$CRON_FILE"
fi

echo "==> Cron configured: price-alert runs every 10 minutes"
echo ""
echo "==> Starting Hermes gateway..."
echo "    Model:    ${HERMES_MODEL}"
echo "    Endpoint: ${OPENAI_BASE_URL}"
echo "    Telegram: configured"
echo ""

exec hermes gateway run
