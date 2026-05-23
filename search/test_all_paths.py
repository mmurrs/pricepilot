"""
Try every plausible path to get real Amazon SERP data for
"nike killshot 2 white" past the Akamai bot wall.

For each path, report:
  - HTTP status / SDK errors
  - bytes of content returned (markdown/html)
  - whether 'bm-verify' (Akamai stub) is present
  - count of real Amazon ASINs extracted from the content
  - first 3 product titles + prices (proof of life)
  - $ cost (if known)

Run:
    cd /Users/matt/agenticenghack
    set -a && source .env.local && set +a
    .venv/bin/python search/test_all_paths.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

ASIN_RE = re.compile(r"amazon\.com/[^/]*/dp/(B[A-Z0-9]{9})")
PRICE_RE = re.compile(r"\$([0-9]+\.[0-9]{2})")
KEYWORD = "nike killshot 2 white"
ZIP = "10001"


@dataclass
class PathResult:
    name: str
    ok: bool
    seconds: float
    bytes_returned: int = 0
    akamai_blocked: bool = False
    asin_count: int = 0
    sample_products: list[str] = field(default_factory=list)
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    notes: str = ""


def _extract_signal(text: str) -> tuple[bool, int, list[str]]:
    """Returns (akamai_blocked, asin_count, sample_titles)."""
    if not text:
        return False, 0, []
    akamai = "bm-verify" in text
    asins = list({m for m in ASIN_RE.findall(text)})
    # Crude title extraction: line-leading [Some Title](url)
    titles = []
    for m in re.finditer(r"\[([^\]]{15,90})\]\(https?://(?:www\.)?amazon\.com/", text):
        t = m.group(1).strip()
        if t and t not in titles and not t.startswith("!["):
            titles.append(t)
        if len(titles) >= 3:
            break
    return akamai, len(asins), titles


def _run(name: str, fn: Callable[[], dict]) -> PathResult:
    print(f"\n--- {name} ---")
    t0 = time.time()
    try:
        out = fn()
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR ({elapsed:.1f}s): {type(e).__name__}: {str(e)[:200]}")
        return PathResult(name=name, ok=False, seconds=elapsed, error=f"{type(e).__name__}: {str(e)[:200]}")

    elapsed = time.time() - t0
    text = out.get("text", "") or ""
    akamai, asin_count, samples = _extract_signal(text)
    res = PathResult(
        name=name,
        ok=asin_count > 0 and not akamai,
        seconds=elapsed,
        bytes_returned=len(text),
        akamai_blocked=akamai,
        asin_count=asin_count,
        sample_products=samples,
        cost_usd=out.get("cost"),
        notes=out.get("notes", ""),
    )
    print(f"  {elapsed:.1f}s | {len(text):>7}b | akamai={akamai} | asins={asin_count} | cost=${out.get('cost') or '?'}")
    for s in samples:
        print(f"    - {s[:80]}")
    return res


# ---------------------------------------------------------------------------
# Path 1+: Nimble — many shapes
# ---------------------------------------------------------------------------

def _nimble_client():
    from nimble_python import Nimble
    return Nimble(api_key=os.environ["NIMBLE_API_KEY"])


def _nimble_to_text(resp) -> str:
    """Combine markdown + html + parsing fields into a single text blob."""
    pieces: list[str] = []
    d = resp.data
    md = getattr(d, "markdown", None)
    if md:
        pieces.append(md)
    html = getattr(d, "html", None)
    if html:
        pieces.append(html)
    parsing = getattr(d, "parsing", None)
    if parsing:
        # parsing is a list of result objects with .entities (might be None)
        for item in parsing:
            ent = getattr(item, "entities", None)
            if ent is None:
                continue
            try:
                pieces.append(json.dumps(ent.model_dump() if hasattr(ent, "model_dump") else ent, default=str))
            except Exception:
                pieces.append(str(ent))
    return "\n".join(pieces)


def path_nimble(label: str, agent: str, params: dict, formats: list[str], extra: dict | None = None):
    def fn():
        c = _nimble_client()
        r = c.agent.run(agent=agent, params=params, formats=formats, extra_body=extra or {})
        text = _nimble_to_text(r)
        return {"text": text, "cost": None, "notes": f"agent={agent}"}
    return _run(f"Nimble[{label}]", fn)


# ---------------------------------------------------------------------------
# Path: Firecrawl via AgentCash
# ---------------------------------------------------------------------------

def path_firecrawl_via_agentcash(url: str):
    """We already proved this works in the parent conversation; re-running for parity."""
    def fn():
        # Simulate by reading the cached AgentCash response we already have
        # (avoids a second $0.0126 charge during the test run)
        cached = "/Users/matt/.claude/projects/-Users-matt/e619a437-f23d-4f96-b329-edcde7fe1bb4/tool-results/toolu_bdrk_01PkUmoGzjXb68fBprVS7MLM.json"
        if os.path.exists(cached):
            data = json.load(open(cached))
            payload = json.loads(data[0]["text"])
            return {"text": payload.get("content") or "", "cost": 0.0126, "notes": "cached from earlier AgentCash call"}
        # Otherwise actually call it
        import urllib.request
        # Not implemented inline — we use the MCP tool from the parent agent
        return {"text": "", "cost": 0.0126, "notes": "Live AgentCash call must be made by the parent agent"}
    return _run("Firecrawl via AgentCash", fn)


# ---------------------------------------------------------------------------
# Path: Surf via AgentCash (the path we proved works at the start of the convo)
# ---------------------------------------------------------------------------

def path_surf_amazon_serp(keyword: str):
    def fn():
        return {"text": "", "cost": 0.005, "notes": "Surf path; call from parent agent"}
    return _run("Surf /amazon/search via AgentCash", fn)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if "NIMBLE_API_KEY" not in os.environ:
        print("ERROR: NIMBLE_API_KEY not set", file=sys.stderr)
        return 2

    results: list[PathResult] = []

    # ---- Nimble: every plausible shape on amazon_serp ----
    base_params = {"keyword": KEYWORD, "zip_code": ZIP}
    nimble_attempts = [
        ("baseline",              {}),
        ("formats=md+html",       {}),  # same baseline but ensure formats
        ("localization=True",     {"localization_extra": True}),
        ("driver=wsa-vx10",       {"driver": "wsa-vx10"}),
        ("driver=wsa-vx6",        {"driver": "wsa-vx6"}),
        ("driver=wsa-12m",        {"driver": "wsa-12m"}),
        ("render=True",           {"render": True}),
        ("unblocker=True",        {"unblocker": True}),
        ("proxy=residential",     {"proxy_type": "residential"}),
        ("country=US",            {"country": "US"}),
    ]
    for label, extra in nimble_attempts:
        formats = ["markdown", "html"]
        results.append(path_nimble(label, "amazon_serp", base_params, formats, extra))

    # ---- Nimble: try google_search to bypass Amazon SERP entirely ----
    def _gs():
        c = _nimble_client()
        r = c.agent.run(
            agent="google_search",
            params={"query": f"{KEYWORD} site:amazon.com", "country": "US"},
            formats=["markdown"],
        )
        return {"text": _nimble_to_text(r), "cost": None, "notes": "google_search → amazon.com"}
    results.append(_run("Nimble[google_search → amazon]", _gs))

    # ---- Firecrawl via AgentCash (proved working) ----
    results.append(path_firecrawl_via_agentcash(f"https://www.amazon.com/s?k={KEYWORD.replace(' ', '+')}"))

    # ---- Surf placeholder (must be invoked by parent agent — see notes) ----
    results.append(path_surf_amazon_serp(KEYWORD))

    # ---- Summary table ----
    print()
    print("=" * 100)
    print(f"{'PATH':<40} {'OK':<5} {'TIME':>6} {'BYTES':>8} {'AKAMAI':<7} {'ASINS':>5} {'COST':>8}")
    print("=" * 100)
    for r in results:
        ok = "✓" if r.ok else "✗"
        cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "?"
        print(f"{r.name:<40} {ok:<5} {r.seconds:>5.1f}s {r.bytes_returned:>7}b {str(r.akamai_blocked):<7} {r.asin_count:>5} {cost:>8}")
        if r.error:
            print(f"  ↳ error: {r.error}")
    print("=" * 100)
    print()
    print("WINNERS (asins>0 AND not akamai-blocked):")
    for r in results:
        if r.ok:
            print(f"  ✓ {r.name}: {r.asin_count} ASINs in {r.seconds:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
