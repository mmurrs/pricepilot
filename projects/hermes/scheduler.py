"""
Hermes scheduler — periodic flight-watch poller.

Consumes search.tools.poll_tracked_flights(), runs find_cheapest_flight for
each active watch, and emits a FlightAlert when the cheapest total comes in
under the watch's threshold. Alerts include a Senso cited-report URL when
SENSO_API_KEY is set.

Caller is responsible for delivering alerts (e.g. Telegram). For the demo,
`run_once()` returns the list; `run_forever(interval)` loops.

Env:
  CLICKHOUSE_HOST / CLICKHOUSE_PASSWORD — required for live polling.
  NIMBLE_API_KEY                        — required for live OTA fan-out.
  SENSO_API_KEY                         — optional; enables cited reports.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

# Make repo root importable.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from search.tools import (  # noqa: E402
    find_cheapest_flight,
    get_flight_history,
    poll_tracked_flights,
    CheapestOfferResponse,
    Offer,
)
from projects.senso.run import ingest_report  # noqa: E402


DEFAULT_INTERVAL_SECONDS = 600  # 10 min — matches architecture.md


@dataclass
class FlightAlert:
    user_id: str
    flight_id: str
    threshold: float
    best_price: float
    best_source: str
    best_url: str
    title: str
    text: str                                  # Telegram-ready
    report_url: Optional[str] = None           # Senso cited report
    missing_sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TickResult:
    polled: int
    fired: int
    alerts: list[FlightAlert] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


async def run_once() -> TickResult:
    """One pass: poll the watchlist, fan out per watch, emit breach alerts."""
    watches = poll_tracked_flights()
    if not watches:
        return TickResult(polled=0, fired=0)

    coros = [_process_watch(w) for w in watches]
    results = await asyncio.gather(*coros, return_exceptions=True)

    alerts: list[FlightAlert] = []
    errors: list[dict[str, str]] = []
    for watch, outcome in zip(watches, results):
        if isinstance(outcome, FlightAlert):
            alerts.append(outcome)
        elif isinstance(outcome, Exception):
            errors.append(
                {
                    "flight_id": str(watch.get("flight_id", "")),
                    "error": f"{type(outcome).__name__}: {outcome}",
                }
            )

    return TickResult(
        polled=len(watches),
        fired=len(alerts),
        alerts=alerts,
        errors=errors,
    )


async def run_forever(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    """Loop run_once() on a fixed cadence. Caller wires delivery."""
    while True:
        tick = await run_once()
        if tick.alerts:
            for alert in tick.alerts:
                print(json.dumps(asdict(alert), default=str))
        if tick.errors:
            print(json.dumps({"scheduler_errors": tick.errors}), file=sys.stderr)
        await asyncio.sleep(interval_seconds)


async def _process_watch(watch: dict[str, Any]) -> Optional[FlightAlert]:
    """Search for the watched flight; emit alert iff cheapest < threshold."""
    flight_id = str(watch["flight_id"])
    user_id = str(watch["user_id"])
    threshold = float(watch["threshold"])
    depart_date = watch["depart_date"]
    if hasattr(depart_date, "isoformat"):
        depart_date = depart_date.isoformat()

    result = await find_cheapest_flight(
        origin=str(watch["origin"]),
        destination=str(watch["destination"]),
        depart_date=str(depart_date),
        query=f"poller {flight_id}",
        user_id=user_id,
    )
    best = result.best
    if best is None:
        return None

    total = best.total_price if best.total_price is not None else best.price
    if total >= threshold:
        return None

    report_url = _generate_senso_report(flight_id, watch, result)
    return _build_alert(
        watch=watch,
        result=result,
        best=best,
        total=total,
        report_url=report_url,
    )


def _build_alert(
    *,
    watch: dict[str, Any],
    result: CheapestOfferResponse,
    best: Offer,
    total: float,
    report_url: Optional[str],
) -> FlightAlert:
    flight_id = str(watch["flight_id"])
    threshold = float(watch["threshold"])
    title = (
        f"{watch['origin']} → {watch['destination']} on {watch['depart_date']} "
        f"hit ${total:.2f}"
    )
    lines = [
        f"🚨 {title} via {best.source}",
        f"Threshold ${threshold:.2f} → cheapest ${total:.2f}",
        best.title or best.source,
        best.url,
    ]
    if report_url:
        lines.append(f"Analysis: {report_url}")
    if result.missing_sources:
        gaps = ", ".join(
            f"{m.source}({m.reason})" for m in result.missing_sources
        )
        lines.append(f"(no data from: {gaps})")

    return FlightAlert(
        user_id=str(watch["user_id"]),
        flight_id=flight_id,
        threshold=threshold,
        best_price=total,
        best_source=str(best.source),
        best_url=best.url,
        title=title,
        text="\n".join(lines),
        report_url=report_url,
        missing_sources=[asdict(m) for m in result.missing_sources],
    )


def _generate_senso_report(
    flight_id: str,
    watch: dict[str, Any],
    result: CheapestOfferResponse,
) -> Optional[str]:
    """Push a cited report into Senso. Returns report URL when available."""
    if not os.environ.get("SENSO_API_KEY"):
        return None

    history = get_flight_history(
        flight_id=flight_id,
        user_id=str(watch["user_id"]),
        days=7,
    )
    title = f"Flight price drop · {flight_id}"
    markdown = _render_report_markdown(watch, result, history)

    try:
        resp = ingest_report(title, markdown)
    except RuntimeError as exc:
        print(f"senso ingest failed for {flight_id}: {exc}", file=sys.stderr)
        return None

    if isinstance(resp, dict):
        for key in ("report_url", "url", "public_url", "permalink"):
            if key in resp and resp[key]:
                return str(resp[key])
        if "id" in resp:
            return f"senso:{resp['id']}"
    return None


def _render_report_markdown(
    watch: dict[str, Any],
    result: CheapestOfferResponse,
    history: list[dict[str, Any]],
) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    best = result.best
    best_block = ""
    if best is not None:
        total = best.total_price if best.total_price is not None else best.price
        best_block = (
            f"**Cheapest right now:** ${total:.2f} via {best.source}\n\n"
            f"- {best.title or best.source}\n"
            f"- Source URL: {best.url}\n"
        )

    offers_md = "\n".join(
        f"- ${(o.total_price if o.total_price is not None else o.price):.2f} "
        f"{o.source} — {o.title or o.seller} — {o.url}"
        for o in result.all_offers
    ) or "_no live offers_"

    history_md = "\n".join(
        f"- **{row.get('source')}**: min ${row.get('min_price'):.2f}, "
        f"max ${row.get('max_price'):.2f}, "
        f"latest ${row.get('latest_price'):.2f} "
        f"(at {row.get('latest_timestamp')}, {row.get('observations')} obs)"
        for row in history
    ) or "_no recorded history yet_"

    return (
        f"# Flight watch alert — {watch['flight_id']}\n\n"
        f"Generated at {now}\n\n"
        f"**Route:** {watch['origin']} → {watch['destination']}\n"
        f"**Depart:** {watch['depart_date']}\n"
        f"**Threshold:** ${float(watch['threshold']):.2f}\n\n"
        f"## Current snapshot\n\n{best_block}\n"
        f"### All live offers\n\n{offers_md}\n\n"
        f"## Price history (last 7 days)\n\n{history_md}\n"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--forever",
        action="store_true",
        help="Loop forever on --interval seconds (default: single tick)",
    )
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    args = parser.parse_args()

    if args.forever:
        asyncio.run(run_forever(args.interval))
    else:
        result = asyncio.run(run_once())
        print(json.dumps(asdict(result), indent=2, default=str))
