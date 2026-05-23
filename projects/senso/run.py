import json, os, sys, urllib.request, urllib.error

API_BASE = "https://apiv2.senso.ai/api/v1"

def ingest_report(title: str, markdown: str) -> dict:
    api_key = os.environ.get("SENSO_API_KEY")
    if not api_key:
        raise RuntimeError("SENSO_API_KEY environment variable is not set")

    payload = json.dumps({"title": title, "text": markdown}).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/org/kb/raw",
        data=payload,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "senso-cli/0.11.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"API error ({e.code}): {body}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run.py <document.json>")
        print('  JSON format: { "title": "My Report", "text": "# Markdown..." }')
        print('  text can also be an array of strings, joined with blank lines')
        sys.exit(1)

    with open(sys.argv[1]) as f:
        doc = json.load(f)

    text = doc["text"]
    if isinstance(text, list):
        text = "\n".join(text)

    try:
        data = ingest_report(doc["title"], text)
        print(json.dumps(data, indent=2))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
