"""
Run the Hermes flight demo call locally.

Usage:
    cd /Users/matt/agenticenghack
    set -a && source .env.local && set +a
    .venv/bin/python search/demo_find_cheapest_flight.py \
      --origin JFK --destination LAX --depart 2026-07-15

    # First run, before serving — registers the Nimble custom agents:
    .venv/bin/python search/demo_find_cheapest_flight.py --register-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from tools import find_cheapest_flight, register_flight_agents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", help="IATA origin, e.g. JFK")
    parser.add_argument("--destination", help="IATA destination, e.g. LAX")
    parser.add_argument("--depart", help="YYYY-MM-DD")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="Register Nimble flight agents and exit (run once at deploy)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()

    if args.register_only:
        status = await register_flight_agents()
        print(json.dumps(status, indent=2))
        return 0 if all(v != "" and not v.startswith("error") for v in status.values()) else 1

    if not (args.origin and args.destination and args.depart):
        print("--origin, --destination, --depart are required", file=sys.stderr)
        return 2

    result = await find_cheapest_flight(
        origin=args.origin,
        destination=args.destination,
        depart_date=args.depart,
        query=f"Cheapest {args.origin} -> {args.destination} on {args.depart}",
        user_id=args.user_id,
    )
    print(json.dumps(asdict(result), indent=2, default=str))
    return 0 if result.best else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
