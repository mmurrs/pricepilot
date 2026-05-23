import os, re, json, hashlib
from dataclasses import dataclass
import requests


@dataclass
class PriceResult:
    title: str
    price: float
    currency: str
    source: str   # "amazon" | "walmart"
    url: str


# ── helpers ────────────────────────────────────────────────────────────────────

def _nimble_headers() -> dict:
    api_key = os.environ.get("NIMBLE_API_KEY", "")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _nimble_get(url: str, render: bool = False) -> dict | None:
    base = os.environ.get("NIMBLE_BASE_URL", "https://api.webit.live/api/v1/realtime/web")
    payload = {"url": url, "render": render, "country": "US"}
    try:
        resp = requests.post(base, headers=_nimble_headers(), json=payload, timeout=45)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None


def _parse_price(s: str) -> float | None:
    cleaned = re.sub(r"[^0-9.]", "", s.replace(",", ""))
    try:
        v = float(cleaned)
        return v if 0.01 < v < 100_000 else None
    except ValueError:
        return None


def _parse_amazon_product(html: str, url: str) -> PriceResult | None:
    title_m = re.search(r'<span id="productTitle"[^>]*>\s*([^<]+?)\s*</span>', html)
    whole_m = re.findall(r'<span[^>]*class="[^"]*a-price-whole[^"]*"[^>]*>([^<]+)', html)
    frac_m  = re.findall(r'<span[^>]*class="[^"]*a-price-fraction[^"]*"[^>]*>([^<]+)', html)

    if title_m and whole_m:
        title = title_m.group(1).strip()
        frac = frac_m[0].strip() if frac_m else "00"
        price = _parse_price(f"{whole_m[0].strip()}.{frac}")
        if price:
            return PriceResult(title=title, price=price, currency="USD", source="amazon", url=url)
    return None


def _parse_walmart_product(html: str, url: str) -> PriceResult | None:
    title_m = re.search(r'"name"\s*:\s*"([^"]{5,200})"', html)
    price_m = re.search(r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)', html)
    if not price_m:
        price_m = re.search(r'\$([0-9]+\.[0-9]{2})', html)

    if title_m and price_m:
        price = _parse_price(price_m.group(1))
        if price:
            return PriceResult(title=title_m.group(1), price=price, currency="USD", source="walmart", url=url)
    return None


def _search_amazon_asins(query: str) -> list[str]:
    """Return up to 5 ASINs from an Amazon search results page via /dp/ links."""
    search_url = f"https://www.amazon.com/s?k={requests.utils.quote(query)}"
    data = _nimble_get(search_url)
    if not data:
        return []
    html = data.get("html_content", "")
    # Prefer /dp/ links in search result containers (more relevant than data-asin which includes ads)
    asins = list(dict.fromkeys(re.findall(r'/dp/([A-Z0-9]{10})', html)))
    return [a for a in asins if a][:5]


def _search_walmart_items(query: str) -> list[dict]:
    """Return up to 3 Walmart items {title, url, price} from a search page."""
    search_url = f"https://www.walmart.com/search?q={requests.utils.quote(query)}"
    data = _nimble_get(search_url)
    if not data:
        return []
    html = data.get("html_content", "")
    results = []
    items = re.findall(
        r'"url"\s*:\s*"(https://www\.walmart\.com/ip/[^"]+)"[^}]*"name"\s*:\s*"([^"]+)"[^}]*"price"\s*:\s*([0-9.]+)',
        html, re.DOTALL
    )
    for url, title, price_str in items[:3]:
        price = _parse_price(price_str)
        if price:
            results.append({"title": title, "url": url, "price": price})
    return results


# ── public API ─────────────────────────────────────────────────────────────────

def check_price(url: str) -> PriceResult | None:
    """Scrape current price for an Amazon or Walmart product URL via Nimble."""
    data = _nimble_get(url)
    if data is None:
        return None
    html = data.get("html_content", "")
    if "walmart" in url:
        return _parse_walmart_product(html, url)
    return _parse_amazon_product(html, url)


def search_and_price(query: str) -> list[PriceResult]:
    """
    Search Amazon and Walmart for a product by keyword, return results sorted by price.
    Each source is queried; product pages are scraped for accurate prices.
    """
    results: list[PriceResult] = []

    # Amazon: get ASINs from search, scrape each product page
    asins = _search_amazon_asins(query)
    for asin in asins[:3]:
        url = f"https://www.amazon.com/dp/{asin}"
        r = check_price(url)
        if r and r.price > 0:
            results.append(r)

    # Walmart: parse search results directly
    walmart_items = _search_walmart_items(query)
    for item in walmart_items:
        results.append(PriceResult(
            title=item["title"],
            price=item["price"],
            currency="USD",
            source="walmart",
            url=item["url"],
        ))

    results.sort(key=lambda r: r.price)
    return results


def product_id_from_url(url: str) -> str:
    """Extract product ID from Amazon or Walmart URL."""
    match = re.search(r"/(?:dp|product)/([A-Z0-9]{10})", url)
    if match:
        return match.group(1)
    match = re.search(r"/ip/[^/]+/(\d+)", url)
    if match:
        return match.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:10]
