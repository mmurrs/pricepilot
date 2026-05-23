import express from "express";
import { fileURLToPath } from "url";
import path from "path";
import { createDual402, dualDiscovery } from "./dual402.js";
import { findCheapestStub } from "./tools/find_cheapest_stub.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;

app.set("trust proxy", true);

app.use(express.json({ limit: "256kb" }));

// Serve static landing page from project root (index.html, favicon.svg, etc.)
app.use(
  express.static(__dirname, {
    extensions: ["html"],
    index: "index.html",
    setHeaders: (res, filepath) => {
      if (filepath.endsWith(".html")) {
        res.setHeader("Cache-Control", "public, max-age=300");
      } else if (filepath.endsWith(".svg")) {
        res.setHeader("Cache-Control", "public, max-age=86400");
      }
    },
  })
);

app.use((req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");
  res.setHeader(
    "Access-Control-Expose-Headers",
    "WWW-Authenticate, Payment-Receipt, PAYMENT-REQUIRED, PAYMENT-RESPONSE"
  );
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

const RECIPIENT_WALLET = process.env.RECIPIENT_WALLET;

const dual = createDual402({
  mpp: {
    currency: process.env.USDC_TEMPO,
    recipient:
      process.env.MPP_RECIPIENT || RECIPIENT_WALLET || process.env.RECIPIENT,
    secretKey: process.env.MPP_SECRET_KEY,
    testnet: process.env.MPP_TESTNET === "true",
  },
  x402: {
    payTo: process.env.X402_PAYEE_ADDRESS || RECIPIENT_WALLET,
    network: process.env.X402_NETWORK || "eip155:84532",
    facilitatorUrl:
      process.env.X402_FACILITATOR_URL || "https://x402.org/facilitator",
  },
});

// CDP Bazaar / x402scan / agentic.market discovery block.
// Surfaced inside the 402 PaymentRequired payload as
// `extensions.bazaar.{info, schema}` so registries index a typed listing
// instead of a probe-only fallback. See docs.cdp.coinbase.com/x402/bazaar.
const findCheapestDiscovery = {
  info: {
    type: "http",
    method: "POST",
    bodyType: "json",
    input: {
      body: {
        brand: "Nike",
        model: "Killshot 2",
        color: "Sail/Lucid Green",
        size: { system: "US", gender: "men", value: 11.5 },
        condition: "new",
        postal_code: "10001",
      },
    },
    output: {
      type: "json",
      example: {
        product_id: "nike-killshot-2",
        best: {
          source: "walmart",
          price: 89.97,
          currency: "USD",
          in_stock: true,
          url: "https://www.walmart.com/ip/...",
        },
        all_offers: [
          { source: "walmart", price: 89.97, in_stock: true },
          { source: "amazon", price: 94.99, in_stock: true },
        ],
        missing_sources: ["target"],
        checked_at: "2026-05-23T15:42:11Z",
      },
    },
  },
  schema: {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    type: "object",
    properties: {
      input: {
        type: "object",
        properties: {
          type: { const: "http" },
          method: { enum: ["POST"] },
          bodyType: { enum: ["json"] },
          body: {
            type: "object",
            properties: {
              brand: {
                type: "string",
                description: "Product brand, e.g. 'Nike', 'Sony', 'LEGO'.",
              },
              model: {
                type: "string",
                description:
                  "Specific model, e.g. 'Killshot 2', 'WH-1000XM5', '10497 Galaxy Explorer'.",
              },
              color: {
                type: "string",
                description: "Color or colorway when relevant.",
              },
              size: {
                type: "object",
                description: "Size spec for apparel/footwear.",
                properties: {
                  system: { type: "string", enum: ["US", "EU", "UK"] },
                  gender: {
                    type: "string",
                    enum: ["men", "women", "kids", "unisex"],
                  },
                  value: { type: "number" },
                },
              },
              condition: {
                type: "string",
                enum: ["new", "used", "ds", "any"],
                default: "new",
              },
              postal_code: {
                type: "string",
                description: "ZIP code for retailer pricing localization.",
                default: "10001",
              },
              source_scope: {
                type: "string",
                enum: ["amazon", "retail", "all"],
                default: "retail",
              },
            },
            required: ["brand", "model"],
          },
        },
        required: ["type", "method", "bodyType", "body"],
      },
      output: {
        type: "object",
        properties: { type: { type: "string" } },
        required: ["type"],
      },
    },
    required: ["input"],
  },
};

const chargeFindCheapest = dual.charge({
  amount: "0.05",
  description: "Cheapest verified product offer across Amazon and Walmart",
  discovery: findCheapestDiscovery,
});

const findCheapestParams = {
  type: "object",
  required: ["brand", "model"],
  properties: {
    brand: {
      type: "string",
      description: "Product brand, e.g. 'Nike', 'Sony', 'LEGO'.",
    },
    model: {
      type: "string",
      description:
        "Specific model name, e.g. 'Killshot 2', 'WH-1000XM5', '10497 Galaxy Explorer'.",
    },
    color: {
      type: "string",
      description: "Color or colorway when relevant.",
    },
    size: {
      type: "object",
      description: "Size spec for apparel/footwear.",
      properties: {
        system: { type: "string", enum: ["US", "EU", "UK"] },
        gender: { type: "string", enum: ["men", "women", "kids", "unisex"] },
        value: { type: "number" },
      },
    },
    condition: {
      type: "string",
      enum: ["new", "used", "ds", "any"],
      default: "new",
    },
    postal_code: {
      type: "string",
      description: "ZIP code for retailer pricing localization.",
      default: "10001",
    },
    source_scope: {
      type: "string",
      enum: ["amazon", "retail", "all"],
      default: "retail",
      description:
        "'amazon' = Amazon only, 'retail' = Amazon + Walmart, 'all' = future cross-retailer.",
    },
  },
};

const findCheapestResponse = {
  type: "object",
  properties: {
    product_id: { type: "string" },
    best: {
      type: "object",
      properties: {
        source: { type: "string" },
        price: { type: "number" },
        currency: { type: "string" },
        in_stock: { type: "boolean" },
        seller: { type: "string" },
        url: { type: "string" },
        variant: { type: "object" },
      },
    },
    all_offers: {
      type: "array",
      items: {
        type: "object",
        properties: {
          source: { type: "string" },
          price: { type: "number" },
          in_stock: { type: "boolean" },
          url: { type: "string" },
        },
      },
    },
    missing_sources: { type: "array", items: { type: "string" } },
    checked_at: { type: "string", format: "date-time" },
  },
};

dualDiscovery(app, dual, {
  info: {
    title: "PricePilot",
    description:
      "Pay-per-call price agent. Name a product, get the cheapest verified buyable offer across Amazon and Walmart — $0.05 per check via x402 or MPP.",
    version: "0.1.0",
    "x-guidance":
      "PricePilot returns the cheapest verified buyable offer for a product. " +
      "POST /find_cheapest with an explicit spec (brand + model, plus variant fields like size, color, storage). " +
      "PricePilot resolves the exact variant on Amazon and Walmart in parallel and returns the offer with the lowest price " +
      "that is currently in stock. The response includes a stable product_id you can reuse to compare prices over time. " +
      "Each check costs $0.05 USD.",
  },
  serviceInfo: {
    categories: ["shopping", "price-comparison", "ecommerce", "amazon", "walmart"],
    docs: {
      homepage: "https://pricepilot-sepia.vercel.app",
    },
  },
  routes: [
    {
      method: "post",
      path: "/find_cheapest",
      handler: chargeFindCheapest,
      operationId: "findCheapestProduct",
      summary: "Cheapest verified buyable offer for a product",
      tags: ["shopping"],
      requestBody: {
        required: true,
        content: {
          "application/json": {
            schema: findCheapestParams,
          },
        },
      },
      responseSchema: findCheapestResponse,
    },
  ],
});

app.post("/find_cheapest", chargeFindCheapest, async (req, res) => {
  try {
    const result = await findCheapestStub(req.body || {});
    res.json(result);
  } catch (err) {
    console.error("[find_cheapest] error:", err);
    res.status(500).json({ error: err.message || "internal error" });
  }
});

app.get("/skill.md", (req, res) => {
  res.type("text/markdown").send(SKILL_MD);
});

app.get("/llms.txt", (req, res) => {
  res.type("text/plain").send(LLMS_TXT);
});

app.get("/health", (req, res) => {
  res.json({ ok: true, service: "pricepilot", version: "0.1.0" });
});

const SKILL_MD = `# PricePilot Skill

Use this skill to find the cheapest verified buyable offer for a specific product across Amazon and Walmart.

## What PricePilot does

PricePilot resolves an exact product variant on Amazon and Walmart in parallel and returns the cheapest currently-in-stock offer. It does not return SERP estimates — every price is pulled from the live product page at request time.

Each check costs **$0.05 USD via x402 (Base) or MPP (Tempo)**. Both payment protocols are accepted on every endpoint.

## Prerequisites

The agent needs a USDC wallet your code can sign with. Any one of:

- **AgentCash**: \`npx agentcash onboard\` — handles MPP and x402 automatically.
- **MPP**: Use \`mppx\` with a Tempo USDC wallet.
- **x402**: Use \`x402-fetch\` with a Base USDC wallet.

## Endpoint

### POST /find_cheapest

Pass an explicit product spec. Required fields: \`brand\`, \`model\`. Variant fields (\`color\`, \`size\`, \`condition\`) sharpen the match — strongly recommended for footwear, apparel, electronics with multiple SKUs.

Request body:

\`\`\`json
{
  "brand": "Nike",
  "model": "Killshot 2",
  "color": "Sail/Lucid Green",
  "size": { "system": "US", "gender": "men", "value": 11.5 },
  "condition": "new",
  "postal_code": "10001",
  "source_scope": "retail"
}
\`\`\`

Response:

\`\`\`json
{
  "product_id": "nike-killshot-2",
  "best": {
    "source": "walmart",
    "price": 89.97,
    "in_stock": true,
    "url": "https://www.walmart.com/ip/...",
    "variant": { "color": "Sail/Lucid Green", "size": "11.5" }
  },
  "all_offers": [
    { "source": "walmart", "price": 89.97, "in_stock": true },
    { "source": "amazon", "price": 94.99, "in_stock": true }
  ],
  "missing_sources": ["target"],
  "checked_at": "2026-05-23T15:42:11Z"
}
\`\`\`

\`best\` is the verified buyable offer with the lowest in-stock price. Treat \`best === null\` as "no verified offer found."

## Tips

- Be specific. "Nike Killshot 2" is fine; "Nike shoes" is not.
- For shoes, always include \`size\`. Apparel, include color + size.
- For electronics, include storage/capacity in the model string when applicable: \`"model": "iPad Air 13\\" 256GB Wi-Fi"\`.
- The same \`product_id\` will come back across calls for the same spec — store it if you want to compare prices over time.
`;

const LLMS_TXT = `# PricePilot

> Pay-per-call price agent for shopping bots. Cheapest verified Amazon + Walmart offer in one call. $0.05 per check via MPP or x402.

## What users ask

- "Cheapest Nike Killshot 2 men's size 11.5"
- "Cheapest Sony WH-1000XM5 headphones in black"
- "Cheapest Hoka Clifton 9 women's size 8"
- "Cheapest LEGO 10497 Galaxy Explorer set"

## Endpoint

### POST /find_cheapest

Pass an explicit product spec. PricePilot resolves the exact variant on Amazon and Walmart in parallel and returns the cheapest currently-in-stock offer.

Required fields: \`brand\`, \`model\`. Optional: \`color\`, \`size\`, \`condition\`, \`postal_code\`, \`source_scope\`.

Returns: \`{ product_id, best, all_offers, missing_sources, checked_at }\`.

\`best\` is the cheapest verified buyable offer. \`null\` means no offer found.

## Coverage

- Amazon — live
- Walmart — live
- Target — coming soon

## Payment

- **x402** on Base (mainnet or Sepolia) — facilitator: https://x402.org/facilitator (testnet) or https://api.cdp.coinbase.com/platform/v2/x402 (mainnet)
- **MPP** on Tempo — wallet pays USDC

Both protocols are accepted on every paid endpoint. Use \`AgentCash\` for the simplest onboarding: \`npx agentcash onboard\`.

## Discovery

- OpenAPI: /openapi.json
- x402 well-known: /.well-known/x402
- Skill definition: /skill.md
`;

// Only bind a port when running locally (not on Vercel)
if (process.env.NODE_ENV !== "test" && !process.env.VERCEL) {
  app.listen(PORT, () => {
    console.log(`PricePilot listening on :${PORT}`);
  });
}

export default app;
