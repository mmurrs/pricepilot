/**
 * dual402.js — Express middleware that accepts both x402 and MPP payments.
 *
 * x402: Generates PAYMENT-REQUIRED header, verifies via facilitator.
 * MPP:  Delegates to mppx (stateless HMAC challenges, USDC settlement).
 *
 * No new npm dependencies — x402 side is just HTTP calls to the facilitator.
 */

import { Mppx, tempo } from "mppx/express";

// ── Default USDC addresses per CAIP-2 network ───────────────────────────

const USDC_BY_NETWORK = {
  "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", // Base Sepolia
  "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", // Base Mainnet
  "eip155:1": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", // Ethereum
};

const FACILITATOR_TIMEOUT_MS = 30_000;

// ── Create dual handler ─────────────────────────────────────────────────

/**
 * @param {object} config
 * @param {object} config.mpp          - MPP config: { currency, recipient, secretKey }
 * @param {object} config.x402         - x402 config: { payTo, network, facilitatorUrl, asset? }
 */
export function createDual402(config) {
  const mppx = Mppx.create({
    methods: [
      tempo.charge({
        currency: config.mpp.currency,
        recipient: config.mpp.recipient,
        ...(config.mpp.testnet && { testnet: true }),
      }),
    ],
    secretKey: config.mpp.secretKey,
  });

  const x402Asset =
    config.x402.asset ?? USDC_BY_NETWORK[config.x402.network];
  if (!x402Asset) {
    throw new Error(
      `No default USDC for network "${config.x402.network}". Set x402.asset explicitly.`
    );
  }

  return {
    _mppx: mppx,
    _x402Config: config.x402,
    _x402Asset: x402Asset,

    /**
     * Returns Express middleware that gates a route behind payment.
     * Accepts both x402 (PAYMENT-SIGNATURE) and MPP (Authorization: Payment).
     *
     * @param {object} opts - { amount: string, description?: string, discovery?: { info, schema } }
     *   discovery: optional CDP Bazaar `extensions.bazaar` block. Provide
     *     `{ info, schema }` and dual402 will surface it in the 402 challenge
     *     so x402scan, Bazaar, and agentic.market index a typed listing
     *     instead of a probe-only fallback entry.
     */
    charge(opts) {
      const { amount, description, discovery } = opts;

      // MPP charge handler — used for both credential verification and challenge generation
      const mppCharge = mppx.charge({ amount, description });

      // x402 amount in smallest unit (USDC = 6 decimals)
      const amountRaw = amountToAtomic(amount);

      // Stash amount for discovery to read
      const handler = async (req, res, next) => {
        try {
          const baseUrl =
            process.env.BASE_URL || `${req.protocol}://${req.get("host")}`;
          const resourceUrl = `${baseUrl}${req.originalUrl}`;
          const paymentRequirements = buildX402PaymentRequirements({
            amountRaw,
            asset: x402Asset,
            config: config.x402,
          });
          const paymentRequired = buildX402PaymentRequired({
            description,
            paymentRequirements,
            resourceUrl,
            discovery,
          });

          // ── Path 1: x402 credential ──
          // v2 header: PAYMENT-SIGNATURE, v1 legacy: X-PAYMENT
          const x402Sig =
            req.headers["payment-signature"] ?? req.headers["x-payment"];

          if (x402Sig) {
            let paymentPayload;
            try {
              paymentPayload = decodePaymentPayload(x402Sig);
            } catch (err) {
              console.warn(`[dual402] invalid x402 payload: ${err.message}`);
            }

            const verified = paymentPayload
              ? await x402Verify(
                  paymentPayload,
                  config.x402.facilitatorUrl,
                  paymentRequirements
                )
              : { isValid: false, invalidReason: "invalid_payload" };

            if (verified.isValid || verified.valid) {
              console.log(`[PAY] x402 verified amount=${amount} network=${config.x402.network}`);
              let settlement;
              try {
                settlement = await x402Settle(
                  paymentPayload,
                  config.x402.facilitatorUrl,
                  paymentRequirements
                );
              } catch (err) {
                console.warn(`[dual402] x402 settlement failed: ${err.message}`);
                settlement = {
                  success: false,
                  errorReason: "settlement_error",
                  errorMessage: err.message,
                };
              }
              res.setHeader(
                "PAYMENT-RESPONSE",
                Buffer.from(JSON.stringify(settlement)).toString("base64")
              );
              if (settlement.success === false) {
                res.setHeader(
                  "PAYMENT-REQUIRED",
                  Buffer.from(JSON.stringify(paymentRequired)).toString("base64")
                );
                return res.status(402).json({
                  error: "payment_settlement_failed",
                  reason: settlement.errorReason,
                  message: settlement.errorMessage,
                });
              }
              console.log(`[PAY] x402 settled amount=${amount}`);
              return next();
            }
            // Invalid x402 credential — fall through to 402
            console.warn(
              `[dual402] x402 verification failed: ${verified.invalidReason ?? verified.reason ?? "unknown"}`
            );
          }

          // ── Path 2 & 3: Delegate to mppx, inject x402 header on 402 ──
          //
          // Strategy: intercept mppx's res.status(402) call to add the
          // x402 PAYMENT-REQUIRED header before the response is sent.
          // This way mppx handles both MPP credentials and challenge
          // generation, and we just layer x402 on top of the 402.

          // Intercept: when mppx sets status 402, also add x402 header
          const origStatus = res.status.bind(res);
          res.status = (code) => {
            if (code === 402) {
              res.setHeader(
                "PAYMENT-REQUIRED",
                Buffer.from(JSON.stringify(paymentRequired)).toString("base64")
              );
            }
            return origStatus(code);
          };

          return mppCharge(req, res, (...args) => {
            console.log(`[PAY] mpp verified amount=${amount}`);
            next(...args);
          });
        } catch (err) {
          console.error("[dual402] middleware error:", err);
          next(err);
        }
      };
      handler._dualAmount = amount;
      return handler;
    },
  };
}

// ── x402 facilitator HTTP calls ─────────────────────────────────────────

function amountToAtomic(amount) {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`Invalid payment amount "${amount}"`);
  }
  return Math.round(parsed * 1e6).toString();
}

function buildX402PaymentRequirements({ amountRaw, asset, config }) {
  if (!config.payTo) {
    throw new Error("X402_PAYEE_ADDRESS or RECIPIENT_WALLET is required");
  }
  return {
    scheme: "exact",
    network: config.network,
    amount: amountRaw,
    asset,
    payTo: config.payTo,
    maxTimeoutSeconds: 300,
    extra: {
      name: "USDC",
      version: "2",
    },
  };
}

function buildX402PaymentRequired({
  description,
  paymentRequirements,
  resourceUrl,
  discovery,
}) {
  const payload = {
    x402Version: 2,
    accepts: [
      {
        ...paymentRequirements,
        extra: {
          ...paymentRequirements.extra,
          resourceUrl,
        },
      },
    ],
    resource: {
      url: resourceUrl,
      description: description || "",
      mimeType: "application/json",
    },
  };

  if (discovery && discovery.info && discovery.schema) {
    payload.extensions = {
      bazaar: {
        info: discovery.info,
        schema: discovery.schema,
      },
    };
  }

  return payload;
}

function decodePaymentPayload(paymentSignature) {
  return JSON.parse(Buffer.from(paymentSignature, "base64").toString("utf-8"));
}

function validateX402Payload(paymentPayload, paymentRequirements) {
  const accepted = paymentPayload.accepted ?? {};
  const paymentAmount = accepted.amount ?? paymentPayload.amount ?? paymentPayload.value;
  if (
    paymentAmount !== undefined &&
    String(paymentAmount) !== String(paymentRequirements.amount)
  ) {
    console.warn(
      `[dual402] x402 amount mismatch: got ${paymentAmount}, expected ${paymentRequirements.amount}`
    );
    return { isValid: false, invalidReason: "amount_mismatch" };
  }

  const paymentPayee = (accepted.payTo ?? paymentPayload.payTo ?? paymentPayload.to ?? "").toLowerCase();
  if (
    paymentPayee &&
    paymentPayee !== paymentRequirements.payTo.toLowerCase()
  ) {
    console.warn(
      `[dual402] x402 payee mismatch: got ${paymentPayee}, expected ${paymentRequirements.payTo}`
    );
    return { isValid: false, invalidReason: "payee_mismatch" };
  }

  const paymentNetwork = accepted.network ?? paymentPayload.network;
  if (paymentNetwork && paymentNetwork !== paymentRequirements.network) {
    console.warn(
      `[dual402] x402 network mismatch: got ${paymentNetwork}, expected ${paymentRequirements.network}`
    );
    return { isValid: false, invalidReason: "network_mismatch" };
  }

  const paymentAsset = (accepted.asset ?? paymentPayload.asset ?? "").toLowerCase();
  if (paymentAsset && paymentAsset !== paymentRequirements.asset.toLowerCase()) {
    console.warn(
      `[dual402] x402 asset mismatch: got ${paymentAsset}, expected ${paymentRequirements.asset}`
    );
    return { isValid: false, invalidReason: "asset_mismatch" };
  }

  return null;
}

async function x402Verify(paymentPayload, facilitatorUrl, paymentRequirements) {
  try {
    const localInvalid = validateX402Payload(paymentPayload, paymentRequirements);
    if (localInvalid) {
      return localInvalid;
    }

    const res = await facilitatorFetch(facilitatorUrl, "verify", {
      x402Version: 2,
      paymentPayload,
      paymentRequirements,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      console.warn(`[dual402] facilitator /verify ${res.status}: ${text}`);
      return { isValid: false, invalidReason: "facilitator_error" };
    }

    return await res.json();
  } catch (err) {
    console.error("[dual402] x402 verify error:", err.message);
    return { isValid: false, invalidReason: "verify_error" };
  }
}

async function x402Settle(paymentPayload, facilitatorUrl, paymentRequirements) {
  const res = await facilitatorFetch(facilitatorUrl, "settle", {
    x402Version: 2,
    paymentPayload,
    paymentRequirements,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`facilitator /settle ${res.status}: ${text}`);
  }

  return res.json();
}

async function facilitatorFetch(facilitatorUrl, path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FACILITATOR_TIMEOUT_MS);
  try {
    return await fetch(`${facilitatorUrl.replace(/\/+$/, "")}/${path}`, {
      method: "POST",
      headers: facilitatorHeaders(),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

function facilitatorHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (process.env.X402_FACILITATOR_BEARER_TOKEN) {
    headers.Authorization = `Bearer ${process.env.X402_FACILITATOR_BEARER_TOKEN}`;
  }
  return headers;
}

// ── Discovery (mounts /openapi.json and /.well-known/x402) ─────────────

/**
 * Build an AgentCash-compliant OpenAPI 3.1.0 spec.
 *
 * @param {import('express').Express} app
 * @param {object} dual - return value of createDual402()
 * @param {object} config - { info, serviceInfo, routes }
 *   route shape: { method, path, handler, summary, operationId, tags, parameters }
 */
export function dualDiscovery(app, dual, config) {
  const paths = {};

  for (const r of config.routes) {
    const amount = r.handler._dualAmount ?? "0.02";

    const operation = {
      operationId: r.operationId,
      summary: r.summary,
      tags: r.tags ?? [],
      "x-payment-info": {
        price: {
          mode: "fixed",
          currency: "USD",
          amount: parseFloat(amount).toFixed(6),
        },
        protocols: [
          { x402: {} },
          { mpp: { method: "", intent: "", currency: "" } },
        ],
      },
      responses: {
        200: {
          description: "Successful response",
          content: {
            "application/json": {
              schema: r.responseSchema ?? {
                type: "object",
                properties: {
                  results: { type: "array", items: { type: "object" } },
                },
                required: ["results"],
              },
            },
          },
        },
        402: { description: "Payment Required" },
      },
    };

    // Input schema — query parameters for GET routes
    if (r.parameters?.length) {
      operation.parameters = r.parameters;
    }
    if (r.requestBody) {
      operation.requestBody = r.requestBody;
    }

    paths[r.path] = { [r.method]: operation };
  }

  const spec = {
    openapi: "3.1.0",
    info: {
      title: config.info.title,
      version: config.info.version,
      description: config.info.description,
      ...(config.info["x-guidance"] && {
        "x-guidance": config.info["x-guidance"],
      }),
    },
    "x-discovery": {
      ownershipProofs: config.ownershipProofs ?? [],
    },
    paths,
  };

  if (config.serviceInfo) {
    spec["x-service-info"] = config.serviceInfo;
  }

  app.get("/openapi.json", (req, res) => {
    res.json(spec);
  });

  // /.well-known/x402 v1 — simple resource list
  app.get("/.well-known/x402", (req, res) => {
    res.json({
      version: 1,
      resources: config.routes.map(
        (r) => `${r.method.toUpperCase()} ${r.path}`
      ),
    });
  });
}
