"""
Run the explicit Hermes demo call locally.

Usage:
    cd /Users/matt/agenticenghack
    set -a && source .env.local && set +a
    .venv/bin/python search/demo_find_cheapest.py \
      --brand Nike \
      --model "Killshot 2" \
      --color "Sail/Lucid Green" \
      --size 11.5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from tools import find_cheapest_product


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--color")
    parser.add_argument("--size", type=float, required=True)
    parser.add_argument("--gender", choices=["men", "women", "kids", "unisex"], default="men")
    parser.add_argument("--postal-code", default="10001")
    parser.add_argument("--source-scope", choices=["amazon", "retail", "all"], default="amazon")
    parser.add_argument("--user-id", default="demo")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    result = await find_cheapest_product(
        brand=args.brand,
        model=args.model,
        color=args.color,
        size={"system": "US", "gender": args.gender, "value": args.size},
        postal_code=args.postal_code,
        source_scope=args.source_scope,
        query=" ".join(part for part in [args.brand, args.model, args.color, str(args.size)] if part),
        user_id=args.user_id,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.best else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
