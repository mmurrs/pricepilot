# PricePilot — landing page

Static landing page for the PricePilot agent API. Built at the Agentic Engineering Hack (May 23, 2026).

## Deploying to Vercel

This folder is the Vercel project root. The rest of the hackathon repo is ignored at deploy time.

### One-time setup (CLI)

```bash
cd projects/pricepilot
npx vercel link        # link this folder to a Vercel project
npx vercel             # preview deploy
npx vercel --prod      # production deploy
```

When `vercel link` asks "in which directory is your code located?", accept the default (`./`). The folder you run from is the deploy root.

### One-time setup (Dashboard)

1. Vercel Dashboard → **Add New → Project** → import the GitHub repo `mmurrs/agenticenghack`.
2. **Root Directory:** `projects/pricepilot`.
3. **Framework Preset:** Other.
4. **Build Command / Output Directory:** leave blank (static HTML at the root).
5. Deploy.

Vercel will only build files inside `projects/pricepilot/`, so changes elsewhere in the repo won't trigger redeploys.

## Local preview

```bash
cd projects/pricepilot
python3 -m http.server 8088
open http://localhost:8088
```

## Files

- `index.html` — the landing page (single file, all styles inline)
- `vercel.json` — clean URLs + minimal security headers
- `.vercelignore` — excludes local cruft from deploys

## What this page advertises

- **Endpoint:** `POST /find_cheapest`
- **Price:** $0.05 per check
- **Coverage today:** Amazon (live). Walmart next, Target planned.
- **Payment:** x402 (Base USDC) or MPP (Tempo USDC), discoverable via AgentCash

The endpoint itself is not deployed from this folder — when the backend lands, point the curl/code examples in `index.html` at the real host.
