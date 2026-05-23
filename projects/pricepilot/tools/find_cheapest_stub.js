/**
 * Stub implementation of find_cheapest.
 *
 * Returns a realistic CheapestOfferResponse shape so the dual402 contract
 * is testable end-to-end and discovery scanners can index. Swap for a real
 * Nimble-backed implementation later — the function signature and response
 * shape are the contract.
 */

const SAMPLE_OFFERS = {
  // brand+model key (lowercased, slugified) -> static offers
  "nike-killshot-2": {
    product_id: "nike-killshot-2",
    offers: [
      {
        source: "walmart",
        price: 89.97,
        currency: "USD",
        in_stock: true,
        seller: "Walmart",
        url: "https://www.walmart.com/ip/Nike-Killshot-2/",
      },
      {
        source: "amazon",
        price: 94.99,
        currency: "USD",
        in_stock: true,
        seller: "Amazon.com",
        url: "https://www.amazon.com/dp/B07K1JDTXP",
      },
    ],
  },
  "sony-wh-1000xm5": {
    product_id: "sony-wh-1000xm5",
    offers: [
      {
        source: "amazon",
        price: 328.0,
        currency: "USD",
        in_stock: true,
        seller: "Amazon.com",
        url: "https://www.amazon.com/dp/B09XS7JWHH",
      },
      {
        source: "walmart",
        price: 348.0,
        currency: "USD",
        in_stock: true,
        seller: "Walmart",
        url: "https://www.walmart.com/ip/Sony-WH-1000XM5/",
      },
    ],
  },
  "lego-10497-galaxy-explorer": {
    product_id: "lego-10497-galaxy-explorer",
    offers: [
      {
        source: "walmart",
        price: 99.0,
        currency: "USD",
        in_stock: true,
        seller: "Walmart",
        url: "https://www.walmart.com/ip/LEGO-10497-Galaxy-Explorer/",
      },
      {
        source: "amazon",
        price: 99.95,
        currency: "USD",
        in_stock: true,
        seller: "Amazon.com",
        url: "https://www.amazon.com/dp/B09Z6MK19C",
      },
    ],
  },
};

const slugify = (s) =>
  String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

const buildProductId = (spec) => {
  const parts = [spec.brand, spec.model].filter(Boolean);
  return slugify(parts.join(" "));
};

export async function findCheapestStub(spec) {
  if (!spec || !spec.brand || !spec.model) {
    return {
      product_id: null,
      best: null,
      all_offers: [],
      missing_sources: ["amazon", "walmart"],
      checked_at: new Date().toISOString(),
      error: "brand and model are required",
    };
  }

  const product_id = buildProductId(spec);
  const sample = SAMPLE_OFFERS[product_id];

  if (sample) {
    const sorted = [...sample.offers].sort((a, b) => a.price - b.price);
    const best = sorted[0];
    return {
      product_id: sample.product_id,
      best: {
        ...best,
        variant: {
          ...(spec.color ? { color: spec.color } : {}),
          ...(spec.size?.value !== undefined
            ? { size: String(spec.size.value) }
            : {}),
        },
      },
      all_offers: sorted.map((o) => ({
        source: o.source,
        price: o.price,
        in_stock: o.in_stock,
        url: o.url,
      })),
      missing_sources: ["target"],
      checked_at: new Date().toISOString(),
    };
  }

  // Unknown product — return a synthesized offer so the contract still works
  // for the demo. Replace with real Nimble lookup before launch.
  const synthBase = 60 + (product_id.length % 50);
  return {
    product_id,
    best: {
      source: "amazon",
      price: synthBase + 9.99,
      currency: "USD",
      in_stock: true,
      seller: "Amazon.com",
      url: `https://www.amazon.com/s?k=${encodeURIComponent(
        `${spec.brand} ${spec.model}`
      )}`,
      variant: {
        ...(spec.color ? { color: spec.color } : {}),
        ...(spec.size?.value !== undefined
          ? { size: String(spec.size.value) }
          : {}),
      },
      stub: true,
    },
    all_offers: [
      {
        source: "amazon",
        price: synthBase + 9.99,
        in_stock: true,
        url: `https://www.amazon.com/s?k=${encodeURIComponent(
          `${spec.brand} ${spec.model}`
        )}`,
      },
      {
        source: "walmart",
        price: synthBase + 14.99,
        in_stock: true,
        url: `https://www.walmart.com/search?q=${encodeURIComponent(
          `${spec.brand} ${spec.model}`
        )}`,
      },
    ],
    missing_sources: ["target"],
    checked_at: new Date().toISOString(),
    note: "Stub response — real Nimble-backed lookup ships next",
  };
}
